"""Runner WebSocket consumer。"""

import asyncio
import time
import uuid
from typing import Any

import structlog
from channels.generic.websocket import AsyncJsonWebsocketConsumer
from django.utils import timezone

from common.log_context import LogSource
from common.request_metrics import arecord_request_metric

logger = structlog.get_logger()


async def _record_runner_ws_metric(*, event: str, connected_at: float | None = None) -> None:
    """为 Runner WS connect/disconnect 记一行 RequestMetric（best-effort）。"""
    try:
        duration_ms = (
            max(int((time.perf_counter() - connected_at) * 1000), 0)
            if connected_at is not None
            else None
        )
        await arecord_request_metric(
            source=LogSource.WS.value,
            route="ws:runner",
            method="WS",
            status_code=101,
            error_class="none",
            duration_ms=duration_ms,
            labels={"ws_event": event},
        )
    except Exception:  # noqa: BLE001 — WS 指标绝不反噬业务
        pass


# 终态集合
_TERMINAL_STATUSES = {"completed", "error", "timeout", "cancelled"}

# 断连超时（秒）：5 分钟后未重连则标记任务失败
DISCONNECT_TIMEOUT = 300

# rejected 重派上限（31u）：累计拒绝达该值即落终态 error（退避曲线 5*2**n 封顶 300s，
# 约 20+ 分钟窗口后放弃），杜绝对持续拒绝的 runner 热循环。
_REJECT_REDISPATCH_LIMIT = 8


HELLO_TIMEOUT = 10


class RunnerConsumer(AsyncJsonWebsocketConsumer):
    """处理 Runner WS 连接，按 type 分发消息到 handler。"""

    _handlers: dict[str, str] = {
        "runner.hello": "_handle_hello",
        "runner.heartbeat": "_handle_heartbeat",
        "task.accepted": "_handle_task_accepted",
        "task.completed": "_handle_task_completed",
        "task.failed": "_handle_task_failed",
        "task.question": "_handle_task_question",
        "task.token_usage": "_handle_task_token_usage",
        "task.log": "_handle_task_log",
        "task.progress": "_handle_task_progress",
        "task.rejected": "_handle_task_rejected",
        "tool.call": "_handle_tool_call",
    }

    async def connect(self):
        runner = self.scope.get("runner")
        if not runner:
            await self.close(code=4001)
            return

        self.runner = runner
        self.group_name = f"runner_{runner.id}"
        self._heartbeat_count = 0
        self._hello_received = False

        await self.channel_layer.group_add(self.group_name, self.channel_name)
        await self.accept()
        await self._update_channel_name(self.channel_name)
        self._ws_connected_at = time.perf_counter()
        await _record_runner_ws_metric(event="connect")

        # 握手超时：runner 必须在 HELLO_TIMEOUT 秒内发送 runner.hello
        self._hello_timeout = asyncio.ensure_future(self._hello_timeout_handler())

    async def _hello_timeout_handler(self) -> None:
        await asyncio.sleep(HELLO_TIMEOUT)
        if not self._hello_received:
            logger.warning(
                "runner_hello_timeout",
                runner_id=str(self.runner.id),
                runner_name=self.runner.name,
            )
            await self.close(code=4004)

    async def disconnect(self, close_code):
        await _record_runner_ws_metric(
            event="disconnect",
            connected_at=getattr(self, "_ws_connected_at", None),
        )
        if hasattr(self, "_hello_timeout"):
            self._hello_timeout.cancel()
        if hasattr(self, "group_name"):
            await self.channel_layer.group_discard(self.group_name, self.channel_name)
        if hasattr(self, "runner") and close_code != 4002:
            if self._hello_received:
                await self._mark_offline()
                await _broadcast_monitor_event(
                    self.channel_layer,
                    "runner.status_changed",
                    self.runner.id,
                    {"status": "offline"},
                )
                await _alog_runner_event(self.runner.id, "disconnected")
                _schedule_disconnect_timeout(self.runner.id)
            else:
                logger.debug(
                    "runner_disconnected_without_hello",
                    runner_id=str(self.runner.id),
                )

    async def receive_json(self, content, **kwargs):
        msg_type = content.get("type")
        handler_name = self._handlers.get(msg_type) if msg_type else None
        if handler_name:
            await getattr(self, handler_name)(content)
        else:
            logger.warning("unknown_message_type", type=msg_type)

    # -- message handlers --

    async def _handle_hello(self, content):
        self._hello_received = True
        if hasattr(self, "_hello_timeout"):
            self._hello_timeout.cancel()
        payload = content.get("payload", {})
        await self._update_hello(payload)
        await _broadcast_monitor_event(
            self.channel_layer,
            "runner.status_changed",
            self.runner.id,
            {"status": "online", "name": self.runner.name, "version": payload.get("version", "")},
        )
        await _alog_runner_event(
            self.runner.id, "connected", {"version": payload.get("version", "")}
        )
        # 重连时恢复未完成任务关联。runner 在 hello 里上报仍在跑的 task_id 列表
        # （running_tasks）；recovery 只对「runner 没在跑」的任务重派发，避免对
        # 旧容器还活着的任务再起第二个容器（历史 non-fast-forward 冲突的根因）。
        running_tasks = payload.get("running_tasks") or []
        await self._recover_pending_tasks(running_tasks=running_tasks)
        # 31u：不再需要「上线触发 drain」——pending 的 durable 派发 job 在下一个
        # run_at 到点自动重试（退避封顶 300s），runner 上线后至多等一个退避周期。

    async def _handle_heartbeat(self, content):
        payload = content.get("payload", {})
        await self._update_heartbeat(payload)
        self._heartbeat_count += 1
        # 每次心跳记录详细指标到 RunnerEvent（支持趋势查看）
        _METRIC_KEYS = (
            "cpu_percent",
            "mem_percent",
            "mem_total_mb",
            "mem_used_mb",
            "disk_percent",
            "disk_total_gb",
            "disk_used_gb",
            "current_tasks",
            "max_concurrent",
            "accepting",
        )
        detail = {k: payload[k] for k in _METRIC_KEYS if k in payload}
        await _alog_runner_event(self.runner.id, "heartbeat", detail)
        # 每 10 次广播到前端监控（避免 WS 消息过多）
        if self._heartbeat_count % 10 == 0:
            await _broadcast_monitor_event(
                self.channel_layer,
                "runner.status_changed",
                self.runner.id,
                {"status": "online", "current_tasks": payload.get("current_tasks", 0)},
            )

    async def _handle_task_accepted(self, content):
        payload = content.get("payload", {})
        task_id = payload.get("task_id", "")
        logger.info("task_accepted", runner=str(self.runner.id), task_id=task_id)
        if answer_endpoint := payload.get("answer_endpoint", ""):
            if task_id:
                await self._store_answer_endpoint(task_id, answer_endpoint)
        await _broadcast_monitor_event(
            self.channel_layer,
            "task.status_changed",
            self.runner.id,
            {"task_id": task_id, "status": "running"},
        )
        await self._update_assignment_status(task_id, "running")
        # 标记 SubAgentSession 为 running（task_id == session_id）。历史上 accepted 只更
        # 新 assignment 不更新 session，导致大量"实际在跑"的 session 永远停在 pending，
        # observability 的 pending 计数严重失真（生产 554 pending 多为此）。
        await self._amark_session_running(task_id, payload)

    async def _amark_session_running(self, task_id: str, payload: dict) -> None:
        """把 task_id 对应的 SubAgentSession 推进到 running，并同步仓库 AI 描述状态。"""
        if not task_id:
            return
        from repositories.models import AISummaryStatus, Repository
        from subagent.models import SubAgentSession

        session = await SubAgentSession.objects.filter(session_id=task_id).afirst()
        if session is None or session.status in _TERMINAL_STATUSES:
            return
        if session.status != SubAgentSession.Status.RUNNING:
            try:
                await session.amark_running(
                    payload.get("container_id", "") or session.container_id,
                    payload.get("container_name", "") or session.container_name,
                )
            except Exception:  # noqa: BLE001 — 标记失败不阻断任务消费
                logger.warning("amark_session_running_failed", task_id=task_id, exc_info=True)
                return
        # repo_summary：把仓库状态从 pending 推进到 running，前端"生成中"才准确。
        if session.task_type == SubAgentSession.TaskType.REPO_SUMMARY and isinstance(
            session.last_output, dict
        ):
            repo_id = session.last_output.get("repository_id")
            if repo_id:
                await Repository.objects.filter(id=repo_id).aupdate(
                    ai_summary_status=AISummaryStatus.RUNNING
                )

    async def _handle_task_completed(self, content):
        payload = content.get("payload", {})
        task_id = payload.get("task_id", "")
        log = logger.bind(runner=str(self.runner.id), task_id=task_id)
        await self._handle_completed(payload, log)
        await _broadcast_monitor_event(
            self.channel_layer,
            "task.status_changed",
            self.runner.id,
            {"task_id": task_id, "status": "completed"},
        )
        await self._update_assignment_status(task_id, "completed")
        await _alog_runner_event(self.runner.id, "task_completed", {"task_id": task_id})
        # 完成即释放一个并发槽位（续派由 durable re-defer backoff 接管，见 _free_runner_slot）。
        await self._free_runner_slot()

    async def _handle_task_failed(self, content):
        payload = content.get("payload", {})
        task_id = payload.get("task_id", "")
        log = logger.bind(runner=str(self.runner.id), task_id=task_id)
        await self._handle_failed(payload, log)
        await _broadcast_monitor_event(
            self.channel_layer,
            "task.status_changed",
            self.runner.id,
            {"task_id": task_id, "status": "failed"},
        )
        await self._update_assignment_status(task_id, "failed")
        await _alog_runner_event(
            self.runner.id, "task_failed", {"task_id": task_id, "error": payload.get("error", "")}
        )
        # 失败同样释放并发槽位（与完成路径对称）。
        await self._free_runner_slot()

    async def _handle_task_question(self, content):
        payload = content.get("payload", {})
        task_id = payload.get("task_id", "")
        log = logger.bind(runner=str(self.runner.id), task_id=task_id)
        result = await self._create_question(payload)
        if result:
            session, question_id = result
            from subagent.question_handler import send_question_card_enhanced

            message_id = await send_question_card_enhanced(
                session=session,
                question=payload.get("question", ""),
                options=payload.get("options", []),
                context=payload.get("context", ""),
                code_snippet=payload.get("code_snippet", ""),
                question_id=question_id,
            )
            if message_id:
                await self._update_feishu_message_id(question_id, message_id)
            log.info("task_question_via_ws", question_id=question_id)

    async def _handle_task_token_usage(self, content):
        payload = content.get("payload", {})
        task_id = payload.get("task_id", "")
        log = logger.bind(runner=str(self.runner.id), task_id=task_id)
        await self._handle_token_usage(payload, log)

    async def _handle_task_log(self, content):
        payload = content.get("payload", {})
        task_id = payload.get("task_id", "")
        message = payload.get("message", "")
        logger.debug(
            "task_log",
            runner=str(self.runner.id),
            task_id=task_id,
            message=message,
        )
        for prefix, log_type in _TASK_LOG_PREFIXES.items():
            if message.startswith(prefix):
                await _append_runtime_log(
                    task_id=task_id,
                    log_type=log_type,
                    content=message[len(prefix) :].strip(),
                )
                break
        _forward_task_log(task_id, message)

    async def _handle_task_progress(self, content):
        payload = content.get("payload", {})
        task_id = payload.get("task_id", "")
        await self._handle_progress(task_id, payload)
        _forward_task_progress(task_id, payload)

    async def _handle_task_rejected(self, content):
        """runner 拒绝任务 → 标记 assignment rejected 后经 durable 队列**退避**重派。

        31u：内存重排（``on_task_rejected``）退役。重派带与「无可用 runner」同一条退避
        曲线（5 * 2**reject_count，封顶 300s），且累计拒绝达 ``_REJECT_REDISPATCH_LIMIT``
        （约 20+ 分钟退避窗口）即不再重派——把 session 落终态 error + 吊销任务 token +
        发结构化告警事件，杜绝对着一个持续拒绝的 runner 热循环。
        入队失败只记 warning（session 仍 PENDING 且有快照，stranded 恢复扫描会捡起来）。
        """
        payload = content.get("payload", {})
        task_id = payload.get("task_id", "")
        reason = payload.get("reason", "")
        logger.info("task_rejected", runner=str(self.runner.id), task_id=task_id, reason=reason)
        # 先标记 rejected：使 assignment 退出 active 集（重派守卫不再拦），且本次计入
        # reject_count（含刚标记的这条）。
        await self._update_assignment_status(task_id, "rejected")

        from runners.models import RunnerTaskAssignment

        # "rejected" 是 _update_assignment_status 既有的存量字面值（choices 之外经
        # aupdate 直写，历史行为），此处按同字面值统计。
        reject_count = await RunnerTaskAssignment.objects.filter(
            session__session_id=task_id, status="rejected"
        ).acount()

        if reject_count >= _REJECT_REDISPATCH_LIMIT:
            await self._afail_session_after_reject_exhausted(task_id, reason, reject_count)
            return

        from datetime import timedelta as _timedelta

        delay = min(5 * (2**reject_count), 300)
        run_at = timezone.now() + _timedelta(seconds=delay)
        try:
            from durable.queues import QUEUE_DISPATCH
            from durable.service import DurableTaskService

            await DurableTaskService.defer(
                "durable_runner_dispatch",
                {"session_id": task_id, "attempt": 0},
                queue=QUEUE_DISPATCH,
                lock=f"dispatch-{task_id}",
                run_at=run_at,
                initiated_by_user_id="system",
            )
            logger.info(
                "runner_dispatch_rejected_requeued",
                category="sampling",
                component="runners",
                session_id=task_id,
                runner_id=str(self.runner.id),
                reject_count=reject_count,
                delay_s=delay,
            )
        except Exception:  # noqa: BLE001 — 入队失败不反噬 WS 消息处理；恢复扫描兜底
            logger.warning(
                "runner_dispatch_rejected_requeue_failed",
                category="caller",
                component="runners",
                initiated_by_user_id="system",
                session_id=task_id,
                exc_info=True,
            )

    async def _afail_session_after_reject_exhausted(
        self, task_id: str, reason: str, reject_count: int
    ) -> None:
        """rejected 重派超限：session 落终态 error + 吊销任务 token + 结构化告警。"""
        from common.logging import redact_secrets_in_text
        from subagent.models import SubAgentSession

        session = await SubAgentSession.objects.filter(session_id=task_id).afirst()
        if session is not None and session.status not in _TERMINAL_STATUSES:
            error_msg = redact_secrets_in_text(
                f"runner 连续拒绝 {reject_count} 次，派发终止（最后拒绝原因：{reason or '未知'}）"
            )
            try:
                await session.amark_failed(error=error_msg)
            except Exception:  # noqa: BLE001 — 收敛失败不阻断 WS 消息处理
                logger.warning(
                    "reject_exhausted_session_converge_failed",
                    session_id=task_id,
                    exc_info=True,
                )
            # 复用 dispatch_coding_task 失败路径的吊销语义（有 token 则吊销，无则幂等 0）。
            try:
                from access_tokens.services import arevoke_task_tokens

                await arevoke_task_tokens(task_id)
            except Exception:  # noqa: BLE001 — best-effort，失败由 TTL 自过期兜底
                pass
        logger.warning(
            "runner_dispatch_rejected_exhausted",
            category="caller",
            component="runners",
            initiated_by_user_id="system",
            session_id=task_id,
            reject_count=reject_count,
            runner_id=str(self.runner.id),
        )

    async def _handle_tool_call(self, content):
        payload = content.get("payload", {})
        call_id = payload.get("call_id", "")
        tool_name = payload.get("tool_name", "")
        arguments = payload.get("arguments", {})

        from tools.executor import execute_tool

        result = await execute_tool(tool_name, arguments)
        await self.send_json(
            {
                "type": "tool.result",
                "payload": {"call_id": call_id, "result": result},
            }
        )

    # -- channel layer events --

    async def runner_message(self, event):
        """Channel layer 事件：向 Runner 发送消息。"""
        await self.send_json(event["message"])

    async def force_disconnect(self, event):
        """收到踢连接指令。"""
        await self.close(code=4002)

    # -- async ORM helpers --

    async def _update_hello(self, payload: dict) -> None:
        r = self.runner
        r.status = "online"
        r.version = payload.get("version", "")
        r.last_heartbeat = timezone.now()
        await r.asave(update_fields=["status", "version", "last_heartbeat", "updated_at"])

    async def _update_heartbeat(self, payload: dict) -> None:
        r = self.runner
        r.status = "online"
        r.last_heartbeat = timezone.now()
        r.current_tasks = payload.get("current_tasks", r.current_tasks)
        await r.asave(update_fields=["status", "last_heartbeat", "current_tasks", "updated_at"])

    async def _store_answer_endpoint(self, session_id: str, answer_endpoint: str) -> None:
        from subagent.models import SubAgentSession

        session = await SubAgentSession.objects.filter(session_id=session_id).afirst()
        if session:
            output = session.last_output or {}
            output["answer_endpoint"] = answer_endpoint
            session.last_output = output
            await session.asave(update_fields=["last_output", "updated_at"])

    async def _handle_completed(self, payload: dict, log: structlog.stdlib.BoundLogger) -> None:
        from subagent.api.callbacks import (
            _schedule_agent_session_resume,
            _schedule_workflow_resume,
            _update_coding_session_on_complete,
        )
        from subagent.models import SubAgentSession, TaskResult

        task_id = payload.get("task_id", "")
        session = await SubAgentSession.objects.filter(session_id=task_id).afirst()
        if not session or session.status in _TERMINAL_STATUSES:
            log.warning(
                "completed_session_not_found_or_terminal", status=getattr(session, "status", None)
            )
            return

        if not await TaskResult.objects.filter(session=session).aexists():
            output = payload.get("output", {})
            if not isinstance(output, dict):
                output = {}
            branch_name = payload.get("branch_name") or output.get("branch_name", "")
            commit_sha = payload.get("commit_sha") or output.get("commit_sha", "")
            modified_files = payload.get("modified_files") or output.get("modified_files", [])
            if not isinstance(modified_files, list):
                modified_files = []
            await TaskResult.objects.acreate(
                session=session,
                result_type=payload.get("result_type", "text"),
                text_output=payload.get("text_output", ""),
                branch_name=branch_name,
                commit_sha=commit_sha,
                modified_files=modified_files,
                raw_output=output,
                duration_ms=payload.get("duration_ms"),
            )

        await session.amark_completed()

        # Phase 103 AGENT-01：WS 直连路径独立写终态（不经 callbacks handler），同点
        # 吊销任务级短 TTL token（best-effort：service 内吞异常且此处再套一层，
        # 绝不阻塞 WS 消息处理）。
        try:
            from access_tokens.services import arevoke_task_tokens

            await arevoke_task_tokens(session.session_id)
        except Exception:  # noqa: BLE001 — best-effort，失败由 TTL 自过期兜底
            pass

        if session.task_type == SubAgentSession.TaskType.REPO_SUMMARY:
            from subagent.api.callbacks import _update_repository_on_summary_complete

            await _update_repository_on_summary_complete(
                session,
                {
                    "result_type": payload.get("result_type", "text"),
                    "output": payload.get("output", {"text": payload.get("text_output", "")}),
                },
            )

        # 与 HTTP callback handler 对齐 — 推进关联 CodingSession 的 graph 状态。
        # 历史上 WS 路径漏了这一步，导致 task_type=coding 的 session 容器退出后
        # CodingSession.status 永远停在 running（follow-up RESEARCH 根因 2b）。
        # 非 CodingSession (deep_analysis / workflow / repo_summary) 在
        # _update_coding_session_on_complete 内部走 `coding_session is None` 短路。
        await _update_coding_session_on_complete(session)

        # chat 的 deep_analysis 完成时自动回算 cross_repo_relevance。
        # 与 HTTP _handle_completed 对齐 —— 历史上 WS 路径漏了这一步，导致
        # deep_analysis 完成走 WS→BarrierManager 时永远写不到 deep_analysis_completion
        # trace / 回灌 [cross_repo_relevance:<trace_id>] 段（284 UAT review round 集成断点）。
        # 必须在 _schedule_agent_session_resume 之前 await：helper 会把 marker 追加进
        # TaskResult.text_output，BarrierManager 随后读取 text_output 回灌 chat 流。
        if (
            session.task_type == SubAgentSession.TaskType.EXPLORE
            and isinstance(session.last_output, dict)
            and session.last_output.get("source") == "chat_deep_analysis"
        ):
            from subagent.api.callbacks import _update_agent_session_cross_repo_relevance

            await _update_agent_session_cross_repo_relevance(session, payload)

        # 与 HTTP callback handler 对齐 —— 四条容器链的完成处理（plan_research /
        # repo_verify / blueprint_research / blueprint_repo_plan）。历史上 WS 路径
        # 全部缺失：结果只经 WS 送达时，RepoResearchTask / RepoVerifyTask 等业务表
        # 永远停在 running、fan-out 屏障永不触发，蓝图/方案编排 waiting_event 卡死
        # （2026-08-05 线上事故根因之一）。各自独立 try/except swallow、内部幂等
        # （任务已终态即 no-op），且必须在续驱调度之前 await（CR-01 顺序约束）。
        from subagent.api.callbacks import (
            _handle_blueprint_repo_plan_completion,
            _handle_blueprint_research_completion,
            _handle_repo_verify_completion,
            _handle_research_completion,
            _is_blueprint_repo_plan,
            _is_blueprint_research,
        )

        try:
            await _handle_research_completion(session, payload, log)
        except Exception as exc:  # noqa: BLE001 — 永不阻塞 WS 消息处理
            logger.warning(
                "research_completion_ws_failed",
                session_id=session.session_id,
                error=str(exc),
            )
        try:
            await _handle_repo_verify_completion(session, payload, log)
        except Exception as exc:  # noqa: BLE001 — 永不阻塞 WS 消息处理
            logger.warning(
                "repo_verify_completion_ws_failed",
                session_id=session.session_id,
                error=str(exc),
            )
        if _is_blueprint_research(session):
            try:
                await _handle_blueprint_research_completion(session, payload, log)
            except Exception as exc:  # noqa: BLE001 — 永不阻塞 WS 消息处理
                logger.warning(
                    "blueprint_research_completion_ws_failed",
                    session_id=session.session_id,
                    error=str(exc),
                )
        if _is_blueprint_repo_plan(session):
            try:
                await _handle_blueprint_repo_plan_completion(session, payload, log)
            except Exception as exc:  # noqa: BLE001 — 永不阻塞 WS 消息处理
                logger.warning(
                    "blueprint_repo_plan_completion_ws_failed",
                    session_id=session.session_id,
                    error=str(exc),
                )

        _schedule_workflow_resume(session, log)
        _schedule_agent_session_resume(session, log)
        log.info("task_completed_via_ws")

    async def _handle_failed(self, payload: dict, log: structlog.stdlib.BoundLogger) -> None:
        from subagent.api.callbacks import (
            _schedule_agent_session_resume,
            _schedule_workflow_resume,
            _send_failure_notification,
            _update_coding_session_on_fail,
        )
        from subagent.models import SubAgentSession

        task_id = payload.get("task_id", "")
        session = await SubAgentSession.objects.filter(session_id=task_id).afirst()
        if not session or session.status in _TERMINAL_STATUSES:
            log.warning(
                "failed_session_not_found_or_terminal", status=getattr(session, "status", None)
            )
            return

        raw_error = payload.get("error", "Unknown error")
        # 丰富过于简略的 runner 错误提示
        if raw_error == "exited with code 1":
            error_msg = (
                "深度分析容器启动后立即退出（exit code 1）。"
                "常见原因：Docker 镜像异常、环境变量缺失、Git 仓库无法克隆或 API 凭据无效。"
                "建议检查 Runner 日志及容器配置。"
            )
        else:
            error_msg = raw_error

        session.failure_reason = error_msg
        await session.asave(update_fields=["failure_reason"])
        await session.amark_failed(error=error_msg)

        # Phase 103 AGENT-01：WS 失败终态同点吊销任务 token（best-effort，见
        # _handle_completed 处注释）。
        try:
            from access_tokens.services import arevoke_task_tokens

            await arevoke_task_tokens(session.session_id)
        except Exception:  # noqa: BLE001 — best-effort，失败由 TTL 自过期兜底
            pass

        # 将错误信息写入 last_output.logs，供前端深度分析卡片展示
        last_output = session.last_output or {}
        if isinstance(last_output, dict):
            logs: list[dict[str, Any]] = last_output.get("logs", [])
            if not isinstance(logs, list):
                logs = []
            logs.append(
                {
                    "type": "error",
                    "content": error_msg,
                    "ts": timezone.now().timestamp(),
                }
            )
            last_output["logs"] = logs
            session.last_output = last_output
            await session.asave(update_fields=["last_output", "updated_at"])

        await _send_failure_notification(session, error_msg)
        if session.task_type == SubAgentSession.TaskType.REPO_SUMMARY:
            from subagent.api.callbacks import _update_repository_on_summary_fail

            await _update_repository_on_summary_fail(session, error_msg)

        # 与 HTTP callback handler 对齐 — 推进关联 CodingSession 的 graph 失败处理。
        # _update_coding_session_on_fail 内部 try/except graph resume 异常会降级
        # 为 amark_failed，所以即便 graph 不存在也安全。
        await _update_coding_session_on_fail(session, error_msg)

        # 与 HTTP callback handler 对齐 —— 四条容器链的失败传播（plan_research /
        # repo_verify / blueprint_research / blueprint_repo_plan）。历史上 WS 路径
        # 全部缺失：失败只经 WS 送达时会话被翻终态、后续投递又被上面的终态守卫拦掉，
        # RepoResearchTask 永远停在 running、屏障永不触发，蓝图卡死在 repo_research
        # （2026-08-05 线上事故根因）。失败也是屏障终态，必须在续驱调度之前 await。
        from subagent.api.callbacks import (
            _handle_blueprint_repo_plan_failure,
            _handle_blueprint_research_failure,
            _handle_repo_verify_failure,
            _handle_research_failure,
            _is_blueprint_repo_plan,
            _is_blueprint_research,
        )

        try:
            await _handle_research_failure(session, payload, log)
        except Exception as exc:  # noqa: BLE001 — 永不阻塞 WS 消息处理
            logger.warning(
                "research_failure_ws_failed",
                session_id=session.session_id,
                error=str(exc),
            )
        try:
            await _handle_repo_verify_failure(session, payload, log)
        except Exception as exc:  # noqa: BLE001 — 永不阻塞 WS 消息处理
            logger.warning(
                "repo_verify_failure_ws_failed",
                session_id=session.session_id,
                error=str(exc),
            )
        if _is_blueprint_research(session):
            try:
                await _handle_blueprint_research_failure(session, payload, log)
            except Exception as exc:  # noqa: BLE001 — 永不阻塞 WS 消息处理
                logger.warning(
                    "blueprint_research_failure_ws_failed",
                    session_id=session.session_id,
                    error=str(exc),
                )
        if _is_blueprint_repo_plan(session):
            try:
                await _handle_blueprint_repo_plan_failure(session, payload, log)
            except Exception as exc:  # noqa: BLE001 — 永不阻塞 WS 消息处理
                logger.warning(
                    "blueprint_repo_plan_failure_ws_failed",
                    session_id=session.session_id,
                    error=str(exc),
                )

        _schedule_workflow_resume(session, log)
        _schedule_agent_session_resume(session, log)
        log.info("task_failed_via_ws")

    async def _create_question(self, payload: dict) -> tuple | None:
        from subagent.models import InteractionLog, SubAgentSession

        task_id = payload.get("task_id", "")
        session = await SubAgentSession.objects.filter(session_id=task_id).afirst()
        if not session:
            logger.warning("question_session_not_found", task_id=task_id)
            return None

        question_id = f"q-{uuid.uuid4().hex[:12]}"
        await InteractionLog.objects.acreate(
            session=session,
            question_id=question_id,
            question_text=payload.get("question", ""),
            question_context=payload.get("context", ""),
            code_snippet=payload.get("code_snippet", ""),
            options=payload.get("options", []),
        )

        session.last_output = {
            **(session.last_output or {}),
            "pending_question": {
                "question_id": question_id,
                "question": payload.get("question", ""),
                "options": payload.get("options", []),
                "asked_at": timezone.now().isoformat(),
            },
        }
        await session.asave(update_fields=["last_output", "updated_at"])
        return session, question_id

    async def _update_feishu_message_id(self, question_id: str, message_id: str) -> None:
        from subagent.models import InteractionLog

        await InteractionLog.objects.filter(question_id=question_id).aupdate(
            feishu_message_id=message_id
        )

    async def _handle_token_usage(self, payload: dict, log: structlog.stdlib.BoundLogger) -> None:
        from subagent.models import SubAgentSession, TokenUsage

        task_id = payload.get("task_id", "")
        session = await SubAgentSession.objects.filter(session_id=task_id).afirst()
        if not session:
            log.warning("token_usage_session_not_found", task_id=task_id)
            return

        await TokenUsage.objects.acreate(
            session=session,
            input_tokens=payload.get("input_tokens", 0),
            output_tokens=payload.get("output_tokens", 0),
            cache_read_tokens=payload.get("cache_read_tokens", 0),
            cache_write_tokens=payload.get("cache_write_tokens", 0),
            model=payload.get("model", ""),
            total_cost_usd=payload.get("total_cost_usd", 0),
            source=TokenUsage.Source.SUBAGENT,
        )
        log.debug("token_usage_recorded_via_ws")

    async def _handle_progress(self, task_id: str, payload: dict) -> None:
        # implementation G4: 调用公共 parse_progress_payload，与 HTTP 路径
        # subagent/api/callbacks.py:_handle_progress 保持同一解析逻辑
        from orchestration.progress_payload import parse_progress_payload
        from subagent.models import SubAgentSession

        session = await SubAgentSession.objects.filter(session_id=task_id).afirst()
        if not session:
            return

        output = parse_progress_payload(payload)
        # implementation G5: merge 语义保留既有 meta（task_type/source/conversation_id/logs 等）
        session.last_output = {**(session.last_output or {}), **output}
        await session.asave(update_fields=["last_output", "updated_at"])
        await _append_runtime_log(
            task_id=task_id,
            log_type="progress",
            content=payload.get("message", ""),
        )

    async def _rebuild_dispatch_task(self, session_id: str):
        """断连恢复重建：委托 dispatcher 模块级共享实现（31u，⛔ 不留拷贝）。

        凭证重解析（Git token / API key 从权威源补回；USER_TOKEN 按
        ``task_token_user_id`` 重铸——31u 起重派容器也能挂上知识工具）由共享的
        ``_rehydrate_dispatch_credentials`` 承担。``require_snapshot=False``：历史行
        （无 dispatch 快照）沿用 session 字段兜底重建的既有行为。
        """
        from runners.dispatcher import arebuild_dispatch_task_from_session
        from runners.models import RunnerTaskAssignment

        assignment = (
            await RunnerTaskAssignment.objects.filter(
                runner=self.runner, session__session_id=session_id
            )
            .select_related("session")
            .afirst()
        )
        if not assignment or not assignment.session:
            return None
        return await arebuild_dispatch_task_from_session(
            assignment.session,
            fallback_tags=list(self.runner.tags),
            require_snapshot=False,
        )

    async def _update_assignment_status(self, session_id: str, status: str) -> None:
        from runners.models import RunnerTaskAssignment

        updates: dict[str, object] = {"status": status}
        if status in ("completed", "failed", "rejected"):
            updates["completed_at"] = timezone.now()
        await RunnerTaskAssignment.objects.filter(
            runner=self.runner, session__session_id=session_id, status__in=["assigned", "running"]
        ).aupdate(**updates)

    async def _free_runner_slot(self) -> None:
        """任务终态后释放一个并发槽位。

        服务端立即把 ``Runner.current_tasks`` 减 1（下限 0），不必等 30s 后的下一次
        心跳，使刚释放的槽位对 ``_try_assign`` 即时可见；心跳上报的绝对值随后会
        权威校正任何漂移。

        31u：续派由 durable re-defer backoff 接管（等待中的派发 job 在下一个 run_at
        到点自动重试，最长等一个退避周期 ≤300s），不再依赖槽位释放事件触发 drain。
        """
        from django.db import models as db_models
        from django.db.models.functions import Greatest

        from runners.models import Runner

        await Runner.objects.filter(id=self.runner.id).aupdate(
            current_tasks=Greatest(db_models.F("current_tasks") - 1, db_models.Value(0)),
        )

    async def _update_channel_name(self, channel_name: str):
        self.runner.channel_name = channel_name
        await self.runner.asave(update_fields=["channel_name", "updated_at"])

    async def _mark_offline(self):
        self.runner.status = "offline"
        self.runner.channel_name = ""
        await self.runner.asave(update_fields=["status", "channel_name", "updated_at"])

    async def _recover_pending_tasks(self, running_tasks: list[str] | None = None) -> None:
        """重连时恢复未完成任务关联。

        查询该 Runner 所有 assigned/running 状态的任务：
        - 任务已在终态：标记 assignment 为 failed（清理脏关联）。
        - runner 仍在跑该任务（session_id 在 ``running_tasks`` 上报列表里）：**不重派发**，
          旧容器会自己完成并通过补发的 WS 消息上报；重派发会起第二个容器导致
          push non-fast-forward 冲突（历史 bug 根因）。
        - 否则（容器确已消失，如 runner 进程重启被 StartupCleanup 清掉）：重新 dispatch。

        Args:
            running_tasks: runner 在 hello 中上报的、当前仍在运行的 task_id 列表。
                旧版 runner（未上报）传 None/空列表时退化为旧行为（全部重派发），
                此时由 dispatcher 的 DB CAS 幂等兜底防止重复 active assignment。
        """
        from runners.models import RunnerTaskAssignment

        running_set = set(running_tasks or [])

        pending_assignments = RunnerTaskAssignment.objects.filter(
            runner=self.runner,
            status__in=["assigned", "running"],
        ).select_related("session")

        recovered_count = 0
        skipped_count = 0
        async for assignment in pending_assignments:
            session = assignment.session
            if not session or session.status in _TERMINAL_STATUSES:
                # 任务已在终态，标记 assignment 为 failed
                assignment.status = "failed"
                assignment.completed_at = timezone.now()
                await assignment.asave(update_fields=["status", "completed_at"])
                continue

            # runner 仍在跑该任务 → 旧容器还活着，跳过重派发，等它自己完成。
            if session.session_id in running_set:
                skipped_count += 1
                continue

            # 重新分发任务（容器确已消失）
            dispatch_task = await self._rebuild_dispatch_task(session.session_id)
            if dispatch_task:
                from runners.dispatcher import get_dispatcher

                await get_dispatcher().dispatch(dispatch_task)
                recovered_count += 1

        if recovered_count > 0 or skipped_count > 0:
            logger.info(
                "runner_tasks_recovered",
                runner_id=str(self.runner.id),
                recovered_count=recovered_count,
                skipped_running=skipped_count,
            )


def _schedule_disconnect_timeout(runner_id: uuid.UUID) -> None:
    """启动断连超时处理。

    在后台线程中等待 DISCONNECT_TIMEOUT 秒后检查 Runner 是否仍离线。
    如果仍离线，将所有 assigned/running 状态的任务标记为 failed。
    """
    import threading

    def _timeout_handler() -> None:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            loop.run_until_complete(_handle_disconnect_timeout(runner_id))
        except Exception as e:
            logger.exception("disconnect_timeout_error", runner_id=str(runner_id), error=str(e))
        finally:
            loop.close()

    timer = threading.Timer(DISCONNECT_TIMEOUT, _timeout_handler)
    timer.daemon = True
    timer.start()


async def _handle_disconnect_timeout(runner_id: uuid.UUID) -> None:
    """断连超时处理：检查 Runner 是否仍离线，如果是则标记任务失败。"""
    from runners.models import Runner, RunnerTaskAssignment

    try:
        runner = await Runner.objects.aget(id=runner_id)
    except Runner.DoesNotExist:
        return

    # Runner 已重连，无需处理
    if runner.status == "online":
        logger.info("disconnect_timeout_runner_reconnected", runner_id=str(runner_id))
        return

    # Runner 仍离线，标记所有未完成任务为失败
    pending = RunnerTaskAssignment.objects.filter(
        runner_id=runner_id,
        status__in=["assigned", "running"],
    ).select_related("session")

    from subagent.models import SubAgentSession

    failed_count = 0
    async for assignment in pending:
        assignment.status = "failed"
        assignment.completed_at = timezone.now()
        await assignment.asave(update_fields=["status", "completed_at"])
        failed_count += 1

        # 收敛 SubAgentSession 到终态（历史上只改 assignment，导致 session 永卡
        # pending/running、仓库 ai_summary_status 永卡 pending）。
        session = assignment.session
        if session is not None and session.status not in _TERMINAL_STATUSES:
            error_msg = f"Runner 断连超时（{DISCONNECT_TIMEOUT}秒），任务自动标记失败"
            try:
                await session.amark_failed(error=error_msg)
                # Phase 103 AGENT-01：断连收敛终态同点吊销任务 token（best-effort，
                # service 内吞异常；外层 except 兜底，绝不阻塞其余 assignment 收敛）。
                from access_tokens.services import arevoke_task_tokens

                await arevoke_task_tokens(session.session_id)
                if session.task_type == SubAgentSession.TaskType.REPO_SUMMARY:
                    from subagent.api.callbacks import _update_repository_on_summary_fail

                    await _update_repository_on_summary_fail(session, error_msg)
            except Exception:
                logger.warning(
                    "disconnect_timeout_session_converge_failed",
                    session_id=session.session_id,
                )

        # 发送失败通知
        if assignment.session:
            try:
                from subagent.api.callbacks import _send_failure_notification

                await _send_failure_notification(
                    assignment.session,
                    f"Runner 断连超时（{DISCONNECT_TIMEOUT}秒），任务自动标记失败",
                )
            except Exception:
                logger.warning(
                    "disconnect_timeout_notification_failed",
                    session_id=assignment.session.session_id,
                )

    if failed_count > 0:
        logger.warning(
            "disconnect_timeout_tasks_failed",
            runner_id=str(runner_id),
            failed_count=failed_count,
        )


# ---------------------------------------------------------------------------
# 深度分析日志转发
# ---------------------------------------------------------------------------

_TASK_LOG_PREFIXES = {
    "[task:text]": "text",
    "[task:tool]": "tool_call",
    "[task:block]": "block",
    "[task:result]": "result",
    "[task:system]": "system",
    "[task:msg]": "message",
}

_MAX_RUNTIME_LOGS = 80


async def _append_runtime_log(task_id: str, log_type: str, content: str) -> None:
    from subagent.models import SubAgentSession

    session = await SubAgentSession.objects.filter(session_id=task_id).afirst()
    if not session:
        return

    output = session.last_output or {}
    logs = output.get("logs")
    if not isinstance(logs, list):
        logs = []

    logs.append(
        {
            "type": log_type,
            "content": content,
            "ts": int(timezone.now().timestamp() * 1000),
        }
    )
    output["logs"] = logs[-_MAX_RUNTIME_LOGS:]
    session.last_output = output
    await session.asave(update_fields=["last_output", "updated_at"])


def _forward_task_log(task_id: str, message: str) -> None:
    """解析容器日志的 [task:*] 前缀并推送到深度分析注册表。"""
    from agents.tools.deep_analysis_registry import push_event

    for prefix, log_type in _TASK_LOG_PREFIXES.items():
        if message.startswith(prefix):
            content = message[len(prefix) :].strip()
            push_event(task_id, {"log_type": log_type, "content": content})
            return


def _forward_task_progress(task_id: str, payload: dict) -> None:
    """将 task.progress 推送到深度分析注册表。"""
    from agents.tools.deep_analysis_registry import push_event

    push_event(
        task_id,
        {
            "log_type": "progress",
            "content": payload.get("message", ""),
        },
    )


# ---------------------------------------------------------------------------
# Monitor WebSocket — 前端实时监控
# ---------------------------------------------------------------------------

MONITOR_GROUP = "runner_monitor"
AUTH_TIMEOUT = 5


async def _broadcast_monitor_event(
    channel_layer: object, event_type: str, runner_id: uuid.UUID, data: dict
) -> None:
    await channel_layer.group_send(  # type: ignore[attr-defined]
        MONITOR_GROUP,
        {
            "type": "monitor.event",
            "data": {"event": event_type, "runner_id": str(runner_id), "data": data},
        },
    )


async def _alog_runner_event(
    runner_id: uuid.UUID, event_type: str, detail: dict | None = None
) -> None:
    from runners.models import RunnerEvent

    await RunnerEvent.objects.acreate(
        runner_id=runner_id, event_type=event_type, detail=detail or {}
    )


class MonitorConsumer(AsyncJsonWebsocketConsumer):
    """前端监控 WebSocket，从 HTTP-only Cookie 读取 JWT 认证，接收 runner/task 事件。"""

    async def connect(self) -> None:
        self.authenticated = False
        await self.accept()

        # 优先从 cookie 读取 access token 进行认证
        cookies = self.scope.get("cookies", {})
        access_token = cookies.get("access_token")
        if access_token:
            try:
                from rest_framework_simplejwt.tokens import AccessToken

                token = AccessToken(access_token)
                user_id = token["sub"]
                from django.contrib.auth import get_user_model

                await get_user_model().objects.aget(id=user_id)
                self.authenticated = True
                await self.channel_layer.group_add(MONITOR_GROUP, self.channel_name)
                await self.send_json({"type": "auth", "status": "ok"})
                return
            except Exception:
                await self.send_json({"type": "auth", "status": "error", "detail": "Invalid token"})
                await self.close(code=4003)
                return

        # Cookie 无 token，等待前端发送 auth 消息（兼容旧客户端）
        self._auth_timeout = asyncio.ensure_future(self._auth_timeout_handler())

    async def _auth_timeout_handler(self) -> None:
        await asyncio.sleep(AUTH_TIMEOUT)
        if not self.authenticated:
            await self.close(code=4001)

    async def disconnect(self, close_code: int) -> None:
        if hasattr(self, "_auth_timeout"):
            self._auth_timeout.cancel()
        if self.authenticated:
            await self.channel_layer.group_discard(MONITOR_GROUP, self.channel_name)

    async def receive_json(self, content: dict, **kwargs) -> None:
        if content.get("type") == "auth":
            await self._handle_auth(content)

    async def _handle_auth(self, content: dict) -> None:
        try:
            from rest_framework_simplejwt.tokens import AccessToken

            token = AccessToken(content.get("token", ""))
            user_id = token["sub"]
            from django.contrib.auth import get_user_model

            await get_user_model().objects.aget(id=user_id)
        except Exception:
            await self.send_json({"type": "auth", "status": "error", "detail": "Invalid token"})
            await self.close(code=4003)
            return

        if not self.authenticated:
            self.authenticated = True
            self._auth_timeout.cancel()
            await self.channel_layer.group_add(MONITOR_GROUP, self.channel_name)
        await self.send_json({"type": "auth", "status": "ok"})

    async def monitor_event(self, event: dict) -> None:
        """Channel layer handler — 转发事件到前端。"""
        await self.send_json(event["data"])
