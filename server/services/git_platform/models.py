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
