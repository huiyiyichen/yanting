"""回复生成提示词（可被 Prompt 管理里的 REPLY 模板覆盖）。"""

from __future__ import annotations

REPLY_PROMPT_VERSION = "s5-reply-v1"

#: 系统提示词：约束写死在这里，改内容即改行为（Prompt 管理页可编辑启用中的模板）
REPLY_SYSTEM_PROMPT = """你是安克售后客服的回复助手，面向客户直接说话。

硬性约束（违反即视为无效输出）：
1. 只能使用「可用依据」与「已知事实」里出现的信息；没有依据就直说查不到，不要编造条款、编号或政策。
2. 绝不承诺赔付金额、退款到账时间、上门时限或「一定能修好」；也不要出现「保证」「承诺」这类词。
3. 不要声称任何业务动作已经完成（如已退款、已发货、已派单）——本 Demo 只做申请与人工确认。
4. 需要客户补充信息时，用一句话问清，不要一次追问超过 3 项。
5. 中文、口语、简洁：整段控制在 200 字以内，不要 Markdown 标题与编号列表以外的排版。
"""


def build_reply_prompt(
    *,
    message: str,
    facts_lines: list[str],
    evidence_lines: list[str],
    missing: list[str],
    style: str,
    candidates: list[str],
    has_images: bool = False,
) -> str:
    """把上下文拼成用户提示词。

    证据按「标题 + 摘录」给出，并要求模型在用到时点名来源标题——这样回复里能看出
    结论来自哪份资料（AC-07/AC-28 的证据引用要求）。
    """

    parts = [f"客户最新消息：{message}"]
    parts.append("已知事实：" + ("；".join(facts_lines) if facts_lines else "（暂无）"))
    parts.append(
        "可用依据："
        + (
            "\n".join(evidence_lines)
            if evidence_lines
            else "（无可用依据：请如实说明查不到，不要编造）"
        )
    )
    if not has_images:
        # 本轮没有图片：明确禁止「我看了照片」这类表述（实测模型会凭空这么说）
        parts.append("本轮客户没有发图片：不要声称看过照片，也不要把图片线索写进回复。")
    if missing:
        parts.append("仍缺的信息：" + "、".join(missing))
    if candidates:
        parts.append("待客户确认的候选产品：" + "；".join(candidates))
    parts.append(f"沟通风格：{style}")
    parts.append(
        "请直接输出给客户的回复正文：先回应客户的问题，再给依据支持的下一步；"
        "如果依据里没有答案，就说明暂时查不到并说明会转人工，不要编造。"
    )
    return "\n".join(parts)


__all__ = ["REPLY_PROMPT_VERSION", "REPLY_SYSTEM_PROMPT", "build_reply_prompt"]
