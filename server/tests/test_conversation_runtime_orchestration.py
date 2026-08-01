"""运行时快照的两个编排可见性分支（Phase 110-03 · OBS-01 / OBS-02 / OBS-03）。

覆盖 `ConversationService.get_conversation_runtime` 新增的 `orchestration` 与
`plan_research_sessions` 两个**独立**字段：

- 形状与降级（无会话 / stage_state 形状意外 / 分支各自 try 内失败）
- 🔴 事件截断**方向**（保留最新 200 条，不是最旧）
- 🔴 `ts` 序列化与**数据库往返**一致性（前端跨链去重键的唯一依据）
- 🔴 泄漏面（`failure` 只有闭集 reason_code，原始异常文本不出网）
- 🔴 归属链（`ConvergenceSession.conversation_id` → `RepoResearchTask` 权威表）与物理隔离：
  容器能改写自己 `last_output` 里的任意标量键，故归属**不得**建立在那个面上
"""

from __future__ import annotations

import json
from datetime import timedelta
from typing import Any

import pytest
from asgiref.sync import sync_to_async
from django.utils import timezone

# ============================================================================
# 建数据辅助
# ============================================================================

# 改动前即存在的 runtime 键（对无编排会话的对话而言）。本 plan 只允许多出
# `orchestration` 与 `plan_research_sessions` 两个键——多一个少一个都要变红。
_PRE_EXISTING_RUNTIME_KEYS = frozenset(
    {
        "conversation_id",
        "active",
        "mode",
        "status",
        "orchestration_run_id",
        "phase",
        "task_progress",
        "session_id",
        "task_description",
        "progress_message",
        "progress_percent",
        "logs",
        "coding_session",
        "streaming_snapshot",
        "pending_clarification",
        "pending_plan_clarification",
        "deep_sessions",
        "coding_plan",
    }
)

_NEW_RUNTIME_KEYS = frozenset({"orchestration", "plan_research_sessions"})


@pytest.fixture
def conversation(db, project):
    from chat.models import Conversation

    return Conversation.objects.create(space=project, title="编排可见性")


@pytest.fixture
def other_conversation(db, project):
    from chat.models import Conversation

    return Conversation.objects.create(space=project, title="另一条对话")


def _make_session(conversation_id, **kwargs):
    """同步建 ConvergenceSession（chat 入口 + technical_plan 流程）。"""
    from delivery.models import ConvergenceSession

    payload: dict[str, Any] = {
        "process_type": "technical_plan",
        "entrypoint": "chat",
        "conversation_id": conversation_id,
        "status": "running",
        "current_stage": "research",
        "stage_state": {},
        "error": {},
    }
    payload.update(kwargs)
    return ConvergenceSession.objects.create(**payload)


def _make_event(session, event: str, *, ts, payload: dict | None = None):
    from delivery.models import ConvergenceSessionEvent

    return ConvergenceSessionEvent.objects.create(
        session=session,
        event=event,
        payload=payload or {},
        ts=ts,
    )


def _make_research_container(
    project,
    *,
    session_id: str,
    plan_session,
    repository,
    logs: list | None = None,
    source: str = "plan_research",
    task_type: str | None = None,
    status: str = "running",
    forged_plan_session_id: str | None = None,
    forged_repository_id: str | None = None,
    link_task: bool = True,
    task_status: str = "done",
):
    """建一条 plan_research 调研容器 + 它的服务端权威 `RepoResearchTask`。

    形状逐字照搬 `research_adapter._dispatch_deep_task`：`AgentSession.metadata` 只有
    `{source, plan_session_id}` 两个键（**没有** conversation_id，F-5），`last_output`
    带 `{source, plan_session_id, research_task_id, repository_id}` 四个键，
    `RepoResearchTask.subagent_session` 由 `ResearchService.mark_running` 服务端回填。

    三个测试开关，对应容器唯一能做的三件事：
    - `forged_plan_session_id` / `forged_repository_id`：容器经 progress 回调改写自己
      `last_output` 里的归属键（`_merge_output` 对标量键无差别 merge）；
    - `link_task=False`：根本没有权威 task 链过来（伪造 last_output 却无权威锚点）。
    """
    from agents.models import AgentSession
    from delivery.models import RepoResearchTask
    from subagent.models import SubAgentSession

    plan_session_id = str(plan_session.id)
    agent = AgentSession.objects.create(
        session_id=f"agent-{session_id}",
        space=project,
        status=AgentSession.Status.RUNNING,
        metadata={"source": "plan_research", "plan_session_id": plan_session_id},
    )
    task = RepoResearchTask.objects.create(
        session=plan_session, repository=repository, status=task_status
    )
    last_output: dict[str, Any] = {
        "source": source,
        "plan_session_id": forged_plan_session_id or plan_session_id,
        "research_task_id": str(task.id),
        "repository_id": forged_repository_id or str(repository.id),
    }
    if logs is not None:
        last_output["logs"] = logs
    sess = SubAgentSession.objects.create(
        session_id=session_id,
        main_session=agent,
        repo_url="https://gitlab.com/test/x.git",
        task_type=task_type or SubAgentSession.TaskType.PLAN,
        status=status,
        last_output=last_output,
    )
    if link_task:
        task.subagent_session = sess
        task.save(update_fields=["subagent_session", "updated_at"])
    return sess


async def _runtime(conversation, *, orchestration_seen: str = "") -> dict[str, Any]:
    from chat.conversation_service import ConversationService

    return await ConversationService.get_conversation_runtime(
        str(conversation.id), orchestration_seen=orchestration_seen
    )


# ============================================================================
# orchestration：形状与降级
# ============================================================================


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
class TestOrchestrationSnapshotShape:
    async def test_no_session_yields_null_and_empty_without_touching_other_keys(
        self, conversation
    ) -> None:
        """无编排会话 ⇒ orchestration=None、plan_research_sessions=[]，其余键零变化。"""
        runtime = await _runtime(conversation)

        assert runtime["orchestration"] is None
        assert runtime["plan_research_sessions"] == []
        # 老会话零影响：只多出两个新键，既有键集合逐键不变。
        assert set(runtime.keys()) == _PRE_EXISTING_RUNTIME_KEYS | _NEW_RUNTIME_KEYS

    async def test_running_session_exposes_stage_pointer(self, conversation) -> None:
        """feature_list 会话 ⇒ has_classify=True、segment_count=3、current_stage 命中。"""
        await sync_to_async(_make_session)(
            conversation.id,
            current_stage="routing",
            stage_state={
                "decomposition": {
                    "mode": "feature_list",
                    "segments": [{"id": 1}, {"id": 2}, {"id": 3}],
                }
            },
        )

        orch = (await _runtime(conversation))["orchestration"]

        assert set(orch.keys()) == {
            "session_id",
            "status",
            "current_stage",
            "has_classify",
            "segment_count",
            "failure",
            "events",
            "events_truncated",
            "converged",
        }
        assert orch["converged"] is False
        assert orch["status"] == "running"
        assert orch["current_stage"] == "routing"
        assert orch["has_classify"] is True
        assert orch["segment_count"] == 3
        assert orch["failure"] is None
        assert orch["events"] == []
        assert orch["events_truncated"] is False

    async def test_non_feature_list_mode_has_no_classify(self, conversation) -> None:
        await sync_to_async(_make_session)(
            conversation.id,
            stage_state={"decomposition": {"mode": "single", "segments": [{"id": 1}]}},
        )

        orch = (await _runtime(conversation))["orchestration"]

        assert orch["has_classify"] is False
        assert orch["segment_count"] == 1

    async def test_malformed_stage_state_degrades_without_raising(self, conversation) -> None:
        """decomposition 是字符串 ⇒ has_classify=False、segment_count=None，且不抛。"""
        await sync_to_async(_make_session)(
            conversation.id,
            stage_state={"decomposition": "这不是 dict"},
        )

        orch = (await _runtime(conversation))["orchestration"]

        assert orch["has_classify"] is False
        assert orch["segment_count"] is None

    async def test_malformed_segments_yields_null_count(self, conversation) -> None:
        """segments 是 dict ⇒ segment_count=None（不 len 一个 dict 得出误导性 key 数）。"""
        await sync_to_async(_make_session)(
            conversation.id,
            stage_state={"decomposition": {"mode": "feature_list", "segments": {"a": 1, "b": 2}}},
        )

        orch = (await _runtime(conversation))["orchestration"]

        assert orch["has_classify"] is True
        assert orch["segment_count"] is None


# ============================================================================
# orchestration：事件截断方向与 ts 序列化
# ============================================================================


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
class TestOrchestrationEvents:
    @staticmethod
    def _bulk_events(session, count: int) -> None:
        from delivery.models import ConvergenceSessionEvent

        base = timezone.now() - timedelta(hours=1)
        ConvergenceSessionEvent.objects.bulk_create(
            [
                ConvergenceSessionEvent(
                    session=session,
                    event=f"evt-{i}",
                    payload={"i": i},
                    ts=base + timedelta(seconds=i),
                )
                for i in range(count)
            ]
        )

    async def test_truncation_keeps_newest_not_oldest(self, conversation) -> None:
        """🔴 250 条 ⇒ 保留**最新** 200 条（evt-50..evt-249），最旧 50 条被丢。

        只断言「长度 200 + truncated」的话，保留最旧的错误实现同样通过——首尾两条
        事件名的断言才是方向的抓手。方向做反会让时间线永远停在早期阶段。
        """
        session = await sync_to_async(_make_session)(conversation.id)
        await sync_to_async(self._bulk_events)(session, 250)

        orch = (await _runtime(conversation))["orchestration"]

        assert len(orch["events"]) == 200
        assert orch["events_truncated"] is True
        assert orch["events"][-1]["event"] == "evt-249"
        assert orch["events"][0]["event"] == "evt-50"

    async def test_exactly_at_limit_is_not_truncated(self, conversation) -> None:
        """边界下沿：恰好 200 条 ⇒ 全量返回且 events_truncated=False。

        实现多取一条（201）只为判定是否截断，这一条守住它不把「刚好满」误判成截断。
        """
        session = await sync_to_async(_make_session)(conversation.id)
        await sync_to_async(self._bulk_events)(session, 200)

        orch = (await _runtime(conversation))["orchestration"]

        assert len(orch["events"]) == 200
        assert orch["events_truncated"] is False
        assert orch["events"][0]["event"] == "evt-0"
        assert orch["events"][-1]["event"] == "evt-199"

    async def test_one_over_limit_truncates_the_oldest(self, conversation) -> None:
        """边界上沿：201 条 ⇒ 截断，且被丢掉的是**最旧**那条（evt-0）。"""
        session = await sync_to_async(_make_session)(conversation.id)
        await sync_to_async(self._bulk_events)(session, 201)

        orch = (await _runtime(conversation))["orchestration"]

        assert len(orch["events"]) == 200
        assert orch["events_truncated"] is True
        assert orch["events"][0]["event"] == "evt-1"
        assert orch["events"][-1]["event"] == "evt-200"

    async def test_snapshot_ts_is_isoformat_of_the_persisted_row(self, conversation) -> None:
        """快照 ts 与落库行的 `.isoformat()` 逐字符相同。

        与 110-01 的 SSE fan-out 同源（那边写的是 `row.ts.isoformat()`）——前端把
        SSE 那条与快照那条认成同一条事件的**唯一**依据就是这个字符串。
        """
        from delivery.models import ConvergenceSessionEvent

        session = await sync_to_async(_make_session)(conversation.id)
        row = await sync_to_async(_make_event)(
            session, "technical_plan.merge.started", ts=timezone.now()
        )

        orch = (await _runtime(conversation))["orchestration"]

        persisted = await sync_to_async(ConvergenceSessionEvent.objects.get)(pk=row.pk)
        assert orch["events"][0]["ts"] == persisted.ts.isoformat()

    async def test_ts_survives_database_round_trip_bit_for_bit(self, conversation) -> None:
        """🔴 内存实例的 `ts.isoformat()` == DB 回读实例的 `ts.isoformat()`。

        上面那条用例的两侧**都是从 DB 读出来的**，对「DB 往返丢精度」是自指的、测不出来。
        真正撑住前端去重键的不变量是「SSE 那条（内存实例，110-01 fan-out 写进信封的值）
        与快照那条（DB 回读的值）逐字符相同」，中间隔着一次数据库往返。

        破了它的症状是**前端计数成倍虚高**——一种极难归因的形状：两条链各自看都对，
        只有合流去重时才多出一倍。
        """
        from delivery.models import ConvergenceSessionEvent

        session = await sync_to_async(_make_session)(conversation.id)
        in_memory = await sync_to_async(_make_event)(
            session, "repo.research.started", ts=timezone.now()
        )
        fresh = await sync_to_async(ConvergenceSessionEvent.objects.get)(pk=in_memory.pk)

        assert in_memory is not fresh
        assert in_memory.ts.isoformat() == fresh.ts.isoformat()

    async def test_payload_is_sanitized_on_the_wire_but_kept_in_the_ledger(
        self, conversation
    ) -> None:
        """出网面净化、留痕面原样——两个面互不影响。"""
        from delivery.models import ConvergenceSessionEvent

        session = await sync_to_async(_make_session)(conversation.id)
        row = await sync_to_async(_make_event)(
            session,
            "clarification.asked",
            ts=timezone.now(),
            payload={"question": "你要哪种鉴权？", "round_no": 1},
        )

        orch = (await _runtime(conversation))["orchestration"]

        assert "question" not in orch["events"][0]["payload"]
        assert orch["events"][0]["payload"]["round_no"] == 1
        persisted = await sync_to_async(ConvergenceSessionEvent.objects.get)(pk=row.pk)
        assert persisted.payload["question"] == "你要哪种鉴权？"


# ============================================================================
# orchestration：失败原因闭集与泄漏面
# ============================================================================


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
class TestOrchestrationFailureLeakSurface:
    async def test_stage_exception_shape_leaks_nothing(self, conversation) -> None:
        """🔴 有 exception 无 reason ⇒ stage_exception；原始文本键名与值片段都不出网。"""
        await sync_to_async(_make_session)(
            conversation.id,
            status="failed",
            current_stage="merge",
            error={
                "stage": "merge",
                "exception": "ValueError",
                "message": "上游 500：<html>boom</html>",
                "report": {"errors": [{"message": "自由文本"}]},
            },
        )

        orch = (await _runtime(conversation))["orchestration"]

        assert orch["failure"] == {"stage": "merge", "reason_code": "stage_exception"}

        blob = json.dumps(orch, ensure_ascii=False)
        # 断言键名 + 值片段两者：只断言键名会漏掉「换个键名塞出去」的实现。
        # 键名带引号比对，避免与闭集取值 "stage_exception" 自身发生子串误命中。
        for leaked_key in ("message", "exception", "report"):
            assert f'"{leaked_key}"' not in blob
        assert "上游 500" not in blob
        assert "自由文本" not in blob

    async def test_known_reason_is_taken_verbatim_and_report_stays_out(self, conversation) -> None:
        await sync_to_async(_make_session)(
            conversation.id,
            status="failed",
            current_stage="merge",
            error={
                "stage": "merge",
                "reason": "merge_validation_exhausted",
                "report": {"errors": [{"message": "校验报告正文"}]},
            },
        )

        orch = (await _runtime(conversation))["orchestration"]

        assert orch["failure"]["reason_code"] == "merge_validation_exhausted"
        blob = json.dumps(orch, ensure_ascii=False)
        assert '"report"' not in blob
        assert "校验报告正文" not in blob

    async def test_unmapped_reason_falls_back_to_unknown(self, conversation) -> None:
        """闭集外取值 ⇒ unknown，且原始取值不回显。"""
        await sync_to_async(_make_session)(
            conversation.id,
            status="failed",
            error={"reason": "weird_unmapped"},
        )

        orch = (await _runtime(conversation))["orchestration"]

        assert orch["failure"]["reason_code"] == "unknown"
        assert "weird_unmapped" not in json.dumps(orch, ensure_ascii=False)

    async def test_non_failed_session_has_no_failure(self, conversation) -> None:
        """非 failed 状态 ⇒ failure 恒 None，即使 error 里有残留。"""
        await sync_to_async(_make_session)(
            conversation.id,
            status="running",
            error={"exception": "ValueError", "message": "残留"},
        )

        orch = (await _runtime(conversation))["orchestration"]

        assert orch["failure"] is None
        assert "残留" not in json.dumps(orch, ensure_ascii=False)


# ============================================================================
# plan_research_sessions：归属链、解析、脱敏、隔离
# ============================================================================


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
class TestPlanResearchSessions:
    @staticmethod
    def _two_repos():
        from repositories.models import Repository

        return [
            Repository.objects.create(
                name=name,
                git_url=f"https://gitlab.com/test/{name}.git",
                git_platform="gitlab",
                default_branch="main",
            )
            for name in ("alpha", "beta")
        ]

    async def test_two_repos_return_one_row_each_with_resolved_names(
        self, conversation, project
    ) -> None:
        """两仓各一条容器 ⇒ 两条、按 id 升序、repository_name 为服务端解析的真实仓名。"""
        session = await sync_to_async(_make_session)(conversation.id)
        repo_a, repo_b = await sync_to_async(self._two_repos)()
        await sync_to_async(_make_research_container)(
            project,
            session_id="research-aaa",
            plan_session=session,
            repository=repo_a,
            logs=[{"type": "text", "content": "clone 完成", "ts": 1}],
        )
        await sync_to_async(_make_research_container)(
            project,
            session_id="research-bbb",
            plan_session=session,
            repository=repo_b,
            logs=[
                {"type": "tool_call", "content": "Read(a.py)", "ts": 2},
                {"type": "result", "content": "done", "ts": 3},
            ],
        )

        rows = (await _runtime(conversation))["plan_research_sessions"]

        assert [r["session_id"] for r in rows] == ["research-aaa", "research-bbb"]
        assert set(rows[0].keys()) == {
            "session_id",
            "plan_session_id",
            "repository_id",
            "repository_name",
            "status",
            "logs",
        }
        assert rows[0]["repository_name"] == "alpha"
        assert rows[1]["repository_name"] == "beta"
        assert rows[0]["plan_session_id"] == str(session.id)
        assert len(rows[0]["logs"]) == 1
        assert len(rows[1]["logs"]) == 2

    async def test_container_of_another_session_is_not_returned(
        self, conversation, other_conversation, project
    ) -> None:
        """🔴 归属：属于**别的** ConvergenceSession 的调研容器不得出现在本对话结果里。"""
        mine = await sync_to_async(_make_session)(conversation.id)
        theirs = await sync_to_async(_make_session)(other_conversation.id)
        repo_a, repo_b = await sync_to_async(self._two_repos)()
        await sync_to_async(_make_research_container)(
            project,
            session_id="research-mine",
            plan_session=mine,
            repository=repo_a,
        )
        await sync_to_async(_make_research_container)(
            project,
            session_id="research-theirs",
            plan_session=theirs,
            repository=repo_b,
        )

        rows = (await _runtime(conversation))["plan_research_sessions"]

        assert [r["session_id"] for r in rows] == ["research-mine"]

    async def test_forged_plan_session_id_without_authoritative_task_is_rejected(
        self, conversation, other_conversation, project
    ) -> None:
        """🔴 110-MN-01：容器把 `last_output.plan_session_id` 改成本会话 ⇒ 仍不出现。

        `_merge_output` 会把 progress 回调 `details` 里的任意标量键 merge 进 last_output，
        `plan_session_id` 与 `source` 同处这一个可写面 ⇒ 旧实现的「两键交叉校验」强度等于
        一个键。归属锚点必须是服务端权威列：这条容器的 `RepoResearchTask` 挂在**别的**
        ConvergenceSession 上，改写 last_output 不能把它搬过来。
        """
        mine = await sync_to_async(_make_session)(conversation.id)
        theirs = await sync_to_async(_make_session)(other_conversation.id)
        repo_a, repo_b = await sync_to_async(self._two_repos)()
        await sync_to_async(_make_research_container)(
            project,
            session_id="research-ok",
            plan_session=mine,
            repository=repo_a,
        )
        await sync_to_async(_make_research_container)(
            project,
            session_id="research-forged",
            plan_session=theirs,
            repository=repo_b,
            forged_plan_session_id=str(mine.id),
        )

        rows = (await _runtime(conversation))["plan_research_sessions"]

        assert [r["session_id"] for r in rows] == ["research-ok"]

    async def test_container_without_authoritative_task_link_never_appears(
        self, conversation, project
    ) -> None:
        """🔴 权威表没有把 task 链到这个容器 ⇒ 不出现，即使 last_output 三个键全对。

        与上一条分开：那条锚点在「链到别的 session」，这条锚点在「压根没链」——
        `subagent_session__isnull=False` 这个条件被去掉时只有这条会红。
        """
        session = await sync_to_async(_make_session)(conversation.id)
        repo_a, repo_b = await sync_to_async(self._two_repos)()
        await sync_to_async(_make_research_container)(
            project,
            session_id="research-linked",
            plan_session=session,
            repository=repo_a,
        )
        await sync_to_async(_make_research_container)(
            project,
            session_id="research-unlinked",
            plan_session=session,
            repository=repo_b,
            link_task=False,
        )

        rows = (await _runtime(conversation))["plan_research_sessions"]

        assert [r["session_id"] for r in rows] == ["research-linked"]

    async def test_forged_repository_id_cannot_relabel_the_repository(
        self, conversation, project
    ) -> None:
        """🔴 110-MN-01 的低配越权：容器改写自己的 repository_id ⇒ 仍按权威列归仓。

        这条不需要猜任何 UUID —— 容器只要把 `last_output.repository_id` 改成另一个仓，
        旧实现就会用那个值去查名字，用户看到的是「beta 仓的调研日志」而内容来自 alpha。
        两个方向都断言：只断言「不是 beta」的话，返回空串的实现也会通过。
        """
        session = await sync_to_async(_make_session)(conversation.id)
        repo_a, repo_b = await sync_to_async(self._two_repos)()
        await sync_to_async(_make_research_container)(
            project,
            session_id="research-relabel",
            plan_session=session,
            repository=repo_a,
            forged_repository_id=str(repo_b.id),
        )

        rows = (await _runtime(conversation))["plan_research_sessions"]

        assert len(rows) == 1
        assert rows[0]["repository_id"] == str(repo_a.id)
        assert rows[0]["repository_name"] == "alpha"

    async def test_deep_analysis_and_plan_research_are_physically_isolated(
        self, conversation, project
    ) -> None:
        """🔴 同一对话内两种会话并存 ⇒ 两个数组的 session_id 集合交集为空。"""
        from agents.models import AgentSession
        from subagent.models import SubAgentSession

        session = await sync_to_async(_make_session)(conversation.id)
        repo_a, _ = await sync_to_async(self._two_repos)()
        await sync_to_async(_make_research_container)(
            project,
            session_id="research-only",
            plan_session=session,
            repository=repo_a,
        )

        def _make_deep() -> None:
            agent = AgentSession.objects.create(
                session_id="agent-deep-only",
                space=project,
                status=AgentSession.Status.COMPLETED,
                metadata={
                    "source": "chat_deep_analysis",
                    "conversation_id": str(conversation.id),
                },
            )
            SubAgentSession.objects.create(
                session_id="deep-only",
                main_session=agent,
                repo_url="https://gitlab.com/test/x.git",
                task_type=SubAgentSession.TaskType.EXPLORE,
                status=SubAgentSession.Status.COMPLETED,
                last_output={
                    "source": "chat_deep_analysis",
                    "task_description": "分析",
                    "logs": [],
                },
            )

        await sync_to_async(_make_deep)()

        runtime = await _runtime(conversation)
        deep_ids = {s["session_id"] for s in runtime["deep_sessions"]}
        research_ids = {s["session_id"] for s in runtime["plan_research_sessions"]}

        assert deep_ids == {"deep-only"}
        assert research_ids == {"research-only"}
        assert deep_ids & research_ids == set()

    async def test_log_content_is_redacted_on_the_wire(self, conversation, project) -> None:
        """🔴 写入侧 `_append_runtime_log` 不脱敏，读取面必须补。"""
        session = await sync_to_async(_make_session)(conversation.id)
        repo_a, _ = await sync_to_async(self._two_repos)()
        secret = "sk-live-abcdefghijklmnopqrst"
        await sync_to_async(_make_research_container)(
            project,
            session_id="research-secret",
            plan_session=session,
            repository=repo_a,
            logs=[{"type": "text", "content": f"export KEY={secret}", "ts": 1}],
        )

        rows = (await _runtime(conversation))["plan_research_sessions"]

        assert secret not in json.dumps(rows, ensure_ascii=False)
        assert "REDACTED" in rows[0]["logs"][0]["content"]

    async def test_garbage_repository_id_in_last_output_never_reaches_the_orm(
        self, conversation, project
    ) -> None:
        """`last_output.repository_id` 为 "not-a-uuid" ⇒ 不抛，且该值不进结果。

        改用权威列之后这个半可信值根本不参与查询（旧实现要靠一道 UUID 过筛才不会让
        `Repository.objects.filter(id__in=['not-a-uuid'])` 抛 ValidationError）。
        """
        session = await sync_to_async(_make_session)(conversation.id)
        repo_a, _ = await sync_to_async(self._two_repos)()
        await sync_to_async(_make_research_container)(
            project,
            session_id="research-bad-repo",
            plan_session=session,
            repository=repo_a,
            forged_repository_id="not-a-uuid",
        )

        rows = (await _runtime(conversation))["plan_research_sessions"]

        assert len(rows) == 1
        assert rows[0]["repository_id"] == str(repo_a.id)
        assert "not-a-uuid" not in json.dumps(rows, ensure_ascii=False)

    async def test_missing_or_malformed_logs_degrade_to_empty_list(
        self, conversation, project
    ) -> None:
        session = await sync_to_async(_make_session)(conversation.id)
        repo_a, repo_b = await sync_to_async(self._two_repos)()
        await sync_to_async(_make_research_container)(
            project,
            session_id="research-nolog",
            plan_session=session,
            repository=repo_a,
        )
        await sync_to_async(_make_research_container)(
            project,
            session_id="research-badlog",
            plan_session=session,
            repository=repo_b,
            logs="这不是 list",  # type: ignore[arg-type]
        )

        rows = (await _runtime(conversation))["plan_research_sessions"]

        assert [r["logs"] for r in rows] == [[], []]


# ============================================================================
# 终态短路：编排凝固后不再重发全量事件流与容器日志（110-MN-02）
# ============================================================================


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
class TestOrchestrationTerminalShortCircuit:
    @staticmethod
    def _repo(name: str = "alpha"):
        from repositories.models import Repository

        return Repository.objects.create(
            name=name,
            git_url=f"https://gitlab.com/test/{name}.git",
            git_platform="gitlab",
            default_branch="main",
        )

    async def _terminal_session_with_facts(self, conversation, project, *, task_status="done"):
        """一个 done 会话 + 3 条事件 + 1 个带日志的调研容器。"""
        session = await sync_to_async(_make_session)(
            conversation.id, status="done", current_stage="merge"
        )
        for i in range(3):
            await sync_to_async(_make_event)(
                session, f"evt-{i}", ts=timezone.now() - timedelta(seconds=3 - i)
            )
        repo = await sync_to_async(self._repo)()
        await sync_to_async(_make_research_container)(
            project,
            session_id="research-frozen",
            plan_session=session,
            repository=repo,
            logs=[{"type": "text", "content": "调研完成", "ts": 1}],
            task_status=task_status,
        )
        return session

    async def test_matching_token_on_terminal_session_stops_resending_events(
        self, conversation, project
    ) -> None:
        session = await self._terminal_session_with_facts(conversation, project)

        runtime = await _runtime(conversation, orchestration_seen=str(session.id))

        assert runtime["orchestration"]["converged"] is True
        assert runtime["orchestration"]["events"] == []

    async def test_matching_token_on_terminal_session_stops_resending_logs(
        self, conversation, project
    ) -> None:
        """与上一条分开：两个分支各自短路，合成一条时第一个断言会遮住另一个分支。"""
        session = await self._terminal_session_with_facts(conversation, project)

        runtime = await _runtime(conversation, orchestration_seen=str(session.id))

        assert runtime["plan_research_sessions"] == []

    async def test_short_circuit_keeps_the_authoritative_fields(
        self, conversation, project
    ) -> None:
        """🔴 短路只省略两份「早已凝固的重复内容」，权威字段照常回。

        少了这条，「converged 时整个 orchestration 回 None」的实现同样能通过上面两条，
        而那会让前端的阶段指针失去权威来源。
        """
        session = await self._terminal_session_with_facts(conversation, project)

        orch = (await _runtime(conversation, orchestration_seen=str(session.id)))["orchestration"]

        assert orch["session_id"] == str(session.id)
        assert orch["status"] == "done"
        assert orch["current_stage"] == "merge"

    async def test_no_token_always_returns_the_full_snapshot(self, conversation, project) -> None:
        """刷新补齐（restoreConversationRuntime 不带令牌）必须永远拿全量。"""
        await self._terminal_session_with_facts(conversation, project)

        runtime = await _runtime(conversation)

        assert runtime["orchestration"]["converged"] is False
        assert len(runtime["orchestration"]["events"]) == 3
        assert [r["session_id"] for r in runtime["plan_research_sessions"]] == ["research-frozen"]

    async def test_token_for_another_session_is_ignored(self, conversation, project) -> None:
        """令牌不匹配（例如同一对话里又跑了一轮）⇒ 退化成全量，不短路。"""
        await self._terminal_session_with_facts(conversation, project)

        runtime = await _runtime(
            conversation, orchestration_seen="0f0f0f0f-0f0f-4f0f-8f0f-0f0f0f0f0f0f"
        )

        assert runtime["orchestration"]["converged"] is False
        assert len(runtime["orchestration"]["events"]) == 3

    async def test_running_session_is_never_short_circuited(self, conversation, project) -> None:
        """会话仍在途 ⇒ 即使令牌命中也必须全量（事件流还在增长）。"""
        session = await sync_to_async(_make_session)(conversation.id, status="running")
        await sync_to_async(_make_event)(session, "evt-live", ts=timezone.now())

        runtime = await _runtime(conversation, orchestration_seen=str(session.id))

        assert runtime["orchestration"]["converged"] is False
        assert len(runtime["orchestration"]["events"]) == 1

    async def test_live_research_container_blocks_the_short_circuit(
        self, conversation, project
    ) -> None:
        """🔴 failed 可能停在 research，那时容器还在写日志 ⇒ 不得短路。

        少了这一条，「只看 session 终态」的实现同样能通过其余用例，而用户会看到日志组
        停在半截——恰好是本里程碑要消灭的「界面撒谎」。
        """
        session = await sync_to_async(_make_session)(
            conversation.id, status="failed", current_stage="research", error={"reason": "boom"}
        )
        await sync_to_async(_make_event)(session, "evt-0", ts=timezone.now())
        repo = await sync_to_async(self._repo)()
        await sync_to_async(_make_research_container)(
            project,
            session_id="research-still-running",
            plan_session=session,
            repository=repo,
            logs=[{"type": "text", "content": "还在跑", "ts": 1}],
            task_status="running",
        )

        runtime = await _runtime(conversation, orchestration_seen=str(session.id))

        assert runtime["orchestration"]["converged"] is False
        assert [r["session_id"] for r in runtime["plan_research_sessions"]] == [
            "research-still-running"
        ]

    async def test_short_circuit_never_touches_the_event_table(
        self, conversation, project, monkeypatch
    ) -> None:
        """🔴 真正的收敛判据：那次查询**根本没发生**，不只是结果被丢掉。

        把事件表查询掐成抛异常——若实现仍去查，orchestration 会被自己的 except 降级成
        None；短路生效时它拿不到这个雷。
        """
        from delivery.models import ConvergenceSessionEvent

        session = await self._terminal_session_with_facts(conversation, project)

        def _boom(*args: Any, **kwargs: Any):
            raise RuntimeError("event query should not happen after convergence")

        monkeypatch.setattr(ConvergenceSessionEvent.objects, "filter", _boom)

        runtime = await _runtime(conversation, orchestration_seen=str(session.id))

        assert runtime["orchestration"] is not None
        assert runtime["orchestration"]["converged"] is True

    async def test_degraded_orchestration_branch_never_short_circuits_the_logs(
        self, conversation, project, monkeypatch
    ) -> None:
        """🔴 orchestration 分支降级成 None 时，日志分支必须走全量。

        两个分支靠 `runtime["orchestration"]["converged"]` 联动。若日志分支改看局部变量，
        「算出 converged 之后 orchestration 才抛」这一拍会同时回「没有编排」与「没有日志」，
        把前端已有的日志组整个抹掉。

        构造：failed 会话（令牌命中、调研已终态 ⇒ converged 算得出 True），随后让
        `compress_failure_reason` 抛——它在 converged 判定**之后**才被调用。
        """
        from delivery.services import process_event_wire

        session = await sync_to_async(_make_session)(
            conversation.id, status="failed", current_stage="merge", error={"reason": "boom"}
        )
        repo = await sync_to_async(self._repo)()
        await sync_to_async(_make_research_container)(
            project,
            session_id="research-frozen",
            plan_session=session,
            repository=repo,
            logs=[{"type": "text", "content": "调研完成", "ts": 1}],
        )

        def _boom(*args: Any, **kwargs: Any):
            raise RuntimeError("compress exploded")

        monkeypatch.setattr(process_event_wire, "compress_failure_reason", _boom)

        runtime = await _runtime(conversation, orchestration_seen=str(session.id))

        assert runtime["orchestration"] is None
        assert [r["session_id"] for r in runtime["plan_research_sessions"]] == ["research-frozen"]


# ============================================================================
# 分支隔离：三段 try 不得合并，共享变量必须预置
# ============================================================================


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
class TestBranchIsolation:
    @staticmethod
    def _pending_clarification(session) -> None:
        from delivery.models import Clarification, ClarificationQuestion

        rnd = Clarification.objects.create(
            session=session, question="容器", round_no=1, answered_at=None
        )
        ClarificationQuestion.objects.create(
            clarification=rnd,
            order=0,
            question="选 A 还是 B？",
            qtype="single",
            options=[{"id": "a", "label": "A"}],
        )

    async def test_event_query_failure_only_degrades_orchestration(
        self, conversation, project, monkeypatch
    ) -> None:
        """事件查询抛异常 ⇒ 只有 orchestration 变 None，另外两支照常（三个 try 未合并）。

        🔴 对照粒度：只掐**事件查询**那一次。无差别抛错会让「三段合并进同一个 try」的
        错误实现也碰巧看起来正确。
        """
        from delivery.models import ConvergenceSessionEvent
        from repositories.models import Repository

        session = await sync_to_async(_make_session)(conversation.id)
        await sync_to_async(self._pending_clarification)(session)
        repo = await sync_to_async(Repository.objects.create)(
            name="alpha",
            git_url="https://gitlab.com/test/alpha.git",
            git_platform="gitlab",
            default_branch="main",
        )
        await sync_to_async(_make_research_container)(
            project,
            session_id="research-alive",
            plan_session=session,
            repository=repo,
        )

        def _boom(*args: Any, **kwargs: Any):
            raise RuntimeError("event query exploded")

        monkeypatch.setattr(ConvergenceSessionEvent.objects, "filter", _boom)

        runtime = await _runtime(conversation)

        assert runtime["orchestration"] is None
        assert [r["session_id"] for r in runtime["plan_research_sessions"]] == ["research-alive"]
        assert runtime["pending_plan_clarification"] is not None
        assert runtime["pending_plan_clarification"]["round_no"] == 1

    async def test_session_query_failure_degrades_both_fields_independently(
        self, conversation, monkeypatch
    ) -> None:
        """🔴 共享变量必须预置 None。

        让 orchestration 分支的 `ConvergenceSession` 查询**本身**抛异常 ⇒
        - `orchestration` 走本分支的 except 降级为 None；
        - `plan_research_sessions` 走 `orch_session is None` 的**显式早退**得到 `[]`，
          而不是 `UnboundLocalError` 被自己的 except 吞掉得到 `[]`——两者结果一样但
          性质完全不同，后者的症状与「后端根本没写日志」逐字相同。
          判据是 plan_research 分支**没有**打出降级 warning。
        - 端点整体不报错，其余键与不抛时逐键一致。

        这条不能由 `test_event_query_failure_only_degrades_orchestration` 代劳：那条掐的
        是事件查询，发生在 `orch_session` 赋值**之后**，无论预置与否都够不到这条路径。
        """
        from unittest.mock import patch

        import chat.conversation_service as cs
        from delivery.models import ConvergenceSession

        await sync_to_async(_make_session)(conversation.id)

        baseline = await _runtime(conversation)

        original_filter = ConvergenceSession.objects.filter
        calls = {"n": 0}

        def _flaky_filter(*args: Any, **kwargs: Any):
            calls["n"] += 1
            # 第 1 次是 pending_plan_clarification 分支，第 2 次是 orchestration 分支。
            # 只掐第 2 次，让「三段合并」的错误实现无处藏身。
            if calls["n"] >= 2:
                raise RuntimeError("session query exploded")
            return original_filter(*args, **kwargs)

        monkeypatch.setattr(ConvergenceSession.objects, "filter", _flaky_filter)

        with patch.object(cs.logger, "warning", wraps=cs.logger.warning) as warned:
            runtime = await _runtime(conversation)

        logged_events = [call.args[0] for call in warned.call_args_list if call.args]

        assert runtime["orchestration"] is None
        assert runtime["plan_research_sessions"] == []
        assert "conversation_runtime_orchestration_failed" in logged_events
        # 早退路径不打 warning；打了就说明走的是被吞掉的 UnboundLocalError。
        assert "conversation_runtime_plan_research_failed" not in logged_events

        for key in _PRE_EXISTING_RUNTIME_KEYS:
            assert runtime[key] == baseline[key], f"既有键 {key} 被新分支牵连"
