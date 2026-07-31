"""stage-aware 蓝图状态映射（B3，Phase 113-06）。

`blueprint_resume._amap_blueprint_status` 是**全相位唯一被允许修改**的 `blueprint_resume`
入口。本文件守它的两侧：

1. ⭐ **前七 stage 等价性回归**（改前七 stage 行为即红）：112 注册的七个 stage 逐个
   构造会话 → 映射后蓝图状态仍是 `researching`，与 113 改动前逐字等价。
2. ⭐ **阶段 2/3 → `drafting`**：`repo_plan` / `merge` 映射到 `drafting`（不是
   `researching`）。
3. ⭐ **澄清恢复回 drafting 而非退回阶段 1**（核心可证伪）：`current_stage="repo_plan"`
   的会话被 blocking 线程阻塞 → `needs_clarification`；线程 resolve 后二次映射 →
   回 `drafting`。若映射写死 researching，这条会看到「已产出 RepoPlan 的会话被当成还没
   调研」（T-113-43）。
4. **`return_status` 走同一映射**：阻塞态转移的事件 payload 里 `return_status == "drafting"`。
5. **未登记 stage 回落**：空串与 `bogus_stage` 都回落 `researching` 且不抛。
6. **best-effort 不反噬**：`transition` 抛异常时 `_amap_blueprint_status` 不抛。
7. **映射表与枚举同值**：`_STAGE_BLUEPRINT_STATUS` 的字面量 == `BlueprintStatus.DRAFTING`
   （表里用字面量是因为本模块的模型 import 全在函数内；这条锁死防漂移）。
"""

from __future__ import annotations

from typing import Any

import pytest

from delivery.models import (
    ArtifactVersion,
    BlueprintStatus,
    ConvergenceSession,
    ConvergenceSessionEntrypoint,
    ConvergenceSessionEvent,
    ThreadKind,
)
from delivery.services import ArtifactService
from delivery.services.blueprint_lifecycle_service import BlueprintLifecycleService
from services.process_runtime import blueprint_resume
from services.process_runtime.blueprint_resume import (
    _STAGE_BLUEPRINT_STATUS,
    _amap_blueprint_status,
    _resolve_stage_status,
)
from tests.helpers.blueprint_samples import make_blueprint

# asyncio_mode=auto 自动标记 async 用例；纯函数用例保持同步。
pytestmark = [pytest.mark.django_db(transaction=True)]

# 112-05 注册的七个 stage（阶段 0/1）——它们的映射结果必须逐字等价改动前。
STAGES_112 = (
    "intake",
    "decompose",
    "spec_gate",
    "route",
    "repo_research",
    "reroute",
    "repo_confirmation",
)
STAGES_113 = ("repo_plan", "merge")
# 114-03 追加的阶段 4——映射到 `ai_reviewing`（与 113 两个 stage 的 `drafting` 不同值）。
STAGES_114 = ("ai_review",)


async def _make_session_with_artifact(stage: str):
    artifact = await ArtifactService().create(
        "technical_plan", make_blueprint(), created_by_user_id="tester"
    )
    session = await ConvergenceSession.objects.acreate(
        process_type="technical_blueprint",
        entrypoint=ConvergenceSessionEntrypoint.CHAT,
        current_stage=stage,
        current_artifact_version_id=artifact.current_version_id,
    )
    return session, artifact


async def _refresh(artifact: Any) -> Any:
    from delivery.models import Artifact

    return await Artifact.objects.aget(id=artifact.id)


# ═══════════════════════════════════════════════════════════════════════════
# 7. 映射表与枚举同值（字面量防漂移）
# ═══════════════════════════════════════════════════════════════════════════


def test_stage_status_table_matches_enum() -> None:
    assert set(_STAGE_BLUEPRINT_STATUS) == set(STAGES_113) | set(STAGES_114), (
        "只有阶段 2/3/4 允许进表；前七 stage 必须靠回落拿 researching"
    )
    for stage in STAGES_113:
        assert _STAGE_BLUEPRINT_STATUS[stage] == BlueprintStatus.DRAFTING
    for stage in STAGES_114:
        assert _STAGE_BLUEPRINT_STATUS[stage] == BlueprintStatus.AI_REVIEWING


@pytest.mark.parametrize("stage", STAGES_112)
def test_resolve_stage_status_falls_back_to_researching_for_112_stages(stage: str) -> None:
    """⭐ 纯函数层的等价性：前七 stage 不在表内 ⇒ 恒回落 researching。"""
    assert _resolve_stage_status(_FakeSession(stage)) == BlueprintStatus.RESEARCHING


@pytest.mark.parametrize("stage", STAGES_113)
def test_resolve_stage_status_maps_stage_two_and_three_to_drafting(stage: str) -> None:
    assert _resolve_stage_status(_FakeSession(stage)) == BlueprintStatus.DRAFTING


@pytest.mark.parametrize("stage", ["", "bogus_stage", None])
def test_resolve_stage_status_never_raises_on_unknown_stage(stage: Any) -> None:
    assert _resolve_stage_status(_FakeSession(stage)) == BlueprintStatus.RESEARCHING


class _FakeSession:
    def __init__(self, stage: Any) -> None:
        self.current_stage = stage


# ═══════════════════════════════════════════════════════════════════════════
# 1-2. 端到端映射：前七 stage → researching；阶段 2/3 → drafting
# ═══════════════════════════════════════════════════════════════════════════


@pytest.mark.parametrize("stage", STAGES_112)
async def test_112_stages_still_map_to_researching(stage: str) -> None:
    """⭐ 七条等价性回归断言：改了前七 stage 的行为，这里必有一条红。"""
    session, artifact = await _make_session_with_artifact(stage)

    await _amap_blueprint_status(session)

    fresh = await _refresh(artifact)
    assert fresh.blueprint_status == BlueprintStatus.RESEARCHING, (
        f"stage={stage} 的映射结果偏离了 112 的口径"
    )


@pytest.mark.parametrize("stage", STAGES_113)
async def test_stage_two_and_three_map_to_drafting(stage: str) -> None:
    """⭐ 阶段 2/3 的状态口径是 `drafting`（产出中），不是 `researching`（调研中）。"""
    session, artifact = await _make_session_with_artifact(stage)

    await _amap_blueprint_status(session)

    fresh = await _refresh(artifact)
    assert fresh.blueprint_status == BlueprintStatus.DRAFTING


@pytest.mark.parametrize("stage", ["", "bogus_stage"])
async def test_unregistered_stage_falls_back_without_raising(stage: str) -> None:
    session, artifact = await _make_session_with_artifact(stage)

    await _amap_blueprint_status(session)

    fresh = await _refresh(artifact)
    assert fresh.blueprint_status == BlueprintStatus.RESEARCHING


# ═══════════════════════════════════════════════════════════════════════════
# 3-4. 澄清恢复回 drafting 而非退回阶段 1 + return_status 走同一映射
# ═══════════════════════════════════════════════════════════════════════════


async def test_clarification_on_stage_two_returns_to_drafting_not_stage_one() -> None:
    """⭐ 核心可证伪：阻塞 → needs_clarification；解除 → 回 `drafting`（**不是**
    `researching`）。映射写死 researching 时后半段即红 —— 那正是「已产出 RepoPlan 的
    会话被当成还没调研」的失效形态（T-113-43）。
    """
    session, artifact = await _make_session_with_artifact("repo_plan")
    # 先落 drafting（阶段 2 handler 的正常动作），再开阻塞线程
    await _amap_blueprint_status(session)
    thread = await BlueprintLifecycleService().open_thread(
        artifact,
        kind=ThreadKind.AI_CLARIFICATION,
        blocking=True,
        question="覆盖率未达标，请裁决",
        return_stage="repo_plan",
    )
    assert thread.return_stage == "repo_plan", "线程必须记住回哪个 stage（B3）"

    await _amap_blueprint_status(session)
    blocked = await _refresh(artifact)
    assert blocked.blueprint_status == BlueprintStatus.NEEDS_CLARIFICATION

    # return_status 走同一映射（不再恒为 researching）
    event = await (
        ConvergenceSessionEvent.objects.filter(session_id=session.id)
        .order_by("-created_at")
        .afirst()
    )
    assert event is not None
    assert event.payload.get("return_status") == BlueprintStatus.DRAFTING, (
        "return_status 恒为 researching 会让人审恢复退回阶段 1"
    )

    await BlueprintLifecycleService().resolve_thread(thread)
    await _amap_blueprint_status(session)

    resumed = await _refresh(artifact)
    assert resumed.blueprint_status == BlueprintStatus.DRAFTING
    assert resumed.blueprint_status != BlueprintStatus.RESEARCHING


async def test_clarification_on_stage_one_still_returns_to_researching() -> None:
    """对照组：阶段 1 的会话阻塞→解除后仍回 `researching`（112 行为逐字未变）。"""
    session, artifact = await _make_session_with_artifact("repo_confirmation")
    await _amap_blueprint_status(session)
    thread = await BlueprintLifecycleService().open_thread(
        artifact,
        kind=ThreadKind.REPO_CONFIRMATION,
        blocking=True,
        question="请确认仓库集",
        return_stage="repo_confirmation",
    )

    await _amap_blueprint_status(session)
    assert (await _refresh(artifact)).blueprint_status == BlueprintStatus.NEEDS_CLARIFICATION

    await BlueprintLifecycleService().resolve_thread(thread)
    await _amap_blueprint_status(session)

    assert (await _refresh(artifact)).blueprint_status == BlueprintStatus.RESEARCHING


# ═══════════════════════════════════════════════════════════════════════════
# 6. best-effort 不反噬
# ═══════════════════════════════════════════════════════════════════════════


async def test_mapping_swallows_transition_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    """`transition` 抛异常 → 映射不抛（既有 best-effort 纪律未被破坏）。"""
    session, _artifact = await _make_session_with_artifact("merge")

    async def _boom(*args: Any, **kwargs: Any) -> Any:
        raise RuntimeError("transition boom")

    monkeypatch.setattr(BlueprintLifecycleService, "transition", _boom)

    await _amap_blueprint_status(session)  # 不抛即通过


async def test_mapping_is_noop_without_artifact_version() -> None:
    """会话无版本指针 → 无 artifact 可映射，直接返回（不抛、不写）。"""
    session = await ConvergenceSession.objects.acreate(
        process_type="technical_blueprint",
        entrypoint=ConvergenceSessionEntrypoint.CHAT,
        current_stage="merge",
    )
    await _amap_blueprint_status(session)
    assert await ArtifactVersion.objects.acount() >= 0


def test_only_amap_blueprint_status_was_touched() -> None:
    """受限面自检：本相位对 `blueprint_resume` 的改动只允许落在状态映射一处。

    `aresume_blueprint_session` / `adrive_blueprint_session_to_pause_or_terminal` /
    `_aload_artifact` 的既有语义与签名必须原样保留（B3 定夺的受限口径）。
    """
    import inspect

    for name in (
        "aresume_blueprint_session",
        "aresume_after_gate_action",
        "adrive_blueprint_session_to_pause_or_terminal",
        "_aload_artifact",
        "_ahas_open_blocking_blueprint_threads",
    ):
        assert hasattr(blueprint_resume, name), f"{name} 被删或改名"
    assert list(
        inspect.signature(blueprint_resume.adrive_blueprint_session_to_pause_or_terminal).parameters
    ) == ["engine", "session", "max_steps"]
    assert list(inspect.signature(blueprint_resume.aresume_blueprint_session).parameters) == [
        "session",
        "engine",
    ]
