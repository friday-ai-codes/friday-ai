"""BlueprintRepoPlanAdapter 编排面机制测试（Phase 113-03，FLOW-05 / SCHEMA-03）。

守九件事：

1. **仓集来源是确认门锁定产物的最新版本**：session 钉住的旧版本 `repo_associations` 为空，
   最新 `ArtifactVersion` 有两仓 → `acollect_locked_repos` 仍返回两仓（**不读会话钉住那版**）。
2. **direct 派发**：`DispatchTask.task_id` 以 `bp-plan-` 开头、
   `metadata["env_FRIDAY_TASK_KNOWLEDGE_QUOTA"] == "400"`、`env_FRIDAY_TASK_MODE` 仍是
   `explore`（git 写拦截未被改）、`SubAgentSession.last_output["source"] == "blueprint_repo_plan"`。
3. ⭐ **B1 归属数据来源**：派发后 `SubAgentSession.main_session.user_id == session.created_by_id`
   —— `mode="plan"` 与缺省 `mode="research"` 各一条；`created_by = None` 时
   `main_session.user_id is None` 且**不抛**（降级不挂、不伪造 system 用户）。
4. ⭐ **mode 缺省等价性**：`dispatch(session)` 不传 mode → `bp-research-` 前缀 +
   `source == "blueprint_research"`（112 路径逐字未变）+ **不注入配额键**。
5. **indirect 合成**：LLM 返合法 JSON → 落 `repo_plan` 段且 dispatcher 未被调用（不起容器）；
   连续非法 → 落 **degraded 但过 schema** 的最小 repo_plan + 开 blocking 澄清线程
   （`return_stage="repo_plan"`），**不静默丢弃**。
6. **完成判据**：两仓只一仓有 repo_plan → False；都有 → True；一仓 failed + 另一仓 ready → True。
7. **判据只看 repo_plan 段存在性**：task 状态翻成 stale 而产物仍 valid → 仍判 ready
   （不复用「全部 task 终态」那条判据）。
8. **单仓定向补调研**：`arequest_targeted_research` 委托 `aupgrade_to_deep` 且透传返回值。
9. **stage_state 小摘要**：只含 id 与计数，序列化后 < 2KB。
"""

from __future__ import annotations

import json
import uuid
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest
from asgiref.sync import sync_to_async
from django.test import override_settings

from delivery.models import (
    Artifact,
    ArtifactVersion,
    BlueprintThread,
    ConvergenceSession,
    ConvergenceSessionEntrypoint,
    PartialPlan,
    RepoResearchTask,
    RepoResearchTaskStatus,
    ThreadKind,
)
from repositories.models import Repository
from runners.models import Runner
from services.process_runtime.blueprint_repo_plan import BlueprintRepoPlanAdapter
from services.process_runtime.blueprint_repo_plan_schema import validate_repo_plan
from services.process_runtime.blueprint_research_adapter import BlueprintResearchAdapter
from subagent.models import SubAgentSession

pytestmark = [pytest.mark.django_db(transaction=True), pytest.mark.asyncio]

_RUNTIME_CFG = "services.provider_config.aget_claude_code_runtime_config"
_GIT_TOKEN = "services.git_credentials.aresolve_git_token"


# ── 工厂与替身 ────────────────────────────────────────────────────────────


class _FakeDispatcher:
    """容器派发替身：记录每次 DispatchTask。"""

    def __init__(self) -> None:
        self.tasks: list[Any] = []
        self.await_count = 0

    async def dispatch(self, task: Any) -> None:
        self.await_count += 1
        self.tasks.append(task)


class _FakeSynthesizer:
    """indirect 合成替身：按序返回预置产物（可返非法值以测有界重试）。"""

    def __init__(self, *results: Any) -> None:
        self._results = list(results)
        self.calls = 0

    async def synthesize(self, session: Any, repo: dict) -> dict:
        self.calls += 1
        value = self._results[min(self.calls - 1, len(self._results) - 1)]
        if isinstance(value, Exception):
            raise value
        return value


def _stub_runtime():
    return (
        patch(_RUNTIME_CFG, new=AsyncMock(return_value={"api_key": "k", "default_model": "m"})),
        patch(_GIT_TOKEN, new=AsyncMock(return_value="")),
    )


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


async def _make_repo() -> Repository:
    name = f"r-{uuid.uuid4().hex[:8]}"
    return await Repository.objects.acreate(
        name=name,
        git_url=f"https://example.com/{name}.git",
        git_platform="github",
        default_branch="main",
    )


def _association(repo: Repository, *, role: str) -> dict:
    return {
        "repository_id": str(repo.id),
        "repository_name": repo.name,
        "role": role,
        "responsibility": [{"block_id": f"blk_{repo.name}", "type": "paragraph", "text": "职责"}],
        "fitness": {"verdict": "suitable", "reasons": [], "citations": []},
        "decided_by": "human",
        "confirmed_at_gate": True,
    }


async def _make_locked_session(
    *associations: dict, user: Any = None, stage_state: dict | None = None
):
    """建 artifact 两版：v1 空（session 钉住它）、v2 带锁定仓集（最新版）。"""
    artifact = await Artifact.objects.acreate(artifact_type="technical_plan")
    stale = await ArtifactVersion.objects.acreate(
        artifact=artifact, version_no=1, content={"repo_associations": []}
    )
    latest = await ArtifactVersion.objects.acreate(
        artifact=artifact, version_no=2, content={"repo_associations": list(associations)}
    )
    artifact.current_version = latest
    await artifact.asave(update_fields=["current_version"])
    session = await ConvergenceSession.objects.acreate(
        process_type="technical_blueprint",
        entrypoint=ConvergenceSessionEntrypoint.CHAT,
        current_stage="repo_plan",
        stage_state=stage_state or {},
        # 故意钉住落后的 v1：适配器必须自己去取最新版
        current_artifact_version_id=stale.id,
        created_by=user,
    )
    return session, artifact


def _repo_plan_section(repository_id: str, *, role: str = "direct") -> dict:
    return {
        "repository_id": repository_id,
        "role": role,
        "impl_items": [
            {"item_id": "it_1", "title": "改动", "change_type": "modify", "how": "改一处"}
        ],
    }


async def _record_repo_plan(session, repo: Repository, *, role: str = "direct"):
    task, _ = await sync_to_async(RepoResearchTask.objects.get_or_create)(
        session=session, repository=repo, defaults={"status": RepoResearchTaskStatus.DONE}
    )
    await PartialPlan.objects.acreate(
        research_task=task,
        content={
            "repository_id": str(repo.id),
            "repo_plan": _repo_plan_section(str(repo.id), role=role),
        },
        content_hash="h" * 8,
        valid=True,
    )
    return task


def _plan_adapter(**kwargs) -> BlueprintRepoPlanAdapter:
    return BlueprintRepoPlanAdapter(**kwargs)


# ===========================================================================
# 1. 仓集来源（最新 ArtifactVersion，不读会话钉住的版本）
# ===========================================================================


async def test_locked_repos_read_from_latest_version() -> None:
    repo_a = await _make_repo()
    repo_b = await _make_repo()
    session, _artifact = await _make_locked_session(
        _association(repo_a, role="direct"), _association(repo_b, role="indirect")
    )

    repos = await _plan_adapter().acollect_locked_repos(session)
    assert [item["repository_id"] for item in repos] == [str(repo_a.id), str(repo_b.id)]
    assert [item["role"] for item in repos] == ["direct", "indirect"]


async def test_locked_repos_fall_back_to_confirmation_snapshot() -> None:
    """最新版本没有 repo_associations 时回落确认门快照（绝不返半截结果）。"""
    repo_a = await _make_repo()
    session = await ConvergenceSession.objects.acreate(
        process_type="technical_blueprint",
        entrypoint=ConvergenceSessionEntrypoint.CHAT,
        current_stage="repo_plan",
        stage_state={"confirmation": {"repos": [_association(repo_a, role="direct")]}},
    )
    repos = await _plan_adapter().acollect_locked_repos(session)
    assert [item["repository_id"] for item in repos] == [str(repo_a.id)]


# ===========================================================================
# 2/3. direct 派发 + B1 会话归属
# ===========================================================================


@override_settings(FRIDAY_BASE_URL="https://friday.example.com")
async def test_direct_plan_dispatch_uses_plan_prefix_quota_and_source() -> None:
    user = await _make_user()
    repo = await _make_repo()
    session, _artifact = await _make_locked_session(_association(repo, role="direct"), user=user)
    await _make_online_runner()
    dispatcher = _FakeDispatcher()
    research = BlueprintResearchAdapter(
        dispatcher_factory=lambda: dispatcher, charters_loader=AsyncMock(return_value={})
    )
    cfg, git = _stub_runtime()

    with cfg, git:
        result = await _plan_adapter(research_adapter=research).dispatch_plans(session)

    assert result["dispatched"] == 1
    assert result["synthesized"] == 0
    assert result["repositories"] == [str(repo.id)]
    assert dispatcher.await_count == 1

    task = dispatcher.tasks[0]
    assert task.task_id.startswith("bp-plan-")
    assert task.metadata["env_FRIDAY_TASK_KNOWLEDGE_QUOTA"] == "400"
    # git 写拦截与调研阶段同源，未被 plan 模式改动
    assert task.metadata["env_FRIDAY_TASK_MODE"] == "explore"
    assert task.metadata["env_FRIDAY_TASK_TASK_MODE"] == "explore"

    sub = await SubAgentSession.objects.filter(session_id=task.session_id).afirst()
    assert sub is not None
    assert sub.last_output["source"] == "blueprint_repo_plan"

    # ⭐ B1：113-02 的会话归属校验读 main_session.user_id，这里是它唯一的数据来源
    main_session = await sync_to_async(lambda: sub.main_session)()
    assert main_session.user_id == session.created_by_id


@override_settings(FRIDAY_BASE_URL="https://friday.example.com")
async def test_plan_prompt_carries_full_requirement_and_stage1_context() -> None:
    """plan prompt「有什么就都给」：需求规格全量段（背景/验收标准/测试用例/边界/约束）+
    阶段 1 完整结论（responsibility + findings，含 mark_stale 置 invalid 后的回落取数）。"""
    user = await _make_user()
    repo = await _make_repo()
    spec = {
        "goal": [{"block_id": "b1", "type": "paragraph", "text": "上线学习报告导出"}],
        "background": [{"block_id": "b0", "type": "paragraph", "text": "运营侧长期依赖人工导表"}],
        "feature_points": [
            {
                "id": "fp_01",
                "title": "报告导出",
                "intent": "greenfield",
                "description": [{"block_id": "b2", "type": "paragraph", "text": "支持导出 PDF"}],
                "acceptance_criteria": ["导出的 PDF 包含学习时长汇总"],
                "test_cases": [
                    {
                        "name": "空数据导出",
                        "given_when_then": "无学习记录时导出应返回提示而非空文件",
                    }
                ],
            }
        ],
        "boundaries": {"in_scope": ["Web 端"], "out_of_scope": ["移动端 App"]},
        "constraints": [{"id": "c1", "kind": "tech", "text": "必须复用既有导出服务"}],
    }
    session, _artifact = await _make_locked_session(
        _association(repo, role="direct"),
        user=user,
        stage_state={"blueprint": {"requirement_spec": spec}},
    )
    # 阶段 1 结论（含 findings）——dispatch_plans 会先 mark_stale 把这行置 invalid，
    # prompt 仍须取到完整结论（valid 优先、失效行回落）。
    task = await RepoResearchTask.objects.acreate(
        session=session, repository=repo, status=RepoResearchTaskStatus.DONE
    )
    await PartialPlan.objects.acreate(
        research_task=task,
        content={
            "repository_id": str(repo.id),
            "fitness": {"verdict": "suitable", "reasons": [], "citations": []},
            "role_suggestion": "direct",
            "responsibility": "承接导出接口与 PDF 渲染",
            "findings": [
                {
                    "title": "已有导出框架",
                    "detail": "services/export 已支持 CSV 导出",
                    "citations": ["services/export.py"],
                }
            ],
        },
        content_hash="h" * 8,
        valid=True,
    )
    await _make_online_runner()
    dispatcher = _FakeDispatcher()
    research = BlueprintResearchAdapter(
        dispatcher_factory=lambda: dispatcher, charters_loader=AsyncMock(return_value={})
    )
    cfg, git = _stub_runtime()

    with cfg, git:
        await _plan_adapter(research_adapter=research).dispatch_plans(session)

    assert dispatcher.await_count == 1
    prompt = dispatcher.tasks[0].prompt
    # 需求规格全量段
    assert "上线学习报告导出" in prompt
    assert "运营侧长期依赖人工导表" in prompt
    assert "导出的 PDF 包含学习时长汇总" in prompt  # 验收标准
    assert "无学习记录时导出应返回提示而非空文件" in prompt  # 测试用例
    assert "移动端 App" in prompt  # 范围边界
    assert "必须复用既有导出服务" in prompt  # 约束
    # 阶段 1 完整结论（不再只有三个标量）
    assert "承接导出接口与 PDF 渲染" in prompt
    assert "已有导出框架" in prompt
    assert "services/export.py" in prompt
    # test_strategy 必须结合验收标准/测试用例的显式指令
    assert "test_strategy 必须结合" in prompt
    # 确认门锁定职责仍在
    assert "职责" in prompt


async def test_indirect_synthesizer_prompt_includes_requirement_context() -> None:
    """indirect 仓的服务端 LLM 合成 prompt 与容器 prompt 同源带完整需求上下文。"""
    from types import SimpleNamespace

    from services.process_runtime.blueprint_repo_plan import LLMRepoPlanSynthesizer

    session = SimpleNamespace(
        stage_state={
            "blueprint": {
                "requirement_spec": {
                    "goal": [{"block_id": "b1", "type": "paragraph", "text": "上线学习报告导出"}],
                    "feature_points": [
                        {
                            "id": "fp_01",
                            "title": "报告导出",
                            "intent": "greenfield",
                            "acceptance_criteria": ["导出的 PDF 包含学习时长汇总"],
                        }
                    ],
                }
            }
        }
    )
    prompt = LLMRepoPlanSynthesizer._build_prompt(
        session,
        {
            "repository_id": "rid-1",
            "responsibility": [{"block_id": "b", "type": "paragraph", "text": "提供用户数据"}],
            "fitness": {"verdict": "partial"},
        },
    )
    assert "上线学习报告导出" in prompt
    assert "导出的 PDF 包含学习时长汇总" in prompt
    assert "提供用户数据" in prompt
    assert "rid-1" in prompt


@override_settings(FRIDAY_BASE_URL="https://friday.example.com")
async def test_research_mode_default_is_byte_equivalent_and_binds_user() -> None:
    """⭐ mode 缺省等价性（112 零回归）+ ⭐ B1 在 research 路径同样成立。"""
    user = await _make_user()
    repo = await _make_repo()
    session = await ConvergenceSession.objects.acreate(
        process_type="technical_blueprint",
        entrypoint=ConvergenceSessionEntrypoint.CHAT,
        current_stage="repo_research",
        stage_state={
            "routing": {
                "candidates": [
                    {
                        "repository_id": str(repo.id),
                        "repository_name": repo.name,
                        "role_suggestion": "direct",
                        "confidence": "high",
                        "evidence": {},
                    }
                ]
            }
        },
        created_by=user,
    )
    await _make_online_runner()
    dispatcher = _FakeDispatcher()
    cfg, git = _stub_runtime()

    with cfg, git:
        result = await BlueprintResearchAdapter(
            dispatcher_factory=lambda: dispatcher, charters_loader=AsyncMock(return_value={})
        ).dispatch(session)

    assert result["dispatched"] == 1
    task = dispatcher.tasks[0]
    assert task.task_id.startswith("bp-research-")
    # 缺省路径不注入配额键（逐字等价 112）
    assert "env_FRIDAY_TASK_KNOWLEDGE_QUOTA" not in task.metadata

    sub = await SubAgentSession.objects.filter(session_id=task.session_id).afirst()
    assert sub is not None
    assert sub.last_output["source"] == "blueprint_research"
    main_session = await sync_to_async(lambda: sub.main_session)()
    assert main_session.user_id == session.created_by_id


@override_settings(FRIDAY_BASE_URL="https://friday.example.com")
async def test_dispatch_without_created_by_leaves_user_null_and_does_not_raise() -> None:
    """无触发用户 → main_session.user_id 为 None 且不抛（绝不伪造 system 用户）。"""
    repo = await _make_repo()
    session, _artifact = await _make_locked_session(_association(repo, role="direct"), user=None)
    await _make_online_runner()
    dispatcher = _FakeDispatcher()
    research = BlueprintResearchAdapter(
        dispatcher_factory=lambda: dispatcher, charters_loader=AsyncMock(return_value={})
    )
    cfg, git = _stub_runtime()

    with cfg, git:
        result = await _plan_adapter(research_adapter=research).dispatch_plans(session)

    assert result["dispatched"] == 1
    sub = await SubAgentSession.objects.filter(session_id=dispatcher.tasks[0].session_id).afirst()
    assert sub is not None
    main_session = await sync_to_async(lambda: sub.main_session)()
    assert main_session.user_id is None
    # 无 user → 不铸 token（空值不注入该键）
    assert "env_FRIDAY_TASK_USER_TOKEN" not in dispatcher.tasks[0].metadata


async def test_repo_with_existing_plan_is_not_redispatched() -> None:
    """已产出 repo_plan 段的仓不重派（T-113-16）。"""
    repo = await _make_repo()
    session, _artifact = await _make_locked_session(_association(repo, role="direct"))
    await _record_repo_plan(session, repo)
    dispatcher = _FakeDispatcher()
    research = BlueprintResearchAdapter(
        dispatcher_factory=lambda: dispatcher, charters_loader=AsyncMock(return_value={})
    )

    result = await _plan_adapter(research_adapter=research).dispatch_plans(session)

    assert result == {
        "dispatched": 0,
        "synthesized": 0,
        "pending": 0,
        "completed": [str(repo.id)],
        "repositories": [str(repo.id)],
    }
    assert dispatcher.await_count == 0


async def test_no_locked_repos_returns_constant_empty_shape() -> None:
    session = await ConvergenceSession.objects.acreate(
        process_type="technical_blueprint",
        entrypoint=ConvergenceSessionEntrypoint.CHAT,
        current_stage="repo_plan",
    )
    assert await _plan_adapter().dispatch_plans(session) == {
        "dispatched": 0,
        "synthesized": 0,
        "pending": 0,
        "completed": [],
        "repositories": [],
    }


# ===========================================================================
# 5. indirect 服务端合成（不起容器）
# ===========================================================================


async def test_indirect_plan_synthesized_without_container() -> None:
    repo = await _make_repo()
    session, _artifact = await _make_locked_session(_association(repo, role="indirect"))
    dispatcher = _FakeDispatcher()
    research = BlueprintResearchAdapter(
        dispatcher_factory=lambda: dispatcher, charters_loader=AsyncMock(return_value={})
    )
    synthesizer = _FakeSynthesizer(
        {
            "repo_plan": {
                "repository_id": "ignored-by-server",
                "role": "direct",
                "impl_items": [],
                "apis_provided": [{"name": "listDrills", "method": "GET", "path": "/api/d/"}],
            }
        }
    )

    result = await _plan_adapter(research_adapter=research, synthesizer=synthesizer).dispatch_plans(
        session
    )

    assert result["synthesized"] == 1
    assert result["dispatched"] == 0
    assert dispatcher.await_count == 0

    plans = await _plan_adapter().acollect_repo_plans(session)
    section = plans[str(repo.id)]
    # 服务端权威字段覆写：repository_id / role 不采信 LLM 上报值
    assert section["repository_id"] == str(repo.id)
    assert section["role"] == "indirect"
    assert validate_repo_plan(section) == (True, None)


async def test_indirect_invalid_synthesis_degrades_and_opens_clarification() -> None:
    """连续非法 → degraded 但过 schema 的最小 repo_plan + blocking 澄清线程（不静默丢弃）。"""
    repo = await _make_repo()
    session, artifact = await _make_locked_session(_association(repo, role="indirect"))
    dispatcher = _FakeDispatcher()
    research = BlueprintResearchAdapter(
        dispatcher_factory=lambda: dispatcher, charters_loader=AsyncMock(return_value={})
    )
    # 三轮都非法（缺 impl_items）
    synthesizer = _FakeSynthesizer({"repo_plan": {"role": "indirect"}})

    result = await _plan_adapter(research_adapter=research, synthesizer=synthesizer).dispatch_plans(
        session
    )

    assert result["synthesized"] == 1
    assert synthesizer.calls == 3  # 首轮 + MAX_REPO_PLAN_ATTEMPTS 轮重试
    assert dispatcher.await_count == 0

    plans = await _plan_adapter().acollect_repo_plans(session)
    section = plans[str(repo.id)]
    assert validate_repo_plan(section) == (True, None)
    assert section["impl_items"] == []
    assert section["risks"], "degraded 产物必须写明缺失原因"

    thread = await BlueprintThread.objects.filter(
        artifact=artifact, kind=ThreadKind.AI_CLARIFICATION
    ).afirst()
    assert thread is not None
    assert thread.blocking is True
    assert thread.return_stage == "repo_plan"
    assert section["open_question_thread_ids"] == [str(thread.id)]


async def test_indirect_synthesizer_exception_is_isolated() -> None:
    """合成器抛异常 → 走同一有界重试通道，最终 degraded 落库（WR-02 不上抛）。"""
    repo = await _make_repo()
    session, _artifact = await _make_locked_session(_association(repo, role="indirect"))
    synthesizer = _FakeSynthesizer(RuntimeError("no_default_model"))

    result = await _plan_adapter(
        research_adapter=BlueprintResearchAdapter(dispatcher_factory=lambda: _FakeDispatcher()),
        synthesizer=synthesizer,
    ).dispatch_plans(session)

    assert result["synthesized"] == 1
    plans = await _plan_adapter().acollect_repo_plans(session)
    assert validate_repo_plan(plans[str(repo.id)]) == (True, None)


# ===========================================================================
# 6/7. 完成判据（自写，不复用调研 barrier）
# ===========================================================================


async def test_completion_criteria_requires_every_repo() -> None:
    repo_a = await _make_repo()
    repo_b = await _make_repo()
    session, _artifact = await _make_locked_session(
        _association(repo_a, role="direct"), _association(repo_b, role="direct")
    )
    adapter = _plan_adapter()

    await _record_repo_plan(session, repo_a)
    assert await adapter.aall_repo_plans_ready(session) is False

    await _record_repo_plan(session, repo_b)
    assert await adapter.aall_repo_plans_ready(session) is True


async def test_failed_repo_does_not_block_barrier() -> None:
    """失败仓不阻塞 barrier（由 merge 阶段标未决项，绝不永久卡住阶段 2）。"""
    repo_a = await _make_repo()
    repo_b = await _make_repo()
    session, _artifact = await _make_locked_session(
        _association(repo_a, role="direct"), _association(repo_b, role="direct")
    )
    await _record_repo_plan(session, repo_a)
    await RepoResearchTask.objects.acreate(
        session=session, repository=repo_b, status=RepoResearchTaskStatus.FAILED
    )

    assert await _plan_adapter().aall_repo_plans_ready(session) is True


async def test_criteria_only_looks_at_repo_plan_section_not_task_status() -> None:
    """task 状态翻成 stale 而产物仍 valid → 仍判 ready（不复用「全部 task 终态」判据）。"""
    repo = await _make_repo()
    session, _artifact = await _make_locked_session(_association(repo, role="direct"))
    task = await _record_repo_plan(session, repo)

    task.status = RepoResearchTaskStatus.STALE
    await task.asave(update_fields=["status"])

    assert await _plan_adapter().aall_repo_plans_ready(session) is True


async def test_repo_plan_collection_takes_latest_valid_row() -> None:
    """一仓多条 PartialPlan：valid=True + 最新一条作 canonical，历史行不被覆盖。"""
    repo = await _make_repo()
    session, _artifact = await _make_locked_session(_association(repo, role="direct"))
    task = await _record_repo_plan(session, repo)
    newest = _repo_plan_section(str(repo.id))
    newest["impl_items"][0]["item_id"] = "it_latest"
    await PartialPlan.objects.acreate(
        research_task=task,
        content={"repository_id": str(repo.id), "repo_plan": newest},
        content_hash="h2" * 4,
        valid=True,
    )

    plans = await _plan_adapter().acollect_repo_plans(session)
    assert plans[str(repo.id)]["impl_items"][0]["item_id"] == "it_latest"
    assert await PartialPlan.objects.filter(research_task=task).acount() == 2


# ===========================================================================
# 8/9. 定向补调研 + stage_state 小摘要
# ===========================================================================


async def test_targeted_research_delegates_to_upgrade_to_deep() -> None:
    repo = await _make_repo()
    session, _artifact = await _make_locked_session(_association(repo, role="direct"))
    research = BlueprintResearchAdapter(dispatcher_factory=lambda: _FakeDispatcher())
    research.aupgrade_to_deep = AsyncMock(return_value=True)  # type: ignore[method-assign]

    assert (
        await _plan_adapter(research_adapter=research).arequest_targeted_research(
            session, str(repo.id)
        )
        is True
    )
    research.aupgrade_to_deep.assert_awaited_once_with(session, str(repo.id))

    research.aupgrade_to_deep = AsyncMock(return_value=False)  # type: ignore[method-assign]
    assert (
        await _plan_adapter(research_adapter=research).arequest_targeted_research(
            session, str(repo.id)
        )
        is False
    )


async def test_repo_completed_event_counts_read_the_real_repo_plan_keys() -> None:
    """⭐ 回归守卫：`repo_plan.repo_completed` 的计数必须读 RepoPlan 段的**真实字段名**。

    曾误读蓝图顶层的 ``implementation_items`` / ``api_contracts`` —— RepoPlan 段里根本没有
    这两个键（实现项是 ``impl_items``、接口分 ``apis_provided`` / ``apis_consumed``）⇒ 两个
    计数恒为 0，界面上每个仓都是「0 项实现 · 0 条接口」，用户点名过这条。

    ⛔ 这里断言的是**非零**：只要还有人把键名改回顶层口径，本测试立刻红。
    """
    repo = await _make_repo()
    session, _artifact = await _make_locked_session(_association(repo, role="direct"))
    task = await RepoResearchTask.objects.acreate(
        session=session, repository=repo, status=RepoResearchTaskStatus.DONE
    )

    section = _repo_plan_section(str(repo.id))
    section["impl_items"] = [
        {"item_id": f"it_{i}", "title": "改动", "change_type": "modify", "how": "改一处"}
        for i in range(3)
    ]
    section["apis_provided"] = [{"name": "GET /a"}, {"name": "GET /b"}]
    section["apis_consumed"] = [{"name": "GET /c", "from_repository_id": "other"}]
    section["current_state"] = [{"summary": "现状", "findings": []}]
    section["risks"] = [{"block_id": "blk_risk", "type": "paragraph", "text": "风险"}]
    section["open_question_thread_ids"] = ["th_1"]

    with patch(
        "delivery.services.convergence_session_service.ConvergenceSessionService.aemit_event",
        new=AsyncMock(),
    ) as emit:
        await _plan_adapter().arecord_repo_plan(task, section)

    completed = [
        call for call in emit.call_args_list if call.args[0] == "blueprint.repo_plan.repo_completed"
    ]
    assert len(completed) == 1
    payload = completed[0].args[2]
    assert payload["item_count"] == 3
    # 供需两侧合计（前端既有消费方按 `api_count` 显示「N 条接口」）
    assert payload["api_count"] == 3
    assert payload["api_provided_count"] == 2
    assert payload["api_consumed_count"] == 1
    assert payload["role"] == "direct"
    assert payload["current_state_count"] == 1
    assert payload["risk_count"] == 1
    assert payload["open_question_count"] == 1
    assert payload["repository_id"] == str(repo.id)


async def test_stage_state_summary_is_ids_and_counts_only() -> None:
    summary = _plan_adapter().build_stage_state(
        plans={"r1": {"impl_items": [{"item_id": "x"}]}, "r2": {}},
        dispatched=["r2"],
        pending=["r2", "r3"],
    )
    assert summary["ready_repository_ids"] == ["r1"]
    assert summary["pending_repository_ids"] == ["r2", "r3"]
    assert summary["attempts"] == {"r2": 1}
    assert set(summary) == {"ready_repository_ids", "pending_repository_ids", "attempts"}
    assert len(json.dumps(summary)) < 2048
