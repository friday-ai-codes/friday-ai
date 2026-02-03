"""Abstract base class for Git platform clients."""
from abc import ABC, abstractmethod
from .models import MRCreateRequest, MRCreateResult
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
 @abstractmethod
 async def get_user_id_by_username(self, username: str) -> int | None:
 """Resolve a username to the platform's user ID.
 Args:
 username: The username to look up.
 Returns:
 The user ID if found, None otherwise.
 """
 pass
