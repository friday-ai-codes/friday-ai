"""E2E test fixtures.
This module exports fixtures for:
- Feishu webhook payload factories
- Technical plan test data
- Mock services for external APIs
"""
from tests.e2e.fixtures.feishu_payloads import (
 create_workitem_create_payload,
 create_workitem_update_payload,
)
from tests.e2e.fixtures.technical_plans import (
 VALID_TECHNICAL_PLAN,
 create_technical_plan,
)
__all__ = [
 # Feishu payloads
 "create_workitem_create_payload",
 "create_workitem_update_payload",
 # Technical plans
 "VALID_TECHNICAL_PLAN",
 "create_technical_plan",
]
