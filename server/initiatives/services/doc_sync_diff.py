"""飞书↔Friday 同步引擎的纯算法层：block_id 结构化 diff + 三方合并 + 内容指纹。

本模块**纯函数、零副作用**——不 import structlog / ORM(`.objects`) / httpx，
不打日志、不入库、不外呼。所有 IO（回拉飞书正文、写映射表/留痕、缓存失效、外呼飞书）
收口在下游 ``DocSyncService``（Wave 2+），故本层可在无 DB / 无网络下被
``tests/initiatives/test_doc_sync_diff.py`` 快速单测（SYNC-03/04 核心算法）。

核心策略（CONTEXT 锁定）：
- **block_id 结构化逐块匹配**代替整篇文本 diff：飞书侧每个 block 有稳定 ``block_id``，
  对照 ``ProjectDocBlockMap``（``feishu_block_id`` ↔ ``content_hash``）逐块判定新增/编辑/删除。
- **三方合并 + capture-never-clobber**：真同块两侧都改时，飞书侧（theirs）优先保留为
  ``merged``，DB 侧（ours）落败内容放入 ``loser``（下游经
  ``ProjectDocService.capture_block_revision`` 留痕），**绝不静默丢用户内容**（SYNC-04）。
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass

__all__ = [
    "BlockDiff",
    "MergeResult",
    "block_content_hash",
    "diff_blocks",
    "three_way_merge",
]

# 新增 block 缺映射时的默认区段（与 ``DocSection.SYSTEM`` 取值一致；此处用字面量避免引入 ORM 依赖）。
_DEFAULT_SECTION = "system"


def block_content_hash(text: str) -> str:
    """对 block 文本做归一化（折叠空白）后取 sha256 十六进制摘要，幂等且稳定。

    归一化（``str.split()`` 折叠所有连续空白 + 去首尾）让"仅空白/换行差异"不被误判为编辑，
    与 ``ProjectDocBlockMap.content_hash``（``max_length=128``）落库口径一致。
    """
    normalized = " ".join((text or "").split())
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class BlockDiff:
    """单个 block 的结构化变更（``op`` ∈ {added, edited, deleted}）。"""

    op: str
    feishu_block_id: str
    db_ref: str
    section: str
    content: str
    content_hash: str


@dataclass(frozen=True)
class MergeResult:
    """三方合并结果：``merged`` 为最终保留内容；``has_conflict`` 标相交冲突；
    ``loser`` 为落败方内容（非空时下游必须 capture 留痕，绝不丢弃）。"""

    merged: str
    has_conflict: bool
    loser: str = ""


def _block_id_of(block: dict) -> str:
    """防御性提取 block_id（兼容 ``block_id`` / ``feishu_block_id`` 两种键名）。"""
    return str(block.get("block_id") or block.get("feishu_block_id") or "")


def _mapped_hash(mapped: object) -> str:
    """从映射条目取已知 content_hash（兼容 dict 形态与裸字符串形态）。"""
    if isinstance(mapped, dict):
        return str(mapped.get("content_hash", "") or "")
    return str(mapped or "")


def _mapped_field(mapped: object, key: str, default: str = "") -> str:
    if isinstance(mapped, dict):
        return str(mapped.get(key, default) or default)
    return default


def diff_blocks(
    *,
    base_snapshot: str = "",
    theirs_blocks: list[dict] | None = None,
    block_map: dict[str, object] | None = None,
) -> list[BlockDiff]:
    """block_id 结构化 diff：对照 ``block_map`` 判定飞书侧（theirs）的新增/编辑/删除。

    判定规则（Pattern 3）：
    - block_id 不在 ``block_map`` → ``added``（用户在飞书新增）。
    - 在 ``block_map`` 且 ``content_hash`` 变 → ``edited``（用户在飞书编辑）。
    - 在 ``block_map`` 但飞书已无 → ``deleted``（用户在飞书删除）。
    - 在 ``block_map`` 且 ``content_hash`` 未变 → no-op（不产出 diff）。

    入参说明（均为纯数据，无 ORM）：
    - ``base_snapshot``：最近同步快照（base），保留入参以备下游 rebase 上下文，本结构化
      diff 不依赖其内容（变更判定以稳定的 block_id + content_hash 为准）。
    - ``theirs_blocks``：飞书回拉的 block 列表，每项至少含 ``block_id`` 与 ``content``。
    - ``block_map``：``{feishu_block_id: {"content_hash", "db_ref", "section"}}``（或裸
      ``content_hash`` 字符串），来自 ``ProjectDocBlockMap``。

    纯函数无副作用；缺 block_id 的脏块**跳过不抛**；``block_map`` 为空 → 全部判为 ``added``。
    """
    _ = base_snapshot  # base 由下游 rebase 使用；结构化 diff 以 block_id + hash 为准
    blocks = theirs_blocks or []
    mapping: dict[str, object] = block_map or {}

    diffs: list[BlockDiff] = []
    seen_ids: set[str] = set()

    for block in blocks:
        if not isinstance(block, dict):
            continue  # 脏数据跳过，绝不抛
        block_id = _block_id_of(block)
        if not block_id:
            continue  # 缺 block_id 跳过（防御性，半可信外部内容）
        seen_ids.add(block_id)

        content = str(block.get("content", "") or "")
        new_hash = block_content_hash(content)
        mapped = mapping.get(block_id)

        if mapped is None:
            # 新增：映射表里没有这个 block_id。
            section = str(block.get("section") or _DEFAULT_SECTION)
            db_ref = str(block.get("db_ref", "") or "")
            diffs.append(
                BlockDiff(
                    op="added",
                    feishu_block_id=block_id,
                    db_ref=db_ref,
                    section=section,
                    content=content,
                    content_hash=new_hash,
                )
            )
            continue

        if _mapped_hash(mapped) != new_hash:
            # 编辑：已知 block_id，但内容指纹变了。
            diffs.append(
                BlockDiff(
                    op="edited",
                    feishu_block_id=block_id,
                    db_ref=_mapped_field(mapped, "db_ref"),
                    section=_mapped_field(mapped, "section", _DEFAULT_SECTION),
                    content=content,
                    content_hash=new_hash,
                )
            )
        # else: 指纹未变 → no-op，不产出 diff。

    # 删除：映射表里有、但飞书侧已无的 block_id。
    for block_id, mapped in mapping.items():
        bid = str(block_id)
        if bid in seen_ids:
            continue
        diffs.append(
            BlockDiff(
                op="deleted",
                feishu_block_id=bid,
                db_ref=_mapped_field(mapped, "db_ref"),
                section=_mapped_field(mapped, "section", _DEFAULT_SECTION),
                content="",
                content_hash=_mapped_hash(mapped),
            )
        )

    return diffs


def three_way_merge(*, base: str, theirs: str, ours: str) -> MergeResult:
    """单块三方合并（base=最近同步 / theirs=飞书 / ours=DB），飞书侧优先 + capture-never-clobber。

    真值表（按块整体比对，SYNC-04 + Pitfall 5）：
    - base==theirs==ours → 都没改 → ``merged=base``，无冲突。
    - base==theirs, ours 变 → 仅 DB 改 → ``merged=ours``，无冲突。
    - base==ours, theirs 变 → 仅飞书改 → ``merged=theirs``，无冲突。
    - 两侧都改且 theirs==ours → 改成了相同内容 → ``merged=theirs``，无冲突。
    - 两侧都改且 theirs!=ours → 相交冲突 → ``merged=theirs``（飞书优先），
      ``has_conflict=True``，``loser=ours``（落败方交下游 capture 留痕，**绝不静默丢**）。
    """
    base_s = base or ""
    theirs_s = theirs or ""
    ours_s = ours or ""

    theirs_changed = theirs_s != base_s
    ours_changed = ours_s != base_s

    if not theirs_changed and not ours_changed:
        return MergeResult(merged=base_s, has_conflict=False)
    if theirs_changed and not ours_changed:
        return MergeResult(merged=theirs_s, has_conflict=False)
    if not theirs_changed and ours_changed:
        return MergeResult(merged=ours_s, has_conflict=False)

    # 两侧都改：内容相同则无冲突；否则飞书优先，DB 落败留痕。
    if theirs_s == ours_s:
        return MergeResult(merged=theirs_s, has_conflict=False)
    return MergeResult(merged=theirs_s, has_conflict=True, loser=ours_s)
