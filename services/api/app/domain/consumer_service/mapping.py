"""Versioned, explicit Excel mapping. Unmapped columns remain in the raw snapshot."""

from dataclasses import dataclass

MAPPING_VERSION = "loreal-excel-v1"
DATASET_ID = "loreal-official-mock"


@dataclass(frozen=True)
class SheetMapping:
    entity: str
    key: str
    fields: dict[str, str]
    datetime_fields: tuple[str, ...] = ()
    money_fields: tuple[str, ...] = ()
    integer_fields: tuple[str, ...] = ()
    status_field: str | None = None


COMMON = {
    "会话ID": "conversation_id",
    "买家昵称": "buyer_alias",
    "店铺": "shop",
}
WORK_ORDER_COMMON = {
    **COMMON,
    "工单号": "work_order_id",
    "关联订单号": "order_id",
    "处理人": "handler",
    "创建时间": "created_at",
    "完成时间": "completed_at",
}
WORK_ORDER_DATES = ("created_at", "completed_at")
SHEETS = {
    "聊天记录": SheetMapping(
        "message",
        "message_id",
        {
            **COMMON,
            "消息序号": "sequence",
            "message_id": "message_id",
            "发送时间": "sent_at",
            "角色": "source_role",
            "发送方": "sender",
            "scene_major": "scene_major",
            "scene_minor": "scene_minor",
            "is_target_buyer_message": "is_target_buyer_message",
            "message_text": "body",
            "内容类型": "source_content_type",
            "chat_content": "chat_content",
            "category": "category",
            "image_path": "image_ref",
            "关联订单号": "order_id",
            "关联工单号": "work_order_id",
        },
        ("sent_at",),
        integer_fields=("sequence", "is_target_buyer_message"),
    ),
    "订单": SheetMapping(
        "order",
        "order_id",
        {
            **COMMON,
            "订单号": "order_id",
            "商品货号": "sku",
            "商品名称": "product_name",
            "数量": "quantity",
            "单价(元)": "unit_price",
            "实付金额(元)": "paid_amount",
            "订单状态": "source_status",
            "下单时间": "ordered_at",
            "付款时间": "paid_at",
            "发货时间": "shipped_at",
            "快递公司": "carrier",
            "物流单号": "tracking_no",
            "收货省": "province",
            "收货市": "city",
            "赠品": "gift",
            "买家留言": "buyer_note",
        },
        ("ordered_at", "paid_at", "shipped_at"),
        ("unit_price", "paid_amount"),
        ("quantity",),
        "source_status",
    ),
    "补发换货工单": SheetMapping(
        "reship_exchange",
        "work_order_id",
        {
            **WORK_ORDER_COMMON,
            "工单类型": "service_type",
            "售后原因": "reason",
            "发出商品货号": "sku",
            "发出商品名称": "product_name",
            "数量": "quantity",
            "原订单物流单号": "original_tracking_no",
            "补发物流单号": "reship_tracking_no",
            "快递公司": "carrier",
            "发货仓库": "warehouse",
            "客诉加急": "urgent",
            "工单状态": "source_status",
        },
        WORK_ORDER_DATES,
        integer_fields=("quantity",),
        status_field="source_status",
    ),
    "线下打款工单": SheetMapping(
        "offline_payment",
        "work_order_id",
        {
            **WORK_ORDER_COMMON,
            "打款类型": "payment_type",
            "退款问题类型": "refund_reason",
            "退款金额(元)": "refund_amount",
            "支付宝实名": "payee_alias",
            "支付宝账号": "payment_account",
            "相关物流单号": "related_tracking_no",
            "转账状态": "transfer_status",
            "工单状态": "source_status",
        },
        WORK_ORDER_DATES,
        ("refund_amount",),
        status_field="source_status",
    ),
    "物流工单": SheetMapping(
        "logistics",
        "work_order_id",
        {
            **WORK_ORDER_COMMON,
            "问题类型": "issue_type",
            "快递公司": "carrier",
            "问题包裹物流单号": "tracking_no",
            "发货仓": "warehouse",
            "订单实付(元)": "paid_amount",
            "处理方案": "solution",
            "收货省": "province",
            "收货市": "city",
            "工单状态": "source_status",
        },
        WORK_ORDER_DATES,
        ("paid_amount",),
        status_field="source_status",
    ),
    "不良反应工单": SheetMapping(
        "adverse_reaction",
        "work_order_id",
        {
            **WORK_ORDER_COMMON,
            "类型": "channel",
            "年龄": "age",
            "肤质": "skin_type",
            "使用商品": "product_name",
            "产品批次号": "product_batch_no",
            "不适部位": "affected_area",
            "症状描述": "symptom_description",
            "用后多久出现": "onset_interval",
            "是否停用": "stopped_use",
            "是否就医": "sought_medical_care",
            "任务状态": "source_status",
        },
        WORK_ORDER_DATES,
        integer_fields=("age",),
        status_field="source_status",
    ),
    "售后退货工单": SheetMapping(
        "return_refund",
        "work_order_id",
        {
            **WORK_ORDER_COMMON,
            "包裹类型": "parcel_type",
            "退货原因": "return_reason",
            "退货物流单号": "tracking_no",
            "快递公司": "carrier",
            "退款编号": "refund_id",
            "签收建议": "receipt_advice",
            "是否异常": "abnormal",
            "任务状态": "source_status",
        },
        WORK_ORDER_DATES,
        status_field="source_status",
    ),
}

ROLE_MAP = {"买家": "customer", "客服": "operator", "系统推送": "system"}
CONTENT_TYPE_MAP = {"文本": "text", "图片": "image"}
STATUS_MAP = {
    "待处理": "pending",
    "进行中": "in_progress",
    "处理中": "in_progress",
    "工单组处理": "in_progress",
    "仓库处理": "in_progress",
    "已完结": "completed",
}
