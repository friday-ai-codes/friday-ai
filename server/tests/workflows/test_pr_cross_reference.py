"""PR-02 守护测试：可复用跨仓 cross-ref + 方案/工作项追溯 helper（Phase 46-02）。

覆盖 `workflows.services.pr_cross_reference` 三函数：

- `generate_cross_reference_section`（纯函数）：多 PR → 段含兄弟仓链接、排除自身；
  单 PR（无兄弟）→ 空段；段标题中文「## 关联 PR」。
- `render_traceability_section`（async）：plan_version_id 为空 / 链断（pv 取不到）→ ""；
  链全在 → 段含 TechnicalPlan 标识（id + version）+ WorkItem 三元组 + 标题（+ prd_url）。
- `add_cross_references`（async）：GitHub mock `_get_repo().get_pull().edit(body=)`；
  GitLab mock `_get_project().mergerequests.get().save()`；缺凭证 / 单 PR 回写异常 →
  该 PR 标 False、不抛、其它 PR 不受影响（fail-soft）。

以及 Task 2 集成：`AICodingNode._finalize_and_notify` 在 ≥2 成功仓时调 helper（守门 +
整段 fail-soft）；单仓不回写；回写抛错收尾仍 completed。
"""

from __future__ import annotations

import uuid
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# generate_cross_reference_section（纯函数，无 DB / 无 IO）
# ---------------------------------------------------------------------------


def test_cross_reference_section_multi_excludes_self() -> None:
    """多仓成功 → 段含其它兄弟仓链接、排除自身，标题为「## 关联 PR」。"""
    from workflows.services.pr_cross_reference import generate_cross_reference_section

    successful = [
        {"repository_name": "frontend", "mr_url": "https://x/frontend/pull/1"},
        {"repository_name": "backend", "mr_url": "https://x/backend/pull/2"},
    ]

    section = generate_cross_reference_section("https://x/frontend/pull/1", successful)

    assert "## 关联 PR" in section
    assert "[backend]" in section
    assert "https://x/backend/pull/2" in section
    # 排除自身。
    assert "[frontend]" not in section


def test_cross_reference_section_single_returns_empty() -> None:
    """单仓（无兄弟）→ 返回空段。"""
    from workflows.services.pr_cross_reference import generate_cross_reference_section

    successful = [{"repository_name": "only", "mr_url": "https://x/only/pull/1"}]

    assert generate_cross_reference_section("https://x/only/pull/1", successful) == ""


# ---------------------------------------------------------------------------
# render_traceability_section（async + 真实 DB 链）
# ---------------------------------------------------------------------------


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_traceability_full_chain() -> None:
    """链全在 → 段含 Artifact 标识 + WorkItem 三元组/标题/prd_url。"""
    from delivery.models import (
        Artifact,
        ArtifactVersion,
        WorkItem,
        WorkItemOrigin,
    )
    from workflows.services.pr_cross_reference import render_traceability_section

    wi = await WorkItem.objects.acreate(
        feishu_project_key="proj",
        work_item_type="story",
        work_item_id=12345,
        origin=WorkItemOrigin.MANUAL,
        title="登录功能",
        prd_url="https://feishu.example/prd/1",
    )
    art = await Artifact.objects.acreate(artifact_type="technical_plan", work_item=wi)
    av = await ArtifactVersion.objects.acreate(artifact=art, version_no=3, content={})

    section = await render_traceability_section(str(av.id))

    assert "## 关联方案 / 工作项" in section
    assert str(art.id) in section
    assert "v3" in section
    assert "story/12345" in section
    assert "登录功能" in section
    assert "https://feishu.example/prd/1" in section


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_traceability_no_work_item_still_renders_plan() -> None:
    """方案无 work_item → 段含技术方案标识、无工作项行、不抛。"""
    from delivery.models import Artifact, ArtifactVersion
    from workflows.services.pr_cross_reference import render_traceability_section

    art = await Artifact.objects.acreate(artifact_type="technical_plan")
    av = await ArtifactVersion.objects.acreate(artifact=art, version_no=1, content={})

    section = await render_traceability_section(str(av.id))

    assert str(art.id) in section
    # 标题含「工作项」但不应有工作项数据行。
    assert "- 工作项:" not in section


@pytest.mark.asyncio
async def test_traceability_none_id_returns_empty() -> None:
    """plan_version_id 为 None → 返回空段（fail-soft，不触 DB）。"""
    from workflows.services.pr_cross_reference import render_traceability_section

    assert await render_traceability_section(None) == ""
    assert await render_traceability_section("") == ""


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_traceability_broken_chain_returns_empty() -> None:
    """plan_version_id 取不到对应 PlanVersion → 省略追溯段、不抛。"""
    from workflows.services.pr_cross_reference import render_traceability_section

    assert await render_traceability_section(str(uuid.uuid4())) == ""


# ---------------------------------------------------------------------------
# add_cross_references（async 回写编排，mock git client / token / Repository）
# ---------------------------------------------------------------------------


class _FakeGitHubClient:
    """仅暴露 `_get_repo` → 被 hasattr 判定为 GitHub 平台。"""

    def __init__(self, *, boom: bool = False) -> None:
        self.pr = MagicMock()
        if boom:
            self.pr.edit = MagicMock(side_effect=RuntimeError("edit boom"))
        self.repo_obj = MagicMock()
        self.repo_obj.get_pull = MagicMock(return_value=self.pr)

    def _get_repo(self) -> Any:
        return self.repo_obj


class _FakeGitLabClient:
    """仅暴露 `_get_project` → 被 hasattr 判定为 GitLab 平台。"""

    def __init__(self) -> None:
        self.mr = MagicMock()
        self.mr.save = MagicMock()
        self.space = MagicMock()
        self.space.mergerequests.get = MagicMock(return_value=self.mr)

    def _get_project(self) -> Any:
        return self.space


def _repo_mock(rid: str, name: str) -> MagicMock:
    """构造仓库替身（``name`` 是 MagicMock 构造保留字，须创建后再赋值）。"""
    repo = MagicMock(id=rid)
    repo.name = name
    return repo


def _patch_repo_lookup(repos: dict[str, Any]) -> Any:
    """patch helper 内 Repository.objects.filter(id=...).afirst() → repos[str(id)]。"""
    fake_model = MagicMock()

    def _filter(*args: Any, **kwargs: Any) -> Any:
        rid = str(kwargs.get("id"))
        qs = MagicMock()

        async def _afirst() -> Any:
            return repos.get(rid)

        qs.afirst = _afirst
        return qs

    fake_model.objects.filter.side_effect = _filter
    return patch("workflows.services.pr_cross_reference.Repository", fake_model)


async def _async_token(*args: Any, **kwargs: Any) -> str | None:
    return "tok"


async def _async_no_token(*args: Any, **kwargs: Any) -> str | None:
    return None


@pytest.mark.asyncio
async def test_writeback_github_edit_called_with_sibling_and_traceability() -> None:
    """GitHub：edit(body=) 被调，body 含兄弟链接 + 追溯段。"""
    from workflows.services import pr_cross_reference

    repo_a = _repo_mock("A", "frontend")
    repo_b = _repo_mock("B", "backend")
    client_a = _FakeGitHubClient()
    client_b = _FakeGitHubClient()
    clients = {"frontend": client_a, "backend": client_b}

    successful = [
        {
            "repository_id": "A",
            "repository_name": "frontend",
            "mr_url": "https://x/frontend/pull/1",
            "mr_id": "1",
            "description": "原始描述A",
        },
        {
            "repository_id": "B",
            "repository_name": "backend",
            "mr_url": "https://x/backend/pull/2",
            "mr_id": "2",
            "description": "原始描述B",
        },
    ]

    with (
        _patch_repo_lookup({"A": repo_a, "B": repo_b}),
        patch.object(pr_cross_reference, "aresolve_git_token", _async_token),
        patch.object(
            pr_cross_reference,
            "get_git_platform_client",
            MagicMock(side_effect=lambda repo, token: clients[repo.name]),
        ),
        patch.object(
            pr_cross_reference,
            "render_traceability_section",
            new=_make_async_return("\n---\n## 关联方案 / 工作项\n\n- 技术方案: `tp-1`"),
        ),
    ):
        status = await pr_cross_reference.add_cross_references(
            successful, plan_version_id="pv-1"
        )

    assert status["https://x/frontend/pull/1"] is True
    assert status["https://x/backend/pull/2"] is True

    body_a = client_a.pr.edit.call_args.kwargs["body"]
    assert "原始描述A" in body_a
    assert "[backend]" in body_a  # 兄弟链接
    assert "关联方案" in body_a  # 追溯段
    assert "[frontend]" not in body_a  # 排除自身


@pytest.mark.asyncio
async def test_writeback_gitlab_save_called() -> None:
    """GitLab：mergerequests.get().save() 被调，description 含兄弟链接。"""
    from workflows.services import pr_cross_reference

    repo_a = _repo_mock("A", "svc-a")
    repo_b = _repo_mock("B", "svc-b")
    client_a = _FakeGitLabClient()
    client_b = _FakeGitLabClient()
    clients = {"svc-a": client_a, "svc-b": client_b}

    successful = [
        {
            "repository_id": "A",
            "repository_name": "svc-a",
            "mr_url": "https://gl/svc-a/-/merge_requests/1",
            "mr_id": "1",
            "description": "",
        },
        {
            "repository_id": "B",
            "repository_name": "svc-b",
            "mr_url": "https://gl/svc-b/-/merge_requests/2",
            "mr_id": "2",
            "description": "",
        },
    ]

    with (
        _patch_repo_lookup({"A": repo_a, "B": repo_b}),
        patch.object(pr_cross_reference, "aresolve_git_token", _async_token),
        patch.object(
            pr_cross_reference,
            "get_git_platform_client",
            MagicMock(side_effect=lambda repo, token: clients[repo.name]),
        ),
        patch.object(
            pr_cross_reference,
            "render_traceability_section",
            new=_make_async_return(""),
        ),
    ):
        status = await pr_cross_reference.add_cross_references(
            successful, plan_version_id=None
        )

    assert status["https://gl/svc-a/-/merge_requests/1"] is True
    client_a.mr.save.assert_called_once()
    assert "[svc-b]" in client_a.mr.description


@pytest.mark.asyncio
async def test_writeback_no_token_marks_false_no_throw() -> None:
    """缺凭证仓 → 标 False、不构造 client、不抛。"""
    from workflows.services import pr_cross_reference

    repo_a = _repo_mock("A", "a")
    repo_b = _repo_mock("B", "b")
    successful = [
        {
            "repository_id": "A",
            "repository_name": "a",
            "mr_url": "urlA",
            "mr_id": "1",
            "description": "",
        },
        {
            "repository_id": "B",
            "repository_name": "b",
            "mr_url": "urlB",
            "mr_id": "2",
            "description": "",
        },
    ]
    get_client = MagicMock()

    with (
        _patch_repo_lookup({"A": repo_a, "B": repo_b}),
        patch.object(pr_cross_reference, "aresolve_git_token", _async_no_token),
        patch.object(pr_cross_reference, "get_git_platform_client", get_client),
        patch.object(
            pr_cross_reference, "render_traceability_section", new=_make_async_return("")
        ),
    ):
        status = await pr_cross_reference.add_cross_references(
            successful, plan_version_id=None
        )

    assert status == {"urlA": False, "urlB": False}
    get_client.assert_not_called()


@pytest.mark.asyncio
async def test_writeback_single_pr_failure_isolated() -> None:
    """单 PR 回写抛错 → 该 PR 标 False，其它 PR 仍成功（fail-soft 隔离）。"""
    from workflows.services import pr_cross_reference

    repo_a = _repo_mock("A", "boom")
    repo_b = _repo_mock("B", "ok")
    client_a = _FakeGitHubClient(boom=True)
    client_b = _FakeGitHubClient()
    clients = {"boom": client_a, "ok": client_b}

    successful = [
        {
            "repository_id": "A",
            "repository_name": "boom",
            "mr_url": "urlA",
            "mr_id": "1",
            "description": "",
        },
        {
            "repository_id": "B",
            "repository_name": "ok",
            "mr_url": "urlB",
            "mr_id": "2",
            "description": "",
        },
    ]

    with (
        _patch_repo_lookup({"A": repo_a, "B": repo_b}),
        patch.object(pr_cross_reference, "aresolve_git_token", _async_token),
        patch.object(
            pr_cross_reference,
            "get_git_platform_client",
            MagicMock(side_effect=lambda repo, token: clients[repo.name]),
        ),
        patch.object(
            pr_cross_reference, "render_traceability_section", new=_make_async_return("")
        ),
    ):
        status = await pr_cross_reference.add_cross_references(
            successful, plan_version_id=None
        )

    assert status["urlA"] is False
    assert status["urlB"] is True


def _make_async_return(value: Any) -> Any:
    """构造一个忽略入参、恒返回 value 的 async 替身。"""

    async def _coro(*args: Any, **kwargs: Any) -> Any:
        return value

    return _coro


# ---------------------------------------------------------------------------
# Task 2 集成：_finalize_and_notify 接线（≥2 守门 + 整段 fail-soft）
# ---------------------------------------------------------------------------


def _finalize_context() -> Any:
    """构造收尾用 ExecutionContext（node_execution=None → emit_sub_step / 持久化 noop）。"""
    from workflows.nodes.base import ExecutionContext

    return ExecutionContext(
        execution_id="exec-pr02",
        node_id="node-pr02",
        node_config={"chat_id": ""},
        input_data={},
        workflow_context={},
        previous_outputs={},
        node_execution=None,  # type: ignore[arg-type]
    )


async def _make_repo_row(name: str) -> Any:
    from repositories.models import Repository

    return await Repository.objects.acreate(
        name=f"{name}-{uuid.uuid4().hex[:6]}",
        git_url=f"https://github.com/test/{uuid.uuid4().hex[:6]}.git",
        git_platform="github",
        default_branch="main",
        index_status="indexed",
    )


def _patch_create_mr(monkeypatch: pytest.MonkeyPatch) -> None:
    """patch _create_mr_for_repo → 返回带 description 的成功 mr dict（不触 git）。"""
    from workflows.nodes.ai.coding import AICodingNode

    async def _fake_mr(self: Any, *, repository: Any, **kwargs: Any) -> dict[str, Any]:
        return {
            "mr_url": f"https://x/{repository.name}/pull/1",
            "mr_id": "1",
            "has_conflicts": False,
            "description": "原始描述",
        }

    monkeypatch.setattr(AICodingNode, "_create_mr_for_repo", _fake_mr)


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_finalize_two_repos_triggers_cross_ref(monkeypatch: pytest.MonkeyPatch) -> None:
    """≥2 成功仓 → 调 add_cross_references（带 plan_version_id），收尾 completed。"""
    import structlog

    from workflows.nodes.ai.coding import AICodingNode
    from workflows.services import pr_cross_reference

    _patch_create_mr(monkeypatch)

    captured: dict[str, Any] = {}

    async def _fake_add(successful_mrs: list[dict[str, Any]], *, plan_version_id: Any) -> dict[str, bool]:
        captured["mrs"] = successful_mrs
        captured["plan_version_id"] = plan_version_id
        return {}

    monkeypatch.setattr(pr_cross_reference, "add_cross_references", _fake_add)

    repo_a = await _make_repo_row("a")
    repo_b = await _make_repo_row("b")
    succeeded = [
        {"repository_id": str(repo_a.id), "repository_name": repo_a.name, "output": {}},
        {"repository_id": str(repo_b.id), "repository_name": repo_b.name, "output": {}},
    ]

    node = AICodingNode()
    result = await node._finalize_and_notify(
        context=_finalize_context(),
        succeeded=succeeded,
        failed_repos=[],
        completed_session_ids=[],
        branch_name="feat/x",
        base_branch="main",
        plan_title="方案",
        plan_data={"plan_version_id": "pv-xyz"},
        log=structlog.get_logger(),
    )

    assert result.status == "completed"
    assert "mrs" in captured
    assert len(captured["mrs"]) == 2
    assert captured["plan_version_id"] == "pv-xyz"


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_finalize_single_repo_no_cross_ref(monkeypatch: pytest.MonkeyPatch) -> None:
    """单仓成功 → 不调 add_cross_references，收尾 completed（零回归 D-14）。"""
    import structlog

    from workflows.nodes.ai.coding import AICodingNode
    from workflows.services import pr_cross_reference

    _patch_create_mr(monkeypatch)

    called = {"hit": False}

    async def _fake_add(*args: Any, **kwargs: Any) -> dict[str, bool]:
        called["hit"] = True
        return {}

    monkeypatch.setattr(pr_cross_reference, "add_cross_references", _fake_add)

    repo_a = await _make_repo_row("solo")
    succeeded = [
        {"repository_id": str(repo_a.id), "repository_name": repo_a.name, "output": {}},
    ]

    node = AICodingNode()
    result = await node._finalize_and_notify(
        context=_finalize_context(),
        succeeded=succeeded,
        failed_repos=[],
        completed_session_ids=[],
        branch_name="feat/x",
        base_branch="main",
        plan_title="方案",
        plan_data={"plan_version_id": "pv-xyz"},
        log=structlog.get_logger(),
    )

    assert result.status == "completed"
    assert called["hit"] is False
    assert len(result.output["coding_result"]["merge_requests"]) == 1


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_finalize_cross_ref_failure_still_completed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """add_cross_references 抛错 → 收尾仍 completed、mr_results 仍在 output（D-15）。"""
    import structlog

    from workflows.nodes.ai.coding import AICodingNode
    from workflows.services import pr_cross_reference

    _patch_create_mr(monkeypatch)

    async def _boom(*args: Any, **kwargs: Any) -> dict[str, bool]:
        raise RuntimeError("cross-ref boom")

    monkeypatch.setattr(pr_cross_reference, "add_cross_references", _boom)

    repo_a = await _make_repo_row("a")
    repo_b = await _make_repo_row("b")
    succeeded = [
        {"repository_id": str(repo_a.id), "repository_name": repo_a.name, "output": {}},
        {"repository_id": str(repo_b.id), "repository_name": repo_b.name, "output": {}},
    ]

    node = AICodingNode()
    result = await node._finalize_and_notify(
        context=_finalize_context(),
        succeeded=succeeded,
        failed_repos=[],
        completed_session_ids=[],
        branch_name="feat/x",
        base_branch="main",
        plan_title="方案",
        plan_data={"plan_version_id": "pv-xyz"},
        log=structlog.get_logger(),
    )

    assert result.status == "completed"
    assert len(result.output["coding_result"]["merge_requests"]) == 2
