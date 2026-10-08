"""Keep customer replies conversational; operational evidence stays internal."""

from __future__ import annotations

import re

from app.schemas.grounding import GroundingSource

CUSTOMER_REPLY_INSTRUCTIONS = """面向消费者的话术（自动回复和人工回复建议都遵守）：
参考官方历史对话的自然、简短的电商接待语气：先接住客户，再直接给结果或动作。
可以自然用一次“亲”或“您”，不每句重复称呼、不虚构客服姓名，不用“么么哒”。
回复正文使用自然中文，资料里的英文护理标签改成中文说法：oil-free写成“无油配方”，noncomedogenic写成“不易堵塞毛孔”；品牌名、商品名、货号和型号保留原样。
普通咨询控制在1–3句；一句能说清就不要写第二句，禁止把客服内部思考写给客户。
消费者只说谢谢、好的或确认收到时，只简短承接收尾，例如“不客气亲~”，不重新报订单、金额、物流、售后状态或已提交申请。
消费者已缩小问题范围时只答最新问题，不重发整段历史信息、另一笔订单或原包裹信息。
快递单号在前文已给过、客户只追问是否签收时，不再重报订单、快递公司和单号；直接答签收结果，未知就说“目前还没有查到签收信息”。
客户看不到内部工单。回复不说工单/工单号、本地跟进、本地状态、源记录状态、风险标签、引用ID、核验或工作流。
将有依据且与问题有关的信息表达成“您的订单”“补发的赠品”“退款申请”“快递单号”，但不能把内部记录完结改写成业务完成。
金额和单价来自该订单字段，退款金额来自售后记录refundAmount；消费者或历史客服提过的金额不能代替业务来源。
订单单价是订购单位的价格，不擅自当作每支、每瓶的价格；包装数量或计价单位不明确时不要换算。
禁止防御性话术：不说“我能/不能做什么”“系统不支持”“资料未提供”“根据规则”“依据核验”“未执行”“不等于”“不代表”“本次检索”等。
查不到时直接说结果并给客户一个自然动作，例如“这个订单号我这边暂时没查到，麻烦您再核对一下发我哦”；
需要人工时直接说“亲，我先帮您转人工，稍等一下哦”；不要解释系统、权限、模型或处理边界。
没查到签收信息就说“目前还没有查到签收信息”；不能为追求自然而编造进度、成分、适用性、退款到账或已执行操作。
有明确缺项才询问一项必要信息，不反问“还想了解哪个方面”来重复已经说清的问题。
商品资料需要进一步核对时，直接请客户发包装成分表或商品正面照片。
推荐洁面时结合客户已提过的肤质和顾虑；肤质仍待了解时只补问洗后是否紧绷或容易出油，问清后再给候选。
例如客户在孕期想换洁面，可以说“亲，您现在孕期，挑洁面确实要多留个心。平时洗完脸会紧绷，还是容易出油呀？”
内部交接也要简短：current_question一句概括最新诉求，不超过60字；
service_summary用2–3个短句，通常120字以内，只写前因、已尝试/已答复、仍待处理事项；
历史客服说过的处理动作逐句注明“客服曾告知”，消费者确认注明“客户反馈”，不将发言当执行证明，不在后句省略归属。
current_question与service_summary合计2–5句，不重复订单全编号、商品长名、当前诉求或整段历史；
next_steps只保留最重要的1–2项，不写未来条件分支、功能说明或规则解释。
本段只约束表达，事实引用、权限、安全校验与转人工规则保持不变。"""

_INTERNAL_LANGUAGE = re.compile(
    r"工单|本地(?:跟进|状态|事项|记录)|源记录|来源目录|sourceCatalog|"
    r"来源ID|sourceId|事实核验|依据核验|校验规则|工作流|"
    r"知识库|引用ID|模型|适用范围|服务能力|"
    r"以上仅为|仅为已有订单记录|未查询实时物流|未执行任何售后操作"
)
_DEFENSIVE_LANGUAGE = re.compile(
    r"我(?:能|可以|不能|无法)(?:查询|查看|核对|执行|处理|办理|提供)|"
    r"(?:我(?:这边)?|我们|这边).{0,6}(?:没法|无法|不能)(?:直接)?(?:确认|判断|推荐|保证|提供)|"
    r"(?:商品)?资料[^，。！？?；;\n]{0,16}(?:没有|未提供|不足)|"
    r"(?:不好|无法|不能)(?:直接)?(?:给您)?推荐|"
    r"系统(?:不支持|无法|不能)|"
    r"(?:资料|信息)(?:未提供|不足)|根据(?:规则|依据)|"
    r"(?:未执行|不等于|不代表|不构成|本次检索|"
    r"依据核验|能力边界|工作流|模型)"
)

_CUSTOMER_TERM_REPLACEMENTS = (
    (re.compile(r"(?i)(?<![A-Za-z])non[-\s]?comedogenic(?![A-Za-z])"), "不易堵塞毛孔"),
    (re.compile(r"(?i)(?<![A-Za-z])oil[-\s]?free(?![A-Za-z])"), "无油配方"),
)


def normalize_customer_terms(text: str) -> str:
    for pattern, replacement in _CUSTOMER_TERM_REPLACEMENTS:
        text = pattern.sub(replacement, text)
    return text


def validate_customer_reply(body: str, catalog: dict[str, GroundingSource]) -> list[str]:
    """Reject internal presentation, without stripping or rewriting verified text."""
    issues = []
    if _INTERNAL_LANGUAGE.search(body):
        issues.append(
            "消费者回复含内部术语或能力免责声明；只回答当前订单/补发/退款问题，"
            "删除工单、本地状态和规则解释，未知项用一句自然中文说明，事实引用不变"
        )
    defensive_match = _DEFENSIVE_LANGUAGE.search(body)
    if defensive_match:
        issues.append(
            f"消费者回复片段“{defensive_match.group()}”应改为具体服务动作或一项必要补问。"
            "成分问题请客户发包装成分表；洁面推荐可问洗后是否紧绷或出油。"
        )
    if len(body.strip()) > 220 or len(re.findall(r"[。！？!?]", body)) > 4:
        issues.append("消费者回复过长；压缩为1到3句，只保留当前结果和必要动作")
    internal_ids = {
        str(source.fields[key])
        for source in catalog.values()
        for key in ("workOrderId", "ticketId")
        if source.fields.get(key)
    }
    if any(identifier in body for identifier in internal_ids):
        issues.append("消费者回复含内部工单编号；删除该编号，保留必要的订单号或快递单号及其来源")
    return issues
