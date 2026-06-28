"""PlanDeepenService 守护测试（Phase 89，PLAN-01，89-01）。

覆盖：
- ``get_verified_associations`` 被调，且 ``include_repos`` 透传给 ``start_orchestration``。
- 引擎工厂复用：``build_orchestration_engine`` 被调（无第二 engine 工厂）+
  ``adrive_convergence_session_to_pause_or_terminal`` 续驱。
- 终态 DONE → ``ProjectDocService.append_research_note`` 被调（RESEARCH 镜像）。
- 非 DONE（clarifying）→ 不镜像。
- 三新 call_source（plan_deepen/plan_revision/branch_naming）normalize 命中。

纯 seam mock（patch repo_association / process_runtime helpers / ProjectDocService），
不落库。
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from agents.call_source import CallSource
from initiatives.services.plan_deepen_service import PlanDeepenService

_SVC_MOD = "initiatives.services.plan_deepen_service"
_RA_MOD = "initiatives.services.repo_association_service"
_PO_MOD = "services.process_runtime"
_DOC_MOD = "initiatives.services.project_doc_service"

_VERIFIED = [
    {"repository_id": "r1", "repo_name": "repo-a", "verdict": {}, "score": 0.9},
    {"repository_id": "r2", "repo_name": "repo-b", "verdict": {}, "score": 0.8},
]


def _fake_session(status: str) -> SimpleNamespace:
    return SimpleNamespace(id="sess-1", status=status, current_plan_version="ver-1")


def _patches(
    *,
    verified: list[dict],
    final_status: str,
    start_capture: dict,
    doc_mock: MagicMock,
):
    ra_instance = MagicMock()
    ra_instance.get_verified_associations = AsyncMock(return_value=verified)

    async def _start(entrypoint, requirement_text, *, work_item=None, include_repos=None, **kw):
        start_capture["entrypoint"] = entrypoint
        start_capture["include_repos"] = include_repos
        return _fake_session("decomposing")

    engine_factory = MagicMock(return_value=SimpleNamespace(name="engine"))
    adrive = AsyncMock(return_value=_fake_session(final_status))

    return (
        patch(f"{_RA_MOD}.RepoAssociationService", return_value=ra_instance),
        patch(f"{_PO_MOD}.start_orchestration", new=AsyncMock(side_effect=_start)),
        patch(f"{_PO_MOD}.build_orchestration_engine", new=engine_factory),
        patch(f"{_PO_MOD}.adrive_convergence_session_to_pause_or_terminal", new=adrive),
        patch(f"{_DOC_MOD}.ProjectDocService", return_value=doc_mock),
        engine_factory,
        adrive,
        ra_instance,
    )


@pytest.mark.asyncio
async def test_deepen_consumes_verified_and_reuses_engine() -> None:
    project = SimpleNamespace(id="p1")
    start_capture: dict = {}
    doc_mock = MagicMock()
    doc_mock.append_research_note = AsyncMock(return_value={"applied": True})

    (p_ra, p_start, p_engine, p_adrive, p_doc, engine_factory, adrive, ra_instance) = _patches(
        verified=_VERIFIED, final_status="done", start_capture=start_capture, doc_mock=doc_mock
    )

    with p_ra, p_start, p_engine, p_adrive, p_doc, patch.object(
        PlanDeepenService, "_aget_current_plan_content", new=AsyncMock(return_value={})
    ), patch.object(PlanDeepenService, "_acollect_partials", new=AsyncMock(return_value=[])):
        session = await PlanDeepenService().deepen(
            project=project,
            requirement_text="把登录接口改成 JWT",
            node_execution_id="ne-1",
            initiated_by_user_id="system",
        )

    # 消费 88 verified → include_repos 透传
    ra_instance.get_verified_associations.assert_awaited_once()
    assert start_capture["include_repos"] == ["r1", "r2"]
    assert start_capture["entrypoint"] == "workflow"
    # 引擎工厂复用（同一 build_orchestration_engine）+ 续驱
    engine_factory.assert_called_once_with(node_execution_id="ne-1")
    adrive.assert_awaited_once()
    # 终态 DONE → 镜像 RESEARCH
    doc_mock.append_research_note.assert_awaited_once()
    assert session.status == "done"


@pytest.mark.asyncio
async def test_deepen_non_done_does_not_mirror() -> None:
    project = SimpleNamespace(id="p1")
    start_capture: dict = {}
    doc_mock = MagicMock()
    doc_mock.append_research_note = AsyncMock(return_value={"applied": True})

    (p_ra, p_start, p_engine, p_adrive, p_doc, engine_factory, adrive, ra_instance) = _patches(
        verified=_VERIFIED, final_status="clarifying", start_capture=start_capture, doc_mock=doc_mock
    )

    with p_ra, p_start, p_engine, p_adrive, p_doc:
        session = await PlanDeepenService().deepen(
            project=project,
            requirement_text="需求",
            initiated_by_user_id="system",
        )

    assert session.status == "clarifying"
    doc_mock.append_research_note.assert_not_awaited()


@pytest.mark.asyncio
async def test_deepen_no_verified_still_runs() -> None:
    """无 verified 仓 → include_repos=[]，仍可走自然语言需求（引擎自路由），不抛。"""
    project = SimpleNamespace(id="p1")
    start_capture: dict = {}
    doc_mock = MagicMock()
    doc_mock.append_research_note = AsyncMock(return_value={"applied": True})

    (p_ra, p_start, p_engine, p_adrive, p_doc, engine_factory, adrive, ra_instance) = _patches(
        verified=[], final_status="failed", start_capture=start_capture, doc_mock=doc_mock
    )

    with p_ra, p_start, p_engine, p_adrive, p_doc:
        session = await PlanDeepenService().deepen(
            project=project, requirement_text="需求", initiated_by_user_id="system"
        )

    assert start_capture["include_repos"] == []
    assert session.status == "failed"
    doc_mock.append_research_note.assert_not_awaited()


def test_new_call_sources_normalize() -> None:
    assert CallSource.normalize("plan_deepen") == "plan_deepen"
    assert CallSource.normalize("plan_revision") == "plan_revision"
    assert CallSource.normalize("branch_naming") == "branch_naming"
    assert CallSource.PLAN_DEEPEN.value == "plan_deepen"
    assert CallSource.PLAN_REVISION.value == "plan_revision"
    assert CallSource.BRANCH_NAMING.value == "branch_naming"


def test_render_plan_markdown_seven_elements() -> None:
    """per-repo 七要素 + overall 渲染：含七要素标签 + overall 段。"""
    overall = {
        "title": "JWT 化登录",
        "summary": "把会话改成 JWT",
        "overall_plan": "先改鉴权仓，再改网关仓",
        "cross_repo_context": "鉴权仓被网关仓依赖",
    }
    partials = [
        {
            "repository_id": "r1",
            "responsibilities": ["签发 JWT"],
            "proposed_changes": ["新增 token 服务"],
            "impacted_modules": ["auth"],
            "estimated_tests": ["e2e 登录", "单测 token"],
            "risks": ["旧 session 兼容"],
            "unclear_features": ["刷新策略未定"],
            "conflicts_with_existing": ["与 cookie 鉴权冲突"],
        }
    ]
    md = PlanDeepenService._render_plan_markdown(overall, partials)
    for label in (
        "负责事项",
        "代码预改动",
        "影响业务模块",
        "预计 e2e·单测 + 覆盖项",
        "风险",
        "feature list 不清处",
        "与现功能冲突",
    ):
        assert label in md
    assert "整体方案" in md
    assert "跨仓上下文" in md
