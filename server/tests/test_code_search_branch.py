"""CodeSearchView 和 search_repository_code 分支感知测试。"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, patch

import pytest

from repositories.index_views import SearchRequestSerializer


@pytest.mark.django_db
class TestSearchRequestSerializer:
    def test_accepts_branch(self) -> None:
        s = SearchRequestSerializer(data={"query": "hello", "branch": "feat/x"})
        assert s.is_valid(), s.errors
        assert s.validated_data["branch"] == "feat/x"

    def test_branch_defaults_to_empty(self) -> None:
        s = SearchRequestSerializer(data={"query": "hello"})
        assert s.is_valid(), s.errors
        assert s.validated_data["branch"] == ""


@pytest.mark.django_db
class TestCodeSearchViewBranch:
    @pytest.mark.asyncio
    async def test_search_passes_branch_to_service(self) -> None:
        """_search 将 branch 传递到 BranchAwareSearchService.search。"""
        from repositories.index_views import CodeSearchView

        view = CodeSearchView()

        mock_embedding = [0.1] * 768
        mock_search_results: list[dict[str, Any]] = [
            {
                "id": "1",
                "score": 0.9,
                "payload": {
                    "file_path": "src/auth.py",
                    "content": "def login():",
                    "language": "python",
                    "start_line": 1,
                    "end_line": 5,
                    "context_header": "",
                    "chunk_index": 0,
                },
            }
        ]

        with (
            patch(
                "repositories.index_views.EmbeddingService.generate_embedding",
                new_callable=AsyncMock,
                return_value=mock_embedding,
            ),
            patch(
                "services.branch_search.BranchAwareSearchService.search",
                new_callable=AsyncMock,
                return_value=mock_search_results,
            ) as mock_service,
            patch(
                "services.reranker.RerankerService.is_enabled",
                new_callable=AsyncMock,
                return_value=False,
            ),
            patch(
                "system.models.SystemSetting.objects",
            ) as mock_objects,
        ):
            mock_qs = AsyncMock()
            mock_qs.afirst = AsyncMock(return_value=None)
            mock_objects.filter.return_value = mock_qs

            results = await view._search("repo-123", "auth logic", 10, {}, branch="feat/login")

            mock_service.assert_called_once()
            call_kwargs = mock_service.call_args.kwargs
            assert call_kwargs["branch_name"] == "feat/login"
            assert len(results) == 1

    @pytest.mark.asyncio
    async def test_search_no_branch_passes_none(self) -> None:
        """未传 branch 时 branch_name=None。"""
        from repositories.index_views import CodeSearchView

        view = CodeSearchView()

        mock_embedding = [0.1] * 768

        with (
            patch(
                "repositories.index_views.EmbeddingService.generate_embedding",
                new_callable=AsyncMock,
                return_value=mock_embedding,
            ),
            patch(
                "services.branch_search.BranchAwareSearchService.search",
                new_callable=AsyncMock,
                return_value=[],
            ) as mock_service,
            patch(
                "services.reranker.RerankerService.is_enabled",
                new_callable=AsyncMock,
                return_value=False,
            ),
            patch(
                "system.models.SystemSetting.objects",
            ) as mock_objects,
        ):
            mock_qs = AsyncMock()
            mock_qs.afirst = AsyncMock(return_value=None)
            mock_objects.filter.return_value = mock_qs

            results = await view._search("repo-123", "auth logic", 10, {})

            mock_service.assert_called_once()
            call_kwargs = mock_service.call_args.kwargs
            assert call_kwargs["branch_name"] is None


@pytest.mark.skip(
    reason=(
        "OBSOLETE — implementation LayeredSearchService 重构后 search_repository_code MCP "
        "工具不再直接调 EmbeddingService（agents.tools.space_tools.EmbeddingService 已不存在）。"
        "v24.0 应迁移为对 LayeredSearchService.search 的契约测试。"
    )
)
@pytest.mark.django_db
class TestSearchRepositoryCodeBranch:
    @pytest.mark.asyncio
    async def test_passes_branch_to_service(self) -> None:
        """MCP 工具将 branch 传递到 BranchAwareSearchService。"""
        from agents.tools.space_tools import search_repository_code

        mock_embedding = [0.1] * 768
        mock_search_results = [
            {
                "id": "1",
                "score": 0.9,
                "payload": {
                    "file_path": "src/auth.py",
                    "content": "def login():",
                    "language": "python",
                    "chunk_index": 0,
                },
            }
        ]

        with (
            patch(
                "agents.tools.space_tools.Repository.objects.aget",
                new_callable=AsyncMock,
            ),
            patch(
                "agents.tools.space_tools.EmbeddingService.generate_embedding",
                new_callable=AsyncMock,
                return_value=mock_embedding,
            ),
            patch(
                "services.branch_search.BranchAwareSearchService.search",
                new_callable=AsyncMock,
                return_value=mock_search_results,
            ) as mock_service,
        ):
            result = await search_repository_code(
                query="login logic",
                repository_id="repo-123",
                branch="feat/auth",
            )

            mock_service.assert_called_once()
            call_kwargs = mock_service.call_args.kwargs
            assert call_kwargs["branch_name"] == "feat/auth"
            assert result.success is True

    @pytest.mark.asyncio
    async def test_no_branch_compatible(self) -> None:
        """不传 branch 时正常搜索（兼容旧行为）。"""
        from agents.tools.space_tools import search_repository_code

        mock_embedding = [0.1] * 768
        mock_search_results = [
            {
                "id": "2",
                "score": 0.85,
                "payload": {
                    "file_path": "src/utils.py",
                    "content": "def helper():",
                    "language": "python",
                    "chunk_index": 0,
                },
            }
        ]

        with (
            patch(
                "agents.tools.space_tools.Repository.objects.aget",
                new_callable=AsyncMock,
            ),
            patch(
                "agents.tools.space_tools.EmbeddingService.generate_embedding",
                new_callable=AsyncMock,
                return_value=mock_embedding,
            ),
            patch(
                "services.branch_search.BranchAwareSearchService.search",
                new_callable=AsyncMock,
                return_value=mock_search_results,
            ) as mock_service,
        ):
            result = await search_repository_code(
                query="helper function",
                repository_id="repo-456",
            )

            mock_service.assert_called_once()
            call_kwargs = mock_service.call_args.kwargs
            assert call_kwargs["branch_name"] is None
            assert result.success is True
