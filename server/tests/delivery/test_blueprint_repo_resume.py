"""每仓 agent 会话可续（Phase 120，REDO-03/04）。

守六件事：

1. ⭐ **留痕落在 ``SubAgentSession``**：容器上报的 ``sdk_session_id`` / ``sdk_transcript``
   落库 —— 此前只有编码链（``CodingSession``）落，蓝图链一直丢掉，导致每仓重跑只能从结论
   重建、拿不到「上一次是怎么分析的」。
2. ⭐ **超上限两个字段一起放弃**（REDO-04 的有界）：只留 id 无法 resume，却会让下游误以为
   有上下文可续而跳过语义重建。
3. ⭐ **按仓 + 按蓝图会话取上一轮**：``mark_stale`` 重跑复用同一条 ``RepoResearchTask``，
   而每次派发新建 ``SubAgentSession`` ⇒ 按 task 反查拿不到上一轮留痕。
4. ⛔ **不跨蓝图会话取**：另一份蓝图对同一个仓的推理是另一个需求的上下文，续进来比不续更糟。
5. 分片规则与容器侧重组口径一致（``_CHUNKS`` + ``_{i}``），且**只有一份实现**。
6. 无留痕 / 空 transcript ⇒ 返回空 env（容器全新执行，默认安全）。
"""

from __future__ import annotations

import uuid

import pytest
from asgiref.sync import async_to_sync
from django.utils import timezone

from delivery.models import (
    ConvergenceSession,
    ConvergenceSessionEntrypoint,
    ConvergenceSessionStatus,
    RepoResearchTask,
)
from repositories.models import Repository
from subagent.models import AgentSession, SubAgentSession

pytestmark = pytest.mark.django_db(transaction=True)


def _make_repo(name: str) -> Repository:
    return Repository.objects.create(
        name=name,
        git_url=f"https://example.com/{name}.git",
        git_platform="github",
        default_branch="main",
    )


def _make_blueprint_session() -> ConvergenceSession:
    return ConvergenceSession.objects.create(
        process_type="technical_blueprint",
        entrypoint=ConvergenceSessionEntrypoint.CHAT,
        current_stage="repo_research",
        status=ConvergenceSessionStatus.RUNNING,
    )


def _make_subagent_session(
    *,
    repository_id: str,
    blueprint_session_id: str,
    transcript: str,
    sdk_session_id: str = "sdk-1",
    saved_at=None,
) -> SubAgentSession:
    main = AgentSession.objects.create(session_id=f"main-{uuid.uuid4().hex[:8]}")
    return SubAgentSession.objects.create(
        session_id=f"sub-{uuid.uuid4().hex[:8]}",
        main_session=main,
        repo_url="https://example.com/x.git",
        task_type=SubAgentSession.TaskType.PLAN,
        status=SubAgentSession.Status.COMPLETED,
        sdk_session_id=sdk_session_id,
        sdk_transcript=transcript,
        sdk_session_saved_at=saved_at or timezone.now(),
        last_output={
            "repository_id": repository_id,
            "blueprint_session_id": blueprint_session_id,
        },
    )


def _resume_env(task: RepoResearchTask) -> dict:
    from services.process_runtime.blueprint_research_adapter import BlueprintResearchAdapter

    return async_to_sync(BlueprintResearchAdapter()._aresume_env)(task)


# ═══════════════════════════════════════════════════════════════════════════
# 1-2. 留痕落库与有界
# ═══════════════════════════════════════════════════════════════════════════


def test_callback_persists_sdk_session_onto_the_subagent_session() -> None:
    import structlog

    from subagent.api.callbacks import _apersist_subagent_sdk_session

    session = _make_subagent_session(
        repository_id=str(uuid.uuid4()), blueprint_session_id=str(uuid.uuid4()), transcript=""
    )
    log = structlog.get_logger("test")

    async_to_sync(_apersist_subagent_sdk_session)(
        session, {"sdk_session_id": "sdk-abc", "sdk_transcript": '{"role":"user"}\n'}, log
    )

    session.refresh_from_db()
    assert session.sdk_session_id == "sdk-abc"
    assert session.sdk_transcript == '{"role":"user"}\n'
    assert session.sdk_session_saved_at is not None


def test_oversize_transcript_drops_both_fields_not_just_the_transcript() -> None:
    """⭐ 只留 id 无法 resume，却会让下游误以为「有上下文可续」⇒ 一起放弃（REDO-04）。"""
    import structlog

    from subagent.api.callbacks import MAX_SDK_TRANSCRIPT_CHARS, _apersist_subagent_sdk_session

    session = _make_subagent_session(
        repository_id=str(uuid.uuid4()), blueprint_session_id=str(uuid.uuid4()), transcript=""
    )
    session.sdk_session_id = ""
    session.save(update_fields=["sdk_session_id"])

    async_to_sync(_apersist_subagent_sdk_session)(
        session,
        {"sdk_session_id": "sdk-big", "sdk_transcript": "x" * (MAX_SDK_TRANSCRIPT_CHARS + 1)},
        structlog.get_logger("test"),
    )

    session.refresh_from_db()
    assert session.sdk_session_id == ""
    assert session.sdk_transcript == ""


# ═══════════════════════════════════════════════════════════════════════════
# 3-6. resume env 反查
# ═══════════════════════════════════════════════════════════════════════════


def test_resume_env_is_built_from_the_previous_container_of_the_same_repo() -> None:
    """⭐ 按仓 + 按蓝图会话反查上一轮留痕（重跑复用同一 task、但换新的 SubAgentSession）。"""
    repo = _make_repo("resume-hit")
    blueprint = _make_blueprint_session()
    task = RepoResearchTask.objects.create(session=blueprint, repository=repo)
    _make_subagent_session(
        repository_id=str(repo.id),
        blueprint_session_id=str(blueprint.id),
        transcript='{"m":"上一轮的推理"}\n',
        sdk_session_id="sdk-prev",
    )

    env = _resume_env(task)

    assert env["env_FRIDAY_TASK_RESUME_SESSION_ID"] == "sdk-prev"
    assert env["env_FRIDAY_TASK_RESUME_TRANSCRIPT_CHUNKS"] == "1"
    assert env["env_FRIDAY_TASK_RESUME_TRANSCRIPT_0"] == '{"m":"上一轮的推理"}\n'


def test_resume_env_never_crosses_blueprint_sessions() -> None:
    """⛔ 另一份蓝图对同一个仓的上下文是另一个需求的推理 ⇒ 不得续进来。"""
    repo = _make_repo("resume-isolated")
    mine = _make_blueprint_session()
    other = _make_blueprint_session()
    task = RepoResearchTask.objects.create(session=mine, repository=repo)
    _make_subagent_session(
        repository_id=str(repo.id),
        blueprint_session_id=str(other.id),
        transcript='{"m":"别的需求"}\n',
    )

    assert _resume_env(task) == {}


def test_resume_env_picks_the_latest_saved_transcript() -> None:
    repo = _make_repo("resume-latest")
    blueprint = _make_blueprint_session()
    task = RepoResearchTask.objects.create(session=blueprint, repository=repo)
    now = timezone.now()
    _make_subagent_session(
        repository_id=str(repo.id),
        blueprint_session_id=str(blueprint.id),
        transcript='{"m":"旧"}\n',
        sdk_session_id="sdk-old",
        saved_at=now - timezone.timedelta(hours=2),
    )
    _make_subagent_session(
        repository_id=str(repo.id),
        blueprint_session_id=str(blueprint.id),
        transcript='{"m":"新"}\n',
        sdk_session_id="sdk-new",
        saved_at=now,
    )

    assert _resume_env(task)["env_FRIDAY_TASK_RESUME_SESSION_ID"] == "sdk-new"


def test_resume_env_is_empty_without_any_transcript() -> None:
    """无留痕 ⇒ 空 env（容器全新执行，默认安全）。"""
    repo = _make_repo("resume-miss")
    blueprint = _make_blueprint_session()
    task = RepoResearchTask.objects.create(session=blueprint, repository=repo)
    # 有 SubAgentSession 但 transcript 为空 ⇒ 同样不可续
    _make_subagent_session(
        repository_id=str(repo.id), blueprint_session_id=str(blueprint.id), transcript=""
    )

    assert _resume_env(task) == {}


def test_transcript_chunking_matches_the_container_side_contract() -> None:
    """⭐ 分片只有一份实现：键名与分片数必须与容器侧重组口径一致。"""
    from chat.sdk_resume import RESUME_CHUNK_CHARS, build_resume_env

    transcript = "y" * (RESUME_CHUNK_CHARS + 10)
    env = build_resume_env("sdk-x", transcript)

    assert env["env_FRIDAY_TASK_RESUME_TRANSCRIPT_CHUNKS"] == "2"
    assert len(env["env_FRIDAY_TASK_RESUME_TRANSCRIPT_0"]) == RESUME_CHUNK_CHARS
    assert len(env["env_FRIDAY_TASK_RESUME_TRANSCRIPT_1"]) == 10
    # 重组后与原文逐字相同（截断即静默灾难：agent 会拿半份历史继续推理）
    assert (
        env["env_FRIDAY_TASK_RESUME_TRANSCRIPT_0"] + env["env_FRIDAY_TASK_RESUME_TRANSCRIPT_1"]
        == transcript
    )


def test_build_resume_env_rejects_empty_inputs_and_oversize() -> None:
    from chat.sdk_resume import MAX_RESUME_TRANSCRIPT_BYTES, build_resume_env

    assert build_resume_env("", "abc") == {}
    assert build_resume_env("sdk", "") == {}
    assert build_resume_env("sdk", "z" * (MAX_RESUME_TRANSCRIPT_BYTES + 1)) == {}


# ═══════════════════════════════════════════════════════════════════════════
# 7. ⭐ 返工带人审反馈进 agent 输入（REDO-02）
#
# 驳回本来就会把理由落成 human_comment 线程、把 revision_round +1，但融合起草**从来没读过
# 它们** ⇒ 会话被复位、AI 重跑，拿到的输入与上一轮一模一样，大概率产出一模一样的方案，
# 用户写的意见石沉大海。这正是「打回重做」体感失灵的根因。
# ═══════════════════════════════════════════════════════════════════════════


def test_first_round_prompt_is_byte_identical_to_before() -> None:
    """⭐ 首轮零扰动：无反馈时 system 串与改动前逐字相同（兼容性的正向对照）。"""
    from services.process_runtime.blueprint_merge import _prompt_parts

    plain = _prompt_parts(("SYS", "HUMAN"))
    assert plain == {"system": "SYS", "human": "HUMAN"}

    class _Inputs:
        human_feedback = ""

    assert _prompt_parts(("SYS", "HUMAN"), _Inputs()) == plain


def test_rework_prompt_carries_round_and_every_comment() -> None:
    from services.process_runtime.blueprint_merge import _format_human_feedback, _prompt_parts

    feedback = _format_human_feedback(
        revision_round=2, comments=["接口契约与现状不符", "缺少回滚设计"]
    )

    assert "第 2 轮" in feedback
    assert "接口契约与现状不符" in feedback
    assert "缺少回滚设计" in feedback
    # ⭐ 必须明确要求「不要原样重复上一版」——否则模型倾向于复述已有结论
    assert "不要原样重复" in feedback

    class _Inputs:
        human_feedback = feedback

    assert _prompt_parts(("SYS", "HUMAN"), _Inputs())["system"].startswith("SYS\n\n")
    assert "缺少回滚设计" in _prompt_parts(("SYS", "HUMAN"), _Inputs())["system"]


def test_feedback_is_bounded_and_truncated() -> None:
    """REDO-04：条数与单条长度都有界——评论是半可信自由文本，无界拼接会挤掉真正的证据。"""
    from services.process_runtime.blueprint_merge import (
        _MAX_FEEDBACK_CHARS,
        _MAX_FEEDBACK_ITEMS,
        _format_human_feedback,
    )

    feedback = _format_human_feedback(
        revision_round=1,
        comments=[f"意见{index}" for index in range(_MAX_FEEDBACK_ITEMS + 5)]
        + ["超长" * _MAX_FEEDBACK_CHARS],
    )

    assert f"{_MAX_FEEDBACK_ITEMS}. " in feedback
    assert f"{_MAX_FEEDBACK_ITEMS + 1}. " not in feedback
    assert len(feedback) < _MAX_FEEDBACK_CHARS * (_MAX_FEEDBACK_ITEMS + 2)


def test_feedback_is_empty_on_a_pristine_first_round() -> None:
    from services.process_runtime.blueprint_merge import _format_human_feedback

    assert _format_human_feedback(revision_round=0, comments=[]) == ""
    assert _format_human_feedback(revision_round=0, comments=["  ", ""]) == ""
