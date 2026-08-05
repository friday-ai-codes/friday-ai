"""项目描述自动生成（#2）——按 feature list 用 AI 重写项目描述。

触发：feature_list 工件创建/更新后自动调用（``ArtifactListCreateView`` / ``ArtifactDetailView``），
也可经 ``POST /api/projects/<id>/description/generate/`` 手动触发。

best-effort 设计：无 Provider 凭证 / 无 feature / LLM 失败 / 任何异常 → 返回 None、不改描述、
不报错、绝不反噬主流程（与 feature_list_extractor 共用 LLM seam）。脱敏不可绕过。
"""

from __future__ import annotations

from time import perf_counter
from typing import Any

import structlog
from asgiref.sync import sync_to_async
from langchain_core.messages import HumanMessage, SystemMessage

from agents.call_source import CallSource, use_call_source
from common.logging import redact_secrets_in_text
from initiatives.services.feature_list_service import FeatureListService
from interactions.ledger import arecord_llm_usage, parse_upstream_status
from services.provider_config import (
    ProviderConfigService,
    ProviderMissingError,
    aget_legacy_anthropic_config,
)

logger = structlog.get_logger(__name__)

__all__ = ["ProjectDescriptionService"]

_COMPONENT = "initiatives.project_description"
_MODEL_FALLBACK = "claude-sonnet-4-20250514"
_MAX_FEATURES = 80

_SYSTEM_PROMPT = (
    "你是资深产品经理。根据给定的项目功能清单，用**一句话**（不超过 60 字）"
    "中文概述这个软件项目的核心价值与范围。直接输出描述本身，"
    "不要任何前后缀、不要引号、不要列点、不要解释。"
)


class ProjectDescriptionService:
    """按 feature list 自动生成/更新项目描述（best-effort）。"""

    async def agenerate_and_save(
        self, project_id: Any, user: Any, *, initiated_by_user_id: Any = None
    ) -> str | None:
        started = perf_counter()
        try:
            project = await self._aget_project(project_id)
            if project is None:
                return None

            names = await self._afeature_names(project_id)
            if not names:
                return None

            outline = "\n".join(f"- {n}" for n in names[:_MAX_FEATURES])
            raw = await self._allm(project, outline)
            if not raw:
                return None

            description = redact_secrets_in_text(raw).strip().strip('"').strip()[:500]
            if not description:
                return None

            await self._asave(project_id, description)
            logger.info(
                "project_description_autogen_completed",
                project_id=str(project_id),
                feature_count=len(names),
                length=len(description),
                duration_ms=round((perf_counter() - started) * 1000, 2),
                category="caller",
                component=_COMPONENT,
            )
            return description
        except Exception as exc:  # noqa: BLE001 — best-effort，绝不反噬主流程
            logger.warning(
                "project_description_autogen_failed",
                project_id=str(project_id),
                error=str(exc),
                category="caller",
                component=_COMPONENT,
            )
            return None

    @sync_to_async
    def _aget_project(self, project_id: Any) -> Any:
        from initiatives.models import Project

        return Project.objects.select_related("space").filter(id=project_id).first()

    async def _afeature_names(self, project_id: Any) -> list[str]:
        tree = await FeatureListService().build_tree(project_id)
        names: list[str] = []
        for module in tree.get("modules", []):
            for feature in module.get("features", []):
                name = str(feature.get("name") or "").strip()
                if name:
                    names.append(name)
        return names

    async def _allm(self, project: Any, outline: str) -> str:
        from agents.llm_factory import build_chat_model

        space = getattr(project, "space", None)
        result = await ProviderConfigService.aresolve_or_error(project=space)
        if isinstance(result, ProviderMissingError):
            # 无凭证：静默跳过（auto 路径不阻断），不抛。
            return ""
        legacy = await aget_legacy_anthropic_config()
        model = legacy.get("default_model") or _MODEL_FALLBACK

        messages = [
            SystemMessage(content=_SYSTEM_PROMPT),
            HumanMessage(
                content=f"项目「{getattr(project, 'name', '') or '未命名'}」功能清单：\n{outline}"
            ),
        ]
        start = perf_counter()
        ttft_ms: int | None = None
        try:
            with use_call_source(CallSource.BOARD_SPLIT):
                chat_model = build_chat_model(result, model, max_output_tokens=256, streaming=False)
                ai_msg = await chat_model.ainvoke(messages)
            ttft_ms = int((perf_counter() - start) * 1000)
        except Exception as exc:  # noqa: BLE001
            # ⛔ 不能静默吞：此前这里不落任何日志，线上排障只能靠本地复现才定位到
            # 网关 usage 解析 TypeError（用户看到的是「未配置 AI Provider」误导提示）。
            logger.warning(
                "project_description_llm_failed",
                model=model,
                provider=str(getattr(result, "provider_type", "")),
                error=redact_secrets_in_text(str(exc))[:500],
                category="caller",
                component=_COMPONENT,
            )
            await self._record_usage(
                result, model, ttft_ms=None, upstream_status_code=parse_upstream_status(exc)
            )
            return ""

        usage = getattr(ai_msg, "usage_metadata", None) or {}
        await self._record_usage(
            result,
            model,
            ttft_ms=ttft_ms,
            prompt_tokens=usage.get("input_tokens", 0) if isinstance(usage, dict) else 0,
            completion_tokens=usage.get("output_tokens", 0) if isinstance(usage, dict) else 0,
            duration_ms=int((perf_counter() - start) * 1000),
        )
        content = getattr(ai_msg, "content", "")
        if isinstance(content, list):
            content = " ".join(
                str(c.get("text", "")) if isinstance(c, dict) else str(c) for c in content
            )
        return str(content or "")

    @sync_to_async
    def _asave(self, project_id: Any, description: str) -> None:
        from django.utils import timezone

        from initiatives.models import Project

        Project.objects.filter(id=project_id).update(
            description=description, updated_at=timezone.now()
        )

    async def _record_usage(
        self,
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
                call_source=CallSource.BOARD_SPLIT.value,
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
