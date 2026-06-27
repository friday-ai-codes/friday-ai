"""create_feishu_technical_plan delegate 守护测试（Phase 94 UNIFY-03）。

覆盖：
- Task 1：``delegate_plan_orchestration`` 三态映射（DONE→completed / RESEARCHING→partial /
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
from typing import Any
from unittest.mock import MagicMock

import pytest

from delivery.models import (
    PlanSession,
    PlanSessionEntrypoint,
    PlanSessionStatus,
    PlanVersion,
    TechnicalPlan,
    TechnicalPlanOrigin,
)

pytestmark = pytest.mark.django_db


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
            }
        ],
    }


async def _make_plan_version(content: dict) -> PlanVersion:
    plan = await TechnicalPlan.objects.acreate(origin=TechnicalPlanOrigin.ORCHESTRATION)
    version = await PlanVersion.objects.acreate(plan=plan, version=1, content=content)
    await TechnicalPlan.objects.filter(id=plan.id).aupdate(current_version=version)
    return version


async def _make_session(status: str, *, plan_version_id: Any = None) -> PlanSession:
    return await PlanSession.objects.acreate(
        entrypoint=PlanSessionEntrypoint.WORKFLOW,
        status=status,
        decomposition={"requirement_text": "登录超时", "include_repos": []},
        current_plan_version=plan_version_id,
    )


def _patch_delegate_pipeline(monkeypatch: pytest.MonkeyPatch, *, session: PlanSession) -> None:
    """monkeypatch delegate 调用的共享 helper（start/build/adrive）使其返回指定 session。"""

    async def _fake_start(*_args: Any, **_kwargs: Any) -> PlanSession:
        return session

    async def _fake_adrive(_engine: Any, _session: Any, **_kwargs: Any) -> PlanSession:
        return session

    monkeypatch.setattr("services.plan_orchestration.start_orchestration", _fake_start)
    monkeypatch.setattr(
        "services.plan_orchestration.build_orchestration_engine",
        lambda **_kwargs: MagicMock(),
    )
    monkeypatch.setattr(
        "services.plan_orchestration.adrive_plan_session_to_pause_or_terminal",
        _fake_adrive,
    )


# ============================== Task 1: delegate 三态映射 ==============================


@pytest.mark.asyncio
async def test_delegate_done_maps_completed_with_canonical_and_markdown(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from mcp_tools.orchestration_delegate import delegate_plan_orchestration

    repo_id = str(uuid.uuid4())
    version = await _make_plan_version(_merged_content(repo_id, "auth-service"))
    session = await _make_session(PlanSessionStatus.DONE, plan_version_id=version.id)
    _patch_delegate_pipeline(monkeypatch, session=session)

    result = await delegate_plan_orchestration(requirement_text="登录超时", include_repos=[repo_id])

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
    from mcp_tools.orchestration_delegate import delegate_plan_orchestration

    session = await _make_session(PlanSessionStatus.RESEARCHING)
    _patch_delegate_pipeline(monkeypatch, session=session)

    result = await delegate_plan_orchestration(requirement_text="登录超时")

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
    from mcp_tools.orchestration_delegate import delegate_plan_orchestration

    session = await _make_session(PlanSessionStatus.FAILED)
    _patch_delegate_pipeline(monkeypatch, session=session)

    result = await delegate_plan_orchestration(requirement_text="登录超时")

    assert result.status == "failed"
    assert result.content == {}
    assert result.plan_version_id is None
    assert result.markdown == ""
