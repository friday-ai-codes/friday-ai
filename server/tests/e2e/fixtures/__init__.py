"""E2E test fixtures.
This module exports fixtures for:
- Feishu webhook payload factories
- Technical plan test data
- Mock services for external APIs
"""
from tests.e2e.fixtures.feishu_payloads import (
 create_status_change_payload,
 create_workitem_comment_payload,
 create_workitem_create_payload,
 create_workitem_update_payload,
)
from tests.e2e.fixtures.mock_services import (
 MockMRResult,
 MockWorkItem,
 create_mock_feishu_client,
 create_mock_git_platform_client,
 create_mock_llm_response,
 mock_feishu_client,
 mock_feishu_client_with_work_item,
 mock_git_platform,
 mock_git_platform_with_result,
 mock_llm_api,
 mock_llm_api_with_plan,
)
from tests.e2e.fixtures.technical_plans import (
 VALID_TECHNICAL_PLAN,
 create_multi_repo_plan,
 create_technical_plan,
)
__all__ = [
 # Feishu payloads
 "create_workitem_create_payload",
 "create_workitem_update_payload",
 "create_workitem_comment_payload",
 "create_status_change_payload",
 # Technical plans
 "VALID_TECHNICAL_PLAN",
 "create_technical_plan",
 "create_multi_repo_plan",
 # Mock services - dataclasses
 "MockWorkItem",
 "MockMRResult",
 # Mock services - factory functions
 "create_mock_feishu_client",
 "create_mock_llm_response",
 "create_mock_git_platform_client",
 # Mock services - pytest fixtures
 "mock_feishu_client",
 "mock_feishu_client_with_work_item",
 "mock_llm_api",
 "mock_llm_api_with_plan",
 "mock_git_platform",
 "mock_git_platform_with_result",
]
