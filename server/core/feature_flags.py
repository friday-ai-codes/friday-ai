"""Feature flags for gradual migration and feature rollout.
This module provides a centralized way to control feature flags across the application.
Feature flags are read from Django settings, which can be configured via environment variables.
"""
from django.conf import settings
class FeatureFlags:
 """Feature flags manager for Task -> Workflow migration."""
 @property
 def use_workflow_for_new_tasks(self) -> bool:
 """Whether new Feishu work items should create Workflow instead of Task.
 When True:
 - FeishuWebhookView will create WorkflowExecution instead of Task
 - Default workflow template will be used
 When False (default):
 - Legacy Task creation behavior is preserved
 """
 return getattr(settings, "FF_USE_WORKFLOW_FOR_NEW_TASKS", False)
 @property
 def enable_task_compat_api(self) -> bool:
 """Whether to enable the /api/tasks/ compatibility layer.
 When True (default):
 - /api/tasks/ endpoints remain functional
 - Internally proxies to Workflow API for new data
 When False:
 - /api/tasks/ returns 410 Gone for new resources
 - Only historical Task data is accessible
 """
 return getattr(settings, "FF_ENABLE_TASK_COMPAT_API", True)
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
