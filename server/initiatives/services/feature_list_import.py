"""feature list 导入/解析（#4）——GitLab 文档取文（全局凭证鉴权）+ 文档 AI 结构化解析。

两种导入来源，最终都产出结构化「模块 → 功能点 → 验收项」树（与手动录入同形），落 markdown
载体工件由 ``FeatureListService`` 写入：

- **GitLab 文档**：给定 GitLab 文件链接（``/-/blob/<ref>/<path>`` 或 ``/-/raw/<ref>/<path>``），
  按 host 命中 ``GitInstanceCredential`` 全局凭证池解析 access token，用 python-gitlab 取文件正文。
- **粘贴文档 AI 解析**：把整篇文档交给 LLM，**强约束：只解析结构、功能点/验收项内容逐字保留原文**
  （不改写、不翻译、不润色），产出结构化 segments。

LLM 解析 best-effort：无凭证 / 解析失败 / 异常 → 返回 ``None``（调用方据此报错或回退），绝不反噬。
新增 LLM 调用赋 ``call_source=feature_list_parse`` 并上报 token/TTFT/上游错误码（LOGGING-SPEC §4.1）。
"""

from __future__ import annotations

import json
import re
from time import perf_counter
from typing import Any
from urllib.parse import unquote, urlparse

import structlog
from asgiref.sync import sync_to_async
from langchain_core.messages import HumanMessage, SystemMessage

from agents.call_source import CallSource, use_call_source
from common.logging import redact_secrets_in_text
from interactions.ledger import arecord_llm_usage, parse_upstream_status
from services.provider_config import (
    ProviderConfigService,
    ProviderMissingError,
    aget_legacy_anthropic_config,
)

logger = structlog.get_logger(__name__)

__all__ = [
    "afetch_gitlab_file_text",
    "agenerate_feature_modules_from_text",
    "GitlabFetchError",
    "FeatureListParseError",
]

_COMPONENT = "initiatives.feature_list_import"
_MODEL_FALLBACK = "claude-sonnet-4-20250514"
_MAX_DOC_CHARS = 60000
# 输出额度：结构化 feature 树需逐字保留原文，输出体积大，给足额度降低截断概率
# （Claude Sonnet 4 支持较大输出；超限时 _parse_modules_json 抢救已完整对象）。
_MAX_OUTPUT_TOKENS = 32000

_SYSTEM_PROMPT = (
    "你是需求结构解析器。把给定文档解析为「模块 → 功能点 → 验收项」三层结构。\n"
    "强约束（必须遵守）：\n"
    "1. 只解析结构，不改写内容。功能点名称、验收项文本必须**逐字保留原文**，"
    "不要翻译、不要润色、不要概括、不要补充。\n"
    "2. 仅输出一个 JSON 对象，不要任何前后缀/解释/代码块标记。\n"
    "3. JSON 结构：{\"modules\":[{\"module\":\"模块名\",\"features\":"
    "[{\"name\":\"功能点原文\",\"acceptance\":[\"验收项原文\"]}]}]}。\n"
    "4. 无法识别模块时用「未分组」。没有验收项时 acceptance 为空数组。"
)


class GitlabFetchError(ValueError):
    """GitLab 文件取文失败（链接非法 / 无凭证 / 远端错误，API 层 except ValueError 转 400）。"""


class FeatureListParseError(ValueError):
    """feature list AI 解析失败（无 Provider / LLM 失败 / 输出截断或非结构化）。

    携带用户可读 ``reason``；API 层 ``except ValueError`` 统一转 4xx 并回显该 reason，
    让用户区分「未配置 AI」「文档过长被截断」「文档无可解析结构」。
    """


def _parse_gitlab_blob_url(url: str) -> tuple[str, str, str, str]:
    """解析 GitLab 文件链接为 (base_url, project_path, ref, file_path)。

    支持 ``https://<host>/<group>/<proj>/-/blob/<ref>/<path>`` 与 ``/-/raw/<ref>/<path>``。
    解析失败抛 ``GitlabFetchError``。
    """
    parsed = urlparse(url.strip())
    if not parsed.scheme or not parsed.netloc:
        raise GitlabFetchError("GitLab 链接格式不正确")
    base_url = f"{parsed.scheme}://{parsed.netloc}"
    path = parsed.path
    m = re.search(r"^/(?P<project>.+?)/-/(?:blob|raw)/(?P<ref>[^/]+)/(?P<file>.+)$", path)
    if not m:
        raise GitlabFetchError("无法从链接解析出 GitLab 项目 / 分支 / 文件路径")
    project_path = unquote(m.group("project"))
    ref = unquote(m.group("ref"))
    file_path = unquote(m.group("file"))
    return base_url, project_path, ref, file_path


@sync_to_async
def _resolve_gitlab_token(host: str) -> str | None:
    """按 host 命中全局 GitLab 凭证池（``GitInstanceCredential``）解析 access token。"""
    from common.encryption import decrypt_value
    from repositories.models import GitInstanceCredential

    instance = GitInstanceCredential.objects.filter(host=host).first()
    if instance and instance.encrypted_token:
        return decrypt_value(instance.encrypted_token)
    return None


async def afetch_gitlab_file_text(url: str) -> str:
    """取 GitLab 文件正文（全局凭证鉴权）。失败抛 ``GitlabFetchError``。"""
    import asyncio

    import gitlab

    base_url, project_path, ref, file_path = _parse_gitlab_blob_url(url)
    host = urlparse(base_url).netloc
    token = await _resolve_gitlab_token(host)
    if not token:
        raise GitlabFetchError(f"未找到 {host} 的全局 GitLab 凭证，请先在仓库凭证中配置")

    def _fetch() -> str:
        gl = gitlab.Gitlab(base_url, private_token=token)
        project = gl.projects.get(project_path)
        f = project.files.get(file_path, ref=ref)
        return f.decode().decode("utf-8", errors="replace")

    try:
        text = await asyncio.to_thread(_fetch)
    except Exception as exc:  # noqa: BLE001 — 远端错误脱敏后转业务错误
        logger.warning(
            "feature_list_gitlab_fetch_failed",
            host=host,
            error_type=type(exc).__name__,
            component=_COMPONENT,
            category="caller",
        )
        raise GitlabFetchError(
            f"取 GitLab 文件失败：{redact_secrets_in_text(str(exc))[:200]}"
        ) from exc
    if not text.strip():
        raise GitlabFetchError("GitLab 文件为空")
    return text


def _extract_complete_objects(array_body: str) -> list[str]:
    """从 JSON 数组正文（``[`` 之后的内容）按括号匹配抽取完整的顶层 ``{...}`` 对象串。

    用于抢救被 ``max_tokens`` 截断的输出：忽略末尾不完整对象，返回已闭合的完整对象列表
    （正确处理字符串内的引号与转义，不被花括号误导）。
    """
    objects: list[str] = []
    depth = 0
    start = -1
    in_str = False
    escape = False
    for i, ch in enumerate(array_body):
        if in_str:
            if escape:
                escape = False
            elif ch == "\\":
                escape = True
            elif ch == '"':
                in_str = False
            continue
        if ch == '"':
            in_str = True
        elif ch == "{":
            if depth == 0:
                start = i
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0 and start != -1:
                objects.append(array_body[start : i + 1])
                start = -1
        elif ch == "]" and depth == 0:
            break
    return objects


def _salvage_truncated_modules(text: str) -> list[Any] | None:
    """从截断的 ``{"modules":[{...},{...}` 文本抢救已完整的 module 对象列表。"""
    m = re.search(r'"modules"\s*:\s*\[', text)
    if not m:
        return None
    objs = _extract_complete_objects(text[m.end():])
    salvaged: list[Any] = []
    for obj in objs:
        try:
            salvaged.append(json.loads(obj))
        except (ValueError, TypeError):
            continue
    return salvaged or None


def _parse_modules_json(raw: str) -> list[dict[str, Any]] | None:
    """从 LLM 输出健壮解析 modules JSON（剥代码块/前后缀，截断时抢救完整对象），失败返回 None。"""
    if not raw:
        return None
    text = raw.strip()
    # 剥 ```json ... ``` 代码块
    fence = re.search(r"```(?:json)?\s*(\{.*\})\s*```", text, re.DOTALL)
    if fence:
        text = fence.group(1)
    else:
        # 取首个 { 到末个 } 之间
        start, end = text.find("{"), text.rfind("}")
        if start != -1 and end != -1 and end > start:
            text = text[start : end + 1]
    modules: Any = None
    try:
        data = json.loads(text)
        modules = data.get("modules") if isinstance(data, dict) else None
    except (ValueError, TypeError):
        # 输出被 max_tokens 截断 → 抢救已完整的 module 对象（尽量不丢已解析内容）。
        modules = _salvage_truncated_modules(raw)
    if not isinstance(modules, list):
        return None
    # 归一防御：丢空名功能点，逐字保留文本。
    out: list[dict[str, Any]] = []
    for mod in modules:
        if not isinstance(mod, dict):
            continue
        module_name = str(mod.get("module") or "未分组").strip() or "未分组"
        features: list[dict[str, Any]] = []
        for feat in mod.get("features") or []:
            if not isinstance(feat, dict):
                continue
            name = str(feat.get("name") or "").strip()
            if not name:
                continue
            acceptance = [
                str(a).strip() for a in (feat.get("acceptance") or []) if str(a).strip()
            ]
            features.append({"name": name, "acceptance": acceptance})
        if features:
            out.append({"module": module_name, "features": features})
    return out or None


async def agenerate_feature_modules_from_text(
    project_id: Any, text: str
) -> list[dict[str, Any]] | None:
    """把文档 LLM 解析为结构化模块（逐字保留功能点/验收项原文）。

    失败抛 :class:`FeatureListParseError`（携可读 reason）：无 Provider / LLM 调用失败 /
    输出截断或非结构化。成功返回非空 modules 列表。
    """
    started = perf_counter()
    project = await _aget_project(project_id)
    if project is None:
        raise FeatureListParseError("项目不存在")
    space = getattr(project, "space", None)
    resolved = await ProviderConfigService.aresolve_or_error(project=space)
    if isinstance(resolved, ProviderMissingError):
        logger.warning(
            "feature_list_parse_no_provider",
            project_id=str(project_id),
            component=_COMPONENT,
            category="caller",
        )
        raise FeatureListParseError("未配置可用的 AI Provider，请先在空间或系统设置中配置 AI 模型")

    from agents.llm_factory import build_chat_model

    legacy = await aget_legacy_anthropic_config()
    model = legacy.get("default_model") or _MODEL_FALLBACK
    doc = text[:_MAX_DOC_CHARS]
    messages = [
        SystemMessage(content=_SYSTEM_PROMPT),
        HumanMessage(content=doc),
    ]
    start = perf_counter()
    ttft_ms: int | None = None
    try:
        with use_call_source(CallSource.FEATURE_LIST_PARSE):
            chat_model = build_chat_model(
                resolved, model, max_output_tokens=_MAX_OUTPUT_TOKENS, streaming=False
            )
            ai_msg = await chat_model.ainvoke(messages)
        ttft_ms = int((perf_counter() - start) * 1000)
    except Exception as exc:  # noqa: BLE001 — 转可读错误，不反噬
        await _record_usage(
            resolved, model, ttft_ms=None, upstream_status_code=parse_upstream_status(exc)
        )
        logger.warning(
            "feature_list_parse_failed",
            project_id=str(project_id),
            doc_chars=len(doc),
            error_type=type(exc).__name__,
            component=_COMPONENT,
            category="caller",
        )
        raise FeatureListParseError("AI 调用失败，请稍后重试或检查 AI Provider 配置") from exc

    usage = getattr(ai_msg, "usage_metadata", None) or {}
    await _record_usage(
        resolved,
        model,
        ttft_ms=ttft_ms,
        prompt_tokens=usage.get("input_tokens", 0) if isinstance(usage, dict) else 0,
        completion_tokens=usage.get("output_tokens", 0) if isinstance(usage, dict) else 0,
        duration_ms=int((perf_counter() - start) * 1000),
    )
    # 截断检测（anthropic stop_reason=max_tokens / openai finish_reason=length）。
    meta = getattr(ai_msg, "response_metadata", None) or {}
    stop_reason = str(meta.get("stop_reason") or meta.get("finish_reason") or "").lower()
    truncated = stop_reason in ("max_tokens", "length")

    content = getattr(ai_msg, "content", "")
    if isinstance(content, list):
        content = " ".join(
            str(c.get("text", "")) if isinstance(c, dict) else str(c) for c in content
        )
    modules = _parse_modules_json(str(content or ""))
    logger.info(
        "feature_list_parsed",
        project_id=str(project_id),
        doc_chars=len(doc),
        module_count=len(modules) if modules else 0,
        truncated=truncated,
        duration_ms=round((perf_counter() - started) * 1000, 2),
        component=_COMPONENT,
        category="caller",
    )
    if not modules:
        if truncated:
            raise FeatureListParseError(
                "文档过长，AI 解析输出被截断，请缩减文档或分模块分多次粘贴解析"
            )
        raise FeatureListParseError("AI 未从文档解析出结构化功能点，请检查文档内容")
    if truncated:
        # 抢救到部分模块但输出被截断：返回已解析部分（前端追加累积，可再分段补充）。
        logger.info(
            "feature_list_parsed_partial_truncated",
            project_id=str(project_id),
            module_count=len(modules),
            component=_COMPONENT,
            category="caller",
        )
    return modules


@sync_to_async
def _aget_project(project_id: Any) -> Any:
    from initiatives.models import Project

    return Project.objects.select_related("space").filter(id=project_id).first()


async def _record_usage(
    resolved: Any,
    model: str,
    *,
    ttft_ms: int | None = None,
    prompt_tokens: int = 0,
    completion_tokens: int = 0,
    duration_ms: int | None = None,
    upstream_status_code: int | None = None,
) -> None:
    try:
        await arecord_llm_usage(
            call_source=CallSource.FEATURE_LIST_PARSE.value,
            provider=str(getattr(resolved, "provider_type", "")),
            model=model,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            ttft_ms=ttft_ms,
            duration_ms=duration_ms,
            upstream_status_code=upstream_status_code,
            failure_type=str(upstream_status_code) if upstream_status_code is not None else "",
            source="initiatives",
        )
    except Exception:  # noqa: BLE001 — 观测绝不反噬主流程
        pass
