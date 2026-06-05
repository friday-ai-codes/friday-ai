"""Vue SFC pre-splitter —— 把 .vue 源码拆为 template / script / style 三段。

per initial implementation：不引入 tree-sitter-vue grammar，用 Python 正则 + 标签扫描
实现的纯函数 splitter；保 line_offset / start_byte 精度，让子 extractor
（TS / HTML / CSS）输出能还原到原 .vue 文件视角行号。

模块仅暴露两个接口：`SfcBlock`（dataclass）+ `split_sfc`（纯函数）。
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Literal

import structlog

logger = structlog.get_logger(__name__)


@dataclass
class SfcBlock:
    """SFC 单块描述符（per initial implementation）。

    - kind: 块类型，固定三选一，便于后续 dispatch
    - attrs: 属性 dict（如 {"lang": "ts", "setup": True}），布尔值表示无 value 的 attr
    - content: 块内容（去除开/闭标签包裹）
    - line_offset: 1-based 块第一行在原 .vue 文件的行号（per Pitfall 1 用于行号还原）
    - start_byte / end_byte: 块内容在原 source 中的字节偏移
    """

    kind: Literal["template", "script", "style"]
    attrs: dict[str, str | bool] = field(default_factory=dict)
    content: str = ""
    line_offset: int = 1
    start_byte: int = 0
    end_byte: int = 0


_BLOCK_OPEN = re.compile(
    r"<(template|script|style)((?:\s+[^>]*?)?)>",
    re.IGNORECASE,
)


def split_sfc(source: str) -> list[SfcBlock]:
    """把 .vue 源码按出现顺序拆为 SfcBlock 列表。

    遇到缺闭标签时不抛错：log warning + 终止扫描（per work item 健壮性）。
    """
    blocks: list[SfcBlock] = []
    pos = 0
    line_at_pos = 1

    while True:
        m = _BLOCK_OPEN.search(source, pos)
        if m is None:
            break

        kind = m.group(1).lower()
        attrs_raw = m.group(2)
        block_open_start = m.start()
        block_content_start = m.end()
        close_tag = f"</{kind}>"
        close_idx = source.find(close_tag, block_content_start)
        if close_idx == -1:
            logger.warning(
                "vue_sfc_block_missing_close_tag",
                kind=kind,
                line_offset=line_at_pos + source.count("\n", pos, block_open_start),
            )
            break

        open_tag_line = line_at_pos + source.count("\n", pos, block_open_start)
        content = source[block_content_start:close_idx]
        line_offset = open_tag_line + 1

        attrs = _parse_attrs(attrs_raw)
        blocks.append(
            SfcBlock(
                kind=kind,  # type: ignore[arg-type]
                attrs=attrs,
                content=content,
                line_offset=line_offset,
                start_byte=block_content_start,
                end_byte=close_idx,
            )
        )

        pos = close_idx + len(close_tag)
        line_at_pos = open_tag_line + content.count("\n")

    return blocks


_ATTRS_PATTERN = re.compile(
    r"([a-zA-Z_][\w-]*)\s*(?:=\s*(?:\"([^\"]*)\"|'([^']*)'|(\S+)))?"
)


def _parse_attrs(attrs_raw: str) -> dict[str, str | bool]:
    """解析 `lang="ts" setup scoped` 类属性串为 dict。

    无 value 的 attr 映射 True；带值的 attr 映射 str。
    """
    attrs: dict[str, str | bool] = {}
    if not attrs_raw.strip():
        return attrs
    for m in _ATTRS_PATTERN.finditer(attrs_raw):
        key = m.group(1)
        value = m.group(2) or m.group(3) or m.group(4)
        attrs[key] = value if value is not None else True
    return attrs


__all__ = ["SfcBlock", "split_sfc"]
