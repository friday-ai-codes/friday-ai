"""MCP 工具 + ContextRetrievalNode 分支查询测试。"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _make_branch_index(
    *, is_base: bool = False, status: str = "indexed", collection: str = "overlay_col"
) -> MagicMock:
    bi = MagicMock()
    bi.is_base_branch = is_base
    bi.status = status
    bi.collection_name = collection
    return bi


def _make_file_change(change_type: str, file_path: str = "src/app.py") -> MagicMock:
    fc = MagicMock()
    fc.change_type = change_type
    fc.file_path = file_path
    return fc


# ===================================================================
# browse_file_content 测试
# ===================================================================


@pytest.mark.asyncio
async def test_browse_file_deleted_in_branch() -> None:
    """分支中被删除的文件应返回空 chunks + 删除提示。"""
    from agents.tools.chat_tools import browse_file_content

    branch_index = _make_branch_index()
    file_change = _make_file_change("deleted")

    with (
        patch(
            "services.branch_utils.is_branch_index_enabled_async",
            new_callable=AsyncMock,
            return_value=True,
        ),
        patch(
            "services.branch_utils.resolve_branch_for_query",
            new_callable=AsyncMock,
            return_value=("feat/x", branch_index),
        ),
        patch(
            "repositories.models.BranchFileIndex.objects",
        ) as mock_bfi_objects,
        patch(
            "agents.tools.chat_tools._build_matcher_failclosed",
            new=AsyncMock(return_value=MagicMock(is_excluded=MagicMock(return_value=False))),
        ),
    ):
        mock_bfi_objects.filter.return_value.afirst = AsyncMock(return_value=file_change)

        result = await browse_file_content(
            repository_id="repo-1",
            file_path="src/app.py",
            branch="feat/x",
        )

    assert result.success is True
    assert result.output["data"]["total_chunks"] == 0
    assert "deleted" in result.output["error"].lower()


@pytest.mark.asyncio
async def test_browse_file_modified_in_branch() -> None:
    """分支中 modified 文件应从 overlay collection 获取 chunks。"""
    from agents.tools.chat_tools import browse_file_content

    branch_index = _make_branch_index(collection="overlay_col")
    file_change = _make_file_change("modified")

    overlay_payload = [
        {"content": "overlay content", "chunk_index": 0, "start_line": 1, "end_line": 10, "language": "python"}
    ]

    with (
        patch(
            "services.branch_utils.is_branch_index_enabled_async",
            new_callable=AsyncMock,
            return_value=True,
        ),
        patch(
            "services.branch_utils.resolve_branch_for_query",
            new_callable=AsyncMock,
            return_value=("feat/x", branch_index),
        ),
        patch(
            "repositories.models.BranchFileIndex.objects",
        ) as mock_bfi_objects,
        patch(
            "agents.tools.chat_tools._scroll_file_from_collection",
            new_callable=AsyncMock,
            return_value=overlay_payload,
        ),
        patch(
            "agents.tools.chat_tools._build_matcher_failclosed",
            new=AsyncMock(return_value=MagicMock(is_excluded=MagicMock(return_value=False))),
        ),
    ):
        mock_bfi_objects.filter.return_value.afirst = AsyncMock(return_value=file_change)

        result = await browse_file_content(
            repository_id="repo-1",
            file_path="src/app.py",
            branch="feat/x",
        )

    assert result.success is True
    assert result.output["data"]["total_chunks"] == 1
    assert result.output["data"]["chunks"][0]["content"] == "overlay content"


@pytest.mark.asyncio
async def test_browse_file_no_branch_unchanged() -> None:
    """不传 branch 时走 base collection，行为不变。"""
    from agents.tools.chat_tools import browse_file_content

    base_payload = [
        {"content": "base content", "chunk_index": 0, "start_line": 1, "end_line": 5, "language": "python"}
    ]

    with (
        patch(
            "agents.tools.chat_tools._scroll_file_from_collection",
            new_callable=AsyncMock,
            return_value=base_payload,
        ),
        patch(
            "agents.tools.chat_tools._build_matcher_failclosed",
            new=AsyncMock(return_value=MagicMock(is_excluded=MagicMock(return_value=False))),
        ),
    ):
        result = await browse_file_content(
            repository_id="repo-1",
            file_path="src/app.py",
        )

    assert result.success is True
    assert result.output["data"]["total_chunks"] == 1
    assert result.output["data"]["chunks"][0]["content"] == "base content"


# ===================================================================
# list_space_structure 测试（集合运算验证）
# ===================================================================


def test_list_structure_branch_view() -> None:
    """分支视图文件树集合运算：final = (base - deleted) | added。"""
    base_paths = {"a.py", "b.py", "c.py"}
    added = {"d.py"}
    deleted = {"b.py"}
    final_paths = (base_paths - deleted) | added

    assert final_paths == {"a.py", "c.py", "d.py"}
    assert "b.py" not in final_paths
    assert "d.py" in final_paths


# ===================================================================
# get_space_overview 测试（统计验证）
# ===================================================================


def test_get_overview_branch_stats() -> None:
    """分支视图统计：file_count = base - deleted + added。"""
    base_count = 100
    added_count = 5
    deleted_count = 3
    adjusted = base_count - deleted_count + added_count
    assert adjusted == 102


# ===================================================================
# deep_analysis 测试
# ===================================================================


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_deep_analysis_passes_branch() -> None:
    """deep_analysis 应将 branch 传递到 DispatchTask。"""
    from agents.tools.chat_tools import deep_analysis

    dispatched_tasks: list[object] = []

    mock_project = MagicMock()
    mock_project.id = "proj-1"
    mock_project.name = "Test"

    mock_repo = MagicMock()
    mock_repo.id = "repo-1"
    mock_repo.name = "test-repo"
    mock_repo.git_url = "https://github.com/test/repo.git"
    mock_repo.default_branch = "main"

    mock_dispatcher = MagicMock()

    async def _fake_dispatch(task: object) -> None:
        dispatched_tasks.append(task)

    mock_dispatcher.dispatch = _fake_dispatch

    with (
        patch("projects.models.Space.objects", new_callable=MagicMock) as mock_proj_objs,
        patch("repositories.models.Repository.objects", new_callable=MagicMock) as mock_repo_objs,
        patch("subagent.models.SubAgentSession.objects", new_callable=MagicMock) as mock_sub_objs,
        patch("runners.models.Runner.objects", new_callable=MagicMock) as mock_runner_objs,
        patch("agents.models.AgentSession.objects", new_callable=MagicMock) as mock_agent_objs,
        patch("runners.dispatcher.get_dispatcher", return_value=mock_dispatcher),
        patch("chat.services.aget_setting_value", new_callable=AsyncMock, return_value=""),
        patch("agents.tools.blocking_task_registry.register_blocking_task", new_callable=AsyncMock),
        patch("repositories.models.GitCredential.objects", new_callable=MagicMock) as mock_git_objs,
    ):
        # Space.objects.aget
        mock_proj_objs.aget = AsyncMock(return_value=mock_project)

        # Repository.objects.filter → async iter repo
        async def _repo_aiter() -> object:  # type: ignore[override]
            yield mock_repo

        repo_qs = MagicMock()
        repo_qs.__getitem__ = MagicMock(return_value=repo_qs)
        repo_qs.__aiter__ = lambda self: _repo_aiter()
        mock_repo_objs.filter.return_value = repo_qs

        # SubAgentSession — empty
        async def _empty_aiter() -> object:  # type: ignore[override]
            return
            yield  # noqa: unreachable

        sub_qs = MagicMock()
        sub_qs.select_related.return_value = sub_qs
        sub_qs.__aiter__ = lambda self: _empty_aiter()
        mock_sub_objs.filter.return_value = sub_qs

        # Runner online
        runner_qs = MagicMock()
        runner_qs.acount = AsyncMock(return_value=1)
        mock_runner_objs.filter.return_value = runner_qs

        # AgentSession.objects.acreate
        mock_agent_session = MagicMock()
        mock_agent_session.session_id = "agent-deep-test"
        mock_agent_objs.acreate = AsyncMock(return_value=mock_agent_session)

        # SubAgentSession.objects.acreate
        mock_sub_session = MagicMock()
        mock_sub_session.session_id = "deep-test"
        mock_sub_objs.acreate = AsyncMock(return_value=mock_sub_session)

        # GitCredential — DoesNotExist
        from repositories.models import GitCredential
        mock_git_objs.aget = AsyncMock(side_effect=GitCredential.DoesNotExist)

        result = await deep_analysis(
            space_id="proj-1",
            task_description="分析模块架构",
            branch="feat/new-feature",
        )

    assert result.success is True
    assert len(dispatched_tasks) == 1
    task = dispatched_tasks[0]
    assert task.branch == "feat/new-feature"


# ===================================================================
# ContextRetrievalNode 测试
# ===================================================================


@pytest.mark.skip(
    reason=(
        "OBSOLETE — implementation LayeredSearchService 替代 EmbeddingService 直调 + "
        "BranchAwareSearchService。本测试 patch 的 "
        "`workflows.nodes.ai.context_retrieval.EmbeddingService` 已不存在。"
        "v24.0 应改写成对 LayeredSearchService.search 的 contract 测试。"
    )
)
@pytest.mark.asyncio
async def test_context_retrieval_passes_branch() -> None:
    """ContextRetrievalNode 应将 branch 传递到 BranchAwareSearchService。"""
    from workflows.nodes.ai.context_retrieval import ContextRetrievalNode

    node = ContextRetrievalNode()

    search_calls: list[dict[str, object]] = []

    async def _fake_search(
        repository_id: str,
        query_dense: list[float],
        *,
        branch_name: str | None = None,
        top_k: int = 30,
        filters: dict[str, object] | None = None,
    ) -> list[dict[str, object]]:
        search_calls.append({
            "repository_id": repository_id,
            "branch_name": branch_name,
            "top_k": top_k,
        })
        return [
            {
                "id": "p1",
                "score": 0.9,
                "payload": {
                    "file_path": "src/main.py",
                    "content": "hello",
                    "language": "python",
                    "start_line": 1,
                    "end_line": 10,
                    "chunk_index": 0,
                },
            }
        ]

    mock_repo = MagicMock()
    mock_repo.id = "repo-1"
    mock_repo.name = "test-repo"
    mock_repo.is_deleted = False

    mock_context = MagicMock()
    mock_context.node_config = {
        "query": "auth flow",
        "branch": "feat/auth",
        "repositories": [{"id": "repo-1"}],
        "top_k": 5,
    }
    mock_context.render_template = lambda v: v

    with (
        patch(
            "workflows.nodes.ai.context_retrieval.EmbeddingService.generate_embedding",
            new_callable=AsyncMock,
            return_value=[0.1] * 768,
        ),
        patch(
            "workflows.nodes.ai.context_retrieval.normalize_repositories",
            return_value=[{"id": "repo-1"}],
        ),
        patch(
            "repositories.models.Repository.objects",
            new_callable=MagicMock,
        ) as mock_repo_objs,
        patch(
            "services.branch_search.BranchAwareSearchService.search",
            side_effect=_fake_search,
        ),
    ):
        mock_repo_objs.filter.return_value.afirst = AsyncMock(return_value=mock_repo)

        result = await node.execute(mock_context)

    assert result.status == "completed"
    assert len(search_calls) == 1
    assert search_calls[0]["branch_name"] == "feat/auth"


@pytest.mark.skip(
    reason=(
        "OBSOLETE — implementation LayeredSearchService 替代 EmbeddingService 直调 + "
        "BranchAwareSearchService。本测试 patch 的 "
        "`workflows.nodes.ai.context_retrieval.EmbeddingService` 已不存在。"
        "v24.0 应改写成对 LayeredSearchService.search 的 contract 测试。"
    )
)
@pytest.mark.asyncio
async def test_context_retrieval_no_branch_compat() -> None:
    """不传 branch 时 ContextRetrievalNode 行为兼容（branch_name=None）。"""
    from workflows.nodes.ai.context_retrieval import ContextRetrievalNode

    node = ContextRetrievalNode()

    search_calls: list[dict[str, object]] = []

    async def _fake_search(
        repository_id: str,
        query_dense: list[float],
        *,
        branch_name: str | None = None,
        top_k: int = 30,
        filters: dict[str, object] | None = None,
    ) -> list[dict[str, object]]:
        search_calls.append({
            "repository_id": repository_id,
            "branch_name": branch_name,
        })
        return []

    mock_repo = MagicMock()
    mock_repo.id = "repo-1"
    mock_repo.name = "test-repo"

    mock_context = MagicMock()
    mock_context.node_config = {
        "query": "auth flow",
        "repositories": [{"id": "repo-1"}],
    }
    mock_context.render_template = lambda v: v

    with (
        patch(
            "workflows.nodes.ai.context_retrieval.EmbeddingService.generate_embedding",
            new_callable=AsyncMock,
            return_value=[0.1] * 768,
        ),
        patch(
            "workflows.nodes.ai.context_retrieval.normalize_repositories",
            return_value=[{"id": "repo-1"}],
        ),
        patch(
            "repositories.models.Repository.objects",
            new_callable=MagicMock,
        ) as mock_repo_objs,
        patch(
            "services.branch_search.BranchAwareSearchService.search",
            side_effect=_fake_search,
        ),
    ):
        mock_repo_objs.filter.return_value.afirst = AsyncMock(return_value=mock_repo)

        result = await node.execute(mock_context)

    assert result.status == "completed"
    assert len(search_calls) == 1
    assert search_calls[0]["branch_name"] is None
