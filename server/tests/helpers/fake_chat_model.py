"""FakeChatModel —— initial implementation contract 测试脚手架。

用法（与 `agents.llm_factory.build_chat_model` 配对使用）::

    from tests.helpers.fake_chat_model import FakeChatModel

    def test_xxx(monkeypatch: pytest.MonkeyPatch) -> None:
        fake = FakeChatModel(responses=["hello"])
        monkeypatch.setattr(
            "agents.llm_factory.build_chat_model",
            lambda *a, **kw: fake,
        )
        runner = LangChainAgentRunner(config)
        events = [e async for e in runner.stream("hi")]
        ...

实现策略：
    继承 ``GenericFakeChatModel`` 复用其 ``messages: Iterator[AIMessage]``
    pydantic 字段 + ``ainvoke`` / ``_generate`` 等现成链路；但 override
    ``_stream`` / ``_astream`` / ``bind_tools`` 以修补两个实测问题：

    1. **Pitfall A**：``GenericFakeChatModel.bind_tools`` 继承自
       ``BaseChatModel.bind_tools``，默认抛 ``NotImplementedError``；
       ``FakeChatModel`` 补实现返回 self（fake 不真走 tool binding，
       ReAct loop 从预置 ``tool_calls`` 序列回放）。
    2. **Empty-content + tool_calls 场景**：基类 ``_stream`` 对 content==""
       且无 additional_kwargs 的 AIMessage 不 yield 任何 chunk（LangChain
       ``generator_adder`` 随后抛 "No generation chunks were returned"）。
       契约测试中 tool_call turn 的 content 一般为 ""，必须在 fake 层自
       yield 一个含 ``tool_call_chunks`` + ``usage_metadata`` 的
       ``AIMessageChunk`` 让 runner ``aimsg = None + chunk`` 累加后
       ``aimsg.tool_calls`` 与预置一致。

参考：
    - ``project docs`` Pattern 3
    - ``project docs`` Pitfall A / G
    - ``project docs`` contract
    - ``server/tests/test_langchain_runner_core.py::_InlineFakeChatModel``
      （Wave 内联实现，本 helper 对齐其 ``_astream`` 行为）
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator, Iterator, Sequence
from typing import Any

from langchain_core.callbacks import (
    AsyncCallbackManagerForLLMRun,
    CallbackManagerForLLMRun,
)
from langchain_core.language_models import GenericFakeChatModel
from langchain_core.messages import AIMessage, AIMessageChunk, BaseMessage
from langchain_core.outputs import ChatGenerationChunk
from langchain_core.runnables import Runnable
from langchain_core.tools import BaseTool


class FakeChatModel(GenericFakeChatModel):
    """测试用 LangChain BaseChatModel（GenericFakeChatModel 薄包装 + tool_calls 回放 override）。

    Parameters:
        responses: 每 turn 的 AIMessage.content 字符串序列。长度决定回放 turn 数。
        tool_calls: 与 responses 一一对应的 `tool_calls` 列表；空列表表示该 turn 无工具调用。
            传入非空时必须与 responses 等长，否则 ``ValueError``。
        usage_metadata: AIMessage.usage_metadata 字段；缺省为
            ``{"input_tokens": 10, "output_tokens": 5, "total_tokens": 15}``，
            用于让 `_extract_usage` 六字段分派有非零输入。
    """

    def __init__(
        self,
        *,
        responses: Sequence[str] = (),
        tool_calls: Sequence[Sequence[dict[str, Any]]] = (),
        usage_metadata: dict[str, int] | None = None,
    ) -> None:
        if tool_calls and len(tool_calls) != len(responses):
            raise ValueError("responses / tool_calls 长度必须一致")
        default_usage = usage_metadata or {
            "input_tokens": 10,
            "output_tokens": 5,
            "total_tokens": 15,
        }
        messages = [
            AIMessage(
                content=r,
                tool_calls=list(tc) if tc else [],
                usage_metadata=dict(default_usage),
            )
            for r, tc in zip(
                responses,
                tool_calls or [[]] * len(responses),
                strict=False,
            )
        ]
        super().__init__(messages=iter(messages))

    def bind_tools(
        self,
        tools: Sequence[dict[str, Any] | type | Any | BaseTool],
        **kwargs: Any,
    ) -> Runnable:
        """Stub：返回 self（fake 不真走 tool binding；ReAct loop 从预置 tool_calls 回放）。

        Pitfall A 修补 —— 基类 ``GenericFakeChatModel.bind_tools`` 继承自
        ``BaseChatModel.bind_tools`` 默认抛 ``NotImplementedError``；
        契约测试需要 ``model.bind_tools(tools)`` 调用链能正常跑通。
        """
        return self

    # ------------------------------------------------------------------
    # _stream / _astream override：让 tool_call + empty content 场景也 yield 一个 chunk
    # ------------------------------------------------------------------

    def _build_chunk(self, message: AIMessage) -> ChatGenerationChunk:
        """把一条预置 AIMessage 打包成单个 ChatGenerationChunk（含 tool_call_chunks）。"""
        tool_call_chunks: list[dict[str, Any]] = [
            {
                "name": tc.get("name"),
                "args": json.dumps(tc.get("args", {})),
                "id": tc.get("id") or "",
                "index": i,
            }
            for i, tc in enumerate(message.tool_calls)
        ]
        return ChatGenerationChunk(
            message=AIMessageChunk(
                content=message.content,
                tool_call_chunks=tool_call_chunks,
                usage_metadata=message.usage_metadata,
            )
        )

    def _stream(  # type: ignore[override]
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager: CallbackManagerForLLMRun | None = None,
        **kwargs: Any,
    ) -> Iterator[ChatGenerationChunk]:
        """单 chunk 回放：含 content + tool_call_chunks + usage_metadata。

        与 Wave ``_InlineFakeChatModel._astream`` 行为对齐。基类 ``_stream`` 在
        content="" + 无 additional_kwargs 场景下会 yield 0 chunks（触发 LangChain
        "No generation chunks were returned"），本 override 保证每 turn 至少 1 chunk。
        """
        try:
            message = next(self.messages)
        except StopIteration:
            return
        message_ = AIMessage(content=message) if isinstance(message, str) else message
        yield self._build_chunk(message_)

    async def _astream(  # type: ignore[override]
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager: AsyncCallbackManagerForLLMRun | None = None,
        **kwargs: Any,
    ) -> AsyncIterator[ChatGenerationChunk]:
        try:
            message = next(self.messages)
        except StopIteration:
            return
        message_ = AIMessage(content=message) if isinstance(message, str) else message
        yield self._build_chunk(message_)
