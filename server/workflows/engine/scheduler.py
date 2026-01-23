"""Workflow execution engine."""
import asyncio
import uuid
from typing import TYPE_CHECKING
import structlog
from asgiref.sync import sync_to_async
from django.utils import timezone
from workflows.engine.dag import DAG
from workflows.models.execution import (
 ExecutionStatus,
 NodeExecution,
 NodeExecutionStatus,
 WorkflowExecution,
)
from workflows.nodes.base import ExecutionContext, NodeResult
from workflows.nodes.registry import NodeRegistry
if TYPE_CHECKING:
 from workflows.hooks import HookManager
 from workflows.models import Workflow, WorkflowNode
logger = structlog.get_logger
class WorkflowEngine:
 """工作流执行引擎
 核心调度器，负责：
 1. 构建 DAG 并验证
 2. 按拓扑顺序调度节点执行
 3. 处理并行执行
 4. 处理审批等阻塞节点
 5. 错误处理和重试
 """
 def __init__(self, hooks: "HookManager | None" = None):
 from workflows.hooks import HookManager
 from workflows.hooks.builtin import LoggingHook, WebSocketBroadcastHook
 self.hooks = hooks or HookManager
 # Register built-in hooks
 logging_hook = LoggingHook
 websocket_hook = WebSocketBroadcastHook
 for event in HookManager.EVENTS:
 self.hooks.register_hook(event, logging_hook)
 self.hooks.register_hook(event, websocket_hook)
 async def start_execution(
 self,
 workflow: "Workflow",
 input_data: dict | None = None,
 triggered_by=None,
 trigger_type: str = "manual",
 trigger_data: dict | None = None,
 ) -> WorkflowExecution:
 """启动工作流执行"""
 input_data = input_data or {}
 trigger_data = trigger_data or {}
 # 检查并发限制
 if workflow.max_concurrent_executions > 0:
 running_count = await sync_to_async(
 lambda: WorkflowExecution.objects.filter(
 workflow=workflow,
 status=ExecutionStatus.RUNNING,
 ).count
 )
 if running_count >= workflow.max_concurrent_executions:
 raise ValueError(
 f"工作流已达到最大并发数 ({workflow.max_concurrent_executions})"
 )
 # 创建执行实例
 execution = await sync_to_async(WorkflowExecution.objects.create)(
 workflow=workflow,
 status=ExecutionStatus.PENDING,
 trigger_type=trigger_type,
 triggered_by=triggered_by,
 trigger_data=trigger_data,
 input_data=input_data,
 context={
 "workflow_id": str(workflow.id),
 "workflow_name": workflow.name,
 "started_at": timezone.now.isoformat,
 },
 )
 # 构建 DAG
 dag = await sync_to_async(DAG.from_workflow)(workflow)
 errors = dag.validate
 if errors:
 await sync_to_async(execution.mark_failed)("\n".join(errors))
 return execution
 # 初始化节点执行记录
 execution.total_nodes = len(dag.nodes)
 await sync_to_async(execution.save)(update_fields=["total_nodes"])
 for dag_node in dag.nodes.values:
 await sync_to_async(NodeExecution.objects.create)(
 workflow_execution=execution,
 node=dag_node.node,
 status=NodeExecutionStatus.PENDING,
 )
 # 触发开始钩子
 await self.hooks.trigger("execution_started", execution=execution)
 # 开始执行
 asyncio.create_task(self._run_execution(execution, dag, input_data))
 return execution
 async def _run_execution(
 self,
 execution: WorkflowExecution,
 dag: DAG,
 input_data: dict,
 ) -> None:
 """执行工作流主循环"""
 try:
 await sync_to_async(execution.mark_started)
 await self.hooks.trigger("execution_running", execution=execution)
 # 节点输出缓存
 node_outputs: dict[str, dict] = {}
 # 节点完成状态
 completed_nodes: set[str] = set
 failed_nodes: set[str] = set
 skipped_nodes: set[str] = set
 # 待处理节点
 pending_nodes = set(dag.nodes.keys)
 # 入口节点的输入数据
 entry_inputs = {dag_node.id: input_data for dag_node in dag.get_entry_nodes}
 while pending_nodes:
 # 找出可以执行的节点（所有前置已完成）
 ready_nodes =
 nodes_to_remove =
 for node_id in pending_nodes:
 dag_node = dag.nodes[node_id]
 # 检查所有前置节点是否完成
 all_deps_completed = all(
 dep_id in completed_nodes or dep_id in skipped_nodes
 for dep_id in dag_node.incoming
 )
 # 检查是否有前置失败（需要跳过）
 any_dep_failed = any(
 dep_id in failed_nodes for dep_id in dag_node.incoming
 )
 if any_dep_failed:
 # 前置失败，跳过此节点
 await self._skip_node(execution, dag_node, "前置节点失败")
 skipped_nodes.add(node_id)
 nodes_to_remove.append(node_id)
 continue
 if all_deps_completed:
 ready_nodes.append(dag_node)
 for node_id in nodes_to_remove:
 pending_nodes.discard(node_id)
 if not ready_nodes:
 # 检查是否有正在等待审批的节点
 waiting_nodes = await sync_to_async(
 lambda: list(
 NodeExecution.objects.filter(
 workflow_execution=execution,
 status=NodeExecutionStatus.WAITING_APPROVAL,
 )
 )
 )
 if waiting_nodes:
 # 有节点在等待审批，等待状态变化
 await asyncio.sleep(5)
 # 刷新状态
 for ne in waiting_nodes:
 await sync_to_async(ne.refresh_from_db)
 if ne.status == NodeExecutionStatus.COMPLETED:
 completed_nodes.add(str(ne.node_id))
 node_outputs[str(ne.node_id)] = ne.output_data
 pending_nodes.discard(str(ne.node_id))
 elif ne.status == NodeExecutionStatus.FAILED:
 failed_nodes.add(str(ne.node_id))
 pending_nodes.discard(str(ne.node_id))
 continue
 else:
 # 死锁检测
 if pending_nodes:
 logger.error(
 "workflow_deadlock",
 execution_id=str(execution.id),
 pending_nodes=list(pending_nodes),
 )
 break
 # 并行执行就绪节点
 tasks =
 for dag_node in ready_nodes:
 # 收集输入数据
 if dag_node.id in entry_inputs:
 node_input = entry_inputs[dag_node.id]
 else:
 node_input = self._collect_inputs(dag_node, dag, node_outputs)
 tasks.append(
 self._execute_node(execution, dag_node, node_input, node_outputs)
 )
 pending_nodes.discard(dag_node.id)
 results = await asyncio.gather(*tasks, return_exceptions=True)
 # 处理结果
 for dag_node, result in zip(ready_nodes, results):
 if isinstance(result, Exception):
 logger.error(
 "node_execution_exception",
 node_id=dag_node.id,
 error=str(result),
 )
 failed_nodes.add(dag_node.id)
 elif result.get("status") == "completed":
 completed_nodes.add(dag_node.id)
 node_outputs[dag_node.id] = result.get("output", {})
 elif result.get("status") == "waiting_approval":
 # 节点正在等待审批，保持在 pending
 pending_nodes.add(dag_node.id)
 else:
 failed_nodes.add(dag_node.id)
 # 检查超时
 await sync_to_async(execution.refresh_from_db)
 if execution.timeout_at and timezone.now > execution.timeout_at:
 execution.status = ExecutionStatus.TIMEOUT
 await sync_to_async(execution.save)(update_fields=["status"])
 await self.hooks.trigger("execution_timeout", execution=execution)
 return
 # 执行完成
 if failed_nodes:
 await sync_to_async(execution.mark_failed)(
 f"失败节点: {len(failed_nodes)}"
 )
 else:
 # 收集最终输出（终端节点的输出）
 final_output = {}
 for node_id in completed_nodes:
 dag_node = dag.nodes.get(node_id)
 if dag_node and not dag_node.outgoing:
 final_output.update(node_outputs.get(node_id, {}))
 await sync_to_async(execution.mark_completed)(final_output)
 await self.hooks.trigger("execution_completed", execution=execution)
 except Exception as e:
 logger.exception(
 "workflow_execution_error", execution_id=str(execution.id)
 )
 await sync_to_async(execution.mark_failed)(str(e))
 await self.hooks.trigger("execution_failed", execution=execution, error=e)
 async def _execute_node(
 self,
 execution: WorkflowExecution,
 dag_node,
 input_data: dict,
 previous_outputs: dict,
 ) -> dict:
 """执行单个节点"""
 node = dag_node.node
 node_execution = await sync_to_async(NodeExecution.objects.get)(
 workflow_execution=execution,
 node=node,
 )
 try:
 node_execution.input_data = input_data
 await sync_to_async(node_execution.mark_started)
 await self.hooks.trigger(
 "node_started",
 execution=execution,
 node_execution=node_execution,
 )
 # 获取节点处理器
 node_class = NodeRegistry.get(node.node_type)
 if not node_class:
 raise ValueError(f"未知的节点类型: {node.node_type}")
 # 构建执行上下文
 context = ExecutionContext(
 execution_id=str(execution.id),
 node_id=str(node.id),
 node_config=node.config,
 input_data=input_data,
 workflow_context=execution.context,
 previous_outputs=previous_outputs,
 workflow_execution=execution,
 node_execution=node_execution,
 )
 # 执行节点
 node_instance = node_class
 result: NodeResult = await node_instance.execute(context)
 # 处理结果
 if result.status == "completed":
 await sync_to_async(node_execution.mark_completed)(result.output)
 await self.hooks.trigger(
 "node_completed",
 execution=execution,
 node_execution=node_execution,
 )
 return {
 "status": "completed",
 "output": result.output,
 "handle": result.next_handle,
 }
 elif result.status == "waiting_approval":
 await sync_to_async(node_execution.mark_waiting_approval)(result.output)
 await self.hooks.trigger(
 "node_waiting_approval",
 execution=execution,
 node_execution=node_execution,
 )
 return {"status": "waiting_approval"}
 else:
 await sync_to_async(node_execution.mark_failed)(
 result.error or "未知错误"
 )
 await self.hooks.trigger(
 "node_failed",
 execution=execution,
 node_execution=node_execution,
 )
 return {"status": "failed", "error": result.error}
 except Exception as e:
 logger.exception(
 "node_execution_error",
 node_id=str(node.id),
 execution_id=str(execution.id),
 )
 await sync_to_async(node_execution.mark_failed)(str(e))
 await self.hooks.trigger(
 "node_failed",
 execution=execution,
 node_execution=node_execution,
 error=e,
 )
 return {"status": "failed", "error": str(e)}
 def _collect_inputs(
 self,
 dag_node,
 dag: DAG,
 node_outputs: dict,
 ) -> dict:
 """收集节点的输入数据（从上游节点输出）"""
 inputs = {}
 for source_id in dag_node.incoming:
 if source_id in node_outputs:
 # 合并上游输出到输入
 inputs.update(node_outputs[source_id])
 return inputs
 async def _skip_node(
 self, execution: WorkflowExecution, dag_node, reason: str
 ) -> None:
 """跳过节点"""
 node_execution = await sync_to_async(NodeExecution.objects.get)(
 workflow_execution=execution,
 node=dag_node.node,
 )
 await sync_to_async(node_execution.mark_skipped)(reason)
 await self.hooks.trigger(
 "node_skipped",
 execution=execution,
 node_execution=node_execution,
 )
 async def pause_execution(self, execution: WorkflowExecution) -> None:
 """暂停执行"""
 if execution.status != ExecutionStatus.RUNNING:
 raise ValueError("只能暂停运行中的执行")
 execution.status = ExecutionStatus.PAUSED
 await sync_to_async(execution.save)(update_fields=["status"])
 await self.hooks.trigger("execution_paused", execution=execution)
 async def resume_execution(self, execution: WorkflowExecution) -> None:
 """恢复执行"""
 if execution.status != ExecutionStatus.PAUSED:
 raise ValueError("只能恢复已暂停的执行")
 execution.status = ExecutionStatus.RUNNING
 await sync_to_async(execution.save)(update_fields=["status"])
 await self.hooks.trigger("execution_resumed", execution=execution)
 # TODO: 重新启动执行循环
 async def cancel_execution(self, execution: WorkflowExecution) -> None:
 """取消执行"""
 if execution.status in (ExecutionStatus.COMPLETED, ExecutionStatus.CANCELLED):
 raise ValueError("执行已完成或已取消")
 execution.status = ExecutionStatus.CANCELLED
 execution.completed_at = timezone.now
 await sync_to_async(execution.save)(update_fields=["status", "completed_at"])
 # 取消所有运行中的节点
 running_nodes = await sync_to_async(
 lambda: list(
 NodeExecution.objects.filter(
 workflow_execution=execution,
 status__in=[
 NodeExecutionStatus.RUNNING,
 NodeExecutionStatus.QUEUED,
 ],
 )
 )
 )
 for node_exec in running_nodes:
 node_exec.status = NodeExecutionStatus.CANCELLED
 await sync_to_async(node_exec.save)(update_fields=["status"])
 await self.hooks.trigger("execution_cancelled", execution=execution)
 async def approve_node(
 self,
 node_execution: NodeExecution,
 approver,
 comment: str = "",
 ) -> None:
 """审批通过节点"""
 if node_execution.status != NodeExecutionStatus.WAITING_APPROVAL:
 raise ValueError("节点不在等待审批状态")
 await sync_to_async(node_execution.approve)(approver, comment)
 await sync_to_async(node_execution.mark_completed)(node_execution.approval_data)
 await self.hooks.trigger(
 "node_approved",
 execution=node_execution.workflow_execution,
 node_execution=node_execution,
 approver=approver,
 )
 async def reject_node(
 self,
 node_execution: NodeExecution,
 approver,
 comment: str = "",
 ) -> None:
 """审批拒绝节点"""
 if node_execution.status != NodeExecutionStatus.WAITING_APPROVAL:
 raise ValueError("节点不在等待审批状态")
 await sync_to_async(node_execution.reject)(approver, comment)
 await self.hooks.trigger(
 "node_rejected",
 execution=node_execution.workflow_execution,
 node_execution=node_execution,
 approver=approver,
 )
