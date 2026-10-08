import tempfile
from importlib.metadata import version

from qdrant_client import QdrantClient, models

print("qdrant-client:", version("qdrant-client"))
c = QdrantClient(path=tempfile.mkdtemp())
c.create_collection(
    collection_name="probe",
    vectors_config={"dense": models.VectorParams(size=8, distance=models.Distance.COSINE)},
    sparse_vectors_config={"sparse": models.SparseVectorParams()},
)
c.upsert(
    "probe",
    points=[
        models.PointStruct(
            id=1,
            vector={
                "dense": [1, 0, 0, 0, 0, 0, 0, 0],
                "sparse": models.SparseVector(indices=[1, 5, 9], values=[0.5, 0.3, 0.2]),
            },
            payload={"t": "a"},
        ),
        models.PointStruct(
            id=2,
            vector={
                "dense": [0, 1, 0, 0, 0, 0, 0, 0],
                "sparse": models.SparseVector(indices=[2, 5], values=[0.7, 0.1]),
            },
            payload={"t": "b"},
        ),
        models.PointStruct(
            id=3,
            vector={
                "dense": [0.7, 0.7, 0, 0, 0, 0, 0, 0],
                "sparse": models.SparseVector(indices=[1, 2], values=[0.4, 0.6]),
            },
            payload={"t": "c"},
        ),
    ],
    wait=True,
)
res = c.query_points(
    "probe",
    prefetch=[
        models.Prefetch(query=[0.9, 0.1, 0, 0, 0, 0, 0, 0], using="dense", limit=8),
        models.Prefetch(
            query=models.SparseVector(indices=[1, 2], values=[0.6, 0.5]), using="sparse", limit=8
        ),
    ],
    query=models.FusionQuery(fusion=models.Fusion.RRF),
    limit=5,
    with_payload=True,
).points
print("RRF hybrid OK ->", [(p.id, round(p.score, 5), p.payload["t"]) for p in res])
res2 = c.query_points(
    "probe",
    query=models.SparseVector(indices=[1], values=[1.0]),
    using="sparse",
    query_filter=models.Filter(
        must=[models.FieldCondition(key="t", match=models.MatchValue(value="a"))]
    ),
    limit=5,
).points
print("payload filter OK ->", [p.id for p in res2])
c.delete(
    "probe",
    points_selector=models.FilterSelector(
        filter=models.Filter(must=[models.FieldCondition(key="t", match=models.MatchValue(value="b"))])
    ),
)
print("count after delete:", c.count("probe").count)
print("PROBE PASS")
