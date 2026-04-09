"""GitHub client implementation for PR operations."""
import asyncio
import structlog
from github import Auth, Github, GithubException
from .base import GitPlatformClient
from .models import MRCreateRequest, MRCreateResult, MRDiffFile, MRDiffResult
logger = structlog.get_logger
class GitHubClient(GitPlatformClient):
 """GitHub platform client for pull request operations."""
 def __init__(self, token: str, owner: str, repo: str) -> None:
 """Initialize GitHub client.
 Args:
 token: GitHub personal access token.
 owner: Repository owner (user or organization).
 repo: Repository name.
 """
 self.token = token
 self.owner = owner
 self.repo_name = repo
 self._gh: Github | None = None
 def _get_client(self) -> Github:
 """Get or create GitHub client instance."""
 if self._gh is None:
 auth = Auth.Token(self.token)
 self._gh = Github(auth=auth)
 return self._gh
 def _get_repo(self):
 """Get repository instance."""
 gh = self._get_client
 return gh.get_repo(f"{self.owner}/{self.repo_name}")
 async def get_user_id_by_username(self, username: str) -> int | None:
 """Resolve GitHub username to user ID.
 Args:
 username: GitHub username to look up.
 Returns:
 User ID if found, None otherwise.
 """
 try:
 gh = self._get_client
 user = await asyncio.to_thread(gh.get_user, username)
 return user.id
 except GithubException as e:
 logger.warning("github_user_lookup_failed", username=username, error=str(e))
 return None
 except Exception as e:
 logger.warning("github_user_lookup_error", username=username, error=str(e))
 return None
 async def branch_exists(self, branch_name: str) -> bool:
 """检查 GitHub 远程仓库是否存在指定分支。
 Args:
 branch_name: 分支名称。
 Returns:
 True if branch exists, False otherwise.
 """
 try:
 repo = self._get_repo
 await asyncio.to_thread(repo.get_branch, branch_name)
 return True
 except GithubException:
 return False
 async def create_merge_request(self, request: MRCreateRequest) -> MRCreateResult:
 """Create a GitHub pull request with optional reviewers.
 Args:
 request: PR creation parameters.
 Returns:
 MRCreateResult with success status, PR URL, or error details.
 """
 try:
 repo = self._get_repo
 # Create PR in thread pool (blocking call)
 pr = await asyncio.to_thread(
 repo.create_pull,
 title=request.title,
 body=request.description,
 head=request.source_branch,
 base=request.target_branch,
 )
 # Add reviewers if specified
 if request.reviewer_usernames:
 try:
 await asyncio.to_thread(
 pr.create_review_request,
 reviewers=request.reviewer_usernames,
 )
 logger.info(
 "github_reviewers_added",
 pr_number=pr.number,
 reviewers=request.reviewer_usernames,
 )
 except GithubException as e:
 # Log warning but don't fail - PR was created successfully
 logger.warning(
 "github_add_reviewers_failed",
 pr_number=pr.number,
 reviewers=request.reviewer_usernames,
 error=str(e),
 )
 # Check for merge conflicts
 # Note: mergeable may be None initially while GitHub calculates it
 has_conflicts = pr.mergeable is False
 logger.info(
 "github_pr_created",
 pr_number=pr.number,
 pr_url=pr.html_url,
 has_conflicts=has_conflicts,
 mergeable=pr.mergeable,
 )
 return MRCreateResult(
 success=True,
 mr_url=pr.html_url,
 mr_id=str(pr.number),
 has_conflicts=has_conflicts,
 )
 except GithubException as e:
 error_msg = str(e)
 logger.error(
 "github_pr_creation_failed",
 owner=self.owner,
 repo=self.repo_name,
 source=request.source_branch,
 target=request.target_branch,
 error=error_msg,
 )
 return MRCreateResult(success=False, error=error_msg)
 except Exception as e:
 error_msg = f"Unexpected error: {e}"
 logger.error(
 "github_pr_creation_error",
 owner=self.owner,
 repo=self.repo_name,
 error=error_msg,
 )
 return MRCreateResult(success=False, error=error_msg)
 async def get_merge_request_diff(
 self,
 mr_id: str,
 max_files: int = 50,
 max_diff_lines: int = 500,
 ) -> MRDiffResult:
 """获取 GitHub PR 的文件变更 diff。
 Args:
 mr_id: PR 编号
 max_files: 最大文件数限制
 max_diff_lines: 单个文件 diff 最大行数
 Returns:
 MRDiffResult 包含文件列表和 diff 内容
 """
 try:
 repo = self._get_repo
 pr = await asyncio.to_thread(repo.get_pull, int(mr_id))
 raw_files = await asyncio.to_thread(lambda: list(pr.get_files))
 truncated = False
 # 截断文件数量
 if len(raw_files) > max_files:
 raw_files = raw_files[:max_files]
 truncated = True
 files: list[MRDiffFile] =
 for f in raw_files:
 diff_text: str = f.patch or ""
 # 截断单个文件 diff 行数
 diff_lines = diff_text.split("\n")
 if len(diff_lines) > max_diff_lines:
 diff_text = "\n".join(diff_lines[:max_diff_lines]) + "\n[diff truncated]"
 truncated = True
 # 判断文件状态
 status: str = f.status or ""
 new_file = status == "added"
 renamed_file = status == "renamed"
 deleted_file = status == "removed"
 # GitHub renamed 文件有 previous_filename
 old_path = f.previous_filename if renamed_file and f.previous_filename else f.filename
 files.append(
 MRDiffFile(
 old_path=old_path,
 new_path=f.filename,
 diff=diff_text,
 new_file=new_file,
 renamed_file=renamed_file,
 deleted_file=deleted_file,
 )
 )
 logger.info(
 "github_pr_diff_fetched",
 pr_number=mr_id,
 files_count=len(files),
 truncated=truncated,
 )
 return MRDiffResult(success=True, files=files, truncated=truncated)
 except GithubException as e:
 error_msg = f"Failed to fetch PR diff: {e}"
 logger.error(
 "github_pr_diff_error",
 pr_number=mr_id,
 owner=self.owner,
 repo=self.repo_name,
 error=error_msg,
 )
 return MRDiffResult(success=False, error=error_msg)
 except Exception as e:
 error_msg = f"Unexpected error fetching PR diff: {e}"
 logger.error(
 "github_pr_diff_error",
 pr_number=mr_id,
 owner=self.owner,
 repo=self.repo_name,
 error=error_msg,
 )
 return MRDiffResult(success=False, error=error_msg)
