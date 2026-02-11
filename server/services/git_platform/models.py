"""Data models for Git platform operations."""
from dataclasses import dataclass, field
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
 diff: str # unified diff 文本
 new_file: bool = False
 renamed_file: bool = False
 deleted_file: bool = False
@dataclass
class MRDiffResult:
 """MR diff 获取结果。"""
 success: bool
 files: list[MRDiffFile] = field(default_factory=list)
 error: str | None = None
 truncated: bool = False # diff 是否因过大被截断
