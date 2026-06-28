"""检查并处理超时的工作流事件订阅。

定期运行（推荐 60 秒间隔，已接入 APScheduler，见 agents.runapscheduler），
扫描 timeout_at 已到达的活跃订阅，按 timeout_action 执行对应超时处理逻辑。

Chassis v2 · P0：补齐 ``retry`` 动作的真实实现——通过引擎 ``_continue_after_node``
重跑等待节点（节点会重新创建订阅并刷新 timeout），并以 execution.context 上的
有界计数器防止无限重试。

Usage: python manage.py check_timeouts
"""

import asyncio

import structlog
from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone

from workflows.models.execution import (
    ExecutionStatus,
    NodeExecutionStatus,
    WorkflowEventSubscription,
)

logger = structlog.get_logger(__name__)

# retry 动作的最大重试次数（按 execution + node 计），超过后回退为 fail。
_MAX_TIMEOUT_RETRIES = 3


class Command(BaseCommand):
    help = "检查并处理超时的工作流事件订阅"

    def handle(self, *args: object, **options: object) -> None:
        now = timezone.now()

        # retry 目标需在事务外用异步引擎重跑，先在事务内收集。
        retry_targets: list[tuple[str, str]] = []

        with transaction.atomic():
            expired_subs = list(
                WorkflowEventSubscription.objects.select_for_update(skip_locked=True)
                .filter(is_active=True, timeout_at__lte=now, timeout_at__isnull=False)
                .select_related("workflow_execution", "node_execution")
                .exclude(workflow_execution__is_debug=True)
            )

            processed = 0
            for sub in expired_subs:
                try:
                    target = self._handle_timeout(sub)
                    if target is not None:
                        retry_targets.append(target)
                    processed += 1
                except Exception:
                    logger.exception("timeout_handle_error", subscription_id=str(sub.id))

        # 事务外重跑 retry 目标（异步引擎入口，不能在 atomic + select_for_update 内调用）。
        for wf_exec_id, node_exec_id in retry_targets:
            try:
                asyncio.run(self._redrive_retry(wf_exec_id, node_exec_id))
            except Exception:
                logger.exception(
                    "timeout_retry_redrive_error",
                    workflow_execution_id=wf_exec_id,
                    node_execution_id=node_exec_id,
                )

        self.stdout.write(f"处理了 {processed} 个超时订阅")
        if processed > 0:
            logger.info(
                "timeouts_processed",
                category="caller",
                component="workflow_timeout",
                count=processed,
                retried=len(retry_targets),
            )

    def _handle_timeout(self, sub: WorkflowEventSubscription) -> tuple[str, str] | None:
        """根据 timeout_action 处理单个超时订阅。

        Returns:
            若需在事务外重跑，返回 (workflow_execution_id, node_execution_id)，否则 None。
        """
        action = sub.timeout_action
        node_exec = sub.node_execution
        wf_exec = sub.workflow_execution

        log = logger.bind(
            category="caller",
            component="workflow_timeout",
            subscription_id=str(sub.id),
            node_execution_id=str(node_exec.id),
            workflow_execution_id=str(wf_exec.id),
            timeout_action=action,
        )

        if action == "retry":
            # 有界重试：超过上限回退 fail，避免无限重试。
            retries = self._bump_retry_counter(wf_exec, str(node_exec.node_id))
            if retries <= _MAX_TIMEOUT_RETRIES:
                # 仅标记本订阅失效；节点保持 WAITING_EVENT，事务外经引擎重跑重新挂起。
                sub.mark_inactive()
                log.info("timeout_retry_scheduled", retries=retries)
                return (str(wf_exec.id), str(node_exec.id))
            # 超限回退 fail
            log.warning("timeout_retry_exhausted", retries=retries, fallback="fail")
            action = "fail"

        if action == "fail":
            node_exec.status = NodeExecutionStatus.TIMEOUT
            node_exec.save(update_fields=["status"])

            wf_exec.status = ExecutionStatus.TIMEOUT
            wf_exec.completed_at = timezone.now()
            wf_exec.error_message = f"节点 {node_exec.node_id} 等待事件超时"
            wf_exec.error_node_id = node_exec.node_id
            wf_exec.save(
                update_fields=["status", "completed_at", "error_message", "error_node_id"]
            )
            log.info("timeout_fail")

        elif action == "skip":
            node_exec.status = NodeExecutionStatus.SKIPPED
            node_exec.save(update_fields=["status"])
            log.info("timeout_skip")

        sub.mark_inactive()
        return None

    @staticmethod
    def _bump_retry_counter(wf_exec, node_id: str) -> int:
        """在 execution.context 上累加该节点的超时重试计数并返回新值。"""
        context = wf_exec.context or {}
        counters = context.get("_timeout_retries", {})
        counters[node_id] = int(counters.get(node_id, 0)) + 1
        context["_timeout_retries"] = counters
        wf_exec.context = context
        wf_exec.save(update_fields=["context"])
        return counters[node_id]

    @staticmethod
    async def _redrive_retry(wf_exec_id: str, node_exec_id: str) -> None:
        """通过引擎重跑等待节点：节点会重新创建订阅并刷新 timeout。"""
        from workflows.engine.scheduler import WorkflowEngine
        from workflows.models.execution import NodeExecution

        node_exec = await NodeExecution.objects.select_related("workflow_execution").aget(
            id=node_exec_id
        )
        wf_exec = node_exec.workflow_execution
        # 仅在节点仍处等待态、执行未终态时重跑。
        if node_exec.status not in (
            NodeExecutionStatus.WAITING_EVENT,
            NodeExecutionStatus.WAITING_INPUT,
            NodeExecutionStatus.WAITING_APPROVAL,
        ):
            return
        if wf_exec.status in (
            ExecutionStatus.COMPLETED,
            ExecutionStatus.FAILED,
            ExecutionStatus.CANCELLED,
            ExecutionStatus.TIMEOUT,
        ):
            return

        # 设置恢复标记，令 _continue_after_node 重置 RUNNING 并重跑该节点。
        output = node_exec.output_data or {}
        output["_resume_from_callback"] = True
        output["_timeout_retry"] = True
        node_exec.output_data = output
        await node_exec.asave(update_fields=["output_data"])

        engine = WorkflowEngine()
        await engine._continue_after_node(wf_exec, node_exec)
