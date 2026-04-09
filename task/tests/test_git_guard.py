"""GitOperations explore 模式守卫测试。
验证 GitOperations 在 explore 模式下拦截所有写操作，
在非 explore 模式下正常放行。
"""
import pytest
from core.exceptions import ExploreModeForbiddenError
from git_ops import GitOperations
class TestExploreModeForbiddenError:
 """ExploreModeForbiddenError 异常类测试。"""
 def test_error_has_operation_attribute(self):
 """Test 8: ExploreModeForbiddenError 有 operation 属性且值正确。"""
 err = ExploreModeForbiddenError("commit_changes")
 assert err.operation == "commit_changes"
 def test_error_message_contains_operation(self):
 """异常消息包含操作名称。"""
 err = ExploreModeForbiddenError("push_branch")
 assert "push_branch" in str(err)
 assert "explore" in str(err)
class TestExploreGuardBlocking:
 """explore 模式下写操作应被拦截。"""
 @pytest.mark.asyncio
 async def test_commit_changes_blocked(self, mock_explore_config):
 """Test 1: explore 模式下调用 commit_changes 抛出 ExploreModeForbiddenError。"""
 git_ops = GitOperations(mock_explore_config)
 with pytest.raises(ExploreModeForbiddenError) as exc_info:
 await git_ops.commit_changes("test commit")
 assert "commit_changes" in str(exc_info.value)
 assert exc_info.value.operation == "commit_changes"
 @pytest.mark.asyncio
 async def test_push_branch_blocked(self, mock_explore_config):
 """Test 2: explore 模式下调用 push_branch 抛出 ExploreModeForbiddenError。"""
 git_ops = GitOperations(mock_explore_config)
 with pytest.raises(ExploreModeForbiddenError) as exc_info:
 await git_ops.push_branch("main")
 assert "push_branch" in str(exc_info.value)
 assert exc_info.value.operation == "push_branch"
 @pytest.mark.asyncio
 async def test_push_branch_with_retry_blocked(self, mock_explore_config):
 """Test 3: explore 模式下调用 push_branch_with_retry 抛出 ExploreModeForbiddenError。"""
 git_ops = GitOperations(mock_explore_config)
 with pytest.raises(ExploreModeForbiddenError) as exc_info:
 await git_ops.push_branch_with_retry("main")
 assert "push_branch_with_retry" in str(exc_info.value)
 assert exc_info.value.operation == "push_branch_with_retry"
 @pytest.mark.asyncio
 async def test_create_feature_branch_blocked(self, mock_explore_config):
 """Test 4: explore 模式下调用 create_feature_branch 抛出 ExploreModeForbiddenError。"""
 git_ops = GitOperations(mock_explore_config)
 with pytest.raises(ExploreModeForbiddenError) as exc_info:
 await git_ops.create_feature_branch("feature-test")
 assert "create_feature_branch" in str(exc_info.value)
 assert exc_info.value.operation == "create_feature_branch"
 @pytest.mark.asyncio
 async def test_setup_task_branch_blocked(self, mock_explore_config):
 """Test 5: explore 模式下调用 setup_task_branch 抛出 ExploreModeForbiddenError。"""
 git_ops = GitOperations(mock_explore_config)
 with pytest.raises(ExploreModeForbiddenError) as exc_info:
 await git_ops.setup_task_branch(None, "test-task")
 assert "setup_task_branch" in str(exc_info.value)
 assert exc_info.value.operation == "setup_task_branch"
class TestNonExploreModePasses:
 """非 explore 模式下写操作不应被模式守卫拦截。"""
 @pytest.mark.asyncio
 async def test_plan_mode_commit_not_blocked(self, mock_config):
 """Test 6: plan 模式下调用 commit_changes 不抛出 ExploreModeForbiddenError。"""
 git_ops = GitOperations(mock_config)
 # 会因为 repo 未初始化抛出 RuntimeError，但不应是 ExploreModeForbiddenError
 with pytest.raises(Exception) as exc_info:
 await git_ops.commit_changes("test")
 assert not isinstance(exc_info.value, ExploreModeForbiddenError)
 @pytest.mark.asyncio
 async def test_execute_mode_push_not_blocked(self, mock_config):
 """Test 7: execute 模式下调用 push_branch 不抛出 ExploreModeForbiddenError。"""
 mock_config.task_mode = "execute"
 git_ops = GitOperations(mock_config)
 # 会因为 repo 未初始化抛出 RuntimeError，但不应是 ExploreModeForbiddenError
 with pytest.raises(Exception) as exc_info:
 await git_ops.push_branch("main")
 assert not isinstance(exc_info.value, ExploreModeForbiddenError)
class TestReadOnlyMethodsPassing:
 """explore 模式下只读方法不应被拦截。"""
 @pytest.mark.asyncio
 async def test_get_modified_files_not_blocked(self, mock_explore_config):
 """Test 9: explore 模式下 get_modified_files 不抛出 ExploreModeForbiddenError。"""
 git_ops = GitOperations(mock_explore_config)
 # repo 为 None 时返回空列表，不应抛出 ExploreModeForbiddenError
 result = await git_ops.get_modified_files
 assert result ==
 @pytest.mark.asyncio
 async def test_get_diff_summary_not_blocked(self, mock_explore_config):
 """Test 9b: explore 模式下 get_diff_summary 不抛出 ExploreModeForbiddenError。"""
 git_ops = GitOperations(mock_explore_config)
 # 会因为 repo 未初始化抛出 RuntimeError，但不应是 ExploreModeForbiddenError
 with pytest.raises(Exception) as exc_info:
 await git_ops.get_diff_summary
 assert not isinstance(exc_info.value, ExploreModeForbiddenError)
 def test_cleanup_not_blocked(self, mock_explore_config):
 """Test 10: explore 模式下 cleanup 不抛出 ExploreModeForbiddenError。"""
 git_ops = GitOperations(mock_explore_config)
 # cleanup 是同步方法，不需要 await，不应抛出任何异常
 git_ops.cleanup
