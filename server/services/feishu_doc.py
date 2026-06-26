"""Feishu Document API client for reading and creating cloud documents.

Provides FeishuDocClient for document operations with Markdown conversion support.
Uses tenant_access_token authentication (same as IM API, different from Space API).
"""

import time
import unicodedata
from typing import Any

import httpx
import mistune
import structlog
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

logger = structlog.get_logger(__name__)


class FeishuDocAPIError(Exception):
    """Error from Feishu Document API."""

    pass


class RateLimitError(FeishuDocAPIError):
    """Rate limit error, should retry with backoff."""

    pass


class PermissionDeniedError(FeishuDocAPIError):
    """用户无权限访问文档。"""

    pass


class DocumentNotFoundError(FeishuDocAPIError):
    """文档不存在或已删除。"""

    pass


# 飞书 API 错误码分类集合
PERMISSION_CODES: frozenset[int] = frozenset({91003, 91004, 91204, 95008, 95009, 99991672})
NOT_FOUND_CODES: frozenset[int] = frozenset({1002, 18066, 91402, 95006, 95007})

MAX_DOC_CHARS: int = 30_000


def truncate_doc_content(markdown: str) -> tuple[str, bool]:
    """截断过长文档内容。返回 (内容, 是否截断)。"""
    if len(markdown) <= MAX_DOC_CHARS:
        return markdown, False
    return markdown[:MAX_DOC_CHARS], True


class FeishuDocClient:
    """Feishu Document API client using tenant_access_token authentication.

    Provides methods to read and create Feishu cloud documents with
    automatic Markdown conversion.

    Authentication uses tenant_access_token (2-hour validity, auto-refresh).
    This is different from FeishuClient which uses plugin_token for Space API.
    """

    OPEN_API_BASE = "https://open.feishu.cn/open-apis"

    def __init__(self, app_id: str, app_secret: str):
        """Initialize Feishu Document client.

        Args:
            app_id: Feishu application ID
            app_secret: Feishu application secret
        """
        self.app_id = app_id
        self.app_secret = app_secret
        self._tenant_token: str | None = None
        self._token_expires_at: float = 0

    async def get_tenant_access_token(self) -> str:
        """Get tenant_access_token with caching (2-hour validity).

        Returns:
            Valid tenant_access_token

        Raises:
            FeishuDocAPIError: Failed to get token
        """
        now = time.time()
        if self._tenant_token and now < self._token_expires_at:
            return self._tenant_token

        async with httpx.AsyncClient() as client:
            response = await client.post(
                f"{self.OPEN_API_BASE}/auth/v3/tenant_access_token/internal",
                json={
                    "app_id": self.app_id,
                    "app_secret": self.app_secret,
                },
            )
            data = response.json()

            if data.get("code") != 0:
                raise FeishuDocAPIError(f"Failed to get tenant token: {data}")

            self._tenant_token = data["tenant_access_token"]
            # Token valid for 2 hours, refresh 5 minutes early
            self._token_expires_at = now + data.get("expire", 7200) - 300

            logger.debug("feishu_doc_token_refreshed", expires_in=data.get("expire"))
            token = self._tenant_token
            assert token is not None
            return token

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=4, max=60),
        retry=retry_if_exception_type(RateLimitError),
        reraise=True,
    )
    async def get_document_content(
        self,
        document_id: str,
    ) -> tuple[str, list[dict[str, Any]]]:
        """Read Feishu cloud document content.

        Args:
            document_id: Document ID (extracted from URL, e.g., doxcnXXXX)

        Returns:
            Tuple of (markdown_content, raw_blocks)

        Raises:
            FeishuDocAPIError: API call failed
            RateLimitError: Rate limit hit (will retry automatically)
        """
        token = await self.get_tenant_access_token()

        async with httpx.AsyncClient() as client:
            # Get document blocks
            response = await client.get(
                f"{self.OPEN_API_BASE}/docx/v1/documents/{document_id}/blocks",
                headers={"Authorization": f"Bearer {token}"},
                params={"page_size": 500},
            )
            data = response.json()

            if data.get("code") != 0:
                error_code = data.get("code", 0)
                error_msg = data.get("msg", "Unknown error")
                if error_code == 99991400 or "rate limit" in error_msg.lower():
                    raise RateLimitError(f"Rate limit hit: {error_msg}")
                if error_code in PERMISSION_CODES:
                    raise PermissionDeniedError(f"无权限访问文档: {error_msg}")
                if error_code in NOT_FOUND_CODES:
                    raise DocumentNotFoundError(f"文档不存在: {error_msg}")
                raise FeishuDocAPIError(f"读取文档失败: {error_msg}")

            blocks = data.get("data", {}).get("items", [])
            markdown = blocks_to_markdown(blocks)

            logger.info(
                "feishu_document_read",
                document_id=document_id,
                block_count=len(blocks),
                content_length=len(markdown),
            )

            return markdown, blocks

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=4, max=60),
        retry=retry_if_exception_type(RateLimitError),
        reraise=True,
    )
    async def create_document(
        self,
        title: str,
        folder_token: str,
        content: str,
    ) -> dict[str, str]:
        """Create a Feishu cloud document.

        Args:
            title: Document title
            folder_token: Parent folder token (from project document space)
            content: Document content in Markdown format

        Returns:
            Dict with document_id and url

        Raises:
            FeishuDocAPIError: API call failed
            RateLimitError: Rate limit hit (will retry automatically)
        """
        token = await self.get_tenant_access_token()

        async with httpx.AsyncClient() as client:
            # 1. Create empty document
            response = await client.post(
                f"{self.OPEN_API_BASE}/docx/v1/documents",
                headers={
                    "Authorization": f"Bearer {token}",
                    "Content-Type": "application/json",
                },
                json={
                    "title": title,
                    "folder_token": folder_token,
                },
            )
            data = response.json()

            if data.get("code") != 0:
                error_msg = data.get("msg", "Unknown error")
                if "rate limit" in error_msg.lower() or data.get("code") == 99991400:
                    raise RateLimitError(f"Rate limit hit: {error_msg}")
                raise FeishuDocAPIError(f"Failed to create document: {error_msg}")

            document = data.get("data", {}).get("document", {})
            document_id = document.get("document_id", "")

            if not document_id:
                raise FeishuDocAPIError("No document_id in response")

            # 2. Write content blocks
            blocks = markdown_to_blocks(content)
            if blocks:
                await self._write_blocks(document_id, blocks, token)

            # Construct document URL
            doc_url = f"https://feishu.cn/docx/{document_id}"

            logger.info(
                "feishu_document_created",
                document_id=document_id,
                title=title,
                block_count=len(blocks),
            )

            return {
                "document_id": document_id,
                "url": doc_url,
            }

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=4, max=60),
        retry=retry_if_exception_type(RateLimitError),
        reraise=True,
    )
    async def create_folder(self, name: str, folder_token: str) -> str:
        """在指定父文件夹下创建子文件夹，返回新文件夹 token。

        镜像 ``create_document`` 的 token/headers/retry/错误码处理。每项目专属工作区
        文件夹经此创建（父 = Space 的 ``feishu_doc_folder_token``）。

        约束：飞书 Drive ``create_folder`` 5QPS 且**不可并发** —— 调用方须 per-task 串行
        （绝不 ``asyncio.gather``）；限流（``99991400`` / msg 含 "rate limit"）经 @retry 退避。

        # A1: 端点形态 MEDIUM，需 live 验证（POST /drive/v1/files/create_folder，
        # body {name, folder_token}，返回 data.token）。

        Args:
            name: 新文件夹名称。
            folder_token: 父文件夹 token（Space ``feishu_doc_folder_token``）。

        Returns:
            新建文件夹 token。

        Raises:
            FeishuDocAPIError: API 调用失败或返回体缺 token。
            RateLimitError: 命中限流（@retry 自动退避重试）。
        """
        token = await self.get_tenant_access_token()

        async with httpx.AsyncClient() as client:
            response = await client.post(
                f"{self.OPEN_API_BASE}/drive/v1/files/create_folder",
                headers={
                    "Authorization": f"Bearer {token}",
                    "Content-Type": "application/json",
                },
                json={
                    "name": name,
                    "folder_token": folder_token,
                },
            )
            data = response.json()

            if data.get("code") != 0:
                error_msg = data.get("msg", "Unknown error")
                if "rate limit" in error_msg.lower() or data.get("code") == 99991400:
                    raise RateLimitError(f"Rate limit hit: {error_msg}")
                raise FeishuDocAPIError(f"Failed to create folder: {error_msg}")

            new_token = data.get("data", {}).get("token", "")
            if not new_token:
                raise FeishuDocAPIError("No token in create_folder response")

            # 仅记父/新 token（业务标识，非凭证/正文），便于排障定位。
            logger.info(
                "feishu_folder_created",
                folder_token=folder_token,
                new_token=new_token,
            )
            return new_token

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=4, max=60),
        retry=retry_if_exception_type(RateLimitError),
        reraise=True,
    )
    async def _subscribe_file_request(self, file_token: str, file_type: str) -> bool:
        """按文件订阅飞书云文档变更事件的实际外呼（限流经 @retry 退避）。

        # [ASSUMED] A3: 端点形态 MEDIUM，需 live 验证
        # （POST /drive/v1/files/{file_token}/subscribe?file_type=docx，tenant_token 鉴权，
        # 返回 data.code==0 即订阅成功）。app 即文件 owner 可订；单回调地址多路复用。
        """
        token = await self.get_tenant_access_token()

        async with httpx.AsyncClient() as client:
            response = await client.post(
                f"{self.OPEN_API_BASE}/drive/v1/files/{file_token}/subscribe",
                headers={
                    "Authorization": f"Bearer {token}",
                    "Content-Type": "application/json",
                },
                params={"file_type": file_type},
            )
            data = response.json()

            if data.get("code") != 0:
                error_msg = data.get("msg", "Unknown error")
                if "rate limit" in error_msg.lower() or data.get("code") == 99991400:
                    raise RateLimitError(f"Rate limit hit: {error_msg}")
                # 非限流错误（权限/未发布/端点漂移）→ fail-soft 返回 False（不抛）。
                return False
            return True

    async def subscribe_file(self, file_token: str, *, file_type: str = "docx") -> bool:
        """按文件订阅 drive.file.edit_v1 变更事件，返回是否订阅成功（fail-soft，绝不抛）。

        订阅态在飞书侧（不入 git/DB，DB 仅记 ``ProjectDoc.subscribed`` 标志，OQ-4）。失败
        （限流耗尽 / 权限 / 端点漂移 / 网络）一律 **fail-soft 返回 False**，退化为 TTL 轮询
        兜底（83-06），绝不抛回 provision / 主流程。仅记 ``file_token``（业务标识）+ 结果布尔，
        **绝不记 token / 正文**。
        """
        try:
            ok = await self._subscribe_file_request(file_token, file_type)
        except Exception as exc:  # noqa: BLE001 — 订阅失败 fail-soft（退化 TTL 轮询），绝不抛
            logger.warning(
                "feishu_file_subscribe_failed",
                file_token=file_token,
                error_type=type(exc).__name__,
                component="doc_sync",
                category="caller",
            )
            return False
        logger.info(
            "feishu_file_subscribe",
            file_token=file_token,
            subscribed=ok,
            component="doc_sync",
            category="caller",
        )
        return ok

    async def append_markdown(
        self,
        document_id: str,
        content: str,
    ) -> dict[str, Any]:
        """Append Markdown content to an existing Feishu cloud document."""
        token = await self.get_tenant_access_token()
        blocks = markdown_to_blocks(content)
        if blocks:
            await self._write_blocks(document_id, blocks, token)
        logger.info(
            "feishu_document_appended",
            document_id=document_id,
            block_count=len(blocks),
            content_length=len(content),
        )
        return {
            "document_id": document_id,
            "appended_blocks": len(blocks),
        }

    async def _write_blocks(
        self,
        document_id: str,
        blocks: list[dict[str, Any]],
        token: str,
    ) -> None:
        """Write blocks to a document. Uses descendants API for tables."""
        # Split into groups: consecutive regular blocks, or single table
        groups: list[dict[str, Any]] = []  # {"type": "regular"|"table", "data": ...}
        current_regular: list[dict[str, Any]] = []

        for block in blocks:
            if block.get("_table_data"):
                if current_regular:
                    groups.append({"type": "regular", "data": current_regular})
                    current_regular = []
                groups.append({"type": "table", "data": block["_table_data"]})
            else:
                current_regular.append(block)
        if current_regular:
            groups.append({"type": "regular", "data": current_regular})

        async with httpx.AsyncClient(timeout=30.0) as client:
            headers = {
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
            }
            # Write each group sequentially to maintain order
            for group in groups:
                if group["type"] == "regular":
                    await self._write_regular_blocks(
                        document_id, group["data"], headers, client,
                    )
                else:
                    await self._write_table_via_descendants(
                        document_id, group["data"], headers, client,
                    )

    async def _write_regular_blocks(
        self,
        document_id: str,
        blocks: list[dict[str, Any]],
        headers: dict[str, str],
        client: Any,
    ) -> None:
        """Write regular (non-table) blocks via children API."""
        response = await client.post(
            f"{self.OPEN_API_BASE}/docx/v1/documents/{document_id}/blocks/{document_id}/children",
            headers=headers,
            json={"children": blocks, "index": -1},
        )
        data = response.json()
        if data.get("code") != 0:
            logger.error(
                "feishu_write_blocks_failed",
                document_id=document_id,
                error_code=data.get("code"),
                error_msg=data.get("msg"),
                error_data=data,
            )
            raise FeishuDocAPIError(
                f"文档已创建但内容写入失败: {data.get('msg', 'Unknown error')} (code={data.get('code')})"
            )

    async def _write_table_via_descendants(
        self,
        document_id: str,
        table_data: dict[str, Any],
        headers: dict[str, str],
        client: Any,
    ) -> None:
        """Write a table using the descendants API (single request, full structure)."""
        row_size = table_data["row_size"]
        col_size = table_data["column_size"]
        cells = table_data["cells"]  # list[list[list[element_dict]]]

        table_id = "tbl_1"
        descendants: list[dict[str, Any]] = []
        cell_ids: list[str] = []

        # Build cell blocks (row-major order)
        for r in range(row_size):
            for c in range(col_size):
                cell_id = f"cell_{r}_{c}"
                text_id = f"txt_{r}_{c}"
                cell_ids.append(cell_id)

                # Get elements for this cell
                elements: list[dict[str, Any]] = [{"text_run": {"content": ""}}]
                if r < len(cells) and c < len(cells[r]):
                    cell_elements = cells[r][c]
                    if cell_elements:
                        elements = cell_elements

                # Table cell block
                descendants.append({
                    "block_id": cell_id,
                    "block_type": 32,
                    "children": [text_id],
                    "table_cell": {},
                })
                # Text block inside cell
                descendants.append({
                    "block_id": text_id,
                    "block_type": 2,
                    "text": {"elements": elements, "style": {}},
                })

        # Table block (parent of all cells)
        table_block = {
            "block_id": table_id,
            "block_type": 31,
            "children": cell_ids,
            "table": {
                "property": {
                    "row_size": row_size,
                    "column_size": col_size,
                    "column_width": _estimate_table_column_widths(cells, col_size),
                    "header_row": True,
                },
            },
        }
        descendants.insert(0, table_block)

        payload = {
            "children_id": [table_id],
            "index": -1,
            "descendants": descendants,
        }

        response = await client.post(
            f"{self.OPEN_API_BASE}/docx/v1/documents/{document_id}/blocks/{document_id}/descendant",
            headers=headers,
            json=payload,
        )
        data = response.json()
        if data.get("code") != 0:
            logger.error(
                "feishu_write_table_failed",
                document_id=document_id,
                error_code=data.get("code"),
                error_msg=data.get("msg"),
                error_data=data,
            )
            # Don't raise — table failure shouldn't block the rest of the doc


def blocks_to_markdown(blocks: list[dict[str, Any]]) -> str:
    """Convert Feishu document blocks to Markdown.

    Supports:
    - text/paragraph blocks
    - heading1-9 blocks
    - bullet/ordered list blocks
    - code blocks
    - quote blocks
    - image blocks (converted to [Image: url])

    Args:
        blocks: List of Feishu document blocks

    Returns:
        Markdown formatted string
    """
    result: list[str] = []

    for block in blocks:
        block_type = block.get("block_type", 0)

        # Block type mapping (Feishu uses numeric types):
        # 1: Page, 2: Text, 3: Heading1, 4: Heading2, ...
        # 9: Heading7, 10: Heading8, 11: Heading9
        # 12: Bullet, 13: Ordered, 14: Code, 15: Quote
        # 27: Image

        if block_type == 2:  # Text/Paragraph
            text = _extract_text_content(block)
            if text:
                result.append(text)

        elif 3 <= block_type <= 11:  # Heading 1-9
            level = block_type - 2  # heading1 = type 3, so level = 1
            text = _extract_text_content(block)
            if text:
                result.append(f"{'#' * level} {text}")

        elif block_type == 12:  # Bullet list
            text = _extract_text_content(block)
            if text:
                result.append(f"- {text}")

        elif block_type == 13:  # Ordered list
            text = _extract_text_content(block)
            if text:
                # Note: Feishu doesn't provide list index, we use generic numbering
                result.append(f"1. {text}")

        elif block_type == 14:  # Code block
            code_block = block.get("code", {})
            elements = code_block.get("elements", [])
            code_text = "".join(
                elem.get("text_run", {}).get("content", "") for elem in elements
            )
            language = code_block.get("style", {}).get("language", "")
            # Map language code to name (Feishu uses numeric codes)
            lang_name = _get_language_name(language)
            result.append(f"```{lang_name}\n{code_text}\n```")

        elif block_type == 15:  # Quote
            text = _extract_text_content(block)
            if text:
                result.append(f"> {text}")

        elif block_type == 27:  # Image
            image_block = block.get("image", {})
            token = image_block.get("token", "")
            result.append(f"[Image: {token}]")

        # Skip other block types (page, divider, etc.)

    return "\n\n".join(result)


def _extract_text_content(block: dict[str, Any]) -> str:
    """Extract text content from a block.

    Args:
        block: Feishu document block

    Returns:
        Plain text content with inline formatting
    """
    # Different block types store text differently
    text_block = block.get("text", {})
    if not text_block:
        # Try heading block format
        for i in range(1, 10):
            text_block = block.get(f"heading{i}", {})
            if text_block:
                break

    if not text_block:
        # Try bullet/ordered format
        text_block = block.get("bullet", {}) or block.get("ordered", {})

    if not text_block:
        # Try quote format
        text_block = block.get("quote", {})

    elements = text_block.get("elements", [])
    parts: list[str] = []

    for elem in elements:
        text_run = elem.get("text_run", {})
        content = text_run.get("content", "")

        if not content:
            continue

        # Apply inline styles
        style = text_run.get("text_element_style", {})
        if style.get("bold"):
            content = f"**{content}**"
        if style.get("italic"):
            content = f"*{content}*"
        if style.get("inline_code"):
            content = f"`{content}`"
        if style.get("link", {}).get("url"):
            url = style["link"]["url"]
            content = f"[{content}]({url})"

        parts.append(content)

    return "".join(parts)


def _estimate_table_column_widths(
    cells: list[list[list[dict[str, Any]]]],
    column_count: int,
) -> list[int]:
    """Estimate Feishu table column widths in px from cell contents.

    飞书表格支持在 `table.property.column_width` 中传列宽。这里按每列最宽内容做
    估算，并对总宽度做约束，避免短列过宽或整张表无限膨胀。
    """
    if column_count <= 0:
        return []

    min_width = 120
    max_width = 420
    total_width_budget = 1080

    widths = [min_width] * column_count

    for col_idx in range(column_count):
        max_content_width = 0
        for row in cells:
            if col_idx >= len(row):
                continue
            cell_text = _elements_to_plain_text(row[col_idx])
            max_content_width = max(max_content_width, _estimate_text_display_width(cell_text))

        # 预留内边距，并让长文本列明显更宽一些。
        estimated_px = 56 + (max_content_width * 14)
        widths[col_idx] = max(min_width, min(max_width, estimated_px))

    total_width = sum(widths)
    if total_width <= total_width_budget:
        return widths

    shrinkable_total = sum(max(width - min_width, 0) for width in widths)
    if shrinkable_total <= 0:
        return widths

    overflow = total_width - total_width_budget
    adjusted: list[int] = []
    for width in widths:
        shrinkable = max(width - min_width, 0)
        shrink = round(overflow * (shrinkable / shrinkable_total)) if shrinkable_total else 0
        adjusted.append(max(min_width, width - shrink))

    # 处理四舍五入导致的残差，优先从最宽列继续回收。
    while sum(adjusted) > total_width_budget:
        widest_idx = max(range(len(adjusted)), key=lambda idx: adjusted[idx])
        if adjusted[widest_idx] <= min_width:
            break
        adjusted[widest_idx] -= 1

    return adjusted


def _elements_to_plain_text(elements: list[dict[str, Any]]) -> str:
    """Flatten Feishu text elements into plain text for width estimation."""
    parts: list[str] = []
    for elem in elements:
        text_run = elem.get("text_run", {})
        content = text_run.get("content", "")
        if content:
            parts.append(str(content))
    return "".join(parts)


def _estimate_text_display_width(text: str) -> int:
    """Estimate display width where CJK chars occupy more visual space."""
    width = 0
    for ch in text.strip():
        if ch == "\n":
            continue
        width += 2 if unicodedata.east_asian_width(ch) in {"F", "W"} else 1
    return max(width, 1)


def _get_language_name(language_code: int | str) -> str:
    """Map Feishu language code to language name.

    Args:
        language_code: Feishu language code (numeric or string)

    Returns:
        Language name for code fence
    """
    # 飞书 API 代码块语言码 (1-75) 反向映射
    lang_map: dict[int, str] = {
        1: "plaintext",
        2: "bash",
        4: "c",
        5: "cpp",
        6: "csharp",
        7: "css",
        9: "go",
        12: "html",
        13: "java",
        14: "javascript",
        16: "json",
        18: "kotlin",
        20: "markdown",
        24: "objectivec",
        25: "php",
        28: "python",
        31: "ruby",
        32: "rust",
        33: "scala",
        36: "sql",
        37: "swift",
        39: "typescript",
        44: "xml",
        45: "yaml",
    }

    if isinstance(language_code, int):
        return lang_map.get(language_code, "")
    return str(language_code) if language_code else ""


def markdown_to_blocks(content: str) -> list[dict[str, Any]]:
    """Convert Markdown to Feishu document blocks.

    Uses mistune to parse Markdown AST and converts to Feishu block format.

    Args:
        content: Markdown formatted content

    Returns:
        List of Feishu document block definitions
    """
    if not content.strip():
        return []

    blocks: list[dict[str, Any]] = []

    # Mistune AST does not recognize GitHub-style tables unless the table
    # plugin is enabled explicitly. Without it, pipe table syntax is parsed as
    # plain paragraph text and Feishu receives literal `| ... |` lines.
    md = mistune.create_markdown(renderer=None, plugins=["table"])
    tokens = md(content)

    if tokens is None:
        return blocks

    # tokens is a list of token dicts when renderer=None
    for token in tokens:
        token_blocks = _token_to_blocks(token)
        blocks.extend(token_blocks)

    return blocks


def _token_to_blocks(token: Any) -> list[dict[str, Any]]:
    """Convert a mistune token to Feishu blocks."""
    if not isinstance(token, dict):
        return []

    token_type = token.get("type", "")

    if token_type == "list":
        blocks: list[dict[str, Any]] = []
        is_ordered = token.get("attrs", {}).get("ordered", False)
        for child in token.get("children", []):
            if child.get("type") == "list_item":
                elements = _extract_token_elements(child)
                if elements:
                    blocks.append(_create_block_with_elements(
                        13 if is_ordered else 12,
                        "ordered" if is_ordered else "bullet",
                        elements,
                    ))
        return blocks

    if token_type == "table":
        return _table_to_blocks(token)

    block = _token_to_block(token)
    return [block] if block else []


def _token_to_block(token: Any) -> dict[str, Any] | None:
    """Convert a mistune token to a Feishu block."""
    if not isinstance(token, dict):
        return None

    token_type = token.get("type", "")

    if token_type == "paragraph":
        elements = _extract_token_elements(token)
        return _create_block_with_elements(2, "text", elements)

    elif token_type == "heading":
        level = token.get("attrs", {}).get("level", 1)
        elements = _extract_token_elements(token)
        block_type = min(level + 2, 11)
        return _create_block_with_elements(block_type, f"heading{level}", elements)

    elif token_type == "block_code":
        code = token.get("raw", "")
        lang = token.get("attrs", {}).get("info", "") or ""
        return _create_code_block(code, lang)

    elif token_type == "block_quote":
        elements = _extract_token_elements(token)
        return _create_block_with_elements(15, "quote", elements)

    elif token_type == "thematic_break":
        return {"block_type": 22, "divider": {}}  # Divider

    return None


def _extract_token_elements(
    token: dict[str, Any],
    style: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """Extract structured elements (with inline styles) from a mistune token.

    Returns a list of text_run dicts for use in Feishu block elements.
    """
    if style is None:
        style = {}

    # Direct text content
    if token.get("type") == "text" or (
        "raw" in token and token.get("type") not in ("block_code", "codespan", "paragraph", "list_item", "strong", "emphasis", "link")
    ):
        raw = token.get("raw", "")
        if not raw:
            return []
        element: dict[str, Any] = {"text_run": {"content": raw}}
        if style:
            element["text_run"]["text_element_style"] = style
        return [element]

    # Inline code
    if token.get("type") == "codespan":
        raw = token.get("raw", token.get("children", ""))
        if isinstance(raw, list):
            raw = "".join(c.get("raw", "") if isinstance(c, dict) else str(c) for c in raw)
        return [{"text_run": {"content": str(raw), "text_element_style": {**style, "inline_code": True}}}]

    # Bold
    if token.get("type") == "strong":
        return _extract_children_elements(token, {**style, "bold": True})

    # Italic
    if token.get("type") == "emphasis":
        return _extract_children_elements(token, {**style, "italic": True})

    # Link
    if token.get("type") == "link":
        url = token.get("attrs", {}).get("url", "")
        link_style = {**style, "link": {"url": url}} if url else style
        return _extract_children_elements(token, link_style)

    # Strikethrough
    if token.get("type") == "strikethrough":
        return _extract_children_elements(token, {**style, "strikethrough": True})

    # Container types (paragraph, list_item, etc.) — recurse into children
    return _extract_children_elements(token, style)


def _extract_children_elements(
    token: dict[str, Any],
    style: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """Recurse into children and collect elements."""
    children = token.get("children", [])
    if not children:
        return []
    elements: list[dict[str, Any]] = []
    for child in children:
        if isinstance(child, dict):
            elements.extend(_extract_token_elements(child, style))
        elif isinstance(child, str) and child:
            element: dict[str, Any] = {"text_run": {"content": child}}
            if style:
                element["text_run"]["text_element_style"] = style
            elements.append(element)
    return elements


def _table_to_blocks(token: dict[str, Any]) -> list[dict[str, Any]]:
    """Convert a Markdown table to a Feishu table block with _table_data marker."""
    head = None
    body_rows: list[Any] = []
    for child in token.get("children", []):
        if isinstance(child, dict):
            if child.get("type") == "table_head":
                head = child
            elif child.get("type") == "table_body":
                body_rows = child.get("children", [])

    # Collect all rows as cells: list[list[elements]]
    all_rows: list[list[list[dict[str, Any]]]] = []

    # Header row (bold)
    if head:
        head_rows = head.get("children", [])
        if head_rows:
            row = head_rows[0]
            cells = row.get("children", [])
            header_row: list[list[dict[str, Any]]] = []
            for cell in cells:
                elements = _extract_token_elements(cell)
                # Make header cells bold
                for elem in elements:
                    tr = elem.get("text_run", {})
                    style = tr.get("text_element_style", {})
                    style["bold"] = True
                    tr["text_element_style"] = style
                header_row.append(elements)
            all_rows.append(header_row)

    # Body rows
    for row in body_rows:
        if not isinstance(row, dict):
            continue
        cells = row.get("children", [])
        body_row: list[list[dict[str, Any]]] = []
        for cell in cells:
            elements = _extract_token_elements(cell)
            body_row.append(elements)
        all_rows.append(body_row)

    if not all_rows:
        return []

    row_size = len(all_rows)
    col_size = max(len(r) for r in all_rows) if all_rows else 0

    if col_size == 0:
        return []

    # Pad rows to uniform column count
    for row in all_rows:
        while len(row) < col_size:
            row.append([{"text_run": {"content": ""}}])

    return [{
        "_table_data": {
            "row_size": row_size,
            "column_size": col_size,
            "cells": all_rows,
        },
    }]


def _create_block_with_elements(
    block_type: int,
    block_key: str,
    elements: list[dict[str, Any]],
) -> dict[str, Any]:
    """Create a Feishu block with pre-built elements."""
    if not elements:
        elements = [{"text_run": {"content": ""}}]
    return {
        "block_type": block_type,
        block_key: {
            "elements": elements,
            "style": {},
        },
    }


def _create_code_block(code: str, language: str = "") -> dict[str, Any]:
    """Create a code block."""
    lang_code = _get_language_code(language)
    return {
        "block_type": 14,
        "code": {
            "elements": [
                {"text_run": {"content": code.rstrip("\n")}}
            ],
            "style": {"language": lang_code},
        },
    }


def _create_quote_block(text: str) -> dict[str, Any]:
    """Create a quote block (plain text version, used by blocks_to_markdown)."""
    return _create_block_with_elements(15, "quote", [{"text_run": {"content": text}}])


def _get_language_code(language: str) -> int:
    """Map language name to Feishu language code.

    Args:
        language: Programming language name

    Returns:
        Feishu language code (defaults to plaintext)
    """
    # 飞书 API 代码块语言码范围为 1-75
    # 参考: https://open.feishu.cn/document/client-docs/docs-add-on/06-code-block
    lang_map: dict[str, int] = {
        "": 1,
        "text": 1,
        "plaintext": 1,
        "bash": 2,
        "sh": 2,
        "shell": 2,
        "c": 4,
        "cpp": 5,
        "c++": 5,
        "csharp": 6,
        "c#": 6,
        "css": 7,
        "go": 9,
        "golang": 9,
        "html": 12,
        "java": 13,
        "javascript": 14,
        "js": 14,
        "json": 16,
        "kotlin": 18,
        "markdown": 20,
        "md": 20,
        "objectivec": 24,
        "objc": 24,
        "php": 25,
        "python": 28,
        "py": 28,
        "ruby": 31,
        "rb": 31,
        "rust": 32,
        "rs": 32,
        "scala": 33,
        "sql": 36,
        "swift": 37,
        "typescript": 39,
        "ts": 39,
        "xml": 44,
        "yaml": 45,
        "yml": 45,
    }

    code = lang_map.get(language.lower(), 1)
    # 安全兜底：确保不超出 API 允许范围
    if code < 1 or code > 75:
        return 1
    return code
