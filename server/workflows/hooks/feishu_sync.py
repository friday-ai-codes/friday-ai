"""Feishu synchronization hook for workflow events.

Sends workflow status updates to Feishu via card notifications.
Implements exponential backoff retry (3 attempts, 1s -> 2s -> 4s)
with graceful degradation on complete failure.
"""

import asyncio
from typing import Any

import structlog

from core.feature_flags import feature_flags
from workflows.hooks.base import BaseHook

logger = structlog.get_logger()

# 重试配置
MAX_RETRIES = 3
BASE_DELAY = 1.0  # 指数退避基础延迟（秒）


class FeishuSyncHook(BaseHook):
    """Hook to synchronize workflow status to Feishu.

    Sends card notifications when workflow nodes change state,
    providing real-time visibility into execution progress.
    Uses exponential backoff retry with graceful degradation.
    """

    name = "feishu_sync"

    async def on_node_started(self, execution: Any, node_execution: Any, **kwargs: Any) -> None:
        """Send notification when node starts."""
        if not feature_flags.sync_workflow_to_feishu:
            return

        await self._send_notification(
            execution,
            content=f"开始执行: {node_execution.node.name}",
            color="blue",
        )

    async def on_node_completed(self, execution: Any, node_execution: Any, **kwargs: Any) -> None:
        """Send notification when node completes."""
        if not feature_flags.sync_workflow_to_feishu:
            return

        await self._send_notification(
            execution,
            content=f"完成: {node_execution.node.name}",
            color="green",
        )

    async def on_node_failed(self, execution: Any, node_execution: Any, **kwargs: Any) -> None:
        """Send notification when node fails."""
        if not feature_flags.sync_workflow_to_feishu:
            return

        error_msg = node_execution.error_message or "未知错误"
        await self._send_notification(
            execution,
            content=f"失败: {node_execution.node.name}\n错误: {error_msg[:200]}",
            color="red",
        )

    async def on_node_waiting_approval(self, execution: Any, node_execution: Any, **kwargs: Any) -> None:
        """Send approval request notification."""
        if not feature_flags.sync_workflow_to_feishu:
            return

        config = node_execution.node.config or {}
        description = config.get("description_template", "请审批")

        await self._send_notification(
            execution,
            content=(
                f"等待审批: {node_execution.node.name}\n\n"
                f"{description}\n\n"
                "回复「通过」或「驳回」进行审批"
            ),
            color="orange",
        )

    async def execute(self, event: str, **kwargs: Any) -> None:
        """Execute hook by routing to the appropriate on_* handler."""
        # 调试执行不触发飞书推送
        execution = kwargs.get("execution")
        if execution and getattr(execution, "is_debug", False):
            return

        event_map = {
            "node_started": self.on_node_started,
            "node_completed": self.on_node_completed,
            "node_failed": self.on_node_failed,
            "node_waiting_approval": self.on_node_waiting_approval,
            "execution_completed": self.on_execution_completed,
            "execution_failed": self.on_execution_failed,
        }
        handler = event_map.get(event)
        if handler:
            await handler(**kwargs)  # type: ignore[operator]

    async def on_execution_completed(self, execution: Any, **kwargs: Any) -> None:
        """Send completion notification."""
        if not feature_flags.sync_workflow_to_feishu:
            return

        await self._send_notification(
            execution,
            content="工作流执行完成!",
            color="green",
        )

    async def on_execution_failed(self, execution: Any, **kwargs: Any) -> None:
        """Send failure notification."""
        if not feature_flags.sync_workflow_to_feishu:
            return

        error_msg = execution.error_message or "未知错误"
        await self._send_notification(
            execution,
            content=f"工作流执行失败\n错误: {error_msg[:500]}",
            color="red",
        )

    def _get_chat_id(self, execution: Any) -> str | None:
        """Extract chat_id from execution context or input_data."""
        context = execution.context or {}
        chat_id = context.get("chat_id")
        if not chat_id:
            input_data = execution.input_data or {}
            chat_id = input_data.get("chat_id")
        return chat_id

    def _get_work_item_id(self, execution: Any) -> str | None:
        """Extract work_item_id from execution context."""
        context = execution.context or {}
        work_item_id = context.get("work_item_id")
        if not work_item_id:
            input_data = execution.input_data or {}
            work_item_id = input_data.get("work_item_id")
        return work_item_id

    @staticmethod
    def _build_status_card(content: str, *, color: str = "blue") -> dict[str, Any]:
        """构建通用状态通知卡片。"""
        return {
            "config": {"wide_screen_mode": True},
            "header": {
                "title": {"tag": "plain_text", "content": "工作流通知"},
                "template": color,
            },
            "elements": [
                {
                    "tag": "markdown",
                    "content": content,
                },
            ],
        }

    async def _send_notification(
        self,
        execution: Any,
        content: str,
        *,
        color: str = "blue",
    ) -> None:
        """发送飞书通知（带重试和降级）。

        指数退避重试：3 次重试，间隔 1s -> 2s -> 4s。
        全部失败后降级记录 ERROR 日志，不阻塞工作流执行。
        """
        chat_id = self._get_chat_id(execution)
        if not chat_id:
            logger.debug(
                "feishu_sync_no_chat_id",
                execution_id=str(execution.id),
                content=content[:100],
            )
            return

        project = execution.workflow.space if hasattr(execution, "workflow") and execution.workflow else None

        for attempt in range(MAX_RETRIES):
            try:
                from services.feishu_im import FeishuIMService

                im_service = await FeishuIMService.create(project)
                card = self._build_status_card(content, color=color)
                await im_service.send_card(
                    receive_id=chat_id,
                    receive_id_type="chat_id",
                    card=card,
                )
                logger.info(
                    "feishu_notification_sent",
                    execution_id=str(execution.id),
                    attempt=attempt + 1,
                )
                return
            except Exception as exc:
                delay = BASE_DELAY * (2 ** attempt)  # 1s, 2s, 4s
                logger.warning(
                    "feishu_notification_retry",
                    execution_id=str(execution.id),
                    attempt=attempt + 1,
                    max_retries=MAX_RETRIES,
                    delay=delay,
                    error=str(exc),
                )
                if attempt < MAX_RETRIES - 1:
                    await asyncio.sleep(delay)

        # 全部重试失败 — 降级：记录 ERROR 日志，不阻塞工作流
        logger.error(
            "feishu_notification_failed_all_retries",
            execution_id=str(execution.id),
            content=content[:200],
        )
