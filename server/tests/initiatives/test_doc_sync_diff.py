"""doc_sync_diff 纯函数单测（83-01 Task 2/3，SYNC-03/04）。

全部无 IO / 无 DB / 无网络——验证 block_id 结构化 diff 三分支 + 三方合并真值表 +
content_hash 幂等归一化。
"""

from __future__ import annotations

from initiatives.services.doc_sync_diff import (
    BlockDiff,
    MergeResult,
    block_content_hash,
    diff_blocks,
    three_way_merge,
)


def _ops(diffs: list[BlockDiff]) -> dict[str, BlockDiff]:
    """按 (op, block_id) 索引，便于断言。"""
    return {f"{d.op}:{d.feishu_block_id}": d for d in diffs}


# ---- block_content_hash ----


def test_block_content_hash_idempotent() -> None:
    assert block_content_hash("hello") == block_content_hash("hello")


def test_block_content_hash_normalizes_whitespace() -> None:
    # 仅空白/换行差异不应改变指纹（折叠空白）。
    assert block_content_hash("a  b\n c") == block_content_hash("a b c")
    assert block_content_hash("  x  ") == block_content_hash("x")


def test_block_content_hash_distinguishes_content() -> None:
    assert block_content_hash("a") != block_content_hash("b")


# ---- diff_blocks: 四类 ----


def test_diff_added_when_block_not_in_map() -> None:
    diffs = diff_blocks(
        theirs_blocks=[{"block_id": "b1", "content": "新段落"}],
        block_map={},
    )
    assert len(diffs) == 1
    assert diffs[0].op == "added"
    assert diffs[0].feishu_block_id == "b1"
    assert diffs[0].content_hash == block_content_hash("新段落")


def test_diff_edited_when_hash_changed() -> None:
    block_map = {
        "b1": {"content_hash": block_content_hash("旧内容"), "db_ref": "ref1", "section": "human"}
    }
    diffs = diff_blocks(
        theirs_blocks=[{"block_id": "b1", "content": "新内容"}],
        block_map=block_map,
    )
    assert len(diffs) == 1
    d = diffs[0]
    assert d.op == "edited"
    assert d.feishu_block_id == "b1"
    assert d.db_ref == "ref1"
    assert d.section == "human"
    assert d.content_hash == block_content_hash("新内容")


def test_diff_deleted_when_mapped_block_gone() -> None:
    block_map = {
        "b1": {"content_hash": block_content_hash("内容"), "db_ref": "ref1", "section": "system"}
    }
    diffs = diff_blocks(theirs_blocks=[], block_map=block_map)
    assert len(diffs) == 1
    assert diffs[0].op == "deleted"
    assert diffs[0].feishu_block_id == "b1"
    assert diffs[0].db_ref == "ref1"


def test_diff_noop_when_hash_unchanged() -> None:
    h = block_content_hash("稳定内容")
    diffs = diff_blocks(
        theirs_blocks=[{"block_id": "b1", "content": "稳定内容"}],
        block_map={"b1": {"content_hash": h}},
    )
    assert diffs == []


def test_diff_mixed_add_edit_delete() -> None:
    block_map = {
        "keep": {"content_hash": block_content_hash("不变")},
        "edit": {"content_hash": block_content_hash("原"), "db_ref": "r-edit"},
        "gone": {"content_hash": block_content_hash("将删"), "db_ref": "r-gone"},
    }
    diffs = diff_blocks(
        theirs_blocks=[
            {"block_id": "keep", "content": "不变"},
            {"block_id": "edit", "content": "改后"},
            {"block_id": "new", "content": "全新"},
        ],
        block_map=block_map,
    )
    by = _ops(diffs)
    assert "added:new" in by
    assert "edited:edit" in by
    assert "deleted:gone" in by
    # keep 是 no-op，不产出。
    assert "edited:keep" not in by and "added:keep" not in by
    assert len(diffs) == 3


# ---- diff_blocks: 防御性 ----


def test_diff_skips_blocks_missing_id_without_raising() -> None:
    diffs = diff_blocks(
        theirs_blocks=[
            {"content": "无 id 脏块"},
            {"block_id": "", "content": "空 id"},
            "not-a-dict",  # type: ignore[list-item]
            {"block_id": "ok", "content": "正常"},
        ],
        block_map={},
    )
    assert len(diffs) == 1
    assert diffs[0].feishu_block_id == "ok"


def test_diff_empty_block_map_all_added() -> None:
    diffs = diff_blocks(
        theirs_blocks=[
            {"block_id": "a", "content": "1"},
            {"block_id": "b", "content": "2"},
        ],
        block_map=None,
    )
    assert {d.op for d in diffs} == {"added"}
    assert len(diffs) == 2


def test_diff_supports_bare_hash_map_entries() -> None:
    # block_map 值为裸 content_hash 字符串时也应正确判定。
    diffs = diff_blocks(
        theirs_blocks=[{"block_id": "b1", "content": "变了"}],
        block_map={"b1": block_content_hash("原始")},
    )
    assert len(diffs) == 1 and diffs[0].op == "edited"


# ---- three_way_merge: 真值表 ----


def test_merge_only_ours_changed_keeps_ours() -> None:
    # (base=X, theirs=X, ours=Y) → merged=Y，无冲突。
    r = three_way_merge(base="X", theirs="X", ours="Y")
    assert r == MergeResult(merged="Y", has_conflict=False, loser="")


def test_merge_only_theirs_changed_keeps_theirs() -> None:
    # (X, Z, X) → merged=Z，无冲突。
    r = three_way_merge(base="X", theirs="Z", ours="X")
    assert r.merged == "Z"
    assert r.has_conflict is False
    assert r.loser == ""


def test_merge_both_changed_conflict_feishu_wins_loser_captured() -> None:
    # (X, Z, Y), Z!=Y → 冲突，飞书优先 merged=Z，DB 落败 loser=Y（绝不丢）。
    r = three_way_merge(base="X", theirs="Z", ours="Y")
    assert r.merged == "Z"
    assert r.has_conflict is True
    assert r.loser == "Y"


def test_merge_no_change_keeps_base() -> None:
    # (X, X, X) → merged=X，无冲突。
    r = three_way_merge(base="X", theirs="X", ours="X")
    assert r == MergeResult(merged="X", has_conflict=False, loser="")


def test_merge_both_changed_to_same_no_conflict() -> None:
    # 两侧都改成相同内容 → 无冲突。
    r = three_way_merge(base="X", theirs="Z", ours="Z")
    assert r.merged == "Z"
    assert r.has_conflict is False
    assert r.loser == ""
