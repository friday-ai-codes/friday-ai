"""Feishu IM tools for the Agent.

Provides tools for sending card messages to Feishu chats.
Uses FeishuIMClient with tenant_access_token authentication.
"""

from datetime import datetime, timezone

import structlog

from agents.tools.base import ToolResult, tool
from common.encryption import decrypt_value
from projects.models import Space
from services.feishu_im import CardTemplate, FeishuIMClient, FeishuIMError
from system.models import SettingKeys, SystemSetting

logger = structlog.get_logger(__name__)

# Maximum content length before truncation
MAX_CONTENT_LENGTH = 3000


def _get_system_feishu_credentials() -> tuple[str, str] | None:
    """从 SystemSetting 获取飞书 IM 凭证（同步）。"""
    try:
        app_id_setting = SystemSetting.objects.get(key=SettingKeys.FEISHU_APP_ID)
        app_secret_setting = SystemSetting.objects.get(key=SettingKeys.FEISHU_APP_SECRET)
        if app_id_setting.value and app_secret_setting.value:
            app_secret = decrypt_value(app_secret_setting.value) if app_secret_setting.is_encrypted else app_secret_setting.value
            return app_id_setting.value, app_secret
    except SystemSetting.DoesNotExist:
        pass
    return None


async def _aget_system_feishu_credentials() -> tuple[str, str] | None:
    """从 SystemSetting 获取飞书 IM 凭证（async 版本）。"""
    app_id_setting = await SystemSetting.objects.filter(key=SettingKeys.FEISHU_APP_ID).afirst()
    app_secret_setting = await SystemSetting.objects.filter(key=SettingKeys.FEISHU_APP_SECRET).afirst()
    if app_id_setting and app_secret_setting and app_id_setting.value and app_secret_setting.value:
        app_secret = decrypt_value(app_secret_setting.value) if app_secret_setting.is_encrypted else app_secret_setting.value
        return app_id_setting.value, app_secret
    return None


async def create_feishu_im_client_for_project(project: Space) -> FeishuIMClient:
    """为指定项目创建 FeishuIMClient 实例。

    优先使用项目的飞书 IM App 配置 (feishu_app_id/feishu_app_secret)，
    如果未配置则回退到系统级飞书 IM 配置 (SystemSetting)。

    Args:
        project: Space 模型实例

    Returns:
        配置好的 FeishuIMClient 实例

    Raises:
        ValueError: 未配置飞书 IM 集成时抛出
    """
    # 优先使用项目级飞书 IM App 配置
    if project.feishu_app_id and project.feishu_app_secret_encrypted:
        app_secret = decrypt_value(project.feishu_app_secret_encrypted)
        return FeishuIMClient(
            app_id=project.feishu_app_id,
            app_secret=app_secret,
        )

    # 回退到系统级飞书 IM 配置
    credentials = await _aget_system_feishu_credentials()
    if credentials:
        return FeishuIMClient(
            app_id=credentials[0],
            app_secret=credentials[1],
        )

    raise ValueError(
        f"项目 {project.id} 未配置飞书 IM 集成。"
        "请在系统设置或项目设置中配置飞书自建应用 App ID 和 App Secret。"
    )


def _truncate_content(content: str, max_length: int = MAX_CONTENT_LENGTH) -> str:
    """截断超长内容并添加省略号。

    Args:
        content: 原始内容
        max_length: 最大长度

    Returns:
        截断后的内容（如果需要）
    """
    if len(content) <= max_length:
        return content

    return content[: max_length - 20] + "\n\n... [内容已截断]"


@tool(
    name="send_card_message",
    description="发送卡片消息到飞书群聊或私聊。卡片支持 Markdown 内容和交互按钮。",
    category="FEISHU",
    parameters={
        "type": "object",
        "properties": {
            "space_id": {
                "type": "string",
                "description": "空间 UUID，用于获取飞书配置",
            },
            "chat_id": {
                "type": "string",
                "description": "群聊 ID (oc_xxx 格式) 或用户 open_id",
            },
            "title": {
                "type": "string",
                "description": "卡片标题",
            },
            "content": {
                "type": "string",
                "description": "卡片内容 (Markdown 格式)",
            },
            "buttons": {
                "type": "array",
                "description": "按钮列表（可选）",
                "items": {
                    "type": "object",
                    "properties": {
                        "text": {"type": "string", "description": "按钮文字"},
                        "value": {"type": "string", "description": "按钮值（回调用）"},
                        "type": {
                            "type": "string",
                            "enum": ["primary", "default", "danger"],
                            "description": "按钮类型",
                        },
                    },
                    "required": ["text"],
                },
            },
            "color": {
                "type": "string",
                "enum": ["blue", "green", "orange", "red"],
                "description": "卡片主题色，默认 blue",
            },
        },
        "required": ["space_id", "chat_id", "title", "content"],
    },
)
async def send_card_message(
    space_id: str,
    chat_id: str,
    title: str,
    content: str,
    buttons: list[dict] | None = None,
    color: str = "blue",
) -> ToolResult:
    """发送卡片消息到飞书群聊或私聊。

    Args:
        space_id: Friday 空间 ID
        chat_id: 群聊 ID 或用户 open_id
        title: 卡片标题
        content: 卡片内容（Markdown 格式）
        buttons: 按钮列表（可选）
        color: 卡片主题色

    Returns:
        ToolResult with message_id on success
    """
    log = logger.bind(
        space_id=space_id,
        chat_id=chat_id,
        title=title,
        content_length=len(content),
    )

    # Get project
    try:
        project = await Space.objects.aget(id=space_id)
    except Space.DoesNotExist:
        log.warning("space_not_found")
        return ToolResult(
            success=False,
            error=f"空间不存在: {space_id}",
        )

    # Create IM client
    try:
        client = await create_feishu_im_client_for_project(project)
    except ValueError as e:
        log.warning("feishu_im_not_configured", error=str(e))
        return ToolResult(
            success=False,
            error=str(e),
        )

    # Truncate long content
    truncated_content = _truncate_content(content)
    was_truncated = len(truncated_content) < len(content)

    # Build card template
    # Validate and normalize color
    valid_colors = ("blue", "green", "orange", "red")
    card_color = color if color in valid_colors else "blue"

    card = CardTemplate(
        title=title,
        content=truncated_content,
        buttons=buttons or [],
        color=card_color,  # type: ignore[arg-type]
    )

    # Determine receive_id_type based on chat_id format
    # oc_ prefix = chat_id, ou_ prefix = open_id
    if chat_id.startswith("oc_"):
        receive_id_type = "chat_id"
    elif chat_id.startswith("ou_"):
        receive_id_type = "open_id"
    else:
        receive_id_type = "chat_id"  # Default to chat_id

    # Send card message
    try:
        message_id = await client.send_card(
            receive_id=chat_id,
            receive_id_type=receive_id_type,  # type: ignore[arg-type]
            card=card.to_card_json(),
        )

        log.info("card_message_sent", message_id=message_id, truncated=was_truncated)

        return ToolResult(
            success=True,
            output={
                "data": {
                    "message_id": message_id,
                    "chat_id": chat_id,
                },
                "metadata": {
                    "sent_at": datetime.now(timezone.utc).isoformat(),
                    "truncated": was_truncated,
                    "original_length": len(content),
                },
            },
        )
    except FeishuIMError as e:
        log.error("send_card_failed", error=str(e), code=e.code)
        return ToolResult(
            success=False,
            error=f"发送卡片消息失败: {e}",
        )
    except Exception as e:
        log.error("send_card_unexpected_error", error=str(e))
        return ToolResult(
            success=False,
            error=f"发送卡片消息失败: {e}",
        )
