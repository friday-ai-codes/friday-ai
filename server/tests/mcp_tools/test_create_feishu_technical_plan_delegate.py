"""create_feishu_technical_plan delegate 守护测试（Phase 94 UNIFY-03）。

覆盖：
- Task 1：``delegate_process_runtime`` 三态映射（DONE→completed / RESEARCHING→partial /
  FAILED→failed），DONE 含 render 后 markdown + canonical content + plan_version_id；
  partial 可取 session_id。
- Task 2：``create_feishu_technical_plan`` 经 delegate 接线后响应外形 snapshot（旧键全在 +
  新增 session_id）+ McpWorkItemTechnicalPlan 落库兼容 + delegate 被调（不再走
  ``_build_repo_task_matrix``）+ 缺 actor 降级不崩。
- Task 2 ③：MCP 同步达 DONE 契约（真实 delegate 路径、空 node_execution_id、research 同步
  解析）。**调用方契约**：当 RESEARCHING 真在途（容器未就绪、MCP 无 resume 通路）时 delegate
  默认返回 ``status="partial"`` + ``session_id``，调用方须容忍 PARTIAL 并经会话/工作流续推。
"""

from __future__ import annotations

import uuid
from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock

import pytest
from rest_framework.test import APIClient

from delivery.models import (
    Artifact,
    ArtifactVersion,
    ConvergenceSession,
    ConvergenceSessionEntrypoint,
    ConvergenceSessionStatus,
)
from interactions.ledger import create_interaction_run
from mcp_tools.models import McpWorkItemContext, McpWorkItemTechnicalPlan
from runners.models import hash_token

pytestmark = pytest.mark.django_db

# create_feishu_technical_plan 响应外形契约：旧键集合不得缩减（T-94-03-COMPAT snapshot 守护）。
_LEGACY_OUTPUT_KEYS = {
    "technical_plan_id",
    "context_id",
    "project_id",
    "plan",
    "markdown",
    "repository_tasks",
    "evidence",
    "feishu_document",
    "comment",
    "status",
    "retry_state",
    "run_id",
}

# 嵌套 plan / 落库 plan_body 外形契约（WR-02：旧关键键映射自 canonical，外形兼容守护）。
_LEGACY_PLAN_KEYS = {
    "title",
    "summary",
    "work_item",
    "repository_task_matrix",
    "linked_documents",
    "similar_cases",
    "evidence",
    "context_preview",
}


def _merged_content(repo_id: str, repo_name: str) -> dict:
    """合法 §7 MergedPlan content（单仓最小集，过 validate_merged_plan）。"""
    return {
        "title": "登录超时修复跨仓方案",
        "summary": "在 auth 仓修复 token 刷新边界。",
        "api_contracts": [],
        "dependency_dag": {},
        "data_migrations": [],
        "compat_risks": ["token 边界变更需回归登录态"],
        "release_order": [repo_id],
        "rollback_plan": {repo_id: "revert 对应 PR"},
        "execution_plan": [
            {
                "id": "t1",
                "name": "修复 token 刷新",
                "description": "对齐刷新边界",
                "repository_id": repo_id,
                "repository_name": repo_name,
                "branch_strategy": "feature",
                "coding_instruction": "在 session 校验处补刷新边界判断并加测试。",
                "dependencies": [],
                # WR-01/IN-02：canonical task 携带方案细节 + 基线分支（映射须透传至 repository_tasks）。
                "base_branch": "release/2026.06",
                "steps": ["定位 session 校验入口", "补刷新边界判断", "加回归测试"],
                "test_strategy": ["针对刷新边界补单测", "回归登录态 e2e"],
                "risks": ["token 边界变更需回归登录态"],
                "rollback": "revert 对应 PR 并回滚刷新边界判断。",
            }
        ],
    }


async def _make_plan_version(content: dict) -> ArtifactVersion:
    artifact = await Artifact.objects.acreate(artifact_type="technical_plan")
    version = await ArtifactVersion.objects.acreate(
        artifact=artifact, version_no=1, content=content, content_hash="h"
    )
    await Artifact.objects.filter(id=artifact.id).aupdate(current_version=version)
    return version


async def _make_session(
    status: str, *, current_stage: str = "merge", plan_version_id: Any = None
) -> ConvergenceSession:
    return await ConvergenceSession.objects.acreate(
        process_type="technical_plan",
        entrypoint=ConvergenceSessionEntrypoint.WORKFLOW,
        current_stage=current_stage,
        status=status,
        stage_state={"decomposition": {"requirement_text": "登录超时", "include_repos": []}},
        current_artifact_version_id=plan_version_id,
    )


def _patch_delegate_pipeline(monkeypatch: pytest.MonkeyPatch, *, session: ConvergenceSession) -> None:
    """monkeypatch delegate 调用的共享 helper（start/build/adrive）使其返回指定 session。"""

    async def _fake_start(*_args: Any, **_kwargs: Any) -> ConvergenceSession:
        return session

    async def _fake_adrive(_engine: Any, _session: Any, **_kwargs: Any) -> ConvergenceSession:
        return session

    monkeypatch.setattr("services.process_runtime.start_orchestration", _fake_start)
    monkeypatch.setattr(
        "services.process_runtime.build_orchestration_engine",
        lambda **_kwargs: MagicMock(),
    )
    monkeypatch.setattr(
        "services.process_runtime.adrive_convergence_session_to_pause_or_terminal",
        _fake_adrive,
    )


# ============================== Task 1: delegate 三态映射 ==============================


@pytest.mark.asyncio
async def test_delegate_done_maps_completed_with_canonical_and_markdown(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from mcp_tools.orchestration_delegate import delegate_process_runtime

    repo_id = str(uuid.uuid4())
    version = await _make_plan_version(_merged_content(repo_id, "auth-service"))
    session = await _make_session(ConvergenceSessionStatus.DONE, plan_version_id=version.id)
    _patch_delegate_pipeline(monkeypatch, session=session)

    result = await delegate_process_runtime(requirement_text="登录超时", include_repos=[repo_id])

    assert result.status == "completed"
    assert result.plan_version_id == str(version.id)
    assert result.content["title"] == "登录超时修复跨仓方案"
    assert result.content["execution_plan"][0]["repository_id"] == repo_id
    # markdown 经 render_merged_plan_markdown（复用 94-01 helper），含结构化标题/风险渲染。
    assert "登录超时修复跨仓方案" in result.markdown
    assert "token 边界变更需回归登录态" in result.markdown


@pytest.mark.asyncio
async def test_delegate_researching_maps_partial_with_session(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from mcp_tools.orchestration_delegate import delegate_process_runtime

    session = await _make_session(ConvergenceSessionStatus.WAITING_EVENT, current_stage="research")
    _patch_delegate_pipeline(monkeypatch, session=session)

    result = await delegate_process_runtime(requirement_text="登录超时")

    assert result.status == "partial"
    # 调用方据 session_id 后续经会话/工作流续推（MCP 无 resume 通路）。
    assert str(result.session.id) == str(session.id)
    assert result.plan_version_id is None
    assert result.content == {}
    assert result.markdown == ""


@pytest.mark.asyncio
async def test_delegate_failed_maps_failed_empty(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from mcp_tools.orchestration_delegate import delegate_process_runtime

    session = await _make_session(ConvergenceSessionStatus.FAILED)
    _patch_delegate_pipeline(monkeypatch, session=session)

    result = await delegate_process_runtime(requirement_text="登录超时")

    assert result.status == "failed"
    assert result.content == {}
    assert result.plan_version_id is None
    assert result.markdown == ""


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_delegate_aggregates_orchestration_model_usage(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """WR-03：编排 adapters 落 run 未绑定的用量行 → delegate 聚合本次驱动窗口回传 model_usage。

    必须 transaction=True：本用例经 async ORM（``acreate``）落 ModelUsageRecord，
    ``sync_to_async`` 在独立线程拿到另一条 DB 连接，写入会直接提交、逃出模块级非事务
    ``django_db`` 的回滚，污染后续按 provider 聚合 token 的用例
    （``test_metrics_query.py::test_tps_sum_tokens_by_provider`` 曾因此多出 200 tokens）。
    transaction=True 让 pytest-django 在用例结束后 truncate，泄漏不再跨用例。
    """
    from interactions.models import ModelUsageRecord
    from mcp_tools.orchestration_delegate import delegate_process_runtime

    repo_id = str(uuid.uuid4())
    version = await _make_plan_version(_merged_content(repo_id, "auth-service"))
    session = await _make_session(ConvergenceSessionStatus.DONE, plan_version_id=version.id)

    async def _fake_start(*_args: Any, **_kwargs: Any) -> ConvergenceSession:
        return session

    async def _fake_adrive(_engine: Any, _session: Any, **_kwargs: Any) -> ConvergenceSession:
        # 模拟编排 adapter 落一行用量（run=None，挂 call_source 维度，不挂 MCP run）。
        await ModelUsageRecord.objects.acreate(
            run=None,
            provider="anthropic",
            model="claude",
            call_source="plan_deepen",
            prompt_tokens=120,
            completion_tokens=80,
            total_tokens=200,
            duration_ms=42,
        )
        return session

    monkeypatch.setattr("services.process_runtime.start_orchestration", _fake_start)
    monkeypatch.setattr(
        "services.process_runtime.build_orchestration_engine",
        lambda **_kwargs: MagicMock(),
    )
    monkeypatch.setattr(
        "services.process_runtime.adrive_convergence_session_to_pause_or_terminal",
        _fake_adrive,
    )

    result = await delegate_process_runtime(requirement_text="登录超时", include_repos=[repo_id])

    assert result.status == "completed"
    assert result.model_usage["total_tokens"] == 200
    assert result.model_usage["prompt_tokens"] == 120
    assert result.model_usage["completion_tokens"] == 80


@pytest.mark.asyncio
async def test_delegate_guards_unexpected_exception_as_failed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """IN-03：start_orchestration 等抛穿被外层护栏映射为 failed 终态（不回退 5xx）。"""
    from mcp_tools.orchestration_delegate import delegate_process_runtime

    async def _boom(*_args: Any, **_kwargs: Any) -> Any:
        raise RuntimeError("orchestration backend down")

    monkeypatch.setattr("services.process_runtime.start_orchestration", _boom)
    monkeypatch.setattr(
        "services.process_runtime.build_orchestration_engine",
        lambda **_kwargs: MagicMock(),
    )

    result = await delegate_process_runtime(requirement_text="登录超时")

    assert result.status == "failed"
    assert result.content == {}
    assert result.plan_version_id is None
    assert result.markdown == ""
    # session 未建 → 占位 SimpleNamespace(id="")，调用方 str(.id) 安全。
    assert str(result.session.id) == ""


# ===================== Task 2: create_feishu_technical_plan delegate 接线 =====================


def _fake_delegate_result(*, status: str, repo_id: str, repo_name: str) -> Any:
    """构造 DelegateResult（view/service 级测试用，不触发真实编排）。"""
    from mcp_tools.orchestration_delegate import DelegateResult

    if status == "completed":
        content = _merged_content(repo_id, repo_name)
        content["execution_plan"][0]["files"] = [
            {"path": "src/auth/session.py", "action": "modify"}
        ]
        return DelegateResult(
            session=SimpleNamespace(id=uuid.uuid4()),
            status="completed",
            content=content,
            plan_version_id=str(uuid.uuid4()),
            markdown="**登录超时修复跨仓方案**\n\n在 auth 仓修复 token 刷新边界。",
        )
    return DelegateResult(
        session=SimpleNamespace(id=uuid.uuid4()),
        status=status,
        content={},
        plan_version_id=None,
        markdown="",
    )


def _make_context(project) -> McpWorkItemContext:
    run = create_interaction_run(token_fingerprint=hash_token("delegate-context"), source="mcp")
    return McpWorkItemContext.objects.create(
        run=run,
        space=project,
        feishu_project_key=project.feishu_project_key,
        work_item_type="bug",
        work_item_id=77,
        name="登录超时 Bug",
        status=McpWorkItemContext.Status.COMPLETED,
        work_item_status="doing",
        description="登录超过 30 秒后 token 过期。",
    )


def test_create_feishu_technical_plan_response_shape_and_persistence(
    mcp_client: tuple[APIClient, str],
    project,
    indexed_repository,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """响应外形 snapshot（旧键全在 + session_id）+ delegate 被调 + 落库兼容。"""
    client, _plaintext = mcp_client
    context = _make_context(project)
    captured: dict[str, Any] = {}

    async def _fake_delegate(**kwargs: Any) -> Any:
        captured.update(kwargs)
        return _fake_delegate_result(
            status="completed",
            repo_id=str(indexed_repository.id),
            repo_name=indexed_repository.name,
        )

    monkeypatch.setattr(
        "mcp_tools.technical_plan_service.delegate_process_runtime", _fake_delegate
    )

    response = client.post(
        "/api/mcp/tools/create_feishu_technical_plan/",
        {
            "context_id": str(context.id),
            "repository_ids": [str(indexed_repository.id)],
            "create_document": False,
            "write_comment": False,
        },
        format="json",
    )

    assert response.status_code == 200
    body = response.json()
    # 响应键集合不缩减（旧键全在）+ 新增可选 session_id（T-94-03-COMPAT）。
    assert _LEGACY_OUTPUT_KEYS <= set(body.keys())
    assert "session_id" in body
    assert body["status"] == "completed"
    # delegate 被调（走统一编排，不再走 _build_repo_task_matrix——该 seam 已移除）。
    import mcp_tools.technical_plan_service as svc

    assert not hasattr(svc, "_build_repo_task_matrix")
    assert captured["requirement_text"]
    assert captured["include_repos"] == [str(indexed_repository.id)]
    # canonical execution_plan → 旧矩阵形态映射（显式白名单字段）。
    task = body["repository_tasks"][0]
    assert task["repository_id"] == str(indexed_repository.id)
    assert task["repository_name"] == indexed_repository.name
    assert task["planned_branch"] == "feature"
    assert "src/auth/session.py" in task["candidate_files"]
    assert task["coding_instruction"]
    # WR-01：下游 _coding_plan_body 读取的方案细节键非空映射（steps/test_strategy/risks/rollback）。
    assert task["steps"]
    assert task["test_strategy"]
    assert task["risks"]
    assert task["rollback"]
    # IN-02：canonical base_branch 透传（下游不再静默回退仓库默认分支）。
    assert task["base_branch"] == "release/2026.06"
    # WR-02：plan 恢复旧外形（repository_task_matrix/work_item/summary 等），canonical 入 canonical_content。
    assert _LEGACY_PLAN_KEYS <= set(body["plan"].keys())
    assert body["plan"]["repository_task_matrix"][0]["repository_id"] == str(indexed_repository.id)
    assert body["plan"]["work_item"]["work_item_id"] == 77
    assert body["plan"]["summary"]
    assert body["plan"]["canonical_content"]["execution_plan"][0]["repository_id"] == str(
        indexed_repository.id
    )
    assert "登录超时修复跨仓方案" in body["markdown"]

    # McpWorkItemTechnicalPlan 继续落库（plan_body=旧外形映射 WR-02 / markdown / status）。
    artifact = McpWorkItemTechnicalPlan.objects.get(id=body["technical_plan_id"])
    assert artifact.status == McpWorkItemTechnicalPlan.Status.COMPLETED
    assert _LEGACY_PLAN_KEYS <= set(artifact.plan_body.keys())
    assert artifact.plan_body["title"] == "登录超时修复跨仓方案"
    assert artifact.plan_body["repository_task_matrix"][0]["repository_id"] == str(
        indexed_repository.id
    )
    assert artifact.markdown == body["markdown"]
    assert artifact.repository_tasks[0]["repository_id"] == str(indexed_repository.id)


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_build_work_item_technical_plan_missing_actor_degrades(
    project,
    indexed_repository,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """缺 actor（None）降级：delegate 收 created_by=None，不崩，正常落 artifact（V4 文档化降级）。"""
    from asgiref.sync import sync_to_async

    from mcp_tools.technical_plan_service import build_work_item_technical_plan

    def _setup() -> Any:
        run = create_interaction_run(
            token_fingerprint=hash_token("delegate-actor-none"), source="mcp"
        )
        context = _make_context(project)
        return run, context

    run, context = await sync_to_async(_setup)()
    captured: dict[str, Any] = {}

    async def _fake_delegate(**kwargs: Any) -> Any:
        captured.update(kwargs)
        return _fake_delegate_result(
            status="completed",
            repo_id=str(indexed_repository.id),
            repo_name=indexed_repository.name,
        )

    async def _noop_ingest(_request: Any) -> None:
        return None

    monkeypatch.setattr(
        "mcp_tools.technical_plan_service.delegate_process_runtime", _fake_delegate
    )
    # 避免真实后台 ingestion 线程与测试连接竞争（sqlite table locked）。
    monkeypatch.setattr("knowledge.ingestion.aschedule_ingestion", _noop_ingest)

    result = await build_work_item_technical_plan(
        run=run,
        context_id=str(context.id),
        repository_ids=[str(indexed_repository.id)],
        repo_hints=[],
        context_chunks=[],
        similar_cases=[{"case_id": "c1", "title": "先例", "outcome": "merged"}],
        title="",
        folder_token="",
        create_document=False,
        write_comment=False,
        actor=None,
    )

    # actor=None 透传 delegate（召回 stage fail-closed 空召回，不崩）。
    assert "created_by" in captured
    assert captured["created_by"] is None
    assert result.output["status"] == McpWorkItemTechnicalPlan.Status.COMPLETED
    assert result.output["session_id"]


def test_create_feishu_technical_plan_partial_when_orchestration_suspended(
    mcp_client: tuple[APIClient, str],
    project,
    indexed_repository,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """编排挂起（RESEARCHING）→ status=partial + session_id + retry_state retryable（调用方续推契约）。"""
    client, _plaintext = mcp_client
    context = _make_context(project)

    async def _fake_delegate(**_kwargs: Any) -> Any:
        return _fake_delegate_result(
            status="partial",
            repo_id=str(indexed_repository.id),
            repo_name=indexed_repository.name,
        )

    monkeypatch.setattr(
        "mcp_tools.technical_plan_service.delegate_process_runtime", _fake_delegate
    )

    response = client.post(
        "/api/mcp/tools/create_feishu_technical_plan/",
        {
            "context_id": str(context.id),
            "repository_ids": [str(indexed_repository.id)],
            "create_document": False,
            "write_comment": False,
        },
        format="json",
    )

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "partial"
    assert body["session_id"]
    assert body["retry_state"]["retryable"] is True
    assert body["retry_state"]["failed_stage"] == "orchestration_pending"


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_mcp_sync_research_reaches_done_via_real_delegate(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """WARNING 2 契约：真实 delegate 路径（真实 start_orchestration + build_orchestration_engine(
    skip_clarification=True) + adrive）在**空 node_execution_id**（MCP 入口形态、无工作流节点
    barrier）下，research 同步解析（stub research/merge adapter，不触发容器 fan-out）能同步达
    DONE → delegate 终态 status="completed" + 取到 canonical content + 非空 markdown。

    **调用方契约（文档化）**：当 RESEARCHING 真在途（容器未就绪、MCP 无 resume 通路）时，delegate
    默认返回 status="partial" + session_id，调用方须容忍 PARTIAL 并经会话/工作流续推。本用例证实
    「research 可同步完成」时的同步友好路径真实可达（非仅 monkeypatch adrive 的单测）。
    """
    from services.process_runtime.architect_merge_adapter import (
        ArchitectMergeAdapter as RealMergeAdapter,
    )

    repo_id = str(uuid.uuid4())
    merged = _merged_content(repo_id, "auth-service")

    class _FakeRouter:
        async def route(self, _session: Any) -> dict:
            return {"candidates": [{"repo_id": repo_id, "confidence": "high"}]}

    class _FakeRecall:
        async def recall(self, _session: Any) -> dict:
            return {"hits": [], "query": "", "kinds": []}

    class _FakeResearch:
        def __init__(self, **_kwargs: Any) -> None:
            # 同步解析：dispatch 不建 RepoResearchTask（无在途）→ research barrier 立即终态，
            # 不触发容器 fan-out（模拟「research 可同步完成」）。
            pass

        async def dispatch(self, _session: Any) -> None:
            return None

    class _FakeSynth:
        async def synthesize(self, _session: Any, _partials: list[dict]) -> dict:
            return merged

    async def _noop_spec(_version_id: Any) -> None:
        return None

    def _merge_factory() -> RealMergeAdapter:
        return RealMergeAdapter(synthesizer=_FakeSynth(), spec_generation_hook=_noop_spec)

    # 仅 stub router/recall/research/merge adapter（IO 边界）；ClarifyAdapter + build_orchestration_engine
    # + adrive + start_orchestration 全走真实路径（空 node_execution_id 由 build 默认注入）。
    monkeypatch.setattr("services.process_runtime.RepoRouterV2Adapter", lambda: _FakeRouter())
    monkeypatch.setattr(
        "services.process_runtime.DeliveryKnowledgeRecallAdapter", lambda: _FakeRecall()
    )
    monkeypatch.setattr("services.process_runtime.ResearchDispatchAdapter", _FakeResearch)
    monkeypatch.setattr(
        "services.process_runtime.ArchitectMergeAdapter", lambda: _merge_factory()
    )

    from mcp_tools.orchestration_delegate import delegate_process_runtime

    result = await delegate_process_runtime(
        requirement_text="为 auth 仓修复登录超时", include_repos=[repo_id]
    )

    assert result.status == "completed"
    assert result.plan_version_id
    assert result.content["title"] == "登录超时修复跨仓方案"
    assert result.markdown
    # 底层 session 确达 DONE（canonical 已落 current_plan_version）。
    refreshed = await ConvergenceSession.objects.aget(id=result.session.id)
    assert refreshed.status == ConvergenceSessionStatus.DONE
    assert refreshed.current_artifact_version_id is not None
