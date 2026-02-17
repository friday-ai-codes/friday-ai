"""Tests for CreateBranchNode multi-repository support.
Tests cover:
- Batch create branch with all repositories succeeding
- Batch create branch with partial failures
- Backward compatibility with repository_path
"""
import subprocess
import uuid
from pathlib import Path
from unittest.mock import MagicMock, patch
import pytest
from workflows.nodes.base import ExecutionContext
from workflows.nodes.git.branch import CreateBranchNode
def make_context(
 node_config: dict,
 input_data: dict | None = None,
 workflow_context: dict | None = None,
) -> ExecutionContext:
 """Create a minimal ExecutionContext for testing."""
 return ExecutionContext(
 execution_id=str(uuid.uuid4),
 node_id="test_node",
 node_config=node_config,
 input_data=input_data or {},
 workflow_context=workflow_context or {},
 previous_outputs={},
 )
class MockRepository:
 """Mock Repository model for testing."""
 def __init__(self, repo_id: str, name: str):
 self.id = uuid.UUID(repo_id) if len(repo_id) == 36 else repo_id
 self.name = name
 self.is_deleted = False
@pytest.mark.django_db
class TestCreateBranchNodeBatch:
 """Tests for CreateBranchNode multi-repository batch operations."""
 @pytest.mark.asyncio
 async def test_batch_create_branch_all_success(self, tmp_path: Path):
 """Test batch branch creation with all repositories succeeding."""
 # Setup: Create mock repositories
 repo1_id = str(uuid.uuid4)
 repo2_id = str(uuid.uuid4)
 repo1 = MockRepository(repo1_id, "repo-1")
 repo2 = MockRepository(repo2_id, "repo-2")
 # Create temp repo directories
 repo1_path = tmp_path / "repos" / repo1_id
 repo2_path = tmp_path / "repos" / repo2_id
 repo1_path.mkdir(parents=True)
 repo2_path.mkdir(parents=True)
 node = CreateBranchNode
 context = make_context({
 "repositories": [repo1_id, repo2_id],
 "branch_name": "feature/test-branch",
 "base_branch": "main",
 "checkout": True,
 "push": False,
 })
 # Mock Repository.objects.filter to return our mock repos
 def mock_filter_side_effect(id=None, name=None, is_deleted=False):
 mock_qs = MagicMock
 if id == repo1_id:
 mock_qs.first.return_value = repo1
 elif id == repo2_id:
 mock_qs.first.return_value = repo2
 else:
 mock_qs.first.return_value = None
 return mock_qs
 # Mock subprocess.run to succeed
 mock_run = MagicMock(return_value=MagicMock(returncode=0))
 with patch("workflows.nodes.git.branch.DATA_DIR", tmp_path), \
 patch("repositories.models.Repository.objects") as mock_objects, \
 patch("asyncio.to_thread", side_effect=lambda func, *args, **kwargs: func(*args, **kwargs)), \
 patch("subprocess.run", mock_run):
 mock_objects.filter.side_effect = mock_filter_side_effect
 result = await node.execute(context)
 assert result.status == "completed"
 assert result.next_handle == "default"
 assert result.output["branch_name"] == "feature/test-branch"
 assert result.output["base_branch"] == "main"
 assert result.output["total"] == 2
 assert len(result.output["succeeded"]) == 2
 assert len(result.output["failed"]) == 0
 assert result.output["all_succeeded"] is True
 # Verify succeeded contains correct info
 succeeded_ids = [s["repository_id"] for s in result.output["succeeded"]]
 assert repo1_id in succeeded_ids
 assert repo2_id in succeeded_ids
 @pytest.mark.asyncio
 async def test_batch_create_branch_partial_failure(self, tmp_path: Path):
 """Test batch branch creation with partial failures - other repos continue."""
 # Setup: Create mock repositories
 repo1_id = str(uuid.uuid4)
 repo2_id = str(uuid.uuid4)
 repo1 = MockRepository(repo1_id, "repo-success")
 repo2 = MockRepository(repo2_id, "repo-fail")
 # Only create repo1 path, repo2 will fail
 repo1_path = tmp_path / "repos" / repo1_id
 repo1_path.mkdir(parents=True)
 # repo2 path intentionally NOT created to simulate failure
 node = CreateBranchNode
 context = make_context({
 "repositories": [repo1_id, repo2_id],
 "branch_name": "feature/test-branch",
 "base_branch": "main",
 "checkout": True,
 "push": False,
 })
 def mock_filter_side_effect(id=None, name=None, is_deleted=False):
 mock_qs = MagicMock
 if id == repo1_id:
 mock_qs.first.return_value = repo1
 elif id == repo2_id:
 mock_qs.first.return_value = repo2
 else:
 mock_qs.first.return_value = None
 return mock_qs
 # Mock subprocess.run to succeed
 mock_run = MagicMock(return_value=MagicMock(returncode=0))
 with patch("workflows.nodes.git.branch.DATA_DIR", tmp_path), \
 patch("repositories.models.Repository.objects") as mock_objects, \
 patch("asyncio.to_thread", side_effect=lambda func, *args, **kwargs: func(*args, **kwargs)), \
 patch("subprocess.run", mock_run):
 mock_objects.filter.side_effect = mock_filter_side_effect
 result = await node.execute(context)
 # Should still complete (partial success)
 assert result.status == "completed"
 assert result.next_handle == "default"
 assert result.output["total"] == 2
 assert len(result.output["succeeded"]) == 1
 assert len(result.output["failed"]) == 1
 assert result.output["all_succeeded"] is False
 # Verify correct repo succeeded
 assert result.output["succeeded"][0]["repository_id"] == repo1_id
 assert result.output["succeeded"][0]["repository_name"] == "repo-success"
 # Verify correct repo failed
 assert result.output["failed"][0]["repository_id"] == repo2_id
 assert "不存在" in result.output["failed"][0]["error"]
 @pytest.mark.asyncio
 async def test_batch_create_branch_backward_compat(self, tmp_path: Path):
 """Test backward compatibility with repository_path config."""
 node = CreateBranchNode
 # Use legacy repository_path instead of repositories
 repo_path = tmp_path / "legacy-repo"
 repo_path.mkdir(parents=True)
 context = make_context({
 "repository_path": str(repo_path),
 "branch_name": "feature/legacy-branch",
 "base_branch": "main",
 "checkout": True,
 "push": False,
 })
 # Mock subprocess.run to succeed
 mock_run = MagicMock(return_value=MagicMock(returncode=0))
 with patch("asyncio.to_thread", side_effect=lambda func, *args, **kwargs: func(*args, **kwargs)), \
 patch("subprocess.run", mock_run):
 result = await node.execute(context)
 assert result.status == "completed"
 assert result.next_handle == "default"
 assert result.output["branch_name"] == "feature/legacy-branch"
 assert result.output["repository_path"] == str(repo_path)
 assert result.output["pushed"] is False
 @pytest.mark.asyncio
 async def test_batch_create_branch_empty_name_fails(self):
 """Test that empty branch name returns error."""
 node = CreateBranchNode
 context = make_context({
 "repositories": ["some-repo-id"],
 "branch_name": "",
 })
 result = await node.execute(context)
 assert result.status == "failed"
 assert result.next_handle == "error"
 assert "分支名称" in result.error
 @pytest.mark.asyncio
 async def test_batch_create_branch_no_repos_or_path_fails(self):
 """Test that missing both repositories and repository_path returns error."""
 node = CreateBranchNode
 context = make_context({
 "branch_name": "feature/test",
 })
 result = await node.execute(context)
 assert result.status == "failed"
 assert result.next_handle == "error"
 assert "repositories" in result.error or "repository_path" in result.error
 @pytest.mark.asyncio
 async def test_batch_create_branch_all_invalid_repos(self):
 """Test that all invalid repository IDs returns error."""
 node = CreateBranchNode
 context = make_context({
 "repositories": ["invalid-id-1", "invalid-id-2"],
 "branch_name": "feature/test",
 })
 def mock_filter_side_effect(id=None, name=None, is_deleted=False):
 mock_qs = MagicMock
 mock_qs.first.return_value = None # No repos found
 return mock_qs
 with patch("repositories.models.Repository.objects") as mock_objects:
 mock_objects.filter.side_effect = mock_filter_side_effect
 result = await node.execute(context)
 assert result.status == "failed"
 assert result.next_handle == "error"
 assert "无效" in result.error
 @pytest.mark.asyncio
 async def test_batch_create_branch_git_error_captured(self, tmp_path: Path):
 """Test that git command errors are properly captured."""
 repo_id = str(uuid.uuid4)
 repo = MockRepository(repo_id, "repo-git-error")
 # Create repo path
 repo_path = tmp_path / "repos" / repo_id
 repo_path.mkdir(parents=True)
 node = CreateBranchNode
 context = make_context({
 "repositories": [repo_id],
 "branch_name": "feature/test-branch",
 "base_branch": "main",
 })
 def mock_filter_side_effect(id=None, name=None, is_deleted=False):
 mock_qs = MagicMock
 if id == repo_id:
 mock_qs.first.return_value = repo
 else:
 mock_qs.first.return_value = None
 return mock_qs
 # Mock subprocess.run to raise CalledProcessError
 def mock_run_error(*args, **kwargs):
 error = subprocess.CalledProcessError(1, "git fetch")
 error.stderr = b"fatal: remote origin not found"
 raise error
 with patch("workflows.nodes.git.branch.DATA_DIR", tmp_path), \
 patch("repositories.models.Repository.objects") as mock_objects, \
 patch("asyncio.to_thread", side_effect=lambda func, *args, **kwargs: func(*args, **kwargs)), \
 patch("subprocess.run", side_effect=mock_run_error):
 mock_objects.filter.side_effect = mock_filter_side_effect
 result = await node.execute(context)
 # Should complete but with failure in the list
 assert result.status == "completed"
 assert len(result.output["failed"]) == 1
 assert "Git 操作失败" in result.output["failed"][0]["error"]
 assert "remote origin not found" in result.output["failed"][0]["error"]
