from __future__ import annotations

import json
from pathlib import Path

import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.config import Settings
from app.db import build_engine, build_session_factory
from app.domain.case_state.models import Base as CaseBase
from app.domain.consumer_service import models as _consumer_models  # noqa: F401
from app.domain.consumer_service.importer import import_business_workbook
from app.domain.consumer_service.mapping import DATASET_ID
from app.domain.consumer_service.models import (
    DatasetRow,
    ImportBatchRow,
    ServiceMessageRow,
    ServiceOrderRow,
    SourceRecordRow,
    WorkOrderRow,
)

OFFICIAL_SOURCE = Path(r"D:\下载\赛题 1：数据共情者-业务数据.xlsx")


@pytest.fixture
def session(tmp_path: Path):
    db_path = tmp_path / "consumer-service.sqlite3"
    engine = build_engine(Settings(database_url=f"sqlite+pysqlite:///{db_path}"))
    CaseBase.metadata.create_all(engine)
    factory = build_session_factory(engine)
    db_session = factory()
    try:
        yield db_session, tmp_path
    finally:
        db_session.close()
        engine.dispose()


@pytest.mark.slow
def test_official_workbook_import_is_idempotent_and_complete(session) -> None:
    db_session, repo_root = session
    if not OFFICIAL_SOURCE.exists():
        pytest.skip("官方 Excel 不在当前机器")

    first = import_business_workbook(db_session, OFFICIAL_SOURCE, repo_root=repo_root)
    db_session.commit()
    second = import_business_workbook(db_session, OFFICIAL_SOURCE, repo_root=repo_root)

    assert first.reused is False
    assert second.reused is True
    assert first.batch_id == second.batch_id
    assert first.counts == {
        "sheets": 7,
        "messages": 998,
        "orders": 113,
        "workOrders": 80,
        "conversations": 138,
        "imageMessages": 29,
    }
    assert first.report["qualityStatus"] == "passed"
    assert first.report["issues"] == []
    assert Path(first.snapshot_path).is_file()
    assert Path(first.report_path).is_file()

    assert db_session.query(ImportBatchRow).count() == 1
    assert db_session.query(SourceRecordRow).count() == 1191
    assert db_session.query(ServiceMessageRow).count() == 998
    assert db_session.query(ServiceOrderRow).count() == 113
    assert db_session.query(WorkOrderRow).count() == 80
    dataset = db_session.get(DatasetRow, DATASET_ID)
    assert dataset is not None
    assert dataset.active_batch_id == first.batch_id

    report = json.loads(Path(first.report_path).read_text(encoding="utf-8"))
    assert report["source"]["sha256"] == first.source_sha256
    assert report["imageReferences"] == {"count": 29, "withPath": 29}


@pytest.mark.slow
def test_imported_facts_are_database_immutable(session) -> None:
    db_session, repo_root = session
    if not OFFICIAL_SOURCE.exists():
        pytest.skip("官方 Excel 不在当前机器")

    result = import_business_workbook(db_session, OFFICIAL_SOURCE, repo_root=repo_root)
    db_session.commit()
    order = db_session.scalar(select(ServiceOrderRow))
    assert order is not None
    original_amount = order.paid_amount_minor
    order.paid_amount_minor = (original_amount or 0) + 1

    with pytest.raises(IntegrityError):
        db_session.commit()
    db_session.rollback()

    fresh_order = db_session.get(ServiceOrderRow, order.record_id)
    assert fresh_order is not None
    assert fresh_order.paid_amount_minor == original_amount
    assert result.report["qualityStatus"] == "passed"
