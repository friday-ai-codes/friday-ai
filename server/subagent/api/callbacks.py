"""容器统一回调端点（Phase）。

POST /api/containers/callback/

容器 SubAgent 通过此端点上报状态变更：
- completed: 任务完成，创建 TaskResult
- failed: 任务失败，更新 session 状态
- heartbeat: 心跳，更新 last_heartbeat_at
- question: 提问，触发 Feishu 卡片
- progress: 进度更新，写入 last_output
"""

import asyncio
from typing import Any

import structlog
from adrf.views import APIView
from django.conf import settings
from django.utils import timezone
from rest_framework import status
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from structlog.stdlib import BoundLogger

from agents.call_source import CallSource
from common.logging import redact_secrets_in_text
from interactions.ledger import arecord_llm_usage
from orchestration.progress_payload import parse_progress_payload
from services.protocols import CallbackType
from subagent.models import ActionLog, SubAgentSession, TaskResult, TokenUsage

from .serializers import (
    ActionLogPayloadSerializer,
    CallbackSerializer,
    CompletedPayloadSerializer,
    FailedPayloadSerializer,
    HeartbeatPayloadSerializer,
    ProgressPayloadSerializer,
    QuestionPayloadSerializer,
    TokenUsagePayloadSerializer,
)

logger = structlog.get_logger()

# 终态集合 — 处于终态的 session 不再接受回调
_TERMINAL_STATUSES = {
    SubAgentSession.Status.COMPLETED,
    SubAgentSession.Status.ERROR,
    SubAgentSession.Status.TIMEOUT,
    SubAgentSession.Status.CANCELLED,
}

# 数据补充类回调绕过终态检查（它们不改变状态，只追加数据）
_DATA_APPEND_TYPES = {CallbackType.ACTION_LOG, CallbackType.TOKEN_USAGE}

# SDK transcript 落库上限（字符）。超限丢弃走语义重建回退，防 DB 单行膨胀 +
# 留余量给 Django DATA_UPLOAD_MAX_MEMORY_SIZE（默认 2.5MB）。
MAX_SDK_TRANSCRIPT_CHARS = 1_500_000


def _notify_barrier_manager(session: SubAgentSession, log: BoundLogger) -> None:
    """通知 BarrierManager 任务完成/失败 — 由 chat_deep_analysis 回调触发。"""
    is_success = session.status == SubAgentSession.Status.COMPLETED

    async def _do_notify() -> None:
        try:
            from orchestration.barrier import get_barrier_manager
            from orchestration.contracts import BlockingTaskResult

            output_text = ""
            error_text = ""
            if is_success:
                task_result = await TaskResult.objects.filter(session=session).afirst()
                if task_result:
                    output_text = task_result.text_output or ""
                    if not output_text and task_result.raw_output:
                        output_text = str(task_result.raw_output)[:3000]
            else:
                error_text = session.last_error or f"Task {session.status}"

            result: BlockingTaskResult = {
                "task_id": session.session_id,
                "task_type": session.task_type or "deep_analysis",
                "success": is_success,
                "output": output_text,
                "error": error_text,
            }

            barrier = get_barrier_manager()
            satisfied = await barrier.task_completed(session.session_id, result)
            log.info(
                "barrier_task_notified",
                session_id=session.session_id,
                success=is_success,
                barrier_satisfied=satisfied,
            )
        except Exception:
            log.exception("barrier_notify_error", session_id=session.session_id)

    try:
        loop = asyncio.get_running_loop()
        loop.create_task(_do_notify())
    except RuntimeError:
        asyncio.run(_do_notify())


def _schedule_agent_session_resume(session: SubAgentSession, log: BoundLogger) -> None:
    """触发 Agent 会话恢复（当容器完成时）。

    仅当 session 有 main_session 但无 node_execution 时触发（纯 Agent 场景）。
    如果有 node_execution，由 workflow 恢复处理。

    Args:
        session: SubAgentSession 实例
        log: Bound logger
    """
    # 如果有 node_execution，由 workflow 恢复处理
    if session.node_execution_id:
        log.debug("has_node_execution_skip_agent_resume")
        return

    if isinstance(session.last_output, dict):
        src = session.last_output.get("source")
        if src == "chat_deep_analysis":
            log.info("chat_deep_analysis_notify_barrier", session_id=session.session_id)
            _notify_barrier_manager(session, log)
            return
        if src == "plan_research":
            # plan_research 容器复用 AgentSession+SubAgentSession 底座，但调研结果
            # 由 _handle_research_completion / _handle_research_failure（→ barrier）
            # 唯一驱动，绝不能在此触发 SDKAgentRunner resume 合成 AgentSession——否则
            # 每次调研容器完成/失败的 happy path 都会拉起一个无上下文的幽灵 agent
            # 执行并双重处理同一回调（Phase 39 CR-01）。与 chat_deep_analysis 短路对称。
            #
            # 注（Phase 41 CR-02）：工作流入口节点派发的调研容器会设置 node_execution_id，
            # 故工作流路径已在本函数顶部 `if session.node_execution_id: return` 提前短路，
            # 并改由 _schedule_workflow_resume 重新驱动挂起节点（researching→merging→done）。
            # 本分支仅覆盖 Chat 入口（无 node_execution）下的 plan_research 容器——同样不在
            # 此触发 agent resume（barrier 唯一驱动）。
            #
            # RESUME-01 接线（消化 D-2 a/b）：委派到 _schedule_chat_plan_resume——所有调研
            # 终态后续驱 engine 到 done 并经 barrier 回灌主方案。entrypoint==chat 守门在
            # _schedule_chat_plan_resume 内做（不在此重复查询，分支保持薄）。
            log.debug("plan_research_delegate_chat_resume", session_id=session.session_id)
            _schedule_chat_plan_resume(session, log)
            return
        if src == "repo_verify":
            # repo_verify 容器复用 AgentSession+SubAgentSession 底座，但 verdict 由
            # _handle_repo_verify_completion / _handle_repo_verify_failure 唯一驱动落
            # RepoVerifyTask（经 service）。绝不在此触发 SDKAgentRunner resume 合成幽灵
            # agent（与 plan_research / chat_deep_analysis 短路对称，88-03 Pitfall）。
            # 工作流入口（有 node_execution_id）已在本函数顶部短路并改由
            # _schedule_workflow_resume 续驱挂起节点；Chat 入口此处直接 no-op。
            log.debug("repo_verify_no_agent_resume", session_id=session.session_id)
            return

    # 检查是否有 main_session
    if not session.main_session_id:
        log.debug("no_main_session_skip_agent_resume")
        return

    async def _prepare_and_resume():
        """异步准备并调度 Agent 会话恢复。"""
        try:
            from subagent.models import TaskResult

            # 获取 TaskResult
            task_result = await TaskResult.objects.filter(
                session=session,
            ).afirst()

            # 构建结果消息
            if task_result:
                if session.status == SubAgentSession.Status.COMPLETED:
                    result_msg = f"SubAgent 任务完成。\n\n结果：\n{task_result.text_output[:2000]}"
                else:
                    result_msg = f"SubAgent 任务失败：{session.last_error}"
            else:
                if session.status == SubAgentSession.Status.COMPLETED:
                    result_msg = "SubAgent 任务完成。"
                else:
                    result_msg = f"SubAgent 任务失败：{session.last_error}"

            # 调度 Agent 会话恢复
            from agents.models import AgentSession
            from tasks.agent_tasks import schedule_resume_agent_session

            await session.arefresh_from_db()
            if session.main_session_id:
                main_session = await AgentSession.objects.filter(
                    id=session.main_session_id,
                ).afirst()
                if main_session:
                    schedule_resume_agent_session(
                        session_id=main_session.session_id,
                        user_response=result_msg,
                    )
                    log.info(
                        "agent_session_resume_scheduled",
                        main_session_id=main_session.session_id,
                    )

        except Exception as e:
            log.exception("agent_session_resume_error", error=str(e))

    try:
        loop = asyncio.get_running_loop()
        loop.create_task(_prepare_and_resume())
    except RuntimeError:
        # 没有运行中的事件循环
        asyncio.run(_prepare_and_resume())


#: 续跑重试次数。瞬时故障（DB 抖动、连接失效）占多数，几次退避基本能过；
#: 耗尽即判定为持续性故障，走标失败而不是继续挂着。
_RESUME_MAX_ATTEMPTS = 3

#: 退避基数（秒），第 N 次重试前等 N × 该值。
_RESUME_RETRY_BACKOFF_SECONDS = 2.0

#: 持有在途续跑任务的强引用。asyncio 的 loop.create_task 只保弱引用，不持有就
#: 可能在 await 点被 GC 回收，症状是续跑「偶尔就是没发生」且不留任何日志。
_PENDING_RESUME_TASKS: set[asyncio.Task] = set()


async def _mark_execution_failed_after_resume_exhausted(
    session: SubAgentSession,
    error: Exception | None,
    log: BoundLogger,
) -> None:
    """续跑重试耗尽后把工作流执行标失败，避免永久停在 SUSPENDED。

    best-effort：这一步再失败也只能记日志——但至少前面已经有 workflow_resume_exhausted
    这个可查询、可告警的事件，不再是完全静默。
    """
    try:
        from workflows.models.execution import ExecutionStatus, NodeExecution

        node_exec = (
            await NodeExecution.objects.select_related("workflow_execution")
            .filter(id=session.node_execution_id)
            .afirst()
        )
        if not node_exec:
            return
        execution = node_exec.workflow_execution
        if execution.status in (ExecutionStatus.COMPLETED, ExecutionStatus.FAILED):
            return
        execution.status = ExecutionStatus.FAILED
        execution.error_message = (
            f"容器回调后续跑失败，已重试 {_RESUME_MAX_ATTEMPTS} 次仍未成功: {error}"
        )
        await execution.asave(update_fields=["status", "error_message"])
        log.error(
            "workflow_marked_failed_after_resume_exhausted",
            workflow_execution_id=str(execution.id),
        )
    except Exception as exc:  # noqa: BLE001 — 标失败本身失败不再上抛，事件已留痕
        log.exception("mark_execution_failed_error", error=str(exc))


def _schedule_workflow_resume(session: SubAgentSession, log: BoundLogger) -> None:
    """触发 workflow 恢复（异步，不阻塞回调响应）。

    当容器完成时，检查该节点的所有 SubAgentSession 是否都已终态，
    如果是则恢复 workflow 执行。
    """
    if not session.node_execution_id:
        log.debug("no_node_execution_skip_resume")
        return

    async def _resume():
        try:
            from django.db import close_old_connections

            from workflows.engine.scheduler import WorkflowEngine
            from workflows.models.execution import NodeExecution

            # 关闭旧连接（防止长时间运行后的连接问题）
            close_old_connections()

            # 获取 node_execution
            node_exec = (
                await NodeExecution.objects.select_related("workflow_execution")
                .filter(id=session.node_execution_id)
                .afirst()
            )

            if not node_exec:
                log.warning("node_execution_not_found_for_resume")
                return

            # 检查该节点的所有 SubAgentSession 是否都已终态
            pending_count = await SubAgentSession.objects.filter(
                node_execution=node_exec,
                status__in=[
                    SubAgentSession.Status.PENDING,
                    SubAgentSession.Status.RUNNING,
                ],
            ).acount()

            if pending_count > 0:
                log.info(
                    "pending_subagents_remain",
                    pending_count=pending_count,
                    node_execution_id=str(node_exec.id),
                )
                return

            # 所有任务完成，设置恢复标记并触发 workflow 恢复
            output_data = node_exec.output_data or {}
            output_data["_resume_from_callback"] = True
            output_data["_all_containers_completed"] = True

            # 保存每个 session 的结果摘要
            session_results = {}
            async for s in SubAgentSession.objects.filter(node_execution=node_exec):
                session_results[s.session_id] = {
                    "status": s.status,
                    "error": s.last_error,
                }
            output_data["_session_results"] = session_results

            node_exec.output_data = output_data
            await node_exec.asave(update_fields=["output_data"])

            # 恢复 workflow：统一续跑入口（18-04）。节点仍 WAITING_EVENT 且带
            # _resume_from_callback 标记 → 入口检测后经 _execute_node 重跑该节点
            # （消费标记，修复容器回调断裂 A1），再重建状态重入主循环；SUSPENDED→RUNNING
            # 抢锁与互斥由 _continue_after_node 统一负责，本模块不做手工状态翻转。
            engine = WorkflowEngine()
            await engine._continue_after_node(
                node_exec.workflow_execution,
                node_exec,
            )

            log.info(
                "workflow_resumed_after_container_completion",
                node_execution_id=str(node_exec.id),
                workflow_execution_id=str(node_exec.workflow_execution.id),
            )

        except Exception as e:
            log.exception("workflow_resume_error", error=str(e))
            raise

    async def _resume_with_retry() -> None:
        """有界重试 + 终局标失败。

        续跑此前是纯 fire-and-forget：异常只 log.exception，执行就永久停在
        SUSPENDED / WAITING_EVENT。前端显示「等待容器」，容器其实早退出了，只能
        人工介入，而且没有任何可查询的失败信号。

        DB 抖动之类的瞬时故障占多数，先按退避重试；重试耗尽说明是持续性故障，
        此时把执行显式标 failed —— 一个可见的失败远好过一个不可见的永久挂起。
        """
        last_error: Exception | None = None
        for attempt in range(1, _RESUME_MAX_ATTEMPTS + 1):
            try:
                await _resume()
                return
            except Exception as exc:  # noqa: BLE001 — 每轮都已记日志，此处决定是否再试
                last_error = exc
                if attempt < _RESUME_MAX_ATTEMPTS:
                    await asyncio.sleep(_RESUME_RETRY_BACKOFF_SECONDS * attempt)

        log.error(
            "workflow_resume_exhausted",
            attempts=_RESUME_MAX_ATTEMPTS,
            error=str(last_error),
            session_id=str(session.session_id),
        )
        await _mark_execution_failed_after_resume_exhausted(session, last_error, log)

    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        # 没有运行中的事件循环，创建新的
        asyncio.run(_resume_with_retry())
        return

    # 必须持强引用：loop.create_task 只保弱引用，任务可能在 await 点被 GC 回收，
    # 表现为续跑「有时候就是没发生」且无任何日志。
    task = loop.create_task(_resume_with_retry())
    _PENDING_RESUME_TASKS.add(task)
    task.add_done_callback(_PENDING_RESUME_TASKS.discard)


def _schedule_chat_plan_resume(session: SubAgentSession, log: BoundLogger) -> None:
    """触发 chat 入口 plan_research 续驱 + barrier 回灌（RESUME-01 接线，消化 D-2 a/b）。

    与 ``_schedule_workflow_resume`` 对称（fire-and-forget + 幂等 + fail-soft），但驱动的是
    **chat 入口**（无 node_execution）的 ``PlanSession``：所有 RepoResearchTask 终态后，用
    43-02 的同源续驱 helper ``adrive_convergence_session_to_pause_or_terminal`` 把 engine 续驱到
    ``done``（消化缺口 b：``amaybe_complete_research`` 只 researching→merging，chat 入口此后
    无消费者驱动 ``engine.advance``），再经 ``BarrierManager.task_completed`` 回灌主方案到
    chat 会话（消化缺口 a：chat barrier 从不被通知）。

    安全（T-43-TAMPER）：以服务端权威字段 ``PlanSession.entrypoint == CHAT`` 守门——绝不信
    runner 可经 progress 篡改的字段，不放大既有信任面（对齐 cross_repo_relevance 用权威字段
    范式）。日志仅记 plan_session_id / status / barrier_satisfied 非敏感字段。
    """

    async def _resume() -> None:
        try:
            from delivery.models import (
                ConvergenceSession,
                ConvergenceSessionEntrypoint,
                ConvergenceSessionStatus,
                RepoResearchTask,
            )
            from orchestration.barrier import get_barrier_manager
            from orchestration.contracts import BlockingTaskResult
            from services.process_runtime import (
                aall_research_tasks_terminal,
                adrive_convergence_session_to_pause_or_terminal,
                build_orchestration_engine,
            )

            # a. 取 plan_session（缺失/取不到 → no-op）
            lo = session.last_output if isinstance(session.last_output, dict) else {}
            plan_session_id = lo.get("plan_session_id")
            if not plan_session_id:
                return
            plan_session = await ConvergenceSession.objects.filter(id=plan_session_id).afirst()
            if plan_session is None:
                return

            # b. 守门（T-43-TAMPER）：仅 chat 入口续驱，用服务端权威字段 entrypoint
            if str(plan_session.entrypoint) != str(ConvergenceSessionEntrypoint.CHAT):
                return

            # b2. 归属校验（T-43-TAMPER 加固，WR-03）：交叉验证本 session 的 research_task 确属
            #     该 plan_session，绝不单信 runner 可经 progress 篡改的 last_output.plan_session_id
            #     —— 否则半可信 runner 可把 plan_session_id 指向他人受害 PlanSession 触发越权续驱。
            research_task_id = lo.get("research_task_id")
            if research_task_id:
                task = await RepoResearchTask.objects.filter(id=research_task_id).afirst()
                if task is None or str(task.session_id) != str(plan_session.id):
                    return

            # c. 幂等短路：仅当全部调研终态才续驱（多仓逐个完成时只有最后一个真正续驱）
            if not await aall_research_tasks_terminal(plan_session.id):
                return

            # d. 构建 chat 入口 engine（无 node_execution_id），绝不新建第二个 engine 工厂
            engine = build_orchestration_engine()

            # e. 先续驱到终态（43-02 同源 helper）
            plan_session = await adrive_convergence_session_to_pause_or_terminal(engine, plan_session)

            # e2. 终态守门（WR-02）：adrive 可能在非终态短路返回（clarifying-pending /
            #     researching-在途），此时不构建 BlockingTaskResult、不通知 barrier——否则会以
            #     success=False 提前把 chat 阻塞任务误解析为失败。仅 {DONE, FAILED} 才回灌。
            if plan_session.status not in (
                ConvergenceSessionStatus.DONE,
                ConvergenceSessionStatus.FAILED,
            ):
                log.info(
                    "chat_plan_resume_resuspended",
                    plan_session_id=str(plan_session.id),
                    status=plan_session.status,
                )
                return

            # f. 再构建 BlockingTaskResult（复用 deep_analysis 回灌通道；A2：失败 output="")
            success = plan_session.status == ConvergenceSessionStatus.DONE
            output_text = str(plan_session.current_artifact_version_id or "") if success else ""
            error_text = "" if success else str(plan_session.error or {})
            result: BlockingTaskResult = {
                "task_id": str(plan_session.id),
                "task_type": "plan_research",
                "success": success,
                "output": output_text,
                "error": error_text,
            }

            # g. barrier 回灌（关键 Pitfall 3：task_id 用 str(plan_session.id) 而非 session_id；
            #    chat barrier 注册键见 plan_research_tools.py:249）。barrier 已去重（幂等安全）。
            satisfied = await get_barrier_manager().task_completed(str(plan_session.id), result)
            log.info(
                "chat_plan_resume_notified",
                plan_session_id=str(plan_session.id),
                status=plan_session.status,
                barrier_satisfied=satisfied,
            )
        except Exception:
            log.warning("chat_plan_resume_error", session_id=session.session_id)

    try:
        loop = asyncio.get_running_loop()
        loop.create_task(_resume())
    except RuntimeError:
        # 没有运行中的事件循环，创建新的
        asyncio.run(_resume())


async def _send_failure_notification(
    session: SubAgentSession,
    error_msg: str,
    retry_count: int = 0,
) -> None:
    """发送失败通知给任务触发者。

    通过飞书卡片通知用户任务失败。
    只通知任务触发者（用户决策）。
    """
    log = logger.bind(session_id=session.session_id)

    try:
        from feishu.cards.failure_notification_card import build_failure_notification_card

        # 获取触发者信息（从 main_session 或 node_execution）
        chat_id = await _resolve_notification_chat_id(session)
        if not chat_id:
            log.warning("failure_notification_no_chat_id")
            return

        repository_name = ""
        if session.last_output and isinstance(session.last_output, dict):
            repository_name = session.last_output.get("repository_name", "")

        card = build_failure_notification_card(
            task_type=session.task_type,
            error_message=error_msg,
            retry_count=retry_count,
            repository_name=repository_name,
            session_id=session.session_id,
        )

        # 发送卡片
        await _send_feishu_card(chat_id, card)
        log.info("failure_notification_sent", chat_id=chat_id)

    except Exception as e:
        log.error("failure_notification_error", error=str(e))


async def _resolve_notification_chat_id(session: SubAgentSession) -> str:
    """解析通知目标的 chat_id。"""
    # 优先从 main_session 获取（metadata 中的 chat_id）
    if session.main_session_id:
        from agents.models import AgentSession

        main = await AgentSession.objects.filter(pk=session.main_session_id).afirst()
        if main and main.metadata:
            chat_id: str = main.metadata.get("chat_id", "")
            if chat_id:
                return chat_id

    # 从 node_execution 获取
    if session.node_execution_id:
        from workflows.models.execution import NodeExecution

        ne = (
            await NodeExecution.objects.select_related("node")
            .filter(pk=session.node_execution_id)
            .afirst()
        )
        if ne and ne.node and ne.node.config:
            return ne.node.config.get("chat_id", "")

    return ""


async def _send_feishu_card(chat_id: str, card: dict[str, Any]) -> None:
    """发送飞书卡片。"""
    try:
        from services.feishu_im import FeishuIMClient

        app_id = getattr(settings, "FEISHU_APP_ID", "")
        app_secret = getattr(settings, "FEISHU_APP_SECRET", "")

        if not app_id or not app_secret:
            logger.warning("feishu_config_missing")
            return

        client = FeishuIMClient(app_id=app_id, app_secret=app_secret)
        await client.send_card(
            receive_id=chat_id,
            receive_id_type="chat_id",
            card=card,
        )
    except Exception as e:
        logger.exception("feishu_card_send_error", error=str(e))


class ContainerCallbackView(APIView):
    """容器统一回调端点。

    所有容器 SubAgent 通过 POST 请求上报状态。
    使用 CONTAINER_CALLBACK_TOKEN 进行身份验证。
    """

    permission_classes = [AllowAny]

    async def post(self, request):
        # 1. 反序列化 + 基础验证
        serializer = CallbackSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(
                {"detail": "Invalid callback payload", "errors": serializer.errors},
                status=status.HTTP_400_BAD_REQUEST,
            )

        data = serializer.validated_data
        callback_type = data["type"]
        session_id = data["session_id"]
        token = data["token"]
        payload = data.get("payload", {})

        log = logger.bind(
            callback_type=callback_type,
            session_id=session_id,
        )

        # LOG-07：容器回调原始留痕（脱敏后入库，best-effort 绝不反噬回调主流程）。
        # 仅记录生命周期/用户相关回调（completed/failed/question），跳过高频
        # heartbeat/progress/action_log/token_usage 以免撑爆留痕表（per 观测规范「高频禁刷屏」）。
        if callback_type in {
            CallbackType.COMPLETED,
            CallbackType.FAILED,
            CallbackType.QUESTION,
        }:
            from system.webhook_recorder import client_ip, record_inbound_webhook

            await record_inbound_webhook(
                kind="container_callback",
                raw_body=request.data,
                headers=dict(request.headers),
                source_ip=client_ip(request),
                verified=False,
                correlation={
                    "session_id": session_id,
                    "callback_type": str(callback_type),
                },
            )

        # 2. Token 验证
        expected_token = getattr(settings, "CONTAINER_CALLBACK_TOKEN", "")
        if not expected_token or token != expected_token:
            log.warning("callback_token_invalid")
            return Response(
                {"detail": "Invalid token"},
                status=status.HTTP_403_FORBIDDEN,
            )

        # 3. Session 查找
        try:
            session = await SubAgentSession.objects.aget(session_id=session_id)
        except SubAgentSession.DoesNotExist:
            log.warning("callback_session_not_found")
            return Response(
                {"detail": f"Session not found: {session_id}"},
                status=status.HTTP_404_NOT_FOUND,
            )

        # 4. 终态检查 — 已完成的 session 拒绝重复回调（数据补充类回调除外）
        if session.status in _TERMINAL_STATUSES and callback_type not in _DATA_APPEND_TYPES:
            log.info("callback_terminal_state", current_status=session.status)
            return Response(
                {"detail": "Session already in terminal state", "status": session.status},
                status=status.HTTP_409_CONFLICT,
            )

        # 5. 分发处理
        handler = _HANDLERS.get(callback_type)
        if not handler:
            return Response(
                {"detail": f"Unknown callback type: {callback_type}"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        return await handler(session, payload, log)


# === CodingSession 回调扩展 (implementation) ===


async def _persist_sdk_session(
    coding_session: Any,
    sdk_session_id: str,
    sdk_transcript: str,
) -> None:
    """落库 Claude Code SDK 会话数据到 CodingSession，支撑 7 天内 resume 续跑。

    transcript 超 ``MAX_SDK_TRANSCRIPT_CHARS`` 则丢弃（仅留 session_id 也无法 resume，
    一并置空 session_id 走语义重建回退），防 DB 单行膨胀。
    """
    from django.utils import timezone

    if not sdk_session_id:
        return

    if sdk_transcript and len(sdk_transcript) > MAX_SDK_TRANSCRIPT_CHARS:
        logger.warning(
            "sdk_transcript_oversize_dropped",
            coding_session_id=str(coding_session.id),
            size=len(sdk_transcript),
            cap=MAX_SDK_TRANSCRIPT_CHARS,
        )
        return

    coding_session.sdk_session_id = sdk_session_id
    coding_session.sdk_transcript = sdk_transcript
    coding_session.sdk_session_saved_at = timezone.now()
    await coding_session.asave(
        update_fields=[
            "sdk_session_id",
            "sdk_transcript",
            "sdk_session_saved_at",
            "updated_at",
        ]
    )
    logger.info(
        "sdk_session_persisted",
        coding_session_id=str(coding_session.id),
        has_transcript=bool(sdk_transcript),
    )

    # 落库成功后镜像到 SessionStore（Redis）支持跨容器/跨副本/冷启动 resume。
    # best-effort：镜像失败绝不影响回调落库（DB 仍是真相源，HOOK-04）。
    try:
        from chat.session_store import SessionStore

        await SessionStore().mirror(coding_session=coding_session)
    except Exception:  # noqa: BLE001 — 镜像 best-effort，绝不反噬回调主流程
        pass


async def _update_coding_session_on_complete(
    session: SubAgentSession,
    sdk_session_id: str = "",
    sdk_transcript: str = "",
) -> None:
    """容器完成回调 -- 根据 task_type 区分 Phase/2，resume CodingSession graph。

    Phase (coding): 提取 suggested_commit_message，resume graph 进入 awaiting_confirmation。
    Phase (coding_commit): resume graph 标记 completed。
    兼容旧流程: 非 graph 管理的 session 直接 amark_completed。

    ``sdk_session_id`` / ``sdk_transcript`` 非空时落库到 CodingSession，供 resume 续跑。
    """
    from chat.coding_events import store_coding_complete_to_message
    from chat.models import CodingSession

    coding_session = await CodingSession.objects.filter(
        subagent_session=session,
    ).afirst()
    if coding_session is None:
        return

    await _persist_sdk_session(coding_session, sdk_session_id, sdk_transcript)

    task_result = await TaskResult.objects.filter(session=session).afirst()
    if (
        task_result
        and task_result.branch_name
        and task_result.branch_name != coding_session.branch_name
    ):
        coding_session.branch_name = task_result.branch_name
        await coding_session.asave(update_fields=["branch_name", "updated_at"])

    last_output = session.last_output if isinstance(session.last_output, dict) else {}
    effective_task_type = str(last_output.get("task_type") or session.task_type)

    if effective_task_type == "coding":
        # Phase 完成: 提取 suggested_commit_message，resume graph
        suggested_msg = ""
        if isinstance(session.last_output, dict):
            suggested_msg = session.last_output.get("suggested_commit_message", "")

        from langgraph.types import Command

        from orchestration.checkpointer import get_checkpointer
        from orchestration.coding_graph import build_coding_graph

        checkpointer = await get_checkpointer()
        graph = build_coding_graph().compile(checkpointer=checkpointer)
        config = {"configurable": {"thread_id": f"coding-{coding_session.id}"}}

        try:
            await graph.ainvoke(
                Command(resume={"success": True, "suggested_commit_message": suggested_msg}),
                config=config,
            )
            logger.info(
                "coding_session_phase1_complete",
                coding_session_id=str(coding_session.id),
            )
        except Exception as exc:
            logger.exception(
                "coding_graph_resume_complete_fail",
                coding_session_id=str(coding_session.id),
                phase="phase1",
            )
            await coding_session.amark_failed(f"编码流程恢复失败: {exc}")

    elif effective_task_type == "coding_commit":
        # Phase 完成: resume graph，三阶段流程中 graph 继续执行到 PR 创建/跳过，
        # store_coding_complete_to_message 已在 create_pr_or_skip_node 中调用
        from langgraph.types import Command

        from orchestration.checkpointer import get_checkpointer
        from orchestration.coding_graph import build_coding_graph

        checkpointer = await get_checkpointer()
        graph = build_coding_graph().compile(checkpointer=checkpointer)
        config = {"configurable": {"thread_id": f"coding-{coding_session.id}"}}

        try:
            await graph.ainvoke(
                Command(resume={"success": True}),
                config=config,
            )
            logger.info(
                "coding_session_phase2_complete",
                coding_session_id=str(coding_session.id),
            )
        except Exception as exc:
            logger.exception(
                "coding_graph_resume_complete_fail",
                coding_session_id=str(coding_session.id),
                phase="phase2",
            )
            await coding_session.amark_failed(f"提交后 PR 流程恢复失败: {exc}")

    else:
        # 兼容旧流程（非 graph 管理的 session）
        pr_url = task_result.pr_url if task_result else ""
        await coding_session.amark_completed(pr_url=pr_url)

        # INGEST-02（14-06）：仅旧兼容路径在回调时刻投递（TaskResult 自带 pr_url 的
        # 容器内建 MR 历史模式）；graph 主路径（coding/coding_commit）零投递——
        # 归档挂 create_pr_or_skip_node / _resume_after_containers（时序防线 Pitfall 1）。
        from knowledge import ingestion  # lazy import 防循环

        await ingestion.aschedule_ingestion(
            ingestion.IngestionRequest("task_result", session.session_id, "legacy_coding_completed")
        )

        await store_coding_complete_to_message(coding_session)
        logger.info(
            "coding_session_completed", coding_session_id=str(coding_session.id), pr_url=pr_url
        )


async def _update_coding_session_on_fail(session: SubAgentSession, error: str) -> None:
    """容器失败回调 -- resume graph 标记 CodingSession failed。

    graph 管理的 session (coding/coding_commit): 通过 Command(resume=) 恢复 graph 处理失败。
    graph resume 本身失败时降级为直接更新 DB。
    兼容旧流程: 非 graph 管理的 session 直接 amark_failed。
    """
    from chat.coding_events import store_coding_failed_to_message
    from chat.models import CodingSession

    coding_session = await CodingSession.objects.filter(
        subagent_session=session,
    ).afirst()
    if coding_session is None:
        return

    last_output = session.last_output if isinstance(session.last_output, dict) else {}
    effective_task_type = str(last_output.get("task_type") or session.task_type)

    if effective_task_type in ("coding", "coding_commit"):
        # graph 管理的 session: resume graph 处理失败
        from langgraph.types import Command

        from orchestration.checkpointer import get_checkpointer
        from orchestration.coding_graph import build_coding_graph

        checkpointer = await get_checkpointer()
        graph = build_coding_graph().compile(checkpointer=checkpointer)
        config = {"configurable": {"thread_id": f"coding-{coding_session.id}"}}

        try:
            await graph.ainvoke(
                Command(resume={"success": False, "error": error}),
                config=config,
            )
        except Exception:
            # graph resume 失败时直接更新 DB
            logger.exception("coding_graph_resume_fail", coding_session_id=str(coding_session.id))
            await coding_session.amark_failed(error=error)
    else:
        await coding_session.amark_failed(error=error)

    await store_coding_failed_to_message(coding_session)
    logger.info(
        "coding_session_failed",
        coding_session_id=str(coding_session.id),
        error=error,
    )


# === 回调处理函数 ===


async def _handle_completed(
    session: SubAgentSession, payload: dict[str, Any], log: BoundLogger
) -> Response:
    """处理 completed 回调 — 创建 TaskResult，更新 session 状态。"""
    ser = CompletedPayloadSerializer(data=payload)
    if not ser.is_valid():
        return Response(
            {"detail": "Invalid completed payload", "errors": ser.errors},
            status=status.HTTP_400_BAD_REQUEST,
        )

    p = ser.validated_data

    # 幂等：如果 TaskResult 已存在，直接返回成功
    if await TaskResult.objects.filter(session=session).aexists():
        log.info("callback_completed_idempotent")
        return Response({"status": "ok", "detail": "Already recorded"})

    output = p["output"] or {}
    branch_name = p.get("branch_name") or str(output.get("branch_name", "") or "")
    commit_sha = p.get("commit_sha") or str(output.get("commit_sha", "") or "")
    modified_files = p.get("modified_files") or output.get("modified_files", [])
    if not isinstance(modified_files, list):
        modified_files = []

    # 创建 TaskResult
    await TaskResult.objects.acreate(
        session=session,
        result_type=p["result_type"],
        text_output=output.get("text", "") if p["result_type"] == "text" else "",
        branch_name=branch_name,
        commit_sha=commit_sha,
        modified_files=modified_files,
        raw_output=output,
        duration_ms=p.get("duration_ms"),
    )

    # 更新 session 状态
    await session.amark_completed()

    # Phase 103 AGENT-01：终态吊销任务级短 TTL token（best-effort，service 内吞异常，
    # 幂等，绝不阻塞回调主流程）。注：SubAgentSession.amark_timeout/amark_cancelled
    # 对 coding 任务无调用方（规划期核实；amark_cancelled 仅 REPO_SUMMARY 取消路径
    # 调用，该类型不 mint token），残余假想终态路径由 expires_at 自过期兜底。
    from access_tokens.services import arevoke_task_tokens

    await arevoke_task_tokens(session.session_id)

    # 更新关联的 CodingSession（如果有）+ 落库 SDK 会话恢复数据
    await _update_coding_session_on_complete(
        session,
        sdk_session_id=str(p.get("sdk_session_id", "") or ""),
        sdk_transcript=str(p.get("sdk_transcript", "") or ""),
    )

    # repo_summary 完成写回 Repository
    if session.task_type == SubAgentSession.TaskType.REPO_SUMMARY:
        await _update_repository_on_summary_complete(session, p)

    # chat 的 deep_analysis 完成时自动回算 cross_repo_relevance。
    # 仅当 EXPLORE + source=chat_deep_analysis 触发（其它 EXPLORE 用途不回算）。
    if (
        session.task_type == SubAgentSession.TaskType.EXPLORE
        and isinstance(session.last_output, dict)
        and session.last_output.get("source") == "chat_deep_analysis"
    ):
        await _update_agent_session_cross_repo_relevance(session, p)

    # plan_research 容器完成 → 落 PartialPlan + §15 事件 + barrier（Phase 39-04）。
    # 独立 try/except swallow，绝不让回调失败（mirror cross_repo_relevance 钩子范式）。
    try:
        await _handle_research_completion(session, p, log)
    except Exception as exc:  # noqa: BLE001 — 永不阻塞 _handle_completed 主流程
        logger.warning(
            "research_completion_callback_failed",
            session_id=session.session_id,
            error=str(exc),
        )

    # repo_verify 容器完成 → 解析 verdict 落 RepoVerifyTask（经 service，INV-6，88-03）。
    # 独立 try/except swallow，绝不让回调失败（Pitfall 4 不回 5xx）。
    try:
        await _handle_repo_verify_completion(session, p, log)
    except Exception as exc:  # noqa: BLE001 — 永不阻塞 _handle_completed 主流程
        logger.warning(
            "repo_verify_completion_callback_failed",
            session_id=session.session_id,
            error=str(exc),
        )

    # blueprint_research 容器完成 → fitness 落 PartialPlan.content（经 service，INV-6，112-04）。
    # 独立 try/except swallow，绝不让回调失败（与上面两条链完全对称）。
    if _is_blueprint_research(session):
        try:
            await _handle_blueprint_research_completion(session, p, log)
        except Exception as exc:  # noqa: BLE001 — 永不阻塞 _handle_completed 主流程
            logger.warning(
                "blueprint_research_completion_callback_failed",
                session_id=session.session_id,
                error=str(exc),
            )

    # CR-01：续驱调度必须在 _handle_research_completion 之后——它把 RepoResearchTask 翻终态
    # 并将 chat 入口 session researching→merging。若在其之前调度（旧实现），fire-and-forget
    # 的 _resume() 会与 research 完成处理在事件循环 await 点交错，可能在 task 翻终态前读到
    # 非终态而 aall_research_tasks_terminal 短路返回 no-op，导致 chat 会话永久卡在 merging、
    # barrier 永不被通知。research 状态落库后再调度，保证 _resume() 创建时 DB 状态已一致。
    # 触发 workflow 恢复（如果有 node_execution）
    _schedule_workflow_resume(session, log)
    # 触发 Agent 会话恢复（如果有 main_session 但无 node_execution）
    _schedule_agent_session_resume(session, log)

    log.info("callback_completed_ok", result_type=p["result_type"])
    return Response({"status": "ok"})


async def _handle_failed(
    session: SubAgentSession, payload: dict[str, Any], log: BoundLogger
) -> Response:
    """处理 failed 回调 — 标记失败，通知，恢复 workflow/agent。

    Phase: Runner 端独立处理重试，Server 端不再重试。
    """
    ser = FailedPayloadSerializer(data=payload)
    if not ser.is_valid():
        return Response(
            {"detail": "Invalid failed payload", "errors": ser.errors},
            status=status.HTTP_400_BAD_REQUEST,
        )

    p = ser.validated_data
    error_msg = p.get("error", "Unknown error")

    # 直接标记失败（Runner 端独立处理重试）
    session.failure_reason = error_msg
    await session.asave(update_fields=["failure_reason"])
    await session.amark_failed(error=error_msg)

    # Phase 103 AGENT-01：终态吊销任务级短 TTL token（best-effort、幂等，见
    # _handle_completed 处注释；timeout/cancelled 假想路径由 TTL 自过期兜底）。
    from access_tokens.services import arevoke_task_tokens

    await arevoke_task_tokens(session.session_id)

    # 更新关联的 CodingSession（如果有）
    await _update_coding_session_on_fail(session, error_msg)

    await _send_failure_notification(session, error_msg)

    # repo_summary 失败写回 Repository
    if session.task_type == SubAgentSession.TaskType.REPO_SUMMARY:
        await _update_repository_on_summary_fail(session, error_msg)

    # plan_research 容器失败 → mark_failed + repo.research.failed + barrier（Phase 39-04）。
    # 独立 try/except swallow，绝不让回调失败（failed 也是 barrier 终态，不卡死 merging）。
    try:
        await _handle_research_failure(session, p, log)
    except Exception as exc:  # noqa: BLE001 — 永不阻塞 _handle_failed 主流程
        logger.warning(
            "research_failure_callback_failed",
            session_id=session.session_id,
            error=str(exc),
        )

    # repo_verify 容器失败 → mark_verify_failed（经 service，88-03）。独立 try/except swallow。
    try:
        await _handle_repo_verify_failure(session, p, log)
    except Exception as exc:  # noqa: BLE001 — 永不阻塞 _handle_failed 主流程
        logger.warning(
            "repo_verify_failure_callback_failed",
            session_id=session.session_id,
            error=str(exc),
        )

    # blueprint_research 容器失败 → mark_failed + blueprint.repo_research.failed + barrier（112-04）。
    # 独立 try/except swallow（失败也是 barrier 终态，不能卡住蓝图续驱）。
    if _is_blueprint_research(session):
        try:
            await _handle_blueprint_research_failure(session, p, log)
        except Exception as exc:  # noqa: BLE001 — 永不阻塞 _handle_failed 主流程
            logger.warning(
                "blueprint_research_failure_callback_failed",
                session_id=session.session_id,
                error=str(exc),
            )

    # CR-01：与 _handle_completed 对称——续驱调度移到 _handle_research_failure 之后，确保
    # _resume() 创建时 RepoResearchTask 已翻 FAILED 终态 + session 已 researching→merging，
    # 消除 fire-and-forget 续驱在 task 翻终态前短路 no-op 导致会话卡死的竞态。
    # （_schedule_workflow_resume 自身有「所有 SubAgentSession 终态才续跑」二次 guard，
    #   工作流路径不受顺序影响。）
    # 触发 workflow 恢复（如果有 node_execution）
    _schedule_workflow_resume(session, log)
    # 触发 Agent 会话恢复
    _schedule_agent_session_resume(session, log)

    log.info("callback_failed_ok", error=error_msg)
    return Response({"status": "ok"})


async def _handle_heartbeat(
    session: SubAgentSession, payload: dict[str, Any], log: BoundLogger
) -> Response:
    """处理 heartbeat 回调 — 更新 last_heartbeat_at。"""
    ser = HeartbeatPayloadSerializer(data=payload)
    if not ser.is_valid():
        return Response(
            {"detail": "Invalid heartbeat payload", "errors": ser.errors},
            status=status.HTTP_400_BAD_REQUEST,
        )

    session.last_heartbeat_at = timezone.now()
    await session.asave(update_fields=["last_heartbeat_at", "updated_at"])

    log.debug("callback_heartbeat_ok")
    return Response({"status": "ok"})


async def _handle_question(
    session: SubAgentSession, payload: dict[str, Any], log: BoundLogger
) -> Response:
    """处理 question 回调 — 创建 InteractionLog 并触发 Feishu 提问卡片。"""
    import uuid

    from subagent.models import InteractionLog
    from subagent.question_handler import send_question_card_enhanced

    ser = QuestionPayloadSerializer(data=payload)
    if not ser.is_valid():
        return Response(
            {"detail": "Invalid question payload", "errors": ser.errors},
            status=status.HTTP_400_BAD_REQUEST,
        )

    p = ser.validated_data

    # 生成问题 ID
    question_id = f"q-{uuid.uuid4().hex[:12]}"

    # 创建 InteractionLog 记录
    interaction_log = await InteractionLog.objects.acreate(
        session=session,
        question_id=question_id,
        question_text=p["question"],
        question_context=p.get("context", ""),
        code_snippet=p.get("code_snippet", ""),
        options=p.get("options", []),
    )

    # 存储问题到 last_output（保持兼容）
    session.last_output = {
        **(session.last_output or {}),
        "pending_question": {
            "question_id": question_id,
            "question": p["question"],
            "options": p.get("options", []),
            "asked_at": timezone.now().isoformat(),
        },
    }
    await session.asave(update_fields=["last_output", "updated_at"])

    # 触发增强版 Feishu 提问卡片（异步）
    async def _send_card():
        message_id = await send_question_card_enhanced(
            session=session,
            question=p["question"],
            options=p.get("options", []),
            context=p.get("context", ""),
            code_snippet=p.get("code_snippet", ""),
            question_id=question_id,
        )
        # 更新 message_id 到 InteractionLog
        if message_id:
            interaction_log.feishu_message_id = message_id
            await interaction_log.asave(update_fields=["feishu_message_id"])

    try:
        loop = asyncio.get_running_loop()
        loop.create_task(_send_card())
    except RuntimeError:
        # 没有运行中的事件循环
        asyncio.run(_send_card())

    # PLAN-03：容器编码遇阻发卡 → 注册 5min 无回复挂起计时（仅 coding 容器，
    # best-effort try/except 绝不反噬回调）。到点无回复 → 停容器 + CodingSession
    # SUSPENDED；用户回复经 container_callback resume 续跑。
    async def _arm_suspend_timeout() -> None:
        try:
            from chat.container_suspend_service import ContainerSuspendService
            from chat.models import CodingSession

            coding_session = await CodingSession.objects.filter(
                subagent_session=session
            ).afirst()
            if coding_session is None:
                return  # 非 coding 容器问答（如 workflow chat 提问）→ 不挂起
            initiated_by = await _resolve_initiated_user(session)
            await ContainerSuspendService().arm_timeout(
                coding_session_id=str(coding_session.id),
                task_id=session.session_id,
                initiated_by_user_id=initiated_by,
            )
        except Exception as exc:  # noqa: BLE001 — 计时注册 best-effort，绝不反噬回调
            log.warning(
                "container_suspend_arm_from_question_failed",
                session_id=session.session_id,
                error_type=type(exc).__name__,
            )

    try:
        loop = asyncio.get_running_loop()
        loop.create_task(_arm_suspend_timeout())
    except RuntimeError:
        asyncio.run(_arm_suspend_timeout())

    log.info(
        "callback_question_ok",
        question_id=question_id,
        interaction_log_id=interaction_log.id,
        question_preview=p["question"][:80],
    )
    return Response({"status": "ok", "question_id": question_id})


async def _handle_progress(
    session: SubAgentSession, payload: dict[str, Any], log: BoundLogger
) -> Response:
    """处理 progress 回调 — 更新 last_output（临时进度数据）。

    implementation G1 + G4 + G5 修复（v18.1 audit gap closure）:
      - G4: 调用公共 ``parse_progress_payload`` 与 WebSocket 路径
        (runners/consumers.py:RunnerConsumer._handle_progress) 共享同一解析逻辑，
        避免两条路径分叉。
      - G1 (BLOCKER): ``details.suggested_commit_message`` scalar 透传到 output 顶层，
        使下游 ``GET /api/chat/coding-sessions/{id}/commit-confirm/`` 返回真实 AI 建议。
      - G5: 使用 dict spread merge 语义写入 ``session.last_output``，保留既有
        task_type/source/conversation_id/logs 等 meta 而非整体覆盖。
    """
    ser = ProgressPayloadSerializer(data=payload)
    if not ser.is_valid():
        return Response(
            {"detail": "Invalid progress payload", "errors": ser.errors},
            status=status.HTTP_400_BAD_REQUEST,
        )

    p = ser.validated_data
    output = parse_progress_payload(p)
    # G5 merge 语义：严格使用 (session.last_output or {}) fallback 防御 None
    session.last_output = {**(session.last_output or {}), **output}
    await session.asave(update_fields=["last_output", "updated_at"])

    log.debug("callback_progress_ok", phase=p.get("phase", ""))
    return Response({"status": "ok"})


async def _handle_action_log(
    session: SubAgentSession, payload: dict[str, Any], log: BoundLogger
) -> Response:
    """处理 action_log 回调 — 写入 ActionLog 记录。"""
    ser = ActionLogPayloadSerializer(data=payload)
    if not ser.is_valid():
        return Response(
            {"detail": "Invalid action_log payload", "errors": ser.errors},
            status=status.HTTP_400_BAD_REQUEST,
        )

    p = ser.validated_data
    await ActionLog.objects.acreate(
        session=session,
        action_type=p["action_type"],
        timestamp=p["timestamp"],
        sequence=p["sequence"],
        payload={
            "tool_name": p["tool_name"],
            "input": p["input"],
            "output": p["output"],
            "thinking": p["thinking"],
            "model": p["model"],
        },
        duration_ms=p["duration_ms"],
    )

    log.debug("callback_action_log_ok", action_type=p["action_type"], sequence=p["sequence"])
    return Response({"status": "ok"})


def _derive_container_call_source(session: SubAgentSession) -> str:
    """服务端权威派生四类容器 LLM 调用来源（T-72-03-TAMPER）。

    依据 dispatch 时服务端写入、runner 不可篡改的 ``SubAgentSession.task_type`` +
    ``last_output.source`` 映射四类容器 ``CallSource``；无法判定回退 ``sdk_agent_task``。
    返回值经 ``CallSource.normalize`` 受控，杜绝非法维度。**绝不**采信 runner 经 payload
    上报的 call_source（对齐 cross_repo_relevance 权威字段范式）。
    """
    last_output = session.last_output if isinstance(session.last_output, dict) else {}
    source = last_output.get("source")
    effective_task_type = str(last_output.get("task_type") or "")

    if session.task_type == SubAgentSession.TaskType.REPO_SUMMARY:
        derived = CallSource.REPO_SUMMARY_CONTAINER
    elif session.task_type == SubAgentSession.TaskType.REPO_VERIFY:
        # 逐仓 explore 容器深验 LLM（88-03）；服务端权威派生，不信 runner 上报 call_source
        derived = CallSource.REPO_VERIFY_CONTAINER
    elif session.task_type == SubAgentSession.TaskType.EXPLORE and source == "chat_deep_analysis":
        derived = CallSource.DEEP_ANALYSIS_CONTAINER
    elif session.task_type == SubAgentSession.TaskType.PLAN and source == _BLUEPRINT_RESEARCH_SOURCE:
        # 蓝图逐仓调研容器（112-04）：不补这条会回退 sdk_agent_task，违反显式 call_source 要求
        derived = CallSource.BLUEPRINT_REPO_RESEARCH
    elif (
        session.task_type == SubAgentSession.TaskType.CODING
        or effective_task_type in ("coding", "coding_commit")
    ):
        derived = CallSource.WORKFLOW_CODING_CONTAINER
    else:
        derived = CallSource.SDK_AGENT_TASK
    return CallSource.normalize(derived)


async def _resolve_initiated_user(session: SubAgentSession) -> str:
    """从服务端权威来源派生发起用户（T-72-03-TAMPER）。

    优先 ``main_session.user``（``AgentSession.user`` FK，dispatch 时服务端写入）；
    其次 workflow 触发者（``node_execution → workflow_execution.triggered_by``）；均无则
    ``system``。**绝不**取 runner 可经 progress 篡改的 ``last_output`` 任意键作归因用户。
    async 安全：仅取标量 id，不在 async 上下文直接访问 FK。
    """
    try:
        if session.main_session_id:
            from agents.models import AgentSession

            main = await AgentSession.objects.filter(id=session.main_session_id).afirst()
            if main is not None and main.user_id:
                return str(main.user_id)
        if session.node_execution_id:
            from workflows.models.execution import NodeExecution

            ne = (
                await NodeExecution.objects.select_related("workflow_execution")
                .filter(id=session.node_execution_id)
                .afirst()
            )
            if (
                ne is not None
                and ne.workflow_execution is not None
                and ne.workflow_execution.triggered_by_id
            ):
                return str(ne.workflow_execution.triggered_by_id)
    except Exception:  # noqa: BLE001 — 用户派生失败回退 system，绝不反噬回调
        return "system"
    return "system"


async def _handle_token_usage(
    session: SubAgentSession, payload: dict[str, Any], log: BoundLogger
) -> Response:
    """处理 token_usage 回调 — 写入 TokenUsage 记录，并桥接落一行 ModelUsageRecord。

    ``TokenUsage``（成本归因既有消费方）保持原样不动；在其之外**追加**一行
    ``ModelUsageRecord`` 把容器 LLM token 纳入统一 TPS 源（72-03，指标/留痕分离、不复制
    语义）。``call_source`` 与发起用户由 ``SubAgentSession`` 服务端权威派生（不信任 runner
    可篡改 payload）。桥接 best-effort 独立 try/except，失败仅 warning、回调仍返回 200。
    """
    ser = TokenUsagePayloadSerializer(data=payload)
    if not ser.is_valid():
        return Response(
            {"detail": "Invalid token_usage payload", "errors": ser.errors},
            status=status.HTTP_400_BAD_REQUEST,
        )

    p = ser.validated_data
    await TokenUsage.objects.acreate(
        session=session,
        input_tokens=p["input_tokens"],
        output_tokens=p["output_tokens"],
        cache_read_tokens=p["cache_read_tokens"],
        cache_write_tokens=p["cache_write_tokens"],
        model=p["model"],
        total_cost_usd=p["total_cost_usd"],
        source=TokenUsage.Source.SUBAGENT,
    )

    # 桥接：补一行 ModelUsageRecord 纳入 TPS（72-03，RATE-02 核心）。best-effort 独立
    # try/except swallow，绝不影响回调 200（T-72-03-03）；call_source/user 服务端权威派生
    # （T-72-03-TAMPER）；只承载 token 计数 + provider/model/status 元数据，无 prompt 文本。
    try:
        last_output = session.last_output if isinstance(session.last_output, dict) else {}
        call_source = _derive_container_call_source(session)
        provider = p.get("provider") or str(last_output.get("provider") or "")
        user_id = await _resolve_initiated_user(session)
        input_tokens = p["input_tokens"]
        output_tokens = p["output_tokens"]
        await arecord_llm_usage(
            run=None,
            call_source=call_source,
            provider=provider,
            model=p["model"],
            prompt_tokens=input_tokens,
            completion_tokens=output_tokens,
            total_tokens=input_tokens + output_tokens,
            cache_read_tokens=p["cache_read_tokens"],
            cache_write_tokens=p["cache_write_tokens"],
            cost_estimate=p["total_cost_usd"],
            ttft_ms=p.get("ttft_ms"),
            upstream_status_code=p.get("upstream_status_code"),
            failure_type=p.get("failure_type", ""),
            user_id=user_id,
            source="container_callback",
        )
    except Exception as exc:  # noqa: BLE001 — 桥接绝不反噬回调主流程
        logger.warning(
            "container_token_bridge_failed",
            session_id=session.session_id,
            error=str(exc),
        )

    log.debug("callback_token_usage_ok", model=p["model"])
    return Response({"status": "ok"})


# === repo_summary 回调辅助函数 (implementation) ===


def _parse_summary_json(raw_text: str) -> str:
    """尝试从 Claude 输出中提取 JSON summary；失败返回原始文本。"""
    import json as json_mod
    import re as re_mod

    if not raw_text:
        return raw_text

    # 1. 先尝试 ```json ... ``` 代码块提取
    m = re_mod.search(r"```json\s*(\{.*?\})\s*```", raw_text, re_mod.DOTALL)
    if m:
        try:
            obj = json_mod.loads(m.group(1))
            return json_mod.dumps(obj, ensure_ascii=False, indent=2)
        except json_mod.JSONDecodeError:
            pass
    # 2. 直接尝试 json.loads
    try:
        obj = json_mod.loads(raw_text.strip())
        return json_mod.dumps(obj, ensure_ascii=False, indent=2)
    except json_mod.JSONDecodeError:
        pass
    # 3. 首个 { 到末个 } 跨度提取（容忍模型前言 / 未闭合 ```json 围栏）
    start, end = raw_text.find("{"), raw_text.rfind("}")
    if start != -1 and end > start:
        try:
            obj = json_mod.loads(raw_text[start : end + 1])
            return json_mod.dumps(obj, ensure_ascii=False, indent=2)
        except json_mod.JSONDecodeError:
            pass
    # 4. 降级：返回原始文本（markdown 存储）
    return raw_text


async def _update_repository_on_summary_complete(
    session: SubAgentSession, p: dict[str, Any]
) -> None:
    """repo_summary 完成 -- 解析结果写回 Repository。

    PageIndex 化扩展：结果含 tree 时走业务校验（结构/paths 真实性/monorepo
    对齐），校验通过写 ai_summary_tree + is_monorepo + 语义 facets 并触发
    节点向量化；校验失败保留旧树（fail-closed），仅更新文本 ai_summary。
    """
    import json as json_mod

    from repositories.models import Repository

    repo_id = (session.last_output or {}).get("repository_id")
    if not repo_id:
        logger.warning("repo_summary_complete_no_repo_id", session_id=session.session_id)
        return
    repo = await Repository.objects.filter(id=repo_id).afirst()
    if not repo:
        logger.warning("repo_summary_complete_repo_not_found", repo_id=repo_id)
        return

    raw_text = p["output"].get("text", "") if p["result_type"] == "text" else ""
    parsed_summary = _parse_summary_json(raw_text)

    try:
        payload_obj = json_mod.loads(parsed_summary)
    except (json_mod.JSONDecodeError, TypeError):
        payload_obj = None

    # ai_summary 存「剥离 tree 的 JSON」：tree 体积大（可达数万字符）且已
    # 单独存 ai_summary_tree；带 tree 直接截断 8192 会把 JSON 腰斩，导致
    # overview_text 解析失败、对外描述变成乱码 JSON 片段。
    if isinstance(payload_obj, dict):
        summary_obj = {k: v for k, v in payload_obj.items() if k != "tree"}
        repo.ai_summary = json_mod.dumps(summary_obj, ensure_ascii=False, indent=2)[:8192]
    else:
        repo.ai_summary = parsed_summary[:8192]
    repo.ai_summary_status = "completed"
    repo.ai_summary_generated_at = timezone.now()
    repo.ai_summary_error = ""
    update_fields = [
        "ai_summary",
        "ai_summary_status",
        "ai_summary_generated_at",
        "ai_summary_error",
        "updated_at",
    ]

    # 结构化能力树解析 + 校验（fail-closed：失败保留旧树）
    tree_written = False

    if isinstance(payload_obj, dict) and payload_obj.get("tree"):
        from repositories.tree_schema import (
            TreeValidationError,
            validate_and_assemble_tree,
        )

        try:
            nested_tree = await validate_and_assemble_tree(str(repo_id), payload_obj)
        except TreeValidationError as exc:
            logger.warning(
                "repo_summary_tree_validation_failed",
                repository_id=repo_id,
                error=str(exc),
            )
        else:
            repo.ai_summary_tree = nested_tree
            repo.is_monorepo = bool(payload_obj.get("is_monorepo", False))
            # 树重建成功 → 清空增量 stale 状态
            repo.tree_stale_state = {}
            update_fields += ["ai_summary_tree", "is_monorepo", "tree_stale_state"]
            tree_written = True

            facets = payload_obj.get("facets")
            if isinstance(facets, dict) and facets:
                merged = dict(repo.facets or {})
                merged.update({str(k): str(v) for k, v in facets.items()})
                repo.facets = merged
                update_fields.append("facets")

    await repo.asave(update_fields=update_fields)
    logger.info(
        "repo_summary_written",
        repository_id=repo_id,
        summary_length=len(parsed_summary),
        tree_written=tree_written,
    )

    # 树写入成功后异步重建节点向量索引 + 全局树增量归类（不阻塞 callback 响应）
    if tree_written:
        from codegraph.services.corpus_tree import CorpusTreeService
        from codegraph.services.repo_index_tree import RepoIndexTreeBuilder
        from repositories.facet_service import FacetService
        from services.background_runner import run_in_background

        repo_id_str = str(repo_id)

        async def _post_tree_tasks() -> None:
            # 事实分面（团队归属/技术栈/活跃度）刷新依赖 ai_summary_tree 已存在，
            # 而索引完成时 summary 任务往往尚未回写树（异步），导致索引侧的
            # _refresh_tree_facts 被跳过——这里在树落库后补刷一次，保证浏览树
            # 兜底分组（团队归属）与节点向量 payload 拿到最新事实分面。
            try:
                await FacetService.refresh_fact_facets(repo_id_str)
            except Exception:  # noqa: BLE001 — 分面刷新失败不阻塞节点索引
                logger.warning(
                    "fact_facets_refresh_failed",
                    repository_id=repo_id_str,
                    exc_info=True,
                )
            await RepoIndexTreeBuilder.build(repo_id_str)
            try:
                await CorpusTreeService.assign_repository(repo_id_str)
            except Exception:  # noqa: BLE001 — 归类失败不影响节点索引
                logger.warning(
                    "corpus_tree_assign_failed",
                    repository_id=repo_id_str,
                    exc_info=True,
                )

        run_in_background(
            _post_tree_tasks,
            name=f"repo_index_tree_{repo_id_str}",
        )


async def _update_repository_on_summary_fail(session: SubAgentSession, error_msg: str) -> None:
    """repo_summary 失败 -- 写回错误状态。"""
    from repositories.models import Repository

    repo_id = (session.last_output or {}).get("repository_id")
    if not repo_id:
        return
    repo = await Repository.objects.filter(id=repo_id).afirst()
    if not repo:
        return

    repo.ai_summary_status = "failed"
    repo.ai_summary_error = error_msg[:2000]
    await repo.asave(update_fields=["ai_summary_status", "ai_summary_error", "updated_at"])
    logger.info("repo_summary_fail_written", repository_id=repo_id, error=error_msg[:100])


# === deep_analysis 完成回算 cross_repo_relevance ===


async def _update_agent_session_cross_repo_relevance(
    session: SubAgentSession,
    payload: dict[str, Any],
) -> None:
    """deep_analysis 完成时复用 work item helper 反算跨仓相关性。

    步骤：
    1. ``conversation_id`` 从**服务端权威来源** ``main_session.metadata`` 取，
       ``space_id`` 从该 conversation 的 project 派生（见安全说明）；
       ``task_description``（query）非安全关键字段，仍取自 ``session.last_output``。
    2. 调 ``_analyze_relevance_core(triggered_by=DEEP_ANALYSIS_COMPLETION,
       agent_session_id=session.main_session.id)`` —— 复用 chat_tool 路径
       同一段聚合逻辑，trace 自动落库。
    3. 把 candidates 写入 ``AgentSession.metadata['cross_repo_relevance']`` +
       ``cross_repo_relevance_trace_id`` 让 LLM 下一轮 resume 时能读到。
    4. 把候选 JSON 拼成 ``[cross_repo_relevance:<trace_id>]\n<JSON>`` 段追加
       到本 session 的 ``TaskResult.text_output`` 末尾 —— BarrierManager
       通过 TaskResult 回灌 chat 流时前端可解析为 RoutingDecisionPanel。
    5. 任何异常仅 ``logger.warning`` 不阻塞 ``_handle_completed`` 主流程。

    安全（284 SECURITY contract-E1）：``conversation_id`` / ``space_id`` **绝不**信任
    ``session.last_output`` —— 该字典可被 runner 经 progress 回调（透传任意
    ``details`` scalar 键）篡改，否则半可信 runner 可把路由 trace 越权写入他人
    会话。改为从 dispatch 时服务端写入、runner 不可改的 ``main_session.metadata``
    取 ``conversation_id``，再由该 conversation 的 ``project_id`` 派生 ``space_id``。

    Args:
        session: deep_analysis 子任务的 SubAgentSession。
        payload: completed 回调的 validated payload（暂未使用，留作未来 Runner
            主动附带 ``cross_repo_relevance`` 字段时的扩展点）。
    """
    try:
        output = session.last_output or {}
        # task_description 非安全关键（仅作为检索 query 文本），可取自 last_output。
        task_description = output.get("task_description") or ""
        # 用 main_session_id（标量，无需查询）+ 异步取 AgentSession —— 兼容
        # WS 完成路径（session 未 select_related('main_session')，直接访问 FK
        # 在 async 上下文会抛 SynchronousOnlyOperation）。
        main_session_id = session.main_session_id
        main_session = None
        if main_session_id:
            from agents.models import AgentSession

            main_session = await AgentSession.objects.filter(id=main_session_id).afirst()

        # contract-E1：conversation_id 取自服务端权威来源 main_session.metadata（dispatch
        # 时写入，runner 不可改），而非 runner 可篡改的 session.last_output。
        authoritative_conv_id = None
        if main_session and isinstance(main_session.metadata, dict):
            authoritative_conv_id = main_session.metadata.get("conversation_id")

        if not (authoritative_conv_id and task_description and main_session):
            logger.warning(
                "cross_repo_relevance_skip_missing_context",
                session_id=session.session_id,
                has_conv=bool(authoritative_conv_id),
                has_query=bool(task_description),
                has_main_session=bool(main_session),
            )
            return

        # space_id 由 conversation 的 project 派生（权威），不取 last_output。
        from chat.models import Conversation

        conv = await Conversation.objects.filter(id=authoritative_conv_id).afirst()
        if conv is None or conv.space_id is None:
            logger.warning(
                "cross_repo_relevance_skip_conv_not_found",
                session_id=session.session_id,
                conversation_id=str(authoritative_conv_id),
            )
            return
        conversation_id = str(conv.id)
        space_id = str(conv.space_id)

        # lazy import 防止 agents.tools 与 subagent.api 启动顺序循环
        from agents.tools.repository_relevance import _analyze_relevance_core
        from chat.models import RepositoryRoutingTrace

        candidates, trace_id = await _analyze_relevance_core(
            query=task_description,
            space_id=space_id,
            conversation_id=conversation_id,
            triggered_by=RepositoryRoutingTrace.TriggeredBy.DEEP_ANALYSIS_COMPLETION,
            agent_session_id=str(main_session.id),
        )

        candidates_dump = [c.model_dump() for c in candidates]

        # (1) AgentSession.metadata 写入
        metadata = dict(main_session.metadata or {})
        metadata["cross_repo_relevance"] = candidates_dump
        metadata["cross_repo_relevance_trace_id"] = trace_id
        main_session.metadata = metadata
        await main_session.asave(update_fields=["metadata", "updated_at"])

        # (2) TaskResult.text_output 末尾拼接 → BarrierManager 回灌
        import json as _json

        relevance_block = f"\n\n[cross_repo_relevance:{trace_id}]\n" + _json.dumps(
            candidates_dump, ensure_ascii=False
        )
        task_result = await TaskResult.objects.filter(session=session).afirst()
        if task_result is not None:
            task_result.text_output = (task_result.text_output or "") + relevance_block
            await task_result.asave(update_fields=["text_output"])

        logger.info(
            "cross_repo_relevance_written",
            session_id=session.session_id,
            agent_session_id=str(main_session.id),
            candidate_count=len(candidates_dump),
            trace_id=trace_id,
        )
    except Exception as exc:  # noqa: BLE001 — 永不阻塞 _handle_completed 主流程
        logger.warning(
            "cross_repo_relevance_failed",
            session_id=session.session_id,
            error=str(exc),
        )


# === plan_research 容器回调 → PartialPlan 落库 + §15 事件 + barrier 触发 (Phase 39-04) ===


def _is_plan_research(session: SubAgentSession) -> bool:
    """路由判定：PLAN 任务 + last_output.source == plan_research。"""
    return (
        session.task_type == SubAgentSession.TaskType.PLAN
        and isinstance(session.last_output, dict)
        and session.last_output.get("source") == "plan_research"
    )


async def _aload_research_task(session: SubAgentSession):
    """从 last_output 取 research_task_id → 读 RepoResearchTask（缺失/已终态返回 None）。

    返回 ``(task, plan_session)``；任一不可用则对应位 None（调用方 no-op，幂等）。
    """
    from delivery.models import ConvergenceSession, RepoResearchTask, RepoResearchTaskStatus

    lo = session.last_output or {}
    research_task_id = lo.get("research_task_id")
    plan_session_id = lo.get("plan_session_id")
    if not research_task_id:
        return None, None
    task = await RepoResearchTask.objects.filter(id=research_task_id).afirst()
    if task is None or task.status in (
        RepoResearchTaskStatus.DONE,
        RepoResearchTaskStatus.FAILED,
        RepoResearchTaskStatus.STALE,
    ):
        return None, None
    plan_session = None
    if plan_session_id:
        plan_session = await ConvergenceSession.objects.filter(id=plan_session_id).afirst()
    return task, plan_session


async def _trigger_research_barrier(plan_session) -> None:
    """所有 RepoResearchTask 终态则推 research_complete（→ merging）；幂等安全。"""
    if plan_session is None:
        return
    from services.process_runtime.research_aggregation import amaybe_complete_research

    await amaybe_complete_research(plan_session)


async def _handle_research_completion(
    session: SubAgentSession, p: dict[str, Any], log: BoundLogger
) -> None:
    """plan_research 容器完成 → 解析结构化/降级 PartialPlan 落库 + §15 事件 + barrier。

    空/不可解析 → mark_failed + repo.research.failed；否则 record_partial + repo.research.completed。
    所有终态 → amaybe_complete_research（researching→merging）。非 plan_research 不触发。
    """
    if not _is_plan_research(session):
        return

    from delivery.services import ConvergenceSessionService, ResearchService
    from delivery.services.event_taxonomy import (
        EVENT_REPO_RESEARCH_COMPLETED,
        EVENT_REPO_RESEARCH_FAILED,
    )
    from services.process_runtime.research_aggregation import parse_partial_plan_content

    task, plan_session = await _aload_research_task(session)
    if task is None:
        return

    research_service = ResearchService()
    session_service = ConvergenceSessionService()
    content = parse_partial_plan_content(
        p.get("output") or {}, repository_id=str(task.repository_id)
    )

    if content is None:
        await research_service.mark_failed(task, {"reason": "empty_or_unparseable_result"})
        if plan_session is not None:
            await session_service._emit_event(
                EVENT_REPO_RESEARCH_FAILED,
                plan_session,
                {
                    "repo_id": str(task.repository_id),
                    "task_id": str(task.id),
                    "error": "empty_or_unparseable_result",
                },
            )
    else:
        await research_service.record_partial(task, content)
        if plan_session is not None:
            await session_service._emit_event(
                EVENT_REPO_RESEARCH_COMPLETED,
                plan_session,
                {
                    "repo_id": str(task.repository_id),
                    "task_id": str(task.id),
                    "summary": content.get("research_summary", ""),
                    "candidate_files": content.get("candidate_files", []),
                    "api_contracts_exposed": content.get("api_contracts_exposed", []),
                },
            )

    await _trigger_research_barrier(plan_session)
    log.info("research_completion_handled", task_id=str(task.id), failed=content is None)


async def _handle_research_failure(
    session: SubAgentSession, p: dict[str, Any], log: BoundLogger
) -> None:
    """plan_research 容器失败 → mark_failed + repo.research.failed + barrier（failed 也是终态）。"""
    if not _is_plan_research(session):
        return

    from delivery.services import ConvergenceSessionService, ResearchService
    from delivery.services.event_taxonomy import EVENT_REPO_RESEARCH_FAILED

    task, plan_session = await _aload_research_task(session)
    if task is None:
        return

    error_msg = p.get("error", "Unknown error")
    await ResearchService().mark_failed(task, {"reason": "container_failed", "error": error_msg})
    if plan_session is not None:
        await ConvergenceSessionService()._emit_event(
            EVENT_REPO_RESEARCH_FAILED,
            plan_session,
            {"repo_id": str(task.repository_id), "task_id": str(task.id), "error": error_msg},
        )
    await _trigger_research_barrier(plan_session)
    log.info("research_failure_handled", task_id=str(task.id))


# === repo_verify 容器回调 → verdict 落 RepoVerifyTask（经 service，INV-6，Phase 88-03） ===


def _is_repo_verify(session: SubAgentSession) -> bool:
    """路由判定：REPO_VERIFY 任务 + last_output.source == repo_verify。"""
    return (
        session.task_type == SubAgentSession.TaskType.REPO_VERIFY
        and isinstance(session.last_output, dict)
        and session.last_output.get("source") == "repo_verify"
    )


def parse_verify_verdict(output: Any) -> dict[str, Any] | None:
    """从容器 output 提取 JSON verdict（含 ``fit`` 键）；空/不可解析返回 None。

    优先结构化透传（output 已含 ``fit``）；否则从 ``output["text"]`` 经
    ``_parse_summary_json`` 风格的 JSON 围栏 / 花括号跨度提取后 ``json.loads``。
    """
    import json as json_mod

    if not isinstance(output, dict):
        return None
    if "fit" in output:
        return output
    text = str(output.get("text", "") or "")
    if not text:
        return None
    parsed = _parse_summary_json(text)
    try:
        obj = json_mod.loads(parsed)
    except (json_mod.JSONDecodeError, TypeError):
        return None
    if not isinstance(obj, dict) or "fit" not in obj:
        return None
    return obj


async def _aload_verify_task(session: SubAgentSession):
    """从 last_output 取 repo_verify_task_id → 读 RepoVerifyTask（缺失/已终态返回 None）。"""
    from initiatives.models import RepoVerifyTask, RepoVerifyTaskStatus

    lo = session.last_output or {}
    task_id = lo.get("repo_verify_task_id")
    if not task_id:
        return None
    task = await RepoVerifyTask.objects.filter(id=task_id).afirst()
    if task is None or task.status in (
        RepoVerifyTaskStatus.DONE,
        RepoVerifyTaskStatus.FAILED,
        RepoVerifyTaskStatus.STALE,
    ):
        return None
    return task


async def _handle_repo_verify_completion(
    session: SubAgentSession, p: dict[str, Any], log: BoundLogger
) -> None:
    """repo_verify 容器完成 → 解析 verdict 落 RepoVerifyTask（经 service，INV-6）。

    空/不可解析 → ``mark_verify_failed("empty_or_unparseable")``；否则 ``record_verdict``
    （verdict 文本经 service 内 redact 脱敏）。非 repo_verify session 不触发。
    """
    if not _is_repo_verify(session):
        return

    from initiatives.services.repo_association_service import RepoAssociationService

    task = await _aload_verify_task(session)
    if task is None:
        return

    svc = RepoAssociationService()
    verdict = parse_verify_verdict(p.get("output") or {})
    if verdict is None:
        await svc.mark_verify_failed(task, {"reason": "empty_or_unparseable"})
    else:
        await svc.record_verdict(task, verdict)
    log.info(
        "repo_verify_completion_handled",
        task_id=str(task.id),
        failed=verdict is None,
    )


async def _handle_repo_verify_failure(
    session: SubAgentSession, p: dict[str, Any], log: BoundLogger
) -> None:
    """repo_verify 容器失败 → mark_verify_failed（container_failed，经 service）。"""
    if not _is_repo_verify(session):
        return

    from initiatives.services.repo_association_service import RepoAssociationService

    task = await _aload_verify_task(session)
    if task is None:
        return

    error_msg = p.get("error", "Unknown error")
    await RepoAssociationService().mark_verify_failed(
        task,
        {"reason": "container_failed", "error": redact_secrets_in_text(str(error_msg))},
    )
    log.info("repo_verify_failure_handled", task_id=str(task.id))


# === blueprint_research 容器回调 → fitness 落 PartialPlan.content（Phase 112-04，FLOW-02） ===
#
# PLAN 任务类型的**第三种**用途（前两种：plan_research 落 §7 PartialPlan、repo_verify 落
# verdict）。三者靠 ``last_output.source`` 互斥路由，判定条件不重叠。业务表写入全部经
# ``ResearchService``（INV-6，本段零裸 ORM 写）。token 吊销由上游终态钩子无条件完成，
# 本段**不新增吊销调用**。

# 派发侧（services/process_runtime/blueprint_research_adapter.py）写入的 source 值
_BLUEPRINT_RESEARCH_SOURCE = "blueprint_research"
_BLUEPRINT_VERDICTS = ("suitable", "partial", "unsuitable")
_BLUEPRINT_ROLES = ("direct", "indirect")
# 反幻觉上界：容器编造大量 findings 时截断（T-112-18）
_BLUEPRINT_MAX_FINDINGS = 20
_BLUEPRINT_MAX_TEXT = 4000
# 与 fitness 平级保留的既有 §7 键（容器若一并产出则透传，缺失不补造）
_BLUEPRINT_PASSTHROUGH_LIST_KEYS = (
    "proposed_changes",
    "candidate_files",
    "api_contracts_exposed",
    "dependencies_on_other_repos",
)


def _is_blueprint_research(session: SubAgentSession) -> bool:
    """路由判定：PLAN 任务 + last_output.source == blueprint_research。

    与 ``_is_plan_research`` 互斥（同为 PLAN 任务，靠 source 值区分），因此既有方案调研链
    不会被本链抢走，反之亦然。
    """
    return (
        session.task_type == SubAgentSession.TaskType.PLAN
        and isinstance(session.last_output, dict)
        and session.last_output.get("source") == _BLUEPRINT_RESEARCH_SOURCE
    )


def _parse_blueprint_fitness(output: Any) -> dict[str, Any] | None:
    """从容器 output 提取蓝图调研结论（**缺 fitness.verdict 即视为不可解析返回 None**）。

    优先结构化透传（output 已含 ``fitness``），否则从 ``output["text"]`` 提 JSON 围栏 /
    花括号跨度后 ``json.loads``。归一化按白名单 + 枚举校验：``verdict`` 非法即判不可解析
    （宁可失败重跑，也不把编造结论落进蓝图投影数据）；``role_suggestion`` 非法回落保守的
    ``direct``（要改动的仓被误判成不改动，代价远高于反过来）。
    """
    import json as json_mod

    if not isinstance(output, dict):
        return None
    raw: dict[str, Any] | None = output if "fitness" in output else None
    if raw is None:
        text = str(output.get("text", "") or "")
        if not text:
            return None
        try:
            parsed = json_mod.loads(_parse_summary_json(text))
        except (json_mod.JSONDecodeError, TypeError):
            return None
        raw = parsed if isinstance(parsed, dict) else None
    if raw is None:
        return None

    fitness = raw.get("fitness")
    if not isinstance(fitness, dict):
        return None
    verdict = str(fitness.get("verdict") or "").strip().lower()
    if verdict not in _BLUEPRINT_VERDICTS:
        return None

    role = str(raw.get("role_suggestion") or "").strip().lower()
    if role not in _BLUEPRINT_ROLES:
        role = "direct"

    content: dict[str, Any] = {
        "fitness": {
            "verdict": verdict,
            "reasons": _blueprint_str_list(fitness.get("reasons")),
            "citations": _blueprint_str_list(fitness.get("citations")),
        },
        "role_suggestion": role,
        "responsibility": str(raw.get("responsibility") or "")[:_BLUEPRINT_MAX_TEXT],
        "findings": _blueprint_findings(raw.get("findings")),
    }
    summary = str(raw.get("research_summary") or "")[:_BLUEPRINT_MAX_TEXT]
    if summary:
        content["research_summary"] = summary
    for key in _BLUEPRINT_PASSTHROUGH_LIST_KEYS:
        value = raw.get(key)
        if isinstance(value, list):
            content[key] = value[:_BLUEPRINT_MAX_FINDINGS]
    return content


def _blueprint_str_list(value: Any) -> list[str]:
    """归一为字符串列表（非 list → []；空项剔除；条数上界）。"""
    if not isinstance(value, list):
        return []
    items = [str(item).strip() for item in value if str(item or "").strip()]
    return items[:_BLUEPRINT_MAX_FINDINGS]


def _blueprint_findings(value: Any) -> list[dict[str, Any]]:
    """findings 白名单归一：每项 ``{title, detail, citations}``，条数与文本长度设上界。"""
    if not isinstance(value, list):
        return []
    findings: list[dict[str, Any]] = []
    for item in value[:_BLUEPRINT_MAX_FINDINGS]:
        if isinstance(item, str):
            text = item.strip()
            if text:
                findings.append(
                    {"title": "", "detail": text[:_BLUEPRINT_MAX_TEXT], "citations": []}
                )
            continue
        if not isinstance(item, dict):
            continue
        findings.append(
            {
                "title": str(item.get("title") or "")[:_BLUEPRINT_MAX_TEXT],
                "detail": str(item.get("detail") or item.get("description") or "")[
                    :_BLUEPRINT_MAX_TEXT
                ],
                "citations": _blueprint_str_list(item.get("citations")),
            }
        )
    return findings


async def _aload_blueprint_research_task(session: SubAgentSession):
    """由 last_output 反查 ``(RepoResearchTask, ConvergenceSession)``（不可用位为 None）。

    缺 ``research_task_id`` 或 task 已终态（done/failed/stale）→ ``(None, None)``，调用方
    no-op（回调重投递幂等：已落库的结论不会被二次覆盖）。
    """
    from delivery.models import ConvergenceSession, RepoResearchTask, RepoResearchTaskStatus

    lo = session.last_output or {}
    task_id = lo.get("research_task_id")
    blueprint_session_id = lo.get("blueprint_session_id")
    if not task_id:
        return None, None
    task = await RepoResearchTask.objects.filter(id=task_id).afirst()
    if task is None or task.status in (
        RepoResearchTaskStatus.DONE,
        RepoResearchTaskStatus.FAILED,
        RepoResearchTaskStatus.STALE,
    ):
        return None, None
    blueprint_session = None
    if blueprint_session_id:
        blueprint_session = await ConvergenceSession.objects.filter(
            id=blueprint_session_id
        ).afirst()
    return task, blueprint_session


async def _trigger_blueprint_research_barrier(blueprint_session) -> None:
    """fan-out barrier（幂等）：所有 RepoResearchTask 终态才把会话交给蓝图续驱。

    **计数与 stage 转移都不在这里做**：reroute 轮次只在 barrier 后的单点串行转移里递增
    （见 blueprint_research_adapter.aadvance_reroute），本函数只负责「全部终态了，叫醒
    续驱器」。续驱器（blueprint_resume）由 112-05 交付；未就位时静默 no-op，回调不受影响。
    """
    if blueprint_session is None:
        return
    from services.process_runtime.research_aggregation import aall_research_tasks_terminal

    if not await aall_research_tasks_terminal(blueprint_session.id):
        return
    try:
        from services.process_runtime import blueprint_resume
    except ImportError:
        logger.info(
            "blueprint_research_barrier_reached",
            session_id=str(blueprint_session.id),
            driver="pending_112_05",
            category="sampling",
            component="subagent",
        )
        return
    resume = getattr(blueprint_resume, "aresume_blueprint_session", None)
    if resume is None:
        return
    await resume(blueprint_session)


async def _handle_blueprint_research_completion(
    session: SubAgentSession, p: dict[str, Any], log: BoundLogger
) -> None:
    """蓝图调研容器完成 → fitness/role/responsibility/findings 落 ``PartialPlan.content``。

    不可解析（缺 ``fitness.verdict``）→ ``mark_failed({"reason": "empty_or_unparseable_result"})``
    + emit failed；否则 ``record_partial``（**已含置 done，不再调 mark_done**）+ emit completed。
    末尾统一触发 barrier（幂等）。非本链 session 不触发。
    """
    if not _is_blueprint_research(session):
        return

    from delivery.services import ConvergenceSessionService, ResearchService
    from delivery.services.event_taxonomy import (
        EVENT_BLUEPRINT_REPO_RESEARCH_COMPLETED,
        EVENT_BLUEPRINT_REPO_RESEARCH_FAILED,
    )

    task, blueprint_session = await _aload_blueprint_research_task(session)
    if task is None:
        return

    research_service = ResearchService()
    session_service = ConvergenceSessionService()
    content = _parse_blueprint_fitness(p.get("output") or {})

    if content is None:
        await research_service.mark_failed(task, {"reason": "empty_or_unparseable_result"})
        if blueprint_session is not None:
            await session_service._emit_event(
                EVENT_BLUEPRINT_REPO_RESEARCH_FAILED,
                blueprint_session,
                {
                    "repository_id": str(task.repository_id),
                    "task_id": str(task.id),
                    "error": "empty_or_unparseable_result",
                },
            )
    else:
        # 与既有 §7 键平级：repository_id 由服务端权威写入，不采信容器上报值
        content["repository_id"] = str(task.repository_id)
        await research_service.record_partial(task, content)
        if blueprint_session is not None:
            await session_service._emit_event(
                EVENT_BLUEPRINT_REPO_RESEARCH_COMPLETED,
                blueprint_session,
                {
                    "repository_id": str(task.repository_id),
                    "task_id": str(task.id),
                    "verdict": content["fitness"]["verdict"],
                    "role_suggestion": content["role_suggestion"],
                    "findings_count": len(content["findings"]),
                },
            )

    await _trigger_blueprint_research_barrier(blueprint_session)
    log.info("blueprint_research_completion_handled", task_id=str(task.id), failed=content is None)


async def _handle_blueprint_research_failure(
    session: SubAgentSession, p: dict[str, Any], log: BoundLogger
) -> None:
    """蓝图调研容器失败 → mark_failed(container_failed) + emit failed + barrier（失败也是终态）。"""
    if not _is_blueprint_research(session):
        return

    from delivery.services import ConvergenceSessionService, ResearchService
    from delivery.services.event_taxonomy import EVENT_BLUEPRINT_REPO_RESEARCH_FAILED

    task, blueprint_session = await _aload_blueprint_research_task(session)
    if task is None:
        return

    error_msg = redact_secrets_in_text(str(p.get("error", "Unknown error")))
    await ResearchService().mark_failed(task, {"reason": "container_failed", "error": error_msg})
    if blueprint_session is not None:
        await ConvergenceSessionService()._emit_event(
            EVENT_BLUEPRINT_REPO_RESEARCH_FAILED,
            blueprint_session,
            {
                "repository_id": str(task.repository_id),
                "task_id": str(task.id),
                "error": error_msg,
            },
        )
    await _trigger_blueprint_research_barrier(blueprint_session)
    log.info("blueprint_research_failure_handled", task_id=str(task.id))


# 处理器映射
_HANDLERS = {
    CallbackType.COMPLETED: _handle_completed,
    CallbackType.FAILED: _handle_failed,
    CallbackType.HEARTBEAT: _handle_heartbeat,
    CallbackType.QUESTION: _handle_question,
    CallbackType.PROGRESS: _handle_progress,
    CallbackType.ACTION_LOG: _handle_action_log,
    CallbackType.TOKEN_USAGE: _handle_token_usage,
}
