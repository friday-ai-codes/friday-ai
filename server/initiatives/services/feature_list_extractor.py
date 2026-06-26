"""FeatureListExtractor —— feature list 多源输入归一化 + 结构化抽取（BOARD-01，87-02）。

把「杂乱多源 feature list」变成「可逐 feature 建子看板」的结构化拆分（模块→功能点→验收项），
供 87-03 落子看板（每个 feature 一个子看板 work_item，模块作分组）。

两段职责：

- :meth:`FeatureListExtractor.normalize_sources`：三源（文件上传 md / 飞书文档链接回拉 /
  粘贴文本）归一化为统一原文。飞书链接复用 Phase 83 回拉（``create_feishu_doc_client_for_project``
  + ``get_document_content``）。各源独立 **fail-soft**：单源缺失/失败仅降级跳过，至少一源即可
  继续；三源全空才抛 ``ValueError``。

- :meth:`FeatureListExtractor.extract_structure`：原文 → 按 markdown 标题分块 + token 预算降级
  （超大 82KB demo 绝不整篇塞 LLM 上下文）→ 每块走 LLM 结构化抽取（**新增 LLM 调用**，赋
  ``call_source="board_split"``，LOGGING-SPEC §4.1）→ 跨块合并去重 → 返回
  ``{modules, features_flat, degraded, chunk_count}``。

可观测（强制）：``feature_list_normalize_completed`` / ``feature_list_extract_started`` /
``_completed`` / ``_failed``（caller，带 ``duration_ms`` / ``chunk_count`` / ``degraded``），
per-chunk ``feature_list_chunk_extracted``（sampling，debug）；正文/异常文本经
``redact_secrets_in_text``，日志仅记长度/块数；LLM 调用经 ``arecord_llm_usage`` 上报
请求/token/TTFT/上游错误码（best-effort，绝不反噬）。

LLM seam：``agents.llm_factory.build_chat_model`` 函数体内 import（FakeChatModel monkeypatch
``agents.llm_factory.build_chat_model`` 即可绕过真实 provider）；provider 解析 seam =
:meth:`_aresolve_model`（测试可 patch）。
"""

from __future__ import annotations

import json
import re
from time import perf_counter
from typing import Any

import structlog
from langchain_core.messages import HumanMessage, SystemMessage

from agents.call_source import CallSource, use_call_source
from agents.tools.feishu_doc_tools import (
    _extract_document_id,
    create_feishu_doc_client_for_project,
)
from common.logging import redact_secrets_in_text
from interactions.ledger import arecord_llm_usage, parse_upstream_status
from services.provider_config import (
    ProviderConfigService,
    ProviderMissingError,
    aget_legacy_anthropic_config,
)

logger = structlog.get_logger(__name__)

__all__ = ["FeatureListExtractor"]

_COMPONENT = "board_split"
_EXTRACT_MODEL_FALLBACK = "claude-sonnet-4-20250514"

# 来源分隔标注（便于抽取定位 + 可观测，不入日志）。
_SRC_FILE = "## [来源:文件]"
_SRC_FEISHU = "## [来源:飞书文档]"
_SRC_PASTED = "## [来源:粘贴]"

# token 预算粗估：中英文混排约 2.5 字符/token（保守偏低，宁可多切块）。
_CHARS_PER_TOKEN = 2.5
# 单块 token 预算上限：超过则二次细切（绝不整篇塞 LLM 上下文，T-87-02-DOS）。
_MAX_CHUNK_TOKENS = 4000
# 整体 token 超此阈值即判定「过大」→ degraded（粗粒度/分批），82KB demo 必然命中。
_DEGRADE_TOKEN_THRESHOLD = 8000

_EXTRACT_SYSTEM_PROMPT = (
    "你是看板拆分助手。请把给定的 feature list 原文拆解为「模块 → 功能点 → 验收项」结构，"
    "每个功能点（feature）对应一个独立的子看板。\n"
    "只输出**严格 JSON**（不要 markdown 代码块、不要解释），schema：\n"
    '{"modules":[{"name":"模块名","features":[{"name":"功能点名",'
    '"description":"功能点原文片段","acceptance":["验收项1","验收项2"]}]}]}\n'
    "无法识别模块时归入 name=\"未分组\"；无验收项时 acceptance 留空数组。"
)


class FeatureListExtractor:
    """feature list 多源归一化 + LLM 结构化抽取（编排，无状态）。"""

    async def normalize_sources(
        self,
        *,
        uploaded_text: str | None = None,
        feishu_url: str | None = None,
        pasted_text: str | None = None,
        space: Any | None = None,
    ) -> str:
        """三源归一化为统一原文（fail-soft，至少一源即可继续）。

        Args:
            uploaded_text: 文件上传的 md 文本（直接采用）。
            feishu_url: 飞书文档链接/ID（经 Phase 83 回拉正文为 markdown）。
            pasted_text: 粘贴文本（直接采用）。
            space: ``projects.models.Space`` 实例，用于解析飞书凭证（飞书源需要）。

        Returns:
            带 ``## [来源:xxx]`` 分隔标注的合并原文。

        Raises:
            ValueError: 三源全空（无可用 feature list 输入源）。
        """
        started = perf_counter()
        parts: list[str] = []
        source_count = 0

        if uploaded_text and uploaded_text.strip():
            parts.append(f"{_SRC_FILE}\n{uploaded_text.strip()}")
            source_count += 1

        if feishu_url and feishu_url.strip():
            try:
                markdown = await self._afetch_feishu(feishu_url.strip(), space=space)
            except Exception as exc:  # noqa: BLE001 — 单源失败 fail-soft 降级跳过
                logger.warning(
                    "feature_list_source_feishu_failed",
                    error=redact_secrets_in_text(str(exc)),
                    error_type=type(exc).__name__,
                    component=_COMPONENT,
                    category="caller",
                )
            else:
                if markdown and markdown.strip():
                    parts.append(f"{_SRC_FEISHU}\n{markdown.strip()}")
                    source_count += 1

        if pasted_text and pasted_text.strip():
            parts.append(f"{_SRC_PASTED}\n{pasted_text.strip()}")
            source_count += 1

        if not parts:
            raise ValueError("无可用 feature list 输入源")

        merged = "\n\n".join(parts)
        logger.info(
            "feature_list_normalize_completed",
            source_count=source_count,
            total_len=len(merged),
            duration_ms=round((perf_counter() - started) * 1000, 2),
            component=_COMPONENT,
            category="caller",
        )
        return merged

    async def _afetch_feishu(self, feishu_url: str, *, space: Any) -> str:
        """飞书链接回拉正文（Phase 83）：URL→document_id→get_document_content markdown。"""
        if space is None:
            raise ValueError("飞书文档源需要 space 以解析飞书应用凭证")
        doc_id = _extract_document_id(feishu_url)
        client = await create_feishu_doc_client_for_project(space)
        markdown, _blocks = await client.get_document_content(doc_id)
        return markdown or ""

    async def extract_structure(
        self,
        raw_text: str,
        *,
        space: Any | None = None,
        initiated_by_user_id: Any = None,
    ) -> dict[str, Any]:
        """原文 → 分块 + token 预算降级 + LLM 抽取 → 结构化拆分。

        Returns:
            ``{"modules": [{"name", "features": [{"name", "description", "acceptance": [...]}]}],
            "features_flat": [{"module", "name", "description", "acceptance": [...]}],
            "degraded": bool, "chunk_count": int}``

        Raises:
            LLM 传输/凭证异常 fail-loud 抛由调用方（87-03/87-04）；异常文本经
            ``redact_secrets_in_text``。单块 JSON 解析失败仅跳过（不反噬整体）。
        """
        started = perf_counter()
        chunks = self._chunk_text(raw_text)
        degraded = self._estimate_tokens(raw_text) > _DEGRADE_TOKEN_THRESHOLD

        logger.info(
            "feature_list_extract_started",
            chunk_count=len(chunks),
            total_len=len(raw_text or ""),
            degraded=degraded,
            initiated_by_user_id=str(initiated_by_user_id)
            if initiated_by_user_id is not None
            else "system",
            component=_COMPONENT,
            category="caller",
        )

        modules_acc: dict[str, dict[str, Any]] = {}
        try:
            for idx, chunk in enumerate(chunks):
                chunk_result = await self._aextract_chunk(chunk, space=space)
                self._merge_modules(modules_acc, chunk_result)
                logger.debug(
                    "feature_list_chunk_extracted",
                    chunk_index=idx,
                    chunk_len=len(chunk),
                    modules=len(chunk_result.get("modules", [])),
                    component=_COMPONENT,
                    category="sampling",
                )
        except Exception as exc:  # noqa: BLE001 — fail-loud，异常文本脱敏后再抛
            logger.error(
                "feature_list_extract_failed",
                error=redact_secrets_in_text(str(exc)),
                error_type=type(exc).__name__,
                chunk_count=len(chunks),
                degraded=degraded,
                duration_ms=round((perf_counter() - started) * 1000, 2),
                component=_COMPONENT,
                category="caller",
            )
            raise

        modules = self._finalize_modules(modules_acc)
        features_flat: list[dict[str, Any]] = []
        for mod in modules:
            for feat in mod["features"]:
                features_flat.append(
                    {
                        "module": mod["name"],
                        "name": feat["name"],
                        "description": feat["description"],
                        "acceptance": feat["acceptance"],
                    }
                )

        logger.info(
            "feature_list_extract_completed",
            chunk_count=len(chunks),
            modules=len(modules),
            features=len(features_flat),
            degraded=degraded,
            duration_ms=round((perf_counter() - started) * 1000, 2),
            component=_COMPONENT,
            category="caller",
        )
        return {
            "modules": modules,
            "features_flat": features_flat,
            "degraded": degraded,
            "chunk_count": len(chunks),
        }

    # ------------------------------------------------------------------
    # 分块 + token 预算
    # ------------------------------------------------------------------

    @staticmethod
    def _estimate_tokens(text: str) -> int:
        """字符数粗估 token（中英文混排保守系数）。"""
        return int(len(text or "") / _CHARS_PER_TOKEN)

    def _chunk_text(self, raw_text: str) -> list[str]:
        """按 markdown 标题（``#``/``##``）切块 + 单块超预算二次细切。

        空文本 → 单空块（仍走一次抽取，返回空模块）；标题前的前导内容自成一块。
        """
        text = (raw_text or "").strip()
        if not text:
            return [""]

        # 以行首 1~2 级标题为切点（保留标题行作为块首）。
        heading = re.compile(r"^#{1,2} ", re.MULTILINE)
        starts = [m.start() for m in heading.finditer(text)]
        raw_chunks: list[str]
        if not starts:
            raw_chunks = [text]
        else:
            raw_chunks = []
            if starts[0] > 0:
                raw_chunks.append(text[: starts[0]].strip())
            bounds = starts + [len(text)]
            for i in range(len(starts)):
                segment = text[bounds[i] : bounds[i + 1]].strip()
                if segment:
                    raw_chunks.append(segment)

        chunks: list[str] = []
        for chunk in raw_chunks:
            if not chunk:
                continue
            if self._estimate_tokens(chunk) > _MAX_CHUNK_TOKENS:
                chunks.extend(self._split_oversize(chunk))
            else:
                chunks.append(chunk)
        return chunks or [""]

    def _split_oversize(self, chunk: str) -> list[str]:
        """单块超 token 预算 → 按行贪心打包到 ``_MAX_CHUNK_TOKENS`` 子块。"""
        budget_chars = int(_MAX_CHUNK_TOKENS * _CHARS_PER_TOKEN)
        sub_chunks: list[str] = []
        buf: list[str] = []
        size = 0
        for line in chunk.splitlines(keepends=True):
            if size + len(line) > budget_chars and buf:
                sub_chunks.append("".join(buf).strip())
                buf, size = [], 0
            # 单行本身就超预算（极端）：硬切。
            if len(line) > budget_chars:
                for i in range(0, len(line), budget_chars):
                    sub_chunks.append(line[i : i + budget_chars].strip())
                continue
            buf.append(line)
            size += len(line)
        if buf:
            sub_chunks.append("".join(buf).strip())
        return [c for c in sub_chunks if c]

    # ------------------------------------------------------------------
    # LLM 抽取 + 解析 + 合并
    # ------------------------------------------------------------------

    async def _aextract_chunk(self, chunk_text: str, *, space: Any) -> dict[str, Any]:
        """单块抽取：LLM → JSON 解析（解析失败返回空模块，不反噬整体）。"""
        if not chunk_text.strip():
            return {"modules": []}
        raw = await self._acall_llm(chunk_text, space=space)
        return self._parse_llm_json(raw)

    async def _aresolve_model(self, space: Any) -> tuple[Any, str]:
        """provider 解析 seam（测试可 patch）：返回 (resolved, model)。

        无凭证 fail-loud（抽取是 87-03/87-04 主路径，缺凭证不可静默成功）。
        """
        result = await ProviderConfigService.aresolve_or_error(project=space)
        if isinstance(result, ProviderMissingError):
            raise ValueError(
                f"未配置 Provider 凭证，无法做 feature list 结构化抽取："
                f"{result.recommended_action}"
            )
        legacy = await aget_legacy_anthropic_config()
        model = legacy.get("default_model") or _EXTRACT_MODEL_FALLBACK
        return result, model

    async def _acall_llm(self, chunk_text: str, *, space: Any) -> str:
        """单轮 LLM 抽取，包裹 ``use_call_source(BOARD_SPLIT)`` + 指标上报（fail-loud）。"""
        from agents.llm_factory import build_chat_model

        resolved, model = await self._aresolve_model(space)
        messages = [
            SystemMessage(content=_EXTRACT_SYSTEM_PROMPT),
            HumanMessage(content=chunk_text),
        ]

        start = perf_counter()
        ttft_ms: int | None = None
        try:
            with use_call_source(CallSource.BOARD_SPLIT):
                chat_model = build_chat_model(
                    resolved, model, max_output_tokens=4096, streaming=False
                )
                ai_msg = await chat_model.ainvoke(messages)
            ttft_ms = int((perf_counter() - start) * 1000)
        except Exception as exc:  # noqa: BLE001 — 上游错误码留痕后 fail-loud 抛
            await self._record_usage(
                resolved,
                model,
                ttft_ms=None,
                upstream_status_code=parse_upstream_status(exc),
            )
            raise

        usage = self._extract_usage(ai_msg)
        await self._record_usage(
            resolved,
            model,
            ttft_ms=ttft_ms,
            prompt_tokens=usage.get("input_tokens", 0),
            completion_tokens=usage.get("output_tokens", 0),
            duration_ms=int((perf_counter() - start) * 1000),
        )
        return self._extract_text(ai_msg)

    def _parse_llm_json(self, raw: str) -> dict[str, Any]:
        """解析 LLM JSON 输出为 ``{modules:[...]}``；解析失败 → 空模块（仅 warning）。"""
        text = (raw or "").strip()
        if not text:
            return {"modules": []}
        # 去掉可能的 markdown code fence。
        if text.startswith("```"):
            text = re.sub(r"^```(?:json)?\s*", "", text)
            text = re.sub(r"\s*```$", "", text).strip()
        try:
            data = json.loads(text)
        except (ValueError, TypeError):
            logger.warning(
                "feature_list_chunk_parse_failed",
                raw_len=len(text),
                component=_COMPONENT,
                category="sampling",
            )
            return {"modules": []}
        modules = data.get("modules") if isinstance(data, dict) else None
        if not isinstance(modules, list):
            return {"modules": []}
        return {"modules": modules}

    @staticmethod
    def _merge_modules(acc: dict[str, dict[str, Any]], chunk_result: dict[str, Any]) -> None:
        """跨块合并：模块按名归并，功能点按名归并（验收项去重合并，描述取首个非空）。"""
        for mod in chunk_result.get("modules", []):
            if not isinstance(mod, dict):
                continue
            name = str(mod.get("name") or "未分组").strip() or "未分组"
            module = acc.setdefault(name, {"name": name, "features": {}})
            for feat in mod.get("features", []):
                if not isinstance(feat, dict):
                    continue
                fname = str(feat.get("name") or "").strip()
                if not fname:
                    continue
                feature = module["features"].setdefault(
                    fname, {"name": fname, "description": "", "acceptance": []}
                )
                desc = str(feat.get("description") or "").strip()
                if desc and not feature["description"]:
                    feature["description"] = desc
                acceptance = feat.get("acceptance")
                if isinstance(acceptance, list):
                    for item in acceptance:
                        item_text = str(item).strip()
                        if item_text and item_text not in feature["acceptance"]:
                            feature["acceptance"].append(item_text)

    @staticmethod
    def _finalize_modules(acc: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
        """合并累加器 → 保序列表（dict→list）。"""
        return [
            {"name": m["name"], "features": list(m["features"].values())}
            for m in acc.values()
        ]

    @staticmethod
    def _extract_text(ai_msg: Any) -> str:
        content = getattr(ai_msg, "content", "")
        if isinstance(content, list):
            parts = [
                str(b.get("text", ""))
                for b in content
                if isinstance(b, dict) and b.get("type") == "text"
            ]
            return "".join(parts)
        return str(content) if content else ""

    @staticmethod
    def _extract_usage(ai_msg: Any) -> dict[str, int]:
        usage = getattr(ai_msg, "usage_metadata", None)
        if not isinstance(usage, dict):
            return {}
        return {
            "input_tokens": int(usage.get("input_tokens", 0) or 0),
            "output_tokens": int(usage.get("output_tokens", 0) or 0),
        }

    @staticmethod
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
        """LLM 指标上报（best-effort，绝不反噬主流程）。"""
        try:
            await arecord_llm_usage(
                call_source=CallSource.BOARD_SPLIT.value,
                provider=str(getattr(resolved, "provider_type", "")),
                model=model,
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
                ttft_ms=ttft_ms,
                duration_ms=duration_ms,
                upstream_status_code=upstream_status_code,
                failure_type=str(upstream_status_code)
                if upstream_status_code is not None
                else "",
                source="initiatives",
            )
        except Exception:  # noqa: BLE001 — 观测绝不反噬主流程
            pass
