"""blueprint_anchor —— 划线线程重锚定纯函数（Phase 111，DESIGN §6.2）。

新版本蓝图装配后，把线程的 anchor 重挂到新 block 序列：

1. **精确**：``anchor.block_id`` 仍存在于新 blocks → 原样保留（anchored）；
2. **模糊**：块被编辑导致 block_id 消失时，按 ``anchor.quoted_text`` 与各新块文本的
   ``difflib.SequenceMatcher.ratio()`` 相似度匹配，最佳 ≥ ``SIMILARITY_THRESHOLD``
   （0.85，111-CONTEXT 锁定值）→ 重挂新 block_id（quoted_text 保留原文）；
3. **失锚**：以上都不中 → ``orphaned``——**绝不删线程**（前端集中展示「失锚评论」，
   不静默丢失；批量应用到线程行的调用方在 Phase 114，111 只交付算法与单测）。

**纯函数**（stdlib only，无 ORM / 无 LLM）——形态沿 ``process_runtime/wave_layering.py``。
输入是半可信 LLM 合成产物，逐字段 ``.get`` 防御，绝不抛异常。
"""

from __future__ import annotations

import difflib

__all__ = [
    "reanchor",
    "SIMILARITY_THRESHOLD",
    "ANCHOR_STATUS_ANCHORED",
    "ANCHOR_STATUS_ORPHANED",
]

# quoted_text 模糊匹配相似度阈值（111-CONTEXT 锁定值）
SIMILARITY_THRESHOLD = 0.85

ANCHOR_STATUS_ANCHORED = "anchored"
ANCHOR_STATUS_ORPHANED = "orphaned"


def _block_text(block: dict) -> str:
    """提取 block 的可比对文本（DESIGN §3.2 Block 基元，逐字段 .get 防御）。

    - ``text`` 为 str（paragraph/mermaid）→ 直取；
    - ``text`` 为 list（list 型 block 的 items[]）→ 逐条 join；
    - pseudocode → ``code.source``；
    - table → ``rows`` 扁平 join。
    """
    if not isinstance(block, dict):
        return ""
    text = block.get("text")
    if isinstance(text, str) and text:
        return text
    if isinstance(text, list):
        return "\n".join(str(item) for item in text)
    code = block.get("code")
    if isinstance(code, dict):
        source = code.get("source")
        if isinstance(source, str) and source:
            return source
    rows = block.get("rows")
    if isinstance(rows, list):
        cells: list[str] = []
        for row in rows:
            if isinstance(row, list):
                cells.extend(str(cell) for cell in row)
            else:
                cells.append(str(row))
        return "\n".join(cells)
    return ""


def reanchor(anchor: dict, new_blocks: list[dict]) -> tuple[dict, str]:
    """把线程 anchor 重挂到新 block 序列，返回 ``(new_anchor, anchor_status)``。

    三分支：block_id 精确命中 → anchored（anchor 原样）；quoted_text 相似度
    ≥ SIMILARITY_THRESHOLD 模糊命中 → anchored（重挂新 block_id，quoted_text
    保留原文）；否则 orphaned（anchor 原样）——失锚不删线程（调用方语义）。

    同分并列时取 block_id 字典序小者，保证确定性。
    """
    if not isinstance(anchor, dict) or not anchor:
        return (anchor, ANCHOR_STATUS_ORPHANED)

    blocks = [b for b in (new_blocks or []) if isinstance(b, dict)]

    # 1) 精确：block_id 仍存在
    block_id = anchor.get("block_id")
    if block_id and any(b.get("block_id") == block_id for b in blocks):
        return (anchor, ANCHOR_STATUS_ANCHORED)

    # 2) 模糊：quoted_text 相似度匹配
    quoted_text = anchor.get("quoted_text") or ""
    if not isinstance(quoted_text, str) or not quoted_text:
        return (anchor, ANCHOR_STATUS_ORPHANED)

    best_ratio = -1.0
    best_block_id: str | None = None
    for block in blocks:
        candidate_id = block.get("block_id")
        if not candidate_id:
            continue
        ratio = difflib.SequenceMatcher(None, quoted_text, _block_text(block)).ratio()
        # 同分取 block_id 字典序小者（确定性）
        if ratio > best_ratio or (ratio == best_ratio and str(candidate_id) < str(best_block_id)):
            best_ratio = ratio
            best_block_id = str(candidate_id)

    if best_block_id is not None and best_ratio >= SIMILARITY_THRESHOLD:
        return (dict(anchor, block_id=best_block_id), ANCHOR_STATUS_ANCHORED)

    # 3) 失锚：anchor 原样，绝不删线程
    return (anchor, ANCHOR_STATUS_ORPHANED)
