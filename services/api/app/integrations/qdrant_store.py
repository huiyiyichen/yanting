"""Qdrant 本地索引适配层。

关键约束（工程规范第 12.4、13.1 节）：
- Qdrant local 使用文件锁，同一目录**只允许一个进程**写入；
- 客户端必须**显式 close()**：依赖 `__del__` 收尾会在解释器关闭阶段因
  portalocker 导入 msvcrt 失败而打印堆栈并以非 0 退出（已实测）；
- 同一快照、同一过滤器下做 dense/sparse 各 top_k=8，用 RRF 合并；
- 权限与适用性过滤在**检索时**生效，不能只靠入库时过滤。
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from qdrant_client import QdrantClient, models

from app.integrations.embedding_provider import SparseVector
from app.logging_setup import get_logger

logger = get_logger(__name__)

DENSE_VECTOR_NAME = "dense"
SPARSE_VECTOR_NAME = "sparse"

# 检索模式：混合（RRF 融合）与两条单路，用于工程规范第 12.5 节的对照实验
RetrievalMode = Literal["hybrid", "dense_only", "sparse_only"]

# 片段 ID 的命名空间。Qdrant 只接受 uint64 或 UUID 作为 point id，
# 而本项目的 chunk_id 是可读字符串，因此用 UUIDv5 做**确定性**映射：
# 同一个 chunk_id 永远得到同一个 point id，重复导入不会产生副本。
CHUNK_ID_NAMESPACE = uuid.UUID("6f1d0f9a-8d3b-4c47-9d1e-0f5a7c2b8e31")


def to_point_id(chunk_id: str) -> str:
    return str(uuid.uuid5(CHUNK_ID_NAMESPACE, chunk_id))


@dataclass(slots=True)
class ScoredChunk:
    chunk_id: str
    score: float
    payload: dict[str, Any]


class QdrantKnowledgeStore:
    """每个快照一个 collection，便于整体替换与回滚。"""

    def __init__(self, path: Path, *, vector_dimension: int) -> None:
        self._path = path
        self._vector_dimension = vector_dimension
        self._client: QdrantClient | None = None

    # ----------------------------------------------------------- 生命周期

    def _ensure_client(self) -> QdrantClient:
        if self._client is None:
            self._path.mkdir(parents=True, exist_ok=True)
            self._client = QdrantClient(path=str(self._path))
        return self._client

    def close(self) -> None:
        if self._client is not None:
            try:
                self._client.close()
            finally:
                self._client = None

    def __enter__(self) -> QdrantKnowledgeStore:
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    # -------------------------------------------------------------- 集合

    @staticmethod
    def collection_name(snapshot_id: str) -> str:
        return f"kb_{snapshot_id}"

    def recreate_collection(self, collection: str) -> None:
        client = self._ensure_client()
        if client.collection_exists(collection):
            client.delete_collection(collection)
        client.create_collection(
            collection_name=collection,
            vectors_config={
                DENSE_VECTOR_NAME: models.VectorParams(
                    size=self._vector_dimension, distance=models.Distance.COSINE
                )
            },
            sparse_vectors_config={
                SPARSE_VECTOR_NAME: models.SparseVectorParams(
                    index=models.SparseIndexParams(on_disk=False)
                )
            },
        )

    def collection_exists(self, collection: str) -> bool:
        return self._ensure_client().collection_exists(collection)

    def drop_collection(self, collection: str) -> None:
        client = self._ensure_client()
        if client.collection_exists(collection):
            client.delete_collection(collection)

    def count(self, collection: str) -> int:
        client = self._ensure_client()
        if not client.collection_exists(collection):
            return 0
        return int(client.count(collection, exact=True).count)

    # -------------------------------------------------------------- 写入

    def upsert_chunks(
        self,
        collection: str,
        *,
        chunk_ids: list[str],
        dense: list[list[float]],
        sparse: list[SparseVector],
        payloads: list[dict[str, Any]],
        batch_size: int = 64,
    ) -> int:
        """写入片段。使用确定性 ID，重复导入同一片段不会复制。"""

        client = self._ensure_client()
        total = 0
        for start in range(0, len(chunk_ids), batch_size):
            end = start + batch_size
            points: list[models.PointStruct] = []
            for index in range(start, min(end, len(chunk_ids))):
                sparse_vector = sparse[index]
                points.append(
                    models.PointStruct(
                        id=to_point_id(chunk_ids[index]),
                        vector={
                            DENSE_VECTOR_NAME: dense[index],
                            SPARSE_VECTOR_NAME: models.SparseVector(
                                indices=sparse_vector.indices, values=sparse_vector.values
                            ),
                        },
                        payload=payloads[index],
                    )
                )
            client.upsert(collection_name=collection, points=points, wait=True)
            total += len(points)
        return total

    def delete_chunks(self, collection: str, chunk_ids: list[str]) -> None:
        """按 chunk_id 删除向量（用同一 UUIDv5 映射）。"""

        if not chunk_ids:
            return
        client = self._ensure_client()
        if not client.collection_exists(collection):
            return
        client.delete(
            collection_name=collection,
            points_selector=models.PointIdsList(
                points=[to_point_id(chunk_id) for chunk_id in chunk_ids]
            ),
            wait=True,
        )

    # -------------------------------------------------------------- 检索

    def hybrid_search(
        self,
        collection: str,
        *,
        dense_query: list[float],
        sparse_query: SparseVector,
        query_filter: models.Filter | None,
        top_k: int,
        limit: int,
        mode: RetrievalMode = "hybrid",
    ) -> list[ScoredChunk]:
        """按指定模式检索。

        - `hybrid`：dense/sparse 各取 top_k，用 Qdrant RRF 合并；
        - `dense_only` / `sparse_only`：单路 top_k，**不做融合**。

        单路模式用于工程规范第 12.5 节要求的对照实验（混合检索是否真的优于单路），
        不能因为「有 RRF」就假定混合一定更好。
        """

        client = self._ensure_client()
        if not client.collection_exists(collection):
            return []

        if mode in {"dense_only", "sparse_only"}:
            using = DENSE_VECTOR_NAME if mode == "dense_only" else SPARSE_VECTOR_NAME
            if mode == "sparse_only" and not sparse_query.indices:
                return []
            query: object = (
                dense_query
                if mode == "dense_only"
                else models.SparseVector(indices=sparse_query.indices, values=sparse_query.values)
            )
            points = client.query_points(
                collection_name=collection,
                query=query,
                using=using,
                limit=min(top_k, limit),
                query_filter=query_filter,
                with_payload=True,
            ).points
            return [
                ScoredChunk(
                    chunk_id=str((point.payload or {}).get("chunk_id") or point.id),
                    score=float(point.score),
                    payload=dict(point.payload or {}),
                )
                for point in points
            ]

        prefetch: list[models.Prefetch] = [
            models.Prefetch(
                query=dense_query,
                using=DENSE_VECTOR_NAME,
                limit=top_k,
                filter=query_filter,
            )
        ]
        if sparse_query.indices:
            prefetch.append(
                models.Prefetch(
                    query=models.SparseVector(
                        indices=sparse_query.indices, values=sparse_query.values
                    ),
                    using=SPARSE_VECTOR_NAME,
                    limit=top_k,
                    filter=query_filter,
                )
            )

        response = client.query_points(
            collection_name=collection,
            prefetch=prefetch,
            query=models.FusionQuery(fusion=models.Fusion.RRF),
            limit=limit,
            with_payload=True,
        )
        return [
            ScoredChunk(
                # 用 payload 里的可读 chunk_id，而不是 point id（后者是 UUIDv5 映射）
                chunk_id=str((point.payload or {}).get("chunk_id") or point.id),
                score=float(point.score),
                payload=dict(point.payload or {}),
            )
            for point in response.points
        ]

    def channel_ranks(
        self,
        collection: str,
        *,
        dense_query: list[float],
        sparse_query: SparseVector,
        query_filter: models.Filter | None,
        top_k: int,
        limit: int,
    ) -> dict[str, dict[str, int]]:
        """单独取两路排名，写入证据的 `channel_ranks`，便于复盘召回来源。

        返回的键是 point id（UUIDv5 映射结果），调用方用 `to_point_id(chunk_id)`
        对齐，避免为了可读性再取一次 payload。
        """

        client = self._ensure_client()
        if not client.collection_exists(collection):
            return {"dense": {}, "sparse": {}}

        ranks: dict[str, dict[str, int]] = {"dense": {}, "sparse": {}}
        dense_points = client.query_points(
            collection_name=collection,
            query=dense_query,
            using=DENSE_VECTOR_NAME,
            limit=top_k,
            query_filter=query_filter,
            with_payload=False,
        ).points
        for rank, point in enumerate(dense_points, start=1):
            ranks["dense"][str(point.id)] = rank

        if sparse_query.indices:
            sparse_points = client.query_points(
                collection_name=collection,
                query=models.SparseVector(indices=sparse_query.indices, values=sparse_query.values),
                using=SPARSE_VECTOR_NAME,
                limit=top_k,
                query_filter=query_filter,
                with_payload=False,
            ).points
            for rank, point in enumerate(sparse_points, start=1):
                ranks["sparse"][str(point.id)] = rank
        del limit
        return ranks
