"""飞书 IM API 客户端。
独立于 FeishuClient (Project API)，使用 tenant_access_token 认证。
用于发送群聊消息、卡片消息等 IM 功能。
"""
import base64
import hashlib
import json
import time
from dataclasses import dataclass, field
from typing import Any, Literal
import httpx
import structlog
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from tenacity import (
 retry,
 retry_if_exception_type,
 stop_after_attempt,
 wait_exponential,
)
from common.encryption import decrypt_value
from projects.models import Project
from system.models import SettingKeys, SystemSetting
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
 token = self._tenant_token
 assert token is not None
 return token
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
 raise RateLimitError(f"Rate limit exceeded: {data.get('msg', data)}", code=code)
 if code != 0:
 log.error("send_message_failed", response=data)
 raise FeishuIMError(f"发送消息失败: {data.get('msg', data)}", code=code)
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
 @staticmethod
 def verify_callback_signature(
 timestamp: str,
 nonce: str,
 body: str,
 signature: str,
 encrypt_key: str,
 ) -> bool:
 """验证卡片回调签名。
 飞书回调使用 SHA256(timestamp + nonce + encrypt_key + body) 签名。
 Args:
 timestamp: 请求头中的时间戳
 nonce: 请求头中的随机数
 body: 原始请求体
 signature: 请求头中的签名
 encrypt_key: 应用的 Encrypt Key
 Returns:
 签名是否有效
 """
 content = f"{timestamp}{nonce}{encrypt_key}{body}"
 computed = hashlib.sha256(content.encode("utf-8")).hexdigest
 return computed == signature
 @staticmethod
 def decrypt_callback(encrypt: str, encrypt_key: str) -> dict[str, Any]:
 """解密 -CBC 加密的回调内容。
 飞书使用 -CBC 加密回调内容，密钥为 SHA256(encrypt_key) 的前 32 字节。
 Args:
 encrypt: Base64 编码的加密内容
 encrypt_key: 应用的 Encrypt Key
 Returns:
 解密后的 JSON 数据
 Raises:
 ValueError: 解密失败
 """
 # 生成 AES 密钥: SHA256(encrypt_key) 取前 32 字节
 key = hashlib.sha256(encrypt_key.encode("utf-8")).digest
 # Base64 解码
 ciphertext = base64.b64decode(encrypt)
 # 前 16 字节是 IV
 iv = ciphertext[:16]
 encrypted_data = ciphertext[16:]
 # -CBC 解密
 cipher = Cipher(algorithms.AES(key), modes.CBC(iv))
 decryptor = cipher.decryptor
 decrypted = decryptor.update(encrypted_data) + decryptor.finalize
 # 去除 PKCS7 填充
 padding_len = decrypted[-1]
 decrypted = decrypted[:-padding_len]
 return json.loads(decrypted.decode("utf-8"))
 # ------------------------------------------------------------------
 # 群聊成员管理方法
 # ------------------------------------------------------------------
 async def get_chat_members(self, chat_id: str) -> list[dict[str, Any]]:
 """获取群聊成员列表。
 Args:
 chat_id: 群聊 ID
 Returns:
 成员列表，每项包含 member_id、name、tenant_key 等
 Raises:
 FeishuIMError: API 调用失败
 """
 token = await self.get_tenant_access_token
 log = logger.bind(chat_id=chat_id)
 async with httpx.AsyncClient as client:
 response = await client.get(
 f"{self.OPEN_API_BASE}/im/v1/chats/{chat_id}/members",
 params={"member_id_type": "app_id"},
 headers={"Authorization": f"Bearer {token}"},
 )
 data = response.json
 code = data.get("code", -1)
 if code != 0:
 log.error("get_chat_members_failed", response=data)
 raise FeishuIMError(
 f"获取群聊成员失败: {data.get('msg', data)}", code=code
 )
 items: list[dict[str, Any]] = data.get("data", {}).get("items", )
 log.info("chat_members_fetched", count=len(items))
 return items
 async def is_bot_in_chat(self, chat_id: str) -> bool:
 """检查当前 Bot 是否已在指定群聊中。
 通过查询群聊成员列表，检查 self.app_id 是否在其中。
 查询失败时降级返回 False。
 Args:
 chat_id: 群聊 ID
 Returns:
 Bot 在群聊中返回 True，否则返回 False
 """
 try:
 members = await self.get_chat_members(chat_id)
 return any(m.get("member_id") == self.app_id for m in members)
 except Exception:
 logger.warning("is_bot_in_chat_check_failed", chat_id=chat_id, exc_info=True)
 return False
 async def add_bot_to_chat(self, chat_id: str) -> dict[str, Any]:
 """将当前 Bot 加入指定群聊。
 Args:
 chat_id: 群聊 ID
 Returns:
 API 响应数据
 Raises:
 RateLimitError: 触发 rate limit
 FeishuIMError: API 调用失败
 """
 token = await self.get_tenant_access_token
 log = logger.bind(chat_id=chat_id, app_id=self.app_id)
 async with httpx.AsyncClient as client:
 response = await client.post(
 f"{self.OPEN_API_BASE}/im/v1/chats/{chat_id}/members",
 params={"member_id_type": "app_id"},
 headers={
 "Authorization": f"Bearer {token}",
 "Content-Type": "application/json",
 },
 json={"id_list": [self.app_id]},
 )
 data = response.json
 code = data.get("code", -1)
 if code == 99991400 or "rate limit" in str(data).lower:
 log.warning("rate_limit_hit", response=data)
 raise RateLimitError(
 f"Rate limit exceeded: {data.get('msg', data)}", code=code
 )
 if code != 0:
 log.error("add_bot_to_chat_failed", response=data)
 raise FeishuIMError(
 f"Bot 加入群聊失败: {data.get('msg', data)}", code=code
 )
 log.info("bot_added_to_chat")
 return data.get("data", {})
 async def ensure_bot_in_chat(self, chat_id: str) -> dict[str, Any]:
 """确保 Bot 在指定群聊中（幂等 + 降级）。
 先检查 Bot 是否已在群聊中，未在则尝试加入。
 加入失败时降级返回结构化错误而非抛异常。
 Args:
 chat_id: 群聊 ID
 Returns:
 结构化结果：
 - success: 是否成功（已在群内或成功加入）
 - already_member: Bot 是否已在群内
 - error: 失败时的错误信息，成功时为 None
 """
 log = logger.bind(chat_id=chat_id, app_id=self.app_id)
 # 先检查是否已在群内
 already = await self.is_bot_in_chat(chat_id)
 if already:
 log.info("bot_already_in_chat")
 return {"success": True, "already_member": True, "error": None}
 # 尝试加入
 try:
 await self.add_bot_to_chat(chat_id)
 log.info("bot_joined_chat")
 return {"success": True, "already_member": False, "error": None}
 except Exception as exc:
 log.warning("ensure_bot_in_chat_failed", error=str(exc))
 return {"success": False, "already_member": False, "error": str(exc)}
async def _aget_system_feishu_credentials -> tuple[str, str] | None:
 """Load system-level Feishu IM credentials if configured."""
 app_id_setting = await SystemSetting.objects.filter(key=SettingKeys.FEISHU_APP_ID).afirst
 app_secret_setting = await SystemSetting.objects.filter(key=SettingKeys.FEISHU_APP_SECRET).afirst
 if app_id_setting and app_secret_setting and app_id_setting.value and app_secret_setting.value:
 app_secret = (
 decrypt_value(app_secret_setting.value)
 if app_secret_setting.is_encrypted
 else app_secret_setting.value
 )
 return app_id_setting.value, app_secret
 return None
async def create_feishu_im_client_for_project(project: Project | None = None) -> FeishuIMClient:
 """Create a Feishu IM client from project config or system defaults."""
 if project and project.feishu_app_id and project.feishu_app_secret_encrypted:
 return FeishuIMClient(
 app_id=project.feishu_app_id,
 app_secret=decrypt_value(project.feishu_app_secret_encrypted),
 )
 credentials = await _aget_system_feishu_credentials
 if credentials:
 return FeishuIMClient(app_id=credentials[0], app_secret=credentials[1])
 fallback_project = await Project.objects.exclude(feishu_app_id__isnull=True).exclude(
 feishu_app_id=""
 ).exclude(feishu_app_secret_encrypted__isnull=True).exclude(
 feishu_app_secret_encrypted=""
 ).order_by("created_at").afirst
 if fallback_project:
 return FeishuIMClient(
 app_id=fallback_project.feishu_app_id or "",
 app_secret=decrypt_value(fallback_project.feishu_app_secret_encrypted or ""),
 )
 raise ValueError("未配置飞书 IM 集成。请先配置项目级或系统级飞书 App ID / App Secret。")
class FeishuIMService:
 """Convenience wrapper around `FeishuIMClient` for bot workflows."""
 def __init__(self, client: FeishuIMClient):
 self.client = client
 @classmethod
 async def create(cls, project: Project | None = None) -> "FeishuIMService":
 client = await create_feishu_im_client_for_project(project)
 return cls(client)
 async def send_card(
 self,
 receive_id: str,
 receive_id_type: Literal["chat_id", "open_id", "user_id"],
 card: dict[str, Any],
 ) -> str:
 return await self.client.send_card(receive_id=receive_id, receive_id_type=receive_id_type, card=card)
 async def update_card(self, message_id: str, card: dict[str, Any]) -> bool:
 return await self.client.update_card(message_id=message_id, card=card)
 async def ensure_bot_in_chat(self, chat_id: str) -> dict[str, Any]:
 """确保 Bot 在指定群聊中（委托给 client）。"""
 return await self.client.ensure_bot_in_chat(chat_id)
