"""Webhook Secret 生成与全量索引统计修复测试

测试覆盖：
- Webhook Secret 生成 API（generate_webhook_secret action）
- 前端集成所需的 API 响应格式验证
- 全量索引统计返回值修复（run_full_index 返回 added 字段）
"""

import re
from unittest.mock import AsyncMock, patch

import pytest
from rest_framework.test import APIClient

from repositories.models import Repository
from services.indexer import _build_summary_text

pytestmark = pytest.mark.django_db(transaction=True)


# ============================================================================
# Webhook Secret 生成 API 测试
# ============================================================================


class TestGenerateWebhookSecret:
    """POST /api/repositories/{id}/generate-webhook-secret/ 测试。"""

    @pytest.fixture(autouse=True)
    def _setup(self, user) -> None:
        from permissions.models import SpaceMembership, SpaceRole
        from projects.models import Space

        self.client = APIClient()
        self.client.force_authenticate(user=user)
        self.repo = Repository.objects.create(
            name="Test Repo",
            git_url="https://github.com/test/repo.git",
            git_platform="github",
            default_branch="main",
        )
        # 本端点是 RepositoryViewSet 的 detail action，走 get_queryset()：仓库可见性按
        # 空间成员过滤，孤儿仓库仅超管可见（#9/#11），否则普通用户拿到 404。
        space = Space.objects.create(name="Webhook Secret Space")
        space.repositories.add(self.repo)
        SpaceMembership.objects.create(user=user, space=space, role=SpaceRole.MEMBER)
        self.url = f"/api/repositories/{self.repo.id}/generate-webhook-secret/"

    def test_generate_secret_returns_64_hex(self) -> None:
        """生成的 secret 应为 64 字符 hex 字符串。"""
        response = self.client.post(self.url)
        assert response.status_code == 200
        secret = response.data["webhook_secret"]
        assert len(secret) == 64
        assert re.fullmatch(r"[0-9a-f]{64}", secret)

    def test_secret_persisted_to_database(self) -> None:
        """secret 应持久化到数据库。"""
        response = self.client.post(self.url)
        secret = response.data["webhook_secret"]
        self.repo.refresh_from_db()
        assert self.repo.webhook_secret == secret

    def test_regenerate_overwrites_old_secret(self) -> None:
        """重复调用应生成不同 secret，覆盖旧值。"""
        resp1 = self.client.post(self.url)
        resp2 = self.client.post(self.url)
        secret1 = resp1.data["webhook_secret"]
        secret2 = resp2.data["webhook_secret"]
        assert secret1 != secret2
        self.repo.refresh_from_db()
        assert self.repo.webhook_secret == secret2

    def test_nonexistent_repo_returns_404(self) -> None:
        """不存在的仓库应返回 404。"""
        import uuid

        url = f"/api/repositories/{uuid.uuid4()}/generate-webhook-secret/"
        response = self.client.post(url)
        assert response.status_code == 404


# ============================================================================
# 全量索引统计修复测试
# ============================================================================


class TestFullIndexStats:
    """全量索引统计返回值修复测试。"""

    def test_build_summary_text_with_added_files(self) -> None:
        """files_added > 0 时应返回含'新增 N 文件'的摘要。"""
        result = _build_summary_text(15, 0, 0)
        assert "新增 15 文件" in result
        assert "无变更" not in result

    def test_build_summary_text_no_changes(self) -> None:
        """全部为 0 时应返回'无变更'。"""
        result = _build_summary_text(0, 0, 0)
        assert result == "无变更"

    def test_build_summary_text_mixed(self) -> None:
        """混合操作应包含所有变更类型。"""
        result = _build_summary_text(3, 2, 1)
        assert "新增 3 文件" in result
        assert "修改 2 文件" in result
        assert "删除 1 文件" in result

    @pytest.mark.asyncio
    async def test_run_full_index_returns_added(self) -> None:
        """run_full_index 返回值应包含 added 字段。

        contract 续传重构后：run_full_index 在 PARSING 循环内会真实读取文件 hash
        + 调用图谱抽取等下游服务，单测需要 mock 这些外部依赖。
        """
        from services.indexer import IndexerService

        repo = await Repository.objects.acreate(
            name="Stats Test Repo",
            git_url="https://github.com/test/stats.git",
            git_platform="github",
            default_branch="main",
        )
        indexer = IndexerService(str(repo.id))

        with (
            patch("services.indexer.qdrant_create_collection", new_callable=AsyncMock),
            patch("services.indexer.scan_directory", return_value=["/tmp/a.py", "/tmp/b.py"]),
            patch("services.indexer.compute_file_hash", side_effect=["hash-a", "hash-b"]),
            patch("services.indexer.get_files_last_commit", new_callable=AsyncMock, return_value={}),
            patch.object(indexer.parser, "parse_file", return_value=[]),
            patch("services.indexer.update_index_progress", new_callable=AsyncMock),
            patch("services.indexer.update_current_indexing_file", new_callable=AsyncMock),
            patch.object(
                IndexerService, "_extract_and_write_graph", new_callable=AsyncMock,
            ),
            patch(
                "codegraph.services.repo_summary_builder.RepoSummaryBuilder.build",
                new_callable=AsyncMock,
            ),
        ):
            result = await indexer.run_full_index("/tmp/fake-repo")

        assert result["status"] == "success"
        assert result["added"] == 2
        assert result["files_processed"] == 2
