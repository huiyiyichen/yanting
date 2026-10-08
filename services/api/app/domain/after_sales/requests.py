"""售后申请草稿与 Demo 人工确认。

关键规则（PRD 第 4.4 节）：
- 确认人：售后客服（Demo 由项目人员扮演），不接入真实坐席；
- **已批准只表示人工批准了申请草稿，不表示真实业务系统已完成**；
- 批准绑定 `request_id + request_revision + payload_hash`：
  内容或依据变更后必须使旧确认失效；
- 重复提交、刷新和恢复不生成重复申请；
- 未操作时始终待确认，**不设置处理时限、超时状态或自动升级**。
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.domain.case_state.models import AfterSalesRequestRow, CaseRow, new_id
from app.domain.case_state.state_machine import (
    assert_request_action_allowed,
    assert_request_transition,
)
from app.domain.enums import RequestStatus, RequestType
from app.errors import ConflictError, NotFoundError

# 生成草稿前必须已确认的最小事实（PRD 第 3.4 节）
REQUIRED_FACTS_FOR_DRAFT = ("product_model", "country_code")


@dataclass(frozen=True, slots=True)
class DraftOutcome:
    request_id: str | None
    request_status: str
    request_revision: int
    created: bool
    message: str
    error_code: str | None = None


@dataclass(frozen=True, slots=True)
class ReviewOutcome:
    request_id: str
    request_status: str
    request_revision: int
    action: str
    changed: bool
    message: str
    error_code: str | None = None


def compute_payload_hash(payload: dict[str, object]) -> str:
    """申请内容摘要。用于让旧确认在内容变化后失效。"""

    canonical = json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


class RequestRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    # ------------------------------------------------------------------ 查询

    def get(self, request_id: str) -> AfterSalesRequestRow:
        row = self._session.get(AfterSalesRequestRow, request_id)
        if row is None:
            raise NotFoundError(f"申请不存在：{request_id}")
        return row

    def find_by_idempotency_key(self, key: str) -> AfterSalesRequestRow | None:
        return self._session.execute(
            select(AfterSalesRequestRow).where(AfterSalesRequestRow.idempotency_key == key)
        ).scalar_one_or_none()

    def list_for_case(self, case_id: str) -> list[AfterSalesRequestRow]:
        return list(
            self._session.execute(
                select(AfterSalesRequestRow)
                .where(AfterSalesRequestRow.case_id == case_id)
                .order_by(AfterSalesRequestRow.created_at.asc())
            ).scalars()
        )

    def list_pending(self) -> list[AfterSalesRequestRow]:
        """待人工确认队列。不含任何超时排序或升级逻辑。"""

        return list(
            self._session.execute(
                select(AfterSalesRequestRow)
                .where(
                    AfterSalesRequestRow.request_status == RequestStatus.PENDING_CONFIRMATION.value
                )
                .order_by(AfterSalesRequestRow.created_at.asc())
            ).scalars()
        )

    # ------------------------------------------------------------ 生成草稿

    def create_draft(
        self,
        *,
        case_id: str,
        request_type: RequestType,
        summary: str,
        payload: dict[str, object],
        idempotency_key: str | None = None,
    ) -> DraftOutcome:
        """生成草稿并进入待确认；缺少必要事实时拒绝生成。"""

        case = self._session.get(CaseRow, case_id)
        if case is None:
            return DraftOutcome(
                request_id=None,
                request_status=RequestStatus.DRAFT.value,
                request_revision=0,
                created=False,
                message=f"案件不存在：{case_id}",
                error_code="not_found",
            )

        missing = [field for field in REQUIRED_FACTS_FOR_DRAFT if not getattr(case, field, None)]
        if missing:
            return DraftOutcome(
                request_id=None,
                request_status=RequestStatus.DRAFT.value,
                request_revision=0,
                created=False,
                message=(
                    "生成申请草稿前必须先确认：" + "、".join(missing) + "；"
                    "当前信息不足，不能进入高风险办理。"
                ),
                error_code="conflict",
            )

        body = {
            "caseId": case_id,
            "requestType": request_type.value,
            "summary": summary,
            "productModel": case.product_model,
            "countryCode": case.country_code,
            "purchaseChannel": case.purchase_channel,
            "warrantyStatus": case.warranty_status,
            "dealerAuthorizationStatus": case.dealer_authorization_status,
            "payload": payload,
        }
        payload_hash = compute_payload_hash(body)
        key = idempotency_key or f"{case_id}|{request_type.value}|{payload_hash}"

        existing = self.find_by_idempotency_key(key)
        if existing is not None:
            return DraftOutcome(
                request_id=existing.request_id,
                request_status=existing.request_status,
                request_revision=existing.request_revision,
                created=False,
                message="相同幂等键的申请已存在，返回原申请（未重复生成）",
            )

        # 同一案件同一类型若已有未结申请，不重复创建
        for row in self.list_for_case(case_id):
            if row.request_type == request_type.value and row.request_status in {
                RequestStatus.PENDING_CONFIRMATION.value,
                RequestStatus.NEEDS_INFORMATION.value,
            }:
                return DraftOutcome(
                    request_id=row.request_id,
                    request_status=row.request_status,
                    request_revision=row.request_revision,
                    created=False,
                    message="该案件已有同类未结申请，返回原申请",
                )

        row = AfterSalesRequestRow(
            request_id=new_id("req"),
            case_id=case_id,
            conversation_id=case.conversation_id,
            request_type=request_type.value,
            # 草稿先落库，再提交进入待确认
            request_status=RequestStatus.DRAFT.value,
            request_revision=1,
            payload_hash=payload_hash,
            request_payload_json=json.dumps(body, ensure_ascii=False),
            idempotency_key=key,
        )
        self._session.add(row)
        self._session.flush()

        # 生成后立即提交待确认：本期没有「仅保存草稿不提交」的用户路径
        self.submit(row.request_id)
        return DraftOutcome(
            request_id=row.request_id,
            request_status=row.request_status,
            request_revision=row.request_revision,
            created=True,
            message="申请草稿已生成并进入待人工确认",
        )

    # ------------------------------------------------------------ 状态流转

    def submit(self, request_id: str) -> AfterSalesRequestRow:
        row = self.get(request_id)
        current = RequestStatus(row.request_status)
        assert_request_transition(current, RequestStatus.PENDING_CONFIRMATION)
        row.request_status = RequestStatus.PENDING_CONFIRMATION.value
        self._session.flush()
        return row

    def review(
        self,
        request_id: str,
        *,
        action: str,
        reviewer_role: str,
        reason: str | None = None,
        reason_text: str | None = None,
        expected_revision: int | None = None,
        expected_payload_hash: str | None = None,
    ) -> ReviewOutcome:
        """人工确认。批准/拒绝/退回补充。

        竞态保护：
        - `expected_revision` / `expected_payload_hash` 与当前值不符时抛冲突，
          防止「旧版本的批准」生效（AC-29）；
        - 重复执行同一动作（申请已是终态）抛冲突，不重复记账；
        - 拒绝与退回**必须**给出原因。
        """

        row = self.get(request_id)
        current = RequestStatus(row.request_status)

        if expected_revision is not None and expected_revision != row.request_revision:
            raise ConflictError(
                "申请版本已变化，旧确认结果失效",
                detail=(
                    f"期望版本 {expected_revision}，当前版本 {row.request_revision}；"
                    "请刷新后重新确认"
                ),
            )
        if expected_payload_hash is not None and expected_payload_hash != row.payload_hash:
            raise ConflictError(
                "申请内容已变化，旧确认结果失效",
                detail="请基于最新内容重新确认",
            )

        assert_request_action_allowed(current, action)

        if action in {"reject", "request_information"} and not reason:
            raise ConflictError(
                "拒绝或退回补充必须给出固定原因",
                detail="reason 不能为空",
            )

        target = {
            "approve": RequestStatus.APPROVED,
            "reject": RequestStatus.REJECTED,
            "request_information": RequestStatus.NEEDS_INFORMATION,
        }[action]

        row.request_status = target.value
        row.reviewer_role = reviewer_role
        row.reviewed_at = datetime.now(UTC)
        row.review_action = action
        row.review_reason = reason
        row.review_reason_text = reason_text
        if target is RequestStatus.APPROVED:
            # 记录生效的版本，重复批准同一版本不再记账
            row.approved_revision = row.request_revision
        self._session.flush()

        return ReviewOutcome(
            request_id=row.request_id,
            request_status=row.request_status,
            request_revision=row.request_revision,
            action=action,
            changed=True,
            message=(
                f"申请已{ {'approve': '批准', 'reject': '拒绝', 'request_information': '退回补充'}[action] }"
                "；该结论仅表示 Demo 内的人工确认，不代表真实业务已完成"
            ),
        )

    def revise(
        self, request_id: str, *, payload: dict[str, object], summary: str | None = None
    ) -> AfterSalesRequestRow:
        """申请内容变更：递增版本并使旧批准失效。"""

        row = self.get(request_id)
        current = RequestStatus(row.request_status)
        if current is RequestStatus.APPROVED:
            raise ConflictError("已批准的申请不能就地修改；请新建申请")

        body = json.loads(row.request_payload_json)
        body["payload"] = payload
        if summary:
            body["summary"] = summary
        row.request_payload_json = json.dumps(body, ensure_ascii=False)
        row.payload_hash = compute_payload_hash(body)
        row.request_revision += 1
        # 内容变化后旧确认失效：回到草稿并重新提交
        if current in {RequestStatus.NEEDS_INFORMATION, RequestStatus.PENDING_CONFIRMATION}:
            row.request_status = RequestStatus.PENDING_CONFIRMATION.value
        row.approved_revision = None
        self._session.flush()
        return row
