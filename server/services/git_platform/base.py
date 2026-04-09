"""Abstract base class for Git platform clients."""
from abc import ABC, abstractmethod
from .models import BranchCompareResult, MRCreateRequest, MRCreateResult, MRDiffResult
class GitPlatformClient(ABC):
 """Abstract base class for Git platform operations."""
 @abstractmethod
 async def create_merge_request(self, request: MRCreateRequest) -> MRCreateResult:
 """Create a merge/pull request with optional reviewers.
 Args:
 request: The merge request creation parameters.
 Returns:
 MRCreateResult with success status and MR details or error.
 """
 pass
 @abstractmethod
 async def get_user_id_by_username(self, username: str) -> int | None:
 """Resolve a username to the platform's user ID.
 Args:
 username: The username to look up.
 Returns:
 The user ID if found, None otherwise.
 """
 pass
 @abstractmethod
 async def branch_exists(self, branch_name: str) -> bool:
 """检查远程仓库是否存在指定分支。
 Args:
 branch_name: 分支名称。
 Returns:
 True if branch exists, False otherwise.
 """
 pass
 @abstractmethod
 async def get_merge_request_diff(
 self,
 mr_id: str,
 max_files: int = 50,
 max_diff_lines: int = 500,
 ) -> MRDiffResult:
 """获取 MR/PR 的文件变更 diff。
 Args:
 mr_id: MR/PR 的 ID 或编号
 max_files: 最大文件数限制
 max_diff_lines: 单个文件 diff 最大行数
 Returns:
 MRDiffResult 包含文件列表和 diff 内容
 """
 pass
 @abstractmethod
 async def compare_branches(
 self,
 source_branch: str,
 target_branch: str,
 max_files: int = 50,
 ) -> BranchCompareResult:
 """对比两个分支的差异（per ）。
 Args:
 source_branch: 功能分支名。
 target_branch: 目标（base）分支名。
 max_files: 最大返回文件数（per 默认 50）。
 Returns:
 BranchCompareResult 包含文件变更统计和冲突推断。
 """
 pass
