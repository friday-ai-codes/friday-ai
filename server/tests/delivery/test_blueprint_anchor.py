"""blueprint_anchor 重锚定纯函数测试（Phase 111-02 Task 3，DESIGN §6.2）。

纯函数无 django_db。覆盖：精确命中 / 模糊重挂（>0.85）/ 完全不同 → orphaned /
阈值边界（difflib 现算断言，不硬编码猜测值）/ quoted_text 为空 → orphaned /
list 与 pseudocode 型块的 _block_text 提取。
"""

from __future__ import annotations

import difflib

from delivery.services.blueprint_anchor import (
    ANCHOR_STATUS_ANCHORED,
    ANCHOR_STATUS_ORPHANED,
    SIMILARITY_THRESHOLD,
    reanchor,
)

_PARA = "蓝图的状态转移必须经由 BlueprintLifecycleService 单点收口，禁止旁路写。"


def _anchor(block_id: str = "blk_a", quoted_text: str = _PARA) -> dict:
    return {
        "section_path": "implementation_overview",
        "block_id": block_id,
        "start_offset": 0,
        "end_offset": len(quoted_text),
        "quoted_text": quoted_text,
    }


# ---- 精确命中分支 ----


def test_exact_block_id_hit_keeps_anchor() -> None:
    anchor = _anchor(block_id="blk_a")
    blocks = [
        {"block_id": "blk_a", "type": "paragraph", "text": "内容已被大改也不要紧"},
        {"block_id": "blk_b", "type": "paragraph", "text": _PARA},
    ]
    new_anchor, status = reanchor(anchor, blocks)
    assert status == ANCHOR_STATUS_ANCHORED
    assert new_anchor is anchor  # 原样返回，未复制改写


# ---- 模糊重挂分支（相似度 > 0.85） ----


def test_fuzzy_rehit_rebinds_new_block_id_and_keeps_quoted_text() -> None:
    edited = _PARA + "（INV-6）"  # 轻微追加，相似度高
    assert difflib.SequenceMatcher(None, _PARA, edited).ratio() > SIMILARITY_THRESHOLD
    anchor = _anchor(block_id="blk_gone")
    blocks = [
        {"block_id": "blk_new", "type": "paragraph", "text": edited},
        {"block_id": "blk_other", "type": "paragraph", "text": "毫不相干的另一段话"},
    ]
    new_anchor, status = reanchor(anchor, blocks)
    assert status == ANCHOR_STATUS_ANCHORED
    assert new_anchor["block_id"] == "blk_new"
    assert new_anchor["quoted_text"] == _PARA  # 保留原文
    assert anchor["block_id"] == "blk_gone"  # 入参不被原地修改


def test_fuzzy_tie_prefers_lexicographically_smaller_block_id() -> None:
    anchor = _anchor(block_id="blk_gone")
    blocks = [
        {"block_id": "blk_z", "type": "paragraph", "text": _PARA},
        {"block_id": "blk_b", "type": "paragraph", "text": _PARA},
    ]
    new_anchor, status = reanchor(anchor, blocks)
    assert status == ANCHOR_STATUS_ANCHORED
    assert new_anchor["block_id"] == "blk_b"


# ---- orphaned 分支 ----


def test_totally_different_text_orphans_and_keeps_anchor() -> None:
    anchor = _anchor(block_id="blk_gone")
    blocks = [{"block_id": "blk_x", "type": "paragraph", "text": "completely unrelated"}]
    new_anchor, status = reanchor(anchor, blocks)
    assert status == ANCHOR_STATUS_ORPHANED
    assert new_anchor is anchor  # 原样，不删不改


def test_empty_quoted_text_orphans() -> None:
    anchor = _anchor(block_id="blk_gone", quoted_text="")
    blocks = [{"block_id": "blk_x", "type": "paragraph", "text": _PARA}]
    _, status = reanchor(anchor, blocks)
    assert status == ANCHOR_STATUS_ORPHANED


def test_non_dict_or_empty_anchor_is_defensive_orphaned() -> None:
    assert reanchor({}, [])[1] == ANCHOR_STATUS_ORPHANED
    assert reanchor(None, [{"block_id": "blk_x", "text": _PARA}])[1] == ANCHOR_STATUS_ORPHANED  # type: ignore[arg-type]


# ---- 阈值边界（difflib 现算，两侧各证一例） ----


def test_threshold_boundary_both_sides() -> None:
    base = "abcdefghijklmnopqrst"  # 20 字符
    # 改 1 尾字符：ratio = 2*19/40 = 0.95 ≥ 0.85 → anchored
    above = base[:-1] + "X"
    ratio_above = difflib.SequenceMatcher(None, base, above).ratio()
    assert ratio_above >= SIMILARITY_THRESHOLD
    # 改 4 尾字符：ratio = 2*16/40 = 0.80 < 0.85 → orphaned
    below = base[:-4] + "WXYZ"
    ratio_below = difflib.SequenceMatcher(None, base, below).ratio()
    assert ratio_below < SIMILARITY_THRESHOLD

    anchor = _anchor(block_id="blk_gone", quoted_text=base)
    _, status_above = reanchor(anchor, [{"block_id": "blk_n", "text": above}])
    assert status_above == ANCHOR_STATUS_ANCHORED
    _, status_below = reanchor(anchor, [{"block_id": "blk_n", "text": below}])
    assert status_below == ANCHOR_STATUS_ORPHANED


# ---- _block_text 各型块提取（经 reanchor 行为断言） ----


def test_list_block_items_are_joined_for_matching() -> None:
    items = ["第一条要点内容", "第二条要点内容", "第三条要点内容"]
    quoted = "\n".join(items)
    anchor = _anchor(block_id="blk_gone", quoted_text=quoted)
    blocks = [{"block_id": "blk_list", "type": "list", "text": items}]
    new_anchor, status = reanchor(anchor, blocks)
    assert status == ANCHOR_STATUS_ANCHORED
    assert new_anchor["block_id"] == "blk_list"


def test_pseudocode_block_matches_on_code_source() -> None:
    source = "def transition(artifact, to_status):\n    assert to_status in allowed\n"
    anchor = _anchor(block_id="blk_gone", quoted_text=source)
    blocks = [
        {
            "block_id": "blk_code",
            "type": "pseudocode",
            "code": {"language": "python", "source": source},
        }
    ]
    new_anchor, status = reanchor(anchor, blocks)
    assert status == ANCHOR_STATUS_ANCHORED
    assert new_anchor["block_id"] == "blk_code"


def test_table_block_matches_on_flattened_rows() -> None:
    rows = [["状态", "含义"], ["researching", "调研中"], ["drafting", "产出中"]]
    quoted = "\n".join(cell for row in rows for cell in row)
    anchor = _anchor(block_id="blk_gone", quoted_text=quoted)
    blocks = [{"block_id": "blk_tbl", "type": "table", "rows": rows}]
    new_anchor, status = reanchor(anchor, blocks)
    assert status == ANCHOR_STATUS_ANCHORED
    assert new_anchor["block_id"] == "blk_tbl"
