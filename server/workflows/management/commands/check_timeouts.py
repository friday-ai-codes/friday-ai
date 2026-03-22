"""检查并处理超时的工作流事件订阅。
定期运行（推荐 60 秒间隔），扫描 timeout_at 已到达的活跃订阅，
按 timeout_action 执行对应超时处理逻辑。
Usage: python manage.py check_timeouts
"""
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
class Command(BaseCommand):
 help = "检查并处理超时的工作流事件订阅"
 def handle(self, *args: object, **options: object) -> None:
 now = timezone.now
 # 查询超时的活跃订阅（带 select_for_update 防竞态）
 with transaction.atomic:
 expired_subs = list(
 WorkflowEventSubscription.objects.select_for_update(skip_locked=True) # type: ignore[attr-defined]
 .filter(is_active=True, timeout_at__lte=now, timeout_at__isnull=False)
 .select_related("workflow_execution", "node_execution")
 .exclude(workflow_execution__is_debug=True)
 )
 processed = 0
 for sub in expired_subs:
 try:
 self._handle_timeout(sub)
 processed += 1
 except Exception:
 logger.exception("timeout_handle_error", subscription_id=str(sub.id))
 self.stdout.write(f"处理了 {processed} 个超时订阅")
 if processed > 0:
 logger.info("timeouts_processed", count=processed)
 def _handle_timeout(self, sub: WorkflowEventSubscription) -> None:
 """根据 timeout_action 处理单个超时订阅。"""
 action = sub.timeout_action
 node_exec = sub.node_execution
 wf_exec = sub.workflow_execution
 log = logger.bind(
 subscription_id=str(sub.id),
 node_execution_id=str(node_exec.id),
 workflow_execution_id=str(wf_exec.id),
 timeout_action=action,
 )
 if action == "fail":
 node_exec.status = NodeExecutionStatus.TIMEOUT
 node_exec.save(update_fields=["status"])
 wf_exec.status = ExecutionStatus.TIMEOUT
 wf_exec.completed_at = timezone.now
 wf_exec.error_message = f"节点 {node_exec.node_id} 等待事件超时"
 wf_exec.error_node_id = node_exec.node_id
 wf_exec.save(update_fields=["status", "completed_at", "error_message", "error_node_id"])
 log.info("timeout_fail")
 elif action == "skip":
 node_exec.status = NodeExecutionStatus.SKIPPED
 node_exec.save(update_fields=["status"])
 log.info("timeout_skip")
 elif action == "retry":
 # retry 的完整实现需要 WorkflowEngine 介入，
 # 当前标记为 timeout 并记录需要重试
 node_exec.status = NodeExecutionStatus.TIMEOUT
 node_exec.save(update_fields=["status"])
 log.warning("timeout_retry_not_implemented", fallback="fail")
 # 标记订阅为非活跃
 sub.mark_inactive
