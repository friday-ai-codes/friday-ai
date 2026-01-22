"""Git operations for task container.
每次任务执行都使用临时目录克隆仓库，完成后清理。
不再使用 repos 缓存，简化状态管理。
"""
import os
import shutil
import tempfile
from pathlib import Path
import structlog
from git import Actor, Repo
from git.exc import GitCommandError
from core.config import TaskConfig
logger = structlog.get_logger
class GitOperations:
 """Handle Git operations for task execution.
 使用临时目录进行 Git 操作，任务完成后清理。
 """
 def __init__(self, config: TaskConfig):
 """Initialize Git operations with config."""
 self.config = config
 self._temp_dir: str | None = None
 self.workspace: Path | None = None
 self.repo: Repo | None = None
 self._ssh_key_file: str | None = None
 def _mask_url(self, url: str) -> str:
 """遮蔽 URL 中的敏感信息（如 token）用于日志输出."""
 import re
 masked = re.sub(r"(https?://)[^@]+@", r"\1***@", url)
 return masked
 async def setup(self) -> None:
 """Set up Git authentication and clone repository to temp directory."""
 log = logger.bind(task_id=self.config.task_id, repo_url=self.config.git_repo_url)
 # 创建临时目录
 self._temp_dir = tempfile.mkdtemp(prefix=f"friday-task-{self.config.task_id}-")
 self.workspace = Path(self._temp_dir)
 log.info("Created temporary workspace", workspace=self._temp_dir)
 # 配置 SSL 验证
 if not self.config.git_ssl_verify:
 os.environ["GIT_SSL_NO_VERIFY"] = "true"
 log.warning("SSL verification disabled for Git operations")
 # Set up authentication
 auth_type = self.config.git_auth_type
 if auth_type == "ssh" and self.config.git_ssh_key:
 await self._setup_ssh_auth
 elif auth_type == "token" and self.config.git_access_token:
 await self._setup_token_auth
 elif self.config.git_access_token:
 await self._setup_token_auth
 elif self.config.git_ssh_key:
 await self._setup_ssh_auth
 else:
 log.warning("No Git credentials provided, clone may fail for private repos")
 # Clone repository
 log.info("Starting repository clone", repo_url_masked=self._mask_url(self.config.git_repo_url))
 await self._clone_repo
 await self._checkout_branch
 log.info("Git setup complete", branch=self.config.git_branch)
 async def _setup_ssh_auth(self) -> None:
 """Set up SSH key authentication."""
 with tempfile.NamedTemporaryFile(mode="w", suffix="_id_rsa", delete=False) as f:
 f.write(self.config.git_ssh_key)
 self._ssh_key_file = f.name
 os.chmod(self._ssh_key_file, 0o600)
 ssh_command = f"ssh -i {self._ssh_key_file} -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null"
 os.environ["GIT_SSH_COMMAND"] = ssh_command
 logger.info("SSH authentication configured")
 def _convert_ssh_to_https(self, url: str) -> str:
 """将 SSH 格式的 Git URL 转换为 HTTPS 格式。"""
 import re
 ssh_pattern = r"^git@([^:]+):(.+?)(?:\.git)?$"
 match = re.match(ssh_pattern, url)
 if match:
 host = match.group(1)
 path = match.group(2)
 if not path.endswith(".git"):
 path = f"{path}.git"
 return f"https://{host}/{path}"
 return url
 async def _setup_token_auth(self) -> None:
 """Set up access token authentication."""
 url = self.config.git_repo_url
 if url.startswith("git@"):
 url = self._convert_ssh_to_https(url)
 logger.info("Converted SSH URL to HTTPS for token auth")
 if url.startswith("https://"):
 host_part = url[8:]
 if "gitlab" in host_part.lower:
 self.config.git_repo_url = f"https://oauth2:{self.config.git_access_token}@{host_part}"
 else:
 self.config.git_repo_url = f"https://{self.config.git_access_token}@{host_part}"
 else:
 raise ValueError(f"无法使用访问令牌认证：URL '{url}' 不是有效的 HTTPS 或 SSH 格式")
 logger.info("Token authentication configured")
 async def _clone_repo(self) -> None:
 """Clone the repository using shallow clone."""
 if not self.workspace:
 raise RuntimeError("Workspace not initialized")
 try:
 self.repo = Repo.clone_from(
 self.config.git_repo_url,
 self.workspace,
 branch=self.config.git_branch,
 depth=1,
 )
 except GitCommandError as e:
 logger.error("Failed to clone repository", error=str(e))
 raise
 async def _checkout_branch(self) -> None:
 """Checkout the target branch."""
 if not self.repo:
 if not self.workspace:
 raise RuntimeError("Workspace not initialized")
 self.repo = Repo(self.workspace)
 try:
 if self.config.git_branch in self.repo.heads:
 self.repo.heads[self.config.git_branch].checkout
 except GitCommandError as e:
 logger.error("Failed to checkout branch", error=str(e))
 raise
 async def create_feature_branch(self, branch_name: str) -> str:
 """Create a new feature branch for the task."""
 if not self.repo:
 if not self.workspace:
 raise RuntimeError("Workspace not initialized")
 self.repo = Repo(self.workspace)
 full_branch_name = f"friday/{branch_name}"
 try:
 new_branch = self.repo.create_head(full_branch_name)
 new_branch.checkout
 logger.info("Created feature branch", branch=full_branch_name)
 return full_branch_name
 except GitCommandError as e:
 logger.error("Failed to create feature branch", error=str(e))
 raise
 async def commit_changes(self, message: str) -> str | None:
 """Commit all changes with the given message."""
 if not self.repo:
 if not self.workspace:
 raise RuntimeError("Workspace not initialized")
 self.repo = Repo(self.workspace)
 try:
 self.repo.git.add("--all")
 if not self.repo.is_dirty and not self.repo.untracked_files:
 logger.info("No changes to commit")
 return None
 # 在代码里指定 author，不依赖全局 git config
 commit = self.repo.index.commit(
 message,
 author=Actor("Friday Codes AI Agent", "ai@friday.codes"),
 committer=Actor("Friday Codes AI Agent", "ai@friday.codes"),
 )
 logger.info("Committed changes", commit_sha=commit.hexsha[:8])
 return commit.hexsha
 except GitCommandError as e:
 logger.error("Failed to commit changes", error=str(e))
 raise
 async def push_branch(self, branch_name: str) -> None:
 """Push branch to remote."""
 if not self.repo:
 if not self.workspace:
 raise RuntimeError("Workspace not initialized")
 self.repo = Repo(self.workspace)
 try:
 origin = self.repo.remotes.origin
 origin.push(branch_name, set_upstream=True)
 logger.info("Pushed branch", branch=branch_name)
 except GitCommandError as e:
 logger.error("Failed to push branch", error=str(e))
 raise
 async def get_diff_summary(self) -> str:
 """Get a summary of current changes."""
 if not self.repo:
 if not self.workspace:
 raise RuntimeError("Workspace not initialized")
 self.repo = Repo(self.workspace)
 try:
 diff = self.repo.git.diff("--stat")
 return diff if diff else "No changes"
 except GitCommandError as e:
 logger.error("Failed to get diff", error=str(e))
 return "Unable to get diff"
 def cleanup(self) -> None:
 """Clean up temporary files and directories."""
 if self._ssh_key_file and os.path.exists(self._ssh_key_file):
 try:
 os.unlink(self._ssh_key_file)
 except OSError:
 pass
 self._ssh_key_file = None
 if self._temp_dir and os.path.exists(self._temp_dir):
 try:
 shutil.rmtree(self._temp_dir)
 except OSError:
 pass
 self._temp_dir = None
 self.workspace = None
 def get_workspace_path(self) -> Path:
 """Get the workspace path for Claude Code to work in."""
 if not self.workspace:
 raise RuntimeError("Workspace not initialized. Call setup first.")
 return self.workspace
