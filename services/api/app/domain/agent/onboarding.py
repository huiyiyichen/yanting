"""新会话开场白与快捷选项（固定文案，唯一来源在后端）。

为什么放在后端而不是前端常量：
- 开场白要**真的落库**成一条服务方消息，刷新后仍然在；文案只有一个来源，
  不会出现"前端显示一套、库里存另一套"；
- 快捷选项点击后是**当作客户消息发出去**的（走完整的理解/检索/回复链路），
  所以文案与后续追问逻辑应该由后端定义；
- 前端只在"这条会话还没有客户消息"时展示快捷选项——用户直接打字也能正常走流程，
  两条路径共用同一套编排，不做"点按钮才有的特殊分支"。

边界：这里只是**文案与入口**，没有新增业务能力；点「退款进度」不会执行退款，
仍然走原有的草稿 + 人工确认流程。
"""

from __future__ import annotations

from dataclasses import dataclass

#: 开场白。写成一段话而不是列表：客户视角的聊天气泡里，列表会被压缩得难读。
WELCOME_MESSAGE = "您好，请描述您遇到的肌肤、商品、订单或售后问题。"

#: 快捷选项：`label` 是按钮文字，`prompt` 是点击后真正发给 Agent 的那句话。
QUICK_REPLIES: tuple[dict[str, str], ...] = (
    {"label": "使用后出现不适", "prompt": "使用产品后出现不适，需要客服协助。"},
    {"label": "查询订单物流", "prompt": "我想查询订单和物流进度。"},
    {"label": "申请退换货", "prompt": "我想申请退货或换货。"},
    {"label": "查询补发打款", "prompt": "我想查询补发或打款进度。"},
    {"label": "转人工客服", "prompt": "我要转人工客服。"},
)


@dataclass(frozen=True, slots=True)
class QuickReply:
    label: str
    prompt: str


def quick_replies() -> list[QuickReply]:
    return [QuickReply(label=item["label"], prompt=item["prompt"]) for item in QUICK_REPLIES]


#: 开场白消息的幂等键：同一会话重复创建不会插入第二条开场白。
WELCOME_KEY = "welcome-v1"
