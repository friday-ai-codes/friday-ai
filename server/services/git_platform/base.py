"""Abstract base class for Git platform clients."""

from abc import ABC, abstractmethod

from .models import (
    BranchCompareResult,
    MRCreateRequest,
    MRCreateResult,
    MRDiffResult,
    MRMetadataResult,
)


def truncate_diff_lines(diff_text: str, max_diff_lines: int) -> tuple[str, bool]:
    """按行数截断单文件 unified diff 文本（双客户端共用，避免截断逻辑复制多份）。

    Args:
        diff_text: unified diff 文本。
        max_diff_lines: 单个文件 diff 最大行数。

    Returns:
        (截断后文本, 是否发生截断)。截断时尾部追加 "[diff truncated]" 标记，
        与 get_merge_request_diff 同款语义。
    """
    diff_lines = diff_text.split("\n")
    if len(diff_lines) <= max_diff_lines:
        return diff_text, False
    return "\n".join(diff_lines[:max_diff_lines]) + "\n[diff truncated]", True


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

    async def find_open_merge_request(
        self, source_branch: str, target_branch: str
    ) -> MRCreateResult | None:
        """查同 source→target 分支是否已有 open 的 MR/PR（IDEMP-02 reuse-first fence）。

        创建 MR/PR 前的前置去重查询：命中既有 open MR/PR 即复用其 URL/ID 不重复创建。

        **刻意不设为 @abstractmethod**：新增抽象方法会让所有既有子类实例化抛
        ``TypeError``（漏实现），破坏既有调用方。改为带默认 ``return None`` 的普通
        async 方法——子类按平台覆盖，未覆盖的实现自然退化为"查不到 → 照常创建"，
        零回归。

        Args:
            source_branch: 功能（变更侧）分支名。
            target_branch: 目标（base）分支名。

        Returns:
            命中既有 open MR/PR → ``MRCreateResult(success=True, mr_url=..., mr_id=...)``；
            无既有 / 平台异常（fail-soft）→ ``None``（绝不上抛，不阻断后续创建）。
        """
        return None

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
    async def get_branch_diff(
        self,
        source_branch: str,
        target_branch: str,
        max_files: int = 50,
        max_diff_lines: int = 500,
    ) -> MRDiffResult:
        """获取分支级全量 diff 文本（skip-PR 兜底，KMOD-05）。

        语义为"取 source 相对 target 的全量 unified diff 文本"，与
        get_merge_request_diff 统一返回 MRDiffResult，供 DiffArchiver
        在无 MR/PR 的 skip-PR 路径下消费；与 compare_branches（冲突预检/
        统计语义）并列，互不替代。抽象方法强制双子类实现，漏实现即
        实例化 TypeError。

        Args:
            source_branch: 功能（变更侧）分支名。
            target_branch: 目标（base）分支名。
            max_files: 最大文件数限制（调用方按归档语义放大）。
            max_diff_lines: 单个文件 diff 最大行数。

        Returns:
            MRDiffResult 包含文件列表（含 per-file unified diff 文本）；
            超限或平台侧 patch 缺失时 truncated=True 响亮标记。
        """
        pass

    @abstractmethod
    async def get_merge_request_metadata(self, mr_id: str) -> MRMetadataResult:
        """获取已合并 MR/PR 的元数据：merge commit sha + 目标/源分支 + 合并业务时间。

        供历史 diff commit 锚定（HDIFF-01）：用真实 merge_commit_sha 作为归档
        commit_sha、target_branch 作为 base_branch（绝不假设 master），merged_at
        作为 MODIFIES_CHUNK 边 valid_at 的业务时间。抽象方法强制双子类实现，漏实现
        即实例化 TypeError。拉取失败一律返回 success=False 不上抛（与
        get_merge_request_diff 同款降级），token 绝不入日志。

        Args:
            mr_id: MR/PR 的 ID 或编号。

        Returns:
            MRMetadataResult 包含 merge_commit_sha/target_branch/source_branch/merged_at；
            未合并或拉取失败时 success=False。
        """
        pass

    @abstractmethod
    async def compare_branches(
        self,
        source_branch: str,
        target_branch: str,
        max_files: int = 50,
    ) -> BranchCompareResult:
        """对比两个分支的差异（per contract）。

        Args:
            source_branch: 功能分支名。
            target_branch: 目标（base）分支名。
            max_files: 最大返回文件数（per contract 默认 50）。

        Returns:
            BranchCompareResult 包含文件变更统计和冲突推断。
        """
        pass
