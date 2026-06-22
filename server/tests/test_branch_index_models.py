"""分支索引 DB 模型与工具函数的单元测试。"""

import uuid
from unittest.mock import MagicMock, patch

import pytest

from repositories.models import (
    BranchFileIndex,
    BranchIndexStatus,
    Repository,
    RepositoryBranchIndex,
)
from services.branch_utils import (
    MAX_OVERLAY_COLLECTIONS_PER_REPO,
    BranchOverlayLimitExceeded,
    get_overlay_collection_name,
    sanitize_branch_name,
)
from services.qdrant_service import QdrantService


@pytest.mark.django_db
class TestRepositoryBranchIndex:
    """RepositoryBranchIndex 模型测试。"""

    def test_create_branch_index(self) -> None:
        repo = Repository.objects.create(name="test-repo", git_url="https://example.com/repo.git")
        branch_index = RepositoryBranchIndex.objects.create(
            repository=repo,
            branch_name="feature/login",
        )
        assert branch_index.id is not None
        assert branch_index.branch_name == "feature/login"
        assert branch_index.is_base_branch is False
        assert branch_index.status == BranchIndexStatus.NOT_INDEXED

    def test_default_field_values(self) -> None:
        repo = Repository.objects.create(name="test-repo-2", git_url="https://example.com/r2.git")
        branch_index = RepositoryBranchIndex.objects.create(
            repository=repo,
            branch_name="main",
            is_base_branch=True,
        )
        assert branch_index.head_sha is None
        assert branch_index.merge_base_sha is None
        assert branch_index.last_indexed_commit_sha is None
        assert branch_index.last_indexed_at is None
        assert branch_index.is_stale is False
        assert branch_index.effective_chunks_count == 0
        assert branch_index.collection_name is None

    def test_unique_constraint(self) -> None:
        repo = Repository.objects.create(name="uc-repo", git_url="https://example.com/uc.git")
        RepositoryBranchIndex.objects.create(repository=repo, branch_name="main")
        from django.db import IntegrityError

        with pytest.raises(IntegrityError):
            RepositoryBranchIndex.objects.create(repository=repo, branch_name="main")

    def test_branch_index_status_values(self) -> None:
        assert BranchIndexStatus.NOT_INDEXED == "not_indexed"
        assert BranchIndexStatus.INDEXING == "indexing"
        assert BranchIndexStatus.INDEXED == "indexed"
        assert BranchIndexStatus.INHERITED == "inherited"
        assert BranchIndexStatus.FAILED == "failed"

    def test_fk_cascade_delete(self) -> None:
        repo = Repository.objects.create(name="del-repo", git_url="https://example.com/del.git")
        RepositoryBranchIndex.objects.create(repository=repo, branch_name="dev")
        repo_id = repo.id
        repo.delete()
        assert RepositoryBranchIndex.objects.filter(repository_id=repo_id).count() == 0

    def test_reverse_relation(self) -> None:
        repo = Repository.objects.create(name="rel-repo", git_url="https://example.com/rel.git")
        RepositoryBranchIndex.objects.create(repository=repo, branch_name="b1")
        RepositoryBranchIndex.objects.create(repository=repo, branch_name="b2")
        assert repo.branch_indexes.count() == 2


@pytest.mark.django_db
class TestBranchFileIndex:
    """BranchFileIndex 模型测试。"""

    def test_create_branch_file_index(self) -> None:
        repo = Repository.objects.create(name="fi-repo", git_url="https://example.com/fi.git")
        branch_index = RepositoryBranchIndex.objects.create(
            repository=repo, branch_name="feature/x"
        )
        file_index = BranchFileIndex.objects.create(
            branch_index=branch_index,
            file_path="src/main.py",
            change_type="added",
        )
        assert file_index.id is not None
        assert file_index.file_path == "src/main.py"
        assert file_index.change_type == "added"
        assert file_index.indexed_at is not None

    def test_unique_constraint(self) -> None:
        repo = Repository.objects.create(name="fuc-repo", git_url="https://example.com/fuc.git")
        bi = RepositoryBranchIndex.objects.create(repository=repo, branch_name="feat")
        BranchFileIndex.objects.create(branch_index=bi, file_path="a.py", change_type="added")
        from django.db import IntegrityError

        with pytest.raises(IntegrityError):
            BranchFileIndex.objects.create(
                branch_index=bi, file_path="a.py", change_type="modified"
            )

    def test_fk_cascade_delete(self) -> None:
        repo = Repository.objects.create(name="fcd-repo", git_url="https://example.com/fcd.git")
        bi = RepositoryBranchIndex.objects.create(repository=repo, branch_name="feat")
        BranchFileIndex.objects.create(branch_index=bi, file_path="x.py", change_type="deleted")
        bi_id = bi.id
        bi.delete()
        assert BranchFileIndex.objects.filter(branch_index_id=bi_id).count() == 0


class TestBranchUtils:
    """分支命名工具函数测试。"""

    def test_sanitize_normal_branch(self) -> None:
        result = sanitize_branch_name("feature/work item/fix")
        assert "/" not in result
        assert result.startswith("feature_work_item_fix")

    def test_sanitize_special_characters(self) -> None:
        result = sanitize_branch_name("feat/hello@world#test!")
        assert "@" not in result
        assert "#" not in result
        assert "!" not in result

    def test_sanitize_long_branch_name_truncation(self) -> None:
        long_name = "feature/" + "a" * 200
        result = sanitize_branch_name(long_name)
        # 截断到 80 字符 + _ + 8字符 hash = 89 字符
        assert len(result) <= 89

    def test_sanitize_different_names_no_collision(self) -> None:
        r1 = sanitize_branch_name("feature/login")
        r2 = sanitize_branch_name("feature/logout")
        assert r1 != r2

    def test_sanitize_preserves_valid_chars(self) -> None:
        result = sanitize_branch_name("my-branch.v2")
        assert "my-branch.v2" in result

    def test_get_overlay_collection_name_format(self) -> None:
        repo_id = "abc-123"
        name = get_overlay_collection_name(repo_id, "feature/test")
        assert name.startswith(f"code_index_{repo_id}_br_")

    def test_max_overlay_constant(self) -> None:
        assert MAX_OVERLAY_COLLECTIONS_PER_REPO == 20

    def test_branch_overlay_limit_exceeded_is_exception(self) -> None:
        assert issubclass(BranchOverlayLimitExceeded, Exception)
        exc = BranchOverlayLimitExceeded("too many")
        assert str(exc) == "too many"


class TestQdrantServiceOverlay:
    """QdrantService overlay collection 方法测试（mock QdrantClient）。"""

    @patch.object(QdrantService, "get_client")
    def test_create_collection_by_name(self, mock_get_client: MagicMock) -> None:
        mock_client = MagicMock()
        mock_get_client.return_value = mock_client
        mock_client.get_collections.return_value = MagicMock(collections=[])

        result = QdrantService.create_collection_by_name("test_overlay_col")
        assert result is True
        mock_client.create_collection.assert_called_once()
        call_kwargs = mock_client.create_collection.call_args
        assert call_kwargs[1]["collection_name"] == "test_overlay_col"

    @patch.object(QdrantService, "get_client")
    def test_create_collection_by_name_already_exists(self, mock_get_client: MagicMock) -> None:
        mock_client = MagicMock()
        mock_get_client.return_value = mock_client
        existing = MagicMock()
        existing.name = "existing_col"
        mock_client.get_collections.return_value = MagicMock(collections=[existing])

        result = QdrantService.create_collection_by_name("existing_col")
        assert result is True
        mock_client.create_collection.assert_not_called()

    @patch.object(QdrantService, "get_client")
    def test_delete_collection_by_name(self, mock_get_client: MagicMock) -> None:
        mock_client = MagicMock()
        mock_get_client.return_value = mock_client

        result = QdrantService.delete_collection_by_name("some_col")
        assert result is True
        mock_client.delete_collection.assert_called_once_with(collection_name="some_col")

    @patch.object(QdrantService, "get_client")
    def test_upsert_vectors_by_name(self, mock_get_client: MagicMock) -> None:
        mock_client = MagicMock()
        mock_get_client.return_value = mock_client

        points = [
            {"id": "p1", "vector": [0.1, 0.2], "payload": {"file_path": "a.py"}},
        ]
        result = QdrantService.upsert_vectors_by_name("overlay_col", points)
        assert result is True
        mock_client.upsert.assert_called_once()
