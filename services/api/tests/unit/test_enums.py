"""枚举与契约一致性测试。

覆盖 AC-04 的基础：受限字段枚举必须拒绝自由生成类别，只有声明 unknown 的
分类字段可以归为未知。
"""

from __future__ import annotations

import pytest

from app.domain.enums import (
    CaseStatus,
    ComplaintRisk,
    CustomerIntent,
    EmotionLevel,
    FaultPart,
    FaultType,
    KnowledgeHitStatus,
    RequestStatus,
    ToolName,
    enum_values,
)

REQUIRED_ENUMS = {
    "caseStatus",
    "conversationStage",
    "requestType",
    "requestStatus",
    "toolName",
    "toolResultStatus",
    "riskLevel",
    "knowledgeSourceType",
    "customerIntent",
    "faultType",
    "faultPart",
    "emotionLevel",
    "complaintRisk",
    "ratingStatus",
    "warrantyStatus",
    "dealerAuthorizationStatus",
    "knowledgeHitStatus",
    "troubleshootingResult",
}

# 工程规范第 4.2 节明确禁止的人工超时状态
FORBIDDEN_REQUEST_STATUS = {"timeout", "expired", "auto_approved", "auto_rejected", "escalated"}


def test_required_enums_are_exported() -> None:
    exported = set(enum_values())
    missing = REQUIRED_ENUMS - exported
    assert not missing, f"缺少规范要求固定的枚举：{sorted(missing)}"


def test_machine_values_are_snake_case_ascii() -> None:
    for name, mapping in enum_values().items():
        if name == "locale":
            # 国家/地区使用 ISO 3166-1 alpha-2 大写代码（CN/US/DE），
            # 属于外来标准标识，不套用 snake_case 规则。
            assert all(value.isalpha() and value.isupper() for value in mapping)
            continue
        for value in mapping:
            assert value == value.lower(), f"{name}.{value} 必须是小写机器值"
            assert value.replace("_", "").isalnum(), f"{name}.{value} 必须是 snake_case"


def test_every_enum_value_has_chinese_label() -> None:
    for name, mapping in enum_values().items():
        for value, label in mapping.items():
            assert label and label.strip(), f"{name}.{value} 缺少展示文案"


def test_request_status_has_no_manual_timeout_state() -> None:
    values = set(RequestStatus.values())
    assert not (values & FORBIDDEN_REQUEST_STATUS)
    assert values == {"draft", "pending_confirmation", "approved", "rejected", "needs_information"}


def test_emotion_and_complaint_risk_are_separate() -> None:
    assert set(EmotionLevel.values()) == {"calm", "dissatisfied", "angry", "unknown"}
    assert set(ComplaintRisk.values()) == {"flagged", "not_flagged", "unknown"}
    # 投诉风险不能混入情绪等级
    assert not (set(EmotionLevel.values()) & set(ComplaintRisk.values()) - {"unknown"})


def test_knowledge_hit_status_excludes_query_failure() -> None:
    values = set(KnowledgeHitStatus.values())
    assert values == {"sufficient", "insufficient", "not_found", "conflicting"}
    # 工具失败由 tool_result_status 表达，不能伪装成未命中
    assert "query_failed" not in values


def test_strict_parse_rejects_unknown_values() -> None:
    with pytest.raises(ValueError, match="不接受取值"):
        CaseStatus.parse("finished")
    with pytest.raises(ValueError, match="不接受取值"):
        ToolName.parse("delete_order")
    with pytest.raises(ValueError, match="不接受取值"):
        RequestStatus.parse("timeout")


def test_parse_or_unknown_only_for_classification_fields() -> None:
    assert CustomerIntent.parse_or_unknown("这不是任何意图") is CustomerIntent.UNKNOWN
    assert CustomerIntent.parse_or_unknown("refund") is CustomerIntent.REFUND
    # 非分类字段不允许兜底
    with pytest.raises(TypeError, match="未声明 unknown"):
        CaseStatus.parse_or_unknown("whatever")


def test_no_free_text_substitutes_unknown() -> None:
    """允许未知的分类字段必须显式声明 unknown，不能用自由文本代替。"""

    for enum_cls in (CustomerIntent, EmotionLevel, ComplaintRisk, FaultType, FaultPart):
        assert "unknown" in enum_cls.values(), f"{enum_cls.__name__} 必须显式声明 unknown"


def test_knowledge_hit_status_uses_empty_for_not_yet_retrieved() -> None:
    """尚未检索时该字段为空，而不是 unknown —— 这是 PRD 第 5.2 节的明确要求。"""

    assert "unknown" not in KnowledgeHitStatus.values()
