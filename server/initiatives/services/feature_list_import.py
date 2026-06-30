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
from services.model_capabilities import ModelCapabilities, strip_context_suffix
from services.provider_config import (
    ProviderConfigService,
    ProviderMissingError,
    aget_legacy_anthropic_config,
)

logger = structlog.get_logger(__name__)

__all__ = [
    "afetch_gitlab_file_text",
    "agenerate_feature_modules_from_text",
    "agenerate_feature_detail_sections",
    "agenerate_module_outline",
    "agenerate_module_features",
    "compute_parse_budget",
    "aget_parse_budget",
    "GitlabFetchError",
    "FeatureListParseError",
]

_COMPONENT = "initiatives.feature_list_import"
_MODEL_FALLBACK = "claude-sonnet-4-20250514"

# ── 输入/输出额度预算（按解析模型的 ModelCapabilities 动态计算）──────────────
# 行号裁剪方案下输出只含「结构 + 行号」，体积很小：请求量取**期望值 8000**，并按模型
# max_output_tokens 取 min（≤ DeepSeek 8192 上限，避免请求超限被 API 400 拒绝）。
_DESIRED_OUTPUT_TOKENS = 8000
# 输入预算 = 模型 max_input_tokens − 输出预留 − system prompt 预留 − 安全余量。
# system prompt 体积固定且不大，预留 1500 token；再留 2000 token 安全余量吸收分词偏差。
_SYSTEM_PROMPT_TOKEN_RESERVE = 1500
_SAFETY_TOKEN_BUFFER = 2000
# token→字数换算：文档以中文为主（≈1 char/token），取 1.4 略放宽但仍偏保守，避免超限。
_CHARS_PER_TOKEN = 1.4
# 输入字数硬顶（即便模型上下文很大，单次粘贴也不超过此值；多步解析在 Phase 2 承接）。
_MAX_DOC_CHARS = 100000
# 无 Provider 时给前端的兜底预算（按 DEFAULT_CAPABILITIES：128k 输入 / 4096 输出）。
_FALLBACK_INPUT_CHARS = 60000


def compute_parse_budget(provider_type: str, model: str) -> dict[str, Any]:
    """按解析模型的能力表算出本次解析的输入/输出额度预算。

    返回 ``{model, max_input_tokens, max_output_tokens, max_input_chars}``：
    - ``max_output_tokens``：min(期望 8000, 模型输出上限)，喂给 ``build_chat_model``；
    - ``max_input_chars``：(模型输入上限 − 输出预留 − prompt 预留 − 安全余量) × 字/token，
      并与硬顶 ``_MAX_DOC_CHARS`` 取 min；前端据此限制单次粘贴字数，避免 prompt 撑爆上下文。
    """
    caps = ModelCapabilities.get(provider_type, strip_context_suffix(model))
    max_out = min(_DESIRED_OUTPUT_TOKENS, caps.max_output_tokens)
    input_budget_tokens = max(
        2000,
        caps.max_input_tokens - max_out - _SYSTEM_PROMPT_TOKEN_RESERVE - _SAFETY_TOKEN_BUFFER,
    )
    max_chars = min(_MAX_DOC_CHARS, int(input_budget_tokens * _CHARS_PER_TOKEN))
    return {
        "model": model,
        "max_input_tokens": caps.max_input_tokens,
        "max_output_tokens": max_out,
        "max_input_chars": max_chars,
    }


async def aget_parse_budget(project_id: Any) -> dict[str, Any]:
    """解析「粘贴文档」前端所需的额度配置（best-effort，无 Provider 时给兜底预算）。"""
    project = await _aget_project(project_id)
    space = getattr(project, "space", None) if project is not None else None
    resolved = await ProviderConfigService.aresolve_or_error(project=space)
    if isinstance(resolved, ProviderMissingError):
        return {
            "model": "",
            "max_input_tokens": 0,
            "max_output_tokens": 0,
            "max_input_chars": _FALLBACK_INPUT_CHARS,
        }
    legacy = await aget_legacy_anthropic_config()
    model = legacy.get("default_model") or _MODEL_FALLBACK
    return compute_parse_budget(str(resolved.provider_type), model)

# 行号裁剪 prompt：模型只返回「结构 + 行号范围」，不复制原文 → 输出与文档大小解耦、不被截断；
# 验收项内容由系统按行号从原文裁剪，保证逐字一致。功能点名为短标题，可直接给出原文。
_SYSTEM_PROMPT = (
    "你是需求结构解析器。输入是**带行号的文档**（每行形如「123|内容」，123 为该行行号）。"
    "把它解析为「模块 → 功能点 → 验收项」三层结构。\n"
    "强约束（必须遵守）：\n"
    "1. **不要复制原文内容**；一律用**行号范围**指向原文，由系统裁剪，确保逐字一致。\n"
    "2. 功能点名称(name)取该功能点的标题原文（简短，逐字，不要补充）。\n"
    "3. feature_lines 是 [起始行号, 结束行号]（含两端），指向该功能点**完整正文区间**"
    "（从其标题行到下一个功能点/模块之前），供后续逐功能点结构化解析。\n"
    "4. acceptance_lines 是若干 [起始行号, 结束行号]，指向验收项所在原文行；无则空数组。\n"
    "5. summary_lines 是 [起始行号, 结束行号]，指向**模块概述/交互流程**区间（模块标题到第一个"
    "功能点之前）；无则省略或空数组。\n"
    "6. 行号必须是输入中真实出现的行号。仅输出一个 JSON 对象，无任何前后缀/解释/代码块标记。\n"
    "7. JSON 结构："
    "{\"modules\":[{\"module\":\"模块名\",\"summary_lines\":[5,20],\"features\":"
    "[{\"name\":\"功能点名\",\"feature_lines\":[21,60],\"acceptance_lines\":[[50,55]]}]}]}。\n"
    "8. 无法识别模块时用「未分组」。"
)

# Step 2 逐功能点结构化 prompt：输入是**单个功能点的原文**，拆为柔性 sections（不固定字段）。
_DETAIL_SYSTEM_PROMPT = (
    "你是需求结构化解析器。输入是**单个功能点（或模块）的原文片段**。"
    "把它拆成若干有序段落 sections，便于前端分层展示。\n"
    "强约束（必须遵守）：\n"
    "1. **逐字保留原文**，不改写/不翻译/不润色/不补充；只做结构切分与归类。\n"
    "2. 每个 section = {\"title\":\"小标题\",\"type\":\"text|list|mermaid\",\"content\":...}：\n"
    "   - type=text：content 为字符串（多段用换行）；\n"
    "   - type=list：content 为字符串数组（如验收项、业务规则逐条）；\n"
    "   - type=mermaid：content 为 mermaid 流程图源码字符串（flowchart/graph 等，逐字照搬）。\n"
    "3. title 取原文里的自然小标题（如「功能描述」「业务规则与约束」「数据流转」「交互流程」"
    "「验收项」等）；没有明确标题时自拟简短贴切的标题。**不要固定字段**，原文有什么就切什么。\n"
    "4. 识别到流程图（mermaid 代码，常以 flowchart/graph/sequenceDiagram 开头）必须单列为"
    " type=mermaid 的 section，content 为其源码（去掉 ``` 围栏，保留图本身）。\n"
    "5. 仅输出一个 JSON 对象：{\"sections\":[...]}，无任何前后缀/解释/代码块标记。"
)
# Step 2 输出仍较小（结构 + 原文切片），单功能点正文有限，输出额度取期望值即可。
_DETAIL_DESIRED_OUTPUT_TOKENS = 8000
_DETAIL_MAX_SOURCE_CHARS = 24000

# ── 分层解析（修复多模块大文档一次性输出被截断）──────────────────────────
# Step 0：只识别**模块**层级（输出极小，模块再多也不截断），返回各模块的行区间，
# 由前端按行区间切片后逐模块再发起 Step 1 功能点解析，实现「先出模块、再逐步填功能点」。
_MODULES_ONLY_SYSTEM_PROMPT = (
    "你是需求结构解析器。输入是**带行号的文档**（每行形如「123|内容」）。"
    "**只识别模块层级，不要解析功能点**。\n"
    "强约束：\n"
    "1. 仅输出一个 JSON 对象：{\"modules\":[{\"module\":\"模块名\",\"lines\":[起始行号,结束行号]}]}。\n"
    "2. lines 指向该模块**完整区间**（从模块标题行到下一个模块标题之前；最后一个模块到文末）。\n"
    "3. 模块名取标题原文（简短、逐字）。行号必须是输入中真实出现的行号。\n"
    "4. 无任何前后缀/解释/代码块标记。无法识别模块时用「未分组」。"
)
# Step 1：输入是**单个模块**的正文切片，只解析该模块下的功能点（输出受单模块体量约束，不截断）。
_MODULE_FEATURES_SYSTEM_PROMPT = (
    "你是需求结构解析器。输入是**带行号的【单个模块】正文**（每行形如「123|内容」）。"
    "把它解析为该模块下的**功能点**列表。\n"
    "强约束：\n"
    "1. 不要复制原文；一律用行号范围指向原文，由系统裁剪，确保逐字一致。\n"
    "2. name 取功能点标题原文（简短、逐字）。\n"
    "3. feature_lines=[起始行号,结束行号] 指向功能点完整正文区间。\n"
    "4. acceptance_lines=若干 [起始行号,结束行号] 指向验收项原文行；无则空数组。\n"
    "5. 行号必须是输入中真实出现的行号。仅输出 {\"features\":[{\"name\":\"\",\"feature_lines\":[s,e],"
    "\"acceptance_lines\":[[s,e]]}]}，无任何前后缀/解释/代码块标记。"
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


def _number_lines(text: str) -> tuple[list[str], str]:
    """把文档拆行并生成带行号的文本（每行「行号|内容」），供 LLM 引用行号。"""
    lines = text.split("\n")
    numbered = "\n".join(f"{i + 1}|{ln}" for i, ln in enumerate(lines))
    return lines, numbered


def _slice_lines(lines: list[str], start: Any, end: Any) -> str:
    """按 1-indexed 闭区间行号从原文裁剪（越界 clamp，非法返回空），保证逐字一致。"""
    try:
        s = int(start)
        e = int(end)
    except (TypeError, ValueError):
        return ""
    s = max(1, s)
    e = min(len(lines), e)
    if s > e:
        return ""
    return "\n".join(lines[s - 1 : e]).strip()


def _loads_modules_raw(raw: str) -> list[Any] | None:
    """从 LLM 输出取出 modules 数组（剥代码块/前后缀；截断时抢救完整对象），失败返回 None。"""
    if not raw:
        return None
    text = raw.strip()
    fence = re.search(r"```(?:json)?\s*(\{.*\})\s*```", text, re.DOTALL)
    if fence:
        text = fence.group(1)
    else:
        start, end = text.find("{"), text.rfind("}")
        if start != -1 and end != -1 and end > start:
            text = text[start : end + 1]
    try:
        data = json.loads(text)
        modules = data.get("modules") if isinstance(data, dict) else None
    except (ValueError, TypeError):
        modules = _salvage_truncated_modules(raw)
    return modules if isinstance(modules, list) else None


def _materialize_modules(
    raw_modules: list[Any], lines: list[str]
) -> list[dict[str, Any]] | None:
    """把 LLM 返回的「结构 + 行号范围」物化为 modules 树：验收项按行号从原文裁剪。

    兼容三种功能点表达：``acceptance_lines``（行号范围，优先裁剪）/ ``acceptance``（文本，回退）；
    名称取 ``name``（短标题文本）或 ``name_line``（行号，裁剪该行）。
    """
    out: list[dict[str, Any]] = []
    for mod in raw_modules:
        if not isinstance(mod, dict):
            continue
        module_name = str(mod.get("module") or "未分组").strip() or "未分组"
        module_summary = _slice_span(lines, mod.get("summary_lines"))
        features = _materialize_features(mod.get("features") or [], lines)
        if features:
            mod_out: dict[str, Any] = {"module": module_name, "features": features}
            if module_summary:
                mod_out["summary"] = module_summary
            out.append(mod_out)
    return out or None


def _materialize_features(
    raw_feats: list[Any], lines: list[str]
) -> list[dict[str, Any]]:
    """把 LLM 返回的功能点（行号范围）物化为 ``[{name, acceptance, source}]``（验收项/原文按行裁剪）。"""
    features: list[dict[str, Any]] = []
    for feat in raw_feats or []:
        if not isinstance(feat, dict):
            continue
        name = str(feat.get("name") or "").strip()
        if not name and feat.get("name_line") is not None:
            name = _slice_lines(lines, feat["name_line"], feat["name_line"])
        if not name:
            continue
        acceptance: list[str] = []
        spans = feat.get("acceptance_lines")
        if isinstance(spans, list):
            for span in spans:
                if isinstance(span, (list, tuple)) and len(span) >= 2:
                    sliced = _slice_lines(lines, span[0], span[1])
                elif isinstance(span, (int, str)):
                    sliced = _slice_lines(lines, span, span)
                else:
                    sliced = ""
                if sliced:
                    acceptance.append(sliced)
        else:
            acceptance = [
                str(a).strip() for a in (feat.get("acceptance") or []) if str(a).strip()
            ]
        # 功能点整段原文（供 Step 2 按需结构化为 sections）。
        source = _slice_span(lines, feat.get("feature_lines"))
        feat_out: dict[str, Any] = {"name": name, "acceptance": acceptance}
        if source:
            feat_out["source"] = source
        features.append(feat_out)
    return features


def _slice_span(lines: list[str], span: Any) -> str:
    """按 [start, end] 行号区间裁原文；span 非法/缺失返回空串。"""
    if isinstance(span, (list, tuple)) and len(span) >= 2:
        return _slice_lines(lines, span[0], span[1])
    return ""


def _parse_modules_json(raw: str) -> list[dict[str, Any]] | None:
    """文本型 acceptance 的解析（向后兼容/回退路径）：剥壳+解析+抢救后按文本归一。"""
    modules = _loads_modules_raw(raw)
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
    budget = compute_parse_budget(str(resolved.provider_type), model)
    max_output_tokens = budget["max_output_tokens"]
    doc = text[: budget["max_input_chars"]]
    # 行号裁剪：喂带行号的文档，模型只回结构+行号范围，验收项由系统按行号裁剪原文。
    lines, numbered_doc = _number_lines(doc)
    messages = [
        SystemMessage(content=_SYSTEM_PROMPT),
        HumanMessage(content=numbered_doc),
    ]
    start = perf_counter()
    ttft_ms: int | None = None
    try:
        with use_call_source(CallSource.FEATURE_LIST_PARSE):
            chat_model = build_chat_model(
                resolved, model, max_output_tokens=max_output_tokens, streaming=False
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
            model=model,
            max_output_tokens=max_output_tokens,
            error_type=type(exc).__name__,
            # 脱敏后记录上游错误摘要，便于区分「max_tokens 超限 / 鉴权 / 限流」等真实原因。
            error=redact_secrets_in_text(str(exc))[:300],
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
    # 行号裁剪物化：取出结构（含 acceptance_lines），按行号从原文裁剪验收项 → 逐字一致。
    raw_modules = _loads_modules_raw(str(content or ""))
    modules = _materialize_modules(raw_modules, lines) if raw_modules else None
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


def _loads_features_raw(raw: str) -> list[Any] | None:
    """从 LLM 输出取出 features 数组（剥代码块/前后缀；截断时抢救完整对象），失败返回 None。"""
    if not raw:
        return None
    text = raw.strip()
    fence = re.search(r"```(?:json)?\s*(\{.*\})\s*```", text, re.DOTALL)
    if fence:
        text = fence.group(1)
    else:
        start, end = text.find("{"), text.rfind("}")
        if start != -1 and end != -1 and end > start:
            text = text[start : end + 1]
    try:
        data = json.loads(text)
        feats = data.get("features") if isinstance(data, dict) else None
    except (ValueError, TypeError):
        m = re.search(r'"features"\s*:\s*\[', raw)
        feats = None
        if m:
            objs = _extract_complete_objects(raw[m.end():])
            salvaged: list[Any] = []
            for obj in objs:
                try:
                    salvaged.append(json.loads(obj))
                except (ValueError, TypeError):
                    continue
            feats = salvaged or None
    return feats if isinstance(feats, list) else None


async def _ainvoke_parse_llm(
    project_id: Any, system_prompt: str, doc: str, *, log_event: str
) -> tuple[str, list[str], bool]:
    """通用解析 LLM 调用：解析 Provider → 算额度 → 喂带行号文档 → 返回 ``(content, lines, truncated)``。

    无 Provider / LLM 调用失败抛 :class:`FeatureListParseError`（携可读 reason）。
    """
    project = await _aget_project(project_id)
    if project is None:
        raise FeatureListParseError("项目不存在")
    space = getattr(project, "space", None)
    resolved = await ProviderConfigService.aresolve_or_error(project=space)
    if isinstance(resolved, ProviderMissingError):
        raise FeatureListParseError("未配置可用的 AI Provider，请先在空间或系统设置中配置 AI 模型")

    from agents.llm_factory import build_chat_model

    legacy = await aget_legacy_anthropic_config()
    model = legacy.get("default_model") or _MODEL_FALLBACK
    budget = compute_parse_budget(str(resolved.provider_type), model)
    doc = doc[: budget["max_input_chars"]]
    lines, numbered_doc = _number_lines(doc)
    messages = [
        SystemMessage(content=system_prompt),
        HumanMessage(content=numbered_doc),
    ]
    start = perf_counter()
    ttft_ms: int | None = None
    try:
        with use_call_source(CallSource.FEATURE_LIST_PARSE):
            chat_model = build_chat_model(
                resolved, model, max_output_tokens=budget["max_output_tokens"], streaming=False
            )
            ai_msg = await chat_model.ainvoke(messages)
        ttft_ms = int((perf_counter() - start) * 1000)
    except Exception as exc:  # noqa: BLE001 — 转可读错误，不反噬
        await _record_usage(
            resolved, model, ttft_ms=None, upstream_status_code=parse_upstream_status(exc)
        )
        logger.warning(
            f"{log_event}_failed",
            project_id=str(project_id),
            doc_chars=len(doc),
            model=model,
            error_type=type(exc).__name__,
            error=redact_secrets_in_text(str(exc))[:300],
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
    meta = getattr(ai_msg, "response_metadata", None) or {}
    stop_reason = str(meta.get("stop_reason") or meta.get("finish_reason") or "").lower()
    truncated = stop_reason in ("max_tokens", "length")
    content = getattr(ai_msg, "content", "")
    if isinstance(content, list):
        content = " ".join(
            str(c.get("text", "")) if isinstance(c, dict) else str(c) for c in content
        )
    return str(content or ""), lines, truncated


async def agenerate_module_outline(
    project_id: Any, text: str
) -> list[dict[str, Any]]:
    """Step 0：只解析**模块层级**，返回 ``[{module, line_start, line_end}]``。

    输出极小（模块再多也不截断）；行区间供前端切片后逐模块再发起 Step 1 功能点解析。
    无可解析模块 / 无 Provider / LLM 失败抛 :class:`FeatureListParseError`。
    """
    if not str(text or "").strip():
        raise FeatureListParseError("文档为空")
    content, lines, truncated = await _ainvoke_parse_llm(
        project_id, _MODULES_ONLY_SYSTEM_PROMPT, str(text), log_event="feature_list_parse_modules"
    )
    raw = _loads_modules_raw(content)
    out: list[dict[str, Any]] = []
    for mod in raw or []:
        if not isinstance(mod, dict):
            continue
        name = str(mod.get("module") or "未分组").strip() or "未分组"
        span = mod.get("lines")
        if isinstance(span, (list, tuple)) and len(span) >= 2:
            try:
                s = max(1, int(span[0]))
                e = min(len(lines), int(span[1]))
            except (TypeError, ValueError):
                s, e = 1, len(lines)
        else:
            s, e = 1, len(lines)
        if s > e:
            s, e = 1, len(lines)
        out.append({"module": name, "line_start": s, "line_end": e})
    logger.info(
        "feature_list_modules_parsed",
        project_id=str(project_id),
        module_count=len(out),
        truncated=truncated,
        component=_COMPONENT,
        category="caller",
    )
    if not out:
        raise FeatureListParseError("AI 未从文档解析出模块，请检查文档内容")
    return out


async def agenerate_module_features(
    project_id: Any, module_text: str
) -> list[dict[str, Any]]:
    """Step 1：解析**单个模块切片**下的功能点，返回 ``[{name, acceptance, source}]``。

    输入受单模块体量约束、输出不截断。无 Provider / LLM 失败抛 :class:`FeatureListParseError`；
    解析不出功能点时返回空列表（前端展示该模块为空，可手动补）。
    """
    src = str(module_text or "").strip()
    if not src:
        return []
    content, lines, _ = await _ainvoke_parse_llm(
        project_id,
        _MODULE_FEATURES_SYSTEM_PROMPT,
        src,
        log_event="feature_list_parse_module_features",
    )
    features = _materialize_features(_loads_features_raw(content) or [], lines)
    logger.info(
        "feature_list_module_features_parsed",
        project_id=str(project_id),
        feature_count=len(features),
        component=_COMPONENT,
        category="caller",
    )
    return features


def _normalize_sections(raw: Any) -> list[dict[str, Any]]:
    """归一 LLM 返回的 sections：保留 {title, type, content}，type∈text/list/mermaid，丢空段。"""
    out: list[dict[str, Any]] = []
    items = raw.get("sections") if isinstance(raw, dict) else raw
    if not isinstance(items, list):
        return out
    for item in items:
        if not isinstance(item, dict):
            continue
        stype = str(item.get("type") or "text").strip().lower()
        if stype not in ("text", "list", "mermaid"):
            stype = "text"
        content = item.get("content")
        if stype == "list":
            if isinstance(content, list):
                content = [str(c).strip() for c in content if str(c).strip()]
            elif isinstance(content, str) and content.strip():
                content = [ln.strip() for ln in content.splitlines() if ln.strip()]
            else:
                content = []
            if not content:
                continue
        else:
            content = str(content or "").strip()
            if not content:
                continue
        out.append(
            {"title": str(item.get("title") or "").strip(), "type": stype, "content": content}
        )
    return out


def _loads_sections_raw(raw: str) -> Any:
    """从 LLM 输出取出 JSON（剥代码块/前后缀），失败返回 None。"""
    if not raw:
        return None
    text = raw.strip()
    fence = re.search(r"```(?:json)?\s*(\{.*\})\s*```", text, re.DOTALL)
    if fence:
        text = fence.group(1)
    else:
        start, end = text.find("{"), text.rfind("}")
        if start != -1 and end != -1 and end > start:
            text = text[start : end + 1]
    try:
        return json.loads(text)
    except (ValueError, TypeError):
        return None


async def agenerate_feature_detail_sections(
    project_id: Any, source: str
) -> list[dict[str, Any]]:
    """Step 2：把**单个功能点/模块的原文**结构化为柔性 sections（按需调用）。

    best-effort：无 Provider / LLM 失败 / 解析失败 → 返回空列表（前端回退展示原文），绝不反噬。
    """
    src = str(source or "").strip()
    if not src:
        return []
    project = await _aget_project(project_id)
    space = getattr(project, "space", None) if project is not None else None
    resolved = await ProviderConfigService.aresolve_or_error(project=space)
    if isinstance(resolved, ProviderMissingError):
        return []

    from agents.llm_factory import build_chat_model

    legacy = await aget_legacy_anthropic_config()
    model = legacy.get("default_model") or _MODEL_FALLBACK
    caps_out = min(
        _DETAIL_DESIRED_OUTPUT_TOKENS,
        ModelCapabilities.get(str(resolved.provider_type), strip_context_suffix(model)).max_output_tokens,
    )
    messages = [
        SystemMessage(content=_DETAIL_SYSTEM_PROMPT),
        HumanMessage(content=src[:_DETAIL_MAX_SOURCE_CHARS]),
    ]
    start = perf_counter()
    try:
        with use_call_source(CallSource.FEATURE_LIST_PARSE):
            chat_model = build_chat_model(
                resolved, model, max_output_tokens=caps_out, streaming=False
            )
            ai_msg = await chat_model.ainvoke(messages)
    except Exception as exc:  # noqa: BLE001 — 详情 best-effort，失败回退原文
        await _record_usage(
            resolved, model, upstream_status_code=parse_upstream_status(exc)
        )
        logger.warning(
            "feature_detail_parse_failed",
            project_id=str(project_id),
            source_chars=len(src),
            model=model,
            error_type=type(exc).__name__,
            error=redact_secrets_in_text(str(exc))[:200],
            component=_COMPONENT,
            category="caller",
        )
        return []

    usage = getattr(ai_msg, "usage_metadata", None) or {}
    await _record_usage(
        resolved,
        model,
        prompt_tokens=usage.get("input_tokens", 0) if isinstance(usage, dict) else 0,
        completion_tokens=usage.get("output_tokens", 0) if isinstance(usage, dict) else 0,
        duration_ms=int((perf_counter() - start) * 1000),
    )
    content = getattr(ai_msg, "content", "")
    if isinstance(content, list):
        content = " ".join(
            str(c.get("text", "")) if isinstance(c, dict) else str(c) for c in content
        )
    sections = _normalize_sections(_loads_sections_raw(str(content or "")))
    logger.info(
        "feature_detail_parsed",
        project_id=str(project_id),
        source_chars=len(src),
        section_count=len(sections),
        component=_COMPONENT,
        category="caller",
    )
    return sections


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
