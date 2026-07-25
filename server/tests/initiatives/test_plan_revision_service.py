"""PlanDeepenService 方案修订回路守护测试（Phase 89，PLAN-02，89-02）。

覆盖（纯 seam mock，无 DB/网络）：
- ``detect_revision``：经 ``use_call_source(CallSource.PLAN_REVISION)`` LLM（ainvoke 内
  ``get_call_source`` 命中 plan_revision）+ ``arecord_llm_usage`` 被调；产物归一化为受控结构；
  空观测 / LLM 抛错 → 空结构（best-effort 不反噬）。
- ``apply_supplement_revision``：经 ``ArtifactService.add_version`` 加版本（无旁路写
  ArtifactVersion）；delta 为空 → content 不变（content_hash 相等 service 幂等不翻版本）；
  delta 非空 → summary 折入 delta（翻版本）。
- 关联同步：add → ``confirm_repos``、remove → ``reopen_candidates``、change →
  ``dispatch_verify`` 分别经 ``RepoAssociationService`` 被调（INV-6 写收口）。
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from agents.call_source import CallSource
from initiatives.services.plan_deepen_service import PlanDeepenService

_SVC_MOD = "initiatives.services.plan_deepen_service"
_RA_MOD = "initiatives.services.repo_association_service"

_BASE_CONTENT = {
    "title": "JWT 化登录",
    "summary": "把会话改成 JWT",
    "execution_plan": [
        {
            "id": "t0",
            "name": "auth",
            "repository_id": "r1",
            "repository_name": "auth-repo",
            "branch_strategy": "feature",
        }
    ],
}


# ---------------------------------------------------------------------------
# detect_revision
# ---------------------------------------------------------------------------


class _FakeModel:
    def __init__(self, captured: dict, content: str) -> None:
        self._captured = captured
        self._content = content

    async def ainvoke(self, messages):  # noqa: ANN001
        from agents.call_source import get_call_source

        self._captured["call_source"] = get_call_source()
        return SimpleNamespace(content=self._content)


@pytest.mark.asyncio
async def test_detect_revision_uses_call_source_and_records_usage() -> None:
    captured: dict = {}
    resolved = SimpleNamespace(extra={"default_model": "m1"}, provider_type="anthropic")
    fake_model = _FakeModel(
        captured,
        '{"add_repos":["r3"],"remove_repos":["r2"],"change_repos":["r1"],'
        '"plan_delta_summary":"新增缓存仓"}',
    )
    usage = AsyncMock()

    with (
        patch(
            "services.provider_config.ProviderConfigService.aresolve",
            new=AsyncMock(return_value=resolved),
        ),
        patch("agents.llm_factory.build_chat_model", return_value=fake_model),
        patch("interactions.ledger.arecord_llm_usage", new=usage),
    ):
        result = await PlanDeepenService().detect_revision(
            observed_change_text="发现还要改缓存仓", initiated_by_user_id="42"
        )

    # ainvoke 期间 call_source 命中 plan_revision（use_call_source 作用域断言）
    assert captured["call_source"] == CallSource.PLAN_REVISION.value
    # arecord_llm_usage 被调（plan_revision 留痕）
    usage.assert_awaited_once()
    assert usage.await_args.kwargs["call_source"] == CallSource.PLAN_REVISION.value
    # 产物归一化
    assert result["add_repos"] == ["r3"]
    assert result["remove_repos"] == ["r2"]
    assert result["change_repos"] == ["r1"]
    assert result["plan_delta_summary"] == "新增缓存仓"


@pytest.mark.asyncio
async def test_detect_revision_empty_text_returns_empty() -> None:
    result = await PlanDeepenService().detect_revision(observed_change_text="   ")
    assert result == {
        "add_repos": [],
        "remove_repos": [],
        "change_repos": [],
        "plan_delta_summary": "",
    }


@pytest.mark.asyncio
async def test_detect_revision_llm_failure_is_failsoft() -> None:
    with patch(
        "services.provider_config.ProviderConfigService.aresolve",
        new=AsyncMock(side_effect=RuntimeError("boom")),
    ):
        result = await PlanDeepenService().detect_revision(
            observed_change_text="要改仓", initiated_by_user_id="system"
        )
    # LLM/provider 失败 → 空结构（best-effort 不抛）
    assert result["add_repos"] == []
    assert result["plan_delta_summary"] == ""


# ---------------------------------------------------------------------------
# apply_supplement_revision —— ArtifactVersion.supersedes（经 ArtifactService）
# ---------------------------------------------------------------------------


def _plan_service_mock(captured: dict) -> MagicMock:
    svc = MagicMock()

    async def _add_version(plan, content):  # noqa: ANN001
        captured["content"] = content
        return SimpleNamespace(id="nv", version=2)

    svc.add_version = AsyncMock(side_effect=_add_version)
    return svc


@pytest.mark.asyncio
async def test_apply_supplement_revision_adds_version_via_service() -> None:
    captured: dict = {}
    plan = SimpleNamespace(id="p1", current_version_id="v1")
    revision = {"add_repos": [], "remove_repos": [], "change_repos": [], "plan_delta_summary": "加缓存"}
    plan_svc = _plan_service_mock(captured)

    with (
        patch(f"{_SVC_MOD}.PlanDeepenService._aget_plan_content", new=AsyncMock(return_value=dict(_BASE_CONTENT))),
        patch("delivery.services.ArtifactService", return_value=plan_svc),
        patch(f"{_SVC_MOD}.PlanDeepenService._sync_repo_associations", new=AsyncMock()),
    ):
        version = await PlanDeepenService().apply_supplement_revision(
            plan=plan, revision=revision, project=None, initiated_by_user_id="42"
        )

    plan_svc.add_version.assert_awaited_once()
    # 经 ArtifactService 加版本（无旁路写 ArtifactVersion）；delta 折入 summary（翻版本）
    assert "加缓存" in captured["content"]["summary"]
    assert version.version == 2


@pytest.mark.asyncio
async def test_apply_supplement_revision_empty_delta_is_idempotent_content() -> None:
    """delta 为空 → content 不变（content_hash 相等，service 幂等不翻版本）。"""
    captured: dict = {}
    plan = SimpleNamespace(id="p1", current_version_id="v1")
    revision = {"add_repos": [], "remove_repos": [], "change_repos": [], "plan_delta_summary": ""}
    plan_svc = _plan_service_mock(captured)

    with (
        patch(f"{_SVC_MOD}.PlanDeepenService._aget_plan_content", new=AsyncMock(return_value=dict(_BASE_CONTENT))),
        patch("delivery.services.ArtifactService", return_value=plan_svc),
        patch(f"{_SVC_MOD}.PlanDeepenService._sync_repo_associations", new=AsyncMock()),
    ):
        await PlanDeepenService().apply_supplement_revision(
            plan=plan, revision=revision, project=None
        )

    # content 与原 canonical 相等（service 据此不翻版本）
    assert captured["content"] == _BASE_CONTENT


# ---------------------------------------------------------------------------
# 关联同步 —— add/remove/change → RepoAssociationService 对应方法
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_sync_repo_associations_routes_each_branch() -> None:
    project = SimpleNamespace(id="p1")
    revision = {
        "add_repos": ["r_add"],
        "remove_repos": ["r_rm"],
        "change_repos": ["r_chg"],
        "plan_delta_summary": "",
    }
    ra = MagicMock()
    ra.confirm_repos = AsyncMock(return_value=[])
    ra.reopen_candidates = AsyncMock(return_value=True)
    ra.dispatch_verify = AsyncMock(return_value={})

    assoc_rm = MagicMock(repository_id="r_rm")
    assoc_chg = MagicMock(repository_id="r_chg")

    async def _load(proj, repo_ids):  # noqa: ANN001
        return [assoc_rm] if repo_ids == ["r_rm"] else [assoc_chg]

    with (
        patch(f"{_RA_MOD}.RepoAssociationService", return_value=ra),
        patch(f"{_SVC_MOD}.PlanDeepenService._aload_associations", new=AsyncMock(side_effect=_load)),
    ):
        await PlanDeepenService()._sync_repo_associations(
            project=project, revision=revision, initiated_by_user_id="42"
        )

    # add → confirm_repos
    ra.confirm_repos.assert_awaited_once()
    assert ra.confirm_repos.await_args.kwargs["repo_ids"] == ["r_add"]
    # remove → reopen_candidates（逐 assoc）
    ra.reopen_candidates.assert_awaited_once()
    # change → dispatch_verify
    ra.dispatch_verify.assert_awaited_once()
    assert ra.dispatch_verify.await_args.kwargs["confirmed"] == [assoc_chg]


@pytest.mark.asyncio
async def test_sync_repo_associations_no_project_skips() -> None:
    ra = MagicMock()
    ra.confirm_repos = AsyncMock()
    with patch(f"{_RA_MOD}.RepoAssociationService", return_value=ra):
        await PlanDeepenService()._sync_repo_associations(
            project=None,
            revision={"add_repos": ["x"]},
            initiated_by_user_id="system",
        )
    ra.confirm_repos.assert_not_awaited()


@pytest.mark.asyncio
async def test_sync_repo_associations_failsoft() -> None:
    project = SimpleNamespace(id="p1")
    ra = MagicMock()
    ra.confirm_repos = AsyncMock(side_effect=RuntimeError("boom"))
    with patch(f"{_RA_MOD}.RepoAssociationService", return_value=ra):
        # 同步失败吞掉，不冒泡（绝不反噬补充修订版本）
        await PlanDeepenService()._sync_repo_associations(
            project=project,
            revision={"add_repos": ["x"]},
            initiated_by_user_id="system",
        )
