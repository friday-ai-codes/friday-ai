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
