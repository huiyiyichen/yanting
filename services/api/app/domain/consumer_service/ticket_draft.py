"""工作台内建工单预填（改进方案 P1-4）。

规则抽取，不调用模型：只读消费者本人发言，每个预填字段附原话来源；无依据的字段留空。
预填结果只填入表单，客服确认后才创建本地工单，不执行任何真实售后动作。
"""

from __future__ import annotations

import re

from app.schemas.base import ApiModel

TYPE_RULES: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("adverse_reaction", re.compile(r"过敏|红肿|肿了|脸肿|发红|泛红|红了|又红|脸红|有点红|很红|刺痛|灼热|起疹|疹子|长痘|爆痘|脱皮|瘙痒|发痒|又痒|就医|医院|皮肤科")),
    ("reship_exchange", re.compile(r"空包|空的|漏发|少发|错发|发错|破损|压坏|漏液|换货|补发")),
    ("offline_payment", re.compile(r"退款[^，。！？]{0,12}(?:没|未)到|没到账|未到账|打款|补款|差价|补偿")),
    ("return_refund", re.compile(r"退货|仅退款|退回去")),
    ("logistics", re.compile(r"物流|快递|没动|不动|没收到|未收到|签收|派送|揽收")),
)
AREA = re.compile(r"全脸|两颊|脸颊|额头|下巴|鼻子|鼻翼|眼周|眼睛|嘴角|唇周|脖子|颈部|T区|手背|脸")
ONSET = re.compile(r"(?:用|敷|涂)(?:完|了)?[^，。！？]{0,4}?(\d+\s*(?:分钟|小时|天))|(\d+\s*(?:分钟|小时|天))(?:后|之后|以后)|(前天|昨天|当天|今天)")
BATCH = re.compile(r"(?:批次|批号)(?:号)?\s*[:：是为]?\s*([A-Za-z0-9]{3,12})")
MEDICAL_NO = re.compile(r"(?:没|还没|没有|不想|不用)(?:去)?(?:就医|医院|看医生|皮肤科)")
MEDICAL_YES = re.compile(r"就医|在医院|去了医院|去医院了|已经去医院|看了医生|看过医生|皮肤科")
STOP_NO = re.compile(r"还在用|继续用|没停|没有停")
STOP_YES = re.compile(r"停用|停了|不敢用|没再用|不用了|已经停")


class DraftField(ApiModel):
    field: str
    value: str
    source_ref: str
    quote: str


class TicketDraftView(ApiModel):
    conversation_id: str = ""
    work_order_type: str | None
    order_id: str | None = None
    fields: list[DraftField]


def _quote(body: str, start: int, end: int) -> str:
    left = max(body.rfind(mark, 0, start) for mark in "，。！？,.!?\n") + 1
    rights = [i for i in (body.find(mark, end) for mark in "，。！？,.!?\n") if i >= 0]
    return body[left:min(rights) if rights else len(body)].strip() or body.strip()


def draft_ticket(messages: list[tuple[str, str, str]]) -> TicketDraftView:
    customer = [(ref, body) for role, ref, body in messages if role == "customer" and body]
    kind = None
    for name, pattern in TYPE_RULES:
        if any(pattern.search(body) for _, body in customer):
            kind = name
            break
    fields: list[DraftField] = []

    def put(field: str, value: str, ref: str, body: str, match: re.Match) -> None:
        if all(item.field != field for item in fields):
            fields.append(DraftField(field=field, value=value, source_ref=ref,
                                     quote=_quote(body, match.start(), match.end())))

    if kind == "adverse_reaction":
        symptom = TYPE_RULES[0][1]
        for ref, body in customer:
            if (match := symptom.search(body)) and not MEDICAL_YES.fullmatch(match.group(0)):
                put("symptomDescription", _quote(body, match.start(), match.end()), ref, body, match)
            if match := AREA.search(body):
                put("affectedArea", match.group(0), ref, body, match)
            if match := ONSET.search(body):
                put("onsetInterval", next(g for g in match.groups() if g), ref, body, match)
            if match := BATCH.search(body):
                put("productBatchNo", match.group(1), ref, body, match)
        for ref, body in reversed(customer):
            if match := MEDICAL_NO.search(body):
                put("soughtMedicalCare", "no", ref, body, match)
            elif match := MEDICAL_YES.search(body):
                put("soughtMedicalCare", "yes", ref, body, match)
            if match := STOP_NO.search(body):
                put("stoppedUse", "no", ref, body, match)
            elif match := STOP_YES.search(body):
                put("stoppedUse", "yes", ref, body, match)
    elif kind is not None:
        pattern = dict(TYPE_RULES)[kind]
        for ref, body in customer:
            if match := pattern.search(body):
                put("reason", _quote(body, match.start(), match.end()), ref, body, match)
                break
    return TicketDraftView(work_order_type=kind, fields=fields)


def draft_for_conversation(session, conversation_id: str) -> TicketDraftView:
    from app.domain.consumer_service.workspace import conversation_messages
    from app.repositories.consumer_service import ConsumerServiceRepository

    messages = [(m.sender_role.value, f"message:{conversation_id}:{m.message_id}", m.body or "")
                for m in conversation_messages(session, conversation_id)]
    draft = draft_ticket(messages)
    orders = ConsumerServiceRepository(session).context(conversation_id).orders
    order_ids = list(dict.fromkeys(order.order_id for order in orders if order.conversation_id == conversation_id))
    return draft.model_copy(update={"conversation_id": conversation_id,
                                    "order_id": order_ids[0] if len(order_ids) == 1 else None})
