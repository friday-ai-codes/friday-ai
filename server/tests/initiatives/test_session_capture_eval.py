"""Phase 143 Wave 0：Session Capture 三档价值评估契约（RED）。"""

from __future__ import annotations

import importlib
import json
import uuid
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from agents.call_source import get_call_source
from initiatives.models import ProjectMemory, SessionCapture, SessionCaptureStatus
from initiatives.services import CaptureService

_MODULE_NAME = "initiatives.services.session_capture_eval"
_FORBIDDEN_IMPORTS = (
    "evaluate_writeback_quality",
    "knowledge.llm_grader",
    "repo_router",
    "MemoryService",
    "record_hook_writeback",
)


def _load_eval_module():
    """在测试执行期加载待实现模块，确保 RED 文件自身可被 pytest 收集。"""

    return importlib.import_module(_MODULE_NAME)


def _resolved(default_model: str = "test-model") -> SimpleNamespace:
    return SimpleNamespace(
        extra={"default_model": default_model} if default_model else {},
        provider_type=SimpleNamespace(value="anthropic"),
        provider="anthropic",
        source="system",
    )


def _response(payload: dict[str, object]) -> SimpleNamespace:
    return SimpleNamespace(
        content=json.dumps(payload, ensure_ascii=False),
        usage_metadata={
            "input_tokens": 17,
            "output_tokens": 9,
            "total_tokens": 26,
        },
        response_metadata={},
    )


def _patch_evaluator_dependencies(
    monkeypatch: pytest.MonkeyPatch,
    module,
    *,
    resolved: object,
    model: object,
    usage: AsyncMock | None = None,
) -> AsyncMock:
    usage = usage or AsyncMock()
    monkeypatch.setattr(
        "services.provider_config.ProviderConfigService.aresolve",
        AsyncMock(return_value=resolved),
    )
    monkeypatch.setattr("agents.llm_factory.build_chat_model", lambda *args, **kwargs: model)
    monkeypatch.setattr(
        module,
        "build_chat_model",
        lambda *args, **kwargs: model,
        raising=False,
    )
    monkeypatch.setattr("interactions.ledger.arecord_llm_usage", usage)
    monkeypatch.setattr(module, "arecord_llm_usage", usage, raising=False)
    return usage


async def _evaluate(module, *, question: str = "问题", answer: str = "答案"):
    return await module.SessionCaptureEvaluator().evaluate(
        capture_id=str(uuid.uuid4()),
        question=question,
        answer=answer,
    )


@pytest.mark.parametrize("tier", ["high", "medium", "low"])
async def test_eval_writes_high_medium_low_and_essence(
    monkeypatch: pytest.MonkeyPatch,
    tier: str,
) -> None:
    module = _load_eval_module()
    model = SimpleNamespace(
        ainvoke=AsyncMock(
            return_value=_response(
                {
                    "value_tier": tier,
                    "distilled_essence": f"{tier} 可独立召回的根因、方案与验证证据",
                }
            )
        )
    )
    _patch_evaluator_dependencies(
        monkeypatch,
        module,
        resolved=_resolved(),
        model=model,
    )

    result = await _evaluate(module)

    assert result.value_tier == tier
    assert result.distilled_essence.strip()


@pytest.mark.parametrize(
    "content",
    [
        "not-json",
        '{"value_tier":"critical","distilled_essence":"有内容"}',
        '{"value_tier":"high"}',
        '{"value_tier":"low","distilled_essence":"   "}',
    ],
)
async def test_invalid_json_or_tier_is_failure_not_low(
    monkeypatch: pytest.MonkeyPatch,
    content: str,
) -> None:
    module = _load_eval_module()
    model = SimpleNamespace(ainvoke=AsyncMock(return_value=SimpleNamespace(content=content)))
    _patch_evaluator_dependencies(
        monkeypatch,
        module,
        resolved=_resolved(),
        model=model,
    )

    with pytest.raises(module.SessionCaptureEvaluationError):
        await _evaluate(module)


@pytest.mark.parametrize(
    ("question", "answer"),
    [
        ("", "答案"),
        ("问题", ""),
        ("   ", "答案"),
        ("问题", "\n\t"),
    ],
)
async def test_empty_input_skips_llm_and_fails(
    monkeypatch: pytest.MonkeyPatch,
    question: str,
    answer: str,
) -> None:
    module = _load_eval_module()
    aresolve = AsyncMock(return_value=_resolved())
    model = SimpleNamespace(ainvoke=AsyncMock())
    monkeypatch.setattr(
        "services.provider_config.ProviderConfigService.aresolve",
        aresolve,
    )
    monkeypatch.setattr(module, "build_chat_model", lambda *args, **kwargs: model, raising=False)

    with pytest.raises(module.SessionCaptureEvaluationError):
        await _evaluate(module, question=question, answer=answer)

    aresolve.assert_not_awaited()
    model.ainvoke.assert_not_awaited()


async def test_missing_default_model_fails_without_guessing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = _load_eval_module()
    model = SimpleNamespace(ainvoke=AsyncMock())
    build_model = AsyncMock(return_value=model)
    monkeypatch.setattr(
        "services.provider_config.ProviderConfigService.aresolve",
        AsyncMock(return_value=_resolved(default_model="")),
    )
    monkeypatch.setattr(module, "build_chat_model", build_model, raising=False)
    monkeypatch.setattr("agents.llm_factory.build_chat_model", build_model)

    with pytest.raises(module.SessionCaptureEvaluationError):
        await _evaluate(module)

    build_model.assert_not_awaited()
    model.ainvoke.assert_not_awaited()


@pytest.mark.django_db(transaction=True)
async def test_eval_failure_keeps_capture_and_redacts_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = _load_eval_module()
    token = "sk-ant-abcdefghijklmnopqrstuvwxyz123456"
    capture_result = await CaptureService().persist(
        question="为何失败？",
        answer="保留原始 Capture",
        session_id=f"eval-failure-{uuid.uuid4()}",
        initiated_by_user_id="eval-test",
    )
    model = SimpleNamespace(ainvoke=AsyncMock(side_effect=RuntimeError(f"upstream {token}")))
    _patch_evaluator_dependencies(
        monkeypatch,
        module,
        resolved=_resolved(),
        model=model,
    )

    with pytest.raises(module.SessionCaptureEvaluationError) as exc_info:
        await module.SessionCaptureEvaluator().evaluate(
            capture_id=str(capture_result.capture.id),
            question=capture_result.capture.question,
            answer=capture_result.capture.answer,
        )

    assert token not in str(exc_info.value)
    capture = await SessionCapture.objects.aget(pk=capture_result.capture.id)
    assert capture.status == SessionCaptureStatus.PENDING_EVAL
    assert capture.question == capture_result.capture.question
    assert capture.answer == capture_result.capture.answer


@pytest.mark.parametrize("upstream_failure", [False, True])
async def test_eval_records_usage_with_session_capture_eval(
    monkeypatch: pytest.MonkeyPatch,
    upstream_failure: bool,
) -> None:
    module = _load_eval_module()
    seen_call_sources: list[str | None] = []

    class UpstreamError(RuntimeError):
        status_code = 429

    async def _invoke(_messages):
        seen_call_sources.append(get_call_source())
        if upstream_failure:
            raise UpstreamError("rate limited")
        return _response(
            {
                "value_tier": "high",
                "distilled_essence": "独立结论与验证证据",
            }
        )

    usage = AsyncMock()
    model = SimpleNamespace(ainvoke=AsyncMock(side_effect=_invoke))
    _patch_evaluator_dependencies(
        monkeypatch,
        module,
        resolved=_resolved(),
        model=model,
        usage=usage,
    )

    if upstream_failure:
        with pytest.raises(module.SessionCaptureEvaluationError):
            await _evaluate(module)
    else:
        await _evaluate(module)

    assert seen_call_sources == ["session_capture_eval"]
    usage.assert_awaited_once()
    kwargs = usage.await_args.kwargs
    assert kwargs["call_source"] == "session_capture_eval"
    assert kwargs["source"] == "initiatives"
    assert kwargs["duration_ms"] >= 0
    if upstream_failure:
        assert kwargs["upstream_status_code"] == 429
    else:
        assert kwargs["prompt_tokens"] == 17
        assert kwargs["completion_tokens"] == 9
        assert kwargs["ttft_ms"] is not None


def test_eval_module_does_not_import_quality_gates() -> None:
    module_path = (
        Path(__file__).parents[2] / "initiatives" / "services" / "session_capture_eval.py"
    )
    assert module_path.exists(), "Phase 143 evaluator module 尚未实现"
    source = module_path.read_text(encoding="utf-8")
    for forbidden in _FORBIDDEN_IMPORTS:
        assert forbidden not in source


@pytest.mark.django_db(transaction=True)
async def test_eval_does_not_write_project_memory(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = _load_eval_module()
    model = SimpleNamespace(
        ainvoke=AsyncMock(
            return_value=_response(
                {
                    "value_tier": "medium",
                    "distilled_essence": "只返回精华，不写 ProjectMemory",
                }
            )
        )
    )
    _patch_evaluator_dependencies(
        monkeypatch,
        module,
        resolved=_resolved(),
        model=model,
    )
    before = await ProjectMemory.objects.acount()

    await _evaluate(module)

    assert await ProjectMemory.objects.acount() == before
