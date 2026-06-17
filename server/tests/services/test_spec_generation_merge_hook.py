"""全链路 merge hook 守护测试（Phase 49-04 Task 2，D-49-5/7）。

复用 test_architect_merge_adapter 的 session+partial 直建范式 + mock MergedPlanSynthesizer
（返回引用真实 SDD 仓 UUID 的 valid MergedPlan）。执行 ``adapter.merge(session)`` 走真实
pass 分支落 canonical PlanVersion，验证 spec 挂接：

- SDD 仓全链路产 spec（SddSpec(draft) + Document(sdd_spec) + DocumentVersion + 关联 + emit）。
- 非 SDD 仓零回归（merge 仍 passed，SddSpec 0）。
- spec 合成异常 fail-soft（merge 仍 passed，warning 不冒泡）。
- 幂等（同 plan_version_id 连调 hook 两次不翻倍）。
- 注入 stub hook 记录被调用的 plan_version_id == canonical PlanVersion id。

异步 + sync_to_async 跨线程写库 → transaction=True。
"""

from __future__ import annotations

import uuid
from typing import Any
from unittest.mock import AsyncMock

import pytest
from asgiref.sync import sync_to_async

from delivery.models import (
    Document,
    DocumentType,
    PlanSession,
    PlanSessionEntrypoint,
    PlanSessionEvent,
    PlanSessionStatus,
    RepoResearchTask,
    RepoResearchTaskStatus,
    SddSpec,
    SddSpecStatus,
)
from repositories.models import Repository
from services.plan_orchestration import ArchitectMergeAdapter, agenerate_specs_for_plan

pytestmark = pytest.mark.django_db(transaction=True)


def _make_repo(*, sdd: bool) -> Repository:
    return Repository.objects.create(
        name=f"repo-{uuid.uuid4().hex[:6]}",
        git_url=f"https://github.com/test/{uuid.uuid4().hex[:6]}.git",
        git_platform="github",
        default_branch="main",
        index_status="indexed",
        facets={"methodology": "SDD"} if sdd else {},
    )


def _valid_merged_plan_for_repo(repo_id: str) -> dict[str, Any]:
    """单仓 valid MergedPlan，execution_plan repository_id 指向真实仓 UUID。"""
    return {
        "title": "单仓改造",
        "summary": "对目标仓做改造",
        "api_contracts": [],
        "dependency_dag": {repo_id: []},
        "data_migrations": [],
        "compat_risks": [],
        "release_order": [repo_id],
        "rollback_plan": {repo_id: "回滚步骤"},
        "execution_plan": [
            {
                "id": "t-0",
                "name": "改造任务",
                "repository_id": repo_id,
                "repository_name": "target-repo",
                "branch_strategy": "feature",
                "coding_instruction": "实现需求",
                "dependencies": [],
            }
        ],
    }


def _make_session_with_partial() -> PlanSession:
    session = PlanSession.objects.create(
        entrypoint=PlanSessionEntrypoint.CHAT,
        status=PlanSessionStatus.MERGING,
        work_item=None,
        decomposition={"requirement_text": "做个登录"},
    )
    repo = _make_repo(sdd=False)
    task = RepoResearchTask.objects.create(
        session=session, repository=repo, status=RepoResearchTaskStatus.DONE
    )
    from delivery.models import PartialPlan

    PartialPlan.objects.create(
        research_task=task,
        content={"repository_id": "x", "research_summary": "y"},
        valid=True,
    )
    return session


@sync_to_async
def _amake_repo(*, sdd: bool) -> Repository:
    return _make_repo(sdd=sdd)


@sync_to_async
def _amake_session_with_partial() -> PlanSession:
    return _make_session_with_partial()


def _merge_synth(merged: dict) -> AsyncMock:
    synth = AsyncMock()
    synth.synthesize = AsyncMock(return_value=merged)
    return synth


def _spec_synth(return_value: str = "## Why\nspec\n", side_effect=None) -> AsyncMock:
    synth = AsyncMock()
    synth.synthesize = AsyncMock(return_value=return_value, side_effect=side_effect)
    return synth


def _hook_with_spec_synth(spec_synth: Any):
    """真实 agenerate_specs_for_plan + 注入 mock SddSpecSynthesizer（绕开真 LLM）。"""

    async def _hook(plan_version_id):
        return await agenerate_specs_for_plan(plan_version_id, synthesizer=spec_synth)

    return _hook


async def test_sdd_repo_full_chain_produces_spec() -> None:
    """SDD 仓融合通过 → merge passed + 全链路产 SddSpec(draft) + Document(sdd_spec) + emit。"""
    repo = await _amake_repo(sdd=True)
    session = await _amake_session_with_partial()
    merged = _valid_merged_plan_for_repo(str(repo.id))
    adapter = ArchitectMergeAdapter(
        synthesizer=_merge_synth(merged),
        spec_generation_hook=_hook_with_spec_synth(_spec_synth()),
    )

    result = await adapter.merge(session)

    assert result["validation_status"] == "passed"
    assert await SddSpec.objects.acount() == 1
    spec = await SddSpec.objects.afirst()
    assert spec.status == SddSpecStatus.DRAFT
    assert spec.repository_id == repo.id
    assert str(spec.plan_version_id) == result["plan_version_id"]
    doc = await Document.objects.aget(pk=spec.document_id)
    assert doc.document_type == DocumentType.SDD_SPEC
    ev = await PlanSessionEvent.objects.filter(
        session_id=session.id, event="spec.drafted"
    ).afirst()
    assert ev is not None
    assert ev.payload["spec_id"] == str(spec.id)


async def test_non_sdd_repo_no_regression() -> None:
    """非 SDD 仓 → merge 仍 passed，SddSpec 计数 0（零回归）。"""
    repo = await _amake_repo(sdd=False)
    session = await _amake_session_with_partial()
    merged = _valid_merged_plan_for_repo(str(repo.id))
    adapter = ArchitectMergeAdapter(
        synthesizer=_merge_synth(merged),
        spec_generation_hook=_hook_with_spec_synth(_spec_synth()),
    )

    result = await adapter.merge(session)

    assert result["validation_status"] == "passed"
    assert await SddSpec.objects.acount() == 0
    reloaded = await PlanSession.objects.aget(id=session.id)
    assert reloaded.current_plan_version is not None


async def test_no_matching_repo_no_spec() -> None:
    """execution_plan repo 无匹配 Repository → merge passed，spec 0。"""
    session = await _amake_session_with_partial()
    merged = _valid_merged_plan_for_repo(str(uuid.uuid4()))
    adapter = ArchitectMergeAdapter(
        synthesizer=_merge_synth(merged),
        spec_generation_hook=_hook_with_spec_synth(_spec_synth()),
    )

    result = await adapter.merge(session)

    assert result["validation_status"] == "passed"
    assert await SddSpec.objects.acount() == 0


async def test_spec_synthesis_failure_fail_soft() -> None:
    """spec 合成异常 → merge 仍 passed（warning 不冒泡）；canonical/指针不受影响。"""
    repo = await _amake_repo(sdd=True)
    session = await _amake_session_with_partial()
    merged = _valid_merged_plan_for_repo(str(repo.id))
    adapter = ArchitectMergeAdapter(
        synthesizer=_merge_synth(merged),
        spec_generation_hook=_hook_with_spec_synth(
            _spec_synth(side_effect=RuntimeError("llm down"))
        ),
    )

    result = await adapter.merge(session)

    assert result["validation_status"] == "passed"
    # hook 内逐仓 try/except 吞错 → spec 0，但 merge 不受影响
    assert await SddSpec.objects.acount() == 0
    reloaded = await PlanSession.objects.aget(id=session.id)
    assert reloaded.current_plan_version is not None


async def test_hook_total_failure_fail_soft() -> None:
    """hook 整体抛错（非逐仓）→ _handle_pass 外层 try/except 吞为 warning，merge 仍 passed。"""
    repo = await _amake_repo(sdd=True)
    session = await _amake_session_with_partial()
    merged = _valid_merged_plan_for_repo(str(repo.id))

    async def _boom(plan_version_id):
        raise RuntimeError("hook import/parse boom")

    adapter = ArchitectMergeAdapter(
        synthesizer=_merge_synth(merged), spec_generation_hook=_boom
    )

    result = await adapter.merge(session)

    assert result["validation_status"] == "passed"
    reloaded = await PlanSession.objects.aget(id=session.id)
    assert reloaded.current_plan_version is not None


async def test_stub_hook_receives_canonical_plan_version_id() -> None:
    """注入 stub hook → 被调用一次，plan_version_id == canonical PlanVersion id。"""
    repo = await _amake_repo(sdd=True)
    session = await _amake_session_with_partial()
    merged = _valid_merged_plan_for_repo(str(repo.id))
    stub = AsyncMock(return_value=[])
    adapter = ArchitectMergeAdapter(
        synthesizer=_merge_synth(merged), spec_generation_hook=stub
    )

    result = await adapter.merge(session)

    assert result["validation_status"] == "passed"
    stub.assert_awaited_once()
    called_pv = stub.await_args.args[0]
    assert str(called_pv) == result["plan_version_id"]


async def test_idempotent_hook_rerun_no_duplicate() -> None:
    """同 plan_version_id 连调 hook 两次 → SddSpec 不翻倍、Document/Version 不新增。"""
    repo = await _amake_repo(sdd=True)
    session = await _amake_session_with_partial()
    merged = _valid_merged_plan_for_repo(str(repo.id))
    adapter = ArchitectMergeAdapter(
        synthesizer=_merge_synth(merged),
        spec_generation_hook=_hook_with_spec_synth(_spec_synth()),
    )

    result = await adapter.merge(session)
    pv_id = result["plan_version_id"]
    # 再对同一 canonical plan_version_id 连调一次 hook
    await agenerate_specs_for_plan(pv_id, synthesizer=_spec_synth())

    assert await SddSpec.objects.acount() == 1
    assert await Document.objects.filter(document_type=DocumentType.SDD_SPEC).acount() == 1
    spec = await SddSpec.objects.afirst()
    assert await Document.objects.filter(pk=spec.document_id).acount() == 1
