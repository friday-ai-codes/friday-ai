"""GitLab client implementation for MR operations."""
import asyncio
from typing import Any
import gitlab
import structlog
from .base import GitPlatformClient
from .models import MRCreateRequest, MRCreateResult, MRDiffFile, MRDiffResult
logger = structlog.get_logger
class GitLabClient(GitPlatformClient):
 """GitLab platform client for merge request operations."""
 def __init__(self, base_url: str, token: str, project_path: str) -> None:
 """Initialize GitLab client.
 Args:
 base_url: GitLab instance URL (e.g., https://gitlab.com).
 token: GitLab personal access token.
 project_path: Project path (e.g., namespace/project).
 """
 self.base_url = base_url
 self.token = token
 self.project_path = project_path
 self._gl: gitlab.Gitlab | None = None
 self._project: Any = None
 def _get_client(self) -> gitlab.Gitlab:
 """Get or create GitLab client instance."""
 if self._gl is None:
 self._gl = gitlab.Gitlab(self.base_url, private_token=self.token)
 return self._gl
 def _get_project(self) -> Any:
 """Get or create project instance."""
 if self._project is None:
 gl = self._get_client
 self._project = gl.projects.get(self.project_path)
 return self._project
 async def get_user_id_by_username(self, username: str) -> int | None:
 """Resolve GitLab username to user ID.
 Args:
 username: GitLab username to look up.
 Returns:
 User ID if found, None otherwise.
 """
 try:
 gl = self._get_client
 # Run blocking API call in thread pool
 users = await asyncio.to_thread(
 lambda: list(gl.users.list(username=username))
 )
 if users:
 return users[0].id
 return None
 except Exception as e:
 logger.warning("gitlab_user_lookup_failed", username=username, error=str(e))
 return None
 async def create_merge_request(self, request: MRCreateRequest) -> MRCreateResult:
 """Create a GitLab merge request with optional reviewers.
 Args:
 request: MR creation parameters.
 Returns:
 MRCreateResult with success status, MR URL, or error details.
 """
 try:
 project = self._get_project
 # Resolve reviewer usernames to IDs
 reviewer_ids: list[int] =
 for username in request.reviewer_usernames:
 user_id = await self.get_user_id_by_username(username)
 if user_id:
 reviewer_ids.append(user_id)
 else:
 logger.warning(
 "gitlab_reviewer_not_found",
 username=username,
 project=self.project_path,
 )
 # Prepare MR data
 mr_data: dict[str, Any] = {
 "source_branch": request.source_branch,
 "target_branch": request.target_branch,
 "title": request.title,
 "description": request.description,
 "remove_source_branch": request.remove_source_branch,
 }
 if reviewer_ids:
 mr_data["reviewer_ids"] = reviewer_ids
 # Create MR in thread pool (blocking call)
 mr = await asyncio.to_thread(project.mergerequests.create, mr_data)
 # Check for merge conflicts
 has_conflicts = mr.merge_status == "cannot_be_merged"
 logger.info(
 "gitlab_mr_created",
 mr_id=mr.iid,
 mr_url=mr.web_url,
 has_conflicts=has_conflicts,
 reviewers=reviewer_ids,
 )
 return MRCreateResult(
 success=True,
 mr_url=mr.web_url,
 mr_id=str(mr.iid),
 has_conflicts=has_conflicts,
 )
 except gitlab.exceptions.GitlabCreateError as e:
 error_msg = str(e)
 logger.error(
 "gitlab_mr_creation_failed",
 project=self.project_path,
 source=request.source_branch,
 target=request.target_branch,
 error=error_msg,
 )
 return MRCreateResult(success=False, error=error_msg)
 except Exception as e:
 error_msg = f"Unexpected error: {e}"
 logger.error(
 "gitlab_mr_creation_error",
 project=self.project_path,
 error=error_msg,
 )
 return MRCreateResult(success=False, error=error_msg)
 async def get_merge_request_diff(
 self,
 mr_id: str,
 max_files: int = 50,
 max_diff_lines: int = 500,
 ) -> MRDiffResult:
 """获取 GitLab MR 的文件变更 diff。
 Args:
 mr_id: MR 的 IID（项目内编号）
 max_files: 最大文件数限制
 max_diff_lines: 单个文件 diff 最大行数
 Returns:
 MRDiffResult 包含文件列表和 diff 内容
 """
 try:
 project = self._get_project
 # 获取 MR 对象及其变更
 mr = await asyncio.to_thread(project.mergerequests.get, int(mr_id))
 changes = await asyncio.to_thread(lambda: mr.changes)
 raw_changes: list[dict[str, Any]] = changes.get("changes", )
 truncated = False
 # 截断文件数量
 if len(raw_changes) > max_files:
 raw_changes = raw_changes[:max_files]
 truncated = True
 files: list[MRDiffFile] =
 for change in raw_changes:
 diff_text: str = change.get("diff", "")
 # 截断单个文件 diff 行数
 diff_lines = diff_text.split("\n")
 if len(diff_lines) > max_diff_lines:
 diff_text = "\n".join(diff_lines[:max_diff_lines]) + "\n[diff truncated]"
 truncated = True
 files.append(
 MRDiffFile(
 old_path=change.get("old_path", ""),
 new_path=change.get("new_path", ""),
 diff=diff_text,
 new_file=change.get("new_file", False),
 renamed_file=change.get("renamed_file", False),
 deleted_file=change.get("deleted_file", False),
 )
 )
 logger.info(
 "gitlab_mr_diff_fetched",
 mr_id=mr_id,
 files_count=len(files),
 truncated=truncated,
 )
 return MRDiffResult(success=True, files=files, truncated=truncated)
 except Exception as e:
 error_msg = f"Failed to fetch MR diff: {e}"
 logger.error(
 "gitlab_mr_diff_error",
 mr_id=mr_id,
 project=self.project_path,
 error=error_msg,
 )
 return MRDiffResult(success=False, error=error_msg)
