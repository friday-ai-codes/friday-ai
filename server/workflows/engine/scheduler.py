"""Workflow execution engine."""
import asyncio
import threading
from typing import TYPE_CHECKING
import structlog
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
 from workflows.models import Workflow
logger = structlog.get_logger
def _run_in_thread(coro):
 """Run a coroutine in a new thread with its own event loop."""
 def target:
 loop = asyncio.new_event_loop
 asyncio.set_event_loop(loop)
 try:
 loop.run_until_complete(coro)
 except Exception as e:
 logger.exception("background_task_error", error=str(e))
 finally:
 loop.close
 thread = threading.Thread(target=target, daemon=True)
 thread.start
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
 execution: WorkflowExecution | None = None,
 run_sync: bool = False,
 ) -> WorkflowExecution:
 """启动工作流执行
 Args:
 workflow: 工作流实例
 input_data: 输入数据
 triggered_by: 触发者
 trigger_type: 触发类型
 trigger_data: 触发数据
 execution: 可选的已创建执行实例（如果提供则复用，否则创建新的）
 run_sync: 是否同步执行（用于测试，确保在同一事务/上下文中运行）
 """
 input_data = input_data or {}
 trigger_data = trigger_data or {}
 # 检查并发限制
 if workflow.max_concurrent_executions > 0:
 running_count = await WorkflowExecution.objects.filter(
 workflow=workflow,
 status=ExecutionStatus.RUNNING,
 ).acount
 if running_count >= workflow.max_concurrent_executions:
 raise ValueError(f"工作流已达到最大并发数 ({workflow.max_concurrent_executions})")
 # 使用已有执行实例或创建新的
 if execution is None:
 execution = await WorkflowExecution.objects.acreate(
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
 else:
 # 确保执行状态正确
 execution.status = ExecutionStatus.PENDING
 await execution.asave(update_fields=["status"])
 # 构建 DAG
 dag = await DAG.afrom_workflow(workflow)
 errors = dag.validate
 if errors:
 await execution.amark_failed("\n".join(errors))
 return execution
 # 初始化节点执行记录
 execution.total_nodes = len(dag.nodes)
 await execution.asave(update_fields=["total_nodes"])
 for dag_node in dag.nodes.values:
 await NodeExecution.objects.acreate(
 workflow_execution=execution,
 node=dag_node.node,
 status=NodeExecutionStatus.PENDING,
 )
 # 触发开始钩子
 await self.hooks.trigger("execution_started", execution=execution)
 # 开始执行
 if run_sync:
 # 同步执行（用于测试，保持在同一事务/上下文中）
 await self._run_execution(execution, dag, input_data)
 else:
 # 异步执行（在独立线程中运行，避免事件循环退出问题）
 _run_in_thread(self._run_execution(execution, dag, input_data))
 return execution
 async def _run_execution(
 self,
 execution: WorkflowExecution,
 dag: DAG,
 input_data: dict,
 ) -> None:
 """执行工作流主循环"""
 try:
 await execution.amark_started
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
 any_dep_failed = any(dep_id in failed_nodes for dep_id in dag_node.incoming)
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
 # 检查是否有正在等待审批或等待事件的节点
 waiting_nodes = [
 ne async for ne in NodeExecution.objects.filter(
 workflow_execution=execution,
 status__in=[
 NodeExecutionStatus.WAITING_APPROVAL,
 NodeExecutionStatus.WAITING_EVENT,
 ],
 )
 ]
 if waiting_nodes:
 # Check if ALL remaining pending nodes are in waiting states
 # If so, we can truly suspend and release resources
 all_blocked = True
 for node_id in pending_nodes:
 # Check if this pending node is in waiting state
 ne = await NodeExecution.objects.filter(
 workflow_execution=execution,
 node_id=node_id,
 ).afirst
 if ne and ne.status not in [
 NodeExecutionStatus.WAITING_APPROVAL,
 NodeExecutionStatus.WAITING_EVENT,
 ]:
 all_blocked = False
 break
 if all_blocked:
 # All paths are blocked on external events - truly suspend
 logger.info(
 "workflow_suspended",
 execution_id=str(execution.id),
 waiting_nodes=len(waiting_nodes),
 )
 await execution.amark_suspended
 await self.hooks.trigger("execution_suspended", execution=execution)
 # Exit the loop - webhook will restart via _continue_after_node
 return
 else:
 # Some nodes might become ready (e.g., approval being processed)
 # Keep polling
 await asyncio.sleep(5)
 # 刷新状态
 for ne in waiting_nodes:
 await ne.arefresh_from_db
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
 tasks.append(self._execute_node(execution, dag_node, node_input, node_outputs))
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
 output = result.get("output", {})
 node_outputs[dag_node.id] = output
 # Also store by short_id for template variable support
 if hasattr(dag_node.node, "short_id") and dag_node.node.short_id:
 node_outputs[dag_node.node.short_id] = output
 elif result.get("status") == "waiting_approval":
 # 节点正在等待审批，保持在 pending
 pending_nodes.add(dag_node.id)
 elif result.get("status") == "waiting_event":
 # 节点正在等待外部事件，不加回 pending
 # 循环会检测到 waiting 节点并挂起 workflow
 pass
 else:
 failed_nodes.add(dag_node.id)
 # 检查超时
 await execution.arefresh_from_db
 if execution.timeout_at and timezone.now > execution.timeout_at:
 execution.status = ExecutionStatus.TIMEOUT
 await execution.asave(update_fields=["status"])
 await self.hooks.trigger("execution_timeout", execution=execution)
 return
 # 执行完成
 if failed_nodes:
 await execution.amark_failed(f"失败节点: {len(failed_nodes)}")
 else:
 # 收集最终输出（终端节点的输出）
 final_output = {}
 for node_id in completed_nodes:
 dag_node = dag.nodes.get(node_id)
 if dag_node and not dag_node.outgoing:
 final_output.update(node_outputs.get(node_id, {}))
 await execution.amark_completed(final_output)
 await self.hooks.trigger("execution_completed", execution=execution)
 except Exception as e:
 logger.exception("workflow_execution_error", execution_id=str(execution.id))
 await execution.amark_failed(str(e))
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
 node_execution = await NodeExecution.objects.aget(
 workflow_execution=execution,
 node=node,
 )
 try:
 await node_execution.amark_started(input_data)
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
 # Persist handle info in output_data for _continue_after_node routing
 output_with_handle = {**(result.output or {})}
 if result.next_handle and result.next_handle != "default":
 output_with_handle["_next_handle"] = result.next_handle
 await node_execution.amark_completed(output_with_handle)
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
 await node_execution.amark_waiting_approval(result.output)
 await self.hooks.trigger(
 "node_waiting_approval",
 execution=execution,
 node_execution=node_execution,
 )
 return {"status": "waiting_approval"}
 elif result.status == "waiting_event":
 await node_execution.amark_waiting_event(result.output)
 await self.hooks.trigger(
 "node_waiting_event",
 execution=execution,
 node_execution=node_execution,
 )
 return {"status": "waiting_event"}
 else:
 await node_execution.amark_failed(result.error or "未知错误")
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
 await node_execution.amark_failed(str(e))
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
 async def _skip_node(self, execution: WorkflowExecution, dag_node, reason: str) -> None:
 """跳过节点"""
 node_execution = await NodeExecution.objects.aget(
 workflow_execution=execution,
 node=dag_node.node,
 )
 await node_execution.amark_skipped(reason)
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
 await execution.asave(update_fields=["status"])
 await self.hooks.trigger("execution_paused", execution=execution)
 async def resume_execution(self, execution: WorkflowExecution) -> None:
 """恢复执行"""
 if execution.status != ExecutionStatus.PAUSED:
 raise ValueError("只能恢复已暂停的执行")
 execution.status = ExecutionStatus.RUNNING
 await execution.asave(update_fields=["status"])
 await self.hooks.trigger("execution_resumed", execution=execution)
 raise NotImplementedError("恢复执行循环未实现")
 async def cancel_execution(self, execution: WorkflowExecution) -> None:
 """取消执行"""
 if execution.status in (ExecutionStatus.COMPLETED, ExecutionStatus.CANCELLED):
 raise ValueError("执行已完成或已取消")
 execution.status = ExecutionStatus.CANCELLED
 execution.completed_at = timezone.now
 await execution.asave(update_fields=["status", "completed_at"])
 # 取消所有运行中的节点
 running_nodes = [
 ne async for ne in NodeExecution.objects.filter(
 workflow_execution=execution,
 status__in=[
 NodeExecutionStatus.RUNNING,
 NodeExecutionStatus.QUEUED,
 ],
 )
 ]
 for node_exec in running_nodes:
 node_exec.status = NodeExecutionStatus.CANCELLED
 await node_exec.asave(update_fields=["status"])
 await self.hooks.trigger("execution_cancelled", execution=execution)
 async def approve_node(
 self,
 node_execution: NodeExecution,
 approver,
 comment: str = "",
 ) -> None:
 """审批通过节点"""
 if node_execution.status not in [
 NodeExecutionStatus.WAITING_APPROVAL,
 NodeExecutionStatus.WAITING_EVENT,
 ]:
 raise ValueError("节点不在等待审批状态")
 await node_execution.aapprove(approver, comment)
 # Build output: preserve original data + set next_handle for routing
 approval_output = {
 **(node_execution.approval_data or {}),
 "_next_handle": "approved",
 }
 await node_execution.amark_completed(approval_output)
 await self.hooks.trigger(
 "node_approved",
 execution=node_execution.workflow_execution,
 node_execution=node_execution,
 approver=approver,
 )
 # Continue workflow execution from approved port
 node_execution = await NodeExecution.objects.select_related("workflow_execution").aget(id=node_execution.id)
 execution = node_execution.workflow_execution
 await self._continue_after_node(execution, node_execution)
 async def reject_node(
 self,
 node_execution: NodeExecution,
 approver,
 comment: str = "",
 ) -> None:
 """审批拒绝节点
 Per Phase design: reject marks node as completed (not failed)
 with next_handle="rejected", allowing workflow to route through
 the rejected output port.
 """
 if node_execution.status not in [
 NodeExecutionStatus.WAITING_APPROVAL,
 NodeExecutionStatus.WAITING_EVENT,
 ]:
 raise ValueError("节点不在等待审批状态")
 # Update approval_data with rejection info (without calling mark_failed)
 await node_execution.arefresh_from_db
 node_execution.approval_data.update(
 {
 "approved": False,
 "approver_id": approver.id if approver else None,
 "approver_name": approver.username if approver else "",
 "comment": comment,
 "rejected_at": timezone.now.isoformat,
 }
 )
 await node_execution.asave(update_fields=["approval_data"])
 # Mark completed (NOT failed) with next_handle="rejected" for routing
 original_data = node_execution.approval_data or {}
 reject_output = {
 **original_data,
 "_next_handle": "rejected",
 "reject_reason": comment,
 "rejected_by": str(approver) if approver else "",
 }
 await node_execution.amark_completed(reject_output)
 await self.hooks.trigger(
 "node_rejected",
 execution=node_execution.workflow_execution,
 node_execution=node_execution,
 approver=approver,
 )
 # Continue workflow execution from rejected port
 node_execution = await NodeExecution.objects.select_related("workflow_execution").aget(id=node_execution.id)
 execution = node_execution.workflow_execution
 await self._continue_after_node(execution, node_execution)
 async def trigger_manual_node(
 self,
 node_execution: NodeExecution,
 input_data: dict | None = None,
 ) -> None:
 """触发等待中的手动触发节点"""
 if node_execution.status != NodeExecutionStatus.PENDING:
 raise ValueError("节点不在等待触发状态")
 if node_execution.node.node_type != "manual_trigger":
 raise ValueError("只有手动触发节点可以被触发")
 input_data = input_data or {}
 node_execution = await NodeExecution.objects.select_related("workflow_execution").aget(id=node_execution.id)
 execution = node_execution.workflow_execution
 # 更新执行的输入数据
 execution.input_data = input_data
 await execution.asave(update_fields=["input_data"])
 # 标记节点开始执行
 node_execution.input_data = input_data
 await node_execution.amark_started
 await self.hooks.trigger(
 "node_started",
 execution=execution,
 node_execution=node_execution,
 )
 # 直接完成手动触发节点（将输入数据作为输出）
 await node_execution.amark_completed(input_data)
 await self.hooks.trigger(
 "node_completed",
 execution=execution,
 node_execution=node_execution,
 )
 # 直接执行后续节点（同步方式，确保错误信息正确保存）
 await self._continue_after_node(execution, node_execution)
 async def _continue_after_node(
 self,
 execution: WorkflowExecution,
 node_execution: NodeExecution,
 ) -> None:
 """Continue workflow execution after a node completes via callback.
 This is called when a container-based node (like CodeImplementNode)
 reports completion through the callback API.
 """
 # Trigger completion hook
 await self.hooks.trigger(
 "node_completed",
 execution=execution,
 node_execution=node_execution,
 )
 # Get the workflow and rebuild DAG
 execution = await WorkflowExecution.objects.select_related("workflow").aget(id=execution.id)
 workflow = execution.workflow
 dag = await DAG.afrom_workflow(workflow)
 # Find successor nodes
 completed_node_id = str(node_execution.node_id)
 dag_node = dag.nodes.get(completed_node_id)
 if not dag_node:
 logger.warning(
 "callback_node_not_in_dag",
 node_id=completed_node_id,
 execution_id=str(execution.id),
 )
 return
 # Check if there are successor nodes to execute
 if not dag_node.outgoing:
 # This was a terminal node - check if execution is complete
 await self._check_execution_complete(execution)
 return
 # Read next_handle from output_data for handle-based routing
 output_data = node_execution.output_data or {}
 next_handle = output_data.get("_next_handle", "default")
 # Use dag.get_successors to route by handle
 successors = dag.get_successors(completed_node_id, next_handle)
 # Fallback to "default" handle if specified handle has no successors
 if not successors and next_handle != "default":
 successors = dag.get_successors(completed_node_id, "default")
 if not successors:
 # Terminal node - check if execution is complete
 await self._check_execution_complete(execution)
 return
 # Collect all node outputs for context
 node_outputs = await self._collect_all_outputs(execution)
 # Execute successor nodes that are now ready
 for successor_dag_node in successors:
 # Check if all dependencies are satisfied
 all_deps_ready = await self._check_dependencies_ready(execution, successor_dag_node)
 if all_deps_ready:
 # Get successor's node execution
 successor_exec = await NodeExecution.objects.filter(
 workflow_execution=execution,
 node_id=successor_dag_node.id,
 status=NodeExecutionStatus.PENDING,
 ).afirst
 if successor_exec:
 # Collect inputs and execute
 input_data = self._collect_inputs(successor_dag_node, dag, node_outputs)
 result = await self._execute_node(
 execution, successor_dag_node, input_data, node_outputs
 )
 # Recursive: if successor also completed immediately, continue its downstream
 if isinstance(result, dict) and result.get("status") == "completed":
 successor_ne = await NodeExecution.objects.filter(
 workflow_execution=execution,
 node_id=successor_dag_node.id,
 status=NodeExecutionStatus.COMPLETED,
 ).afirst
 if successor_ne:
 await self._continue_after_node(execution, successor_ne)
 async def _handle_node_failure(
 self,
 execution: WorkflowExecution,
 node_execution: NodeExecution,
 ) -> None:
 """Handle node failure from callback.
 Updates workflow status and triggers failure hooks.
 """
 # Trigger failure hook
 await self.hooks.trigger(
 "node_failed",
 execution=execution,
 node_execution=node_execution,
 )
 # Check if we should fail the entire workflow
 # For now, any node failure fails the workflow
 await execution.amark_failed(
 f"节点 {node_execution.node.name} 执行失败: {node_execution.error_message}"
 )
 await self.hooks.trigger("execution_failed", execution=execution)
 async def _check_execution_complete(self, execution: WorkflowExecution) -> None:
 """Check if workflow execution is complete and update status."""
 # Count node statuses
 base_qs = NodeExecution.objects.filter(workflow_execution=execution)
 stats = {
 "pending": await base_qs.filter(status=NodeExecutionStatus.PENDING).acount,
 "running": await base_qs.filter(status=NodeExecutionStatus.RUNNING).acount,
 "waiting": await base_qs.filter(
 status__in=[
 NodeExecutionStatus.WAITING_APPROVAL,
 NodeExecutionStatus.WAITING_EVENT,
 ],
 ).acount,
 "failed": await base_qs.filter(status=NodeExecutionStatus.FAILED).acount,
 }
 if stats["pending"] == 0 and stats["running"] == 0 and stats["waiting"] == 0:
 # All nodes are done
 if stats["failed"] > 0:
 await execution.amark_failed(f"失败节点: {stats['failed']}")
 else:
 # Collect final outputs
 final_output = await self._collect_final_outputs(execution)
 await execution.amark_completed(final_output)
 await self.hooks.trigger("execution_completed", execution=execution)
 async def _check_dependencies_ready(
 self,
 execution: WorkflowExecution,
 dag_node,
 ) -> bool:
 """Check if all dependencies of a node are completed."""
 for dep_id in dag_node.incoming:
 dep_exec = await NodeExecution.objects.filter(
 workflow_execution=execution,
 node_id=dep_id,
 ).afirst
 if not dep_exec or dep_exec.status != NodeExecutionStatus.COMPLETED:
 return False
 return True
 async def _collect_all_outputs(self, execution: WorkflowExecution) -> dict:
 """Collect outputs from all completed nodes."""
 completed_nodes = [
 ne async for ne in NodeExecution.objects.filter(
 workflow_execution=execution,
 status=NodeExecutionStatus.COMPLETED,
 ).select_related("node")
 ]
 outputs = {}
 for node_exec in completed_nodes:
 outputs[str(node_exec.node_id)] = node_exec.output_data or {}
 return outputs
 async def _collect_final_outputs(self, execution: WorkflowExecution) -> dict:
 """Collect outputs from terminal nodes."""
 # Get workflow and DAG
 execution = await WorkflowExecution.objects.select_related("workflow").aget(id=execution.id)
 workflow = execution.workflow
 dag = await DAG.afrom_workflow(workflow)
 # Find terminal nodes (no outgoing edges)
 terminal_node_ids = [
 node_id for node_id, dag_node in dag.nodes.items if not dag_node.outgoing
 ]
 # Get their outputs
 terminal_outputs = [
 ne async for ne in NodeExecution.objects.filter(
 workflow_execution=execution,
 node_id__in=terminal_node_ids,
 status=NodeExecutionStatus.COMPLETED,
 )
 ]
 final_output = {}
 for node_exec in terminal_outputs:
 if node_exec.output_data:
 final_output.update(node_exec.output_data)
 return final_output
