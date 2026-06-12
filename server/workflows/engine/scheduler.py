"""Workflow execution engine."""

import asyncio
import json
import random
import threading
import time
from collections import deque
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

import structlog
from asgiref.sync import sync_to_async
from django.db import transaction
from django.utils import timezone
from rest_framework.exceptions import PermissionDenied

from workflows.engine.dag import DAG
from workflows.engine.template_resolver import TemplateResolutionError
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

logger = structlog.get_logger()


def _run_in_thread(coro):
    """Run a coroutine in a new thread with its own event loop."""

    def target():
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            loop.run_until_complete(coro)
        except Exception as e:
            logger.exception("background_task_error", error=str(e))
        finally:
            loop.close()

    thread = threading.Thread(target=target, daemon=True)
    thread.start()


@dataclass
class DebugSession:
    """调试会话状态——存储暂停/释放的协调信息。"""

    execution_id: str
    loop: asyncio.AbstractEventLoop
    event: asyncio.Event = field(default_factory=asyncio.Event)
    current_node_id: str | None = None
    debug_action: str = ""  # release / skip / timeout / cancel
    action_data: dict[str, Any] = field(default_factory=dict)
    created_at: float = field(default_factory=time.time)
    breakpoints: set[str] = field(default_factory=set)  # 断点节点 ID 集合
    debug_mode: str = "step"  # "step" | "breakpoint"


_debug_sessions: dict[str, DebugSession] = {}


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
        from workflows.hooks.builtin import (
            LoggingHook,
            NotificationHook,
            WebSocketBroadcastHook,
        )

        self.hooks = hooks or HookManager()

        # Register built-in hooks
        logging_hook = LoggingHook()
        websocket_hook = WebSocketBroadcastHook()
        notification_hook = NotificationHook()

        for event in HookManager.EVENTS:
            self.hooks.register_hook(event, logging_hook)
            self.hooks.register_hook(event, websocket_hook)

        for event in (
            "execution_completed",
            "execution_failed",
            "node_waiting_approval",
        ):
            self.hooks.register_hook(event, notification_hook)

        # AlertRuleHook: 告警规则引擎
        from workflows.hooks.builtin import AlertRuleHook

        alert_rule_hook = AlertRuleHook()
        for event in (
            "execution_failed",
            "execution_timeout",
            "execution_completed",
            "node_failed",
        ):
            self.hooks.register_hook(event, alert_rule_hook)

        # FeishuSyncHook: 飞书卡片状态同步
        # execute() 内部有 event_map 路由，对未处理事件是 no-op，注册所有事件安全
        from workflows.hooks.feishu_sync import FeishuSyncHook

        feishu_hook = FeishuSyncHook()
        for event in HookManager.EVENTS:
            self.hooks.register_hook(event, feishu_hook)

    async def _load_execution_for_hooks(self, execution: WorkflowExecution) -> WorkflowExecution:
        """Load execution with related objects to keep hook handlers async-safe."""
        return await WorkflowExecution.objects.select_related(
            "workflow__project",
            "project",
        ).aget(pk=execution.pk)

    @staticmethod
    def _map_error_code(exception: Exception) -> str:
        """将异常映射为 WorkflowErrorCode 值。"""
        import httpx

        if isinstance(exception, asyncio.TimeoutError):
            return "timeout"
        if isinstance(exception, PermissionDenied):
            return "permission"
        # 资源相关异常（OSError 涵盖内存/磁盘不足；docker 异常在容器节点中可能抛出）
        if isinstance(exception, OSError):
            return "resource"
        # 外部 API 异常
        if isinstance(exception, (httpx.TimeoutException, httpx.ConnectError,
                                  httpx.HTTPError, httpx.HTTPStatusError)):
            return "api"
        # 通用 Python 异常 / 节点逻辑错误
        if isinstance(exception, Exception):
            return "runtime"
        return "unknown"

    @staticmethod
    def _create_execution_with_atomic_concurrency_guard(
        *,
        workflow_id: Any,
        max_concurrent_executions: int,
        trigger_type: str,
        triggered_by_id: Any = None,
        trigger_data: dict[str, Any] | None = None,
        input_data: dict[str, Any] | None = None,
        workflow_definition: dict[str, Any] | None = None,
        context: dict[str, Any] | None = None,
    ) -> WorkflowExecution:
        """Atomically check active executions and create the pending execution."""
        trigger_data = trigger_data or {}
        input_data = input_data or {}
        workflow_definition = workflow_definition or {}
        context = context or {}

        with transaction.atomic():
            # Lock workflow row to serialize concurrent start requests per workflow.
            from workflows.models import Workflow

            workflow = Workflow.objects.select_for_update().get(pk=workflow_id)

            if max_concurrent_executions > 0:
                active_count = WorkflowExecution.objects.select_for_update().filter(
                    workflow_id=workflow_id,
                    status__in=[ExecutionStatus.PENDING, ExecutionStatus.RUNNING],
                    is_debug=False,  # 调试执行不计入并发限制
                ).count()
                if active_count >= max_concurrent_executions:
                    raise ValueError(f"工作流已达到最大并发数 ({max_concurrent_executions})")

            return WorkflowExecution.objects.create(
                workflow_id=workflow_id,
                project_id=workflow.project_id,
                status=ExecutionStatus.PENDING,
                trigger_type=trigger_type,
                triggered_by_id=triggered_by_id,
                trigger_data=trigger_data,
                input_data=input_data,
                workflow_definition=workflow_definition,
                context=context,
            )

    async def start_execution(
        self,
        workflow: "Workflow",
        input_data: dict | None = None,
        triggered_by=None,
        trigger_type: str = "manual",
        trigger_data: dict | None = None,
        execution: WorkflowExecution | None = None,
        run_sync: bool = False,
        debug_mode: bool = False,
        stop_before_node_id: str | None = None,
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
            debug_mode: 是否以调试模式启动（逐节点暂停）
            stop_before_node_id: 单节点测试：执行到该节点前停止
        """
        input_data = input_data or {}
        trigger_data = trigger_data or {}

        # Ensure related project is preloaded to keep hook execution async-safe.
        if "project" not in workflow._state.fields_cache:
            from workflows.models import Workflow as WorkflowModel

            workflow = await WorkflowModel.objects.select_related("project").aget(pk=workflow.pk)

        # 构建 workflow_definition 快照（DAG 结构 + 节点位置，用于前端可视化）
        nodes_snapshot: list[dict] = []
        async for node in workflow.nodes.all():
            nodes_snapshot.append({
                "id": str(node.id),
                "name": node.name,
                "node_type": node.node_type,
                "position": {"x": node.position_x, "y": node.position_y},
                "config": node.config or {},
            })
        edges_snapshot: list[dict] = []
        async for edge in workflow.edges.all():
            edges_snapshot.append({
                "id": str(edge.id),
                "source": str(edge.source_node_id),
                "target": str(edge.target_node_id),
                "sourcePort": edge.source_handle or "default",
                "targetPort": edge.target_handle or "default",
            })

        # 使用已有执行实例或创建新的
        if execution is None:
            execution = await sync_to_async(
                self._create_execution_with_atomic_concurrency_guard,
                thread_sensitive=True,
            )(
                workflow_id=workflow.id,
                max_concurrent_executions=workflow.max_concurrent_executions,
                trigger_type=trigger_type,
                triggered_by_id=triggered_by.id if triggered_by else None,
                trigger_data=trigger_data,
                input_data=input_data,
                workflow_definition={
                    "nodes": nodes_snapshot,
                    "edges": edges_snapshot,
                },
                context={
                    "workflow_id": str(workflow.id),
                    "workflow_name": workflow.name,
                    "started_at": timezone.now().isoformat(),
                },
            )
        else:
            if workflow.max_concurrent_executions > 0:
                active_count = await WorkflowExecution.objects.filter(
                    workflow=workflow,
                    status__in=[ExecutionStatus.PENDING, ExecutionStatus.RUNNING],
                ).exclude(pk=execution.pk).acount()
                if active_count >= workflow.max_concurrent_executions:
                    raise ValueError(f"工作流已达到最大并发数 ({workflow.max_concurrent_executions})")
            # 确保执行状态正确
            execution.status = ExecutionStatus.PENDING
            await execution.asave(update_fields=["status"])

        # Cache related objects on execution to avoid sync FK lazy-load in async hooks.
        execution.workflow = workflow
        execution.project_id = workflow.project_id
        if "project" in workflow._state.fields_cache:
            execution.project = workflow.project

        # 设置调试模式标记（需在失败路径触发 hook 前生效，保证 debug 执行不发通知）
        if debug_mode and not execution.is_debug:
            execution.is_debug = True
            await execution.asave(update_fields=["is_debug"])

        # 构建 DAG
        dag = await DAG.afrom_workflow(workflow)
        errors = dag.validate()
        if errors:
            await execution.amark_failed("\n".join(errors))
            hook_execution = await self._load_execution_for_hooks(execution)
            await self.hooks.trigger("execution_failed", execution=hook_execution)
            return execution

        # 初始化节点执行记录
        execution.total_nodes = len(dag.nodes)
        await execution.asave(update_fields=["total_nodes"])

        for dag_node in dag.nodes.values():
            await NodeExecution.objects.acreate(
                workflow_execution=execution,
                node=dag_node.node,
                status=NodeExecutionStatus.PENDING,
            )

        # implementation contract contract：Execution 启动时统一快照 AI 节点 Provider，
        # 保证 Replay 稳定（后续项目 default_provider_credential_id 修改不影响本 Execution）。
        try:
            snapshots = await self._snapshot_ai_node_providers(dag, execution)
        except Exception as snap_err:  # noqa: BLE001
            logger.exception(
                "snapshot.ai_node_providers_helper_failed",
                execution_id=str(execution.id),
                error=str(snap_err),
            )
            snapshots = {}
        if snapshots:
            current_ctx = execution.context or {}
            current_ctx["node_snapshots"] = snapshots
            execution.context = current_ctx
            await execution.asave(update_fields=["context"])

        # 触发开始钩子
        await self.hooks.trigger("execution_started", execution=execution)

        # 开始执行
        if run_sync:
            # 同步执行（用于测试，保持在同一事务/上下文中）
            await self._run_execution(execution, dag, input_data, stop_before_node_id=stop_before_node_id)
        else:
            # 异步执行（在独立线程中运行，避免事件循环退出问题）
            _run_in_thread(self._run_execution(execution, dag, input_data, stop_before_node_id=stop_before_node_id))

        return execution

    # implementation contract contract：AI 节点白名单（Execution 启动时遍历 DAG 统一快照）
    _AI_NODE_TYPES: set[str] = {
        "ai_prompt",
        "ai_variable_extractor",
        "ai_plan_generation",
        "ai_code_review",
        "ai_coding",
        "ai_coding_dispatcher",
    }

    async def _snapshot_ai_node_providers(
        self,
        dag: "DAG",
        workflow_execution: WorkflowExecution,
    ) -> dict[str, dict]:
        """contract：Execution 启动时遍历 DAG AI 节点，统一快照 resolved Provider。

        Miss 节点（ProviderMissingError）不写入——运行时节点 runner 会再次 aresolve
        并抛正常错误（base_agent._resolve_from_snapshot_or_runtime miss fallback）。

        Args:
            dag: 构建好的 DAG（从 workflow 加载）
            workflow_execution: 当前 Execution 实例（project 需已预取）

        Returns:
            dict shape: {node_id: {provider_type: str, model: str,
                         source: str, credential_id: str | None}}
            JSON 序列化安全（ProviderType enum 转 str；UUID 转 str）。
        """
        from services.provider_config import (
            ProviderConfigService,
            ProviderMissingError,
            ResolvedProviderConfig,
        )

        # 确保 project 可读（start_execution 主路径已预填 workflow + project 缓存）
        project = getattr(workflow_execution, "project", None)

        snapshots: dict[str, dict] = {}
        for dag_node in dag.nodes.values():
            node = getattr(dag_node, "node", None)
            node_type = getattr(node, "node_type", None)
            if node_type not in self._AI_NODE_TYPES:
                continue

            node_config = getattr(node, "config", None) or {}
            try:
                result = await ProviderConfigService.aresolve_or_error(
                    node_config=node_config,
                    conversation=None,  # workflow 无 conversation 维度
                    project=project,
                )
            except Exception as exc:  # noqa: BLE001
                logger.exception(
                    "snapshot.aresolve_failed",
                    execution_id=str(workflow_execution.id),
                    node_id=str(getattr(node, "id", "")),
                    node_type=node_type,
                    error=str(exc),
                )
                continue

            if isinstance(result, ProviderMissingError):
                # contract 契约：miss 节点不写入，运行时 runner fallback 统一处理
                continue

            if isinstance(result, ResolvedProviderConfig):
                provider_type_str = str(result.provider_type).replace(
                    "ProviderType.", ""
                )
                # enum 的 str()/.value 可能返回 "ProviderType.ANTHROPIC" 或 "anthropic"；
                # 统一读 .value 保持 JSON 友好字符串
                if hasattr(result.provider_type, "value"):
                    provider_type_str = result.provider_type.value

                # model 优先读 node_config.model；fallback 到 resolved.extra["model"]
                snap_model = (
                    node_config.get("model")
                    or (result.extra or {}).get("model")
                    or ""
                )
                snap_credential_id = (
                    str(result.credential_id) if result.credential_id else None
                )
                snapshots[str(node.id)] = {
                    "provider_type": provider_type_str,
                    "model": snap_model,
                    "source": result.source,
                    "credential_id": snap_credential_id,
                }

        logger.info(
            "snapshot.ai_node_providers_written",
            execution_id=str(workflow_execution.id),
            count=len(snapshots),
        )
        return snapshots

    async def _debug_pause_after_node(
        self,
        execution: WorkflowExecution,
        node_execution: NodeExecution,
    ) -> tuple[str, dict[str, Any]]:
        """节点执行完后暂停，等待用户调试操作。返回 (action, action_data)。"""
        loop = asyncio.get_event_loop()
        session = _debug_sessions.get(str(execution.id))
        if not session:
            session = DebugSession(execution_id=str(execution.id), loop=loop)
            _debug_sessions[str(execution.id)] = session

        # 每次暂停时创建新 Event，确保 Event 属于当前 event loop
        session.event = asyncio.Event()
        session.current_node_id = str(node_execution.node_id)
        session.debug_action = ""
        session.action_data = {}
        session.loop = loop

        execution.debug_paused_at_node = node_execution.node_id
        await execution.asave(update_fields=["debug_paused_at_node"])
        await self.hooks.trigger("node_debug_paused", execution=execution, node_execution=node_execution)

        try:
            await asyncio.wait_for(session.event.wait(), timeout=1800)
        except asyncio.TimeoutError:
            session.debug_action = "timeout"
            logger.warning("debug_session_timeout", execution_id=str(execution.id))

        execution.debug_paused_at_node = None
        await execution.asave(update_fields=["debug_paused_at_node"])

        action = session.debug_action or "release"
        action_data = session.action_data.copy()

        # 超时或取消时清理会话
        if action in ("timeout", "cancel"):
            _debug_sessions.pop(str(execution.id), None)

        return action, action_data

    @classmethod
    def release_debug_node(
        cls,
        execution_id: str,
        action: str = "release",
        action_data: dict[str, Any] | None = None,
    ) -> bool:
        """由 WS Consumer 调用，跨线程释放调试暂停。"""
        session = _debug_sessions.get(execution_id)
        if not session:
            return False
        session.debug_action = action
        session.action_data = action_data or {}
        session.loop.call_soon_threadsafe(session.event.set)
        return True

    async def _run_execution(
        self,
        execution: WorkflowExecution,
        dag: DAG,
        input_data: dict,
        initial_outputs: dict[str, dict] | None = None,
        is_resume: bool = False,
        stop_before_node_id: str | None = None,
    ) -> None:
        """执行工作流主循环

        Args:
            execution: 执行实例
            dag: DAG 实例
            input_data: 输入数据
            initial_outputs: 预填充的节点输出（从失败节点继续时，包含 skipped 节点的输出）
            is_resume: 是否从暂停恢复（跳过 amark_started 避免覆盖 started_at）
            stop_before_node_id: 单节点测试：执行到该节点前停止
        """
        try:
            if not is_resume:
                await execution.amark_started()
            await self.hooks.trigger("execution_running", execution=execution)

            # 节点输出缓存
            node_outputs: dict[str, dict] = {}

            # 节点完成状态
            completed_nodes: set[str] = set()
            failed_nodes: set[str] = set()
            skipped_nodes: set[str] = set()
            tolerated_failures: set[str] = set()  # on_error=ignore 的失败节点

            # 待处理节点
            pending_nodes = set(dag.nodes.keys())

            # 预填充 skipped 节点的输出（从失败节点继续场景）
            if initial_outputs:
                node_outputs.update(initial_outputs)
                # 从数据库查询 skipped 节点，将其加入 completed/skipped 集合
                skipped_ne_list = [
                    ne async for ne in NodeExecution.objects.filter(
                        workflow_execution=execution,
                        status=NodeExecutionStatus.SKIPPED,
                    )
                ]
                for ne in skipped_ne_list:
                    node_id = str(ne.node_id)
                    skipped_nodes.add(node_id)
                    completed_nodes.add(node_id)
                    pending_nodes.discard(node_id)

            # 入口节点的输入数据
            entry_inputs = {dag_node.id: input_data for dag_node in dag.get_entry_nodes()}

            while pending_nodes:
                # 找出可以执行的节点（所有前置已完成）
                ready_nodes = []
                nodes_to_remove = []

                for node_id in pending_nodes:
                    dag_node = dag.nodes[node_id]

                    # 用 forward_incoming 检查依赖（排除反馈环 back-edge）
                    forward_deps = dag_node.forward_incoming

                    all_deps_completed = all(
                        dep_id in completed_nodes or dep_id in skipped_nodes
                        for dep_id in forward_deps
                    )

                    any_dep_failed = any(dep_id in failed_nodes for dep_id in forward_deps)

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

                # 单节点测试：检查是否到达 stop_before 节点
                if stop_before_node_id:
                    stop_node = next((n for n in ready_nodes if n.id == stop_before_node_id), None)
                    if stop_node:
                        ready_nodes.remove(stop_node)
                        # 将 stop_before 及其下游从 pending 中移除
                        downstream = self._get_downstream_nodes(dag, stop_before_node_id)
                        pending_nodes.discard(stop_before_node_id)
                        for ds_id in downstream:
                            pending_nodes.discard(ds_id)
                            ds_dag_node = dag.nodes.get(ds_id)
                            if ds_dag_node:
                                await self._skip_node(execution, ds_dag_node, "单节点测试：上游已停止")
                                skipped_nodes.add(ds_id)
                        logger.info(
                            "execution_stop_before_node",
                            execution_id=str(execution.id),
                            stop_before_node_id=stop_before_node_id,
                            downstream_removed=len(downstream),
                        )
                        # 如果移除后没有可执行节点，正常完成
                        if not ready_nodes and not pending_nodes:
                            final_output = {}
                            for nid in completed_nodes:
                                dnode = dag.nodes.get(nid)
                                if dnode and not dnode.outgoing:
                                    final_output.update(node_outputs.get(nid, {}))
                            await execution.amark_completed(final_output)
                            hook_execution = await self._load_execution_for_hooks(execution)
                            await self.hooks.trigger("execution_completed", execution=hook_execution)
                            return

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
                            ).afirst()
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
                            await execution.amark_suspended()
                            await self.hooks.trigger("execution_suspended", execution=execution)
                            # Exit the loop - webhook will restart via _continue_after_node
                            return
                        else:
                            # Some nodes might become ready (e.g., approval being processed)
                            # Keep polling
                            await asyncio.sleep(5)
                            # 刷新状态
                            for ne in waiting_nodes:
                                await ne.arefresh_from_db()
                                if ne.status == NodeExecutionStatus.COMPLETED:
                                    completed_nodes.add(str(ne.node_id))
                                    node_outputs[str(ne.node_id)] = ne.output_data
                                    pending_nodes.discard(str(ne.node_id))
                                elif ne.status == NodeExecutionStatus.FAILED:
                                    failed_nodes.add(str(ne.node_id))
                                    pending_nodes.discard(str(ne.node_id))
                            continue
                    else:
                        # 死锁：有 pending 节点但没有任何节点可以调度
                        if pending_nodes:
                            logger.error(
                                "workflow_deadlock",
                                execution_id=str(execution.id),
                                pending_nodes=list(pending_nodes),
                            )
                            pending_names = []
                            for nid in pending_nodes:
                                dn = dag.nodes.get(nid)
                                if dn:
                                    pending_names.append(dn.node.name)
                            await execution.amark_failed(
                                f"工作流死锁：{len(pending_nodes)} 个节点无法调度 ({', '.join(pending_names)})"
                            )
                            hook_execution = await self._load_execution_for_hooks(execution)
                            await self.hooks.trigger("execution_failed", execution=hook_execution)
                            return
                        break

                # 调试模式：串行执行，每次逐节点暂停
                if execution.is_debug:
                    for dag_node in ready_nodes:
                        if dag_node.id in entry_inputs:
                            node_input = entry_inputs[dag_node.id]
                        else:
                            node_input = self._collect_inputs(dag_node, dag, node_outputs)
                        result = await self._execute_node(execution, dag_node, node_input, node_outputs)
                        pending_nodes.discard(dag_node.id)

                        if isinstance(result, Exception):
                            failed_nodes.add(dag_node.id)
                        elif result.get("status") == "completed":
                            completed_nodes.add(dag_node.id)
                            output = result.get("output", {})
                            node_outputs[dag_node.id] = output
                            if hasattr(dag_node, 'node') and hasattr(dag_node.node, 'short_id') and dag_node.node.short_id:
                                node_outputs[dag_node.node.short_id] = output

                            # 断点模式条件暂停：仅断点节点暂停，非断点节点自动放行
                            session = _debug_sessions.get(str(execution.id))
                            should_pause = True
                            if session and session.debug_mode == "breakpoint":
                                should_pause = dag_node.id in session.breakpoints

                            if should_pause:
                                # 调试暂停点
                                ne = await NodeExecution.objects.aget(
                                    workflow_execution=execution, node_id=dag_node.id,
                                )
                                action, action_data = await self._debug_pause_after_node(execution, ne)

                                if action == "release":
                                    edited_output = action_data.get("edited_output")
                                    if edited_output is not None:
                                        # 用编辑后数据覆盖原始输出
                                        node_outputs[dag_node.id] = edited_output
                                        if hasattr(dag_node, 'node') and hasattr(dag_node.node, 'short_id') and dag_node.node.short_id:
                                            node_outputs[dag_node.node.short_id] = edited_output
                                        ne.output_data = edited_output
                                        await ne.asave(update_fields=["output_data"])
                                elif action == "mock":
                                    mock_data = action_data.get("mock_output", {})
                                    node_outputs[dag_node.id] = mock_data
                                    if hasattr(dag_node, 'node') and hasattr(dag_node.node, 'short_id') and dag_node.node.short_id:
                                        node_outputs[dag_node.node.short_id] = mock_data
                                    ne.output_data = mock_data
                                    await ne.asave(update_fields=["output_data"])
                                elif action == "skip":
                                    await ne.amark_skipped("用户调试跳过")
                                    completed_nodes.discard(dag_node.id)
                                    skipped_nodes.add(dag_node.id)
                                    node_outputs[dag_node.id] = {}
                                elif action in ("timeout", "cancel"):
                                    if action == "cancel":
                                        await execution.amark_cancelled()
                                    else:
                                        await execution.amark_failed("调试会话超时")
                                        hook_execution = await self._load_execution_for_hooks(execution)
                                        await self.hooks.trigger("execution_failed", execution=hook_execution)
                                    return
                        elif isinstance(result, dict) and result.get("status") == "failed":
                            if result.get("tolerated"):
                                # on_error=ignore: 容错处理
                                tolerated_failures.add(dag_node.id)
                                completed_nodes.add(dag_node.id)
                                fallback = dag_node.node.fallback_values or {"status": "skipped", "output": {}}
                                node_outputs[dag_node.id] = fallback
                            else:
                                failed_nodes.add(dag_node.id)
                        else:
                            failed_nodes.add(dag_node.id)
                    continue  # 回到 while 循环找下一批就绪节点

                # 并行执行就绪节点
                tasks = []
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
                    elif result.get("status") == "failed":
                        if result.get("tolerated"):
                            # on_error=ignore: 节点失败但不阻断工作流
                            tolerated_failures.add(dag_node.id)
                            completed_nodes.add(dag_node.id)  # 允许下游继续
                            fallback = dag_node.node.fallback_values or {"status": "skipped", "output": {}}
                            node_outputs[dag_node.id] = fallback
                            if hasattr(dag_node.node, "short_id") and dag_node.node.short_id:
                                node_outputs[dag_node.node.short_id] = fallback
                            logger.info(
                                "node_failure_tolerated",
                                node_id=dag_node.id,
                                error=result.get("error"),
                            )
                        else:
                            failed_nodes.add(dag_node.id)
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
                await execution.arefresh_from_db()
                if execution.timeout_at and timezone.now() > execution.timeout_at:
                    execution.status = ExecutionStatus.TIMEOUT
                    await execution.asave(update_fields=["status"])
                    await self.hooks.trigger("execution_timeout", execution=execution)
                    return

            # 执行完成
            if failed_nodes:
                await execution.amark_failed(f"失败节点: {len(failed_nodes)}")
                hook_execution = await self._load_execution_for_hooks(execution)
                await self.hooks.trigger("execution_failed", execution=hook_execution)
            else:
                # 收集最终输出（终端节点的输出）
                final_output = {}
                for node_id in completed_nodes:
                    dag_node = dag.nodes.get(node_id)
                    if dag_node and not dag_node.outgoing:
                        final_output.update(node_outputs.get(node_id, {}))
                await execution.amark_completed(final_output)
                hook_execution = await self._load_execution_for_hooks(execution)
                await self.hooks.trigger("execution_completed", execution=hook_execution)

        except Exception as e:
            logger.exception("workflow_execution_error", execution_id=str(execution.id))
            await execution.amark_failed(str(e))
            hook_execution = await self._load_execution_for_hooks(execution)
            await self.hooks.trigger("execution_failed", execution=hook_execution, error=e)
        finally:
            _debug_sessions.pop(str(execution.id), None)

    async def _execute_node(
        self,
        execution: WorkflowExecution,
        dag_node,
        input_data: dict,
        previous_outputs: dict,
    ) -> dict:
        """执行单个节点，支持重试、超时和 on_error 策略。

        on_error 策略：
        - abort（默认）：失败后立即中止，返回 failed
        - retry：按 retry_times 次数重试，指数退避间隔
        - ignore：失败后标记 tolerated，返回 failed + tolerated=True

        超时控制：
        - node_timeout_seconds 设置后，用 asyncio.wait_for 包装执行
        - 超时触发 on_timeout() 生命周期钩子，然后走 on_error 路径
        """
        node = dag_node.node
        on_error: str = getattr(node, "on_error", "abort") or "abort"
        retry_times: int = getattr(node, "retry_times", 0) or 0
        retry_delay: int = getattr(node, "retry_delay", 5) or 5
        node_timeout: int | None = getattr(node, "node_timeout_seconds", None)

        # 重试模式下最大尝试次数 = 1（初始）+ retry_times
        max_attempts = 1 + retry_times if on_error == "retry" else 1
        last_error: str | None = None

        for attempt in range(1, max_attempts + 1):
            node_execution = await NodeExecution.objects.aget(
                workflow_execution=execution,
                node=node,
            )

            # 重试时递增 attempt 字段
            if attempt > 1:
                node_execution.attempt = attempt
                await node_execution.asave(update_fields=["attempt"])

            # 确定性失败标志（IN-01）：模板解析失败是配置错误，重试结果必然
            # 相同，retry 策略下直接短路转最终失败，避免无意义退避延迟上报。
            # 注：except 块的 as 变量在块外不可用，故用标志位而非 isinstance(_exc)
            _deterministic_error = False

            try:
                await node_execution.amark_started(input_data)
                await node_execution.aappend_log(
                    level="INFO",
                    message=f"节点开始执行 (attempt {attempt}/{max_attempts})",
                    context={"node_type": node.node_type, "node_timeout": node_timeout},
                )
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
                exec_context = execution.context or {}
                node_snapshots: dict[str, dict] = (
                    exec_context.get("node_snapshots") or {}
                )
                context = ExecutionContext(
                    execution_id=str(execution.id),
                    node_id=str(node.id),
                    node_config=node.config,
                    input_data=input_data,
                    workflow_context=execution.context,
                    previous_outputs=previous_outputs,
                    workflow_execution=execution,
                    node_execution=node_execution,
                    node_snapshots=node_snapshots,
                )

                # 执行节点（带可选超时）
                node_instance = node_class()
                if node_timeout:
                    result: NodeResult = await asyncio.wait_for(
                        node_instance.execute(context),
                        timeout=node_timeout,
                    )
                else:
                    result = await node_instance.execute(context)

                # 处理结果
                if result.status == "completed":
                    output_with_handle = {**(result.output or {})}
                    if result.next_handle and result.next_handle != "default":
                        output_with_handle["_next_handle"] = result.next_handle
                    await node_execution.amark_completed(output_with_handle)
                    await node_execution.aappend_log(
                        level="INFO",
                        message="节点执行完成",
                        context={"duration_seconds": node_execution.duration},
                    )
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
                    await node_execution.aappend_log(
                        level="INFO",
                        message="节点进入等待审批状态",
                        context={"approval_data": result.output},
                    )
                    hook_execution = await self._load_execution_for_hooks(execution)
                    await self.hooks.trigger(
                        "node_waiting_approval",
                        execution=hook_execution,
                        node_execution=node_execution,
                    )
                    return {"status": "waiting_approval"}

                elif result.status == "waiting_event":
                    await node_execution.amark_waiting_event(result.output)
                    await node_execution.aappend_log(
                        level="INFO",
                        message="节点进入等待事件状态",
                        context={"subscription_data": result.output},
                    )
                    await self.hooks.trigger(
                        "node_waiting_event",
                        execution=execution,
                        node_execution=node_execution,
                    )
                    return {"status": "waiting_event"}

                else:
                    last_error = result.error or "未知错误"
                    raise RuntimeError(last_error)

            except asyncio.TimeoutError as _exc:
                # 超时：调用 on_timeout 生命周期钩子
                try:
                    await node_instance.on_timeout(context)
                except Exception:  # noqa: BLE001
                    pass  # on_timeout 清理失败不应掩盖超时错误
                last_error = f"节点执行超时 ({node_timeout}s)"
                _error_code = self._map_error_code(_exc)
                await node_execution.aappend_log(
                    level="ERROR",
                    message=last_error,
                    context={"node_timeout": node_timeout, "attempt": attempt},
                )

            except Exception as _exc:
                if isinstance(_exc, TemplateResolutionError):
                    # 模板解析失败（VAR-02）：中文一句话 + 结构化 JSON。
                    # 最后一行可被 JSON.parse（Phase 21 错误展示直接消费）
                    structured = json.dumps(
                        {
                            "reference": _exc.reference,
                            "reason": _exc.reason,
                            "available": _exc.available,
                            "template": _exc.template,
                        },
                        ensure_ascii=False,
                    )
                    last_error = f"{_exc}\n{structured}"
                    _deterministic_error = True
                elif isinstance(_exc, RuntimeError) and last_error:
                    pass  # 已设置 last_error
                else:
                    last_error = str(_exc)
                _error_code = self._map_error_code(_exc)
                logger.exception(
                    "node_execution_error",
                    node_id=str(node.id),
                    execution_id=str(execution.id),
                    attempt=attempt,
                )
                await node_execution.aappend_log(
                    level="ERROR",
                    message=f"节点执行失败: {last_error}",
                    context={"attempt": attempt, "exception_type": type(_exc).__name__},
                )

            # 到达此处表示执行失败
            if attempt < max_attempts and on_error == "retry" and not _deterministic_error:
                # 指数退避 + 随机 jitter
                delay = min(300, max(1, retry_delay * (2 ** (attempt - 1)) + random.randint(0, retry_delay)))
                await node_execution.amark_failed(last_error, error_code=_error_code)
                await node_execution.aappend_log(
                    level="WARN",
                    message=f"第 {attempt} 次尝试失败，将在 {delay}s 后重试",
                    context={"retry_attempt": attempt, "next_delay": delay, "error": last_error},
                )
                await self.hooks.trigger(
                    "node_failed",
                    execution=execution,
                    node_execution=node_execution,
                )
                logger.info(
                    "node_retry_scheduled",
                    node_id=str(node.id),
                    attempt=attempt,
                    max_attempts=max_attempts,
                    delay=delay,
                    error=last_error,
                )
                await asyncio.sleep(delay)
                continue

            # 最终失败 — 应用 on_error 策略
            await node_execution.amark_failed(last_error, error_code=_error_code)
            await self.hooks.trigger(
                "node_failed",
                execution=execution,
                node_execution=node_execution,
            )

            if on_error == "ignore":
                return {"status": "failed", "error": last_error, "tolerated": True}

            return {"status": "failed", "error": last_error}

        # 安全兜底（不应到达此处）
        return {"status": "failed", "error": last_error or "未知错误"}

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
        """恢复暂停的执行，从中断点继续调度。"""
        if execution.status != ExecutionStatus.PAUSED:
            raise ValueError("只能恢复已暂停的执行")

        # 1. 获取工作流和 DAG
        execution = await WorkflowExecution.objects.select_related("workflow").aget(
            pk=execution.pk
        )
        workflow = execution.workflow
        dag = await DAG.afrom_workflow(workflow)

        # 2. 收集已完成节点的输出作为 initial_outputs
        initial_outputs: dict[str, dict] = {}
        async for ne in NodeExecution.objects.filter(
            workflow_execution=execution,
            status=NodeExecutionStatus.COMPLETED,
        ):
            initial_outputs[str(ne.node_id)] = ne.output_data or {}

        # 3. 将已完成节点标记为 SKIPPED（让 _run_execution 的 initial_outputs 机制识别）
        completed_node_ids = list(initial_outputs.keys())
        await NodeExecution.objects.filter(
            workflow_execution=execution,
            status=NodeExecutionStatus.COMPLETED,
        ).aupdate(status=NodeExecutionStatus.SKIPPED)

        # 4. 将 QUEUED 节点重置为 PENDING
        await NodeExecution.objects.filter(
            workflow_execution=execution,
            status=NodeExecutionStatus.QUEUED,
        ).aupdate(status=NodeExecutionStatus.PENDING)

        # 5. 更新执行状态并恢复
        execution.status = ExecutionStatus.RUNNING
        await execution.asave(update_fields=["status"])
        await self.hooks.trigger("execution_resumed", execution=execution)

        logger.info(
            "execution_resumed",
            execution_id=str(execution.id),
            skipped_nodes=len(completed_node_ids),
        )

        # 6. 重入主循环（is_resume=True 避免覆盖 started_at）
        _run_in_thread(
            self._run_execution(
                execution, dag, execution.input_data or {}, initial_outputs,
                is_resume=True,
            )
        )

    async def cancel_execution(self, execution: WorkflowExecution) -> None:
        """取消执行"""
        if execution.status in (ExecutionStatus.COMPLETED, ExecutionStatus.CANCELLED):
            raise ValueError("执行已完成或已取消")

        execution.status = ExecutionStatus.CANCELLED
        execution.completed_at = timezone.now()
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

        # INGEST-01（14-04）：ai_plan_approval 审批通过 → 投递统一摄取。
        # source_id 恒为同 execution 中生成节点（ai_plan_generation）的 key（OQ-2 定案）；
        # node FK 未必预加载，经 sync_to_async 安全取 node_type。
        node_type = await sync_to_async(lambda: node_execution.node.node_type)()
        if node_type == "ai_plan_approval":
            generation_node_id = await (
                NodeExecution.objects.filter(
                    workflow_execution_id=node_execution.workflow_execution_id,
                    node__node_type="ai_plan_generation",
                    status=NodeExecutionStatus.COMPLETED,
                )
                .exclude(output_data={})
                .order_by("-completed_at")
                .values_list("node_id", flat=True)
                .afirst()
            )
            if generation_node_id is None:
                # 审批先于生成属病理态：warning 不投递
                logger.warning(
                    "knowledge_workflow_plan_source_missing",
                    execution_id=str(node_execution.workflow_execution_id),
                    node_execution_id=str(node_execution.id),
                )
            else:
                from knowledge import ingestion  # lazy import 防循环

                await ingestion.aschedule_ingestion(
                    ingestion.IngestionRequest(
                        "workflow_plan",
                        f"{node_execution.workflow_execution_id}:{generation_node_id}",
                        "workflow_plan_approved",
                    )
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
        await node_execution.arefresh_from_db()
        node_execution.approval_data.update(
            {
                "approved": False,
                "approver_id": approver.id if approver else None,
                "approver_name": approver.username if approver else "",
                "comment": comment,
                "rejected_at": timezone.now().isoformat(),
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
        await node_execution.amark_started()

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

        # Use dag.get_successors() to route by handle
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
                ).afirst()

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
                        ).afirst()
                        if successor_ne:
                            await self._continue_after_node(execution, successor_ne)

    async def _handle_node_failure(
        self,
        execution: WorkflowExecution,
        node_execution: NodeExecution,
    ) -> None:
        """Handle node failure from callback.

        Updates workflow status and triggers failure hooks.

        TODO: This method is used in the callback path (Docker/container nodes).
        It currently always fails the workflow. Future work should apply on_error
        strategy here too (retry, ignore) for callback-based nodes.
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

        hook_execution = await self._load_execution_for_hooks(execution)
        await self.hooks.trigger("execution_failed", execution=hook_execution)

    async def _check_execution_complete(self, execution: WorkflowExecution) -> None:
        """Check if workflow execution is complete and update status."""
        # Count node statuses
        base_qs = NodeExecution.objects.filter(workflow_execution=execution)
        stats = {
            "pending": await base_qs.filter(status=NodeExecutionStatus.PENDING).acount(),
            "running": await base_qs.filter(status=NodeExecutionStatus.RUNNING).acount(),
            "waiting": await base_qs.filter(
                status__in=[
                    NodeExecutionStatus.WAITING_APPROVAL,
                    NodeExecutionStatus.WAITING_EVENT,
                ],
            ).acount(),
            "failed": await base_qs.filter(status=NodeExecutionStatus.FAILED).acount(),
        }

        if stats["pending"] == 0 and stats["running"] == 0 and stats["waiting"] == 0:
            # All nodes are done
            if stats["failed"] > 0:
                await execution.amark_failed(f"失败节点: {stats['failed']}")
                hook_execution = await self._load_execution_for_hooks(execution)
                await self.hooks.trigger("execution_failed", execution=hook_execution)
            else:
                # Collect final outputs
                final_output = await self._collect_final_outputs(execution)
                await execution.amark_completed(final_output)
                hook_execution = await self._load_execution_for_hooks(execution)
                await self.hooks.trigger("execution_completed", execution=hook_execution)

    async def _check_dependencies_ready(
        self,
        execution: WorkflowExecution,
        dag_node,
    ) -> bool:
        """Check if all forward dependencies of a node are completed."""
        for dep_id in dag_node.forward_incoming:
            dep_exec = await NodeExecution.objects.filter(
                workflow_execution=execution,
                node_id=dep_id,
            ).afirst()

            if not dep_exec or dep_exec.status != NodeExecutionStatus.COMPLETED:
                return False

        return True

    async def _collect_all_outputs(self, execution: WorkflowExecution) -> dict:
        """Collect outputs from all completed nodes.

        同时按 UUID 和 short_id 存储，确保模板变量
        {{nodes.<short_id>.field}} 能正确解析。
        """
        completed_nodes = [
            ne async for ne in NodeExecution.objects.filter(
                workflow_execution=execution,
                status=NodeExecutionStatus.COMPLETED,
            ).select_related("node")
        ]

        outputs = {}
        for node_exec in completed_nodes:
            output_data = node_exec.output_data or {}
            outputs[str(node_exec.node_id)] = output_data
            if node_exec.node.short_id:
                outputs[node_exec.node.short_id] = output_data

        return outputs

    async def _collect_final_outputs(self, execution: WorkflowExecution) -> dict:
        """Collect outputs from terminal nodes."""
        # Get workflow and DAG
        execution = await WorkflowExecution.objects.select_related("workflow").aget(id=execution.id)
        workflow = execution.workflow
        dag = await DAG.afrom_workflow(workflow)

        # Find terminal nodes (no outgoing edges)
        terminal_node_ids = [
            node_id for node_id, dag_node in dag.nodes.items() if not dag_node.outgoing
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

    # ===== 从失败节点继续执行 =====

    def _get_downstream_nodes(self, dag: DAG, start_node_id: str) -> set[str]:
        """BFS 收集失败节点的所有下游节点 ID（不包含起始节点本身）。"""
        visited: set[str] = set()
        queue: deque[str] = deque()
        # 从起始节点的所有直接后继开始
        for successor in dag.get_all_successors(start_node_id):
            if successor.id not in visited:
                visited.add(successor.id)
                queue.append(successor.id)
        # BFS 遍历所有下游
        while queue:
            current_id = queue.popleft()
            for successor in dag.get_all_successors(current_id):
                if successor.id not in visited:
                    visited.add(successor.id)
                    queue.append(successor.id)
        return visited

    async def _compare_workflow_definitions(
        self,
        snapshot: dict[str, Any],
        workflow: "Workflow",
    ) -> bool:
        """对比执行快照与当前工作流定义的结构差异。

        Returns:
            True 表示定义已变更（结构或配置差异），False 表示未变。
            只比较结构（节点 ID、类型、连线）和配置，忽略视觉属性（位置、颜色等）。
        """
        # 提取快照中的节点信息（忽略 position、name 等视觉属性）
        snap_nodes: dict[str, tuple[str, dict]] = {}
        for n in snapshot.get("nodes", []):
            snap_nodes[n["id"]] = (n.get("node_type", ""), n.get("config", {}))

        # 提取当前工作流的节点信息
        curr_nodes: dict[str, tuple[str, dict]] = {}
        async for node in workflow.nodes.all():
            curr_nodes[str(node.id)] = (node.node_type, node.config or {})

        if snap_nodes != curr_nodes:
            return True

        # 提取快照中的边信息
        snap_edges: set[tuple[str, str, str]] = set()
        for e in snapshot.get("edges", []):
            snap_edges.add((e["source"], e["target"], e.get("sourcePort", "default")))

        # 提取当前工作流的边信息
        curr_edges: set[tuple[str, str, str]] = set()
        async for edge in workflow.edges.all():
            curr_edges.add((
                str(edge.source_node_id),
                str(edge.target_node_id),
                edge.source_handle or "default",
            ))

        return snap_edges != curr_edges

    async def resume_from_node(
        self,
        original_execution: WorkflowExecution,
        failed_node_id: str,
        triggered_by: Any = None,
        run_sync: bool = False,
    ) -> WorkflowExecution:
        """从失败节点创建新执行实例并开始执行。

        创建一个新的 WorkflowExecution，跳过已成功的节点，从失败节点开始重新执行。
        已成功节点被标记为 skipped，其 output_data 被复制到新执行作为上下文。

        Args:
            original_execution: 原始失败的执行实例
            failed_node_id: 要从其继续的失败节点 ID
            triggered_by: 触发者
            run_sync: 是否同步执行（用于测试）

        Returns:
            新创建的 WorkflowExecution 实例

        Raises:
            ValueError: 执行状态不符合要求、节点未失败、工作流定义已变更等
        """
        # 1. 验证原执行状态
        if original_execution.status not in (
            ExecutionStatus.FAILED,
            ExecutionStatus.CANCELLED,
            ExecutionStatus.TIMEOUT,
        ):
            raise ValueError("只能从失败、已取消或超时的执行继续")

        # 1.5 互斥锁定：检查是否已有活跃的恢复执行
        active_resume = await WorkflowExecution.objects.filter(
            resumed_from=original_execution,
            status__in=[ExecutionStatus.PENDING, ExecutionStatus.RUNNING],
        ).aexists()
        if active_resume:
            raise ValueError("已有恢复执行正在运行，请等待完成后再试")

        # 2. 验证失败节点存在且确实失败
        failed_ne = await NodeExecution.objects.filter(
            workflow_execution=original_execution,
            node_id=failed_node_id,
            status=NodeExecutionStatus.FAILED,
        ).afirst()
        if not failed_ne:
            raise ValueError("指定节点不存在或不是失败状态")

        # 3. 获取工作流并构建 DAG
        original_execution = await WorkflowExecution.objects.select_related(
            "workflow"
        ).aget(pk=original_execution.pk)
        workflow = original_execution.workflow
        dag = await DAG.afrom_workflow(workflow)

        # 4. 变更检测
        if original_execution.workflow_definition:
            changed = await self._compare_workflow_definitions(
                original_execution.workflow_definition,
                workflow,
            )
            if changed:
                raise ValueError("工作流定义已修改，无法从此继续")

        # 5. 计算需要执行的节点范围（失败节点 + 所有下游）
        downstream_ids = self._get_downstream_nodes(dag, failed_node_id)
        nodes_to_execute = {failed_node_id} | downstream_ids

        # 6. 创建新执行实例
        new_execution = await WorkflowExecution.objects.acreate(
            workflow=workflow,
            project_id=workflow.project_id,
            status=ExecutionStatus.PENDING,
            trigger_type="resume",
            triggered_by=triggered_by,
            trigger_data={
                "metadata": {
                    "resumed_from": str(original_execution.id),
                    "failed_node_id": failed_node_id,
                }
            },
            input_data=original_execution.input_data,
            resumed_from=original_execution,
            workflow_definition=original_execution.workflow_definition,
            total_nodes=len(dag.nodes),
            context={
                "workflow_id": str(workflow.id),
                "workflow_name": workflow.name,
                "started_at": timezone.now().isoformat(),
                "resumed_from": str(original_execution.id),
            },
        )

        # 7. 为所有节点创建 NodeExecution，并收集 skipped 节点输出
        initial_outputs: dict[str, dict] = {}
        original_node_execs = {
            str(ne.node_id): ne
            async for ne in NodeExecution.objects.filter(
                workflow_execution=original_execution,
            )
        }

        for dag_node in dag.nodes.values():
            node_id = dag_node.id
            if node_id in nodes_to_execute:
                # 需要执行的节点 → PENDING
                await NodeExecution.objects.acreate(
                    workflow_execution=new_execution,
                    node=dag_node.node,
                    status=NodeExecutionStatus.PENDING,
                )
            else:
                # 跳过的节点 → SKIPPED + 复制原执行的 output_data
                orig_ne = original_node_execs.get(node_id)
                output_data = orig_ne.output_data if orig_ne else {}

                ne = await NodeExecution.objects.acreate(
                    workflow_execution=new_execution,
                    node=dag_node.node,
                    status=NodeExecutionStatus.PENDING,  # 先创建为 pending
                )
                await ne.amark_skipped("从失败节点继续：复用原执行结果")
                # 复制原执行的 output_data 到新的 skipped 节点
                if output_data:
                    ne.output_data = output_data
                    await ne.asave(update_fields=["output_data"])
                    initial_outputs[node_id] = output_data

        # 8. 触发开始钩子
        await self.hooks.trigger("execution_started", execution=new_execution)

        # 9. 启动执行（传入预填充的 node_outputs）
        if run_sync:
            await self._run_execution(
                new_execution, dag, original_execution.input_data, initial_outputs
            )
        else:
            _run_in_thread(
                self._run_execution(
                    new_execution, dag, original_execution.input_data, initial_outputs
                )
            )

        return new_execution
