"""Chat 对话工具单元测试。

测试 browse_file_content、list_space_structure、get_space_overview 三个工具，
以及动态工具注入逻辑 _get_tool_names()。全部 mock QdrantService 和 DB 查询。
"""

from __future__ import annotations

from collections import namedtuple
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# 触发 @tool 注册
import agents.tools.chat_tools  # noqa: F401
from agents.tools.chat_tools import (
    browse_file_content,
    get_space_overview,
    list_space_structure,
)

# ============================================================================
# Mock 数据结构
# ============================================================================

MockPoint = namedtuple("MockPoint", ["id", "payload"])


def _make_scroll_response(payloads: list[dict], next_offset=None):
    """构造 mock scroll 返回值。"""
    points = [MockPoint(id=i, payload=p) for i, p in enumerate(payloads)]
    return (points, next_offset)


# ============================================================================
# browse_file_content 测试
# ============================================================================


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
class TestBrowseFileContent:
    """browse_file_content 工具测试。"""

    async def test_returns_chunks_sorted_by_index(self):
        """返回按 chunk_index 排序的 chunk 列表。"""
        payloads = [
            {
                "file_path": "src/main.py",
                "content": "chunk 2 content",
                "chunk_index": 2,
                "start_line": 11,
                "end_line": 20,
                "language": "python",
            },
            {
                "file_path": "src/main.py",
                "content": "chunk 1 content",
                "chunk_index": 1,
                "start_line": 1,
                "end_line": 10,
                "language": "python",
            },
        ]

        mock_client = MagicMock()
        mock_client.scroll.return_value = _make_scroll_response(payloads)

        with (
            patch.object(
                agents.tools.chat_tools.QdrantService,
                "get_client",
                return_value=mock_client,
            ),
            patch.object(
                agents.tools.chat_tools.QdrantService,
                "get_collection_name",
                return_value="code_index_repo1",
            ),
            patch(
                "agents.tools.chat_tools._build_matcher_failclosed",
                new=AsyncMock(return_value=MagicMock(is_excluded=MagicMock(return_value=False))),
            ),
        ):
            result = await browse_file_content(
                repository_id="repo1",
                file_path="src/main.py",
            )

        assert result.success is True
        data = result.output["data"]
        assert data["total_chunks"] == 2
        assert data["chunks"][0]["chunk_index"] == 1
        assert data["chunks"][1]["chunk_index"] == 2

    async def test_line_range_filter(self):
        """start_line/end_line 参数过滤 chunk。"""
        payloads = [
            {
                "file_path": "src/main.py",
                "content": "lines 1-10",
                "chunk_index": 0,
                "start_line": 1,
                "end_line": 10,
                "language": "python",
            },
            {
                "file_path": "src/main.py",
                "content": "lines 11-20",
                "chunk_index": 1,
                "start_line": 11,
                "end_line": 20,
                "language": "python",
            },
            {
                "file_path": "src/main.py",
                "content": "lines 21-30",
                "chunk_index": 2,
                "start_line": 21,
                "end_line": 30,
                "language": "python",
            },
        ]

        mock_client = MagicMock()
        mock_client.scroll.return_value = _make_scroll_response(payloads)

        with (
            patch.object(
                agents.tools.chat_tools.QdrantService,
                "get_client",
                return_value=mock_client,
            ),
            patch.object(
                agents.tools.chat_tools.QdrantService,
                "get_collection_name",
                return_value="code_index_repo1",
            ),
            patch(
                "agents.tools.chat_tools._build_matcher_failclosed",
                new=AsyncMock(return_value=MagicMock(is_excluded=MagicMock(return_value=False))),
            ),
        ):
            result = await browse_file_content(
                repository_id="repo1",
                file_path="src/main.py",
                start_line=5,
                end_line=15,
            )

        assert result.success is True
        data = result.output["data"]
        # 应只包含 chunk 0 和 chunk 1（与 5-15 行范围重叠）
        assert data["total_chunks"] == 2
        assert data["chunks"][0]["chunk_index"] == 0
        assert data["chunks"][1]["chunk_index"] == 1

    async def test_file_not_found_returns_empty(self):
        """file_path 不存在时返回空 chunks + error 信息。"""
        mock_client = MagicMock()
        mock_client.scroll.return_value = _make_scroll_response([])

        with (
            patch.object(
                agents.tools.chat_tools.QdrantService,
                "get_client",
                return_value=mock_client,
            ),
            patch.object(
                agents.tools.chat_tools.QdrantService,
                "get_collection_name",
                return_value="code_index_repo1",
            ),
        ):
            result = await browse_file_content(
                repository_id="repo1",
                file_path="nonexistent.py",
            )

        assert result.success is True
        data = result.output["data"]
        assert data["total_chunks"] == 0
        assert data["chunks"] == []
        assert "error" in result.output


# ============================================================================
# list_space_structure 测试
# ============================================================================


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
class TestListSpaceStructure:
    """list_space_structure 工具测试。"""

    async def test_returns_file_tree(self, project):
        """已索引仓库的项目返回文件树。"""
        # 设置仓库为已索引
        repo = await project.repositories.afirst()
        repo.index_status = "indexed"
        await repo.asave()

        payloads = [
            {"file_path": "src/main.py", "language": "python"},
            {"file_path": "src/utils/helper.py", "language": "python"},
            {"file_path": "README.md", "language": "markdown"},
        ]

        mock_client = MagicMock()
        mock_client.scroll.return_value = _make_scroll_response(payloads)

        with (
            patch.object(
                agents.tools.chat_tools.QdrantService,
                "get_client",
                return_value=mock_client,
            ),
            patch.object(
                agents.tools.chat_tools.QdrantService,
                "get_collection_name",
                return_value=f"code_index_{repo.id}",
            ),
        ):
            result = await list_space_structure(
                space_id=str(project.id),
                repository_id=str(repo.id),
            )

        assert result.success is True
        data = result.output["data"]
        assert data["total_files"] == 3
        assert data["structure"] != ""
        assert "README.md" in data["structure"]
        assert "main.py" in data["structure"]

    async def test_missing_repository_id_returns_guidance(self, project):
        """省 token 契约：不传 repository_id → 拒绝全空间 dump，返回引导提示。"""
        result = await list_space_structure(
            space_id=str(project.id),
        )

        assert result.success is True
        data = result.output["data"]
        assert data["total_files"] == 0
        assert data["structure"] == ""
        assert "repository_id" in result.output.get("error", "")

    async def test_no_indexed_repos_returns_empty(self, project):
        """指定仓库未索引 → 返回空结构 + 提示。"""
        repo = await project.repositories.afirst()
        result = await list_space_structure(
            space_id=str(project.id),
            repository_id=str(repo.id),
        )

        assert result.success is True
        data = result.output["data"]
        assert data["total_files"] == 0
        assert "error" in result.output

    async def test_repository_id_filters_to_single_repo(self, project):
        """Phase P15: 传 repository_id 时只列该单仓库的文件树。"""
        repo = await project.repositories.afirst()
        repo.index_status = "indexed"
        await repo.asave()

        payloads = [
            {"file_path": "src/main.py", "language": "python"},
            {"file_path": "src/utils.py", "language": "python"},
        ]
        mock_client = MagicMock()
        mock_client.scroll.return_value = _make_scroll_response(payloads)

        with (
            patch.object(
                agents.tools.chat_tools.QdrantService,
                "get_client",
                return_value=mock_client,
            ),
            patch.object(
                agents.tools.chat_tools.QdrantService,
                "get_collection_name",
                return_value=f"code_index_{repo.id}",
            ),
        ):
            result = await list_space_structure(
                space_id=str(project.id),
                repository_id=str(repo.id),
            )

        assert result.success is True
        data = result.output["data"]
        # repository_id 应反映在返回里供 LLM 后续 chained 调用使用
        assert data["repository_id"] == str(repo.id)
        assert data["total_files"] == 2
        assert "main.py" in data["structure"]

    async def test_repository_id_not_in_space_returns_error_hint(self, project):
        """Phase P15: repository_id 不属于该 space → 友好提示而非崩溃。"""
        import uuid

        result = await list_space_structure(
            space_id=str(project.id),
            repository_id=str(uuid.uuid4()),
        )

        assert result.success is True
        data = result.output["data"]
        assert data["total_files"] == 0
        err = result.output.get("error", "")
        assert "not found" in err.lower() or "not indexed" in err.lower()


# ============================================================================
# get_space_overview 测试
# ============================================================================


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
class TestGetSpaceOverview:
    """get_space_overview 工具测试。"""

    async def test_returns_overview_with_repos(self, project):
        """返回项目概览含仓库信息。"""
        # 设置仓库为已索引
        repo = await project.repositories.afirst()
        repo.index_status = "indexed"
        await repo.asave()

        payloads = [
            {"file_path": "src/main.py", "language": "python"},
            {"file_path": "src/app.ts", "language": "typescript"},
            {"file_path": "src/utils.py", "language": "python"},
        ]

        mock_client = MagicMock()
        mock_client.scroll.return_value = _make_scroll_response(payloads)

        with (
            patch.object(
                agents.tools.chat_tools.QdrantService,
                "get_client",
                return_value=mock_client,
            ),
            patch.object(
                agents.tools.chat_tools.QdrantService,
                "get_collection_name",
                return_value=f"code_index_{repo.id}",
            ),
        ):
            result = await get_space_overview(
                space_id=str(project.id),
            )

        assert result.success is True
        data = result.output["data"]
        assert data["project_name"] == project.name
        assert data["total_repositories"] == 1
        assert data["repositories"][0]["index_status"] == "indexed"
        assert data["repositories"][0]["file_count"] == 3
        assert "python" in data["repositories"][0]["languages"]

    async def test_nonexistent_project(self):
        """不存在的项目返回错误信息。"""
        import uuid

        result = await get_space_overview(
            space_id=str(uuid.uuid4()),
        )

        assert result.success is True
        assert result.output["data"] is None
        assert "error" in result.output


# ============================================================================
# 工具注入逻辑测试
# ============================================================================


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
class TestGetToolNames:
    """_get_tool_names 动态工具注入测试。"""

    async def test_with_indexed_repo_returns_full_tool_set(self, project):
        """有已索引仓库的项目返回完整工具集合（implementation 起含
        ``ask_clarification``，共 9 个工具）。
        """
        from chat.conversation_service import _get_tool_names

        repo = await project.repositories.afirst()
        repo.index_status = "indexed"
        await repo.asave()

        tool_names = await _get_tool_names(str(project.id))

        assert len(tool_names) == 9
        assert "browse_file_content" in tool_names
        assert "list_space_structure" in tool_names
        assert "get_space_overview" in tool_names
        assert "search_repository_code" in tool_names
        assert "list_space_repositories" in tool_names
        assert "get_repository_info" in tool_names
        assert "create_coding_plan" in tool_names
        assert "update_coding_plan" in tool_names
        # 协商工具
        assert "ask_clarification" in tool_names

    async def test_without_indexed_repo_returns_1_tool(self, project):
        """无已索引仓库的项目仅返回 1 个工具。"""
        from chat.conversation_service import _get_tool_names

        tool_names = await _get_tool_names(str(project.id))

        assert len(tool_names) == 1
        assert "get_space_overview" in tool_names
