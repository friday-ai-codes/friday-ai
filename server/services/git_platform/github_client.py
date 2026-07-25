"""GitHub client implementation for PR operations."""

import asyncio
from datetime import timezone as dt_timezone

import structlog
from django.utils import timezone as dj_timezone
from github import Auth, Github, GithubException

from .base import GitPlatformClient, truncate_diff_lines
from .models import (
    BranchCompareResult,
    CompareFileEntry,
    MergeRequestLookupFailed,
    MRCreateRequest,
    MRCreateResult,
    MRDiffFile,
    MRDiffResult,
    MRMetadataResult,
)

logger = structlog.get_logger()


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
        gh = self._get_client()
        return gh.get_repo(f"{self.owner}/{self.repo_name}")

    async def get_user_id_by_username(self, username: str) -> int | None:
        """Resolve GitHub username to user ID.

        Args:
            username: GitHub username to look up.

        Returns:
            User ID if found, None otherwise.
        """
        try:
            gh = self._get_client()
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
            repo = self._get_repo()
            await asyncio.to_thread(repo.get_branch, branch_name)
            return True
        except GithubException:
            return False

    async def find_open_merge_request(
        self, source_branch: str, target_branch: str
    ) -> MRCreateResult | None:
        """查 GitHub 同 source→target 的 open PR（IDEMP-02 reuse-first fence）。

        包装 ``repo.get_pulls(state="open", head=f"{owner}:{source}", base=target)``，
        命中首个 → 复用其 html_url/number；空 → None；平台异常 fail-soft 返回 None
        （绝不上抛，让调用方照常尝试创建）。token 绝不入日志。

        Args:
            source_branch: 功能（变更侧）分支名。
            target_branch: 目标（base）分支名。

        Returns:
            命中 → MRCreateResult(success=True, mr_url=..., mr_id=...)；无/异常 → None。
        """
        try:
            repo = self._get_repo()
            pulls = await asyncio.to_thread(
                lambda: list(
                    repo.get_pulls(
                        state="open",
                        head=f"{self.owner}:{source_branch}",
                        base=target_branch,
                    )
                )
            )
            if not pulls:
                return None
            pr = pulls[0]
            logger.info(
                "github_open_pr_found",
                source=source_branch,
                target=target_branch,
                pr_number=pr.number,
            )
            return MRCreateResult(success=True, mr_url=pr.html_url, mr_id=str(pr.number))
        except GithubException as e:
            # token 绝不入日志，仅记分支与 error。
            # 这里刻意不再 fail-soft 返回 None：那会与「查了确实没有」混为一谈，
            # 让查重 API 一抖动就退化成重复建 PR。抛给调用方显式处理。
            logger.warning(
                "github_find_open_pr_failed",
                source=source_branch,
                target=target_branch,
                error=str(e),
            )
            raise MergeRequestLookupFailed(str(e)) from e
        except Exception as e:
            logger.warning(
                "github_find_open_pr_error",
                source=source_branch,
                target=target_branch,
                error=str(e),
            )
            raise MergeRequestLookupFailed(str(e)) from e

    async def create_merge_request(self, request: MRCreateRequest) -> MRCreateResult:
        """Create a GitHub pull request with optional reviewers.

        Args:
            request: PR creation parameters.

        Returns:
            MRCreateResult with success status, PR URL, or error details.
        """
        try:
            repo = self._get_repo()

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
            repo = self._get_repo()

            pr = await asyncio.to_thread(repo.get_pull, int(mr_id))
            raw_files = await asyncio.to_thread(lambda: list(pr.get_files()))

            truncated = False

            # 截断文件数量
            if len(raw_files) > max_files:
                raw_files = raw_files[:max_files]
                truncated = True

            files: list[MRDiffFile] = []
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
                old_path = (
                    f.previous_filename if renamed_file and f.previous_filename else f.filename
                )

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

    async def get_merge_request_metadata(self, mr_id: str) -> MRMetadataResult:
        """获取 GitHub PR 的 merge commit 元数据（HDIFF-01 历史 diff commit 锚定）。

        复用 get_merge_request_diff 同款 `repo.get_pull` 范式取 PR 对象，读取
        merge_commit_sha / base.ref（target_branch）/ head.ref（source_branch）/
        merged_at（PyGithub ≥2.0 返回 aware datetime；保留 naive→aware UTC 归一
        作为防线，兼容旧版/异常返回 naive 的情形）。GithubException / 通用异常各自
        降级返回 success=False，token 绝不入日志。

        Args:
            mr_id: PR 编号。

        Returns:
            MRMetadataResult：未合并时 merge_commit_sha 为空字符串。
        """
        try:
            repo = self._get_repo()
            pr = await asyncio.to_thread(repo.get_pull, int(mr_id))

            merged_at = pr.merged_at
            if merged_at is not None and dj_timezone.is_naive(merged_at):
                # stdlib timezone.utc：django.utils.timezone.utc 自 Django 5.0 已删除
                merged_at = dj_timezone.make_aware(merged_at, dt_timezone.utc)

            logger.info(
                "github_pr_metadata_fetched",
                pr_number=mr_id,
                has_merge_commit=bool(pr.merge_commit_sha),
                target_branch=pr.base.ref if pr.base else "",
            )

            return MRMetadataResult(
                success=True,
                merge_commit_sha=pr.merge_commit_sha or "",
                target_branch=pr.base.ref if pr.base else "",
                source_branch=pr.head.ref if pr.head else "",
                merged_at=merged_at,
            )
        except GithubException as e:
            error_msg = f"Failed to fetch PR metadata: {e}"
            logger.error(
                "github_pr_metadata_error",
                pr_number=mr_id,
                owner=self.owner,
                repo=self.repo_name,
                error=error_msg,
            )
            return MRMetadataResult(success=False, error=error_msg)
        except Exception as e:
            error_msg = f"Unexpected error fetching PR metadata: {e}"
            logger.error(
                "github_pr_metadata_error",
                pr_number=mr_id,
                owner=self.owner,
                repo=self.repo_name,
                error=error_msg,
            )
            return MRMetadataResult(success=False, error=error_msg)

    async def get_branch_diff(
        self,
        source_branch: str,
        target_branch: str,
        max_files: int = 50,
        max_diff_lines: int = 500,
    ) -> MRDiffResult:
        """获取分支级全量 diff 文本（GitHub 实现，skip-PR 兜底，KMOD-05）。

        包装 repo.compare(base=target, head=source) + file.patch；单文件超大时
        GitHub 不返回 patch 字段（A1 假设）→ 该文件 diff 置空 + truncated=True
        响亮降级，不本地兜底重拉。

        Args:
            source_branch: 功能（变更侧）分支名。
            target_branch: 目标（base）分支名。
            max_files: 最大文件数限制。
            max_diff_lines: 单个文件 diff 最大行数。

        Returns:
            MRDiffResult 包含文件列表和 diff 内容；异常时 success=False 不上抛。
        """
        try:
            repo = self._get_repo()

            # base=target, head=source，与 compare_branches 既有调用同序
            comparison = await asyncio.to_thread(repo.compare, target_branch, source_branch)

            raw_files = list(comparison.files or [])
            truncated = False

            # 截断文件数量
            if len(raw_files) > max_files:
                raw_files = raw_files[:max_files]
                truncated = True

            files: list[MRDiffFile] = []
            for f in raw_files:
                patch_text = getattr(f, "patch", None)
                if not patch_text:
                    # A1 降级：超大文件平台侧不带 patch → 空 diff + 响亮标记
                    diff_text = ""
                    truncated = True
                    logger.warning(
                        "github_branch_diff_patch_missing",
                        filename=f.filename,
                        source=source_branch,
                        target=target_branch,
                    )
                else:
                    diff_text, was_truncated = truncate_diff_lines(patch_text, max_diff_lines)
                    truncated = truncated or was_truncated

                # 判断文件状态
                status: str = f.status or ""
                new_file = status == "added"
                renamed_file = status == "renamed"
                deleted_file = status == "removed"

                # GitHub renamed 文件有 previous_filename
                old_path = (
                    f.previous_filename if renamed_file and f.previous_filename else f.filename
                )

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
                "github_branch_diff_fetched",
                source=source_branch,
                target=target_branch,
                files_count=len(files),
                truncated=truncated,
            )

            return MRDiffResult(success=True, files=files, truncated=truncated)

        except Exception as e:
            # 只记 str(exc) 与分支名，不记 client/token 对象（T-14-05）
            logger.warning(
                "github_branch_diff_error",
                source=source_branch,
                target=target_branch,
                error=str(e),
            )
            return MRDiffResult(success=False, error=str(e))

    async def compare_branches(
        self,
        source_branch: str,
        target_branch: str,
        max_files: int = 50,
    ) -> BranchCompareResult:
        """对比两个分支的差异（GitHub 实现）。

        使用 PyGithub repo.compare() 获取文件变更，当 behind_by > 0 时
        执行反向 compare 检测潜在冲突（文件路径交集）。

        Args:
            source_branch: 功能分支名。
            target_branch: 目标（base）分支名。
            max_files: 最大返回文件数。

        Returns:
            BranchCompareResult 包含文件变更统计和冲突推断。
        """
        try:
            repo = self._get_repo()

            # 正向 compare: target...source（显示 source 相对于 target 的变更）
            comparison = await asyncio.to_thread(repo.compare, target_branch, source_branch)

            # 提取文件列表
            raw_files = comparison.files or []
            truncated = False
            if len(raw_files) > max_files:
                raw_files = raw_files[:max_files]
                truncated = True

            total_additions = 0
            total_deletions = 0
            files: list[CompareFileEntry] = []

            for f in raw_files:
                entry = CompareFileEntry(
                    path=f.filename,
                    change_type=f.status,
                    additions=f.additions,
                    deletions=f.deletions,
                    old_path=f.previous_filename or "",
                )
                files.append(entry)
                total_additions += f.additions
                total_deletions += f.deletions

            # 冲突推断: 当 behind_by > 0 时执行反向 compare
            has_potential_conflicts = False
            conflicting_files: list[str] = []

            if comparison.behind_by > 0:
                reverse_comparison = await asyncio.to_thread(
                    repo.compare, source_branch, target_branch
                )
                forward_paths = {f.filename for f in comparison.files or []}
                reverse_paths = {f.filename for f in reverse_comparison.files or []}
                conflicting_files = sorted(forward_paths & reverse_paths)
                has_potential_conflicts = len(conflicting_files) > 0

            logger.info(
                "github_compare_branches",
                source=source_branch,
                target=target_branch,
                ahead_by=comparison.ahead_by,
                behind_by=comparison.behind_by,
                files_count=len(files),
                has_conflicts=has_potential_conflicts,
            )

            return BranchCompareResult(
                success=True,
                ahead_by=comparison.ahead_by,
                behind_by=comparison.behind_by,
                files=files,
                total_additions=total_additions,
                total_deletions=total_deletions,
                truncated=truncated,
                has_potential_conflicts=has_potential_conflicts,
                conflicting_files=conflicting_files,
            )

        except Exception as e:
            error_msg = str(e)
            logger.error(
                "github_compare_branches_error",
                source=source_branch,
                target=target_branch,
                error=error_msg,
            )
            return BranchCompareResult(success=False, error=error_msg)
