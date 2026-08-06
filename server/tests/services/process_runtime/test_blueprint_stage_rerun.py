"""蓝图节点重跑测试（quick 260806）。

守七件事：

1. ``next_run_label`` 纯函数：major 递增 / 首个子段 / 兄弟子段 / 嵌套子段 / 非法标签跳过。
2. ``operator_instruction`` / ``operator_instruction_section``：无标记空串（prompt 零扰动）、
   有指令时带固定标题、超长截断。
3. ``arerun_blueprint_stage`` 非法 stage / 无会话 → ``invalid`` 且 DB 一字未动。
4. 正路（route + 指令）：会话回卷到 route 且 ``running``；``stage_rerun`` 标记与历史原子
   落库；``run_label`` 为最新版本谱系的子段；``blueprint.stage.rerun_requested`` 事件落库
   且 **payload 不含指令正文**；人审态（pending_review）被拉回 drafting。
5. ``decompose`` 重跑 = major 递增（"1" → "2"）。
6. ``repo_research`` 重跑失效既有调研（task → stale、valid PartialPlan → invalid）；
   ``merge`` 重跑不动它们。
7. ``ArtifactService`` 谱系盖章：create → "1"；add_version 无标记继承 current；有标记随标记。
8. ``arewind_to_stage``：CAS（内存快照陈旧 → False 不盲写）；非法 stage → ValueError。
"""

from __future__ import annotations

import pytest
from asgiref.sync import async_to_sync

from delivery.models import (
    Artifact,
    ArtifactVersion,
    BlueprintStatus,
    ConvergenceSession,
    ConvergenceSessionEntrypoint,
    ConvergenceSessionEvent,
    ConvergenceSessionStatus,
    PartialPlan,
    RepoResearchTask,
    RepoResearchTaskStatus,
)
from delivery.services import ArtifactService
from delivery.services.convergence_session_service import ConvergenceSessionService
from delivery.services.event_taxonomy import EVENT_BLUEPRINT_STAGE_RERUN_REQUESTED
from services.process_runtime import blueprint_stage_rerun as rerun_module
from services.process_runtime.blueprint_stage_rerun import (
    RERUNNABLE_STAGES,
    STAGE_RERUN_HISTORY_KEY,
    STAGE_RERUN_KEY,
    arerun_blueprint_stage,
    next_run_label,
    operator_instruction,
    operator_instruction_section,
)
from tests.helpers.blueprint_samples import make_blueprint

pytestmark = pytest.mark.django_db(transaction=True)


# ── 工厂 ─────────────────────────────────────────────────────────────────────


def _make_artifact(status: str = BlueprintStatus.PENDING_REVIEW) -> Artifact:
    content = make_blueprint()
    artifact = async_to_sync(ArtifactService().create)(
        "technical_plan", content, title="重跑样例", created_by_user_id="tester"
    )
    Artifact.objects.filter(id=artifact.id).update(blueprint_status=status)
    artifact.blueprint_status = status
    return artifact


def _make_session(
    artifact: Artifact,
    *,
    current_stage: str = "ai_review",
    status: str = ConvergenceSessionStatus.DONE,
    stage_state: dict | None = None,
) -> ConvergenceSession:
    return ConvergenceSession.objects.create(
        process_type="technical_blueprint",
        entrypoint=ConvergenceSessionEntrypoint.CHAT,
        current_stage=current_stage,
        status=status,
        stage_state=stage_state or {},
        current_artifact_version_id=Artifact.objects.get(id=artifact.id).current_version_id,
    )


@pytest.fixture(autouse=True)
def _no_enqueue(monkeypatch):
    """重跑的续驱入队在测试内恒 no-op（不把真实 engine/LLM 拖进单测）。"""

    async def _noop(session, *, initiated_by_user_id):
        return None

    monkeypatch.setattr(rerun_module, "_aenqueue_resume", _noop)


def _rerun(artifact, session, **kwargs) -> dict:
    return async_to_sync(arerun_blueprint_stage)(artifact, session, **kwargs)


# ═══════════════════════════════════════════════════════════════════════════
# 1. next_run_label 纯函数
# ═══════════════════════════════════════════════════════════════════════════


@pytest.mark.parametrize(
    ("labels", "base", "major", "expected"),
    [
        ([], "1", True, "2"),  # 无标签 major：视作已有 1
        (["1"], "1", True, "2"),
        (["1", "2", "2.1"], "2.1", True, "3"),  # major 只看首段最大值
        ([], "1", False, "1.1"),  # 首个子段
        (["1", "1.1"], "1", False, "1.2"),  # 兄弟子段
        (["1", "1.1", "1.3"], "1", False, "1.4"),  # 序号取最大 +1（跳号不回填）
        (["2", "2.1", "2.1.1"], "2.1", False, "2.1.2"),  # 嵌套子段
        (["2", "2.1.1"], "2", False, "2.1"),  # 孙辈不算直接子段
        (["abc", "1.x", "2"], "2", False, "2.1"),  # 非法标签跳过
        (["oops"], "oops", False, "oops.1"),  # 基线非数字也能追加（不抛）
    ],
)
def test_next_run_label(labels, base, major, expected) -> None:
    assert next_run_label(labels, base_label=base, major=major) == expected


# ═══════════════════════════════════════════════════════════════════════════
# 2. 操作员指令读取面
# ═══════════════════════════════════════════════════════════════════════════


class _StubSession:
    def __init__(self, stage_state) -> None:
        self.stage_state = stage_state


def test_operator_instruction_empty_without_marker() -> None:
    assert operator_instruction(_StubSession({})) == ""
    assert operator_instruction(_StubSession(None)) == ""
    assert operator_instruction_section(_StubSession({})) == ""
    # 标记形状不对也不抛
    assert operator_instruction(_StubSession({STAGE_RERUN_KEY: "oops"})) == ""


def test_operator_instruction_section_has_title_and_truncates() -> None:
    session = _StubSession({STAGE_RERUN_KEY: {"instruction": "x" * 9000}})
    text = operator_instruction(session)
    assert len(text) == 4000
    section = operator_instruction_section(session)
    assert section.startswith("## 操作员补充指令")
    assert "x" * 100 in section


# ═══════════════════════════════════════════════════════════════════════════
# 3. 非法入参
# ═══════════════════════════════════════════════════════════════════════════


def test_rerun_rejects_unknown_stage() -> None:
    artifact = _make_artifact()
    session = _make_session(artifact)
    result = _rerun(artifact, session, stage="reroute", instruction="hi")
    assert result["status"] == "invalid"
    fresh = ConvergenceSession.objects.get(id=session.id)
    assert fresh.current_stage == "ai_review"
    assert STAGE_RERUN_KEY not in (fresh.stage_state or {})


def test_rerun_rejects_missing_session() -> None:
    artifact = _make_artifact()
    result = _rerun(artifact, None, stage="route")
    assert result["status"] == "invalid"


# ═══════════════════════════════════════════════════════════════════════════
# 4. 正路：回卷 + 标记 + 事件 + 状态拉回
# ═══════════════════════════════════════════════════════════════════════════


def test_rerun_route_rewinds_and_records_marker() -> None:
    artifact = _make_artifact(BlueprintStatus.PENDING_REVIEW)
    session = _make_session(artifact)

    result = _rerun(artifact, session, stage="route", instruction="  主要动网关仓  ")
    assert result["status"] == "accepted"
    # 唯一版本标签 "1" ⇒ 子段 "1.1"
    assert result["run_label"] == "1.1"

    fresh = ConvergenceSession.objects.get(id=session.id)
    assert fresh.current_stage == "route"
    assert fresh.status == ConvergenceSessionStatus.RUNNING
    marker = fresh.stage_state[STAGE_RERUN_KEY]
    assert marker["stage"] == "route"
    assert marker["instruction"] == "主要动网关仓"
    assert marker["run_label"] == "1.1"
    history = fresh.stage_state[STAGE_RERUN_HISTORY_KEY]
    assert len(history) == 1 and history[0]["run_label"] == "1.1"

    # 事件落库且 payload 不含指令正文
    event = ConvergenceSessionEvent.objects.filter(
        session_id=session.id, event=EVENT_BLUEPRINT_STAGE_RERUN_REQUESTED
    ).first()
    assert event is not None
    assert event.payload["stage"] == "route"
    assert event.payload["run_label"] == "1.1"
    assert event.payload["instruction_len"] == len("主要动网关仓")
    assert "主要动网关仓" not in str(event.payload)

    # 人审态拉回 drafting
    assert Artifact.objects.get(id=artifact.id).blueprint_status == BlueprintStatus.DRAFTING


def test_rerun_from_archived_pulls_back_to_drafting() -> None:
    """归档蓝图可迭代：ARCHIVED → DRAFTING 合法边 + 回卷成功。"""
    artifact = _make_artifact(BlueprintStatus.ARCHIVED)
    session = _make_session(artifact)
    result = _rerun(artifact, session, stage="merge")
    assert result["status"] == "accepted"
    assert Artifact.objects.get(id=artifact.id).blueprint_status == BlueprintStatus.DRAFTING


def test_rerun_decompose_bumps_major() -> None:
    artifact = _make_artifact()
    session = _make_session(artifact)
    result = _rerun(artifact, session, stage="decompose", instruction="整体重来")
    assert result["status"] == "accepted"
    assert result["run_label"] == "2"


def test_rerun_history_appends_across_reruns() -> None:
    artifact = _make_artifact()
    session = _make_session(artifact)
    assert _rerun(artifact, session, stage="route")["status"] == "accepted"
    session = ConvergenceSession.objects.get(id=session.id)
    result = _rerun(artifact, session, stage="merge", instruction="再来")
    assert result["status"] == "accepted"
    fresh = ConvergenceSession.objects.get(id=session.id)
    assert [item["stage"] for item in fresh.stage_state[STAGE_RERUN_HISTORY_KEY]] == [
        "route",
        "merge",
    ]


# ═══════════════════════════════════════════════════════════════════════════
# 6. 下游失效
# ═══════════════════════════════════════════════════════════════════════════


def _make_research(session: ConvergenceSession) -> tuple[RepoResearchTask, PartialPlan]:
    from repositories.models import Repository

    repo = Repository.objects.create(
        name="repo-rerun",
        git_url="https://example.com/rerun.git",
        git_platform="github",
        default_branch="main",
    )
    task = RepoResearchTask.objects.create(
        session=session, repository=repo, status=RepoResearchTaskStatus.DONE
    )
    partial = PartialPlan.objects.create(research_task=task, content={"ok": True}, valid=True)
    return task, partial


def test_rerun_repo_research_invalidates_terminal_tasks() -> None:
    artifact = _make_artifact()
    session = _make_session(artifact)
    task, partial = _make_research(session)

    assert _rerun(artifact, session, stage="repo_research")["status"] == "accepted"
    task.refresh_from_db()
    partial.refresh_from_db()
    assert task.status == RepoResearchTaskStatus.STALE
    assert partial.valid is False


def test_rerun_merge_keeps_research_untouched() -> None:
    artifact = _make_artifact()
    session = _make_session(artifact)
    task, partial = _make_research(session)

    assert _rerun(artifact, session, stage="merge")["status"] == "accepted"
    task.refresh_from_db()
    partial.refresh_from_db()
    assert task.status == RepoResearchTaskStatus.DONE
    assert partial.valid is True


# ═══════════════════════════════════════════════════════════════════════════
# 7. ArtifactService 谱系盖章
# ═══════════════════════════════════════════════════════════════════════════


def test_version_label_stamping_follows_lineage() -> None:
    artifact = _make_artifact()
    v1 = ArtifactVersion.objects.get(artifact_id=artifact.id)
    assert v1.version_label == "1"

    # 无标记 add_version：继承 current 的谱系
    content = make_blueprint()
    content["meta"]["title"] = "第二版"
    v2 = async_to_sync(ArtifactService().add_version)(artifact, content)
    assert v2.version_label == "1"

    # 会话带重跑标记：随标记谱系
    session = _make_session(
        artifact, stage_state={STAGE_RERUN_KEY: {"run_label": "1.1", "stage": "merge"}}
    )
    content2 = make_blueprint()
    content2["meta"]["title"] = "重跑版"
    v3 = async_to_sync(ArtifactService().add_version)(
        artifact, content2, produced_by_session_id=str(session.id)
    )
    assert v3.version_label == "1.1"


# ═══════════════════════════════════════════════════════════════════════════
# 8. arewind_to_stage CAS
# ═══════════════════════════════════════════════════════════════════════════


def test_rewind_to_stage_rejects_unknown_stage() -> None:
    artifact = _make_artifact()
    session = _make_session(artifact)
    with pytest.raises(ValueError):
        async_to_sync(ConvergenceSessionService().arewind_to_stage)(session, stage="ghost")


def test_rewind_to_stage_cas_rejects_stale_snapshot() -> None:
    artifact = _make_artifact()
    session = _make_session(artifact, current_stage="merge", status="waiting_clarification")
    # 并发驱动者已把行推进到别的 stage：内存快照陈旧 ⇒ CAS 拒绝、不盲写
    ConvergenceSession.objects.filter(id=session.id).update(
        current_stage="ai_review", status=ConvergenceSessionStatus.RUNNING
    )
    applied = async_to_sync(ConvergenceSessionService().arewind_to_stage)(
        session, stage="route", stage_state_update={STAGE_RERUN_KEY: {"run_label": "1.1"}}
    )
    assert applied is False
    fresh = ConvergenceSession.objects.get(id=session.id)
    assert fresh.current_stage == "ai_review"
    assert STAGE_RERUN_KEY not in (fresh.stage_state or {})


def test_rerunnable_stages_exist_in_blueprint_graph() -> None:
    """可重跑集合必须都是 technical_blueprint 图里的真实 stage（防幽灵 stage）。"""
    from services.process_runtime.registry import get_process_definition

    definition = get_process_definition("technical_blueprint")
    assert definition is not None
    for stage in RERUNNABLE_STAGES:
        assert definition.stage(stage) is not None
