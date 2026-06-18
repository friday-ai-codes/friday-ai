"""看板与 MR 批量爬取关联 —— URL 爬取 agent（crawl）。

给一个 URL（飞书文档 / 飞书多维表格 / 通用 URL，如 txt），自动抓取内容并用系统
默认 LLM 抽成可关联的 ``{space, work_item_id, work_item_type, mr_url}`` 列表，回填
到前端「待爬取」编辑表，复用既有 ``ingest/resolve`` + ``ingest/batch-json`` 流水线。

抓取能力复用既有飞书 client：

- 多维表格（Bitable）：``BitableClient.list_records`` 分页遍历全表（有上限），按
  ``created_time`` 倒序（最新在前）。
- 文档（docx / wiki 包裹的 docx）：``FeishuDocClient.get_document_content`` 取 Markdown。
- wiki：先 ``/wiki/v2/spaces/get_node`` 解析到真实 obj_type + obj_token 再分流。
- 通用 URL：httpx 抓取纯文本（基础 SSRF 防护：禁私网/环回，禁跟随跳转，限大小）。

凭证：系统级 ``SystemSetting.FEISHU_APP_ID/SECRET``（开放平台自建应用）。未配置而用户
提交飞书链接 → 返回 ``feishu_not_configured`` + 系统设置深链，让前端引导去配置。

AI 提取走系统默认 provider（``ProviderConfigService.aresolve_or_error({})``）；模型只
负责把不可信内容映射成结构化条目，``space`` 由模型对照「已知空间」清单尽量填飞书 key /
名称，填不出留空，由用户在「待爬取」表手动确认（与既有 resolve 校验链对齐）。
"""

from __future__ import annotations

import asyncio
import ipaddress
import json
import re
import socket
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import parse_qs, urlparse

import httpx
import structlog

logger = structlog.get_logger(__name__)

__all__ = ["crawl_url", "CrawlResult", "CrawlStatus"]

# 系统设置飞书集成配置页深链（前端「去配置飞书」按钮跳转目标）。
FEISHU_SETTINGS_DEEPLINK = "/admin#integration"

# 抓取/提取上限（防超大 payload 拖垮 LLM 上下文 / 内存）。
_MAX_BITABLE_RECORDS = 500
_MAX_CONTENT_CHARS = 40_000
_MAX_GENERIC_BYTES = 2_000_000
_GENERIC_TIMEOUT = 20.0
_MAX_SPACES_IN_PROMPT = 200

_FEISHU_HOST_SUFFIXES = (".feishu.cn", ".larksuite.com", ".feishu.net")

# 来源类型常量。
_KIND_DOC = "feishu_doc"
_KIND_BITABLE = "feishu_bitable"
_KIND_WIKI = "feishu_wiki"
_KIND_GENERIC = "generic"
_KIND_UNKNOWN = "unknown"


class CrawlStatus:
    """爬取结果状态（与前端契约一致）。"""

    OK = "ok"
    FEISHU_NOT_CONFIGURED = "feishu_not_configured"
    EMPTY = "empty"
    ERROR = "error"


class _CrawlError(Exception):
    """内部受控错误：携带给用户的中文提示，统一转成 ``CrawlResult(error)``。"""


@dataclass
class CrawlResult:
    """爬取结果（透传给前端）。"""

    status: str
    source_kind: str = ""
    items: list[dict[str, Any]] = field(default_factory=list)
    message: str = ""
    settings_deeplink: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "source_kind": self.source_kind,
            "items": self.items,
            "message": self.message,
            "settings_deeplink": self.settings_deeplink,
        }


# ============================================================================
# URL 识别
# ============================================================================

def _is_feishu_host(host: str) -> bool:
    host = (host or "").lower()
    return host.endswith(_FEISHU_HOST_SUFFIXES) or host in {"feishu.cn", "larksuite.com"}


def _classify(url: str) -> tuple[str, dict[str, str]]:
    """识别 URL 类型并抽取关键 id。

    Returns:
        (kind, ids)。kind ∈ feishu_doc/feishu_bitable/feishu_wiki/generic/unknown。
    """
    parsed = urlparse(url)
    scheme = (parsed.scheme or "").lower()
    if scheme not in {"http", "https"}:
        return _KIND_UNKNOWN, {}

    segments = [s for s in (parsed.path or "").split("/") if s]
    query = parse_qs(parsed.query or "")

    if _is_feishu_host(parsed.hostname or ""):
        # /docx/<id>、/docs/<id>
        for marker in ("docx", "docs"):
            if marker in segments:
                idx = segments.index(marker)
                if idx + 1 < len(segments):
                    return _KIND_DOC, {"doc_id": segments[idx + 1]}
        # /base/<app_token>?table=<table_id>&view=<view_id>
        if "base" in segments:
            idx = segments.index("base")
            if idx + 1 < len(segments):
                return _KIND_BITABLE, {
                    "app_token": segments[idx + 1],
                    "table_id": (query.get("table") or [""])[0],
                }
        # /wiki/<token>
        if "wiki" in segments:
            idx = segments.index("wiki")
            if idx + 1 < len(segments):
                return _KIND_WIKI, {"token": segments[idx + 1]}
        # 飞书域但形态未知 → 当作不支持
        return _KIND_UNKNOWN, {}

    # 非飞书 http(s) → 通用 URL
    return _KIND_GENERIC, {}


# ============================================================================
# 凭证 / 空间
# ============================================================================

async def _aget_system_feishu_credentials() -> tuple[str, str] | None:
    """读系统级飞书开放平台凭证（app_id/app_secret），加密则解密。"""
    from common.encryption import decrypt_value
    from system.models import SettingKeys, SystemSetting

    app_id_setting = await SystemSetting.objects.filter(
        key=SettingKeys.FEISHU_APP_ID
    ).afirst()
    app_secret_setting = await SystemSetting.objects.filter(
        key=SettingKeys.FEISHU_APP_SECRET
    ).afirst()
    if (
        app_id_setting
        and app_secret_setting
        and app_id_setting.value
        and app_secret_setting.value
    ):
        secret = (
            decrypt_value(app_secret_setting.value)
            if app_secret_setting.is_encrypted
            else app_secret_setting.value
        )
        return app_id_setting.value, secret
    return None


async def _aget_spaces() -> list[dict[str, str]]:
    """取已知空间清单（名称 + 飞书 key），供 AI 对照填 ``space``。"""
    from projects.models import Project

    out: list[dict[str, str]] = []
    async for p in Project.objects.all()[:_MAX_SPACES_IN_PROMPT]:
        out.append(
            {"name": p.name or "", "key": p.feishu_project_key or "", "id": str(p.id)}
        )
    return out


# ============================================================================
# 飞书抓取
# ============================================================================

async def _aresolve_wiki_node(
    doc_client: Any, token: str
) -> tuple[str, str] | None:
    """解析 wiki 节点 → (obj_type, obj_token)。失败返回 None。"""
    from services.feishu_doc import FeishuDocClient

    access_token = await doc_client.get_tenant_access_token()
    async with httpx.AsyncClient(timeout=20.0) as client:
        resp = await client.get(
            f"{FeishuDocClient.OPEN_API_BASE}/wiki/v2/spaces/get_node",
            headers={"Authorization": f"Bearer {access_token}"},
            params={"token": token},
        )
        data = resp.json()
    if data.get("code") != 0:
        return None
    node = data.get("data", {}).get("node", {})
    obj_type = node.get("obj_type", "")
    obj_token = node.get("obj_token", "")
    if not obj_type or not obj_token:
        return None
    return obj_type, obj_token


async def _afetch_bitable_records(
    client: Any, app_token: str, table_id: str
) -> list[dict[str, Any]]:
    """分页遍历多维表格全表（有上限），按 created_time 倒序（最新在前）。"""
    records: list[dict[str, Any]] = []
    page_token: str | None = None
    while True:
        data = await client.list_records(
            app_token, table_id, page_token=page_token, page_size=100
        )
        items = data.get("items", []) if isinstance(data, dict) else []
        records.extend(it for it in items if isinstance(it, dict))
        if len(records) >= _MAX_BITABLE_RECORDS:
            break
        if not data.get("has_more"):
            break
        page_token = data.get("page_token")
        if not page_token:
            break

    # created_time 存在则按它倒序（最新在前）；缺失时保留接口/视图原序。
    records.sort(key=lambda r: r.get("created_time") or 0, reverse=True)
    return records[:_MAX_BITABLE_RECORDS]


def _records_to_text(records: list[dict[str, Any]]) -> str:
    """把多维表格记录的 fields 压成逐行 JSON 文本（截断到上限）。"""
    lines: list[str] = []
    total = 0
    for r in records:
        fields = r.get("fields", {}) if isinstance(r, dict) else {}
        line = json.dumps(fields, ensure_ascii=False)
        total += len(line) + 1
        if total > _MAX_CONTENT_CHARS:
            break
        lines.append(line)
    return "\n".join(lines)


async def _acrawl_feishu(
    kind: str, ids: dict[str, str], app_id: str, app_secret: str
) -> tuple[str, str]:
    """抓取飞书文档/多维表格内容。返回 (source_kind, content_text)。"""
    from services.feishu_bitable import BitableClient
    from services.feishu_doc import (
        DocumentNotFoundError,
        FeishuDocClient,
        PermissionDeniedError,
    )

    doc_client = FeishuDocClient(app_id=app_id, app_secret=app_secret)

    # wiki：先解析真实对象类型再分流。
    if kind == _KIND_WIKI:
        resolved = await _aresolve_wiki_node(doc_client, ids.get("token", ""))
        if resolved is None:
            raise _CrawlError("无法解析该飞书 wiki 链接（应用可能无权限或链接无效）")
        obj_type, obj_token = resolved
        if obj_type in ("docx", "doc"):
            kind, ids = _KIND_DOC, {"doc_id": obj_token}
        elif obj_type == "bitable":
            kind, ids = _KIND_BITABLE, {"app_token": obj_token, "table_id": ""}
        else:
            raise _CrawlError(f"暂不支持的 wiki 内容类型：{obj_type}")

    try:
        if kind == _KIND_DOC:
            markdown, _blocks = await doc_client.get_document_content(ids["doc_id"])
            return _KIND_DOC, markdown[:_MAX_CONTENT_CHARS]

        # bitable
        bclient = BitableClient(app_id=app_id, app_secret=app_secret)
        app_token = ids.get("app_token", "")
        table_id = ids.get("table_id") or ""
        if not table_id:
            tables = await bclient.list_tables(app_token)
            titems = tables.get("items", []) if isinstance(tables, dict) else []
            if not titems:
                raise _CrawlError("该多维表格中没有数据表")
            table_id = titems[0].get("table_id", "")
        records = await _afetch_bitable_records(bclient, app_token, table_id)
        if not records:
            raise _CrawlError("信息源无法获取到对应的内容（多维表格为空）")
        return _KIND_BITABLE, _records_to_text(records)
    except PermissionDeniedError as exc:
        raise _CrawlError(
            "飞书应用无该文档/表格的访问权限，请在飞书开放平台为应用开通对应文档权限"
        ) from exc
    except DocumentNotFoundError as exc:
        raise _CrawlError("文档不存在或已删除") from exc


# ============================================================================
# 通用 URL 抓取（基础 SSRF 防护）
# ============================================================================

def _resolve_host_ips(host: str) -> list[str]:
    infos = socket.getaddrinfo(host, None)
    return [info[4][0] for info in infos]


async def _ais_safe_public_url(url: str) -> bool:
    """基础 SSRF 防护：仅 http(s) + 解析到的 IP 必须是公网地址。"""
    parsed = urlparse(url)
    if (parsed.scheme or "").lower() not in {"http", "https"}:
        return False
    host = parsed.hostname
    if not host:
        return False
    try:
        ips = await asyncio.to_thread(_resolve_host_ips, host)
    except Exception:
        return False
    if not ips:
        return False
    for raw in ips:
        try:
            ip = ipaddress.ip_address(raw)
        except ValueError:
            return False
        if (
            ip.is_private
            or ip.is_loopback
            or ip.is_link_local
            or ip.is_reserved
            or ip.is_multicast
            or ip.is_unspecified
        ):
            return False
    return True


async def _acrawl_generic(url: str) -> str:
    """抓取通用 URL 的文本内容（不跟随跳转，防重定向绕过 SSRF）。"""
    if not await _ais_safe_public_url(url):
        raise _CrawlError("该 URL 不可访问或被安全策略拦截（仅允许公网 http/https）")
    try:
        async with httpx.AsyncClient(
            timeout=_GENERIC_TIMEOUT, follow_redirects=False
        ) as client:
            resp = await client.get(
                url, headers={"User-Agent": "FridayBot/1.0 (crawl)"}
            )
            resp.raise_for_status()
            raw = resp.content[:_MAX_GENERIC_BYTES]
    except httpx.HTTPError as exc:
        raise _CrawlError(f"抓取链接失败：{type(exc).__name__}") from exc
    try:
        text = raw.decode("utf-8", errors="replace")
    except Exception:
        text = ""
    return text[:_MAX_CONTENT_CHARS]


# ============================================================================
# AI 提取
# ============================================================================

_EXTRACT_SYSTEM_PROMPT = """你是一个把非结构化内容抽取成「看板工作项 ↔ MR 关联」条目的助手。

用户会给你一段内容（可能来自飞书文档、飞书多维表格的多行记录，或一段文本）。
请从中识别出每一条「飞书项目工作项」以及它关联的代码合并请求（MR/PR）链接，
输出**严格的 JSON 数组**，不要任何解释、不要 markdown 代码围栏。

每个数组元素的字段：
- "space": 该条目所属空间。请尽量对照下面「已知空间」清单，填它的飞书 key
  （key=... 的值）或空间名称；实在判断不出来就填空字符串 ""。
- "work_item_id": 飞书项目工作项 ID（纯数字）。这是必填项；无法确定数字 ID 的条目直接跳过、不要输出。
- "work_item_type": 工作项类型，如 "story" / "issue" / "bug" 等；不确定就填 ""。
- "mr_url": 关联的 MR/PR 链接；没有就填 ""。

规则：
- 只输出能确定 work_item_id（数字）的条目。
- 没有任何可识别条目时，输出空数组 []。
- 不要编造不存在的 ID 或链接。

已知空间（name 与 key 对照）：
{spaces}
"""


class _ProviderUnavailable(Exception):
    """系统默认 AI 模型不可用（未配置 provider / 无默认模型）。"""


async def _aextract_items(
    content: str, spaces: list[dict[str, str]]
) -> list[dict[str, Any]]:
    """调用系统默认 LLM 把内容抽成条目列表。"""
    from langchain_core.messages import HumanMessage, SystemMessage

    from agents.llm_factory import build_chat_model, content_to_text
    from services.provider_config import ProviderConfigService, ProviderMissingError

    resolved = await ProviderConfigService.aresolve_or_error({})
    if isinstance(resolved, ProviderMissingError):
        raise _ProviderUnavailable(resolved.recommended_action)
    model_name = (getattr(resolved, "extra", None) or {}).get("default_model", "")
    if not model_name:
        raise _ProviderUnavailable("系统未配置默认模型")

    spaces_block = "\n".join(
        f"- {s['name']} (key={s['key']})" for s in spaces if s.get("name")
    ) or "（无）"
    system = SystemMessage(
        content=_EXTRACT_SYSTEM_PROMPT.format(spaces=spaces_block)
    )
    human = HumanMessage(content=content[:_MAX_CONTENT_CHARS])

    model = build_chat_model(resolved, model_name, streaming=False)
    response = await model.ainvoke([system, human])
    text = content_to_text(response.content)
    return _parse_items_json(text)


_JSON_FENCE_RE = re.compile(r"```(?:json)?\s*(.*?)\s*```", re.DOTALL)


def _parse_items_json(text: str) -> list[dict[str, Any]]:
    """从模型输出里稳健解析 JSON 数组，规整成标准条目。"""
    raw = (text or "").strip()
    if not raw:
        return []
    fence = _JSON_FENCE_RE.search(raw)
    if fence:
        raw = fence.group(1).strip()
    else:
        # 容错：截取首个 '[' 到末个 ']'
        start = raw.find("[")
        end = raw.rfind("]")
        if start != -1 and end != -1 and end > start:
            raw = raw[start : end + 1]

    try:
        parsed = json.loads(raw)
    except (ValueError, TypeError):
        return []
    if not isinstance(parsed, list):
        return []

    items: list[dict[str, Any]] = []
    for el in parsed:
        if not isinstance(el, dict):
            continue
        work_item_id = el.get("work_item_id")
        try:
            wid = int(str(work_item_id).strip())
        except (TypeError, ValueError):
            continue
        if wid <= 0:
            continue
        items.append(
            {
                "space": str(el.get("space") or "").strip(),
                "work_item_id": wid,
                "work_item_type": str(el.get("work_item_type") or "").strip(),
                "mr_url": str(el.get("mr_url") or "").strip(),
            }
        )
    return items


# ============================================================================
# 入口
# ============================================================================

async def crawl_url(url: str) -> CrawlResult:
    """爬取一个 URL → 结构化「待爬取」条目列表（best-effort，不抛到调用方）。"""
    url = (url or "").strip()
    if not url:
        return CrawlResult(status=CrawlStatus.ERROR, message="请输入要爬取的链接")

    kind, ids = _classify(url)
    if kind == _KIND_UNKNOWN:
        return CrawlResult(
            status=CrawlStatus.ERROR,
            message="无法识别该链接类型（支持飞书文档 / 多维表格 / wiki，或通用 http(s) 链接）",
        )

    try:
        if kind in (_KIND_DOC, _KIND_BITABLE, _KIND_WIKI):
            creds = await _aget_system_feishu_credentials()
            if creds is None:
                return CrawlResult(
                    status=CrawlStatus.FEISHU_NOT_CONFIGURED,
                    source_kind=kind,
                    message="检测到飞书链接，但系统未配置飞书应用凭证。请先在系统设置中配置飞书自建应用（App ID / App Secret）后重试。",
                    settings_deeplink=FEISHU_SETTINGS_DEEPLINK,
                )
            app_id, app_secret = creds
            source_kind, content = await _acrawl_feishu(kind, ids, app_id, app_secret)
        else:
            source_kind, content = _KIND_GENERIC, await _acrawl_generic(url)
    except _CrawlError as exc:
        return CrawlResult(
            status=CrawlStatus.ERROR, source_kind=kind, message=str(exc)
        )
    except Exception as exc:  # noqa: BLE001 — 外部抓取失败一律降级为可读提示
        logger.warning(
            "crawl_fetch_failed", kind=kind, error_type=type(exc).__name__
        )
        return CrawlResult(
            status=CrawlStatus.ERROR,
            source_kind=kind,
            message="抓取信息源时出错，请稍后重试或检查链接/权限",
        )

    if not (content or "").strip():
        return CrawlResult(
            status=CrawlStatus.EMPTY,
            source_kind=source_kind,
            message="信息源无法获取到对应的内容",
        )

    spaces = await _aget_spaces()
    try:
        items = await _aextract_items(content, spaces)
    except _ProviderUnavailable as exc:
        return CrawlResult(
            status=CrawlStatus.ERROR,
            source_kind=source_kind,
            message=f"未配置可用的 AI 模型，无法解析内容：{exc}。请在系统设置 → Provider 配置后重试。",
        )
    except Exception:  # noqa: BLE001
        logger.warning("crawl_extract_failed", kind=source_kind)
        return CrawlResult(
            status=CrawlStatus.ERROR,
            source_kind=source_kind,
            message="AI 解析内容时出错，请稍后重试",
        )

    if not items:
        return CrawlResult(
            status=CrawlStatus.EMPTY,
            source_kind=source_kind,
            message="未能从该信息源解析出可关联的看板/MR 内容",
        )

    return CrawlResult(
        status=CrawlStatus.OK,
        source_kind=source_kind,
        items=items,
        message=f"已解析出 {len(items)} 条可关联内容",
    )
