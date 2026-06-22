"""Tests for CreatePRNode multi-repository batch PR creation."""

from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from services.git_platform import MRCreateResult
from workflows.nodes.base import ExecutionContext
from workflows.nodes.git.pr import CreatePRNode


def make_mock_repository(
    repo_id: str | None = None,
    name: str = "test-repo",
    git_url: str = "https://github.com/org/test-repo.git",
    git_platform: str = "github",
    has_credential: bool = True,
) -> MagicMock:
    """Create a mock Repository object."""
    repo = MagicMock()
    repo.id = repo_id or str(uuid4())
    repo.name = name
    repo.git_url = git_url
    repo.git_platform = git_platform
    return repo


def make_mock_credential(has_token: bool = True) -> MagicMock | None:
    """Create a mock GitCredential object."""
    if not has_token:
        return None
    credential = MagicMock()
    credential.encrypted_token = "encrypted_token_value"
    return credential


def make_context(
    config: dict[str, Any],
    input_data: dict[str, Any] | None = None,
) -> ExecutionContext:
    """Create an ExecutionContext for testing."""
    return ExecutionContext(
        execution_id="test-execution-id",
        node_id="test-node-id",
        node_config=config,
        input_data=input_data or {},
        workflow_context={},
        previous_outputs={},
    )


def _make_async_filter_qs(repos: list[MagicMock]) -> MagicMock:
    """Create a mock queryset that supports async for iteration."""
    mock_qs = MagicMock()

    async def async_iter():
        for r in repos:
            yield r

    mock_qs.__aiter__ = lambda self: async_iter()
    return mock_qs


@pytest.mark.asyncio
async def test_batch_create_pr_all_success() -> None:
    """Test batch PR creation with all repositories succeeding."""
    repo1_id = str(uuid4())
    repo2_id = str(uuid4())

    repo1 = make_mock_repository(repo_id=repo1_id, name="frontend")
    repo2 = make_mock_repository(repo_id=repo2_id, name="backend")
    credential = make_mock_credential()

    config = {
        "repositories": [{"id": repo1_id}, {"id": repo2_id}],
        "title": "Test PR",
        "head_branch": "feature/test",
        "base_branch": "main",
        "add_cross_references": False,  # Disable for simpler test
    }
    context = make_context(config)

    mock_client = AsyncMock()
    mock_client.create_merge_request.return_value = MRCreateResult(
        success=True,
        mr_url="https://github.com/org/repo/pull/1",
        mr_id="1",
        has_conflicts=False,
    )

    with (
        patch(
            "workflows.nodes.git.pr.Repository.objects.filter",
            return_value=_make_async_filter_qs([repo1, repo2]),
        ),
        patch(
            "workflows.nodes.git.pr.aresolve_git_token",
            new=AsyncMock(return_value="decrypted_token" if credential else None),
        ),
        patch("workflows.nodes.git.pr.get_git_platform_client", return_value=mock_client),
    ):
        node = CreatePRNode()
        result = await node.execute(context)

    assert result.status == "completed"
    assert result.output["total"] == 2
    assert len(result.output["succeeded"]) == 2
    assert len(result.output["failed"]) == 0
    assert result.output["all_succeeded"] is True

    # Verify PR URLs are in succeeded list
    pr_urls = [s["pr_url"] for s in result.output["succeeded"]]
    assert all("github.com" in url for url in pr_urls)


@pytest.mark.asyncio
async def test_batch_create_pr_partial_failure() -> None:
    """Test batch PR creation with some repositories failing."""
    repo1_id = str(uuid4())
    repo2_id = str(uuid4())

    repo1 = make_mock_repository(repo_id=repo1_id, name="frontend")
    repo2 = make_mock_repository(repo_id=repo2_id, name="backend")
    credential = make_mock_credential()

    config = {
        "repositories": [{"id": repo1_id}, {"id": repo2_id}],
        "title": "Test PR",
        "head_branch": "feature/test",
        "base_branch": "main",
        "add_cross_references": False,
    }
    context = make_context(config)

    # First call succeeds, second fails
    mock_client = AsyncMock()
    mock_client.create_merge_request.side_effect = [
        MRCreateResult(
            success=True,
            mr_url="https://github.com/org/frontend/pull/1",
            mr_id="1",
            has_conflicts=False,
        ),
        MRCreateResult(
            success=False,
            error="Branch not found",
        ),
    ]

    with (
        patch(
            "workflows.nodes.git.pr.Repository.objects.filter",
            return_value=_make_async_filter_qs([repo1, repo2]),
        ),
        patch(
            "workflows.nodes.git.pr.aresolve_git_token",
            new=AsyncMock(return_value="decrypted_token" if credential else None),
        ),
        patch("workflows.nodes.git.pr.get_git_platform_client", return_value=mock_client),
    ):
        node = CreatePRNode()
        result = await node.execute(context)

    # Should still be "completed" because at least one succeeded
    assert result.status == "completed"
    assert result.output["total"] == 2
    assert len(result.output["succeeded"]) == 1
    assert len(result.output["failed"]) == 1
    assert result.output["all_succeeded"] is False

    # Check failed entry has error message
    assert result.output["failed"][0]["error"] == "Branch not found"


@pytest.mark.asyncio
async def test_batch_create_pr_with_cross_references() -> None:
    """Test that cross-references are generated correctly."""
    node = CreatePRNode()

    # Mock successful results
    results = [
        {
            "repository_id": "repo1",
            "repository_name": "frontend",
            "pr_url": "https://github.com/org/frontend/pull/1",
            "pr_id": "1",
            "has_conflicts": False,
            "success": True,
        },
        {
            "repository_id": "repo2",
            "repository_name": "backend",
            "pr_url": "https://gitlab.com/org/backend/-/merge_requests/2",
            "pr_id": "2",
            "has_conflicts": False,
            "success": True,
        },
    ]

    # Test cross-reference generation for first PR
    cross_ref = node._generate_cross_reference_section(
        "https://github.com/org/frontend/pull/1",
        results,  # 测试模拟数据，不完全匹配函数参数类型
    )

    assert "## Related PRs" in cross_ref
    assert "[backend]" in cross_ref
    assert "https://gitlab.com/org/backend/-/merge_requests/2" in cross_ref
    assert "[frontend]" not in cross_ref  # Should not include self

    # Test cross-reference generation for second PR
    cross_ref2 = node._generate_cross_reference_section(
        "https://gitlab.com/org/backend/-/merge_requests/2",
        results,  # 测试模拟数据，不完全匹配函数参数类型
    )

    assert "[frontend]" in cross_ref2
    assert "https://github.com/org/frontend/pull/1" in cross_ref2
    assert "[backend]" not in cross_ref2  # Should not include self


@pytest.mark.asyncio
async def test_batch_create_pr_cross_reference_disabled() -> None:
    """Test that cross-references can be disabled."""
    repo1_id = str(uuid4())
    repo2_id = str(uuid4())

    repo1 = make_mock_repository(repo_id=repo1_id, name="frontend")
    repo2 = make_mock_repository(repo_id=repo2_id, name="backend")
    credential = make_mock_credential()

    config = {
        "repositories": [{"id": repo1_id}, {"id": repo2_id}],
        "title": "Test PR",
        "head_branch": "feature/test",
        "base_branch": "main",
        "add_cross_references": False,  # Explicitly disabled
    }
    context = make_context(config)

    mock_client = AsyncMock()
    mock_client.create_merge_request.return_value = MRCreateResult(
        success=True,
        mr_url="https://github.com/org/repo/pull/1",
        mr_id="1",
        has_conflicts=False,
    )

    with (
        patch(
            "workflows.nodes.git.pr.Repository.objects.filter",
            return_value=_make_async_filter_qs([repo1, repo2]),
        ),
        patch(
            "workflows.nodes.git.pr.aresolve_git_token",
            new=AsyncMock(return_value="decrypted_token" if credential else None),
        ),
        patch("workflows.nodes.git.pr.get_git_platform_client", return_value=mock_client),
    ):
        node = CreatePRNode()
        result = await node.execute(context)

    assert result.status == "completed"
    # All PRs should have cross_referenced=False since disabled
    for succeeded in result.output["succeeded"]:
        assert succeeded["cross_referenced"] is False


@pytest.mark.asyncio
async def test_batch_create_pr_backward_compat() -> None:
    """Test backward compatibility with single repository using repository field."""
    repo_id = str(uuid4())
    repo = make_mock_repository(repo_id=repo_id, name="single-repo")
    credential = make_mock_credential()

    # Use singular 'repository' field (backward compat)
    config = {
        "repository": {"id": repo_id},
        "title": "Single Repo PR",
        "head_branch": "feature/single",
        "base_branch": "main",
        "add_cross_references": False,
    }
    context = make_context(config)

    mock_client = AsyncMock()
    mock_client.create_merge_request.return_value = MRCreateResult(
        success=True,
        mr_url="https://github.com/org/single-repo/pull/1",
        mr_id="1",
        has_conflicts=False,
    )

    with (
        patch(
            "workflows.nodes.git.pr.Repository.objects.filter",
            return_value=_make_async_filter_qs([repo]),
        ),
        patch(
            "workflows.nodes.git.pr.aresolve_git_token",
            new=AsyncMock(return_value="decrypted_token" if credential else None),
        ),
        patch("workflows.nodes.git.pr.get_git_platform_client", return_value=mock_client),
    ):
        node = CreatePRNode()
        result = await node.execute(context)

    assert result.status == "completed"
    assert result.output["total"] == 1
    assert len(result.output["succeeded"]) == 1
    assert result.output["succeeded"][0]["repository_name"] == "single-repo"


@pytest.mark.asyncio
async def test_batch_create_pr_no_credential() -> None:
    """Test handling of repository without credentials."""
    repo_id = str(uuid4())
    repo = make_mock_repository(repo_id=repo_id, name="no-cred-repo", has_credential=False)

    config = {
        "repositories": [{"id": repo_id}],
        "title": "Test PR",
        "head_branch": "feature/test",
        "base_branch": "main",
    }
    context = make_context(config)

    with (
        patch(
            "workflows.nodes.git.pr.Repository.objects.filter",
            return_value=_make_async_filter_qs([repo]),
        ),
        patch(
            "workflows.nodes.git.pr.aresolve_git_token",
            new=AsyncMock(return_value=None),
        ),
    ):
        node = CreatePRNode()
        result = await node.execute(context)

    assert result.status == "failed"
    assert len(result.output["failed"]) == 1
    assert "token" in result.output["failed"][0]["error"].lower()


@pytest.mark.asyncio
async def test_batch_create_pr_empty_repositories() -> None:
    """Test handling of empty repository list."""
    config = {
        "repositories": [],
        "title": "Test PR",
        "head_branch": "feature/test",
        "base_branch": "main",
    }
    context = make_context(config)

    node = CreatePRNode()
    result = await node.execute(context)

    assert result.status == "failed"
    assert result.error is not None
    assert "未配置仓库列表" in result.error


@pytest.mark.asyncio
async def test_batch_create_pr_missing_title() -> None:
    """Test validation of required fields."""
    config = {
        "repositories": [{"id": str(uuid4())}],
        "title": "",  # Empty title
        "head_branch": "feature/test",
    }
    context = make_context(config)

    node = CreatePRNode()
    result = await node.execute(context)

    assert result.status == "failed"
    assert result.error is not None
    assert "标题" in result.error or "title" in result.error.lower()
