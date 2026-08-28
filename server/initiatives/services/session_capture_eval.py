"""Session Capture 严格三档价值评估器（Phase 143）。

评估器只负责调用 Friday 默认 LLM 并返回强类型结果，不读取或写入 Capture ORM，
也不触碰 ProjectMemory。外部模型输出是不可信输入：仅接受完整 JSON object，
档位必须是 ``high``、``medium`` 或 ``low``，精华必须非空且再次脱敏。
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from time import perf_counter
from typing import Any, Literal

import structlog
from langchain_core.messages import HumanMessage

from agents.call_source import CallSource, use_call_source
from agents.llm_factory import build_chat_model, content_to_text
from common.logging import redact_secrets_in_text
from interactions.ledger import arecord_llm_usage, parse_upstream_status
from services.provider_config import ProviderConfigService

logger = structlog.get_logger(__name__)

__all__ = [
    "SessionCaptureEvaluationError",
    "SessionCaptureEvalResult",
    "SessionCaptureEvaluator",
]

_COMPONENT = "knowledge"
_CALL_SOURCE = CallSource.SESSION_CAPTURE_EVAL.value
_VALID_TIERS = frozenset({"high", "medium", "low"})


class SessionCaptureEvaluationError(RuntimeError):
    """可重试的 Session Capture 评估失败。"""


@dataclass(frozen=True)
class SessionCaptureEvalResult:
    """经闭集校验和脱敏后的价值评估结果。"""

    value_tier: Literal["high", "medium", "low"]
    distilled_essence: str


class SessionCaptureEvaluator:
    """使用 Friday 默认模型独立判断 Capture 价值，不执行任何持久化。"""

    async def evaluate(
        self,
        *,
        capture_id: str,
        question: str,
        answer: str,
        attempt: int = 0,
        initiated_by_user_id: str | None = None,
    ) -> SessionCaptureEvalResult:
        started = perf_counter()
        user_label = str(initiated_by_user_id or "system")
        self._log(
            "info",
            "session_capture_eval_started",
            capture_id=str(capture_id),
            status="evaluating",
            attempt=attempt,
            initiated_by_user_id=user_label,
        )

        try:
            question_text = str(question or "").strip()
            answer_text = str(answer or "").strip()
            if not question_text or not answer_text:
                raise SessionCaptureEvaluationError("question 和 answer 必须非空")

            resolved = await ProviderConfigService.aresolve()
            model_name = str(
                (getattr(resolved, "extra", None) or {}).get("default_model", "")
            ).strip()
            if not model_name:
                raise SessionCaptureEvaluationError("Friday 默认模型未配置")

            model = build_chat_model(resolved, model_name, streaming=False)
            prompt = self._build_prompt(question=question_text, answer=answer_text)
            llm_started = perf_counter()
            try:
                with use_call_source(CallSource.SESSION_CAPTURE_EVAL):
                    response = await model.ainvoke([HumanMessage(content=prompt)])
            except Exception as exc:
                duration_ms = self._duration_ms(llm_started)
                await self._record_usage(
                    resolved=resolved,
                    model_name=model_name,
                    duration_ms=duration_ms,
                    upstream_status_code=parse_upstream_status(exc),
                )
                raise SessionCaptureEvaluationError(self._safe_error(exc)) from exc

            duration_ms = self._duration_ms(llm_started)
            usage = self._extract_usage(response)
            await self._record_usage(
                resolved=resolved,
                model_name=model_name,
                prompt_tokens=usage["input_tokens"],
                completion_tokens=usage["output_tokens"],
                total_tokens=usage["total_tokens"],
                ttft_ms=duration_ms,
                duration_ms=duration_ms,
            )
            result = self._parse_result(content_to_text(getattr(response, "content", "")))
        except SessionCaptureEvaluationError as exc:
            self._log(
                "warning",
                "session_capture_eval_failed",
                capture_id=str(capture_id),
                status="eval_failed",
                attempt=attempt,
                initiated_by_user_id=user_label,
                duration_ms=self._duration_ms(started),
                error=self._safe_error(exc),
            )
            raise
        except Exception as exc:
            safe_error = self._safe_error(exc)
            self._log(
                "warning",
                "session_capture_eval_failed",
                capture_id=str(capture_id),
                status="eval_failed",
                attempt=attempt,
                initiated_by_user_id=user_label,
                duration_ms=self._duration_ms(started),
                error=safe_error,
            )
            raise SessionCaptureEvaluationError(safe_error) from exc

        self._log(
            "info",
            "session_capture_eval_completed",
            capture_id=str(capture_id),
            tier=result.value_tier,
            status="evaluated",
            attempt=attempt,
            initiated_by_user_id=user_label,
            duration_ms=self._duration_ms(started),
        )
        return result

    @staticmethod
    def _build_prompt(*, question: str, answer: str) -> str:
        return (
            "你是 Friday 的会话知识价值评估器。独立判断以下问答是否包含可复用的工程知识，"
            "只输出一个严格 JSON object，不要输出 Markdown、代码围栏或解释：\n"
            '{"value_tier":"high|medium|low","distilled_essence":"..."}\n'
            "value_tier 必须逐字为 high、medium 或 low。distilled_essence 在三种档位下都"
            "必须非空，只保留可复用结论、约束、根因、解决方案和验证证据，并改写为脱离原"
            "会话仍可理解的完整表述；不要包含凭证、token、隐藏思维链或无关对话。\n\n"
            f"问题：\n{question}\n\n回答：\n{answer}"
        )

    @staticmethod
    def _parse_result(text: str) -> SessionCaptureEvalResult:
        try:
            payload = json.loads(text.strip())
        except (json.JSONDecodeError, TypeError) as exc:
            raise SessionCaptureEvaluationError("模型未返回合法 JSON object") from exc
        if not isinstance(payload, dict):
            raise SessionCaptureEvaluationError("模型返回值必须是 JSON object")
        if set(payload) != {"value_tier", "distilled_essence"}:
            raise SessionCaptureEvaluationError("模型返回字段不符合评估合同")

        tier = payload.get("value_tier")
        if not isinstance(tier, str) or tier not in _VALID_TIERS:
            raise SessionCaptureEvaluationError("模型返回了非法价值档位")
        essence_raw = payload.get("distilled_essence")
        if not isinstance(essence_raw, str) or not essence_raw.strip():
            raise SessionCaptureEvaluationError("模型返回的精华为空")
        essence = redact_secrets_in_text(essence_raw).strip()
        if not essence:
            raise SessionCaptureEvaluationError("模型返回的精华脱敏后为空")
        return SessionCaptureEvalResult(
            value_tier=tier,
            distilled_essence=essence,
        )

    @staticmethod
    def _extract_usage(response: Any) -> dict[str, int]:
        metadata = getattr(response, "usage_metadata", None)
        if not isinstance(metadata, dict):
            metadata = {}
        input_tokens = int(metadata.get("input_tokens", 0) or 0)
        output_tokens = int(metadata.get("output_tokens", 0) or 0)
        total_tokens = int(metadata.get("total_tokens", 0) or 0)
        return {
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "total_tokens": total_tokens or input_tokens + output_tokens,
        }

    @staticmethod
    async def _record_usage(
        *,
        resolved: Any,
        model_name: str,
        prompt_tokens: int = 0,
        completion_tokens: int = 0,
        total_tokens: int = 0,
        ttft_ms: int | None = None,
        duration_ms: int | None = None,
        upstream_status_code: int | None = None,
    ) -> None:
        provider_type = getattr(resolved, "provider_type", "")
        provider = str(getattr(provider_type, "value", provider_type) or "")
        try:
            await arecord_llm_usage(
                call_source=_CALL_SOURCE,
                provider=provider,
                model=model_name,
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
                total_tokens=total_tokens,
                ttft_ms=ttft_ms,
                duration_ms=duration_ms,
                upstream_status_code=upstream_status_code,
                failure_type=(
                    str(upstream_status_code) if upstream_status_code is not None else ""
                ),
                source="initiatives",
            )
        except Exception:
            pass

    @staticmethod
    def _duration_ms(started: float) -> int:
        return max(0, int((perf_counter() - started) * 1000))

    @staticmethod
    def _safe_error(exc: BaseException) -> str:
        return redact_secrets_in_text(str(exc))[:300] or type(exc).__name__

    @staticmethod
    def _log(level: str, event: str, **fields: Any) -> None:
        try:
            getattr(logger, level)(
                event,
                category="sampling",
                component=_COMPONENT,
                **fields,
            )
        except Exception:
            pass
