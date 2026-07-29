"""BlueprintResearchAdapter 派发面机制测试（Phase 112-04，FLOW-02 / FLOW-04 / SC3）。

守九件事：

1. **容器上下文接通（SC3）**：`DispatchTask.metadata` 含 `env_FRIDAY_TASK_KNOWLEDGE_ENDPOINT`
   / `env_FRIDAY_TASK_TOOLS_ENDPOINT` / `env_FRIDAY_TASK_USER_TOKEN`，且 `AccessToken` 落
   `kind="task"` + `session_id=<subagent session_id>` 行；**明文不等于 DB 任何存储值**（只有 sha256）。
2. **空值不注入**：无 `created_by` → 无 token 键但 dispatch 仍成功；`FRIDAY_BASE_URL` 为空 →
   两个 endpoint 键均不注入且不抛。
3. **单仓错误隔离 + 主动吊销**：一个仓 dispatch 抛异常 → 该 task failed、其余仓继续派发，
   且该 session_id 的 token 已 `revoked_at` 非空。
4. **幂等**：已 running / done 的 task 再 dispatch → dispatcher 不再被调用。
5. **增量派发（B1③）**：`routing.candidates` 已完成的仓不重跑，只派确认门里
   `pending_research` 的新仓。
6. **`routing` 契约容错**：缺 `"routing"` 键 / `candidates == []` → 零派发、不抛、不调 dispatcher。
7. **`aupgrade_to_deep`**：已 done 的 light 仓 → 变 stale 后被派发；不存在的仓 → `False` 不抛。
8. **无 runner 降级**：deep 桶整体降级轻量，`fitness.verdict == "partial"` 且 dispatcher 未被调用。
9. **章程随 prompt 注入 + 明文零泄漏**：prompt 含 positioning / owned_domains 关键字；
   事件 payload 与日志不含 `friday_pat_` 前缀串。
"""

from __future__ import annotations

import uuid
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest
from asgiref.sync import sync_to_async
from django.test import override_settings

from access_tokens.models import AccessToken
from delivery.models import (
    ConvergenceSession,
    ConvergenceSessionEntrypoint,
    ConvergenceSessionEvent,
    PartialPlan,
    RepoResearchTask,
    RepoResearchTaskStatus,
)
from repositories.models import RepoCharter, Repository
from runners.models import Runner
from services.process_runtime.blueprint_research_adapter import BlueprintResearchAdapter

pytestmark = [pytest.mark.django_db(transaction=True), pytest.mark.asyncio]

_RUNTIME_CFG = "services.provider_config.aget_claude_code_runtime_config"
_GIT_TOKEN = "services.git_credentials.aresolve_git_token"


# ── 工厂与替身 ────────────────────────────────────────────────────────────


class _FakeDispatcher:
    """容器派发替身：记录每次 DispatchTask，可对指定 repo_url 抛异常（单仓隔离用）。"""

    def __init__(self, *, fail_for: set[str] | None = None) -> None:
        self.tasks: list[Any] = []
        self.await_count = 0
        self._fail_for = fail_for or set()

    async def dispatch(self, task: Any) -> None:
        self.await_count += 1
        self.tasks.append(task)
        if task.repo_url in self._fail_for:
            raise RuntimeError("runner unreachable")


async def _make_online_runner() -> Runner:
    from django.utils import timezone

    return await Runner.objects.acreate(
        name=f"runner-{uuid.uuid4().hex[:6]}",
        token_hash=uuid.uuid4().hex + uuid.uuid4().hex,
        status=Runner.Status.ONLINE,
        last_heartbeat=timezone.now(),
    )


async def _make_user():
    from django.contrib.auth import get_user_model

    return await sync_to_async(get_user_model().objects.create_user)(
        username=f"u-{uuid.uuid4().hex[:8]}", password="x"
    )


async def _make_repo(name: str | None = None) -> Repository:
    name = name or f"r-{uuid.uuid4().hex[:8]}"
    return await Repository.objects.acreate(
        name=name,
        git_url=f"https://example.com/{name}.git",
        git_platform="github",
        default_branch="main",
    )


def _candidate(repo: Repository, *, role: str = "direct", confidence: str = "high") -> dict:
    return {
        "repository_id": str(repo.id),
        "repository_name": repo.name,
        "role_suggestion": role,
        "confidence": confidence,
        "total": 0.5,
        "breakdown": {"router_base": 0.5, "charter_match": 0.0, "history_match": 0.0},
        "evidence": {
            "matched_node_paths": ["apps/study/page"],
            "matched_domains": [{"domain": "培优/学习提分", "status": "planned"}],
            "violated_boundaries": [],
            "history_match_unavailable": "",
        },
    }


async def _make_session(stage_state: dict, *, user=None) -> ConvergenceSession:
    return await ConvergenceSession.objects.acreate(
        process_type="technical_blueprint",
        entrypoint=ConvergenceSessionEntrypoint.CHAT,
        current_stage="repo_research",
        stage_state=stage_state,
        created_by=user,
    )


def _routing_state(*candidates: dict, spec: dict | None = None) -> dict:
    state: dict = {
        "routing": {
            "router_version": "v2",
            "auto_selected": False,
            "intent": "greenfield",
            "weights_used": {},
            "charter_supplement_count": 0,
            "unjustified_boundary_hit_count": 0,
            "candidates": list(candidates),
            "citations": [],
        }
    }
    if spec is not None:
        state["blueprint"] = {"requirement_spec": spec}
    return state


def _adapter(dispatcher: _FakeDispatcher, **kwargs) -> BlueprintResearchAdapter:
    return BlueprintResearchAdapter(dispatcher_factory=lambda: dispatcher, **kwargs)


def _stub_runtime():
    """凭证解析替身（避免测试依赖真实 provider 配置）。"""
    return (
        patch(_RUNTIME_CFG, new=AsyncMock(return_value={"api_key": "k", "default_model": "m"})),
        patch(_GIT_TOKEN, new=AsyncMock(return_value="")),
    )


# ===========================================================================
# 1. 容器三键接通 + token 落库（SC3）
# ===========================================================================


@override_settings(FRIDAY_BASE_URL="https://friday.example.com")
async def test_deep_dispatch_injects_three_env_keys_and_mints_token() -> None:
    user = await _make_user()
    repo = await _make_repo()
    session = await _make_session(_routing_state(_candidate(repo)), user=user)
    await _make_online_runner()
    dispatcher = _FakeDispatcher()
    cfg, git = _stub_runtime()

    with cfg, git:
        result = await _adapter(dispatcher, charters_loader=AsyncMock(return_value={})).dispatch(
            session
        )

    assert result == {
        "dispatched": 1,
        "synthesized": 0,
        "degraded": False,
        "tasks": result["tasks"],
    }
    assert dispatcher.await_count == 1
    task = dispatcher.tasks[0]
    meta = task.metadata
    assert meta["env_FRIDAY_TASK_KNOWLEDGE_ENDPOINT"] == "https://friday.example.com"
    assert meta["env_FRIDAY_TASK_TOOLS_ENDPOINT"] == (
        "https://friday.example.com/api/tools/execute/"
    )
    plaintext = meta["env_FRIDAY_TASK_USER_TOKEN"]
    assert plaintext.startswith("friday_pat_")
    # 只读语义双层拦截仍在
    assert meta["env_FRIDAY_TASK_MODE"] == "explore"
    assert meta["env_FRIDAY_TASK_TASK_MODE"] == "explore"

    # AccessToken 行：kind=task + session_id == subagent session_id；DB 只有 sha256
    from runners.models import hash_token

    row = await AccessToken.objects.filter(kind="task", session_id=task.session_id).afirst()
    assert row is not None
    assert row.token_hash == hash_token(plaintext)
    assert plaintext not in (row.token_hash, row.token_prefix, row.token_suffix)
    assert row.token_hash != plaintext

    # session_id 带 uuid 后缀（stale 重跑不撞 UNIQUE）；回调路由靠 last_output
    from subagent.models import SubAgentSession

    sub = await SubAgentSession.objects.filter(session_id=task.session_id).afirst()
    assert sub is not None
    assert sub.task_type == SubAgentSession.TaskType.PLAN
    assert sub.last_output["source"] == "blueprint_research"
    assert sub.last_output["blueprint_session_id"] == str(session.id)
    assert sub.last_output["repository_id"] == str(repo.id)

    research_task = await RepoResearchTask.objects.filter(session=session).afirst()
    assert research_task is not None
    assert research_task.status == RepoResearchTaskStatus.RUNNING


@override_settings(FRIDAY_BASE_URL="https://friday.example.com")
async def test_no_created_by_omits_token_key_but_still_dispatches() -> None:
    """无触发用户 → 不注入 token 键（不伪造 actor），dispatch 仍成功。"""
    repo = await _make_repo()
    session = await _make_session(_routing_state(_candidate(repo)))
    await _make_online_runner()
    dispatcher = _FakeDispatcher()
    cfg, git = _stub_runtime()

    with cfg, git:
        result = await _adapter(dispatcher, charters_loader=AsyncMock(return_value={})).dispatch(
            session
        )

    assert result["dispatched"] == 1
    meta = dispatcher.tasks[0].metadata
    assert "env_FRIDAY_TASK_USER_TOKEN" not in meta
    assert "env_FRIDAY_TASK_KNOWLEDGE_ENDPOINT" in meta
    assert await AccessToken.objects.filter(kind="task").acount() == 0


@override_settings(FRIDAY_BASE_URL="")
async def test_empty_base_url_omits_endpoint_keys() -> None:
    """FRIDAY_BASE_URL 为空 → 两个 endpoint 键均不注入且不抛（向后兼容降级）。"""
    user = await _make_user()
    repo = await _make_repo()
    session = await _make_session(_routing_state(_candidate(repo)), user=user)
    await _make_online_runner()
    dispatcher = _FakeDispatcher()
    cfg, git = _stub_runtime()

    with cfg, git:
        result = await _adapter(dispatcher, charters_loader=AsyncMock(return_value={})).dispatch(
            session
        )

    assert result["dispatched"] == 1
    meta = dispatcher.tasks[0].metadata
    assert "env_FRIDAY_TASK_TOOLS_ENDPOINT" not in meta
    assert "env_FRIDAY_TASK_KNOWLEDGE_ENDPOINT" not in meta
    # token 与 endpoint 相互独立：无 endpoint 也照样铸 token
    assert meta["env_FRIDAY_TASK_USER_TOKEN"].startswith("friday_pat_")


@override_settings(FRIDAY_BASE_URL="https://friday.example.com")
async def test_empty_claude_base_url_not_injected() -> None:
    """Claude base_url 为空不注入该键（不沿用既有链无条件写入的瑕疵）。"""
    repo = await _make_repo()
    session = await _make_session(_routing_state(_candidate(repo)))
    await _make_online_runner()
    dispatcher = _FakeDispatcher()

    with (
        patch(_RUNTIME_CFG, new=AsyncMock(return_value={"api_key": "k", "base_url": ""})),
        patch(_GIT_TOKEN, new=AsyncMock(return_value="")),
    ):
        await _adapter(dispatcher, charters_loader=AsyncMock(return_value={})).dispatch(session)

    meta = dispatcher.tasks[0].metadata
    assert "env_FRIDAY_TASK_CLAUDE_BASE_URL" not in meta
    assert meta["env_FRIDAY_TASK_CLAUDE_API_KEY"] == "k"


# ===========================================================================
# 3. 单仓错误隔离 + dispatch 失败主动吊销
# ===========================================================================


@override_settings(FRIDAY_BASE_URL="https://friday.example.com")
async def test_single_repo_dispatch_failure_isolated_and_token_revoked() -> None:
    user = await _make_user()
    bad_repo = await _make_repo("bad-repo")
    good_repo = await _make_repo("good-repo")
    session = await _make_session(
        _routing_state(_candidate(bad_repo), _candidate(good_repo)), user=user
    )
    await _make_online_runner()
    dispatcher = _FakeDispatcher(fail_for={bad_repo.git_url})
    cfg, git = _stub_runtime()

    with cfg, git:
        result = await _adapter(dispatcher, charters_loader=AsyncMock(return_value={})).dispatch(
            session
        )

    # 其余仓继续派发（不上抛拖垮整个 session）
    assert result["dispatched"] == 1
    assert dispatcher.await_count == 2

    bad_task = await RepoResearchTask.objects.filter(session=session, repository=bad_repo).afirst()
    good_task = await RepoResearchTask.objects.filter(
        session=session, repository=good_repo
    ).afirst()
    assert bad_task is not None and bad_task.status == RepoResearchTaskStatus.FAILED
    assert bad_task.error.get("reason") == "dispatch_failed"
    assert good_task is not None and good_task.status == RepoResearchTaskStatus.RUNNING

    # 失败仓铸出的 token 已被主动吊销（无终态回调兜底）
    failed_session_id = next(
        t.session_id for t in dispatcher.tasks if t.repo_url == bad_repo.git_url
    )
    revoked = await AccessToken.objects.filter(kind="task", session_id=failed_session_id).afirst()
    assert revoked is not None and revoked.revoked_at is not None
    ok_session_id = next(t.session_id for t in dispatcher.tasks if t.repo_url == good_repo.git_url)
    alive = await AccessToken.objects.filter(kind="task", session_id=ok_session_id).afirst()
    assert alive is not None and alive.revoked_at is None


async def test_missing_git_url_fails_without_container() -> None:
    """缺 git_url → 直接判失败，不起注定 clone 失败的占位容器。"""
    repo = await Repository.objects.acreate(
        name=f"nogit-{uuid.uuid4().hex[:6]}", git_url="", git_platform="github"
    )
    session = await _make_session(_routing_state(_candidate(repo)))
    await _make_online_runner()
    dispatcher = _FakeDispatcher()
    cfg, git = _stub_runtime()

    with cfg, git:
        result = await _adapter(dispatcher, charters_loader=AsyncMock(return_value={})).dispatch(
            session
        )

    assert result["dispatched"] == 0
    assert dispatcher.await_count == 0
    task = await RepoResearchTask.objects.filter(session=session).afirst()
    assert task is not None and task.status == RepoResearchTaskStatus.FAILED
    assert task.error.get("reason") == "missing_git_url"


# ===========================================================================
# 4/5/6. 幂等、增量、契约容错
# ===========================================================================


@pytest.mark.parametrize("status", [RepoResearchTaskStatus.RUNNING, RepoResearchTaskStatus.DONE])
@override_settings(FRIDAY_BASE_URL="https://friday.example.com")
async def test_non_dispatchable_status_is_skipped(status: str) -> None:
    """已 running / done 的 task 再 dispatch → dispatcher await_count 不增（幂等白名单）。"""
    repo = await _make_repo()
    session = await _make_session(_routing_state(_candidate(repo)))
    await _make_online_runner()
    await RepoResearchTask.objects.acreate(session=session, repository=repo, status=status)
    dispatcher = _FakeDispatcher()
    cfg, git = _stub_runtime()

    with cfg, git:
        result = await _adapter(dispatcher, charters_loader=AsyncMock(return_value={})).dispatch(
            session
        )

    assert dispatcher.await_count == 0
    assert result["dispatched"] == 0


@override_settings(FRIDAY_BASE_URL="https://friday.example.com")
async def test_incremental_dispatch_only_new_pending_research_repo() -> None:
    """B1③：A/B 已 done 不重跑，只为确认门 pending_research 的 C 建 task 并派一个容器。"""
    repo_a = await _make_repo("repo-a")
    repo_b = await _make_repo("repo-b")
    repo_c = await _make_repo("repo-c")
    stage_state = _routing_state(_candidate(repo_a), _candidate(repo_b))
    stage_state["confirmation"] = {
        "repos": [
            {
                "repository_id": str(repo_c.id),
                "role_suggestion": "direct",
                "pending_research": True,
            },
            # 已确认、无需重调研的仓不进候选
            {
                "repository_id": str(repo_a.id),
                "role_suggestion": "direct",
                "pending_research": False,
            },
        ]
    }
    session = await _make_session(stage_state)
    await _make_online_runner()
    task_a = await RepoResearchTask.objects.acreate(
        session=session, repository=repo_a, status=RepoResearchTaskStatus.DONE
    )
    await RepoResearchTask.objects.acreate(
        session=session, repository=repo_b, status=RepoResearchTaskStatus.DONE
    )
    await sync_to_async(PartialPlan.objects.create)(
        research_task=task_a, content={"fitness": {"verdict": "suitable"}}, content_hash="h"
    )
    dispatcher = _FakeDispatcher()
    cfg, git = _stub_runtime()

    with cfg, git:
        result = await _adapter(dispatcher, charters_loader=AsyncMock(return_value={})).dispatch(
            session
        )

    assert dispatcher.await_count == 1
    assert result["dispatched"] == 1
    assert dispatcher.tasks[0].repo_url == repo_c.git_url
    # A 的既有结论未被重跑覆盖
    assert await PartialPlan.objects.filter(research_task=task_a).acount() == 1
    assert await RepoResearchTask.objects.filter(session=session).acount() == 3


@pytest.mark.parametrize(
    "stage_state",
    [{}, {"routing": {}}, {"routing": {"candidates": []}}, {"routing": "not-a-dict"}],
)
async def test_missing_routing_contract_returns_zero_shape(stage_state: Any) -> None:
    """缺 routing 键 / candidates 空 / 形状异常 → 零派发结构、不抛、不调 dispatcher。"""
    session = await _make_session(stage_state)
    dispatcher = _FakeDispatcher()

    result = await _adapter(dispatcher).dispatch(session)

    assert result == {"dispatched": 0, "synthesized": 0, "degraded": False, "tasks": []}
    assert dispatcher.await_count == 0
    assert await RepoResearchTask.objects.filter(session=session).acount() == 0


# ===========================================================================
# 7. aupgrade_to_deep
# ===========================================================================


@override_settings(FRIDAY_BASE_URL="https://friday.example.com")
async def test_upgrade_to_deep_restages_done_light_repo() -> None:
    """已 done 的 light 仓升级 → task 经 mark_stale 变可派发态后起容器（await_count == 1）。"""
    repo = await _make_repo()
    session = await _make_session(
        _routing_state(_candidate(repo, role="indirect", confidence="low"))
    )
    await _make_online_runner()
    task = await RepoResearchTask.objects.acreate(
        session=session, repository=repo, status=RepoResearchTaskStatus.DONE
    )
    await sync_to_async(PartialPlan.objects.create)(
        research_task=task, content={"fitness": {"verdict": "partial"}}, content_hash="h"
    )
    dispatcher = _FakeDispatcher()
    cfg, git = _stub_runtime()

    with cfg, git:
        ok = await _adapter(
            dispatcher, charters_loader=AsyncMock(return_value={})
        ).aupgrade_to_deep(session, str(repo.id))

    assert ok is True
    assert dispatcher.await_count == 1
    await task.arefresh_from_db()
    assert task.status == RepoResearchTaskStatus.RUNNING


async def test_upgrade_to_deep_unknown_repo_returns_false() -> None:
    """不存在于候选与既有 task 的 repository_id → False 且不抛（端点据此回 404）。"""
    repo = await _make_repo()
    session = await _make_session(_routing_state(_candidate(repo)))
    dispatcher = _FakeDispatcher()

    ok = await _adapter(dispatcher).aupgrade_to_deep(session, str(uuid.uuid4()))
    assert ok is False
    assert dispatcher.await_count == 0
    assert await _adapter(dispatcher).aupgrade_to_deep(session, "") is False


# ===========================================================================
# 8. 无 runner → 整体降级轻量
# ===========================================================================


async def test_no_online_runner_degrades_deep_bucket_to_light() -> None:
    """无 online runner → deep 桶整体降级轻量合成，verdict=partial 且 dispatcher 未被调用。"""
    repo = await _make_repo()
    session = await _make_session(_routing_state(_candidate(repo)))
    dispatcher = _FakeDispatcher()

    result = await _adapter(dispatcher, charters_loader=AsyncMock(return_value={})).dispatch(
        session
    )

    assert result == {
        "dispatched": 0,
        "synthesized": 1,
        "degraded": True,
        "tasks": result["tasks"],
    }
    assert dispatcher.await_count == 0

    task = await RepoResearchTask.objects.filter(session=session).afirst()
    assert task is not None and task.status == RepoResearchTaskStatus.DONE
    partial = await PartialPlan.objects.filter(research_task=task, valid=True).afirst()
    assert partial is not None
    assert partial.content["fitness"]["verdict"] == "partial"
    assert partial.content["role_suggestion"] == "indirect"
    assert partial.content["findings"]
    assert partial.content["repository_id"] == str(repo.id)


async def test_indirect_candidate_synthesized_without_container() -> None:
    """indirect 候选默认轻量合成（FLOW-04 后半），即便有 online runner 也不起容器。"""
    repo = await _make_repo()
    session = await _make_session(
        _routing_state(_candidate(repo, role="indirect", confidence="low"))
    )
    await _make_online_runner()
    dispatcher = _FakeDispatcher()

    result = await _adapter(dispatcher, charters_loader=AsyncMock(return_value={})).dispatch(
        session
    )

    assert result["dispatched"] == 0
    assert result["synthesized"] == 1
    assert result["degraded"] is False
    assert dispatcher.await_count == 0


# ===========================================================================
# 9. 章程随 prompt 注入 + 明文零泄漏
# ===========================================================================


@override_settings(FRIDAY_BASE_URL="https://friday.example.com")
async def test_charter_injected_into_prompt() -> None:
    """prompt 含该仓 positioning / owned_domains 关键字（章程随 prompt 注入的证据）。"""
    user = await _make_user()
    repo = await _make_repo("onion-learning")
    await sync_to_async(RepoCharter.objects.create)(
        repository=repo,
        positioning="高三提分专项的学习前台",
        owned_domains=[{"domain": "培优/学习提分", "status": "planned"}],
        boundaries=[{"rule": "不承接课程权益鉴权"}],
        evolution="active",
        source=RepoCharter.Source.HUMAN_CONFIRMED,
        version=1,
    )
    spec = {
        "goal": [{"block_id": "b1", "type": "paragraph", "text": "高三学员进入专项学习页"}],
        "feature_points": [
            {
                "id": "fp_01",
                "title": "专项学习页",
                "intent": "greenfield",
                "description": [{"block_id": "b2", "type": "paragraph", "text": "新增学习页"}],
            }
        ],
    }
    session = await _make_session(_routing_state(_candidate(repo), spec=spec), user=user)
    await _make_online_runner()
    dispatcher = _FakeDispatcher()
    cfg, git = _stub_runtime()

    with cfg, git:
        await _adapter(dispatcher).dispatch(session)

    prompt = dispatcher.tasks[0].prompt
    assert "高三提分专项的学习前台" in prompt
    assert "培优/学习提分" in prompt
    assert "不承接课程权益鉴权" in prompt
    # 服务端权威状态入 prompt（需求目标与功能点），并写死输出 JSON 形状
    assert "高三学员进入专项学习页" in prompt
    assert "专项学习页" in prompt
    assert "fitness" in prompt and "role_suggestion" in prompt


@override_settings(FRIDAY_BASE_URL="https://friday.example.com")
async def test_plaintext_token_never_leaks_to_events_or_logs(capsys) -> None:
    """明文 token 零泄漏：事件 payload 与 stdout 日志均不含 friday_pat_ 串（T-112-15）。"""
    user = await _make_user()
    repo = await _make_repo()
    session = await _make_session(_routing_state(_candidate(repo)), user=user)
    await _make_online_runner()
    dispatcher = _FakeDispatcher()
    cfg, git = _stub_runtime()

    with cfg, git:
        await _adapter(dispatcher, charters_loader=AsyncMock(return_value={})).dispatch(session)

    plaintext = dispatcher.tasks[0].metadata["env_FRIDAY_TASK_USER_TOKEN"]
    assert plaintext.startswith("friday_pat_")

    payloads = [
        e.payload async for e in ConvergenceSessionEvent.objects.filter(session=session).aiterator()
    ]
    assert payloads  # 确实 emit 了 started 事件
    for payload in payloads:
        assert "friday_pat_" not in str(payload)

    captured = capsys.readouterr()
    assert "friday_pat_" not in captured.out
    assert "friday_pat_" not in captured.err


@override_settings(FRIDAY_BASE_URL="https://friday.example.com")
async def test_default_dispatcher_path_uses_get_dispatcher() -> None:
    """零参构造走生产默认 dispatcher（`get_dispatcher()`），注入只是测试便利。"""
    repo = await _make_repo()
    session = await _make_session(_routing_state(_candidate(repo)))
    await _make_online_runner()
    fake = AsyncMock()
    cfg, git = _stub_runtime()

    with (
        cfg,
        git,
        patch("runners.dispatcher.get_dispatcher", return_value=fake) as get_dispatcher,
    ):
        result = await BlueprintResearchAdapter(
            charters_loader=AsyncMock(return_value={})
        ).dispatch(session)

    assert result["dispatched"] == 1
    assert get_dispatcher.called
    assert fake.dispatch.await_count == 1
