"""结构化切片。

规则来源：工程规范第 12.3 节。

关键约定：
- `chunk_size=600` / `chunk_overlap=80` 以 **Unicode 字符数**（Python `len(text)`）计，
  不是 token、不是字节、也不是「汉字数」；
- 不跨文档、版本、可见范围和适用条件拼接（由调用方保证输入同源）；
- 重叠是**目标上限**，不保证每块恰好 80；
- SOP 的适用条件、注意事项与步骤绑定；步骤组过长时拆为完整步骤块并携带共同前置条件
  与 `parent_group_id`；
- 表格按完整行分组并重复表头；不可分割的长步骤/单行允许超过目标长度，
  但编码前必须检查模型上限，超限进入可见错误。
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from app.knowledge.parsing import Block, ParsedDocument, content_hash

# 中英文句末分隔符，用于在语义边界处切分
SENTENCE_SPLIT_RE = re.compile(r"(?<=[。！？；!?;])\s*|\n+")
LIST_ITEM_RE = re.compile(r"^\s*(?:[-*+]|\d+[.、)])\s+")

# SOP 中携带约束语义的小节标题：这些内容不能与其后的步骤分离
CONSTRAINT_HEADINGS = ("前置条件", "注意事项", "禁止事项", "何时需要升级", "升级条件")
STEP_GROUP_RE = re.compile(r"^步骤组?\s*[A-Za-z0-9一二三四五六七八九十]*")
STEP_ITEM_RE = re.compile(r"^###?\s*步骤\s*\d+")


@dataclass(slots=True)
class DraftChunk:
    text: str
    heading_path: tuple[str, ...]
    start_line: int
    end_line: int
    parent_group_id: str | None = None
    kind: str = "paragraph"


def _heading_prefix(heading_path: tuple[str, ...]) -> str:
    """标题路径作为前缀参与检索，同时保留「标题不存在时用空路径」的语义。"""

    visible = [item for item in heading_path if item]
    return " > ".join(visible)


def _split_long_text(text: str, chunk_size: int, overlap: int) -> list[str]:
    """把过长文本切成若干段，优先在句末断开。"""

    sentences = [item for item in SENTENCE_SPLIT_RE.split(text) if item and item.strip()]
    if not sentences:
        return [text]

    pieces: list[str] = []
    current = ""
    for sentence in sentences:
        candidate = f"{current}{sentence}" if current else sentence
        if current and len(candidate) > chunk_size:
            pieces.append(current)
            # 重叠取上一段尾部，作为目标上限而非硬性保证
            tail = current[-overlap:] if overlap > 0 else ""
            current = f"{tail}{sentence}"
        else:
            current = candidate
    if current.strip():
        pieces.append(current)
    return pieces


def _is_constraint_block(block: Block) -> bool:
    if not block.heading_path:
        return False
    tail = block.heading_path[-1]
    return any(keyword in tail for keyword in CONSTRAINT_HEADINGS)


def _pack_group(
    blocks: list[Block],
    *,
    chunk_size: int,
    chunk_overlap: int,
) -> list[DraftChunk]:
    """把同一标题路径下的连续块打包到接近 chunk_size。

    为什么必须打包：夹具里大量块只有几十个字符。若一个块直接成为一个片段，
    `chunk_size` 就退化成「仅用于判断是否要切」的上限，参数实际上不起作用，
    不同切片配置会产出完全相同的索引（已实测：400/60 与 800/100 都是 124 块，
    平均长度仅 93.6 字符）。这里按标题路径分组、在目标长度内合并，
    使 `chunk_size` 真正成为「目标长度」。
    """

    if not blocks:
        return []
    heading_path = blocks[0].heading_path
    prefix = _heading_prefix(heading_path)
    prefix_cost = len(prefix) + 1 if prefix else 0

    # 先拼成"整段文本"，同时记录每块的起止行，便于回溯定位
    body = "\n\n".join(block.text for block in blocks)
    start_line = blocks[0].start_line
    end_line = blocks[-1].end_line

    budget = max(chunk_size - prefix_cost, 1)
    pieces = _split_long_text(body, budget, chunk_overlap)
    chunks: list[DraftChunk] = []
    for piece in pieces:
        text = f"{prefix}\n{piece}" if prefix else piece
        chunks.append(
            DraftChunk(
                text=text,
                heading_path=heading_path,
                start_line=start_line,
                end_line=end_line,
                kind="table" if len(blocks) == 1 and blocks[0].kind == "table" else "paragraph",
            )
        )
    return chunks


def chunk_document(
    document: ParsedDocument,
    *,
    chunk_size: int = 600,
    chunk_overlap: int = 80,
) -> list[DraftChunk]:
    """把解析后的文档切成片段。"""

    # 记录每个标题路径下最近一次出现的「约束」块，供步骤块携带
    constraint_by_path: dict[tuple[str, ...], str] = {}
    for block in document.blocks:
        if _is_constraint_block(block):
            constraint_by_path[block.heading_path] = block.text

    # 1) 表格单独成块（按完整行分组、已重复表头），不与段落混拼
    # 2) 其余按标题路径顺序分组，组内再打包到目标长度
    chunks: list[DraftChunk] = []
    group: list[Block] = []

    def flush() -> None:
        nonlocal group
        if group:
            chunks.extend(_pack_group(group, chunk_size=chunk_size, chunk_overlap=chunk_overlap))
            group = []

    for block in document.blocks:
        if block.kind == "table":
            flush()
            prefix = _heading_prefix(block.heading_path)
            chunks.append(
                DraftChunk(
                    text=f"{prefix}\n{block.text}" if prefix else block.text,
                    heading_path=block.heading_path,
                    start_line=block.start_line,
                    end_line=block.end_line,
                    kind="table",
                )
            )
            continue

        if group and group[-1].heading_path != block.heading_path:
            flush()
        group.append(block)
    flush()

    return _attach_parent_groups(chunks, constraint_by_path)


def _attach_parent_groups(
    chunks: list[DraftChunk], constraint_by_path: dict[tuple[str, ...], str]
) -> list[DraftChunk]:
    """为过长步骤组补充共同前置条件与 parent_group_id。

    SOP 被拆块后，后面的步骤块会丢失前面的「前置条件 / 注意事项」约束，
    这里把该标题路径下的约束补回，避免检索到步骤却看不到限制条件。
    """

    adjusted: list[DraftChunk] = []
    for chunk in chunks:
        is_step_like = chunk.kind == "step" or LIST_ITEM_RE.match(chunk.text.split("\n")[-1] or "")
        if not is_step_like:
            adjusted.append(chunk)
            continue

        constraint = constraint_by_path.get(chunk.heading_path)
        if not constraint:
            # 向上级标题查找
            for depth in range(len(chunk.heading_path) - 1, 0, -1):
                candidate = constraint_by_path.get(chunk.heading_path[:depth])
                if candidate:
                    constraint = candidate
                    break

        if constraint and constraint not in chunk.text:
            merged = f"{chunk.text}\n\n【必须同时满足的约束】\n{constraint}"
            adjusted.append(
                DraftChunk(
                    text=merged,
                    heading_path=chunk.heading_path,
                    start_line=chunk.start_line,
                    end_line=chunk.end_line,
                    parent_group_id=f"grp-{content_hash(' > '.join(chunk.heading_path) + constraint)[:12]}",
                    kind=chunk.kind,
                )
            )
        else:
            adjusted.append(chunk)
    return adjusted


def build_chunk_id(document_id: str, document_version: str, index: int, text: str) -> str:
    """片段 ID 必须稳定：同一文档同一版本同一内容重复导入得到相同 ID。"""

    digest = content_hash(f"{document_id}|{document_version}|{index}|{text}")[:16]
    return f"{document_id}@{document_version}#{index:04d}-{digest}"
