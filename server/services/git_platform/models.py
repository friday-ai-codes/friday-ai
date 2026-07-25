"""Data models for Git platform operations."""

from dataclasses import dataclass, field
from datetime import datetime


@dataclass
class MRCreateRequest:
    """Request data for creating a merge/pull request."""

    source_branch: str
    target_branch: str
    title: str
    description: str
    reviewer_usernames: list[str] = field(default_factory=list)
    remove_source_branch: bool = True


@dataclass
class MRCreateResult:
    """Result of a merge/pull request creation."""

    success: bool
    mr_url: str = ""
    mr_id: str = ""
    error: str = ""
    has_conflicts: bool = False


@dataclass
class MRDiffFile:
    """单个文件的 diff 信息。"""

    old_path: str
    new_path: str
    diff: str  # unified diff 文本
    new_file: bool = False
    renamed_file: bool = False
    deleted_file: bool = False


@dataclass
class MRDiffResult:
    """MR diff 获取结果。"""

    success: bool
    files: list[MRDiffFile] = field(default_factory=list)
    error: str | None = None
    truncated: bool = False  # diff 是否因过大被截断


@dataclass
class MRMetadataResult:
    """已合并 MR/PR 的元数据（HDIFF-01：历史 diff commit 锚定）。

    供历史 diff 锚定到它真正合入的 commit 与目标分支——`merge_commit_sha` 作为
    `CodeChangeArchive.commit_sha`，`target_branch` 作为 `base_branch`（绝不假设
    master），`merged_at` 作为 MODIFIES_CHUNK 边 valid_at 的业务时间。拉取失败一律
    返回 success=False，不上抛（与 MRDiffResult 同款降级风格）。
    """

    success: bool
    merge_commit_sha: str = ""
    target_branch: str = ""
    source_branch: str = ""
    merged_at: datetime | None = None
    error: str = ""


@dataclass
class WebhookSetupResult:
    """自动配置 project push webhook 的结果（一键配置，幂等）。

    ``action`` 为 ``created``（新建）或 ``updated``（按 URL 命中已有 hook 后更新）。
    失败时 ``success=False``，``error`` 为已翻译的用户可读中文提示（token 绝不回显）。
    """

    success: bool
    action: str = ""  # created / updated
    hook_id: str = ""
    error: str = ""


@dataclass
class CompareFileEntry:
    """分支对比中的单个文件变更。"""

    path: str
    change_type: str  # added / modified / deleted / renamed
    additions: int = 0
    deletions: int = 0
    old_path: str = ""


@dataclass
class BranchCompareResult:
    """分支对比结果 -- 同时服务冲突预检和 diff 摘要（per contract）。"""

    success: bool
    ahead_by: int = 0
    behind_by: int = 0
    files: list[CompareFileEntry] = field(default_factory=list)
    total_additions: int = 0
    total_deletions: int = 0
    truncated: bool = False
    has_potential_conflicts: bool = False
    conflicting_files: list[str] = field(default_factory=list)
    error: str = ""


class MergeRequestLookupFailed(Exception):
    """查「同 source→target 是否已有 open MR/PR」时平台侧出错。

    与「查了，确实没有」必须区分开。此前 ``find_open_merge_request`` 对两种情况
    一律返回 ``None``，调用方无从分辨，于是查重 API 一抖动就会被当成「无既有 MR」
    继续创建——本该防重复的围栏反而成了制造重复 PR 的入口。

    抛出方：各平台 client 的 ``find_open_merge_request``。
    调用方约定：捕获后**不要**当作「无命中」继续创建，应显式失败让重试兜底——
    重试时若查重恢复正常就能命中既有 MR，不会留下重复件。
    """
