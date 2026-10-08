"""Markdown 知识源解析：保留标题路径、表格与定位信息。

设计要点（工程规范第 12.3 节）：
- 先按标题层级分组，保留标题路径；
- 表格按完整行分组，每块重复表头；
- 定位到源行号，供 `source_locator` 追溯。
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field

HEADING_RE = re.compile(r"^(#{1,6})\s+(.*)$")
TABLE_ROW_RE = re.compile(r"^\s*\|.*\|\s*$")
TABLE_SEPARATOR_RE = re.compile(r"^\s*\|[\s:|-]+\|\s*$")


@dataclass(slots=True)
class Block:
    """源文档中的一个语义块（段落 / 表格 / 列表 / 提示）。"""

    text: str
    heading_path: tuple[str, ...]
    start_line: int
    end_line: int
    kind: str = "paragraph"


@dataclass(slots=True)
class ParsedDocument:
    blocks: list[Block] = field(default_factory=list)
    headings: list[str] = field(default_factory=list)

    @property
    def char_count(self) -> int:
        return sum(len(block.text) for block in self.blocks)


def content_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def parse_markdown(text: str) -> ParsedDocument:
    """把 Markdown 解析成有序块，并记录标题路径与行号。"""

    lines = text.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    document = ParsedDocument()
    heading_path: list[str] = []
    buffer: list[str] = []
    buffer_start = 0
    index = 0

    def flush(end_line: int) -> None:
        nonlocal buffer, buffer_start
        joined = "\n".join(buffer).strip("\n")
        if joined.strip():
            document.blocks.append(
                Block(
                    text=joined.strip(),
                    heading_path=tuple(heading_path),
                    start_line=buffer_start,
                    end_line=end_line,
                )
            )
        buffer = []

    while index < len(lines):
        line = lines[index]
        heading_match = HEADING_RE.match(line)

        if heading_match:
            flush(index - 1)
            level = len(heading_match.group(1))
            title = heading_match.group(2).strip()
            heading_path = heading_path[: level - 1]
            while len(heading_path) < level - 1:
                heading_path.append("")
            heading_path.append(title)
            document.headings.append(title)
            index += 1
            continue

        if TABLE_ROW_RE.match(line) and not TABLE_SEPARATOR_RE.match(line):
            flush(index - 1)
            # 表格整体成块，并重复表头，保证每个块都能独立读懂
            table_lines: list[str] = []
            start = index
            while index < len(lines) and TABLE_ROW_RE.match(lines[index]):
                if not TABLE_SEPARATOR_RE.match(lines[index]):
                    table_lines.append(lines[index].strip())
                index += 1
            if len(table_lines) > 1:
                header = table_lines[0]
                body = table_lines[1:]
                document.blocks.append(
                    Block(
                        text="\n".join([header, *body]),
                        heading_path=tuple(heading_path),
                        start_line=start,
                        end_line=index - 1,
                        kind="table",
                    )
                )
            elif table_lines:
                document.blocks.append(
                    Block(
                        text=table_lines[0],
                        heading_path=tuple(heading_path),
                        start_line=start,
                        end_line=index - 1,
                        kind="table",
                    )
                )
            continue

        if not line.strip():
            flush(index - 1)
            index += 1
            continue

        if not buffer:
            buffer_start = index
        buffer.append(line)
        index += 1

    flush(len(lines) - 1)
    return document
