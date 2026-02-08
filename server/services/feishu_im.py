"""飞书 IM API 客户端。
独立于 FeishuClient (Project API)，使用 tenant_access_token 认证。
用于发送群聊消息、卡片消息等 IM 功能。
"""
import json
import time
from dataclasses import dataclass, field
from typing import Any, Literal
import httpx
import structlog
from tenacity import (
 retry,
 retry_if_exception_type,
 stop_after_attempt,
 wait_exponential,
)
logger = structlog.get_logger(__name__)
class FeishuIMError(Exception):
 """飞书 IM API 错误基类。"""
 def __init__(self, message: str, code: int | None = None) -> None:
 super.__init__(message)
 self.code = code
class RateLimitError(FeishuIMError):
 """Rate limit 错误，需要等待后重试。"""
 pass
@dataclass
class CardTemplate:
 """飞书卡片消息模板。
 支持 Markdown 内容和交互按钮。
 Attributes:
 title: 卡片标题
 content: 卡片内容（Markdown 格式）
 buttons: 按钮列表，每个按钮包含 text, value, type
 color: 卡片主题色（blue, green, orange, red）
 """
 title: str
 content: str
 buttons: list[dict[str, Any]] = field(default_factory=list)
 color: Literal["blue", "green", "orange", "red"] = "blue"
 def to_card_json(self) -> dict[str, Any]:
 """生成飞书卡片 JSON 结构。
 Returns:
 符合飞书卡片 2.0 规范的 JSON 结构
 """
 elements: list[dict[str, Any]] = [
 {
 "tag": "markdown",
 "content": self.content,
 }
 ]
 if self.buttons:
 actions: list[dict[str, Any]] =
 for btn in self.buttons:
 button_type = btn.get("type", "default")
 actions.append(
 {
 "tag": "button",
 "text": {"tag": "plain_text", "content": btn["text"]},
 "type": button_type,
 "value": {"action": btn.get("value", btn["text"])},
 }
 )
 elements.append({"tag": "action", "actions": actions})
 return {
 "config": {"wide_screen_mode": True},
 "header": {
 "title": {"tag": "plain_text", "content": self.title},
 "template": self.color,
 },
 "elements": elements,
 }
class FeishuIMClient:
 """飞书 IM API 客户端，使用 tenant_access_token 认证。
 与 FeishuClient (Project API) 独立，因为两者使用不同的认证机制：
 - Project API: plugin_token
 - IM API: tenant_access_token (本客户端)
 Example:
 client = FeishuIMClient(app_id="cli_xxx", app_secret="xxx")
 message_id = await client.send_card(
 receive_id="oc_xxx",
 receive_id_type="chat_id",
 card=CardTemplate(title="通知", content="Hello").to_card_json,
 )
 """
 OPEN_API_BASE = "https://open.feishu.cn/open-apis"
 def __init__(self, app_id: str, app_secret: str) -> None:
 """初始化飞书 IM 客户端。
 Args:
 app_id: 飞书应用的 App ID
 app_secret: 飞书应用的 App Secret
 """
 self.app_id = app_id
 self.app_secret = app_secret
 self._tenant_token: str | None = None
 self._token_expires_at: float = 0
 async def get_tenant_access_token(self) -> str:
 """获取 tenant_access_token（带缓存，2小时有效）。
 Token 会在过期前 5 分钟自动刷新。
 Returns:
 有效的 tenant_access_token
 Raises:
 FeishuIMError: 获取 token 失败时抛出
 """
 now = time.time
 if self._tenant_token and now < self._token_expires_at:
 return self._tenant_token
 log = logger.bind(app_id=self.app_id)
 async with httpx.AsyncClient as client:
 response = await client.post(
 f"{self.OPEN_API_BASE}/auth/v3/tenant_access_token/internal",
 json={
 "app_id": self.app_id,
 "app_secret": self.app_secret,
 },
 )
 data = response.json
 if data.get("code") != 0:
 log.error("tenant_token_failed", response=data)
 raise FeishuIMError(
 f"获取 tenant_access_token 失败: {data.get('msg', data)}",
 code=data.get("code"),
 )
 self._tenant_token = data["tenant_access_token"]
 # Token 有效期 2 小时，提前 5 分钟刷新
 self._token_expires_at = now + data.get("expire", 7200) - 300
 log.info("tenant_token_refreshed", expires_in=data.get("expire", 7200))
 return self._tenant_token
 async def send_message(
 self,
 receive_id: str,
 receive_id_type: Literal["chat_id", "open_id", "user_id"],
 msg_type: str,
 content: dict[str, Any],
 ) -> dict[str, Any]:
 """发送消息。
 Args:
 receive_id: 接收者 ID（群聊 ID、用户 open_id 或 user_id）
 receive_id_type: ID 类型（chat_id, open_id, user_id）
 msg_type: 消息类型（text, interactive 等）
 content: 消息内容
 Returns:
 API 响应数据，包含 message_id 等
 Raises:
 FeishuIMError: API 调用失败
 RateLimitError: 触发 rate limit
 """
 token = await self.get_tenant_access_token
 log = logger.bind(
 receive_id=receive_id,
 receive_id_type=receive_id_type,
 msg_type=msg_type,
 )
 async with httpx.AsyncClient as client:
 response = await client.post(
 f"{self.OPEN_API_BASE}/im/v1/messages",
 params={"receive_id_type": receive_id_type},
 headers={
 "Authorization": f"Bearer {token}",
 "Content-Type": "application/json",
 },
 json={
 "receive_id": receive_id,
 "msg_type": msg_type,
 "content": json.dumps(content, ensure_ascii=False),
 },
 )
 data = response.json
 code = data.get("code", -1)
 # Handle rate limit
 if code == 99991400 or "rate limit" in str(data).lower:
 log.warning("rate_limit_hit", response=data)
 raise RateLimitError(
 f"Rate limit exceeded: {data.get('msg', data)}", code=code
 )
 if code != 0:
 log.error("send_message_failed", response=data)
 raise FeishuIMError(
 f"发送消息失败: {data.get('msg', data)}", code=code
 )
 message_id = data.get("data", {}).get("message_id", "")
 log.info("message_sent", message_id=message_id)
 return data.get("data", {})
 @retry(
 stop=stop_after_attempt(3),
 wait=wait_exponential(multiplier=1, min=4, max=60),
 retry=retry_if_exception_type(RateLimitError),
 reraise=True,
 )
 async def send_card(
 self,
 receive_id: str,
 receive_id_type: Literal["chat_id", "open_id", "user_id"],
 card: dict[str, Any],
 ) -> str:
 """发送卡片消息（带自动重试）。
 自动处理 rate limit，使用指数退避重试。
 Args:
 receive_id: 接收者 ID
 receive_id_type: ID 类型（chat_id, open_id, user_id）
 card: 卡片 JSON 结构（可使用 CardTemplate.to_card_json 生成）
 Returns:
 message_id: 消息 ID，可用于后续更新卡片
 Raises:
 FeishuIMError: API 调用失败
 """
 result = await self.send_message(
 receive_id=receive_id,
 receive_id_type=receive_id_type,
 msg_type="interactive",
 content=card,
 )
 return result.get("message_id", "")
 async def update_card(
 self,
 message_id: str,
 card: dict[str, Any],
 ) -> bool:
 """更新已发送的卡片消息。
 注意：卡片更新有效期为 14 天。
 Args:
 message_id: 要更新的消息 ID
 card: 新的卡片 JSON 结构
 Returns:
 更新是否成功
 """
 token = await self.get_tenant_access_token
 log = logger.bind(message_id=message_id)
 async with httpx.AsyncClient as client:
 response = await client.patch(
 f"{self.OPEN_API_BASE}/im/v1/messages/{message_id}",
 headers={
 "Authorization": f"Bearer {token}",
 "Content-Type": "application/json",
 },
 json={
 "msg_type": "interactive",
 "content": json.dumps(card, ensure_ascii=False),
 },
 )
 data = response.json
 if data.get("code") == 0:
 log.info("card_updated")
 return True
 else:
 log.warning("card_update_failed", response=data)
 return False
