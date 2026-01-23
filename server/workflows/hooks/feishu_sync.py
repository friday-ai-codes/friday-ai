"""Feishu synchronization hook for workflow events.
This hook sends workflow status updates to Feishu as comments
on the associated work items.
"""
import structlog
from core.feature_flags import feature_flags
from workflows.hooks.base import BaseHook
logger = structlog.get_logger
class FeishuSyncHook(BaseHook):
 """Hook to synchronize workflow status to Feishu.
 Posts comments to Feishu work items when workflow nodes
 change state, providing real-time visibility into execution progress.
 """
 name = "feishu_sync"
 async def on_node_started(self, execution, node_execution, **kwargs):
 """Post comment when node starts."""
 if not feature_flags.sync_workflow_to_feishu:
 return
 work_item_id = self._get_work_item_id(execution)
 if not work_item_id:
 return
 await self._post_comment(
 work_item_id=work_item_id,
 content=f"🚀 开始执行: {node_execution.node.name}",
 )
 async def on_node_completed(self, execution, node_execution, **kwargs):
 """Post comment when node completes."""
 if not feature_flags.sync_workflow_to_feishu:
 return
 work_item_id = self._get_work_item_id(execution)
 if not work_item_id:
 return
 await self._post_comment(
 work_item_id=work_item_id,
 content=f"✅ 完成: {node_execution.node.name}",
 )
 async def on_node_failed(self, execution, node_execution, **kwargs):
 """Post comment when node fails."""
 if not feature_flags.sync_workflow_to_feishu:
 return
 work_item_id = self._get_work_item_id(execution)
 if not work_item_id:
 return
 error_msg = node_execution.error_message or "未知错误"
 await self._post_comment(
 work_item_id=work_item_id,
 content=f"❌ 失败: {node_execution.node.name}\n错误: {error_msg[:200]}",
 )
 async def on_node_waiting_approval(self, execution, node_execution, **kwargs):
 """Post approval request comment."""
 if not feature_flags.sync_workflow_to_feishu:
 return
 work_item_id = self._get_work_item_id(execution)
 if not work_item_id:
 return
 # Get approval description from node config
 config = node_execution.node.config or {}
 description = config.get("description_template", "请审批")
 await self._post_comment(
 work_item_id=work_item_id,
 content=(
 f"⏳ 等待审批: {node_execution.node.name}\n\n"
 f"{description}\n\n"
 "回复「通过」或「驳回」进行审批"
 ),
 )
 async def on_execution_completed(self, execution, **kwargs):
 """Post completion comment and update work item status."""
 if not feature_flags.sync_workflow_to_feishu:
 return
 work_item_id = self._get_work_item_id(execution)
 if not work_item_id:
 return
 await self._post_comment(
 work_item_id=work_item_id,
 content="🎉 工作流执行完成!",
 )
 # TODO: Update Feishu work item status to "已完成"
 # await self._update_work_item_status(work_item_id, "completed")
 async def on_execution_failed(self, execution, **kwargs):
 """Post failure comment."""
 if not feature_flags.sync_workflow_to_feishu:
 return
 work_item_id = self._get_work_item_id(execution)
 if not work_item_id:
 return
 error_msg = execution.error_message or "未知错误"
 await self._post_comment(
 work_item_id=work_item_id,
 content=f"❌ 工作流执行失败\n错误: {error_msg[:500]}",
 )
 def _get_work_item_id(self, execution) -> str | None:
 """Extract work_item_id from execution context."""
 context = execution.context or {}
 work_item_id = context.get("work_item_id")
 if not work_item_id:
 input_data = execution.input_data or {}
 work_item_id = input_data.get("work_item_id")
 return work_item_id
 async def _post_comment(self, work_item_id: str, content: str):
 """Post a comment to Feishu work item.
 TODO: Implement actual Feishu API call using feishu.services
 """
 logger.info(
 "feishu_comment_posted",
 work_item_id=work_item_id,
 content=content[:100],
 )
 # TODO: Actual implementation
 # from feishu.services import FeishuService
 # feishu = FeishuService
 # await feishu.post_work_item_comment(work_item_id, content)
 async def _update_work_item_status(self, work_item_id: str, status: str):
 """Update Feishu work item status.
 TODO: Implement actual Feishu API call
 """
 logger.info(
 "feishu_status_updated",
 work_item_id=work_item_id,
 status=status,
 )
