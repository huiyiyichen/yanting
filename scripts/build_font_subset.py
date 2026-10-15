"""思源黑体 CN 子集：GB2312 一级常用字 + 前端源码出现的全部字符 + ASCII/中文标点。

用法：python scripts/build_font_subset.py <SourceHanSansCN 目录>
输出 apps/web/public/fonts/YTSans-{Regular,Medium,Bold}.woff2 与 charset.txt。
字体为 SIL OFL 1.1 许可；"Source" 为保留字体名，子集属修改版本，故改名为 YT Sans 分发（LICENSE.txt 随附）。
"""

from __future__ import annotations

import sys
from pathlib import Path

from fontTools import subset

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "apps/web/public/fonts"
WEIGHTS = ("Regular", "Medium", "Bold")


def gb2312_level1() -> set[str]:
    chars = set()
    for hi in range(0xB0, 0xD8):
        for lo in range(0xA1, 0xFF):
            try:
                chars.add(bytes([hi, lo]).decode("gb2312"))
            except UnicodeDecodeError:
                pass
    return chars


def source_chars() -> set[str]:
    chars: set[str] = set()
    for path in (ROOT / "apps/web/src").rglob("*"):
        if path.suffix in {".ts", ".tsx", ".css"}:
            chars |= set(path.read_text(encoding="utf-8"))
    return {c for c in chars if ord(c) > 0x7F}


def charset() -> str:
    ascii_ = {chr(i) for i in range(0x20, 0x7F)}
    punct = set("，。、；：？！“”‘’（）《》【】—…·￥％～　")
    return "".join(sorted(ascii_ | punct | gb2312_level1() | source_chars()))


def main(src_dir: str) -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    text = charset()
    (OUT / "charset.txt").write_text(text, encoding="utf-8")
    for weight in WEIGHTS:
        options = subset.Options()
        options.flavor = "woff2"
        options.layout_features = ["*"]
        options.name_IDs = [0, 7, 8, 9, 11, 12, 13, 14]
        font = subset.load_font(str(Path(src_dir) / f"SourceHanSansCN-{weight}.otf"), options)
        subsetter = subset.Subsetter(options)
        subsetter.populate(text=text)
        subsetter.subset(font)
        name = font["name"]
        name.setName("YT Sans", 1, 3, 1, 0x409)
        name.setName(weight, 2, 3, 1, 0x409)
        name.setName(f"YT Sans {weight}", 4, 3, 1, 0x409)
        name.setName(f"YTSans-{weight}", 6, 3, 1, 0x409)
        name.setName(f"YT Sans {weight} subset of Source Han Sans CN", 3, 3, 1, 0x409)
        name.setName("Version 2.005", 5, 3, 1, 0x409)
        subset.save_font(font, str(OUT / f"YTSans-{weight}.woff2"), options)
    print(f"{len(text)} chars -> {OUT}")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else ".")
