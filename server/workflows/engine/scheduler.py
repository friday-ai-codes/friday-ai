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
from workflows.engine.routing import (
    STATUS_COMPLETED,
    STATUS_FAILED,
    STATUS_SKIPPED,
    STATUS_TOLERATED,
    STATUS_WAITING,
    RoutingState,
    collect_inputs,
    compute_skippable,
    diagnose_deadlock,
    evaluate_node_readiness,
)
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


def _run_in_thread(coro, *, triggered_by_id=None, trace_id=None):
    """Run a coroutine in a new thread with its own event loop.

    CTX-02：后台工作流线程是干净的新 event loop / 新线程，contextvars 不自动传播，
    必须在入口显式 ``bind_task_context`` 重新绑定发起用户（手动触发有 triggered_by；
    飞书/webhook 当前无 → ``system``），run 结束 clear。观测代码 best-effort，
    绑定失败绝不影响工作流主流程。
    """

    def target():
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            from common.log_context import bind_task_context

            with bind_task_context(
                user_id=triggered_by_id,
                source="workflow",
                trace_id=trace_id,
                component="workflow",
            ):
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

        # ReactionDispatchHook: 信号 → 幂等横切反应（Chassis v2 · P0）
        # 投影 lifecycle 事件为 Signal 并后台分发 WorkflowReaction，绝不阻塞主链路。
        from workflows.reactions.hook import ReactionDispatchHook

        reaction_hook = ReactionDispatchHook()
        for event in (
            "node_started",
            "node_completed",
            "node_failed",
            "node_waiting_approval",
            "node_waiting_event",
            "node_approved",
            "node_rejected",
        ):
            self.hooks.register_hook(event, reaction_hook)

        # FeishuSyncHook: 飞书卡片状态同步
        # execute() 内部有 event_map 路由，对未处理事件是 no-op，注册所有事件安全
        from workflows.hooks.feishu_sync import FeishuSyncHook

        feishu_hook = FeishuSyncHook()
        for event in HookManager.EVENTS:
            self.hooks.register_hook(event, feishu_hook)

    async def _load_execution_for_hooks(self, execution: WorkflowExecution) -> WorkflowExecution:
        """Load execution with related objects to keep hook handlers async-safe."""
        return await WorkflowExecution.objects.select_related(
            "workflow__space",
            "space",
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
        if isinstance(
            exception,
            (httpx.TimeoutException, httpx.ConnectError, httpx.HTTPError, httpx.HTTPStatusError),
        ):
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
                active_count = (
                    WorkflowExecution.objects.select_for_update()
                    .filter(
                        workflow_id=workflow_id,
                        status__in=[ExecutionStatus.PENDING, ExecutionStatus.RUNNING],
                        is_debug=False,  # 调试执行不计入并发限制
                    )
                    .count()
                )
                if active_count >= max_concurrent_executions:
                    raise ValueError(f"工作流已达到最大并发数 ({max_concurrent_executions})")

            return WorkflowExecution.objects.create(
                workflow_id=workflow_id,
                space_id=workflow.space_id,
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

            workflow = await WorkflowModel.objects.select_related("space").aget(pk=workflow.pk)

        # 构建 workflow_definition 快照（DAG 结构 + 节点位置，用于前端可视化）
        nodes_snapshot: list[dict] = []
        async for node in workflow.nodes.all():
            nodes_snapshot.append(
                {
                    "id": str(node.id),
                    "name": node.name,
                    "node_type": node.node_type,
                    "position": {"x": node.position_x, "y": node.position_y},
                    "config": node.config or {},
                }
            )
        edges_snapshot: list[dict] = []
        async for edge in workflow.edges.all():
            edges_snapshot.append(
                {
                    "id": str(edge.id),
                    "source": str(edge.source_node_id),
                    "target": str(edge.target_node_id),
                    "sourcePort": edge.source_handle or "default",
                    "targetPort": edge.target_handle or "default",
                }
            )

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
                active_count = (
                    await WorkflowExecution.objects.filter(
                        workflow=workflow,
                        status__in=[ExecutionStatus.PENDING, ExecutionStatus.RUNNING],
                    )
                    .exclude(pk=execution.pk)
                    .acount()
                )
                if active_count >= workflow.max_concurrent_executions:
                    raise ValueError(
                        f"工作流已达到最大并发数 ({workflow.max_concurrent_executions})"
                    )
            # 确保执行状态正确
            execution.status = ExecutionStatus.PENDING
            await execution.asave(update_fields=["status"])

        # Cache related objects on execution to avoid sync FK lazy-load in async hooks.
        execution.workflow = workflow
        execution.space_id = workflow.space_id
        if "project" in workflow._state.fields_cache:
            execution.space = workflow.space

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
            await self._run_execution(
                execution, dag, input_data, stop_before_node_id=stop_before_node_id
            )
        else:
            # 异步执行（在独立线程中运行，避免事件循环退出问题）
            _run_in_thread(
                self._run_execution(
                    execution, dag, input_data, stop_before_node_id=stop_before_node_id
                ),
                triggered_by_id=execution.triggered_by_id,
            )

        return execution

    # implementation contract contract：AI 节点白名单（Execution 启动时遍历 DAG 统一快照）
    _AI_NODE_TYPES: set[str] = {
        "ai_prompt",
        "ai_variable_extractor",
        "ai_plan_generation",
        "ai_coding",
        "ai_coding_dispatcher",
    }

    @staticmethod
    async def _aget_execution_space(workflow_execution: WorkflowExecution):
        """安全取 Execution 关联的 Space —— 已缓存直接用，否则异步查。

        直接 `workflow_execution.space` 在未预取时会触发同步 ORM 查询，async 上下文下
        抛 SynchronousOnlyOperation。
        """
        cached = workflow_execution._state.fields_cache.get("space")
        if cached is not None:
            return cached
        space_id = getattr(workflow_execution, "space_id", None)
        if not space_id:
            return None
        from projects.models import Space

        return await Space.objects.filter(id=space_id).afirst()

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

        # 取 project：不能直接 getattr(workflow_execution, "space")。那是惰性 FK 访问，
        # 未预取时在 async 上下文会抛 SynchronousOnlyOperation，整个快照被 except 吞掉
        # → node_snapshots 为空 → Replay 不再稳定（后续改 default_provider_credential_id
        # 会影响历史 Execution），而现场只留一条 sampling 级 error 日志。
        # 优先读已缓存的关联对象，未缓存时走异步查询。
        project = await self._aget_execution_space(workflow_execution)

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
                provider_type_str = str(result.provider_type).replace("ProviderType.", "")
                # enum 的 str()/.value 可能返回 "ProviderType.ANTHROPIC" 或 "anthropic"；
                # 统一读 .value 保持 JSON 友好字符串
                if hasattr(result.provider_type, "value"):
                    provider_type_str = result.provider_type.value

                # model 优先读 node_config.model；fallback 到 resolved.extra["model"]
                snap_model = node_config.get("model") or (result.extra or {}).get("model") or ""
                snap_credential_id = str(result.credential_id) if result.credential_id else None
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
        await self.hooks.trigger(
            "node_debug_paused", execution=execution, node_execution=node_execution
        )

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
        *,
        rebuilt_state: dict | None = None,
    ) -> None:
        """执行工作流主循环（首跑与回调续跑/恢复重入字面同源，ENG-01/02）。

        Args:
            execution: 执行实例
            dag: DAG 实例
            input_data: 输入数据
            initial_outputs: 预填充的节点输出（从失败节点继续时，包含 skipped 节点的输出）
            is_resume: 是否从暂停/挂起恢复（跳过 amark_started 避免覆盖 started_at）
            stop_before_node_id: 单节点测试：执行到该节点前停止
            rebuilt_state: 重入续跑时从 DB 重建的真实状态集合（_rebuild_state_from_db
                产出）；非 None 时覆盖首跑的空集初始化与 initial_outputs 预填充，使
                回调续跑/恢复与首跑共用同一 while 调度循环与 _finalize_run_state 收口。
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

            # routing 纯函数的状态映射（主循环就绪/级联/后继判定的唯一语义源）。
            # node_statuses: node_id -> STATUS_* 字面值（终态/等待时写入）。
            # node_handles: node_id -> next_handle（仅非 default 时写入，缺省=default，
            # 封堵 RESEARCH Pitfall 2 双来源不对称——热路径只用内存 result["handle"]）。
            node_statuses: dict[str, str] = {}
            node_handles: dict[str, str] = {}

            # 等待外部事件/审批而挂起的节点集合（ENG-01）。waiting_event 与
            # waiting_approval 统一进此集合且都不加回 pending——审批/事件推进完全
            # 依赖 approve_node / 事件回调闭环，消灭旧 waiting_approval 加回 pending
            # 的热循环（§1.4）。收口判定 waiting 非空即挂起。
            waiting_nodes_mem: set[str] = set()

            # 待处理节点
            pending_nodes = set(dag.nodes.keys())

            # 重入续跑（回调续跑 / paused-resume，18-04）：用从 DB 重建的真实 NE 状态
            # 集合覆盖首跑空集——路由/级联/完成/死锁判定与主循环字面同源，消除两套
            # 路由实现漂移。pending = DAG 中无终态/等待记录的节点（_rebuild_state_from_db）。
            if rebuilt_state is not None:
                node_outputs = rebuilt_state["node_outputs"]
                completed_nodes = rebuilt_state["completed_nodes"]
                failed_nodes = rebuilt_state["failed_nodes"]
                skipped_nodes = rebuilt_state["skipped_nodes"]
                tolerated_failures = rebuilt_state["tolerated_failures"]
                node_statuses = rebuilt_state["node_statuses"]
                node_handles = rebuilt_state["node_handles"]
                waiting_nodes_mem = rebuilt_state["waiting_nodes_mem"]
                pending_nodes = rebuilt_state["pending_nodes"]
            # 预填充 skipped 节点的输出（从失败节点继续场景）
            elif initial_outputs:
                node_outputs.update(initial_outputs)
                # 从数据库查询 skipped 节点，将其加入 completed/skipped 集合
                skipped_ne_list = [
                    ne
                    async for ne in NodeExecution.objects.filter(
                        workflow_execution=execution,
                        status=NodeExecutionStatus.SKIPPED,
                    )
                ]
                for ne in skipped_ne_list:
                    node_id = str(ne.node_id)
                    skipped_nodes.add(node_id)
                    completed_nodes.add(node_id)
                    # 续跑/恢复场景：这些节点实际已产出输出（DB 为复用 initial_outputs
                    # 机制临时标记 SKIPPED）。对 routing 而言视为 COMPLETED（已解析且选中），
                    # 保留旧主循环"completed/skipped 上游即放行下游"语义，避免被新的
                    # skip_unselected 级联误伤；并从 output_data 还原 next_handle 保证路由。
                    node_statuses[node_id] = STATUS_COMPLETED
                    restored_handle = (ne.output_data or {}).get("_next_handle")
                    if restored_handle and restored_handle != "default":
                        node_handles[node_id] = restored_handle
                    pending_nodes.discard(node_id)

            # 入口节点的输入数据
            entry_inputs = {dag_node.id: input_data for dag_node in dag.get_entry_nodes()}

            while pending_nodes:
                # 路由状态快照——主循环就绪/级联判定的唯一语义源（routing 纯函数，
                # 与回调续跑共用，消除"两套路由实现漂移"根因）。statuses 即 node_statuses
                # 本体，下面写入 skip 后 routing_state 即时可见（同一 dict 引用）。
                routing_state = RoutingState(statuses=node_statuses, handles=node_handles)

                # 1) fixpoint 级联标记未选中/前置失败的可 skip 节点（含级联下游）
                skippable = compute_skippable(dag, routing_state, pending_nodes)
                for skip_id, skip_verdict in skippable.items():
                    skip_dag_node = dag.nodes[skip_id]
                    skip_reason = "前置节点失败" if skip_verdict == "skip_failed" else "分支未选中"
                    await self._skip_node(execution, skip_dag_node, skip_reason)
                    skipped_nodes.add(skip_id)
                    node_statuses[skip_id] = STATUS_SKIPPED
                    pending_nodes.discard(skip_id)

                # 2) 边感知就绪判定：仅 "ready" 进入本轮执行批；"blocked" 留 pending
                ready_nodes = []
                for node_id in pending_nodes:
                    if evaluate_node_readiness(dag, node_id, routing_state) == "ready":
                        ready_nodes.append(dag.nodes[node_id])

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
                                await self._skip_node(
                                    execution, ds_dag_node, "单节点测试：上游已停止"
                                )
                                skipped_nodes.add(ds_id)
                                node_statuses[ds_id] = STATUS_SKIPPED
                        logger.info(
                            "execution_stop_before_node",
                            execution_id=str(execution.id),
                            stop_before_node_id=stop_before_node_id,
                            downstream_removed=len(downstream),
                        )
                        # 如果移除后没有可执行节点，走统一收口（Pitfall 5：stop_before
                        # 出口同样需查 waiting——waiting 非空仍判 suspended，绝不误判完成）
                        if not ready_nodes and not pending_nodes:
                            await self._finalize_run_state(
                                execution,
                                dag,
                                pending=pending_nodes,
                                waiting=waiting_nodes_mem,
                                failed=failed_nodes,
                                completed=completed_nodes,
                                node_statuses=node_statuses,
                                node_handles=node_handles,
                                node_outputs=node_outputs,
                            )
                            return

                if not ready_nodes:
                    # 无就绪节点：统一收口（删除旧 5s 轮询 + all_blocked 检查 + 单键刷新
                    # 缺陷）。挂起优先于死锁——waiting 非空即挂起返回（webhook/事件回调
                    # 经 _continue_after_node 续跑）；waiting 空且 pending 非空 → 死锁
                    # 转 FAILED；都空 → 完成。挂起后线程立即退出，根除"永久 running
                    # 僵尸线程"（T-18-04）。waiting 与纯死锁混合时先挂起，恢复续跑后
                    # 残留纯死锁在 18-04 重入路径暴露。
                    await self._finalize_run_state(
                        execution,
                        dag,
                        pending=pending_nodes,
                        waiting=waiting_nodes_mem,
                        failed=failed_nodes,
                        completed=completed_nodes,
                        node_statuses=node_statuses,
                        node_handles=node_handles,
                        node_outputs=node_outputs,
                    )
                    return

                # 调试模式：串行执行，每次逐节点暂停
                if execution.is_debug:
                    for dag_node in ready_nodes:
                        if dag_node.id in entry_inputs:
                            node_input = entry_inputs[dag_node.id]
                        else:
                            node_input = self._collect_inputs(dag_node, dag, node_outputs)
                        result = await self._execute_node(
                            execution, dag_node, node_input, node_outputs
                        )
                        pending_nodes.discard(dag_node.id)

                        if isinstance(result, Exception):
                            failed_nodes.add(dag_node.id)
                            node_statuses[dag_node.id] = STATUS_FAILED
                        elif result.get("status") == "completed":
                            completed_nodes.add(dag_node.id)
                            node_statuses[dag_node.id] = STATUS_COMPLETED
                            handle = result.get("handle")
                            if handle and handle != "default":
                                node_handles[dag_node.id] = handle
                            output = result.get("output", {})
                            node_outputs[dag_node.id] = output
                            if (
                                hasattr(dag_node, "node")
                                and hasattr(dag_node.node, "short_id")
                                and dag_node.node.short_id
                            ):
                                node_outputs[dag_node.node.short_id] = output

                            # 断点模式条件暂停：仅断点节点暂停，非断点节点自动放行
                            session = _debug_sessions.get(str(execution.id))
                            should_pause = True
                            if session and session.debug_mode == "breakpoint":
                                should_pause = dag_node.id in session.breakpoints

                            if should_pause:
                                # 调试暂停点
                                ne = await NodeExecution.objects.aget(
                                    workflow_execution=execution,
                                    node_id=dag_node.id,
                                )
                                action, action_data = await self._debug_pause_after_node(
                                    execution, ne
                                )

                                if action == "release":
                                    edited_output = action_data.get("edited_output")
                                    if edited_output is not None:
                                        # 用编辑后数据覆盖原始输出
                                        node_outputs[dag_node.id] = edited_output
                                        if (
                                            hasattr(dag_node, "node")
                                            and hasattr(dag_node.node, "short_id")
                                            and dag_node.node.short_id
                                        ):
                                            node_outputs[dag_node.node.short_id] = edited_output
                                        ne.output_data = edited_output
                                        await ne.asave(update_fields=["output_data"])
                                elif action == "mock":
                                    mock_data = action_data.get("mock_output", {})
                                    node_outputs[dag_node.id] = mock_data
                                    if (
                                        hasattr(dag_node, "node")
                                        and hasattr(dag_node.node, "short_id")
                                        and dag_node.node.short_id
                                    ):
                                        node_outputs[dag_node.node.short_id] = mock_data
                                    ne.output_data = mock_data
                                    await ne.asave(update_fields=["output_data"])
                                elif action == "skip":
                                    await ne.amark_skipped("用户调试跳过")
                                    completed_nodes.discard(dag_node.id)
                                    skipped_nodes.add(dag_node.id)
                                    node_statuses[dag_node.id] = STATUS_SKIPPED
                                    node_outputs[dag_node.id] = {}
                                elif action in ("timeout", "cancel"):
                                    if action == "cancel":
                                        await execution.amark_cancelled()
                                    else:
                                        await execution.amark_failed("调试会话超时")
                                        hook_execution = await self._load_execution_for_hooks(
                                            execution
                                        )
                                        await self.hooks.trigger(
                                            "execution_failed", execution=hook_execution
                                        )
                                    return
                        elif isinstance(result, dict) and result.get("status") == "failed":
                            if result.get("tolerated"):
                                # on_error=ignore: 容错处理
                                tolerated_failures.add(dag_node.id)
                                completed_nodes.add(dag_node.id)
                                node_statuses[dag_node.id] = STATUS_TOLERATED
                                fallback = dag_node.node.fallback_values or {
                                    "status": "skipped",
                                    "output": {},
                                }
                                node_outputs[dag_node.id] = fallback
                            else:
                                failed_nodes.add(dag_node.id)
                                node_statuses[dag_node.id] = STATUS_FAILED
                        elif isinstance(result, dict) and result.get("status") in (
                            "waiting_approval",
                            "waiting_event",
                        ):
                            # 调试串行路径同步收口语义：进 waiting 集合、不加回 pending
                            waiting_nodes_mem.add(dag_node.id)
                            node_statuses[dag_node.id] = STATUS_WAITING
                        else:
                            failed_nodes.add(dag_node.id)
                            node_statuses[dag_node.id] = STATUS_FAILED
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
                        node_statuses[dag_node.id] = STATUS_FAILED
                    elif result.get("status") == "completed":
                        completed_nodes.add(dag_node.id)
                        node_statuses[dag_node.id] = STATUS_COMPLETED
                        # next_handle 写入 routing 状态（仅非 default；缺省=default）
                        handle = result.get("handle")
                        if handle and handle != "default":
                            node_handles[dag_node.id] = handle
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
                            # tolerated=已解析且按 default 选中（routing 语义）
                            node_statuses[dag_node.id] = STATUS_TOLERATED
                            fallback = dag_node.node.fallback_values or {
                                "status": "skipped",
                                "output": {},
                            }
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
                            node_statuses[dag_node.id] = STATUS_FAILED
                    elif result.get("status") == "waiting_approval":
                        # 等待审批 → 挂起。统一进 waiting 集合且**不加回 pending**
                        # （消灭 §1.4 热循环——审批推进完全依赖 approve_node 回调闭环）。
                        waiting_nodes_mem.add(dag_node.id)
                        node_statuses[dag_node.id] = STATUS_WAITING
                    elif result.get("status") == "waiting_event":
                        # 等待外部事件 → 挂起。进 waiting 集合、不加回 pending，
                        # 收口判定 waiting 非空即 amark_suspended。
                        waiting_nodes_mem.add(dag_node.id)
                        node_statuses[dag_node.id] = STATUS_WAITING
                    else:
                        failed_nodes.add(dag_node.id)
                        node_statuses[dag_node.id] = STATUS_FAILED

                # 检查超时
                await execution.arefresh_from_db()
                if execution.timeout_at and timezone.now() > execution.timeout_at:
                    execution.status = ExecutionStatus.TIMEOUT
                    await execution.asave(update_fields=["status"])
                    await self.hooks.trigger("execution_timeout", execution=execution)
                    return

            # 主循环正常退出（pending 耗尽）：统一收口。waiting 非空（末端等待节点
            # 是最后一个 pending）时判 SUSPENDED 而非 COMPLETED——修复 §1 末端
            # waiting_event 被误判完成的根因（Test 1）。
            await self._finalize_run_state(
                execution,
                dag,
                pending=pending_nodes,
                waiting=waiting_nodes_mem,
                failed=failed_nodes,
                completed=completed_nodes,
                node_statuses=node_statuses,
                node_handles=node_handles,
                node_outputs=node_outputs,
            )

        except Exception as e:
            logger.exception("workflow_execution_error", execution_id=str(execution.id))
            await execution.amark_failed(str(e))
            hook_execution = await self._load_execution_for_hooks(execution)
            await self.hooks.trigger("execution_failed", execution=hook_execution, error=e)
        finally:
            _debug_sessions.pop(str(execution.id), None)

    async def _finalize_run_state(
        self,
        execution: WorkflowExecution,
        dag: DAG,
        *,
        pending: set[str],
        waiting: set[str],
        failed: set[str],
        completed: set[str],
        node_statuses: dict[str, str],
        node_handles: dict[str, str],
        node_outputs: dict[str, dict],
    ) -> None:
        """完成 / 挂起 / 死锁三类终局判定的单一收口（主循环两个出口共用，ENG-01/04）。

        判定优先级（顺序敏感，禁调换）：
        a. ``waiting`` 非空 → ``amark_suspended`` + ``execution_suspended`` hook（等待
           即挂起，CONTEXT 锁定语义；webhook/事件回调经 _continue_after_node 续跑）；
        b. ``waiting`` 空且 ``pending`` 非空 → 经 ``routing.diagnose_deadlock`` 转 FAILED，
           error_message = 中文一句话 + ``\\n`` + ``json.dumps(diag, ensure_ascii=False)``
           （Phase 17 结构化约定，末行可独立 json.loads；诊断只含拓扑元数据，
           绝不含节点输出值——V5 信息泄露防线）；
        c. ``failed`` 非空 → 现状失败收口（文案保留）；
        d. 否则 → 收集终端节点（无 outgoing）输出 + ``amark_completed`` + 完成 hook。

        18-04 重入续跑路径复用本方法做恢复后的终局判定。
        """
        # a. 挂起优先：任一节点等待外部事件/审批即挂起
        if waiting:
            logger.info(
                "workflow_suspended",
                execution_id=str(execution.id),
                waiting_nodes=len(waiting),
            )
            await execution.amark_suspended()
            hook_execution = await self._load_execution_for_hooks(execution)
            await self.hooks.trigger("execution_suspended", execution=hook_execution)
            return

        # b. 死锁：waiting 空但仍有 pending 无法调度 → 结构化诊断 + FAILED
        if pending:
            logger.error(
                "workflow_deadlock",
                execution_id=str(execution.id),
                pending_nodes=list(pending),
            )
            routing_state = RoutingState(statuses=node_statuses, handles=node_handles)
            diag = diagnose_deadlock(dag, routing_state, pending)
            if diag is not None:
                structured = json.dumps(diag, ensure_ascii=False)
                error_message = f"工作流死锁：{len(pending)} 个节点无法调度\n{structured}"
            else:
                # 兜底：诊断三要素未齐（极少见，如状态不一致）仍写中文一句话失败
                error_message = f"工作流死锁：{len(pending)} 个节点无法调度"
            await execution.amark_failed(error_message)
            hook_execution = await self._load_execution_for_hooks(execution)
            await self.hooks.trigger("execution_failed", execution=hook_execution)
            return

        # c. 失败节点收口
        if failed:
            await execution.amark_failed(f"失败节点: {len(failed)}")
            hook_execution = await self._load_execution_for_hooks(execution)
            await self.hooks.trigger("execution_failed", execution=hook_execution)
            return

        # d. 完成：收集终端节点（无 outgoing）的输出
        final_output: dict = {}
        for node_id in completed:
            dag_node = dag.nodes.get(node_id)
            if dag_node and not dag_node.outgoing:
                final_output.update(node_outputs.get(node_id, {}))
        await execution.amark_completed(final_output)
        hook_execution = await self._load_execution_for_hooks(execution)
        await self.hooks.trigger("execution_completed", execution=hook_execution)

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
                node_snapshots: dict[str, dict] = exec_context.get("node_snapshots") or {}
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
                    trigger_data=execution.trigger_data
                    or {},  # ENG-03 唯一读取侧缺口：注入触发数据使 {{trigger.*}} 真实可解析
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
                delay = min(
                    300, max(1, retry_delay * (2 ** (attempt - 1)) + random.randint(0, retry_delay))
                )
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
                # tolerated fallback 持久化到 NE.output_data（Pitfall 4 显式决策）：
                # 节点 DB 状态为 FAILED，但带 `_tolerated` 标记 + fallback 输出，
                # 重入续跑重建时据此恢复 tolerated 语义与下游可见的 fallback 值
                # （主循环内存 node_outputs 拿不到，线程退出即丢失）。
                fallback = node.fallback_values or {"status": "skipped", "output": {}}
                tolerated_output = {**fallback, "_tolerated": True}
                node_execution.output_data = tolerated_output
                await node_execution.asave(update_fields=["output_data"])
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
        """收集节点的输入数据（委托 routing.collect_inputs 按 target_handle 归集）。

        调用点零改动；归集语义（扁平保底 + 同名键不覆盖 + 端口键补齐）由 routing
        纯函数统一承载（ENG-05），与回调续跑共用同一语义源。
        """
        return collect_inputs(dag, str(dag_node.id), node_outputs)

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
        """恢复暂停的执行，从中断点继续调度。

        18-04：废弃旧"COMPLETED→SKIPPED 改写 + initial_outputs"手法，改为按真实 NE
        状态重建（_rebuild_state_from_db）重入主循环——与回调续跑字面同源，skipped
        已是正式终态无需伪装为 completed 输出载体。
        """
        if execution.status != ExecutionStatus.PAUSED:
            raise ValueError("只能恢复已暂停的执行")

        # 1. 获取工作流和 DAG
        execution = await WorkflowExecution.objects.select_related("workflow").aget(pk=execution.pk)
        dag = await DAG.afrom_workflow(execution.workflow)

        # 2. QUEUED 节点重置为 PENDING（重建时归入 pending 重新调度）
        await NodeExecution.objects.filter(
            workflow_execution=execution,
            status=NodeExecutionStatus.QUEUED,
        ).aupdate(status=NodeExecutionStatus.PENDING)

        # 3. 更新执行状态并恢复
        execution.status = ExecutionStatus.RUNNING
        await execution.asave(update_fields=["status"])
        await self.hooks.trigger("execution_resumed", execution=execution)
        logger.info("execution_resumed", execution_id=str(execution.id))

        # 4. 重建真实状态重入主循环（is_resume=True 避免覆盖 started_at）
        _run_in_thread(
            self._rebuild_and_run(execution, dag),
            triggered_by_id=execution.triggered_by_id,
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
            ne
            async for ne in NodeExecution.objects.filter(
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

        # INGEST-01（14-04 / C2）：方案审批（human_approval + mode=plan_feishu）通过 →
        # 投递统一摄取。source_id 恒为同 execution 中生成节点（ai_plan_generation）的 key
        # （OQ-2 定案）；node FK 未必预加载，经 sync_to_async 安全取 node_type / config。
        node_meta = await sync_to_async(
            lambda: (node_execution.node.node_type, node_execution.node.config or {})
        )()
        node_type, node_config = node_meta
        if node_type == "human_approval" and node_config.get("mode") == "plan_feishu":
            # D2：方案生成源兼容两条路径——经典 ai_plan_generation（TechnicalPlan）与编排
            # ai_plan_research（PlanVersion 内联 output_data["plan"]）。normalizer
            # （knowledge/sources/workflow_plan.py）统一读 output_data["plan"]，两路径同构。
            generation_node_id = await (
                NodeExecution.objects.filter(
                    workflow_execution_id=node_execution.workflow_execution_id,
                    node__node_type__in=["ai_plan_generation", "ai_plan_research"],
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
        node_execution = await NodeExecution.objects.select_related("workflow_execution").aget(
            id=node_execution.id
        )
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
        node_execution = await NodeExecution.objects.select_related("workflow_execution").aget(
            id=node_execution.id
        )
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
        node_execution = await NodeExecution.objects.select_related("workflow_execution").aget(
            id=node_execution.id
        )
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

    # 容器回调恢复标记键（任一存在即触发"标记重跑"消费容器回调，A1 断裂修复）
    _RESUME_MARKERS = ("_resume_from_callback", "_confirmed_branch_name")

    async def _continue_after_node(
        self,
        execution: WorkflowExecution,
        node_execution: NodeExecution,
    ) -> None:
        """节点经回调终态后的续跑薄入口——重建状态重入主循环（ENG-01/02）。

        七条恢复入口（approve/reject/trigger_manual/skip_wait/trigger_resume/容器回调/
        分支确认）共用本入口，签名不变。三步：

        1. **执行级互斥**（先于任何节点重跑，防并发双执行）：仅 SUSPENDED 时原子抢锁
           ``filter(status=SUSPENDED).aupdate(status=RUNNING)``——抢锁失败（他人已抢）
           即放弃，杜绝同一挂起执行被两个回调起双循环（Pitfall 6 / T-18-05）。已
           RUNNING（外部入口预翻转 / inline 续跑）放行；终态直接 return。
        2. **标记重跑**（容器回调断裂 A1 修复）：节点仍 WAITING_* 且带恢复标记 →
           重置 RUNNING 经 ``_execute_node`` 重跑（复用重试/超时/on_error）；无标记仍
           WAITING → 等真正事件回调，不空转，还原挂起。
        3. **重建重入**：``_rebuild_state_from_db`` 重建真实状态集合 → ``_run_execution``
           重入同一 while 调度循环与 ``_finalize_run_state`` 收口（恢复后残留纯死锁在
           此暴露并转 FAILED）。
        """
        # 完成 hook（保留既有行为：容器/审批回调上报节点完成事件）
        await self.hooks.trigger(
            "node_completed",
            execution=execution,
            node_execution=node_execution,
        )

        # 重新加载执行 + 重建 DAG
        execution = await WorkflowExecution.objects.select_related("workflow").aget(id=execution.id)
        workflow = execution.workflow
        dag = await DAG.afrom_workflow(workflow)

        # --- 步骤 1：执行级互斥抢锁（先于任何节点重跑，防并发双执行 T-18-05） ---
        entry_status = execution.status
        if entry_status in (
            ExecutionStatus.COMPLETED,
            ExecutionStatus.FAILED,
            ExecutionStatus.CANCELLED,
            ExecutionStatus.TIMEOUT,
        ):
            logger.info(
                "continue_after_node_terminal",
                execution_id=str(execution.id),
                status=entry_status,
            )
            return
        if entry_status == ExecutionStatus.SUSPENDED:
            acquired = await WorkflowExecution.objects.filter(
                pk=execution.pk,
                status=ExecutionStatus.SUSPENDED,
            ).aupdate(status=ExecutionStatus.RUNNING)
            if not acquired:
                # 竞态：另一个续跑已原子抢到 SUSPENDED→RUNNING → 放弃（互斥）
                logger.info("resume_lock_lost", execution_id=str(execution.id))
                return
            execution.status = ExecutionStatus.RUNNING
        # else RUNNING/PENDING/PAUSED：外部入口已预翻转或 inline 续跑 → 放行（保留既有行为）

        # --- 步骤 2：标记重跑（容器回调断裂 A1 修复） ---
        await node_execution.arefresh_from_db()
        if node_execution.status in (
            NodeExecutionStatus.WAITING_EVENT,
            NodeExecutionStatus.WAITING_APPROVAL,
            NodeExecutionStatus.WAITING_INPUT,
        ):
            output_data = node_execution.output_data or {}
            if any(marker in output_data for marker in self._RESUME_MARKERS):
                dag_node = dag.nodes.get(str(node_execution.node_id))
                if dag_node is not None:
                    # 重置 RUNNING + 经 _execute_node 重跑（复用重试/超时/on_error）；
                    # 节点 execute 内消费恢复标记后终态，再由步骤 3 重建放行下游。
                    node_execution.status = NodeExecutionStatus.RUNNING
                    await node_execution.asave(update_fields=["status"])
                    rerun_outputs = await self._collect_all_outputs(execution)
                    rerun_input = self._collect_inputs(dag_node, dag, rerun_outputs)
                    await self._execute_node(execution, dag_node, rerun_input, rerun_outputs)
            else:
                # 无恢复标记仍 WAITING → 等待真正事件回调，不空转；还原挂起态
                logger.warning(
                    "continue_after_node_waiting_no_marker",
                    execution_id=str(execution.id),
                    node_id=str(node_execution.node_id),
                )
                await execution.amark_suspended()
                return

        # --- 步骤 3：重建状态重入主循环 ---
        await self._rebuild_and_run(execution, dag)

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

    async def _rebuild_and_run(self, execution: WorkflowExecution, dag: DAG) -> None:
        """重建 DB 状态并重入主循环调度（回调续跑 / paused-resume 共用入口）。"""
        rebuilt_state = await self._rebuild_state_from_db(execution, dag)
        await self._run_execution(
            execution,
            dag,
            execution.input_data or {},
            is_resume=True,
            rebuilt_state=rebuilt_state,
        )

    async def _rebuild_state_from_db(self, execution: WorkflowExecution, dag: DAG) -> dict:
        """从 DB NE 真实状态重建主循环调度集合（重入续跑与完成判定的唯一状态源）。

        映射规则（与主循环 node_statuses/node_handles 维护点对齐，消除两套判定漂移）：
        - COMPLETED → completed + STATUS_COMPLETED + 从 output_data._next_handle 还原 handle；
        - SKIPPED → skipped + STATUS_SKIPPED（真正未选中支，不放行下游）；
        - FAILED 且 output_data._tolerated → tolerated + completed + STATUS_TOLERATED
          （fallback 输出剥离 _tolerated 标记后入 node_outputs，与首跑内存值一致）；
        - FAILED（非 tolerated）→ failed + STATUS_FAILED；
        - WAITING_* → waiting + STATUS_WAITING；
        - CANCELLED/TIMEOUT → 不可解析终态，node_statuses 不置（阻塞下游 → 死锁兜底）；
        - PENDING/QUEUED/RUNNING / 无 NE → pending（重新调度）。

        node_outputs 双键（UUID + short_id）保证模板变量解析（与 _collect_all_outputs 一致）。
        """
        node_outputs: dict[str, dict] = {}
        completed_nodes: set[str] = set()
        failed_nodes: set[str] = set()
        skipped_nodes: set[str] = set()
        tolerated_failures: set[str] = set()
        waiting_nodes_mem: set[str] = set()
        node_statuses: dict[str, str] = {}
        node_handles: dict[str, str] = {}

        ne_status: dict[str, str] = {}
        async for ne in NodeExecution.objects.filter(
            workflow_execution=execution,
        ).select_related("node"):
            nid = str(ne.node_id)
            ne_status[nid] = ne.status
            out = ne.output_data or {}
            short_id = ne.node.short_id

            if ne.status == NodeExecutionStatus.COMPLETED:
                completed_nodes.add(nid)
                node_statuses[nid] = STATUS_COMPLETED
                node_outputs[nid] = out
                if short_id:
                    node_outputs[short_id] = out
                handle = out.get("_next_handle")
                if handle and handle != "default":
                    node_handles[nid] = handle
            elif ne.status == NodeExecutionStatus.SKIPPED:
                skipped_nodes.add(nid)
                node_statuses[nid] = STATUS_SKIPPED
                if out:
                    node_outputs[nid] = out
                    if short_id:
                        node_outputs[short_id] = out
            elif ne.status == NodeExecutionStatus.FAILED:
                if out.get("_tolerated"):
                    tolerated_failures.add(nid)
                    completed_nodes.add(nid)
                    node_statuses[nid] = STATUS_TOLERATED
                    clean = {k: v for k, v in out.items() if k != "_tolerated"}
                    node_outputs[nid] = clean
                    if short_id:
                        node_outputs[short_id] = clean
                    handle = out.get("_next_handle")
                    if handle and handle != "default":
                        node_handles[nid] = handle
                else:
                    failed_nodes.add(nid)
                    node_statuses[nid] = STATUS_FAILED
            elif ne.status in (
                NodeExecutionStatus.WAITING_APPROVAL,
                NodeExecutionStatus.WAITING_EVENT,
                NodeExecutionStatus.WAITING_INPUT,
            ):
                waiting_nodes_mem.add(nid)
                node_statuses[nid] = STATUS_WAITING
            # CANCELLED/TIMEOUT：不可解析终态，node_statuses 不置 → 阻塞下游触发死锁兜底

        pending_nodes: set[str] = set()
        for nid in dag.nodes:
            st = ne_status.get(nid)
            if st is None or st in (
                NodeExecutionStatus.PENDING,
                NodeExecutionStatus.QUEUED,
                NodeExecutionStatus.RUNNING,
            ):
                pending_nodes.add(nid)

        return {
            "node_outputs": node_outputs,
            "completed_nodes": completed_nodes,
            "failed_nodes": failed_nodes,
            "skipped_nodes": skipped_nodes,
            "tolerated_failures": tolerated_failures,
            "node_statuses": node_statuses,
            "node_handles": node_handles,
            "waiting_nodes_mem": waiting_nodes_mem,
            "pending_nodes": pending_nodes,
        }

    async def _check_execution_complete(self, execution: WorkflowExecution) -> None:
        """[兼容入口] 终端节点回调后的完成判定，委托重建 + _finalize_run_state 单一收口。

        回调续跑主路径已改为 ``_continue_after_node`` 重入主循环，不再调用本方法；保留供
        外部历史调用方（test_hooks 等）使用，统一委托收口函数避免判定逻辑漂移。仅当无
        pending/waiting 活跃节点时收口（保留原 all-done 语义）。
        """
        execution = await WorkflowExecution.objects.select_related("workflow").aget(id=execution.id)
        dag = await DAG.afrom_workflow(execution.workflow)
        state = await self._rebuild_state_from_db(execution, dag)
        if state["pending_nodes"] or state["waiting_nodes_mem"]:
            return
        await self._finalize_run_state(
            execution,
            dag,
            pending=state["pending_nodes"],
            waiting=state["waiting_nodes_mem"],
            failed=state["failed_nodes"],
            completed=state["completed_nodes"],
            node_statuses=state["node_statuses"],
            node_handles=state["node_handles"],
            node_outputs=state["node_outputs"],
        )

    async def _collect_all_outputs(self, execution: WorkflowExecution) -> dict:
        """Collect outputs from all completed nodes.

        同时按 UUID 和 short_id 存储，确保模板变量
        {{nodes.<short_id>.field}} 能正确解析。
        """
        completed_nodes = [
            ne
            async for ne in NodeExecution.objects.filter(
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
            ne
            async for ne in NodeExecution.objects.filter(
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
            curr_edges.add(
                (
                    str(edge.source_node_id),
                    str(edge.target_node_id),
                    edge.source_handle or "default",
                )
            )

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
        original_execution = await WorkflowExecution.objects.select_related("workflow").aget(
            pk=original_execution.pk
        )
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
            space_id=workflow.space_id,
            status=ExecutionStatus.PENDING,
            trigger_type="resume",
            triggered_by=triggered_by,
            # ENG-03：继承原执行 trigger_data（source/raw_payload 不丢失），再附加 resume metadata
            trigger_data={
                **(original_execution.trigger_data or {}),
                "metadata": {
                    "resumed_from": str(original_execution.id),
                    "failed_node_id": failed_node_id,
                },
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
                ),
                triggered_by_id=new_execution.triggered_by_id,
            )

        return new_execution
