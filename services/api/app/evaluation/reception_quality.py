"""Checks and receipts for prospective dialogue evaluation, not semantic truth."""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from statistics import median

from sqlalchemy import select

from app.config import Settings
from app.domain.consumer_service.models import AssistantRunRow, ImportBatchRow, SourceRecordRow
from app.evaluation.reception_runtime import configured_prompts, readonly_configuration
from app.knowledge.models import KnowledgeDocumentRow
from app.knowledge.repository import KnowledgeRepository


def conversation_for_turn(api, sessions: dict, turn: dict, run_key: str, case_id: str) -> str:
    name = turn.get("session", "default")
    scope = turn.get("customerScope", "default")
    if name in sessions and sessions[name]["customerScope"] != scope:
        raise ValueError("Session customer scope cannot change within a task")
    if name not in sessions:
        created = api("POST", "/api/customer/conversations", "customer", {
            "customerId": f"QUALITY-{run_key}-{case_id}-{scope}",
        })
        sessions[name] = {"conversationId": created["conversationId"], "customerScope": scope}
    return sessions[name]["conversationId"]


def prior_case_exposure(directory: Path, fixture_hash: str) -> list[str]:
    exposed = set()
    for path in directory.glob("loreal-reception-quality-*.json"):
        report = json.loads(path.read_text(encoding="utf-8"))
        if report.get("caseSha256") == fixture_hash and "configurationBefore" in report:
            exposed.update(case["id"] for case in report["cases"] if case.get("turns"))
    return sorted(exposed)


def configuration_receipt(settings: Settings) -> dict:
    with readonly_configuration(settings) as session:
        if session is None:
            raise ValueError("The configured main database is missing")
        sources = list(session.scalars(select(SourceRecordRow).order_by(SourceRecordRow.record_id)))
        source_digest = hashlib.sha256(json.dumps(
            [(row.record_id, row.row_sha256) for row in sources],
        ).encode()).hexdigest()
        snapshot = KnowledgeRepository(session).get_active_snapshot()
        batches = list(session.scalars(select(ImportBatchRow)))
        receipt = {
            "sourceRecords": len(sources), "sourceRecordDigest": source_digest,
            "sourceFileHashes": sorted({row.source_sha256 for row in batches}),
            "knowledgeSnapshotId": snapshot.snapshot_id if snapshot else None,
            "knowledgeDocuments": [{
                "id": row.document_id, "version": row.document_version,
                "hash": row.content_hash, "enabled": row.enabled,
            } for row in session.scalars(select(KnowledgeDocumentRow).where(
                KnowledgeDocumentRow.knowledge_base_id.like("loreal-%"),
            ).order_by(KnowledgeDocumentRow.document_pk))],
        }
    receipt["prompts"] = [{
        "purpose": item.purpose, "binding": item.binding,
        "templateId": item.template["template_id"] if item.template else None,
        "revision": item.template["revision"] if item.template else None,
        "contentHash": hashlib.sha256(item.template["content"].encode()).hexdigest()
        if item.template else None,
    } for item in configured_prompts(settings)]
    return receipt


def recorded_runs(settings: Settings, conversation_id: str) -> list[dict]:
    with readonly_configuration(settings) as session:
        if session is None:
            raise ValueError("The configured main database is missing")
        return [{
            "runId": row.run_id, "status": row.status, "model": row.model_id,
            "isMock": row.is_mock, "errorCode": row.error_code,
            "usage": json.loads(row.usage_json), "steps": json.loads(row.trace_json),
        } for row in session.scalars(select(AssistantRunRow).where(
            AssistantRunRow.conversation_id == conversation_id,
        ).order_by(AssistantRunRow.created_at, AssistantRunRow.run_id))]


def turn_checks(spec: dict, observed: dict) -> dict[str, bool]:
    replies = observed["reply"]
    assistant = observed.get("assistant")
    checks = {
        "mode": observed["mode"] == spec["expectedMode"],
        "newModelReply": bool(replies) if spec["expectModelReply"] else not replies,
    }
    if spec["expectModelReply"]:
        checks["nonMock"] = bool(assistant) and assistant.get("isMock") is False
        checks["freshResult"] = bool(assistant) and assistant.get("stale") is False
    for phrase in spec.get("replyRequired", []):
        checks[f"replyContains:{phrase}"] = any(
            bool(re.search(r"(?<![\d.])" + re.escape(phrase) + r"(?:\.0+)?(?![\d.])", reply))
            if phrase.isdigit() else phrase in reply
            for reply in replies
        )
    for phrase in spec.get("replyForbidden", []):
        checks[f"replyExcludes:{phrase}"] = all(phrase not in reply for reply in replies)
    memory = observed.get("memory", {}).get("items", [])
    for index, criterion in enumerate(spec.get("memoryCriteria", []), 1):
        checks[f"quotedMemory:{index}"] = any(
            item["category"] == criterion["category"]
            and any(phrase in item["quote"] for phrase in criterion["alternatives"])
            for item in memory
        ) and observed.get("memory", {}).get("verified") is True
    for phrase in spec.get("forbiddenMemoryText", []):
        checks[f"memoryExcludes:{phrase}"] = all(phrase not in item["quote"] for item in memory)
    for phrase in spec.get("forbiddenSourceText", []):
        sources = observed.get("memory", {}).get("sources", []) + (
            assistant.get("groundingSources", []) if assistant else []
        )
        checks[f"sourcesExcludes:{phrase}"] = all(phrase not in source["text"] for source in sources)
    if spec.get("breakpointExpectation") == "none":
        assessment = observed.get("breakpointAssessment", {})
        checks["currentBreakpointAnalysis"] = assessment.get("analyzed") is True and assessment.get("stale") is False
        checks["noServiceBreakpoint"] = not assessment.get("findings", [])
    return checks


def summarize_cases(cases: list[dict]) -> dict:
    turns = [turn for case in cases for turn in case.get("turns", [])]
    checked = [turn for turn in turns if "checks" in turn]
    runs = [run for case in cases for run in case.get("runHistory", [])]
    latencies = [turn["elapsedSeconds"] for turn in turns if "elapsedSeconds" in turn]
    usage = [run["usage"] for run in runs]
    return {
        "caseCount": len(cases), "turnsAttempted": len(turns), "turnsChecked": len(checked),
        "turnsAllMechanicalChecks": sum(all(turn["checks"].values()) for turn in checked),
        "casesAllMechanicalChecks": sum(
            len(case.get("turns", [])) == case.get("plannedTurns")
            and all("checks" in turn and all(turn["checks"].values()) for turn in case.get("turns", []))
            for case in cases
        ),
        "apiErrors": sum("error" in turn for turn in turns),
        "modelRuns": len(runs), "failedRuns": sum(run["status"] == "failed" for run in runs),
        "modelCalls": sum(item.get("calls", 0) for item in usage),
        "promptTokens": sum(item["promptTokens"] for item in usage)
        if all(item.get("promptTokens") is not None for item in usage) else None,
        "completionTokens": sum(item["completionTokens"] for item in usage)
        if all(item.get("completionTokens") is not None for item in usage) else None,
        "inputCharacters": sum(item["inputCharacters"] for item in usage)
        if all(item.get("inputCharacters") is not None for item in usage) else None,
        "usageUnknownRuns": sum(item.get("promptTokens") is None or item.get("completionTokens") is None
                                for item in usage),
        "medianSystemSeconds": round(median(latencies), 3) if latencies else None,
        "maxSystemSeconds": max(latencies) if latencies else None,
        "semanticReviewStatus": "pending_separate_review",
    }


def blind_review_packet(fixture: dict, cases: list[dict]) -> dict:
    return {
        "scope": "AI_or_human_review_of_task_dialogue_not_generator_self_verification",
        "rubric": fixture.get("rubric", {}),
        "rubricStatus": "provided" if fixture.get("rubric") else "missing_no_numeric_score",
        "cases": [{
            "id": case["id"], "topic": case["topic"],
            "goals": case["semanticGoals"], "businessFacts": case.get("businessFacts", {}),
            "turns": [{
                "customer": turn["customer"], "reply": turn.get("reply", []),
                "session": turn.get("session", "default"),
                "customerScope": turn.get("customerScope", "default"),
                "observedMode": turn.get("mode"),
                "expectedHandoffOnly": not turn["expectModelReply"],
                "memory": turn.get("memory", {}).get("items", []),
                "serviceBreakpoints": turn.get("breakpointAssessment", {}).get("findings", []),
            } for turn in case.get("turns", [])],
        } for case in cases],
        "limitations": [
            "Prospective engineered tasks do not establish independent expert truth.",
            "AI reviewers must identify themselves as AI; no human productivity baseline exists.",
            "Generator validation flags, claims and mechanical check outcomes are intentionally omitted.",
        ],
    }
