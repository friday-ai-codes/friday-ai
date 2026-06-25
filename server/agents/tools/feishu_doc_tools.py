"""Feishu document operation tools for the Agent.

Provides tools for reading and creating Feishu cloud documents
with automatic Markdown conversion.
"""

from datetime import datetime, timezone

import structlog

from agents.tools.base import ToolResult, tool
from projects.models import Space
from services.feishu_doc import FeishuDocAPIError, FeishuDocClient

logger = structlog.get_logger(__name__)


def _get_system_feishu_credentials_for_doc() -> tuple[str, str] | None:
    """从 SystemSetting 获取飞书凭证（同步）。"""
    from common.encryption import decrypt_value
    from system.models import SettingKeys, SystemSetting

    try:
        app_id_setting = SystemSetting.objects.get(key=SettingKeys.FEISHU_APP_ID)
        app_secret_setting = SystemSetting.objects.get(key=SettingKeys.FEISHU_APP_SECRET)
        if app_id_setting.value and app_secret_setting.value:
            app_secret = decrypt_value(app_secret_setting.value) if app_secret_setting.is_encrypted else app_secret_setting.value
            return app_id_setting.value, app_secret
    except SystemSetting.DoesNotExist:
        pass
    return None


async def _aget_system_feishu_credentials_for_doc() -> tuple[str, str] | None:
    """从 SystemSetting 获取飞书凭证（async 版本）。"""
    from common.encryption import decrypt_value
    from system.models import SettingKeys, SystemSetting

    app_id_setting = await SystemSetting.objects.filter(key=SettingKeys.FEISHU_APP_ID).afirst()
    app_secret_setting = await SystemSetting.objects.filter(key=SettingKeys.FEISHU_APP_SECRET).afirst()
    if app_id_setting and app_secret_setting and app_id_setting.value and app_secret_setting.value:
        app_secret = decrypt_value(app_secret_setting.value) if app_secret_setting.is_encrypted else app_secret_setting.value
        return app_id_setting.value, app_secret
    return None


async def create_feishu_doc_client_for_project(project: Space) -> FeishuDocClient:
    """Create a FeishuDocClient for a project.

    优先使用项目的飞书 IM App 配置 (feishu_app_id/feishu_app_secret)，
    如果未配置则回退到系统级飞书 IM 配置 (SystemSetting)。

    Args:
        project: Space model instance

    Returns:
        Configured FeishuDocClient instance

    Raises:
        ValueError: Space lacks Feishu app configuration
    """
    from common.encryption import decrypt_value

    # 优先使用项目级飞书 IM App 配置
    if project.feishu_app_id and project.feishu_app_secret_encrypted:
        app_secret = decrypt_value(project.feishu_app_secret_encrypted)
        return FeishuDocClient(
            app_id=project.feishu_app_id,
            app_secret=app_secret,
        )

    # 回退到系统级飞书 IM 配置
    credentials = await _aget_system_feishu_credentials_for_doc()
    if credentials:
        return FeishuDocClient(
            app_id=credentials[0],
            app_secret=credentials[1],
        )

    raise ValueError(
        f"项目 {project.id} 未配置飞书应用凭证。"
        "请在系统设置或项目设置中配置飞书自建应用 App ID 和 App Secret。"
    )


@tool(
    name="fetch_feishu_document",
    description="读取飞书云文档内容，返回 Markdown 格式。",
    category="FEISHU",
    parameters={
        "type": "object",
        "properties": {
            "space_id": {
                "type": "string",
                "description": "空间 UUID",
            },
            "document_id": {
                "type": "string",
                "description": "文档 ID（从 URL 提取，如 doxcnXXXX 或完整 URL）",
            },
        },
        "required": ["space_id", "document_id"],
    },
)
async def fetch_feishu_document(
    space_id: str,
    document_id: str,
) -> ToolResult:
    """Read a Feishu cloud document and convert to Markdown.

    Args:
        space_id: Friday space UUID
        document_id: Feishu document ID (extracted from URL)

    Returns:
        ToolResult with:
        - output.data.content: Markdown content
        - output.data.title: Document title (extracted from first heading)
        - output.metadata.word_count: Word count
        - output.metadata.block_count: Number of blocks
    """
    log = logger.bind(
        space_id=space_id,
        document_id=document_id,
    )

    # Extract document ID from URL if full URL provided
    doc_id = _extract_document_id(document_id)

    try:
        project = await Space.objects.aget(id=space_id)
    except Space.DoesNotExist:
        log.warning("space_not_found")
        return ToolResult(
            success=False,
            error=f"空间不存在: {space_id}",
        )

    try:
        client = await create_feishu_doc_client_for_project(project)
    except ValueError as e:
        log.warning("feishu_not_configured", error=str(e))
        return ToolResult(
            success=False,
            error=str(e),
        )

    try:
        markdown_content, blocks = await client.get_document_content(doc_id)

        # Extract title from first heading or first line
        title = _extract_title(markdown_content)
        word_count = len(markdown_content)

        log.info(
            "document_fetched",
            title=title,
            word_count=word_count,
            block_count=len(blocks),
        )

        return ToolResult(
            success=True,
            output={
                "data": {
                    "content": markdown_content,
                    "title": title,
                    "document_id": doc_id,
                },
                "metadata": {
                    "word_count": word_count,
                    "block_count": len(blocks),
                    "fetched_at": datetime.now(timezone.utc).isoformat(),
                },
            },
        )
    except FeishuDocAPIError as e:
        log.error("fetch_document_failed", error=str(e))
        return ToolResult(
            success=False,
            error=f"读取文档失败: {e}",
        )
    except Exception as e:
        log.error("fetch_document_error", error=str(e))
        return ToolResult(
            success=False,
            error=f"读取文档时发生错误: {e}",
        )


@tool(
    name="create_feishu_document",
    description="创建飞书云文档，内容使用 Markdown 格式。文档创建在工作项关联的空间中，默认组织内可见。",
    category="FEISHU",
    parameters={
        "type": "object",
        "properties": {
            "space_id": {
                "type": "string",
                "description": "空间 UUID",
            },
            "title": {
                "type": "string",
                "description": "文档标题",
            },
            "content": {
                "type": "string",
                "description": "文档内容（Markdown 格式）",
            },
            "folder_token": {
                "type": "string",
                "description": "目标文件夹 token（可选，默认使用项目配置的文档空间）",
            },
        },
        "required": ["space_id", "title", "content"],
    },
)
async def create_feishu_document(
    space_id: str,
    title: str,
    content: str,
    folder_token: str | None = None,
) -> ToolResult:
    """Create a Feishu cloud document with Markdown content.

    Args:
        space_id: Friday space UUID
        title: Document title
        content: Document content in Markdown format
        folder_token: Target folder token (optional, uses project default)

    Returns:
        ToolResult with:
        - output.data.document_id: New document ID
        - output.data.url: Document URL
        - output.data.title: Document title
    """
    log = logger.bind(
        space_id=space_id,
        title=title,
        content_length=len(content),
        folder_token=folder_token,
    )

    try:
        project = await Space.objects.aget(id=space_id)
    except Space.DoesNotExist:
        log.warning("space_not_found")
        return ToolResult(
            success=False,
            error=f"空间不存在: {space_id}",
        )

    try:
        client = await create_feishu_doc_client_for_project(project)
    except ValueError as e:
        log.warning("feishu_not_configured", error=str(e))
        return ToolResult(
            success=False,
            error=str(e),
        )

    # Use project's default document folder if not specified
    target_folder = folder_token
    if not target_folder:
        target_folder = getattr(project, "feishu_doc_folder_token", None) or ""

    if not target_folder:
        log.warning("no_folder_token")
        return ToolResult(
            success=False,
            error="未指定文档文件夹，且空间未配置默认文档空间",
        )

    try:
        result = await client.create_document(
            title=title,
            folder_token=target_folder,
            content=content,
        )

        log.info(
            "document_created",
            document_id=result.get("document_id"),
            url=result.get("url"),
        )

        return ToolResult(
            success=True,
            output={
                "data": {
                    "document_id": result.get("document_id", ""),
                    "url": result.get("url", ""),
                    "title": title,
                },
                "metadata": {
                    "created_at": datetime.now(timezone.utc).isoformat(),
                    "folder_token": target_folder,
                    "content_length": len(content),
                },
            },
        )
    except FeishuDocAPIError as e:
        log.error("create_document_failed", error=str(e))
        return ToolResult(
            success=False,
            error=f"创建文档失败: {e}",
        )
    except Exception as e:
        log.error("create_document_error", error=str(e))
        return ToolResult(
            success=False,
            error=f"创建文档时发生错误: {e}",
        )


def _extract_document_id(document_id_or_url: str) -> str:
    """Extract document ID from URL or return as-is.

    Args:
        document_id_or_url: Document ID or full Feishu document URL

    Returns:
        Document ID
    """
    # Handle full URLs like https://xxx.feishu.cn/docx/doxcnXXXX
    if "feishu.cn" in document_id_or_url or "larksuite.com" in document_id_or_url:
        # Extract the last path segment
        parts = document_id_or_url.rstrip("/").split("/")
        return parts[-1]

    return document_id_or_url


def _extract_title(markdown_content: str) -> str:
    """Extract title from Markdown content.

    Looks for first heading or uses first line.

    Args:
        markdown_content: Markdown formatted content

    Returns:
        Extracted title or empty string
    """
    if not markdown_content:
        return ""

    lines = markdown_content.strip().split("\n")

    for line in lines:
        line = line.strip()
        if not line:
            continue

        # Check for heading
        if line.startswith("#"):
            # Remove leading # and whitespace
            return line.lstrip("#").strip()

        # Use first non-empty line as fallback
        return line[:100]  # Truncate long first lines

    return ""
