"""Git operations for task container.

每次任务执行都使用临时目录克隆仓库，完成后清理。
不再使用 repos 缓存，简化状态管理。
"""

import asyncio
import os
import shutil
import tempfile
from pathlib import Path
from urllib.parse import quote

import structlog
from git import Actor, PushInfo, Repo
from git.exc import GitCommandError
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

from core.config import TaskConfig
from core.exceptions import ExploreModeForbiddenError

logger = structlog.get_logger()


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

    def _check_explore_guard(self, operation: str) -> None:
        """检查 explore/repo_summary 模式守卫，写操作时抛出异常。"""
        if self.config.task_mode in ("explore", "repo_summary"):
            logger.warning(
                "explore_mode_write_blocked",
                operation=operation,
                task_id=self.config.task_id,
                mode=self.config.task_mode,
            )
            raise ExploreModeForbiddenError(operation)

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

        # Configure Proxy
        if self.config.git_http_proxy:
            os.environ["http_proxy"] = self.config.git_http_proxy
            os.environ["https_proxy"] = self.config.git_http_proxy
            # Also set lower case versions just in case
            os.environ["HTTP_PROXY"] = self.config.git_http_proxy
            os.environ["HTTPS_PROXY"] = self.config.git_http_proxy
            log.info("Git proxy configured", proxy=self.config.git_http_proxy)

        # Set up authentication
        auth_type = self.config.git_auth_type

        if auth_type == "ssh" and self.config.git_ssh_key:
            await self._setup_ssh_auth()
        elif auth_type == "token" and self.config.git_access_token:
            await self._setup_token_auth()
        elif self.config.git_access_token:
            await self._setup_token_auth()
        elif self.config.git_ssh_key:
            await self._setup_ssh_auth()
        else:
            log.warning("No Git credentials provided, clone may fail for private repos")

        # Clone repository
        log.info(
            "Starting repository clone", repo_url_masked=self._mask_url(self.config.git_repo_url)
        )
        await self._clone_repo()
        await self._checkout_branch()

        # Phase 22-04 / EXCL-02：clone+checkout 后按 exclude 规则物理删除被排除文件，使容器内
        # agent 不可见（T-22-13）。prune 跳过 .git/ 保护 git 元数据（T-22-15）；被排除文件持久
        # 删除失败 → ExclusionPruneError 向上传播使 setup 失败（fail-closed，T-22-16：宁可任务
        # 失败也绝不让 agent 看到被排除文件）。explore/repo_summary 模式同样 prune（agent 仍读文件）。
        from core.exclusion import prune_excluded

        pruned_count = prune_excluded(self.workspace, self.config.exclude_patterns)
        if pruned_count:
            log.info("exclusion_prune_complete", pruned_count=pruned_count)

        # Fail-closed：clone/checkout/prune 后工作区必须真的含仓库内容。
        # 历史 fail-open bug（repo_summary 把 Friday Task 自身当成目标仓库总结、却标
        # completed 的真凶）：当工作区除 .git 外为空（瞬时 git 失败 / 目标分支为空 /
        # 被 prune 删空）时，agent 走 bypassPermissions、没有文件系统沙箱，会 `ls /`
        # 越界到容器自身的 /app 代码生成张冠李戴的描述。这里在 setup 阶段就 fail-closed，
        # 让任务明确失败而非误导，胜过让 agent 在空工作区上自由发挥。
        self._assert_workspace_populated()

        log.info("Git setup complete", branch=self.config.git_branch)

    def _assert_workspace_populated(self) -> None:
        """校验克隆后的工作区确实含仓库工作树文件（除 .git 外非空），否则 fail-closed。"""
        if not self.workspace:
            raise RuntimeError("Workspace not initialized")
        entries = [p for p in self.workspace.iterdir() if p.name != ".git"]
        if not entries:
            raise RuntimeError(
                "Cloned workspace is empty (only .git present) for "
                f"{self._mask_url(self.config.git_repo_url)} @ {self.config.git_branch}; "
                "refusing to run agent on an empty workspace (fail-closed)。"
            )

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
            encoded_token = quote(self.config.git_access_token, safe="")
            if "gitlab" in host_part.lower():
                self.config.git_repo_url = (
                    f"https://oauth2:{encoded_token}@{host_part}"
                )
            else:
                self.config.git_repo_url = f"https://{encoded_token}@{host_part}"
        else:
            raise ValueError(f"无法使用访问令牌认证：URL '{url}' 不是有效的 HTTPS 或 SSH 格式")

        logger.info("Token authentication configured")

    # clone 重试参数：瞬时 DNS（"Name or service not known"）/ 连接（"Connection
    # refused"）失败在突发并发下（几百容器同时拉取打满 Docker 内嵌 DNS）零星出现。
    # 历史上 _clone_repo 无重试 → 单次瞬时失败即整任务失败；叠加 repo_summary
    # fail-open 还会被 agent 误当成"分析 /app"产出错误描述。这里加退避重试兜瞬时故障。
    _CLONE_MAX_ATTEMPTS = 3

    async def _clone_repo(self) -> None:
        """Clone the repository, using reference if available. 瞬时网络/DNS 失败自动重试。"""
        if not self.workspace:
            raise RuntimeError("Workspace not initialized")

        reference_path = self.config.git_reference_path
        last_error: GitCommandError | None = None

        for attempt in range(1, self._CLONE_MAX_ATTEMPTS + 1):
            try:
                if reference_path and os.path.exists(reference_path):
                    # Reference clone: 从本地 bare repo 获取对象，仅下载增量
                    # --dissociate 确保克隆后独立于 reference，可安全删除 reference
                    logger.info(
                        "using_reference_clone",
                        reference=reference_path,
                        repo_url_masked=self._mask_url(self.config.git_repo_url),
                        attempt=attempt,
                    )
                    self.repo = Repo.clone_from(
                        self.config.git_repo_url,
                        self.workspace,
                        branch=self.config.git_branch,
                        reference=reference_path,
                        dissociate=True,
                    )
                else:
                    # Fallback: shallow clone
                    logger.info(
                        "using_shallow_clone",
                        repo_url_masked=self._mask_url(self.config.git_repo_url),
                        attempt=attempt,
                    )
                    self.repo = Repo.clone_from(
                        self.config.git_repo_url,
                        self.workspace,
                        branch=self.config.git_branch,
                        depth=1,
                    )
                return
            except GitCommandError as e:
                last_error = e
                logger.warning(
                    "clone_attempt_failed",
                    attempt=attempt,
                    max_attempts=self._CLONE_MAX_ATTEMPTS,
                    error=str(e),
                )
                # Repo.clone_from 要求目标目录为空：失败可能残留半成品，重试前清空。
                self._reset_workspace_dir()
                if attempt < self._CLONE_MAX_ATTEMPTS:
                    await asyncio.sleep(min(2 ** (attempt - 1), 8))

        logger.error("Failed to clone repository", error=str(last_error))
        assert last_error is not None
        raise last_error

    def _reset_workspace_dir(self) -> None:
        """清空工作区目录内容（保留目录本身），供 clone 重试前复位。"""
        if not self.workspace or not self.workspace.exists():
            return
        for child in self.workspace.iterdir():
            try:
                if child.is_dir() and not child.is_symlink():
                    shutil.rmtree(child, ignore_errors=True)
                else:
                    child.unlink(missing_ok=True)
            except OSError:
                pass

    async def _checkout_branch(self) -> None:
        """Checkout the target branch."""
        if not self.repo:
            if not self.workspace:
                raise RuntimeError("Workspace not initialized")
            self.repo = Repo(self.workspace)

        try:
            if self.config.git_branch in self.repo.heads:
                self.repo.heads[self.config.git_branch].checkout()
        except GitCommandError as e:
            logger.error("Failed to checkout branch", error=str(e))
            raise

    async def create_feature_branch(self, branch_name: str) -> str:
        """Create a new feature branch for the task."""
        self._check_explore_guard("create_feature_branch")
        if not self.repo:
            if not self.workspace:
                raise RuntimeError("Workspace not initialized")
            self.repo = Repo(self.workspace)

        full_branch_name = f"friday/{branch_name}"

        try:
            new_branch = self.repo.create_head(full_branch_name)
            new_branch.checkout()
            logger.info("Created feature branch", branch=full_branch_name)
            return full_branch_name
        except GitCommandError as e:
            logger.error("Failed to create feature branch", error=str(e))
            raise

    async def commit_changes(self, message: str) -> str | None:
        """Commit all changes with the given message."""
        self._check_explore_guard("commit_changes")
        if not self.repo:
            if not self.workspace:
                raise RuntimeError("Workspace not initialized")
            self.repo = Repo(self.workspace)

        try:
            self.repo.git.add("--all")

            if not self.repo.is_dirty() and not self.repo.untracked_files:
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

    # 错误标志位掩码：GitPython 的 ``PushInfo.flags`` 是位字段，
    # 任何一位被置位都代表 push 被远端拒绝或失败。
    _PUSH_ERROR_MASK = (
        PushInfo.ERROR
        | PushInfo.REJECTED
        | PushInfo.REMOTE_REJECTED
        | PushInfo.REMOTE_FAILURE
    )

    async def push_branch(self, branch_name: str) -> None:
        """Push branch to remote.

        历史 bug（implementation 多次容器跑完后代码丢失的真凶）：原实现只 try
        ``origin.push(...)`` 加 ``except GitCommandError``。**GitPython 的
        ``origin.push()`` 不会因为 push 被远端拒绝而抛 ``GitCommandError``** —
        它返回 ``list[PushInfo]``，错误以位掩码形式存在 ``info.flags``（
        ``ERROR`` / ``REJECTED`` / ``REMOTE_REJECTED`` / ``REMOTE_FAILURE``）。
        漏掉这一步显式检查的结果：push 实际失败（token 失效 / hook 拒绝 /
        forbidden 推送保护分支等）也会被当成成功，``logger.info("Pushed branch")``
        正常输出，上层 ``push_branch_with_retry`` 也不会重试，``_run_execute_mode``
        继续往下走调 ``report_push_complete`` / ``report_completed`` 全链路误报
        success；容器关闭后本地 commit 全部丢失，GitLab 上完全没有任何分支或
        commit 的痕迹。改为读取 ``PushInfo.flags`` 把错误位翻成 ``GitCommandError``
        让上层 retry 机制和异常处理路径正常工作。
        """
        self._check_explore_guard("push_branch")
        if not self.repo:
            if not self.workspace:
                raise RuntimeError("Workspace not initialized")
            self.repo = Repo(self.workspace)

        try:
            origin = self.repo.remotes.origin
            # 使用 --force-with-lease 兜底：编码分支是 Friday 任务专用工作分支，
            # 重跑同一技术方案 / 远端残留旧同名分支时，普通 push 会被 non-fast-forward
            # 拒绝（历史 bug）。--force-with-lease 以「fetch 到的 remote-tracking ref」
            # 为预期值覆盖：自己 setup 时 fetch 的基线被覆盖是预期的；但若期间被
            # 其它进程推进（remote 与预期不符）仍会安全拒绝，不会盲目冲掉他人提交。
            push_infos = origin.push(
                branch_name, set_upstream=True, force_with_lease=True
            )
        except GitCommandError as e:
            logger.error("Failed to push branch", error=str(e))
            raise

        # 显式校验 PushInfo.flags —— GitPython 的契约要求 caller 自己检查。
        failures = [pi for pi in push_infos if pi.flags & self._PUSH_ERROR_MASK]
        if failures:
            summary = "; ".join(
                f"flags={pi.flags} summary={(pi.summary or '').strip()!r}"
                for pi in failures
            )
            logger.error(
                "Branch push rejected by remote",
                branch=branch_name,
                failures=summary,
            )
            raise GitCommandError(
                ["git", "push", "origin", branch_name],
                128,
                stderr=summary.encode("utf-8"),
            )

        logger.info(
            "Pushed branch",
            branch=branch_name,
            pushes=[(pi.summary or "").strip() for pi in push_infos],
        )

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=10),
        retry=retry_if_exception_type(GitCommandError),
        reraise=True,
    )
    async def push_branch_with_retry(self, branch_name: str) -> None:
        """Push branch with exponential backoff retry (2s, 4s, 8s delays)."""
        self._check_explore_guard("push_branch_with_retry")
        logger.info("Pushing branch", branch=branch_name, attempt="with retry")
        await self.push_branch(branch_name)

    async def get_modified_files(self, base_branch: str | None = None) -> list[str]:
        """Get list of files modified in current branch vs base."""
        if not self.repo:
            return []
        try:
            target = base_branch or self.config.git_branch
            diff = self.repo.git.diff("--name-only", f"origin/{target}...HEAD")
            return [f.strip() for f in diff.split("\n") if f.strip()]
        except GitCommandError:
            return []
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
            raise RuntimeError("Workspace not initialized. Call setup() first.")
        return self.workspace

    async def ensure_current_branch(self, expected_branch: str) -> bool:
        """确认 Claude 执行后仍停留在 Runner 准备好的任务分支上。"""
        self._check_explore_guard("ensure_current_branch")
        if not self.repo:
            raise RuntimeError("Repository not initialized. Call setup() first.")
        current_branch = self.repo.active_branch.name
        if current_branch == expected_branch:
            return True
        logger.error(
            "task_branch_drift_detected",
            expected_branch=expected_branch,
            current_branch=current_branch,
        )
        return False

    async def restore_task_branch(self, expected_branch: str) -> bool:
        """在 commit 前强制回到 Runner 准备好的任务分支。

        防御纵深：即便 Claude 通过其它途径（hooks / setup script / 用户脚本）
        切走了 HEAD，commit 之前也要先 checkout 回 expected_branch；如果回不去
        （分支不存在 / repo 状态异常）就返回 False，由 caller 决定如何报错。
        当前工作区里的未提交改动会随分支切换一起带过去，确保 Claude 的修改不会
        被丢到错误分支上提交。
        """
        self._check_explore_guard("restore_task_branch")
        if not self.repo:
            raise RuntimeError("Repository not initialized. Call setup() first.")

        current_branch = self.repo.active_branch.name
        if current_branch == expected_branch:
            return True

        try:
            self.repo.git.checkout(expected_branch)
            logger.warning(
                "restored_task_branch",
                expected_branch=expected_branch,
                previous_branch=current_branch,
            )
            return True
        except GitCommandError as e:
            logger.error(
                "restore_task_branch_failed",
                expected_branch=expected_branch,
                previous_branch=current_branch,
                error=str(e),
            )
            return False

    async def setup_task_branch(self, branch_strategy: str | None, task_id: str) -> str:
        """Create or checkout branch based on branch_strategy.

        Args:
            branch_strategy: Branch name pattern or explicit name.
                            Supports {task_id} placeholder.
                            If None, uses default: friday/task-{task_id}
            task_id: Task ID for placeholder substitution

        Returns:
            The actual branch name created/checked out

        历史 bug（implementation 之后暴露）：原实现末尾强制对所有分支名拼
        ``friday/`` 前缀（"Normalize: ensure friday/ prefix if not present"），
        是早期 Friday 还在用 ``friday/task-{task_id}`` 唯一命名时的兜底。implementation 引入模板分支名（``feat20260519.xxx`` / ``fix20260519.xxx``）后，
        server 端通过 ``FRIDAY_TASK_BRANCH_STRATEGY`` 把模板名传进容器，但
        Runner 这里把 ``fix20260519.study-app-page-apps-favorites`` 静默改成
        ``friday/fix20260519.study-app-page-apps-favorites`` —— 跟 server 端
        校验/记录的分支名完全不一致，GitLab 上的分支名也错位。改为严格尊重
        显式传入的 ``branch_strategy`` 字面值，仅在 caller 不传时落到
        ``friday/task-{task_id}`` 默认值。
        """
        self._check_explore_guard("setup_task_branch")
        if not self.repo:
            raise RuntimeError("Repository not initialized. Call setup() first.")

        # Determine branch name
        if branch_strategy:
            branch_name = branch_strategy.replace("{task_id}", task_id)
        else:
            branch_name = f"friday/task-{task_id}"

        # Check if branch exists remotely
        try:
            self.repo.git.fetch("origin", branch_name)
            # Branch exists remotely; create/reset a local tracking branch from origin.
            self.repo.git.checkout("-B", branch_name, f"origin/{branch_name}")
            logger.info("Checked out existing branch", branch=branch_name)
        except GitCommandError:
            # Branch doesn't exist, create new
            new_branch = self.repo.create_head(branch_name)
            new_branch.checkout()
            logger.info("Created new task branch", branch=branch_name)

        return branch_name
