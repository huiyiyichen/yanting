"""Isolated UI validation server: official fictional data, no live model calls."""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import sys
from contextlib import asynccontextmanager
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "services/api"))

from app.config import Settings  # noqa: E402
from app.db import build_engine, build_session_factory  # noqa: E402
from app.domain.consumer_service.importer import import_business_workbook  # noqa: E402
from app.domain.consumer_service.risk_rules import run_risk_monitor  # noqa: E402
from app.integrations.embedding_provider import MockEmbeddingProvider  # noqa: E402
from app.integrations.model_provider import MockModelProvider  # noqa: E402
from app.main import create_app  # noqa: E402
from app.runtime import RuntimeContext  # noqa: E402


def main() -> None:
    import uvicorn

    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=8001)
    parser.add_argument("--runtime", default="data/runtime/ticket-ops-validation")
    args = parser.parse_args()
    root = (REPO / args.runtime).resolve()
    runtime_root = (REPO / "data/runtime").resolve()
    if root == runtime_root or runtime_root not in root.parents:
        parser.error("Validation directory must be a child of data/runtime")
    root.mkdir(parents=True, exist_ok=True)
    settings = Settings(
        run_mode="mock", database_url=f"sqlite+pysqlite:///{(root / 'fixture.sqlite3').as_posix()}",
        runtime_dir=str(root), qdrant_path=str(root / "qdrant"),
        llm_base_url="", llm_api_key="", llm_model="",
    )
    engine = build_engine(settings)
    context = RuntimeContext(
        settings=settings, engine=engine, session_factory=build_session_factory(engine),
        model_provider=MockModelProvider(), embedding_provider=MockEmbeddingProvider(reason="UI validation"),
    )
    context.ensure_schema()
    source = REPO / "data/source/loreal-official-mock/source-b5ac027e863c5580dab39c8f459e4698d65e9fbec29832c9915448f2087307b7.xlsx"
    with context.new_session() as session:
        import_business_workbook(session, source, repo_root=root)
        session.commit()
    app = create_app()

    @asynccontextmanager
    async def lifespan(app):
        app.state.runtime = context
        monitor = asyncio.create_task(run_risk_monitor(context))
        try:
            yield
        finally:
            monitor.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await monitor
            context.close()

    app.router.lifespan_context = lifespan
    print("Isolated service-desk fixture; mock runtime; no automatic reception worker.", flush=True)
    uvicorn.run(app, host="127.0.0.1", port=args.port)


if __name__ == "__main__":
    main()
