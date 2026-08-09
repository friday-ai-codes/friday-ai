"""``services/code_graph/module_summary.py`` 验收测（MOD-03）。

覆盖 D-09/D-10/D-11 与 T-125-02/03。
"""

from __future__ import annotations

import json
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest

from agents.call_source import CallSource, get_call_source
from tests.helpers.fake_chat_model import FakeChatModel

pytestmark = pytest.mark.django_db(transaction=True)

_ARESOLVE = "services.provider_config.ProviderConfigService.aresolve"
_BUILD = "agents.llm_factory.build_chat_model"

_MEMBERS_OK = [
    {
        "symbol_id": f"id-{i}",
        "name": f"fn_{i}",
        "file_path": f"pkg/mod_{i % 2}.py",
        "symbol_type": "FUNCTION",
        "degree": i,
    }
    for i in range(6)
]


def _resolved(default_model: str = "test-model") -> SimpleNamespace:
    return SimpleNamespace(
        extra={"default_model": default_model},
        credential_id="cred-1",
        max_concurrency=0,
    )


def _summary_json(**overrides: Any) -> str:
    payload = {
        "key_files": ["pkg/mod_0.py", "pkg/mod_1.py"],
        "entry_points": ["fn_0", "fn_1"],
        "responsibility": "Handles module orchestration and routing.",
    }
    payload.update(overrides)
    return json.dumps(payload, ensure_ascii=False)


@pytest.mark.asyncio
async def test_uses_call_source_module_summary() -> None:
    """``agenerate_module_summary`` 经 ``use_call_source(MODULE_SUMMARY)`` 包裹 LLM。

    （Req: MOD-03, 决策: D-09）
    """
    from services.code_graph.module_summary import agenerate_module_summary

    captured: dict[str, Any] = {}

    class _CaptureModel(FakeChatModel):
        async def ainvoke(self, input: Any, config: Any = None, **kwargs: Any) -> Any:  # noqa: A002
            captured["call_source"] = get_call_source()
            return await super().ainvoke(input, config=config, **kwargs)

    with (
        patch(_ARESOLVE, new=AsyncMock(return_value=_resolved())),
        patch(_BUILD, return_value=_CaptureModel(responses=[_summary_json()])),
    ):
        result = await agenerate_module_summary(_MEMBERS_OK)

    assert result is not None
    assert captured["call_source"] == CallSource.MODULE_SUMMARY.value
    data = json.loads(result)
    assert data["key_files"]
    assert data["entry_points"]
    assert data["responsibility"]


@pytest.mark.asyncio
async def test_metadata_only_prompt_no_source_body() -> None:
    """prompt 仅含成员元数据，不含源码正文。

    （Req: MOD-03, 决策: D-10, 威胁: T-125-02）
    """
    from services.code_graph.module_summary import (
        agenerate_module_summary,
        build_module_summary_prompt,
    )

    # 含源码字段的成员：prompt 构建器必须忽略正文。
    dirty_members = [
        {
            **m,
            "source": "def secret():\n    api_key = 'sk-leak'\n",
            "body": "class Evil: pass",
            "code": "print('nope')",
            "content": "full source body must not appear",
        }
        for m in _MEMBERS_OK
    ]
    prompt = build_module_summary_prompt(dirty_members)
    assert "sk-leak" not in prompt
    assert "class Evil" not in prompt
    assert "full source body" not in prompt
    assert "pkg/mod_0.py" in prompt
    assert "fn_0" in prompt
    assert "FUNCTION" in prompt

    captured_messages: list[Any] = []

    class _CaptureModel(FakeChatModel):
        async def ainvoke(self, input: Any, config: Any = None, **kwargs: Any) -> Any:  # noqa: A002
            captured_messages.append(input)
            return await super().ainvoke(input, config=config, **kwargs)

    with (
        patch(_ARESOLVE, new=AsyncMock(return_value=_resolved())),
        patch(_BUILD, return_value=_CaptureModel(responses=[_summary_json()])),
    ):
        await agenerate_module_summary(dirty_members)

    assert captured_messages
    blob = " ".join(str(getattr(m, "content", m)) for m in captured_messages[0])
    assert "sk-leak" not in blob
    assert "class Evil" not in blob
    assert "full source body" not in blob


@pytest.mark.asyncio
async def test_failsoft_returns_none_on_llm_error() -> None:
    """LLM 失败 fail-soft 返回 None，不阻断社区落库。

    （Req: MOD-03, 决策: D-11, 威胁: T-125-03）
    """
    from services.code_graph.module_summary import agenerate_module_summary

    class _BrokenModel:
        def bind(self, **_kwargs: Any) -> _BrokenModel:
            return self

        async def ainvoke(self, *_a: Any, **_k: Any) -> Any:
            raise RuntimeError("upstream boom token=sk-secret")

    with (
        patch(_ARESOLVE, new=AsyncMock(return_value=_resolved())),
        patch(_BUILD, return_value=_BrokenModel()),
    ):
        result = await agenerate_module_summary(_MEMBERS_OK)

    assert result is None

    # 规模门槛：size < 5 直接 None，不调 LLM。
    tiny = _MEMBERS_OK[:3]
    with (
        patch(_ARESOLVE, new=AsyncMock(return_value=_resolved())) as aresolve,
        patch(_BUILD, return_value=FakeChatModel(responses=[_summary_json()])) as build,
    ):
        tiny_result = await agenerate_module_summary(tiny)
    assert tiny_result is None
    aresolve.assert_not_called()
    build.assert_not_called()


def test_render_module_summary_helper() -> None:
    """``render_module_summary`` 将结构化摘要渲染为消费端文本。

    （Req: MOD-03, 决策: D-11）
    """
    from services.code_graph.module_summary import render_module_summary

    raw = _summary_json()
    text = render_module_summary(raw)
    assert "pkg/mod_0.py" in text
    assert "fn_0" in text
    assert "Handles module orchestration" in text
    # 稳定字段顺序 / 标题
    assert "关键文件" in text or "key_files" in text.lower() or "Key files" in text
    assert "职责" in text or "responsibility" in text.lower() or "Responsibility" in text

    # 非法 JSON → 原文兜底（消毒后）
    fallback = render_module_summary("plain text summary")
    assert "plain text summary" in fallback
