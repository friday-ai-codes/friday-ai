"""Git operations for task container.
每次任务执行都使用临时目录克隆仓库，完成后清理。
不再使用 repos 缓存，简化状态管理。
"""
import os
import shutil
import tempfile
from pathlib import Path
import structlog
from git import Repo
from git.exc import GitCommandError
from .config import TaskConfig
logger = structlog.get_logger
class GitOperations:
 """Handle Git operations for task execution.
 使用临时目录进行 Git 操作，任务完成后清理。
 """
 def __init__(self, config: TaskConfig):
 """Initialize Git operations with config."""
 self.config = config
 # 使用临时目录而非固定路径
 self._temp_dir: str | None = None
 self.workspace: Path | None = None
 self.repo: Repo | None = None
 self._ssh_key_file: str | None = None
 def _mask_url(self, url: str) -> str:
 """遮蔽 URL 中的敏感信息（如 token）用于日志输出."""
 import re
 # 匹配 https://host 或 https://token@host 格式
 masked = re.sub(r"(https?://)[^@]+@", r"\1***@", url)
 return masked
 async def setup(self) -> None:
 """Set up Git authentication and clone repository to temp directory."""
 print("[DEBUG] GitOperations.setup starting", flush=True)
 log = logger.bind(task_id=self.config.task_id, repo_url=self.config.git_repo_url)
 # 创建临时目录
 self._temp_dir = tempfile.mkdtemp(prefix=f"friday-task-{self.config.task_id}-")
 self.workspace = Path(self._temp_dir)
 print(f"[DEBUG] Created temporary workspace: {self._temp_dir}", flush=True)
 log.info("Created temporary workspace", workspace=self._temp_dir)
 # 配置 SSL 验证（用于处理自签名证书的内部 Git 服务器）
 if not self.config.git_ssl_verify:
 os.environ["GIT_SSL_NO_VERIFY"] = "true"
 print("[DEBUG] SSL verification disabled", flush=True)
 log.warning("SSL verification disabled for Git operations")
 # Set up authentication
 # 优先使用显式指定的认证类型，否则自动检测
 auth_type = self.config.git_auth_type
 print(
 f"[DEBUG] Git auth_type={auth_type}, has_token={bool(self.config.git_access_token)}, token_len={len(self.config.git_access_token) if self.config.git_access_token else 0}",
 flush=True,
 )
 log.info(
 "Git authentication configuration",
 auth_type=auth_type,
 has_ssh_key=bool(self.config.git_ssh_key),
 has_access_token=bool(self.config.git_access_token),
 access_token_length=len(self.config.git_access_token)
 if self.config.git_access_token
 else 0,
 )
 print(
 f"[DEBUG] Checking auth conditions: auth_type='{auth_type}', auth_type=='ssh'={auth_type == 'ssh'}, auth_type=='token'={auth_type == 'token'}",
 flush=True,
 )
 print(
 f"[DEBUG] has_ssh_key={bool(self.config.git_ssh_key)}, has_access_token={bool(self.config.git_access_token)}",
 flush=True,
 )
 if auth_type == "ssh" and self.config.git_ssh_key:
 print("[DEBUG] Setting up SSH authentication", flush=True)
 log.info("Setting up SSH authentication")
 await self._setup_ssh_auth
 print("[DEBUG] SSH authentication configured successfully", flush=True)
 log.info("SSH authentication configured successfully")
 elif auth_type == "token" and self.config.git_access_token:
 print("[DEBUG] Setting up token authentication", flush=True)
 log.info("Setting up token authentication (explicit auth_type=token)")
 await self._setup_token_auth
 print("[DEBUG] Token authentication configured successfully", flush=True)
 log.info("Token authentication configured successfully")
 elif self.config.git_access_token:
 # 自动检测：如果有 access_token 但 auth_type 没有明确设置为 token
 log.info(
 "Auto-detecting token auth (access_token provided without explicit auth_type=token)"
 )
 await self._setup_token_auth
 log.info("Token authentication configured successfully (auto-detected)")
 elif self.config.git_ssh_key:
 # 自动检测：如果有 ssh_key 但 auth_type 没有明确设置为 ssh
 log.info("Auto-detecting SSH auth (ssh_key provided without explicit auth_type=ssh)")
 await self._setup_ssh_auth
 log.info("SSH authentication configured successfully (auto-detected)")
 else:
 log.warning("No Git credentials provided, clone may fail for private repos")
 # 总是克隆仓库（使用 shallow clone 加速）
 print(f"[DEBUG] Starting repository clone to {self.workspace}", flush=True)
 print(f"[DEBUG] Using URL: {self._mask_url(self.config.git_repo_url)}", flush=True)
 log.info(
 "Starting repository clone (shallow clone)",
 repo_url_masked=self._mask_url(self.config.git_repo_url),
 )
 try:
 await self._clone_repo
 print("[DEBUG] Repository cloned successfully", flush=True)
 log.info("Repository cloned successfully")
 except Exception as e:
 print(f"[ERROR] Clone failed: {e}", flush=True)
 raise
 # Checkout the target branch
 print("[DEBUG] Checking out target branch", flush=True)
 await self._checkout_branch
 print("[DEBUG] Branch checkout completed", flush=True)
 print("[DEBUG] Git setup complete!", flush=True)
 log.info("Git setup complete", branch=self.config.git_branch)
 async def _setup_ssh_auth(self) -> None:
 """Set up SSH key authentication.
 SSH 密钥通过环境变量传入（已解密），写入临时文件使用。
 """
 # Write SSH key to temporary file
 with tempfile.NamedTemporaryFile(mode="w", suffix="_id_rsa", delete=False) as f:
 f.write(self.config.git_ssh_key)
 self._ssh_key_file = f.name
 os.chmod(self._ssh_key_file, 0o600)
 # Configure Git to use this SSH key
 ssh_command = f"ssh -i {self._ssh_key_file} -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null"
 os.environ["GIT_SSH_COMMAND"] = ssh_command
 logger.info("SSH authentication configured")
 def _convert_ssh_to_https(self, url: str) -> str:
 """将 SSH 格式的 Git URL 转换为 HTTPS 格式。
 支持的格式：
 - git@github.com:org/repo.git -> https://github.com/org/repo.git
 - git@gitlab.example.com:group/project.git -> https://gitlab.example.com/group/project.git
 Args:
 url: SSH 格式的 Git URL
 Returns:
 HTTPS 格式的 Git URL
 """
 import re
 # 匹配 SSH URL: git@host:path.git 或 git@host:path
 ssh_pattern = r"^git@([^:]+):(.+?)(?:\.git)?$"
 match = re.match(ssh_pattern, url)
 if match:
 host = match.group(1)
 path = match.group(2)
 # 确保路径以 .git 结尾
 if not path.endswith(".git"):
 path = f"{path}.git"
 return f"https://{host}/{path}"
 return url
 async def _setup_token_auth(self) -> None:
 """Set up access token authentication.
 如果 URL 是 SSH 格式，会自动转换为 HTTPS 格式以支持 token 认证。
 """
 url = self.config.git_repo_url
 # 如果是 SSH URL，转换为 HTTPS
 if url.startswith("git@"):
 original_url = url
 url = self._convert_ssh_to_https(url)
 logger.info(
 "Converted SSH URL to HTTPS for token auth",
 original=original_url,
 converted=url,
 )
 # 对于 HTTPS URLs，嵌入 token
 # 转换: https://github.com/org/repo.git
 # 为: https://github.com/org/repo.git (GitLab 格式)
 # 或: https://token@github.com/org/repo.git (GitHub 格式)
 if url.startswith("https://"):
 host_part = url[8:] # 移除 'https://'
 # 检测是否是 GitLab（使用 oauth2:token 格式）
 # GitHub、Gitea 等可以直接使用 token@host 格式
 if "gitlab" in host_part.lower:
 self.config.git_repo_url = (
 f"https://oauth2:{self.config.git_access_token}@{host_part}"
 )
 else:
 self.config.git_repo_url = f"https://{self.config.git_access_token}@{host_part}"
 else:
 logger.warning(
 "URL is not HTTPS and cannot use token auth",
 url=url,
 )
 raise ValueError(f"无法使用访问令牌认证：URL '{url}' 不是有效的 HTTPS 或 SSH 格式")
 logger.info("Token authentication configured")
 async def _clone_repo(self) -> None:
 """Clone the repository using shallow clone."""
 if not self.workspace:
 raise RuntimeError("Workspace not initialized")
 try:
 # 使用 shallow clone (depth=1) 加速克隆
 self.repo = Repo.clone_from(
 self.config.git_repo_url,
 self.workspace,
 branch=self.config.git_branch,
 depth=1, # Shallow clone
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
 # 对于 shallow clone，分支已经在克隆时指定
 # 这里主要是确保在正确的分支上
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
 # Create and checkout new branch
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
 # Add all changes
 self.repo.git.add("--all")
 # Check if there are changes to commit
 if not self.repo.is_dirty and not self.repo.untracked_files:
 logger.info("No changes to commit")
 return None
 # Commit
 commit = self.repo.index.commit(message)
 logger.info("Committed changes", commit_sha=commit.hexsha[:8], message=message)
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
 # Get diff statistics
 diff = self.repo.git.diff("--stat")
 return diff if diff else "No changes"
 except GitCommandError as e:
 logger.error("Failed to get diff", error=str(e))
 return "Unable to get diff"
 def cleanup(self) -> None:
 """Clean up temporary files and directories.
 删除临时 SSH 密钥文件和临时工作目录。
 """
 # 清理 SSH 密钥文件
 if self._ssh_key_file and os.path.exists(self._ssh_key_file):
 try:
 os.unlink(self._ssh_key_file)
 logger.info("Cleaned up SSH key file")
 except OSError as e:
 logger.warning("Failed to delete SSH key file", error=str(e))
 self._ssh_key_file = None
 # 清理临时工作目录
 if self._temp_dir and os.path.exists(self._temp_dir):
 try:
 shutil.rmtree(self._temp_dir)
 logger.info("Cleaned up temporary workspace", workspace=self._temp_dir)
 except OSError as e:
 logger.warning("Failed to delete temp workspace", error=str(e))
 self._temp_dir = None
 self.workspace = None
 def get_workspace_path(self) -> Path:
 """Get the workspace path for Claude Code to work in."""
 if not self.workspace:
 raise RuntimeError("Workspace not initialized. Call setup first.")
 return self.workspace
