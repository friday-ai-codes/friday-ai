"""Git platform abstraction layer for MR/PR creation."""

import re
from urllib.parse import urlparse

from repositories.models import GitPlatform, Repository

from .base import GitPlatformClient
from .github_client import GitHubClient
from .gitlab_client import GitLabClient
from .models import MRCreateRequest, MRCreateResult, MRDiffFile, MRDiffResult, MRMetadataResult

__all__ = [
    "MRCreateRequest",
    "MRCreateResult",
    "MRDiffFile",
    "MRDiffResult",
    "MRMetadataResult",
    "GitPlatformClient",
    "GitLabClient",
    "GitHubClient",
    "get_git_platform_client",
]


def extract_gitlab_url(git_url: str) -> str:
    """Extract GitLab base URL from git URL.

    Handles both HTTPS and SSH formats:
    - https://gitlab.example.com/namespace/project.git
    - git@gitlab.example.com:namespace/project.git

    Args:
        git_url: Git repository URL.

    Returns:
        Base URL (e.g., https://gitlab.example.com).
    """
    # Handle SSH format: git@host:path
    ssh_match = re.match(r"git@([^:]+):", git_url)
    if ssh_match:
        host = ssh_match.group(1)
        return f"https://{host}"

    # Handle HTTPS format
    parsed = urlparse(git_url)
    if parsed.scheme and parsed.netloc:
        return f"{parsed.scheme}://{parsed.netloc}"

    raise ValueError(f"Cannot extract GitLab URL from: {git_url}")


def extract_project_path(git_url: str) -> str:
    """Extract project path (namespace/project) from git URL.

    Handles both HTTPS and SSH formats:
    - https://gitlab.example.com/namespace/project.git -> namespace/project
    - git@gitlab.example.com:namespace/project.git -> namespace/project

    Args:
        git_url: Git repository URL.

    Returns:
        Space path (e.g., namespace/project).
    """
    # Handle SSH format: git@host:path
    ssh_match = re.match(r"git@[^:]+:(.+?)(?:\.git)?$", git_url)
    if ssh_match:
        return ssh_match.group(1)

    # Handle HTTPS format
    parsed = urlparse(git_url)
    if parsed.path:
        # Remove leading slash and trailing .git
        path = parsed.path.lstrip("/")
        if path.endswith(".git"):
            path = path[:-4]
        return path

    raise ValueError(f"Cannot extract project path from: {git_url}")


def extract_github_owner_repo(git_url: str) -> tuple[str, str]:
    """Extract owner and repository name from GitHub URL.

    Handles both HTTPS and SSH formats:
    - https://github.com/owner/repo.git -> (owner, repo)
    - git@github.com:owner/repo.git -> (owner, repo)

    Args:
        git_url: Git repository URL.

    Returns:
        Tuple of (owner, repo).
    """
    # Handle SSH format: git@github.com:owner/repo.git
    ssh_match = re.match(r"git@github\.com:([^/]+)/(.+?)(?:\.git)?$", git_url)
    if ssh_match:
        return ssh_match.group(1), ssh_match.group(2)

    # Handle HTTPS format
    parsed = urlparse(git_url)
    if parsed.netloc and "github" in parsed.netloc:
        path = parsed.path.lstrip("/")
        if path.endswith(".git"):
            path = path[:-4]
        parts = path.split("/", 1)
        if len(parts) == 2:
            return parts[0], parts[1]

    raise ValueError(f"Cannot extract GitHub owner/repo from: {git_url}")


def get_git_platform_client(repository: Repository, token: str) -> GitPlatformClient:
    """Factory to get appropriate Git platform client.

    Args:
        repository: Repository model instance with git_url and git_platform.
        token: Access token for the Git platform.

    Returns:
        GitPlatformClient instance for the appropriate platform.

    Raises:
        ValueError: If platform is not supported.
    """
    if repository.git_platform == GitPlatform.GITLAB:
        return GitLabClient(
            base_url=extract_gitlab_url(repository.git_url),
            token=token,
            project_path=extract_project_path(repository.git_url),
        )
    elif repository.git_platform == GitPlatform.GITHUB:
        owner, repo = extract_github_owner_repo(repository.git_url)
        return GitHubClient(token=token, owner=owner, repo=repo)
    else:
        raise ValueError(f"Unsupported platform: {repository.git_platform}")
