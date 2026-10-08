from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient
from sqlalchemy import select

from app.config import Settings
from app.db import build_engine, build_session_factory
from app.domain.case_state.models import Base as CaseBase
from app.domain.consumer_service import models as _consumer_models  # noqa: F401
from app.domain.consumer_service.importer import import_business_workbook
from app.domain.consumer_service.models import WorkOrderRow
from app.domain.enums import ViewRole
from app.integrations.embedding_provider import MockEmbeddingProvider
from app.integrations.model_provider import MockModelProvider
from app.knowledge.models import Base as KnowledgeBase
from app.main import create_app
from app.runtime import RuntimeContext
from app.tools.registry import build_default_registry

OFFICIAL_SOURCE = Path(r"D:\下载\赛题 1：数据共情者-业务数据.xlsx")


def _support_headers() -> dict[str, str]:
    return {"X-Demo-View-Role": ViewRole.SUPPORT.value}


def _customer_headers() -> dict[str, str]:
    return {"X-Demo-View-Role": ViewRole.CUSTOMER.value}


def _build_client(tmp_path: Path) -> tuple[TestClient, Any]:
    engine = build_engine(
        Settings(database_url=f"sqlite+pysqlite:///{tmp_path / 'service-context.sqlite3'}")
    )
    CaseBase.metadata.create_all(engine)
    KnowledgeBase.metadata.create_all(engine)
    factory = build_session_factory(engine)
    seed_session = factory()
    result = import_business_workbook(seed_session, OFFICIAL_SOURCE, repo_root=tmp_path)
    seed_session.commit()
    seed_session.close()

    context = RuntimeContext(
        settings=Settings(),
        engine=engine,
        session_factory=factory,
        model_provider=MockModelProvider(),
        embedding_provider=MockEmbeddingProvider(reason="服务轨迹测试"),
        tool_registry=build_default_registry(),
    )
    app = create_app()

    @asynccontextmanager
    async def lifespan(_app: Any):
        _app.state.runtime = context
        yield
        context.close()

    app.router.lifespan_context = lifespan
    return TestClient(app), result


def test_service_context_links_all_five_work_order_types(tmp_path: Path) -> None:
    client, result = _build_client(tmp_path)
    with client:
        session = result
        # 每类工单都从真实批次中取一个会话，确认不是统一成一个案件类型。
        # 查询本身在独立的测试数据库中完成，API 回读在下一个用例覆盖。
        del session

    # 通过 HTTP 逐个读取真实批次里的样例会话。
    db_engine = build_engine(
        Settings(database_url=f"sqlite+pysqlite:///{tmp_path / 'service-context.sqlite3'}")
    )
    factory = build_session_factory(db_engine)
    db_session = factory()
    try:
        rows = list(
            db_session.scalars(select(WorkOrderRow).where(WorkOrderRow.batch_id == result.batch_id))
        )
        samples = {row.work_order_type: row.conversation_id for row in rows}
    finally:
        db_session.close()
        db_engine.dispose()

    client, _ = _build_client(tmp_path / "second")
    with client:
        for work_order_type in (
            "reship_exchange",
            "offline_payment",
            "logistics",
            "adverse_reaction",
            "return_refund",
        ):
            response = client.get(
                f"/api/support/conversations/{samples[work_order_type]}/service-context",
                headers=_support_headers(),
            )
            assert response.status_code == 200
            payload = response.json()
            assert {item["workOrderType"] for item in payload["workOrders"]} >= {work_order_type}
            order_ids = {item["orderId"] for item in payload["orders"]}
            for work_order in payload["workOrders"]:
                assert work_order["orderId"] in order_ids
                assert work_order["detail"]["workOrderId"] == work_order["workOrderId"]
            assert len(payload["timeline"]) == (
                len(payload["orders"])
                + len(payload["workOrders"])
                + sum(1 for item in payload["timeline"] if item["entityType"] == "message")
            )
            assert [item["occurredAt"] for item in payload["timeline"]] == sorted(
                item["occurredAt"] for item in payload["timeline"]
            )


def test_service_context_is_support_only_and_preserves_source_refs(tmp_path: Path) -> None:
    client, _result = _build_client(tmp_path)
    with client:
        support = client.get(
            "/api/support/conversations/S00001/service-context",
            headers=_support_headers(),
        )
        assert support.status_code == 200
        payload = support.json()
        assert payload["datasetId"] == "loreal-official-mock"
        assert payload["batchId"].startswith("loreal-")
        assert payload["conversationId"] == "S00001"
        assert payload["orders"]
        assert payload["workOrders"]
        assert payload["timeline"]
        assert "historyServices" in payload
        assert all({
            "conversationId", "firstAt", "lastAt", "latestCustomerMessage",
            "latestStaffMessage", "orderIds", "workOrderIds", "relation",
        } <= set(item) for item in payload["historyServices"])
        assert all(item["sourceRecordId"] for item in payload["timeline"])
        assert all(
            sum(value is not None for value in (item["message"], item["order"], item["workOrder"]))
            == 1
            for item in payload["timeline"]
        )
        assert "valuesJson" not in support.text

        customer = client.get(
            "/api/support/conversations/S00001/service-context",
            headers=_customer_headers(),
        )
        assert customer.status_code == 403
