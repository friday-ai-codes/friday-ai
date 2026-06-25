"""GitLab client implementation for MR operations."""

import asyncio
from datetime import timezone as dt_timezone
from typing import Any

import gitlab
import structlog
from django.utils import timezone as dj_timezone
from django.utils.dateparse import parse_datetime

from .base import GitPlatformClient, truncate_diff_lines
from .models import (
    BranchCompareResult,
    CompareFileEntry,
    MRCreateRequest,
    MRCreateResult,
    MRDiffFile,
    MRDiffResult,
    MRMetadataResult,
)

logger = structlog.get_logger()


def _parse_diff_stats(diff_text: str) -> tuple[int, int]:
    """从 unified diff 文本中解析增删行数。

    遍历 diff 文本行，`+` 开头且非 `+++` 计为 addition，
    `-` 开头且非 `---` 计为 deletion。

    Args:
        diff_text: unified diff 文本。

    Returns:
        (additions, deletions) 元组。
    """
    additions = 0
    deletions = 0
    for line in diff_text.split("\n"):
        if line.startswith("+") and not line.startswith("+++"):
            additions += 1
        elif line.startswith("-") and not line.startswith("---"):
            deletions += 1
    return additions, deletions


class GitLabClient(GitPlatformClient):
    """GitLab platform client for merge request operations."""

    def __init__(self, base_url: str, token: str, project_path: str) -> None:
        """Initialize GitLab client.

        Args:
            base_url: GitLab instance URL (e.g., https://gitlab.com).
            token: GitLab personal access token.
            project_path: Space path (e.g., namespace/project).
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
            gl = self._get_client()
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
            gl = self._get_client()
            # Run blocking API call in thread pool
            users = await asyncio.to_thread(lambda: list(gl.users.list(username=username)))
            if users:
                return users[0].id
            return None
        except Exception as e:
            logger.warning("gitlab_user_lookup_failed", username=username, error=str(e))
            return None

    async def branch_exists(self, branch_name: str) -> bool:
        """检查 GitLab 远程仓库是否存在指定分支。

        Args:
            branch_name: 分支名称。

        Returns:
            True if branch exists, False otherwise.
        """
        try:
            project = self._get_project()
            await asyncio.to_thread(project.branches.get, branch_name)
            return True
        except Exception:
            return False

    async def find_open_merge_request(
        self, source_branch: str, target_branch: str
    ) -> MRCreateResult | None:
        """查 GitLab 同 source→target 的 open MR（IDEMP-02 reuse-first fence）。

        包装 ``project.mergerequests.list(source_branch=, target_branch=, state="opened")``，
        命中首个 → 复用其 web_url/iid；空 → None；平台异常 fail-soft 返回 None
        （绝不上抛，让调用方照常尝试创建）。token 绝不入日志。

        Args:
            source_branch: 功能（变更侧）分支名。
            target_branch: 目标（base）分支名。

        Returns:
            命中 → MRCreateResult(success=True, mr_url=..., mr_id=...)；无/异常 → None。
        """
        try:
            project = self._get_project()
            mrs = await asyncio.to_thread(
                project.mergerequests.list,
                source_branch=source_branch,
                target_branch=target_branch,
                state="opened",
                get_all=False,
            )
            if not mrs:
                return None
            mr = mrs[0]
            logger.info(
                "gitlab_open_mr_found",
                source=source_branch,
                target=target_branch,
                mr_id=mr.iid,
            )
            return MRCreateResult(success=True, mr_url=mr.web_url, mr_id=str(mr.iid))
        except Exception as e:
            # token 绝不入日志，仅记分支与 error（fail-soft，不阻断创建）
            logger.warning(
                "gitlab_find_open_mr_failed",
                source=source_branch,
                target=target_branch,
                error=str(e),
            )
            return None

    async def create_merge_request(self, request: MRCreateRequest) -> MRCreateResult:
        """Create a GitLab merge request with optional reviewers.

        Args:
            request: MR creation parameters.

        Returns:
            MRCreateResult with success status, MR URL, or error details.
        """
        try:
            project = self._get_project()

            # Resolve reviewer usernames to IDs
            reviewer_ids: list[int] = []
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
            project = self._get_project()

            # 获取 MR 对象及其变更
            mr = await asyncio.to_thread(project.mergerequests.get, int(mr_id))
            changes = await asyncio.to_thread(lambda: mr.changes())

            raw_changes: list[dict[str, Any]] = changes.get("changes", [])
            truncated = False

            # 截断文件数量
            if len(raw_changes) > max_files:
                raw_changes = raw_changes[:max_files]
                truncated = True

            files: list[MRDiffFile] = []
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

    async def get_merge_request_metadata(self, mr_id: str) -> MRMetadataResult:
        """获取 GitLab MR 的 merge commit 元数据（HDIFF-01 历史 diff commit 锚定）。

        复用 get_merge_request_diff 同款 `project.mergerequests.get` 范式取 MR 对象，
        读取 merge_commit_sha / target_branch / source_branch / merged_at；
        merged_at（python-gitlab 返回 ISO8601 字符串）经 parse_datetime 解析，naive
        结果归一为 aware（USE_TZ=True，下游 require_aware 拒 naive）。拉取失败一律
        返回 success=False，token 绝不入日志。

        Args:
            mr_id: MR 的 IID（项目内编号）。

        Returns:
            MRMetadataResult：未合并时 merge_commit_sha 为空字符串。
        """
        try:
            project = self._get_project()
            mr = await asyncio.to_thread(project.mergerequests.get, int(mr_id))

            merged_at_raw = getattr(mr, "merged_at", None)
            merged_at = None
            if merged_at_raw:
                merged_at = parse_datetime(merged_at_raw)
                if merged_at is not None and dj_timezone.is_naive(merged_at):
                    # stdlib timezone.utc：django.utils.timezone.utc 自 Django 5.0 已删除
                    merged_at = dj_timezone.make_aware(merged_at, dt_timezone.utc)

            logger.info(
                "gitlab_mr_metadata_fetched",
                mr_id=mr_id,
                has_merge_commit=bool(getattr(mr, "merge_commit_sha", None)),
                target_branch=getattr(mr, "target_branch", "") or "",
            )

            return MRMetadataResult(
                success=True,
                merge_commit_sha=getattr(mr, "merge_commit_sha", None) or "",
                target_branch=getattr(mr, "target_branch", None) or "",
                source_branch=getattr(mr, "source_branch", None) or "",
                merged_at=merged_at,
            )
        except Exception as e:
            error_msg = f"Failed to fetch MR metadata: {e}"
            logger.error(
                "gitlab_mr_metadata_error",
                mr_id=mr_id,
                project=self.project_path,
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
        """获取分支级全量 diff 文本（GitLab 实现，skip-PR 兜底，KMOD-05）。

        包装 repository_compare(from_=target, to=source)——方向 = target 为基底、
        source 为变更侧，与 MR diff 语义一致；diffs[].diff 自带 per-file unified
        diff 文本，截断语义与 get_merge_request_diff 同款。

        Args:
            source_branch: 功能（变更侧）分支名。
            target_branch: 目标（base）分支名。
            max_files: 最大文件数限制。
            max_diff_lines: 单个文件 diff 最大行数。

        Returns:
            MRDiffResult 包含文件列表和 diff 内容；异常时 success=False 不上抛。
        """
        try:
            project = self._get_project()

            result = await asyncio.to_thread(
                project.repository_compare, from_=target_branch, to=source_branch
            )

            raw_diffs: list[dict[str, Any]] = result.get("diffs", [])
            truncated = False

            # 截断文件数量
            if len(raw_diffs) > max_files:
                raw_diffs = raw_diffs[:max_files]
                truncated = True

            files: list[MRDiffFile] = []
            for entry in raw_diffs:
                diff_text: str = entry.get("diff", "") or ""

                # 截断单个文件 diff 行数
                diff_text, was_truncated = truncate_diff_lines(diff_text, max_diff_lines)
                truncated = truncated or was_truncated

                files.append(
                    MRDiffFile(
                        old_path=entry.get("old_path", ""),
                        new_path=entry.get("new_path", ""),
                        diff=diff_text,
                        new_file=entry.get("new_file", False),
                        renamed_file=entry.get("renamed_file", False),
                        deleted_file=entry.get("deleted_file", False),
                    )
                )

            logger.info(
                "gitlab_branch_diff_fetched",
                source=source_branch,
                target=target_branch,
                files_count=len(files),
                truncated=truncated,
            )

            return MRDiffResult(success=True, files=files, truncated=truncated)

        except Exception as e:
            # 只记 str(exc) 与分支名，不记 client/token 对象（T-14-05）
            logger.warning(
                "gitlab_branch_diff_error",
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
        """对比两个分支的差异（GitLab 实现）。

        使用 python-gitlab repository_compare() 获取 diff，从文本解析增删行数。
        反向 compare 获取 behind_by，当 behind_by > 0 时比较文件路径交集推断冲突。

        Args:
            source_branch: 功能分支名。
            target_branch: 目标（base）分支名。
            max_files: 最大返回文件数。

        Returns:
            BranchCompareResult 包含文件变更统计和冲突推断。
        """
        try:
            project = self._get_project()

            # 正向 compare: target -> source（显示 source 相对于 target 的变更）
            forward = await asyncio.to_thread(
                project.repository_compare, target_branch, source_branch
            )

            # 从正向 commits 获取 ahead_by
            ahead_by = len(forward.get("commits", []))

            # 提取文件列表
            raw_diffs: list[dict[str, Any]] = forward.get("diffs", [])
            truncated = False
            if len(raw_diffs) > max_files:
                raw_diffs = raw_diffs[:max_files]
                truncated = True

            total_additions = 0
            total_deletions = 0
            files: list[CompareFileEntry] = []

            for diff_entry in raw_diffs:
                diff_text = diff_entry.get("diff", "")
                additions, deletions = _parse_diff_stats(diff_text)

                # 判断变更类型
                if diff_entry.get("new_file"):
                    change_type = "added"
                elif diff_entry.get("deleted_file"):
                    change_type = "deleted"
                elif diff_entry.get("renamed_file"):
                    change_type = "renamed"
                else:
                    change_type = "modified"

                entry = CompareFileEntry(
                    path=diff_entry.get("new_path", ""),
                    change_type=change_type,
                    additions=additions,
                    deletions=deletions,
                    old_path=diff_entry.get("old_path", ""),
                )
                files.append(entry)
                total_additions += additions
                total_deletions += deletions

            # 反向 compare: source -> target（获取 behind_by）
            reverse = await asyncio.to_thread(
                project.repository_compare, source_branch, target_branch
            )
            behind_by = len(reverse.get("commits", []))

            # 冲突推断: 当 behind_by > 0 时比较文件路径交集
            has_potential_conflicts = False
            conflicting_files: list[str] = []

            if behind_by > 0:
                forward_paths = {d.get("new_path", "") for d in forward.get("diffs", [])}
                reverse_paths = {d.get("new_path", "") for d in reverse.get("diffs", [])}
                conflicting_files = sorted(forward_paths & reverse_paths)
                has_potential_conflicts = len(conflicting_files) > 0

            logger.info(
                "gitlab_compare_branches",
                source=source_branch,
                target=target_branch,
                ahead_by=ahead_by,
                behind_by=behind_by,
                files_count=len(files),
                has_conflicts=has_potential_conflicts,
            )

            return BranchCompareResult(
                success=True,
                ahead_by=ahead_by,
                behind_by=behind_by,
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
                "gitlab_compare_branches_error",
                source=source_branch,
                target=target_branch,
                error=error_msg,
            )
            return BranchCompareResult(success=False, error=error_msg)
