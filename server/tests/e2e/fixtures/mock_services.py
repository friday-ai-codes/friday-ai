"""Mock service factories for E2E testing.

Provides pytest fixtures that mock external services:
- Feishu API client
- LLM API (Anthropic)
- Git platform clients (GitLab, GitHub)
"""

import json
from dataclasses import dataclass, field
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from tests.e2e.fixtures.technical_plans import VALID_TECHNICAL_PLAN


@dataclass
class MockWorkItem:
    """Mock Feishu work item for testing."""

    name: str = "Test Work Item"
    work_item_id: str = "12345"
    work_item_type: str = "story"
    current_status: str = "created"
    fields: dict[str, Any] = field(default_factory=dict)
    description: str = "Test work item description"
    status: str = "created"
    project_key: str = "e2e-test-project"
    raw_response: str | None = None  # Required by feishu.views

    def __post_init__(self) -> None:
        if not self.fields:
            self.fields = {
                "name": self.name,
                "status": self.current_status,
            }
        # Set raw_response to a valid JSON string if not provided
        if self.raw_response is None:
            self.raw_response = json.dumps({
                "id": self.work_item_id,
                "name": self.name,
                "description": self.description,
            })


@dataclass
class MockMRResult:
    """Mock merge request creation result."""

    success: bool = True
    mr_url: str = "https://gitlab.example.com/repo/-/merge_requests/1"
    mr_id: str = "1"
    has_conflicts: bool = False
    error: str | None = None


def create_mock_feishu_client(
    work_item: MockWorkItem | None = None,
) -> MagicMock:
    """Create a mock Feishu client with configurable responses.

    Args:
        work_item: Optional MockWorkItem to return from get_work_item

    Returns:
        MagicMock configured as a Feishu client
    """
    mock_client = MagicMock()

    # Default work item if not provided
    if work_item is None:
        work_item = MockWorkItem()

    # Async methods
    mock_client.get_work_item = AsyncMock(return_value=work_item)
    mock_client.update_field = AsyncMock(return_value=True)
    mock_client.transition_status = AsyncMock(return_value=True)
    mock_client.add_comment = AsyncMock(return_value=True)

    return mock_client


@pytest.fixture
def mock_feishu_client():
    """Pytest fixture that patches create_feishu_client_for_project.

    Usage:
        def test_something(mock_feishu_client):
            # mock_feishu_client is already configured
            # Access the underlying mock via mock_feishu_client.return_value
            pass
    """
    mock_client = create_mock_feishu_client()

    with patch(
        "feishu.client.create_feishu_client_for_project",
        return_value=mock_client,
    ) as mock_factory:
        # Make the mock client accessible
        mock_factory.mock_client = mock_client
        yield mock_factory


@pytest.fixture
def mock_feishu_client_with_work_item():
    """Factory fixture for creating mock Feishu client with custom work item.

    Usage:
        def test_something(mock_feishu_client_with_work_item):
            work_item = MockWorkItem(name="Custom", fields={"status": "approved"})
            mock_factory = mock_feishu_client_with_work_item(work_item)
            # Now Feishu client returns the custom work item
    """

    def _create(work_item: MockWorkItem):
        mock_client = create_mock_feishu_client(work_item)
        patcher = patch(
            "feishu.client.create_feishu_client_for_project",
            return_value=mock_client,
        )
        mock_factory = patcher.start()
        mock_factory.mock_client = mock_client
        mock_factory._patcher = patcher
        return mock_factory

    yield _create


def create_mock_llm_response(
    plan: dict[str, Any] | None = None,
    model: str = "claude-3-5-sonnet-20241022",
) -> dict[str, Any]:
    """Create a mock Anthropic API response.

    Args:
        plan: Technical plan dict to include in response
        model: Model name for response

    Returns:
        Dict matching Anthropic API response structure
    """
    if plan is None:
        plan = VALID_TECHNICAL_PLAN

    return {
        "id": "msg_test_12345",
        "type": "message",
        "role": "assistant",
        "model": model,
        "content": [
            {
                "type": "text",
                "text": json.dumps(plan, ensure_ascii=False),
            }
        ],
        "stop_reason": "end_turn",
        "usage": {
            "input_tokens": 1000,
            "output_tokens": 500,
        },
    }


@pytest.fixture
def mock_llm_api():
    """Pytest fixture that patches httpx.AsyncClient for LLM API calls.

    Returns mock responses with VALID_TECHNICAL_PLAN by default.

    Usage:
        def test_something(mock_llm_api):
            # LLM API calls will return VALID_TECHNICAL_PLAN
            pass
    """
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = create_mock_llm_response()

    with patch("httpx.AsyncClient") as mock_client_class:
        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value=mock_response)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)
        mock_client_class.return_value = mock_client

        # Expose useful references
        mock_client_class.mock_client = mock_client
        mock_client_class.mock_response = mock_response

        yield mock_client_class


@pytest.fixture
def mock_llm_api_with_plan():
    """Factory fixture for creating mock LLM API with custom plan.

    Usage:
        def test_something(mock_llm_api_with_plan):
            custom_plan = {"title": "Custom", "execution_plan": [...]}
            mock_llm = mock_llm_api_with_plan(custom_plan)
    """

    def _create(plan: dict[str, Any]):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = create_mock_llm_response(plan)

        patcher = patch("httpx.AsyncClient")
        mock_client_class = patcher.start()
        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value=mock_response)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)
        mock_client_class.return_value = mock_client

        mock_client_class.mock_client = mock_client
        mock_client_class.mock_response = mock_response
        mock_client_class._patcher = patcher

        return mock_client_class

    yield _create


def create_mock_git_platform_client(
    mr_result: MockMRResult | None = None,
) -> MagicMock:
    """Create a mock Git platform client.

    Args:
        mr_result: Optional MockMRResult to return from create_merge_request

    Returns:
        MagicMock configured as a Git platform client
    """
    if mr_result is None:
        mr_result = MockMRResult()

    mock_client = MagicMock()

    # Async methods
    mock_client.create_merge_request = AsyncMock(
        return_value={
            "success": mr_result.success,
            "mr_url": mr_result.mr_url,
            "mr_id": mr_result.mr_id,
            "has_conflicts": mr_result.has_conflicts,
            "error": mr_result.error,
        }
    )
    mock_client.create_branch = AsyncMock(return_value=True)
    mock_client.push_changes = AsyncMock(return_value=True)
    mock_client.get_default_branch = AsyncMock(return_value="main")

    return mock_client


@pytest.fixture
def mock_git_platform():
    """Pytest fixture that patches get_git_platform_client.

    Usage:
        def test_something(mock_git_platform):
            # Git platform calls will succeed by default
            pass
    """
    mock_client = create_mock_git_platform_client()

    with patch(
        "services.git_platform.get_git_platform_client",
        return_value=mock_client,
    ) as mock_factory:
        mock_factory.mock_client = mock_client
        yield mock_factory


@pytest.fixture
def mock_git_platform_with_result():
    """Factory fixture for creating mock Git platform with custom MR result.

    Usage:
        def test_conflicts(mock_git_platform_with_result):
            result = MockMRResult(has_conflicts=True)
            mock_git = mock_git_platform_with_result(result)
    """

    def _create(mr_result: MockMRResult):
        mock_client = create_mock_git_platform_client(mr_result)
        patcher = patch(
            "services.git_platform.get_git_platform_client",
            return_value=mock_client,
        )
        mock_factory = patcher.start()
        mock_factory.mock_client = mock_client
        mock_factory._patcher = patcher
        return mock_factory

    yield _create


# Export commonly used fixtures and factories
__all__ = [
    # Dataclasses
    "MockWorkItem",
    "MockMRResult",
    # Factory functions
    "create_mock_feishu_client",
    "create_mock_llm_response",
    "create_mock_git_platform_client",
    # Pytest fixtures (auto-registered)
    "mock_feishu_client",
    "mock_feishu_client_with_work_item",
    "mock_llm_api",
    "mock_llm_api_with_plan",
    "mock_git_platform",
    "mock_git_platform_with_result",
]
