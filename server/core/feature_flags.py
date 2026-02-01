"""Feature flags for workflow feature rollout.
This module provides a centralized way to control feature flags across the application.
Feature flags are read from Django settings, which can be configured via environment variables.
"""
from django.conf import settings
class FeatureFlags:
 """Feature flags manager for Workflow features."""
 @property
 def sync_workflow_to_feishu(self) -> bool:
 """Whether workflow status changes should sync to Feishu.
 When True (default):
 - Node completion updates Feishu work item status
 - Approval requests post comments to Feishu
 When False:
 - Workflow executes silently without Feishu updates
 """
 return getattr(settings, "FF_SYNC_WORKFLOW_TO_FEISHU", True)
 @property
 def enable_workflow_websocket(self) -> bool:
 """Whether to enable WebSocket real-time updates for workflow execution.
 When True (default):
 - Clients can connect to /ws/workflow-executions/{id}/
 - Real-time node status updates are pushed
 When False:
 - Clients must poll for updates
 """
 return getattr(settings, "FF_ENABLE_WORKFLOW_WEBSOCKET", True)
 @property
 def default_workflow_template(self) -> str:
 """The default workflow template to use for new tasks.
 Returns the template name that will be used when creating
 WorkflowExecution from Feishu work items.
 """
 return getattr(settings, "FF_DEFAULT_WORKFLOW_TEMPLATE", "code_generation")
# Singleton instance
feature_flags = FeatureFlags
