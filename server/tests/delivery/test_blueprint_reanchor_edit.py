"""批量重锚定 + 人工 block 编辑测试（Phase 114-04 Task 3，CLAR-02 / CLAR-03）。

守十件事（断言一律**从 DB 重读**，不信返回体）：

1. **精确命中保持 anchored 且 ``section_path`` 被刷新**——``reanchor`` 只改 ``block_id``、
   不刷 path（RESEARCH §4.2 指出的缺口），批量侧必须用 ``iter_blocks`` 的新 path 补上，
   否则 115 会把批注挂在错误的段落标题下。
2. **模糊命中换 ``block_id`` 且 ``quoted_text`` 逐字保留**（相似度用 ``difflib`` **现算**
   断言，不硬编码猜测值）。
3. ⭐ **失锚不删**：``anchor_status="orphaned"``、线程行仍在、``anchor`` 内容原样，且
   ``filter(anchor_status="orphaned")`` 能集中查到（CLAR-02 明令不得静默丢失）。
4. ⭐ **入参不被原地修改**：``reanchor`` 精确命中分支返回**同一对象**，实现里若漏拷贝就会
   原地写 ``section_path``——用 spy 记录「``reanchor`` 收到的 anchor 对象 + 其深拷贝」，
   调用后逐条比对；同时断言 ``new_content`` / ``old_content`` 未被改。
5. ⭐ **diff 预筛跳过（P3）且与全量重锚结果等价**：32 块 / 10 线程只改 1 块，传
   ``old_content`` 时 ``skipped >= 9``、不传时 ``skipped == 0``，**两种模式最终 anchor 逐字相同**。
6. **一次 ``bulk_update`` 且 ``updated_at`` 被更新**（``bulk_update`` 绕过 ``auto_now``，
   漏显式带就会相等 ⇒ 这条即红）。
7. **patch 三 op**：``replace`` / ``insert``(前后各一) / ``delete`` 各自落对，``rejected`` 为空。
8. ⭐ **不合法 content 被拒且版本数不变**：``status == "invalid"``、``detail`` 非空且不含
   植入的凭证样本、``ArtifactVersion`` 行数与调用前**相等**（不落半合法版本）。
9. ⭐ **同 ``content_hash`` 不翻版本**：同一 patch 连提两次，第二次 ``unchanged``。
10. **归属可审计 + 评审人 upsert**：``produced_by_ref == f"human_edit:{user.id}"``、
    ``BlueprintReviewer.first_action == "block_edit"``，重复编辑不覆盖首次 ``first_action``。

另附纯函数节自证：``apply_block_ops`` 不改入参、五类 ``reason`` 各有一例、恒不抛。

``async`` + ``sync_to_async`` 跨线程写库 → ``transaction=True``。
"""

from __future__ import annotations

import copy
import difflib
import uuid
from typing import Any
from unittest.mock import patch

import pytest

from delivery.models import (
    Artifact,
    ArtifactVersion,
    BlueprintReviewer,
    BlueprintThread,
    ThreadAnchorStatus,
    ThreadKind,
)
from delivery.services.artifact_service import ArtifactService
from delivery.services.blueprint_anchor import (
    SIMILARITY_THRESHOLD,
    _block_text,
    reanchor,
)
from delivery.services.blueprint_block_edit import (
    REASON_BLOCK_ID_IMMUTABLE,
    REASON_BLOCK_NOT_FOUND,
    REASON_MISSING_BLOCK,
    REASON_MISSING_BLOCK_ID,
    REASON_UNKNOWN_OP,
    aapply_block_edit,
    apply_block_ops,
)
from delivery.services.blueprint_lifecycle_service import BlueprintLifecycleService
from services.process_runtime.blueprint_schema import iter_blocks
from tests.helpers.blueprint_samples import make_blueprint

pytestmark = [pytest.mark.django_db(transaction=True), pytest.mark.asyncio]

_ANCHOR_TARGET = "blk_impl01_how"
# 足够长且独特：模糊匹配相似度才可控，且不会被其它块抢走最佳匹配
_LONG = (
    "在练习域新增按知识点生成习题的接口，复用既有题库模型与难度配置，"
    "并在生成失败时回落到静态题库，保证练习页不出现空列表。"
)
_UNRELATED = (
    "Runner 侧的容器调度需要在 Docker 与 k8s 两种后端之间做统一抽象，"
    "并把心跳与资源采样上报给服务端的观测面。"
)

_REANCHOR_TARGET = "delivery.services.blueprint_anchor.reanchor"


def _base_content() -> dict:
    """基线蓝图：把锚定目标块的正文换成 :data:`_LONG`（便于控制相似度）。"""
    content = make_blueprint()
    content["implementation_overview"]["items"][0]["how"][0]["text"] = _LONG
    return content


async def _make_blueprint_artifact(content: dict | None = None) -> Artifact:
    return await ArtifactService().create("technical_plan", content or _base_content())


async def _make_user() -> Any:
    from django.contrib.auth import get_user_model

    return await get_user_model().objects.acreate(username=f"u-{uuid.uuid4().hex[:6]}")


async def _open_anchored_thread(
    artifact: Artifact,
    *,
    block_id: str = _ANCHOR_TARGET,
    quoted_text: str = _LONG,
    section_path: str = "已过期的段落路径",
) -> BlueprintThread:
    return await BlueprintLifecycleService().open_thread(
        artifact,
        kind=ThreadKind.HUMAN_COMMENT,
        blocking=False,
        question="这一段的降级策略是否要写进验收标准？",
        anchor={
            "section_path": section_path,
            "block_id": block_id,
            "start_offset": 0,
            "end_offset": len(quoted_text),
            "quoted_text": quoted_text,
        },
    )


async def _reread(thread: BlueprintThread) -> BlueprintThread:
    return await BlueprintThread.objects.aget(id=thread.id)


def _path_of(content: dict, block_id: str) -> str:
    return next(path for path, block in iter_blocks(content) if block["block_id"] == block_id)


def _version_count(artifact: Artifact) -> Any:
    return ArtifactVersion.objects.filter(artifact=artifact).acount()


# ══════════════════════════════════════════════════════════════════════════
# 1-6：批量重锚定
# ══════════════════════════════════════════════════════════════════════════


async def test_exact_hit_stays_anchored_and_section_path_is_refreshed() -> None:
    """守 1：块还在但落位变了（item id 改名）⇒ anchored 且 section_path 被刷成新 path。"""
    artifact = await _make_blueprint_artifact()
    thread = await _open_anchored_thread(artifact)

    new_content = _base_content()
    new_content["implementation_overview"]["items"][0]["id"] = "impl_09"
    new_content["implementation_overview"]["items"][1]["depends_on"] = ["impl_09"]
    expected_path = _path_of(new_content, _ANCHOR_TARGET)
    assert expected_path == "implementation_overview.items[impl_09].how"

    counts = await BlueprintLifecycleService().areanchor_threads(artifact, new_content)

    assert counts == {"checked": 1, "reanchored": 1, "orphaned": 0, "skipped": 0}
    fresh = await _reread(thread)
    assert fresh.anchor_status == ThreadAnchorStatus.ANCHORED
    assert fresh.anchor["block_id"] == _ANCHOR_TARGET
    assert fresh.anchor["section_path"] == expected_path
    # 非 path 字段逐字保留（不是「重建一个新 anchor」）
    assert fresh.anchor["quoted_text"] == _LONG
    assert fresh.anchor["end_offset"] == len(_LONG)


async def test_fuzzy_rehit_rebinds_block_id_and_keeps_quoted_text() -> None:
    """守 2：block_id 消失但文本相似 ≥0.85 ⇒ 换 block_id、quoted_text 逐字不变。"""
    edited = _LONG + "（并发上限为 5 个请求。）"
    # 阈值用 difflib 现算断言，不硬编码猜测值
    assert difflib.SequenceMatcher(None, _LONG, edited).ratio() >= SIMILARITY_THRESHOLD

    artifact = await _make_blueprint_artifact()
    thread = await _open_anchored_thread(artifact)

    new_content = _base_content()
    target = new_content["implementation_overview"]["items"][0]["how"][0]
    target["block_id"] = "blk_impl01_how_v2"
    target["text"] = edited

    counts = await BlueprintLifecycleService().areanchor_threads(artifact, new_content)

    assert counts["reanchored"] == 1
    fresh = await _reread(thread)
    assert fresh.anchor_status == ThreadAnchorStatus.ANCHORED
    assert fresh.anchor["block_id"] == "blk_impl01_how_v2"
    assert fresh.anchor["quoted_text"] == _LONG  # 保留原文，不被改写后的正文覆盖
    assert fresh.anchor["section_path"] == _path_of(new_content, "blk_impl01_how_v2")


async def test_orphaned_thread_is_kept_and_centrally_queryable() -> None:
    """守 3：失锚 ⇒ orphaned + 线程行仍在 + anchor 原样 + 可集中查询（绝不删）。"""
    artifact = await _make_blueprint_artifact()
    thread = await _open_anchored_thread(artifact, block_id="blk_gone", quoted_text=_UNRELATED)
    before = copy.deepcopy((await _reread(thread)).anchor)

    new_content = _base_content()
    blocks = [block for _path, block in iter_blocks(new_content)]
    # 前提用 difflib 现算坐实：没有任何块够得上阈值（否则本用例恒真）
    best_ratio = max(
        difflib.SequenceMatcher(None, _UNRELATED, _block_text(block)).ratio() for block in blocks
    )
    assert best_ratio < SIMILARITY_THRESHOLD

    counts = await BlueprintLifecycleService().areanchor_threads(artifact, new_content)

    assert counts == {"checked": 1, "reanchored": 0, "orphaned": 1, "skipped": 0}
    fresh = await _reread(thread)
    assert fresh.anchor_status == ThreadAnchorStatus.ORPHANED
    assert fresh.anchor == before  # anchor 内容原样保留，不被清空
    assert await BlueprintThread.objects.filter(id=thread.id).acount() == 1
    orphaned = [
        str(row.id)
        async for row in BlueprintThread.objects.filter(
            artifact=artifact, anchor_status=ThreadAnchorStatus.ORPHANED
        )
    ]
    assert orphaned == [str(thread.id)]


async def test_threads_without_any_locator_are_skipped_not_marked_orphaned() -> None:
    """⭐ MJ-02 回归：**本来就没 anchor** 的线程不参与重锚，``anchor_status`` 保持原值。

    ``blueprint_anchor.reanchor`` 的第一条分支把「anchor 非 dict / 为空」直接判 orphaned
    ——那对单条重锚是对的（调用方本该只拿有锚点的线程来问），但批量层取的是该 artifact
    的**全量线程**。本仓大量线程天然无 anchor：``_abp_ensure_blocking_clarification``
    开的「自动推进在 X 阶段停下了」线程、112 的规格门/确认门线程、用户没划线时的驳回
    评论线程、以及无 ``block_id`` 的 finding 线程（anchor 三键全空串）。

    而 ``areanchor_threads`` 挂在**每一条产版本路径**上 ⇒ 修前这些线程必然且持久地被标成
    ``orphaned``，把 CLAR-02 唯一的呈现面 ``orphaned_threads`` 淹成噪声，真正「块被删掉
    导致批注错位」的那几条反而找不到。
    """
    artifact = await _make_blueprint_artifact()
    lifecycle = BlueprintLifecycleService()
    # ① 完全无 anchor（系统线程的典型形状）
    system_thread = await lifecycle.open_thread(
        artifact,
        kind=ThreadKind.AI_CLARIFICATION,
        blocking=True,
        question="自动推进在 merge 阶段停下了（原因：deps_unavailable），需要你处置后再继续。",
    )
    # ② anchor 是 dict 但三键全空串（114-03 对无 block_id finding 开线程的形状）
    keyless_thread = await lifecycle.open_thread(
        artifact,
        kind=ThreadKind.AI_CLARIFICATION,
        blocking=False,
        question="[goal_backward_unavailable] goal-backward 审查未能执行",
        anchor={"section_path": "", "block_id": "", "quoted_text": ""},
    )
    before = {
        str(system_thread.id): (await _reread(system_thread)).anchor_status,
        str(keyless_thread.id): (await _reread(keyless_thread)).anchor_status,
    }

    counts = await BlueprintLifecycleService().areanchor_threads(artifact, _base_content())

    assert counts == {"checked": 2, "reanchored": 0, "orphaned": 0, "skipped": 2}
    for thread in (system_thread, keyless_thread):
        fresh = await _reread(thread)
        assert fresh.anchor_status == before[str(thread.id)]
    assert (
        await BlueprintThread.objects.filter(
            artifact=artifact, anchor_status=ThreadAnchorStatus.ORPHANED
        ).acount()
        == 0
    )


async def test_a_thread_with_a_real_but_deleted_anchor_still_becomes_orphaned() -> None:
    """MJ-02 非恒真对照：**有**锚点却锚不上（块被删且无相似块）⇒ 仍必须落 orphaned。

    与上一条并列——跳过判据只能筛掉「没有可锚定位」的线程，绝不能把「真失锚」一起放过，
    否则 CLAR-02 的失锚清单就成了恒空。
    """
    artifact = await _make_blueprint_artifact()
    thread = await _open_anchored_thread(artifact, block_id="blk_gone", quoted_text=_UNRELATED)
    keyless = await BlueprintLifecycleService().open_thread(
        artifact,
        kind=ThreadKind.HUMAN_COMMENT,
        blocking=False,
        question="没划线的评论",
    )

    counts = await BlueprintLifecycleService().areanchor_threads(artifact, _base_content())

    assert counts == {"checked": 2, "reanchored": 0, "orphaned": 1, "skipped": 1}
    assert (await _reread(thread)).anchor_status == ThreadAnchorStatus.ORPHANED
    assert (await _reread(keyless)).anchor_status != ThreadAnchorStatus.ORPHANED


async def test_reanchor_never_mutates_the_anchor_it_receives() -> None:
    """守 4：精确命中分支 ``reanchor`` 返回同一对象 ⇒ 实现必须先拷贝再写 section_path。"""
    artifact = await _make_blueprint_artifact()
    await _open_anchored_thread(artifact)

    seen: list[tuple[dict, dict]] = []

    def _spy(anchor: Any, new_blocks: Any) -> Any:
        if isinstance(anchor, dict):
            seen.append((anchor, copy.deepcopy(anchor)))
        return reanchor(anchor, new_blocks)

    new_content = _base_content()
    new_content["implementation_overview"]["items"][0]["id"] = "impl_09"
    new_content["implementation_overview"]["items"][1]["depends_on"] = ["impl_09"]
    old_content = _base_content()
    new_snapshot = copy.deepcopy(new_content)
    old_snapshot = copy.deepcopy(old_content)

    with patch(_REANCHOR_TARGET, _spy):
        await BlueprintLifecycleService().areanchor_threads(artifact, new_content, old_content=None)

    assert seen, "reanchor 未被调用 ⇒ 本用例失去意义"
    for received, snapshot in seen:
        assert received == snapshot, "reanchor 收到的 anchor 被原地修改了（漏拷贝）"
    assert new_content == new_snapshot  # 入参 content 也不被原地改
    assert old_content == old_snapshot


async def test_diff_prefilter_skips_untouched_threads_and_matches_full_scan() -> None:
    """守 5：只改 1 块 ⇒ 预筛把其余线程直接 skipped，且两种模式最终 anchor 逐字相同。"""
    block_ids = [block["block_id"] for _path, block in iter_blocks(_base_content())][:10]
    assert len(block_ids) == 10

    def _changed_content() -> dict:
        content = _base_content()
        content["impact_analysis"]["rollback_plan"][0]["text"] = "改为按开关分级回滚。"
        return content

    async def _run(prefiltered: bool) -> tuple[dict, dict]:
        artifact = await _make_blueprint_artifact()
        threads = [
            await _open_anchored_thread(artifact, block_id=bid, quoted_text=_UNRELATED)
            for bid in block_ids
        ]
        new_content = _changed_content()
        counts = await BlueprintLifecycleService().areanchor_threads(
            artifact,
            new_content,
            old_content=_base_content() if prefiltered else None,
        )
        anchors = {}
        for thread in threads:
            fresh = await _reread(thread)
            anchors[fresh.anchor["block_id"]] = (fresh.anchor, fresh.anchor_status)
        return counts, anchors

    prefiltered_counts, prefiltered_anchors = await _run(True)
    full_counts, full_anchors = await _run(False)

    assert prefiltered_counts["checked"] == 10
    assert prefiltered_counts["skipped"] >= 9  # 未落在变动块上的线程一律跳过
    assert full_counts["skipped"] == 0  # old_content 缺省 ⇒ 全量重锚（正确性优先）
    # ⭐ 预筛不改变正确性：两种模式的最终 anchor 与状态逐字一致
    assert prefiltered_anchors == full_anchors


async def test_bulk_update_refreshes_updated_at() -> None:
    """守 6：``bulk_update`` 绕过 ``auto_now`` ⇒ 实现漏显式带 ``updated_at`` 这条即红。"""
    artifact = await _make_blueprint_artifact()
    thread = await _open_anchored_thread(artifact, block_id="blk_gone", quoted_text=_UNRELATED)
    before = (await _reread(thread)).updated_at

    await BlueprintLifecycleService().areanchor_threads(artifact, _base_content())

    after = (await _reread(thread)).updated_at
    assert after > before


async def test_areanchor_returns_constant_four_keys_and_never_raises() -> None:
    """恒定四键 + 非 dict content / 无线程都不抛（best-effort，绝不反噬编辑成功）。"""
    artifact = await _make_blueprint_artifact()
    keys = {"checked", "reanchored", "orphaned", "skipped"}

    empty = await BlueprintLifecycleService().areanchor_threads(artifact, _base_content())
    assert set(empty) == keys and empty["checked"] == 0

    for bad in (None, "x", 123, []):
        result = await BlueprintLifecycleService().areanchor_threads(artifact, bad)  # type: ignore[arg-type]
        assert set(result) == keys
        assert all(value == 0 for value in result.values())


# ══════════════════════════════════════════════════════════════════════════
# 7-10：人工 block 编辑
# ══════════════════════════════════════════════════════════════════════════


async def test_patch_three_ops_land_correctly() -> None:
    """守 7：replace / insert(前后) / delete 三 op 各自落对且 ``rejected`` 为空。"""
    artifact = await _make_blueprint_artifact()
    user = await _make_user()

    replaced = await aapply_block_edit(
        artifact,
        [
            {
                "op": "replace",
                "block_id": _ANCHOR_TARGET,
                "block": {
                    "block_id": _ANCHOR_TARGET,
                    "type": "paragraph",
                    "text": "改为按知识点批量生成，单次上限 20 题。",
                },
            }
        ],
        user=user,
    )
    assert replaced["status"] == "applied"
    assert replaced["rejected"] == []
    version = await ArtifactVersion.objects.aget(id=replaced["version_id"])
    how = version.content["implementation_overview"]["items"][0]["how"]
    assert how[0]["block_id"] == _ANCHOR_TARGET  # block_id 不变
    assert how[0]["text"] == "改为按知识点批量生成，单次上限 20 题。"

    inserted = await aapply_block_edit(
        artifact,
        [
            {
                "op": "insert",
                "block_id": _ANCHOR_TARGET,
                "position": "after",
                "block": {"block_id": "blk_after", "type": "paragraph", "text": "补充：后置说明。"},
            },
            {
                "op": "insert",
                "block_id": _ANCHOR_TARGET,
                "position": "before",
                "block": {
                    "block_id": "blk_before",
                    "type": "paragraph",
                    "text": "补充：前置说明。",
                },
            },
        ],
        user=user,
    )
    assert inserted["status"] == "applied"
    assert inserted["rejected"] == []
    version = await ArtifactVersion.objects.aget(id=inserted["version_id"])
    order = [
        block["block_id"] for block in version.content["implementation_overview"]["items"][0]["how"]
    ]
    assert order == ["blk_before", _ANCHOR_TARGET, "blk_after", "blk_impl01_pseudo"]

    deleted = await aapply_block_edit(
        artifact, [{"op": "delete", "block_id": "blk_impl01_pseudo"}], user=user
    )
    assert deleted["status"] == "applied"
    assert deleted["rejected"] == []
    version = await ArtifactVersion.objects.aget(id=deleted["version_id"])
    order = [
        block["block_id"] for block in version.content["implementation_overview"]["items"][0]["how"]
    ]
    assert "blk_impl01_pseudo" not in order


async def test_invalid_edit_is_rejected_without_creating_a_version() -> None:
    """守 8：编辑后不过 ``validate_blueprint`` ⇒ invalid + 版本行数不变（不落半合法版本）。"""
    artifact = await _make_blueprint_artifact()
    before = await _version_count(artifact)
    planted = "sk-live-PLANTED-CREDENTIAL-SAMPLE"

    # 缺 `type` 必填字段 ⇒ jsonschema 直接失败
    result = await aapply_block_edit(
        artifact,
        [
            {
                "op": "replace",
                "block_id": _ANCHOR_TARGET,
                "block": {"block_id": _ANCHOR_TARGET, "text": planted},
            }
        ],
    )

    assert result["status"] == "invalid"
    assert result["detail"]
    assert planted not in result["detail"]  # 错因不回显被校验实例的正文
    assert await _version_count(artifact) == before


async def test_hard_rejects_do_not_create_a_version() -> None:
    """结构性硬失败（找不到 block_id）⇒ rejected 且版本行数不变。"""
    artifact = await _make_blueprint_artifact()
    before = await _version_count(artifact)

    result = await aapply_block_edit(artifact, [{"op": "delete", "block_id": "blk_不存在"}])

    assert result["status"] == "rejected"
    assert [item["reason"] for item in result["rejected"]] == [REASON_BLOCK_NOT_FOUND]
    assert await _version_count(artifact) == before


async def test_same_content_hash_does_not_bump_version() -> None:
    """守 9：同一 patch 连提两次 ⇒ 第二次 unchanged、``version_no`` 不推进、行数不变。"""
    artifact = await _make_blueprint_artifact()
    ops = [
        {
            "op": "replace",
            "block_id": _ANCHOR_TARGET,
            "block": {"block_id": _ANCHOR_TARGET, "type": "paragraph", "text": "幂等口径验证。"},
        }
    ]

    first = await aapply_block_edit(artifact, ops)
    count_after_first = await _version_count(artifact)
    second = await aapply_block_edit(artifact, ops)

    assert first["status"] == "applied"
    assert second["status"] == "unchanged"
    assert second["version_no"] == first["version_no"]
    assert second["version_id"] == first["version_id"]
    assert await _version_count(artifact) == count_after_first


async def test_edit_is_auditable_and_upserts_reviewer() -> None:
    """守 10：``produced_by_ref == human_edit:{user.id}``、评审人 upsert 且不覆盖首次动作。"""
    artifact = await _make_blueprint_artifact()
    user = await _make_user()
    # 该用户已因「最终确认」进过名单 ⇒ 后续 block_edit 不得覆盖 first_action
    await BlueprintLifecycleService().add_reviewer(artifact, user, "final_approve")

    result = await aapply_block_edit(
        artifact,
        [
            {
                "op": "replace",
                "block_id": _ANCHOR_TARGET,
                "block": {"block_id": _ANCHOR_TARGET, "type": "paragraph", "text": "归属可审计。"},
            }
        ],
        user=user,
    )

    assert result["status"] == "applied"
    version = await ArtifactVersion.objects.aget(id=result["version_id"])
    assert version.produced_by_ref == f"human_edit:{user.id}"
    reviewer = await BlueprintReviewer.objects.aget(artifact=artifact, user=user)
    assert reviewer.first_action == "final_approve"  # aget_or_create 不覆盖

    other = await _make_user()
    await aapply_block_edit(
        artifact, [{"op": "delete", "block_id": "blk_impl01_pseudo"}], user=other
    )
    fresh = await BlueprintReviewer.objects.aget(artifact=artifact, user=other)
    assert fresh.first_action == "block_edit"


async def test_edit_reanchors_threads_in_the_same_call() -> None:
    """编辑成功后自动重锚定：删掉带批注的块 ⇒ 该线程失锚但仍在。"""
    artifact = await _make_blueprint_artifact()
    thread = await _open_anchored_thread(
        artifact, block_id="blk_impl01_pseudo", quoted_text=_UNRELATED
    )

    result = await aapply_block_edit(artifact, [{"op": "delete", "block_id": "blk_impl01_pseudo"}])

    assert result["status"] == "applied"
    assert result["reanchor"]["checked"] == 1
    assert (await _reread(thread)).anchor_status == ThreadAnchorStatus.ORPHANED
    assert await BlueprintThread.objects.filter(id=thread.id).acount() == 1


async def test_edit_without_any_version_is_invalid() -> None:
    """无版本的 artifact 不可编辑（返回 invalid 而不是抛）。"""
    artifact = await Artifact.objects.acreate(artifact_type="technical_plan")

    result = await aapply_block_edit(artifact, [{"op": "delete", "block_id": "x"}])

    assert result["status"] == "invalid"
    assert "尚无版本" in result["detail"]


# ══════════════════════════════════════════════════════════════════════════
# 纯函数节自证（无 DB）
# ══════════════════════════════════════════════════════════════════════════


async def test_apply_block_ops_is_pure_and_reports_every_reason() -> None:
    """入参不被原地修改；五类 ``reason`` 各有一例；未知 op 不静默跳过。"""
    content = _base_content()
    snapshot = copy.deepcopy(content)

    out, rejected = apply_block_ops(
        content,
        [
            {"op": "frobnicate", "block_id": _ANCHOR_TARGET},
            {"op": "delete", "block_id": "blk_不存在"},
            {"op": "replace", "block_id": _ANCHOR_TARGET},
            {"op": "insert", "block_id": _ANCHOR_TARGET, "block": {"type": "paragraph"}},
            {
                "op": "replace",
                "block_id": _ANCHOR_TARGET,
                "block": {"block_id": "被改掉的 id", "type": "paragraph", "text": "正文"},
            },
        ],
    )

    assert content == snapshot  # 纯函数：入参逐字不变
    assert [item["reason"] for item in rejected] == [
        REASON_UNKNOWN_OP,
        REASON_BLOCK_NOT_FOUND,
        REASON_MISSING_BLOCK,
        REASON_MISSING_BLOCK_ID,
        REASON_BLOCK_ID_IMMUTABLE,
    ]
    # block_id_immutable 是**提示级**：替换照常发生，但 id 以原 id 为准
    replaced = out["implementation_overview"]["items"][0]["how"][0]
    assert replaced["block_id"] == _ANCHOR_TARGET
    assert replaced["text"] == "正文"


async def test_apply_block_ops_never_raises_on_garbage() -> None:
    """半可信输入恒不抛，且始终返回 ``(dict, list)``。"""
    for content in (None, {}, "x", 123, []):
        for ops in (None, "x", 42, [None], [{"op": None}]):
            out, rejected = apply_block_ops(content, ops)  # type: ignore[arg-type]
            assert isinstance(out, dict)
            assert isinstance(rejected, list)
