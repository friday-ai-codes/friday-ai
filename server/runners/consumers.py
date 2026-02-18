"""Runner WebSocket consumer。"""
import structlog
from channels.db import database_sync_to_async
from channels.generic.websocket import AsyncJsonWebsocketConsumer
from django.db import close_old_connections
from django.utils import timezone
logger = structlog.get_logger
_close_old_connections = database_sync_to_async(close_old_connections)
class RunnerConsumer(AsyncJsonWebsocketConsumer):
 """处理 Runner WS 连接，按 type 分发消息到 handler。"""
 _handlers: dict[str, str] = {
 "runner.hello": "_handle_hello",
 "runner.heartbeat": "_handle_heartbeat",
 "task.accepted": "_handle_task_accepted",
 }
 async def connect(self):
 runner = self.scope.get("runner")
 if not runner:
 await self.close(code=4001)
 return
 self.runner = runner
 self.group_name = f"runner_{runner.id}"
 # 踢旧连接
 if runner.channel_name:
 await self.channel_layer.send(
 runner.channel_name, {"type": "force.disconnect"}
 )
 await self.channel_layer.group_add(self.group_name, self.channel_name)
 await self.accept
 await self._update_channel_name(self.channel_name)
 async def disconnect(self, close_code):
 if hasattr(self, "group_name"):
 await self.channel_layer.group_discard(self.group_name, self.channel_name)
 if hasattr(self, "runner") and close_code != 4002:
 await self._mark_offline
 async def receive_json(self, content, **kwargs):
 msg_type = content.get("type")
 handler_name = self._handlers.get(msg_type) if msg_type else None
 if handler_name:
 await getattr(self, handler_name)(content)
 else:
 logger.warning("unknown_message_type", type=msg_type)
 async def _handle_hello(self, content):
 payload = content.get("payload", {})
 await _close_old_connections
 await database_sync_to_async(self._sync_update_hello)(payload)
 async def _handle_heartbeat(self, content):
 payload = content.get("payload", {})
 await _close_old_connections
 await database_sync_to_async(self._sync_update_heartbeat)(payload)
 async def _handle_task_accepted(self, content):
 logger.info("task_accepted", runner=str(self.runner.id), payload=content.get("payload"))
 async def runner_message(self, event):
 """Channel layer 事件：向 Runner 发送消息。"""
 await self.send_json(event["message"])
 async def force_disconnect(self, event):
 """收到踢连接指令。"""
 await self.close(code=4002)
 # -- sync ORM helpers (called via database_sync_to_async) --
 def _sync_update_hello(self, payload: dict):
 r = self.runner
 r.status = "online"
 r.version = payload.get("version", "")
 r.save(update_fields=["status", "version", "updated_at"])
 def _sync_update_heartbeat(self, payload: dict):
 r = self.runner
 r.status = "online"
 r.last_heartbeat = timezone.now
 r.save(update_fields=["status", "last_heartbeat", "updated_at"])
 async def _update_channel_name(self, channel_name: str):
 await _close_old_connections
 @database_sync_to_async
 def _save:
 self.runner.channel_name = channel_name
 self.runner.save(update_fields=["channel_name", "updated_at"])
 await _save
 async def _mark_offline(self):
 await _close_old_connections
 @database_sync_to_async
 def _save:
 self.runner.status = "offline"
 self.runner.channel_name = ""
 self.runner.save(update_fields=["status", "channel_name", "updated_at"])
 await _save
