"""飞书 IM API 客户端。

独立于 FeishuClient (Space API)，使用 tenant_access_token 认证。
用于发送群聊消息、卡片消息等 IM 功能。
"""

import base64
import hashlib
import json
import re
import time
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Literal

import structlog
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from common.encryption import decrypt_value
from projects.models import Space
from services.feishu_http import feishu_client
from system.models import SettingKeys, SystemSetting

if TYPE_CHECKING:
    from services.feishu import FeishuClient

logger = structlog.get_logger(__name__)

# 飞书群聊 open_chat_id 格式：oc_ + 字母数字。用于校验工作项字段里取出的值
# 确实是群 ID，过滤掉 group_type="disabled" 这类非群 ID 的同名前缀字段误命中。
_OPEN_CHAT_ID_RE = re.compile(r"oc_[A-Za-z0-9]+")

# 工作项里承载群聊 ID 的语义字段（优先级从高到低），早于 key 名模糊匹配。
# chat_group 为飞书项目新群组字段（文档标注"推荐使用"）优先，group_id 旧字段兜底。
_CHAT_FIELD_PRIORITY = ("chat_group", "group_id", "chat_id")


def _coerce_chat_meta(value: Any) -> tuple[str | None, str | None, str | None]:
    """从字段值中提取 (chat_id, chat_name, owner_id) 候选，支持 str/dict/list。

    仅做"取候选字符串"，不做格式校验（oc_ 校验由调用方统一执行）。
    """
    if isinstance(value, str):
        return value, None, None
    if isinstance(value, dict):
        return (
            value.get("chat_id") or value.get("group_id") or value.get("id"),
            value.get("chat_name") or value.get("name"),
            value.get("owner_id"),
        )
    if isinstance(value, list) and value:
        first = value[0]
        if isinstance(first, str):
            return first, None, None
        if isinstance(first, dict):
            return (
                first.get("chat_id") or first.get("group_id") or first.get("id"),
                first.get("chat_name") or first.get("name"),
                first.get("owner_id"),
            )
    return None, None, None


class FeishuIMError(Exception):
    """飞书 IM API 错误基类。"""

    def __init__(self, message: str, code: int | None = None) -> None:
        super().__init__(message)
        self.code = code


class RateLimitError(FeishuIMError):
    """Rate limit 错误，需要等待后重试。"""

    pass


@dataclass
class DownloadedMessageResource:
    """飞书消息资源下载结果。"""

    content: bytes
    mime_type: str
    file_key: str
    resource_type: Literal["image", "file"]


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
            actions: list[dict[str, Any]] = []
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

    与 FeishuClient (Space API) 独立，因为两者使用不同的认证机制：
    - Space API: plugin_token
    - IM API: tenant_access_token (本客户端)

    Example:
        client = FeishuIMClient(app_id="cli_xxx", app_secret="xxx")
        message_id = await client.send_card(
            receive_id="oc_xxx",
            receive_id_type="chat_id",
            card=CardTemplate(title="通知", content="Hello").to_card_json(),
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
        # 机器人自身 open_id 缓存（用于 is_bot_in_chat 成员比对）。
        # 群成员列表只能按 open_id/union_id/user_id 返回，拿不到 app_id，
        # 故必须用机器人 open_id（/bot/v3/info）去比对，而非 app_id。
        self._bot_open_id: str | None = None

    async def get_tenant_access_token(self) -> str:
        """获取 tenant_access_token（带缓存，2小时有效）。

        Token 会在过期前 5 分钟自动刷新。

        Returns:
            有效的 tenant_access_token

        Raises:
            FeishuIMError: 获取 token 失败时抛出
        """
        now = time.time()
        if self._tenant_token and now < self._token_expires_at:
            return self._tenant_token

        log = logger.bind(app_id=self.app_id)

        async with feishu_client() as client:
            response = await client.post(
                f"{self.OPEN_API_BASE}/auth/v3/tenant_access_token/internal",
                json={
                    "app_id": self.app_id,
                    "app_secret": self.app_secret,
                },
            )
            data = response.json()

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
        token = await self.get_tenant_access_token()

        log = logger.bind(
            receive_id=receive_id,
            receive_id_type=receive_id_type,
            msg_type=msg_type,
        )

        async with feishu_client() as client:
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
            data = response.json()

            code = data.get("code", -1)

            # Handle rate limit
            if code == 99991400 or "rate limit" in str(data).lower():
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
            card: 卡片 JSON 结构（可使用 CardTemplate.to_card_json() 生成）

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
        token = await self.get_tenant_access_token()

        log = logger.bind(message_id=message_id)

        async with feishu_client() as client:
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
            data = response.json()

            if data.get("code") == 0:
                log.info("card_updated")
                return True
            else:
                log.warning("card_update_failed", response=data)
                return False

    # ------------------------------------------------------------------
    # CardKit v1 原生流式卡片方法（手写 httpx，复用 get_tenant_access_token）
    #
    # 与既有 send_card/update_card 同类，独立新增、互不影响：
    #   create_card_entity → send_card_entity → stream_card_content → settle_card_stream
    # content 为「全量文本」（非增量），sequence 由调用方严格递增传入。
    # ------------------------------------------------------------------

    async def create_card_entity(
        self,
        card_json_2_0: dict[str, Any],
        *,
        uuid: str = "",
    ) -> str:
        """创建 CardKit 流式卡片实体。

        Args:
            card_json_2_0: schema 2.0 卡片 JSON（含 config.streaming_mode=true）
            uuid: 幂等键，非空时随请求下发，防重试重复创建

        Returns:
            card_id: 卡片实体 ID，用于后续下发与增量推送

        Raises:
            FeishuIMError: API 返回 code!=0（如租户未开通 cardkit）
        """
        token = await self.get_tenant_access_token()
        log = logger.bind(app_id=self.app_id)

        body: dict[str, Any] = {
            "type": "card_json",
            "data": json.dumps(card_json_2_0, ensure_ascii=False),
        }
        if uuid:
            body["uuid"] = uuid

        async with feishu_client() as client:
            response = await client.post(
                f"{self.OPEN_API_BASE}/cardkit/v1/cards",
                headers={
                    "Authorization": f"Bearer {token}",
                    "Content-Type": "application/json",
                },
                json=body,
            )
            data = response.json()

            code = data.get("code", -1)
            if code != 0:
                log.error("create_card_entity_failed", response=data)
                raise FeishuIMError(
                    f"创建 CardKit 卡片实体失败: {data.get('msg', data)}", code=code
                )

            card_id = data.get("data", {}).get("card_id", "")
            log.info("card_entity_created", card_id=card_id)
            return card_id

    async def send_card_entity(
        self,
        receive_id: str,
        receive_id_type: Literal["chat_id", "open_id", "user_id"],
        card_id: str,
    ) -> str:
        """下发 CardKit 卡片实体（复用 send_message，interactive 引用 card_id）。

        Args:
            receive_id: 接收者 ID
            receive_id_type: ID 类型（chat_id, open_id, user_id）
            card_id: create_card_entity 返回的卡片实体 ID

        Returns:
            message_id: 消息 ID
        """
        result = await self.send_message(
            receive_id=receive_id,
            receive_id_type=receive_id_type,
            msg_type="interactive",
            content={"type": "card", "data": {"card_id": card_id}},
        )
        return result.get("message_id", "")

    async def stream_card_content(
        self,
        card_id: str,
        element_id: str,
        content: str,
        sequence: int,
        *,
        uuid: str = "",
    ) -> bool:
        """增量推送流式文本（全量文本 + 严格递增 sequence）。

        content 是「新的全量文本」（非 delta），方法不做累积——累积是调用方职责。
        sequence 由调用方严格递增传入（同一卡片所有写操作共享单调计数器）。

        Args:
            card_id: 卡片实体 ID
            element_id: 可流式文本元素的 element_id（1~20 字符）
            content: 全量文本内容
            sequence: 严格递增的序号（int）
            uuid: 幂等键，非空时随请求下发

        Returns:
            True 表示推送成功

        Raises:
            FeishuIMError: API 返回 code!=0（如 300317 sequence 未递增）
        """
        token = await self.get_tenant_access_token()
        log = logger.bind(card_id=card_id, element_id=element_id, sequence=sequence)

        body: dict[str, Any] = {"content": content, "sequence": sequence}
        if uuid:
            body["uuid"] = uuid

        async with feishu_client() as client:
            response = await client.put(
                f"{self.OPEN_API_BASE}/cardkit/v1/cards/{card_id}/elements/{element_id}/content",
                headers={
                    "Authorization": f"Bearer {token}",
                    "Content-Type": "application/json",
                },
                json=body,
            )
            data = response.json()

            code = data.get("code", -1)
            if code != 0:
                log.error("stream_card_content_failed", response=data)
                raise FeishuIMError(
                    f"推送 CardKit 流式内容失败: {data.get('msg', data)}", code=code
                )

            log.info("card_content_streamed")
            return True

    async def settle_card_stream(
        self,
        card_id: str,
        sequence: int,
        *,
        uuid: str = "",
    ) -> bool:
        """关闭流式模式（收尾），streaming_mode=false。

        与 stream_card_content 共享同一单调 sequence。

        Args:
            card_id: 卡片实体 ID
            sequence: 严格递增的序号（int）
            uuid: 幂等键，非空时随请求下发

        Returns:
            True 表示收尾成功

        Raises:
            FeishuIMError: API 返回 code!=0
        """
        token = await self.get_tenant_access_token()
        log = logger.bind(card_id=card_id, sequence=sequence)

        body: dict[str, Any] = {
            "settings": json.dumps(
                {"config": {"streaming_mode": False, "update_multi": True}},
                ensure_ascii=False,
            ),
            "sequence": sequence,
        }
        if uuid:
            body["uuid"] = uuid

        async with feishu_client() as client:
            response = await client.patch(
                f"{self.OPEN_API_BASE}/cardkit/v1/cards/{card_id}/settings",
                headers={
                    "Authorization": f"Bearer {token}",
                    "Content-Type": "application/json",
                },
                json=body,
            )
            data = response.json()

            code = data.get("code", -1)
            if code != 0:
                log.error("settle_card_stream_failed", response=data)
                raise FeishuIMError(
                    f"关闭 CardKit 流式失败: {data.get('msg', data)}", code=code
                )

            log.info("card_stream_settled")
            return True

    async def get_chat_history(
        self,
        chat_id: str,
        *,
        page_size: int = 50,
        max_messages: int = 500,
        start_time: str = "",
        end_time: str = "",
    ) -> list[dict[str, Any]]:
        """获取群聊/私聊的历史消息。

        Args:
            chat_id: 聊天 ID
            page_size: 每页条数（最大 50）
            max_messages: 最多返回多少条消息
            start_time: 起始时间戳（秒级字符串）
            end_time: 结束时间戳（秒级字符串）

        Returns:
            消息列表，每项包含 message_id、sender_id、msg_type、body 等
        """
        token = await self.get_tenant_access_token()
        log = logger.bind(chat_id=chat_id)

        items: list[dict[str, Any]] = []
        page_token = ""
        async with feishu_client() as client:
            while len(items) < max_messages:
                params: dict[str, Any] = {
                    "container_id_type": "chat",
                    "container_id": chat_id,
                    "page_size": min(page_size, 50),
                    "sort_type": "ByCreateTimeDesc",
                }
                if start_time:
                    params["start_time"] = start_time
                if end_time:
                    params["end_time"] = end_time
                if page_token:
                    params["page_token"] = page_token

                response = await client.get(
                    f"{self.OPEN_API_BASE}/im/v1/messages",
                    params=params,
                    headers={"Authorization": f"Bearer {token}"},
                )
                data = response.json()

                code = data.get("code", -1)
                if code != 0:
                    log.warning("get_chat_history_failed", response=data)
                    return items

                payload = data.get("data", {})
                page_items = payload.get("items", [])
                if not isinstance(page_items, list) or not page_items:
                    break

                items.extend(page_items)
                if len(items) >= max_messages:
                    break

                if not payload.get("has_more"):
                    break

                page_token = str(payload.get("page_token") or "")
                if not page_token:
                    break

        items = items[:max_messages]
        log.info("chat_history_fetched", count=len(items))
        return items

    async def download_message_resource(
        self,
        *,
        message_id: str,
        file_key: str,
        resource_type: Literal["image", "file"],
    ) -> DownloadedMessageResource:
        """下载用户消息中的资源文件。

        飞书资源接口对图片也使用路径参数名 ``file_key``；调用方可传入
        message content 中的 ``image_key``。
        """
        token = await self.get_tenant_access_token()
        log = logger.bind(message_id=message_id, file_key=file_key, resource_type=resource_type)

        async with feishu_client() as client:
            response = await client.get(
                f"{self.OPEN_API_BASE}/im/v1/messages/{message_id}/resources/{file_key}",
                params={"type": resource_type},
                headers={"Authorization": f"Bearer {token}"},
            )

        data: dict[str, Any] | None = None
        try:
            parsed = response.json()
            if isinstance(parsed, dict):
                data = parsed
        except (ValueError, json.JSONDecodeError):
            data = None

        if data is not None and data.get("code", 0) != 0:
            code = data.get("code")
            log.warning("download_message_resource_failed", response=data)
            raise FeishuIMError(f"获取消息资源失败: {data.get('msg', data)}", code=code)

        content = bytes(getattr(response, "content", b"") or b"")
        if not content:
            log.warning("download_message_resource_empty")
            raise FeishuIMError("获取消息资源失败: empty response")

        headers = getattr(response, "headers", {}) or {}
        raw_content_type = str(headers.get("content-type") or headers.get("Content-Type") or "")
        mime_type = raw_content_type.split(";", 1)[0].strip().lower() or "application/octet-stream"
        log.info("message_resource_downloaded", size_bytes=len(content), mime_type=mime_type)
        return DownloadedMessageResource(
            content=content,
            mime_type=mime_type,
            file_key=file_key,
            resource_type=resource_type,
        )

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
        computed = hashlib.sha256(content.encode("utf-8")).hexdigest()
        return computed == signature

    @staticmethod
    def decrypt_callback(encrypt: str, encrypt_key: str) -> dict[str, Any]:
        """解密 AES-256-CBC 加密的回调内容。

        飞书使用 AES-256-CBC 加密回调内容，密钥为 SHA256(encrypt_key) 的前 32 字节。

        Args:
            encrypt: Base64 编码的加密内容
            encrypt_key: 应用的 Encrypt Key

        Returns:
            解密后的 JSON 数据

        Raises:
            ValueError: 解密失败
        """
        # 生成 AES 密钥: SHA256(encrypt_key) 取前 32 字节
        key = hashlib.sha256(encrypt_key.encode("utf-8")).digest()

        # Base64 解码
        ciphertext = base64.b64decode(encrypt)

        # 前 16 字节是 IV
        iv = ciphertext[:16]
        encrypted_data = ciphertext[16:]

        # AES-256-CBC 解密
        cipher = Cipher(algorithms.AES(key), modes.CBC(iv))
        decryptor = cipher.decryptor()
        decrypted = decryptor.update(encrypted_data) + decryptor.finalize()

        # 去除 PKCS7 填充
        padding_len = decrypted[-1]
        decrypted = decrypted[:-padding_len]

        return json.loads(decrypted.decode("utf-8"))

    # ------------------------------------------------------------------
    # 群聊成员管理方法
    # ------------------------------------------------------------------

    async def get_bot_open_id(self) -> str:
        """获取当前机器人自身的 open_id（带缓存）。

        飞书 ``/bot/v3/info`` 用 tenant_access_token 返回 bot 的 open_id。
        群成员列表无法用 app_id 比对（成员只按 open_id/union_id/user_id 返回），
        因此判断"机器人是否在群"必须用 open_id。

        Returns:
            机器人 open_id（ou_ 前缀）。

        Raises:
            FeishuIMError: API 调用失败。
        """
        if self._bot_open_id:
            return self._bot_open_id

        token = await self.get_tenant_access_token()
        async with feishu_client() as client:
            response = await client.get(
                f"{self.OPEN_API_BASE}/bot/v3/info",
                headers={"Authorization": f"Bearer {token}"},
            )
            data = response.json()
            if data.get("code") != 0:
                logger.error("get_bot_info_failed", app_id=self.app_id, response=data)
                raise FeishuIMError(
                    f"获取机器人信息失败: {data.get('msg', data)}", code=data.get("code")
                )
            open_id = (data.get("bot", {}) or {}).get("open_id", "")
            self._bot_open_id = open_id
            return open_id

    async def get_chat_members(
        self,
        chat_id: str,
        member_id_type: Literal["open_id", "union_id", "user_id"] = "open_id",
    ) -> list[dict[str, Any]]:
        """获取群聊成员列表。

        Args:
            chat_id: 群聊 ID
            member_id_type: 成员 ID 类型，飞书仅接受 open_id/union_id/user_id
                （注意：app_id 非法，会触发 99992402 field validation failed）。

        Returns:
            成员列表，每项包含 member_id、name、tenant_key 等

        Raises:
            FeishuIMError: API 调用失败
        """
        token = await self.get_tenant_access_token()
        log = logger.bind(chat_id=chat_id)

        async with feishu_client() as client:
            response = await client.get(
                f"{self.OPEN_API_BASE}/im/v1/chats/{chat_id}/members",
                params={"member_id_type": member_id_type, "page_size": 100},
                headers={"Authorization": f"Bearer {token}"},
            )
            data = response.json()

            code = data.get("code", -1)
            if code != 0:
                log.error("get_chat_members_failed", response=data)
                raise FeishuIMError(
                    f"获取群聊成员失败: {data.get('msg', data)}", code=code
                )

            items: list[dict[str, Any]] = data.get("data", {}).get("items", [])
            log.info("chat_members_fetched", count=len(items))
            return items

    async def is_bot_in_chat(self, chat_id: str) -> bool:
        """检查当前 Bot 是否已在指定群聊中。

        使用飞书专用接口 ``GET /im/v1/chats/{chat_id}/members/is_in_chat``：用
        tenant_access_token 调用时，判断的就是「当前机器人」是否在群内。

        不能用 ``/members`` 列表比对——该列表只返回**用户成员**，不含机器人，
        且历史代码传 ``member_id_type=app_id`` 是非法参数（99992402）。

        查询失败时降级返回 False（由 ensure_bot_in_chat 走幂等加入兜底）。

        Args:
            chat_id: 群聊 ID

        Returns:
            Bot 在群聊中返回 True，否则返回 False
        """
        try:
            token = await self.get_tenant_access_token()
            async with feishu_client() as client:
                response = await client.get(
                    f"{self.OPEN_API_BASE}/im/v1/chats/{chat_id}/members/is_in_chat",
                    headers={"Authorization": f"Bearer {token}"},
                )
                data = response.json()
            if data.get("code") == 0:
                return bool(data.get("data", {}).get("is_in_chat", False))
            logger.warning("is_bot_in_chat_check_failed", chat_id=chat_id, response=data)
            return False
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
        token = await self.get_tenant_access_token()
        log = logger.bind(chat_id=chat_id, app_id=self.app_id)

        async with feishu_client() as client:
            response = await client.post(
                f"{self.OPEN_API_BASE}/im/v1/chats/{chat_id}/members",
                params={"member_id_type": "app_id"},
                headers={
                    "Authorization": f"Bearer {token}",
                    "Content-Type": "application/json",
                },
                json={"id_list": [self.app_id]},
            )
            data = response.json()

            code = data.get("code", -1)

            if code == 99991400 or "rate limit" in str(data).lower():
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
            结构化结果: {"success": bool, "already_member": bool, "error": str | None}
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
        except FeishuIMError as e:
            log.warning("bot_join_chat_failed", error=str(e), code=e.code)
            return {"success": False, "already_member": False, "error": str(e)}

    async def create_chat(
        self,
        name: str,
        *,
        user_id_list: list[str] | None = None,
        bot_id_list: list[str] | None = None,
        owner_id: str = "",
        description: str = "",
        user_id_type: Literal["open_id", "union_id", "user_id"] = "open_id",
        set_bot_manager: bool = False,
    ) -> dict[str, Any]:
        """创建群聊（建群即拉人单步，POST /im/v1/chats）。

        一次请求完成建群 + 拉人 + 拉 bot——body 带 ``user_id_list``（≤50）/
        ``bot_id_list``（≤5），不做建群后第二次 add_chat_members。手写 httpx
        复用 ``get_tenant_access_token`` + ``httpx.AsyncClient``，与 ``add_bot_to_chat``
        同构（仅 raise RateLimitError，不加 @retry 避免单测真实 sleep）。

        Args:
            name: 群名称（恒放进 body）。
            user_id_list: 初始成员 ID 列表（≤50，非空才放进 body）。
            bot_id_list: 初始机器人 App ID 列表（≤5，非空才放进 body）。
            owner_id: 群主 ID（非空才放进 body；省略时由建群的 bot 自动成为群主）。
            description: 群描述（非空才放进 body）。
            user_id_type: 成员/群主 ID 类型（默认 open_id，透传到 query）。
            set_bot_manager: 是否把建群机器人设为管理员（仅 owner_id 非空时随 query 下发）。

        Returns:
            API 响应的 data 字段（含 chat_id 及群元信息）。

        Raises:
            RateLimitError: 触发 rate limit（99991400）。
            FeishuIMError: API 调用失败（code != 0）。
        """
        token = await self.get_tenant_access_token()
        log = logger.bind(app_id=self.app_id, chat_name=name)

        params: dict[str, Any] = {"user_id_type": user_id_type}
        # set_bot_manager 仅在指定群主且需要建群 bot 兼任管理员时随 query 下发
        if owner_id and set_bot_manager:
            params["set_bot_manager"] = "true"

        # body 仅放非空字段：name 恒放，其余非空才放（避免空值污染 payload）
        payload: dict[str, Any] = {"name": name}
        if user_id_list:
            payload["user_id_list"] = user_id_list
        if bot_id_list:
            payload["bot_id_list"] = bot_id_list
        if owner_id:
            payload["owner_id"] = owner_id
        if description:
            payload["description"] = description

        async with feishu_client() as client:
            response = await client.post(
                f"{self.OPEN_API_BASE}/im/v1/chats",
                params=params,
                headers={
                    "Authorization": f"Bearer {token}",
                    "Content-Type": "application/json",
                },
                json=payload,
            )
            data = response.json()

            code = data.get("code", -1)

            if code == 99991400 or "rate limit" in str(data).lower():
                log.warning("rate_limit_hit", response=data)
                raise RateLimitError(
                    f"Rate limit exceeded: {data.get('msg', data)}", code=code
                )

            if code != 0:
                log.error("create_chat_failed", response=data)
                raise FeishuIMError(
                    f"创建群聊失败: {data.get('msg', data)}", code=code
                )

            result: dict[str, Any] = data.get("data", {})
            log.info("chat_created", chat_id=result.get("chat_id", ""))
            return result


async def _aget_system_feishu_credentials() -> tuple[str, str] | None:
    """Load system-level Feishu IM credentials if configured."""

    app_id_setting = await SystemSetting.objects.filter(key=SettingKeys.FEISHU_APP_ID).afirst()
    app_secret_setting = await SystemSetting.objects.filter(key=SettingKeys.FEISHU_APP_SECRET).afirst()
    if app_id_setting and app_secret_setting and app_id_setting.value and app_secret_setting.value:
        app_secret = (
            decrypt_value(app_secret_setting.value)
            if app_secret_setting.is_encrypted
            else app_secret_setting.value
        )
        return app_id_setting.value, app_secret
    return None


async def create_feishu_im_client_for_project(project: Space | None = None) -> FeishuIMClient:
    """Create a Feishu IM client from project config or system defaults."""

    if project and project.feishu_app_id and project.feishu_app_secret_encrypted:
        return FeishuIMClient(
            app_id=project.feishu_app_id,
            app_secret=decrypt_value(project.feishu_app_secret_encrypted),
        )

    credentials = await _aget_system_feishu_credentials()
    if credentials:
        return FeishuIMClient(app_id=credentials[0], app_secret=credentials[1])

    fallback_project = await Space.objects.exclude(feishu_app_id__isnull=True).exclude(
        feishu_app_id=""
    ).exclude(feishu_app_secret_encrypted__isnull=True).exclude(
        feishu_app_secret_encrypted=""
    ).order_by("created_at").afirst()
    if fallback_project:
        return FeishuIMClient(
            app_id=fallback_project.feishu_app_id or "",
            app_secret=decrypt_value(fallback_project.feishu_app_secret_encrypted or ""),
        )

    raise ValueError("未配置飞书 IM 集成。请先配置空间级或系统级飞书 App ID / App Secret。")


class FeishuIMService:
    """Convenience wrapper around `FeishuIMClient` for bot workflows.

    可选组合 FeishuClient（项目 API）以支持工作项关联群聊 ID 查询。
    """

    def __init__(
        self,
        client: FeishuIMClient,
        project_client: "FeishuClient | None" = None,
    ) -> None:
        self.client = client
        self.project_client = project_client

    @classmethod
    async def create(
        cls,
        project: Space | None = None,
        *,
        with_project_client: bool = False,
    ) -> FeishuIMService:
        """创建 FeishuIMService 实例。

        Args:
            project: 项目实例（可选）
            with_project_client: 是否同时创建 FeishuClient（项目 API）
        """
        from services.feishu import create_feishu_client_for_project

        client = await create_feishu_im_client_for_project(project)

        project_client: "FeishuClient | None" = None
        if with_project_client and project:
            try:
                project_client = create_feishu_client_for_project(project)
            except Exception:
                logger.warning(
                    "project_client_creation_failed",
                    project_id=str(project.id),
                    exc_info=True,
                )

        return cls(client, project_client=project_client)

    async def send_card(
        self,
        receive_id: str,
        receive_id_type: Literal["chat_id", "open_id", "user_id"],
        card: dict[str, Any],
    ) -> str:
        return await self.client.send_card(receive_id=receive_id, receive_id_type=receive_id_type, card=card)

    async def update_card(self, message_id: str, card: dict[str, Any]) -> bool:
        return await self.client.update_card(message_id=message_id, card=card)

    async def create_card_entity(
        self,
        card_json_2_0: dict[str, Any],
        *,
        uuid: str = "",
    ) -> str:
        """委托 client 创建 CardKit 流式卡片实体。"""
        return await self.client.create_card_entity(card_json_2_0, uuid=uuid)

    async def send_card_entity(
        self,
        receive_id: str,
        receive_id_type: Literal["chat_id", "open_id", "user_id"],
        card_id: str,
    ) -> str:
        """委托 client 下发 CardKit 卡片实体。"""
        return await self.client.send_card_entity(
            receive_id=receive_id,
            receive_id_type=receive_id_type,
            card_id=card_id,
        )

    async def stream_card_content(
        self,
        card_id: str,
        element_id: str,
        content: str,
        sequence: int,
        *,
        uuid: str = "",
    ) -> bool:
        """委托 client 增量推送流式文本。"""
        return await self.client.stream_card_content(
            card_id=card_id,
            element_id=element_id,
            content=content,
            sequence=sequence,
            uuid=uuid,
        )

    async def settle_card_stream(
        self,
        card_id: str,
        sequence: int,
        *,
        uuid: str = "",
    ) -> bool:
        """委托 client 关闭 CardKit 流式模式（收尾）。"""
        return await self.client.settle_card_stream(card_id, sequence, uuid=uuid)

    async def ensure_bot_in_chat(self, chat_id: str) -> dict[str, Any]:
        """确保 Bot 在指定群聊中（委托给 client）。"""
        return await self.client.ensure_bot_in_chat(chat_id)

    async def create_chat(
        self,
        name: str,
        *,
        user_id_list: list[str] | None = None,
        bot_id_list: list[str] | None = None,
        owner_id: str = "",
        description: str = "",
        user_id_type: Literal["open_id", "union_id", "user_id"] = "open_id",
        set_bot_manager: bool = False,
    ) -> dict[str, Any]:
        """创建群聊（建群即拉人单步，委托给 client）。"""
        return await self.client.create_chat(
            name,
            user_id_list=user_id_list,
            bot_id_list=bot_id_list,
            owner_id=owner_id,
            description=description,
            user_id_type=user_id_type,
            set_bot_manager=set_bot_manager,
        )

    async def get_chat_history(
        self,
        chat_id: str,
        *,
        page_size: int = 50,
        max_messages: int = 500,
    ) -> list[dict[str, Any]]:
        """获取聊天历史消息。"""
        return await self.client.get_chat_history(
            chat_id,
            page_size=page_size,
            max_messages=max_messages,
        )

    async def download_message_resource(
        self,
        *,
        message_id: str,
        file_key: str,
        resource_type: Literal["image", "file"],
    ) -> DownloadedMessageResource:
        return await self.client.download_message_resource(
            message_id=message_id,
            file_key=file_key,
            resource_type=resource_type,
        )

    async def get_chat_id_for_work_item(
        self,
        project_key: str,
        work_item_id: int,
        work_item_type: str = "story",
    ) -> dict[str, Any] | None:
        """从飞书工作项获取关联群聊 ID。

        需要 project_client（FeishuClient）才能调用飞书项目 API。
        在工作项的 fields 中搜索包含 "chat" 或 "group" 的字段来定位群聊信息。

        Args:
            project_key: 飞书项目空间 Key
            work_item_id: 工作项 ID
            work_item_type: 工作项类型（默认 "story"）

        Returns:
            成功时返回 {"chat_id": str, "chat_name": str | None, "owner_id": str | None, "source": "work_item_api"}
            无关联群聊或失败时返回 None
        """
        log = logger.bind(
            project_key=project_key,
            work_item_id=work_item_id,
            work_item_type=work_item_type,
        )

        if self.project_client is None:
            log.warning("project_client_not_configured")
            return None

        try:
            # 定向只取群字段，缩小响应体（chat_group 新字段优先，group_id 旧字段兜底）
            work_item = await self.project_client.get_work_item(
                project_key=project_key,
                work_item_id=work_item_id,
                work_item_type=work_item_type,
                fields=["chat_group", "group_id"],
            )
        except Exception:
            log.error("get_work_item_failed", exc_info=True)
            return None

        fields = work_item.fields
        log.debug("work_item_fields", field_keys=list(fields.keys()))

        # 候选字段：语义字段（group_id / chat_group / chat_id）优先，
        # 其次才是 key 名模糊匹配（含 chat/group/群聊）作为兜底。
        candidate_keys: list[str] = [k for k in _CHAT_FIELD_PRIORITY if k in fields]
        for key in fields:
            if key in candidate_keys:
                continue
            if any(kw in key.lower() for kw in ("chat", "group", "群聊")):
                candidate_keys.append(key)

        if not candidate_keys:
            log.warning("no_chat_field_found", available_fields=list(fields.keys()))
            return None

        # 逐候选解析 + oc_ 正则校验：第一个产出合法 open_chat_id 的字段命中。
        # oc_ 校验确保过滤掉 group_type="disabled"、空串等非群 ID 的同名前缀字段。
        for field_key in candidate_keys:
            raw_id, chat_name, owner_id = _coerce_chat_meta(fields[field_key])
            if not raw_id or not isinstance(raw_id, str):
                continue
            match = _OPEN_CHAT_ID_RE.fullmatch(raw_id.strip())
            if not match:
                log.debug(
                    "chat_field_value_not_open_chat_id",
                    field_key=field_key,
                    value_preview=str(raw_id)[:40],
                )
                continue
            chat_id = raw_id.strip()
            log.info(
                "chat_id_resolved",
                chat_id=chat_id,
                chat_name=chat_name,
                field_key=field_key,
            )
            return {
                "chat_id": chat_id,
                "chat_name": chat_name,
                "owner_id": owner_id,
                "source": "work_item_api",
            }

        # 有候选字段但都不是合法 oc_ 群 ID（如 group_type="disabled"）→ 视为未绑定
        log.warning(
            "no_valid_chat_id_found",
            candidate_fields=candidate_keys,
        )
        return None
