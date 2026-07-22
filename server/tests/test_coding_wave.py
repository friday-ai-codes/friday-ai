"""AICodingNode wave 调度集成测试（Phase 44-05，WAVE-01/02）。

覆盖三场景（mock IO 边界 = dispatcher + git token + MR 创建 + 通知 + 子步骤；
ORM 走真实 DB transaction=True）：

- test_empty_deps_zero_regression：无 plan_version_id 的 legacy plan → 首发一次性
  dispatch 全部仓、**不建 RepoCodingTask**，单次 resume 即收尾出 MR（零回归命门）。
- test_multi_wave_progression：repoB depends repoA → 首发仅 dispatch repoA(wave0)；
  repoA done 回调 resume → dispatch repoB(wave1) 再 waiting_event；repoB done → 收尾两仓 MR。
- test_partial_success_finalize：wave0 repoA done / repoB failed，repoC(wave1) depends
  repoB → resume 后 repoC 标 blocked(upstream_failed) 不 dispatch，收尾 repoA 出 MR、
  repoB/repoC 如实失败，无自动回滚（仅 done 仓出 MR）。

驱动 wave N→N+1 不另造调度：测试手工模拟 `_schedule_workflow_resume` 回调（置
output_data `_resume_from_callback=True` 重入 execute），与生产回调通路同形。
"""

from __future__ import annotations

import uuid
from typing import Any
from unittest.mock import AsyncMock

import pytest

from delivery.models import (
    Artifact,
    ArtifactVersion,
    RepoCodingTask,
    RepoCodingTaskStatus,
)
from repositories.models import Repository
from services.process_runtime.wave_progression import aadvance_coding_waves
from subagent.models import SubAgentSession, TaskResult
from workflows.nodes.ai.coding import AICodingNode
from workflows.nodes.base import ExecutionContext, NodeResult

pytestmark = [pytest.mark.django_db(transaction=True), pytest.mark.asyncio]


# ---------------------------------------------------------------------------
# Fixtures / harness
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _stub_provider_resolution(monkeypatch: pytest.MonkeyPatch) -> None:
    """stub Anthropic 凭证解析，使测试无需真实 ProviderCredential 行。"""
    from services.provider_config import (
        ProviderConfigService,
        ProviderType,
        ResolvedProviderConfig,
    )

    async def _resolve(*args: object, **kwargs: object) -> ResolvedProviderConfig:
        return ResolvedProviderConfig(
            provider_type=ProviderType.ANTHROPIC,
            api_key="sk-ant-test",
            base_url="https://api.anthropic.com",
            source="system",
        )

    monkeypatch.setattr(ProviderConfigService, "aresolve_or_error", _resolve)


@pytest.fixture
def _dispatched(monkeypatch: pytest.MonkeyPatch) -> list[Any]:
    """捕获 dispatch 的 DispatchTask（mock runner dispatcher）。"""
    captured: list[Any] = []

    class _FakeDispatcher:
        async def dispatch(self, task: Any) -> None:
            captured.append(task)

    monkeypatch.setattr("runners.dispatcher.get_dispatcher", lambda: _FakeDispatcher())

    async def _token(*args: Any, **kwargs: Any) -> str:
        return ""

    monkeypatch.setattr("workflows.nodes.ai.coding.aresolve_git_token", _token)

    async def _noop_ingest(*args: Any, **kwargs: Any) -> None:
        return None

    monkeypatch.setattr("knowledge.ingestion.aschedule_ingestion", _noop_ingest)
    return captured


async def _make_node_execution() -> Any:
    """建真实 NodeExecution 链（含可被 _create_session 命中的 main AgentSession）。

    用真实 NodeExecution（非替身）：① _run_repo_coding._create_session 经 node_execution
    → workflow_execution → 同 metadata 的 main AgentSession 命中同一 main_session，避免并行
    dispatch 各建占位 AgentSession 撞 session_id unique；② _finalize_and_notify 真实
    output_data 持久化路径。
    """
    from agents.models import AgentSession
    from projects.models import Space
    from workflows.models import (
        NodeExecution,
        Workflow,
        WorkflowExecution,
        WorkflowNode,
    )

    project = await Space.objects.acreate(name=f"proj-{uuid.uuid4().hex[:6]}")
    workflow = await Workflow.objects.acreate(name="wf-wave", space=project)
    wf_node = await WorkflowNode.objects.acreate(
        workflow=workflow, node_type="ai_coding", name="AI 编码"
    )
    wf_exec = await WorkflowExecution.objects.acreate(
        workflow=workflow, space=project, trigger_type="manual"
    )
    node_exec = await NodeExecution.objects.acreate(
        workflow_execution=wf_exec, node=wf_node, status="running"
    )
    await AgentSession.objects.acreate(
        session_id=f"main-{uuid.uuid4().hex[:8]}",
        metadata={"workflow_execution_id": str(wf_exec.id)},
    )
    return node_exec


def _make_node() -> AICodingNode:
    """构造 node 并 stub 子步骤 / 通知 / MR 创建 / PAT（仅 IO 边界）。"""
    node = AICodingNode()
    node.emit_sub_step = AsyncMock()  # type: ignore[method-assign]
    node._init_sub_steps = AsyncMock()  # type: ignore[method-assign]
    node._send_result_notification = AsyncMock()  # type: ignore[method-assign]
    node._resolve_dispatch_user = AsyncMock(return_value=None)  # type: ignore[method-assign]

    mr_calls: list[Repository] = []

    async def _fake_mr(*, repository: Repository, **kwargs: Any) -> dict[str, Any]:
        mr_calls.append(repository)
        return {"mr_url": f"https://mr/{repository.name}", "mr_id": "1"}

    node._create_mr_for_repo = AsyncMock(side_effect=_fake_mr)  # type: ignore[method-assign]
    node._mr_calls = mr_calls  # type: ignore[attr-defined]
    return node


def _make_context(plan: dict[str, Any], node_exec: Any) -> ExecutionContext:
    return ExecutionContext(
        execution_id="exec-wave-001",
        node_id="node-coding-wave",
        node_config={"timeout_seconds": 10, "chat_id": ""},
        input_data={"plan": plan},
        workflow_context={},
        previous_outputs={},
        trigger_data={"payload": {"work_item_id": "999"}},
        workflow_execution=None,
        node_execution=node_exec,  # type: ignore[arg-type]
    )


async def _make_repo(name: str) -> Repository:
    return await Repository.objects.acreate(
        name=f"{name}-{uuid.uuid4().hex[:6]}",
        git_url=f"https://github.com/test/{uuid.uuid4().hex[:6]}.git",
        git_platform="github",
        default_branch="main",
        index_status="indexed",
    )


async def _make_plan_version() -> ArtifactVersion:
    artifact = await Artifact.objects.acreate(artifact_type="technical_plan")
    av = await ArtifactVersion.objects.acreate(
        artifact=artifact, version_no=1, content={}, content_hash="h"
    )
    artifact.current_version = av
    await artifact.asave(update_fields=["current_version", "updated_at"])
    return av


async def _settle_session(
    plan_version: ArtifactVersion,
    repo_id: str,
    *,
    ok: bool,
    modified_files: list[str] | None = None,
) -> None:
    """把某仓 RepoCodingTask 关联的 SubAgentSession 置终态（模拟容器完成）。

    ``modified_files`` 默认 ``["f.py"]``（既有 wave 测试零回归）；happy-path 产物传递测试
    传入 openapi 契约文件名（如 ``["api/openapi.yaml"]``）以驱动 Plan 01 提取归类。
    """
    task = await RepoCodingTask.objects.aget(artifact_version=plan_version, repository_id=repo_id)
    sess = await SubAgentSession.objects.aget(id=task.subagent_session_id)
    sess.status = SubAgentSession.Status.COMPLETED if ok else SubAgentSession.Status.ERROR
    sess.last_error = "" if ok else "container boom"
    await sess.asave(update_fields=["status", "last_error"])
    if ok:
        await TaskResult.objects.acreate(
            session=sess,
            pr_url=f"https://mr/{repo_id}",
            modified_files=modified_files if modified_files is not None else ["f.py"],
            raw_output={},
        )


def _resume(node_exec: Any, prev_output: dict[str, Any]) -> None:
    """模拟 _schedule_workflow_resume 回调：置恢复标记重入 execute。"""
    node_exec.output_data = {**prev_output, "_resume_from_callback": True}


def _dispatched_repo_ids(captured: list[Any]) -> set[str]:
    return {t.metadata["repository_id"] for t in captured}


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


async def test_empty_deps_zero_regression(
    _dispatched: list[Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    """无 plan_version_id + 空依赖 → 一次性 dispatch 全部仓、不建 RepoCodingTask、单 resume 收尾。

    Phase 51 零回归门：legacy 非 wave 模式（tasks_by_repo=None）dispatch **不经 openspec gate、
    不查 SddSpec**（gate helper 在该路径完全短路）。
    """
    from delivery.models import SddSpec

    def _no_spec_query(*args: Any, **kwargs: Any):
        raise AssertionError("legacy 非 wave 路径不应触发 SddSpec 查询（gate 须短路）")

    monkeypatch.setattr(SddSpec.objects, "filter", _no_spec_query)

    repo_a = await _make_repo("zr-a")
    repo_b = await _make_repo("zr-b")
    id_a, id_b = str(repo_a.id), str(repo_b.id)

    plan = {
        "title": "zero-reg",
        "branch_name": "feat/zr",
        "global_context": "",
        "execution_plan": [
            {"id": "t1", "repository_id": id_a, "name": "A", "coding_instruction": "a"},
            {"id": "t2", "repository_id": id_b, "name": "B", "coding_instruction": "b"},
        ],
        # 故意不带 plan_version_id → legacy 全并行路径
    }
    node = _make_node()
    ne = await _make_node_execution()
    ctx = _make_context(plan, ne)

    result: NodeResult = await node.execute(ctx)

    assert result.status == "waiting_event"
    # 一次性 dispatch 全部仓（== 仓数）。
    assert _dispatched_repo_ids(_dispatched) == {id_a, id_b}
    # 零回归：legacy 路径不建 RepoCodingTask 行。
    assert await RepoCodingTask.objects.acount() == 0
    # waiting output 不挂 wave 锚（plan_version_id 为空）。
    assert result.output.get("plan_version_id", "") == ""
    assert len(result.output["pending_sessions"]) == 2

    # 单次 resume 即收尾（legacy _resume_legacy，无额外 wave 轮次）。
    for sess_info in result.output["pending_sessions"]:
        sess = await SubAgentSession.objects.aget(session_id=sess_info["session_id"])
        sess.status = SubAgentSession.Status.COMPLETED
        await sess.asave(update_fields=["status"])
        await TaskResult.objects.acreate(session=sess, pr_url="https://mr/x", raw_output={})

    _resume(ne, result.output)
    final: NodeResult = await node.execute(ctx)

    assert final.status == "completed"
    assert len(node._mr_calls) == 2  # type: ignore[attr-defined]


async def test_multi_wave_progression(_dispatched: list[Any]) -> None:
    """repoB depends repoA → 首发仅 dispatch wave0(repoA)，resume 后 dispatch wave1(repoB)，再 resume 收尾。"""
    pv = await _make_plan_version()
    repo_a = await _make_repo("mw-a")
    repo_b = await _make_repo("mw-b")
    id_a, id_b = str(repo_a.id), str(repo_b.id)

    plan = {
        "title": "multi-wave",
        "branch_name": "feat/mw",
        "global_context": "",
        "artifact_version_id": str(pv.id),
        "execution_plan": [
            {"id": "t1", "repository_id": id_a, "name": "A", "coding_instruction": "a"},
            {
                "id": "t2",
                "repository_id": id_b,
                "dependencies": ["t1"],
                "name": "B",
                "coding_instruction": "b",
            },
        ],
    }
    node = _make_node()
    ne = await _make_node_execution()
    ctx = _make_context(plan, ne)

    # ── 首发：仅 dispatch repoA(wave0) ──
    r1: NodeResult = await node.execute(ctx)
    assert r1.status == "waiting_event"
    assert _dispatched_repo_ids(_dispatched) == {id_a}
    assert r1.output["plan_version_id"] == str(pv.id)
    # RepoCodingTask：2 行；repoA running（含 subagent_session）、repoB pending。
    task_a = await RepoCodingTask.objects.aget(artifact_version=pv, repository_id=id_a)
    task_b = await RepoCodingTask.objects.aget(artifact_version=pv, repository_id=id_b)
    assert task_a.status == RepoCodingTaskStatus.RUNNING
    assert task_a.subagent_session_id is not None
    assert task_b.status == RepoCodingTaskStatus.PENDING

    # ── repoA 容器完成 → resume → dispatch repoB(wave1) ──
    await _settle_session(pv, id_a, ok=True)
    _dispatched.clear()
    _resume(ne, r1.output)
    r2: NodeResult = await node.execute(ctx)

    assert r2.status == "waiting_event"
    assert _dispatched_repo_ids(_dispatched) == {id_b}  # 仅 wave1 repoB
    task_a = await RepoCodingTask.objects.aget(id=task_a.id)
    task_b = await RepoCodingTask.objects.aget(id=task_b.id)
    assert task_a.status == RepoCodingTaskStatus.DONE
    assert task_b.status == RepoCodingTaskStatus.RUNNING

    # ── repoB 容器完成 → resume → all_terminal 收尾两仓 MR ──
    await _settle_session(pv, id_b, ok=True)
    _dispatched.clear()
    _resume(ne, r2.output)
    r3: NodeResult = await node.execute(ctx)

    assert r3.status == "completed"
    assert _dispatched_repo_ids(_dispatched) == set()  # 无更多 dispatch
    mr_repo_ids = {str(r.id) for r in node._mr_calls}  # type: ignore[attr-defined]
    assert mr_repo_ids == {id_a, id_b}


async def test_partial_success_finalize(_dispatched: list[Any]) -> None:
    """wave0 repoA done / repoB failed，repoC depends repoB → repoC blocked，收尾仅 repoA 出 MR，无回滚。"""
    pv = await _make_plan_version()
    repo_a = await _make_repo("ps-a")
    repo_b = await _make_repo("ps-b")
    repo_c = await _make_repo("ps-c")
    id_a, id_b, id_c = str(repo_a.id), str(repo_b.id), str(repo_c.id)

    plan = {
        "title": "partial",
        "branch_name": "feat/ps",
        "global_context": "",
        "artifact_version_id": str(pv.id),
        "execution_plan": [
            {"id": "t1", "repository_id": id_a, "name": "A", "coding_instruction": "a"},
            {"id": "t2", "repository_id": id_b, "name": "B", "coding_instruction": "b"},
            {
                "id": "t3",
                "repository_id": id_c,
                "dependencies": ["t2"],
                "name": "C",
                "coding_instruction": "c",
            },
        ],
    }
    node = _make_node()
    ne = await _make_node_execution()
    ctx = _make_context(plan, ne)

    # ── 首发：dispatch wave0 = {repoA, repoB}；repoC(wave1) pending ──
    r1: NodeResult = await node.execute(ctx)
    assert r1.status == "waiting_event"
    assert _dispatched_repo_ids(_dispatched) == {id_a, id_b}
    task_c = await RepoCodingTask.objects.aget(artifact_version=pv, repository_id=id_c)
    assert task_c.status == RepoCodingTaskStatus.PENDING

    # ── repoA done、repoB failed → resume → repoC 被阻断、收尾 ──
    await _settle_session(pv, id_a, ok=True)
    await _settle_session(pv, id_b, ok=False)
    _dispatched.clear()
    _resume(ne, r1.output)
    r2: NodeResult = await node.execute(ctx)

    # repoC 永不 dispatch（被阻断）。
    assert _dispatched_repo_ids(_dispatched) == set()
    # 部分成功：repoA 出 MR → 节点 completed（mr_results 非空）。
    assert r2.status == "completed"

    task_a = await RepoCodingTask.objects.aget(artifact_version=pv, repository_id=id_a)
    task_b = await RepoCodingTask.objects.aget(artifact_version=pv, repository_id=id_b)
    task_c = await RepoCodingTask.objects.aget(artifact_version=pv, repository_id=id_c)
    assert task_a.status == RepoCodingTaskStatus.DONE
    assert task_b.status == RepoCodingTaskStatus.FAILED
    assert task_c.status == RepoCodingTaskStatus.FAILED
    assert task_c.error.get("reason") == "upstream_failed"

    # 无自动回滚：仅 done 仓(repoA)出 MR，failed/blocked 仓不出 MR、不回退。
    mr_repo_ids = {str(r.id) for r in node._mr_calls}  # type: ignore[attr-defined]
    assert mr_repo_ids == {id_a}
    # 失败/阻断仓如实标注在 coding_result.failed_details。
    failed_details = r2.output["coding_result"]["failed_details"]
    failed_ids = {f["repository_id"] for f in failed_details}
    assert {id_b, id_c} <= failed_ids
    # repoC 的失败标注为上游阻断（upstream_failed 文案）。
    c_detail = next(f for f in failed_details if f["repository_id"] == id_c)
    assert "upstream_failed" in c_detail["error"]


async def test_dependency_cycle_fails_fast(_dispatched: list[Any]) -> None:
    """依赖环 → 节点 failed（不进 dispatch、不建 RepoCodingTask）。"""
    pv = await _make_plan_version()
    repo_a = await _make_repo("cy-a")
    repo_b = await _make_repo("cy-b")
    id_a, id_b = str(repo_a.id), str(repo_b.id)

    plan = {
        "title": "cycle",
        "branch_name": "feat/cy",
        "global_context": "",
        "artifact_version_id": str(pv.id),
        "execution_plan": [
            {"id": "t1", "repository_id": id_a, "dependencies": ["t2"], "coding_instruction": "a"},
            {"id": "t2", "repository_id": id_b, "dependencies": ["t1"], "coding_instruction": "b"},
        ],
    }
    node = _make_node()
    ne = await _make_node_execution()
    ctx = _make_context(plan, ne)

    result: NodeResult = await node.execute(ctx)

    assert result.status == "failed"
    assert result.next_handle == "error"
    assert _dispatched_repo_ids(_dispatched) == set()
    assert await RepoCodingTask.objects.acount() == 0


def _wave_task(captured: list[Any], repo_id: str) -> Any:
    """取捕获的某仓 DispatchTask（断言其 prompt / metadata）。"""
    return next(t for t in captured if t.metadata["repository_id"] == repo_id)


async def test_artifact_passthrough(_dispatched: list[Any]) -> None:
    """端到端产物传递（SC-3）：wave1 后端仓 done（TaskResult 含 openapi 契约）→ aadvance
    回填触发提取落 produced_artifacts → wave2 前端仓 dispatch 的 prompt 含上游契约文件名。
    """
    pv = await _make_plan_version()
    repo_backend = await _make_repo("ap-backend")
    repo_frontend = await _make_repo("ap-frontend")
    id_be, id_fe = str(repo_backend.id), str(repo_frontend.id)
    openapi_file = "api/openapi.yaml"

    plan = {
        "title": "artifact-passthrough",
        "branch_name": "feat/ap",
        "global_context": "跨仓契约传递",
        "artifact_version_id": str(pv.id),
        "execution_plan": [
            {"id": "t1", "repository_id": id_be, "name": "后端", "coding_instruction": "建契约"},
            {
                "id": "t2",
                "repository_id": id_fe,
                "dependencies": ["t1"],  # 跨仓边：前端依赖后端
                "name": "前端",
                "coding_instruction": "消费契约",
            },
        ],
    }
    node = _make_node()
    ne = await _make_node_execution()
    ctx = _make_context(plan, ne)

    # ── 首发：仅 dispatch wave0(后端仓) ──
    r1: NodeResult = await node.execute(ctx)
    assert r1.status == "waiting_event"
    assert _dispatched_repo_ids(_dispatched) == {id_be}

    # ── 后端容器完成（TaskResult.modified_files 含 openapi 契约）→ resume →
    #     回填 done 触发提取落 produced_artifacts → dispatch wave1(前端仓) ──
    await _settle_session(pv, id_be, ok=True, modified_files=[openapi_file, "src/app.py"])
    _dispatched.clear()
    _resume(ne, r1.output)
    r2: NodeResult = await node.execute(ctx)

    assert r2.status == "waiting_event"
    assert _dispatched_repo_ids(_dispatched) == {id_fe}  # 仅 wave1 前端仓

    # 提取落库正确：后端 task.produced_artifacts["openapi"] 含契约文件。
    task_be = await RepoCodingTask.objects.aget(artifact_version=pv, repository_id=id_be)
    assert task_be.status == RepoCodingTaskStatus.DONE
    assert task_be.produced_artifacts.get("available") is True
    assert openapi_file in task_be.produced_artifacts["openapi"]

    # 产物传递正确：前端 DispatchTask.prompt 含「上游产物」段 + 上游契约文件名。
    fe_task = _wave_task(_dispatched, id_fe)
    assert "上游产物" in fe_task.prompt
    assert openapi_file in fe_task.prompt
    # 仅传递白名单字段（路径），绝不内联 raw_output 正文（T-45-10）。
    assert "raw_output" not in fe_task.prompt


async def test_artifact_passthrough_idempotent(_dispatched: list[Any]) -> None:
    """幂等（D-15）：wave1 done 后重复触发回填/提取 → produced_artifacts 不漂移（no-op）。

    回填仅遍历 RUNNING task + mark_done 条件更新（running→done），已 done 仓不再进提取段，
    故重复 aadvance 对其 produced_artifacts 是覆盖写 no-op（含 extracted_at 不变）。
    """
    pv = await _make_plan_version()
    repo_backend = await _make_repo("idem-backend")
    repo_frontend = await _make_repo("idem-frontend")
    id_be, id_fe = str(repo_backend.id), str(repo_frontend.id)

    plan = {
        "title": "idem",
        "branch_name": "feat/idem",
        "global_context": "",
        "artifact_version_id": str(pv.id),
        "execution_plan": [
            {"id": "t1", "repository_id": id_be, "name": "后端", "coding_instruction": "a"},
            {
                "id": "t2",
                "repository_id": id_fe,
                "dependencies": ["t1"],
                "name": "前端",
                "coding_instruction": "b",
            },
        ],
    }
    node = _make_node()
    ne = await _make_node_execution()
    ctx = _make_context(plan, ne)

    # 首发 → 后端 done → resume → 提取落库 + dispatch 前端。
    r1: NodeResult = await node.execute(ctx)
    await _settle_session(pv, id_be, ok=True, modified_files=["api/openapi.yaml"])
    _dispatched.clear()
    _resume(ne, r1.output)
    await node.execute(ctx)

    task_be = await RepoCodingTask.objects.aget(artifact_version=pv, repository_id=id_be)
    artifacts_first = dict(task_be.produced_artifacts)
    assert artifacts_first.get("available") is True

    # ── 重复触发回填/提取：后端已 done（非 RUNNING）→ 不再提取，前端仍 RUNNING → waiting ──
    _dispatched.clear()
    again = await aadvance_coding_waves(pv.id)
    assert again.get("waiting") is True  # advance 不冒泡、不重复派发

    task_be = await RepoCodingTask.objects.aget(artifact_version=pv, repository_id=id_be)
    # 覆盖写 no-op：produced_artifacts 逐字不漂移（含 extracted_at）。
    assert task_be.produced_artifacts == artifacts_first
    assert _dispatched_repo_ids(_dispatched) == set()  # 无重复异常派发


async def test_artifact_extract_fail_soft(
    _dispatched: list[Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    """fail-soft（D-15 / T-45-09）：提取链抛异常 → wave1 仍 done、wave 推进、wave2 仍 dispatch
    且注入段为空，advance 不冒泡（容器回调不 5xx）。
    """

    def _boom(*args: Any, **kwargs: Any) -> dict:
        raise RuntimeError("extract boom")

    # _backfill_running_terminal 内局部 import build_produced_artifacts → patch 源模块属性。
    monkeypatch.setattr(
        "services.process_runtime.artifact_extraction.build_produced_artifacts",
        _boom,
    )

    pv = await _make_plan_version()
    repo_backend = await _make_repo("fs-backend")
    repo_frontend = await _make_repo("fs-frontend")
    id_be, id_fe = str(repo_backend.id), str(repo_frontend.id)

    plan = {
        "title": "fail-soft",
        "branch_name": "feat/fs",
        "global_context": "",
        "artifact_version_id": str(pv.id),
        "execution_plan": [
            {"id": "t1", "repository_id": id_be, "name": "后端", "coding_instruction": "a"},
            {
                "id": "t2",
                "repository_id": id_fe,
                "dependencies": ["t1"],
                "name": "前端",
                "coding_instruction": "b",
            },
        ],
    }
    node = _make_node()
    ne = await _make_node_execution()
    ctx = _make_context(plan, ne)

    # 首发 → 后端 done（提取将抛错）→ resume → advance 推进。
    r1: NodeResult = await node.execute(ctx)
    await _settle_session(pv, id_be, ok=True, modified_files=["api/openapi.yaml"])
    _dispatched.clear()
    _resume(ne, r1.output)
    r2: NodeResult = await node.execute(ctx)  # 提取异常被 swallow，绝不冒泡

    # wave 推进不失败：后端仍正确 done，前端正常 dispatch。
    assert r2.status == "waiting_event"
    assert _dispatched_repo_ids(_dispatched) == {id_fe}

    task_be = await RepoCodingTask.objects.aget(artifact_version=pv, repository_id=id_be)
    assert task_be.status == RepoCodingTaskStatus.DONE
    # 提取失败 → produced_artifacts 留空（未落库），下游注入段为空（零回归降级）。
    assert task_be.produced_artifacts == {}

    fe_task = _wave_task(_dispatched, id_fe)
    assert "上游产物" not in fe_task.prompt  # 注入段为空
