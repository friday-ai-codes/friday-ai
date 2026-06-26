"""Feishu WebSocket Long Connection Client.

Provides a long-lived WebSocket connection to receive Feishu events
without requiring a public domain or webhook configuration.

This module supports two modes:
1. Standalone: python manage.py run_feishu_client --project-id <uuid>
2. Auto-start: Starts automatically with Django when configured

Features:
- Receives IM messages (user replies to bot)
- Receives card action callbacks (button clicks, form submissions)
- Auto-reconnect on connection loss
- Forwards events to existing Django handlers
"""

import asyncio
import threading
from typing import Any

import lark_oapi as lark
import structlog
from asgiref.sync import async_to_sync
from lark_oapi.ws import Client as WsClient

logger = structlog.get_logger(__name__)

# Global client manager for auto-start mode
_client_manager: "FeishuClientManager | None" = None


class FeishuWebSocketClient:
    """Feishu WebSocket client for receiving events via long connection.

    This client establishes a persistent WebSocket connection to Feishu servers
    to receive events without needing a public webhook endpoint.
    """

    def __init__(
        self,
        app_id: str,
        app_secret: str,
        project_id: str | None = None,
        log_level: int = lark.LogLevel.INFO,
    ):
        """Initialize the WebSocket client.

        Args:
            app_id: Feishu app ID (cli_xxx format)
            app_secret: Feishu app secret
            project_id: Optional Friday project ID for context
            log_level: Lark SDK log level
        """
        self.app_id = app_id
        self.app_secret = app_secret
        self.space_id = project_id
        self._client: WsClient | None = None
        self._running = False

        # Build event dispatcher
        self._event_handler = self._build_event_handler()

        # Create Lark client
        self._lark_client = (
            lark.Client.builder().app_id(app_id).app_secret(app_secret).log_level(log_level).build()
        )

    def _build_event_handler(self) -> lark.EventDispatcherHandler:
        """Build event dispatcher with registered handlers.

        # [ASSUMED] A2: WS 长连是否支持 register_p2_drive_file_edit_v1 待 live 验证。SDK 暂
        # 不确定有此注册器，故 drive.file.edit_v1 仅经 HTTP webhook 入口路由（FeishuWebhookView
        # ._handle_drive_file_edit），WS 长连不订阅 drive 事件；live 验证可用后再在此注册。
        """
        handler = (
            lark.EventDispatcherHandler.builder("", "")
            .register_p2_im_message_receive_v1(self._handle_message_receive)
            .register_p2_card_action_trigger(self._handle_card_action)
            .build()
        )
        return handler

    def _handle_message_receive(self, data) -> None:
        """Handle incoming IM message events.

        Called when a user sends a message to the bot (private or group mention).
        """
        try:
            event_data = data.event
            if not event_data:
                return

            message = event_data.message
            sender = event_data.sender

            logger.info(
                "ws_message_received",
                message_id=message.message_id if message else None,
                chat_id=message.chat_id if message else None,
                sender_id=sender.sender_id.open_id if sender and sender.sender_id else None,
                message_type=message.message_type if message else None,
            )

            # Forward to existing handler
            self._process_message_sync(data)

        except Exception as e:
            logger.error("ws_message_handle_error", error=str(e))

    @staticmethod
    def _log_dispatch_task_result(task: asyncio.Task[object]) -> None:
        try:
            task.result()
        except Exception as exc:
            logger.error("ws_message_dispatch_task_error", error=str(exc))

    def _handle_card_action(self, data):
        """Handle card action events (button clicks, form submissions).

        Called when a user interacts with a card (clicks button, submits form).
        Must return P2CardActionTriggerResponse within 3 seconds.
        """
        from lark_oapi.event.callback.model.p2_card_action_trigger import (
            CallBackCard,
            P2CardActionTriggerResponse,
        )

        try:
            event_data = data.event
            if not event_data:
                return P2CardActionTriggerResponse()

            action = event_data.action
            operator = event_data.operator

            logger.info(
                "ws_card_action_received",
                action_value=action.value if action else None,
                operator_id=operator.open_id if operator else None,
                token=event_data.token,
            )

            # Forward to existing card callback handler
            card_json = self._process_card_action_sync(data)

            resp = P2CardActionTriggerResponse()
            if card_json:
                card = CallBackCard()
                card.type = "raw"
                card.data = card_json
                resp.card = card
            return resp

        except Exception as e:
            logger.error("ws_card_action_handle_error", error=str(e))
            return P2CardActionTriggerResponse()

    def _process_message_sync(self, data) -> None:
        """Process received message synchronously.

        Forwards the message to the shared dispatcher used by webhook mode.
        """
        from feishu.bot.dispatcher import dispatch_inbound_message
        from feishu.bot.parser import normalize_im_message

        event_data = data.event
        if not event_data or not event_data.message:
            return

        message = event_data.message
        sender = event_data.sender

        raw_payload = {
            "header": {
                "event_type": "im.message.receive_v1",
                "event_id": getattr(getattr(data, "header", None), "event_id", ""),
            },
            "event": {
                "message": {
                    "chat_id": message.chat_id,
                    "chat_type": getattr(message, "chat_type", ""),
                    "message_id": message.message_id,
                    "message_type": message.message_type,
                    "content": message.content or "{}",
                    "mentions": getattr(message, "mentions", []) or [],
                    "parent_id": getattr(message, "parent_id", ""),
                    "root_id": getattr(message, "root_id", ""),
                },
                "sender": {
                    "sender_id": {
                        "open_id": sender.sender_id.open_id if sender and sender.sender_id else "",
                    },
                    "sender_type": getattr(sender, "sender_type", ""),
                },
            },
        }
        normalized_message = normalize_im_message(raw_payload)

        logger.info(
            "ws_im_message_processed",
            message_id=message.message_id,
            chat_id=message.chat_id,
            chat_type=message.chat_type,
            message_type=message.message_type,
            text_preview=normalized_message.normalized_text[:50] if normalized_message.normalized_text else None,
            sender_id=sender.sender_id.open_id if sender and sender.sender_id else None,
        )

        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            async_to_sync(dispatch_inbound_message)(normalized_message)
            return

        task = loop.create_task(dispatch_inbound_message(normalized_message))
        task.add_done_callback(self._log_dispatch_task_result)

    def _process_card_action_sync(self, data) -> dict[str, Any] | None:
        """Process card action synchronously (must return within 3s).

        Forwards to existing CardCallbackView logic.
        """
        from feishu.views import (
            CardCallback,
            _card_callback_handlers,
        )

        event_data = data.event
        if not event_data:
            return None

        action = event_data.action
        operator = event_data.operator
        context = event_data.context

        # Build CardCallback object compatible with existing handlers
        # Pass the full value dict (same as CardCallbackView in views.py)
        action_value_dict: dict[str, Any] | str = ""
        action_name = ""
        if action and action.value:
            if isinstance(action.value, dict):
                action_value_dict = action.value
                action_name = action.value.get("action", "")
                # For form submissions, merge form_value into the dict
                # so handlers can extract user input (e.g. custom_answer)
                form_value = getattr(action, "form_value", None)
                if form_value and isinstance(form_value, dict):
                    action_value_dict = {**action.value, **form_value}
            else:
                action_value_dict = str(action.value)
                action_name = str(action.value)

        callback = CardCallback(
            action_value=action_value_dict,
            message_id=context.open_message_id if context else "",
            user_open_id=operator.open_id if operator else "",
            chat_id=context.open_chat_id if context else "",
            tenant_key=operator.tenant_key if operator else "",
        )

        logger.info(
            "ws_card_callback_dispatching",
            action_value=action_name,
            message_id=callback.message_id,
            user_open_id=callback.user_open_id,
        )

        # Dispatch to registered handlers
        for prefix, handler in _card_callback_handlers.items():
            if action_name.startswith(prefix):
                try:
                    result = handler(callback)
                    logger.info(
                        "ws_card_callback_handled",
                        prefix=prefix,
                        has_result=result is not None,
                    )
                    return result
                except Exception as e:
                    logger.error(
                        "ws_card_callback_handler_error",
                        prefix=prefix,
                        error=str(e),
                    )
                    return None

        logger.warning(
            "ws_card_callback_no_handler",
            action_value=action_name,
        )
        return None

    def start(self) -> None:
        """Start the WebSocket client (blocking).

        This method blocks and runs until stopped or connection fails.
        """
        logger.info(
            "ws_client_starting",
            app_id=self.app_id,
            project_id=self.space_id,
        )

        self._running = True

        # Create WebSocket client
        self._client = WsClient(
            app_id=self.app_id,
            app_secret=self.app_secret,
            event_handler=self._event_handler,
            log_level=lark.LogLevel.WARNING,
        )

        # Start (blocking)
        try:
            self._client.start()
        except KeyboardInterrupt:
            logger.info("ws_client_interrupted")
        except Exception as e:
            logger.error("ws_client_error", error=str(e))
            raise
        finally:
            self._running = False

    def stop(self) -> None:
        """Stop the WebSocket client."""
        logger.info("ws_client_stopping")
        self._running = False


class FeishuClientManager:
    """Manager for auto-starting Feishu WebSocket client.

    Starts a single client using global system settings.
    """

    def __init__(self):
        self._client: FeishuWebSocketClient | None = None
        self._thread: threading.Thread | None = None
        self._running = False

    def start_all(self) -> None:
        """Start WebSocket client if Feishu IM is configured in system settings."""
        from common.encryption import decrypt_value
        from system.models import SettingKeys, SystemSetting

        self._running = True

        # Get global Feishu IM config from system settings
        try:
            app_id_setting = SystemSetting.objects.filter(key=SettingKeys.FEISHU_APP_ID).first()
            app_secret_setting = SystemSetting.objects.filter(
                key=SettingKeys.FEISHU_APP_SECRET
            ).first()

            if not app_id_setting or not app_id_setting.value:
                logger.info("ws_manager_skipped", reason="feishu_app_id not configured")
                return

            if not app_secret_setting or not app_secret_setting.value:
                logger.info("ws_manager_skipped", reason="feishu_app_secret not configured")
                return

            app_id = app_id_setting.value
            app_secret = app_secret_setting.value
            if app_secret_setting.is_encrypted:
                app_secret = decrypt_value(app_secret)

            self._start_client(app_id, app_secret)

        except Exception as e:
            logger.error("ws_client_start_failed", error=str(e))

    def _start_client(self, app_id: str, app_secret: str) -> None:
        """Start the WebSocket client."""
        if self._client is not None:
            return  # Already running

        client = FeishuWebSocketClient(
            app_id=app_id,
            app_secret=app_secret,
            log_level=lark.LogLevel.WARNING,  # Reduce noise in auto-start mode
        )

        self._client = client

        # Start in background thread
        thread = threading.Thread(
            target=client.start,
            name="feishu-ws-global",
            daemon=True,  # Die with main process
        )
        thread.start()
        self._thread = thread

        logger.info(
            "ws_client_started",
            app_id=app_id,
        )

    def stop_all(self) -> None:
        """Stop the WebSocket client."""
        self._running = False
        if self._client:
            try:
                self._client.stop()
            except Exception as e:
                logger.error("ws_client_stop_failed", error=str(e))
        self._client = None
        self._thread = None
        logger.info("ws_manager_stopped")

    def refresh(self) -> None:
        """Refresh client - restart if config changed."""
        self.stop_all()
        self.start_all()


def get_client_manager() -> FeishuClientManager:
    """Get the global client manager, creating if needed."""
    global _client_manager
    if _client_manager is None:
        _client_manager = FeishuClientManager()
    return _client_manager


def auto_start_clients() -> None:
    """Auto-start Feishu WebSocket clients for all configured projects.

    Call this from Django's AppConfig.ready() to start on server boot.
    """
    manager = get_client_manager()
    manager.start_all()


def create_client_for_project(project_id: str) -> FeishuWebSocketClient:
    """Create a WebSocket client for a specific project.

    Args:
        project_id: Friday project UUID

    Returns:
        Configured FeishuWebSocketClient

    Raises:
        ValueError: If project doesn't have Feishu IM configured
    """
    from django.core.exceptions import ObjectDoesNotExist

    from common.encryption import decrypt_value
    from projects.models import Space

    try:
        project = Space.objects.get(id=project_id)
    except ObjectDoesNotExist:
        raise ValueError(f"Space not found: {project_id}")

    # Check for Feishu IM config
    if not project.has_feishu_im_config():
        raise ValueError(
            f"Space {project_id} does not have Feishu IM configured. "
            "Please configure App ID and App Secret in project settings."
        )

    app_id = project.feishu_app_id
    app_secret = decrypt_value(project.feishu_app_secret_encrypted)

    return FeishuWebSocketClient(
        app_id=app_id,
        app_secret=app_secret,
        project_id=project_id,
    )
