"""WebSocket consumers for workflows app."""

import json
import time

import structlog
from channels.generic.websocket import AsyncWebsocketConsumer

from common.channel_groups import safe_group_add, safe_group_discard
from common.log_context import LogSource
from common.request_metrics import arecord_request_metric

logger = structlog.get_logger()


async def _record_ws_metric(
    *, route: str, event: str, connected_at: float | None = None
) -> None:
    """为 WS connect/disconnect 记一行 RequestMetric（best-effort，绝不影响握手/收发）。

    connect：status_code=101（协议切换），ws_event=connect；
    disconnect：duration_ms=连接时长（从 connect 时刻起算）、ws_event=disconnect。
    """
    try:
        duration_ms = (
            max(int((time.perf_counter() - connected_at) * 1000), 0)
            if connected_at is not None
            else None
        )
        await arecord_request_metric(
            source=LogSource.WS.value,
            route=route,
            method="WS",
            status_code=101,
            error_class="none",
            duration_ms=duration_ms,
            labels={"ws_event": event},
        )
    except Exception:  # noqa: BLE001 — WS 指标绝不反噬业务
        pass


class WorkflowExecutionConsumer(AsyncWebsocketConsumer):
    """Consumer for workflow execution updates.

    Clients connect to: /ws/workflow-executions/{execution_id}/
    """

    async def connect(self) -> None:
        self.execution_id = self.scope["url_route"]["kwargs"]["execution_id"]
        self.group_name = f"execution_{self.execution_id}"

        # Join execution group
        if not await safe_group_add(
            self.channel_layer,
            self.group_name,
            self.channel_name,
            component="workflows",
        ):
            await self.close(code=1013)
            return

        await self.accept()
        self._ws_connected_at = time.perf_counter()
        await _record_ws_metric(route="ws:workflow_execution", event="connect")

    async def disconnect(self, close_code: int) -> None:
        await _record_ws_metric(
            route="ws:workflow_execution",
            event="disconnect",
            connected_at=getattr(self, "_ws_connected_at", None),
        )
        # Leave execution group
        await safe_group_discard(
            self.channel_layer,
            self.group_name,
            self.channel_name,
            component="workflows",
        )

        # 调试会话清理：WS 断线时释放暂停并标记取消
        from workflows.engine.scheduler import _debug_sessions

        session = _debug_sessions.pop(self.execution_id, None)
        if session:
            session.debug_action = "cancel"
            session.loop.call_soon_threadsafe(session.event.set)
            logger.info("debug_session_ws_disconnect_cleanup", execution_id=self.execution_id)

    async def receive(self, text_data: str) -> None:
        """处理前端调试控制命令。"""
        data = json.loads(text_data)
        msg_type = data.get("type")

        if msg_type == "debug_action":
            action = data.get("action")
            if action not in ("release", "skip", "mock"):
                await self.send(
                    text_data=json.dumps(
                        {
                            "type": "error",
                            "message": f"未知调试操作: {action}",
                        }
                    )
                )
                return

            from workflows.engine.scheduler import WorkflowEngine

            success = WorkflowEngine.release_debug_node(
                execution_id=self.execution_id,
                action=action,
                action_data=data.get("data", {}),
            )

            if not success:
                await self.send(
                    text_data=json.dumps(
                        {
                            "type": "error",
                            "message": "调试会话不存在或已结束",
                        }
                    )
                )
            else:
                await self.send(
                    text_data=json.dumps(
                        {
                            "type": "debug_action_ack",
                            "action": action,
                        }
                    )
                )

        elif msg_type == "set_breakpoint":
            await self._handle_breakpoint(data, action="set")

        elif msg_type == "remove_breakpoint":
            await self._handle_breakpoint(data, action="remove")

        elif msg_type == "set_debug_mode":
            await self._handle_debug_mode(data)

    async def _handle_breakpoint(self, data: dict, action: str) -> None:
        """处理断点设置/取消消息。"""
        node_id = data.get("node_id")
        if not node_id:
            await self.send(
                text_data=json.dumps(
                    {
                        "type": "error",
                        "message": "缺少 node_id",
                    }
                )
            )
            return

        from workflows.engine.scheduler import _debug_sessions

        session = _debug_sessions.get(self.execution_id)
        if not session:
            await self.send(
                text_data=json.dumps(
                    {
                        "type": "error",
                        "message": "调试会话不存在",
                    }
                )
            )
            return

        if action == "set":
            session.breakpoints.add(node_id)
        else:
            session.breakpoints.discard(node_id)

        await self.send(
            text_data=json.dumps(
                {
                    "type": "breakpoint_ack",
                    "action": action,
                    "node_id": node_id,
                }
            )
        )
        logger.info(
            "debug_breakpoint_updated",
            execution_id=self.execution_id,
            node_id=node_id,
            action=action,
        )

    async def _handle_debug_mode(self, data: dict) -> None:
        """处理调试模式切换消息。"""
        mode = data.get("mode")
        if mode not in ("step", "breakpoint"):
            await self.send(
                text_data=json.dumps(
                    {
                        "type": "error",
                        "message": f"无效调试模式: {mode}",
                    }
                )
            )
            return

        from workflows.engine.scheduler import WorkflowEngine, _debug_sessions

        session = _debug_sessions.get(self.execution_id)
        if not session:
            await self.send(
                text_data=json.dumps(
                    {
                        "type": "error",
                        "message": "调试会话不存在",
                    }
                )
            )
            return

        old_mode = session.debug_mode
        session.debug_mode = mode

        # 切换到断点模式且当前暂停在非断点节点时自动放行
        if mode == "breakpoint" and old_mode == "step":
            if (
                session.current_node_id
                and session.current_node_id not in session.breakpoints
                and not session.event.is_set()
            ):
                WorkflowEngine.release_debug_node(
                    self.execution_id,
                    action="release",
                )
                logger.info(
                    "debug_mode_switch_auto_release",
                    execution_id=self.execution_id,
                    node_id=session.current_node_id,
                )

        await self.send(
            text_data=json.dumps(
                {
                    "type": "debug_mode_ack",
                    "mode": mode,
                }
            )
        )
        logger.info(
            "debug_mode_switched",
            execution_id=self.execution_id,
            old_mode=old_mode,
            new_mode=mode,
        )

    async def workflow_event(self, event: dict) -> None:
        """Handle workflow event message from group."""
        # Send message to WebSocket
        await self.send(text_data=json.dumps(event))
