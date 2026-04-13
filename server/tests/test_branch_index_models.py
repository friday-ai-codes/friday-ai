"""分支索引 DB 模型与工具函数的单元测试。"""
import uuid
import pytest
from repositories.models import (
 BranchFileIndex,
 BranchIndexStatus,
 Repository,
 RepositoryBranchIndex,
)
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
 repo.delete
 assert RepositoryBranchIndex.objects.filter(repository_id=repo_id).count == 0
 def test_reverse_relation(self) -> None:
 repo = Repository.objects.create(name="rel-repo", git_url="https://example.com/rel.git")
 RepositoryBranchIndex.objects.create(repository=repo, branch_name="b1")
 RepositoryBranchIndex.objects.create(repository=repo, branch_name="b2")
 assert repo.branch_indexes.count == 2
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
 bi.delete
 assert BranchFileIndex.objects.filter(branch_index_id=bi_id).count == 0
