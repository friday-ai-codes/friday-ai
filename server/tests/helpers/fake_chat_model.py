"""FakeChatModel —— Phase 测试脚手架。
用法（与 `agents.llm_factory.build_chat_model` 配对使用）:
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
关键修补（RESEARCH Pitfall A 实测）：
 `GenericFakeChatModel` 未 override `bind_tools`，
 `BaseChatModel.bind_tools` 默认 `raise NotImplementedError`。
 本类补实现 `bind_tools(self, tools, **kw) -> self` —— fake 不真走 tool
 binding，ReAct loop 从预置 `tool_calls` 序列回放。
参考：
 - `project-docs/phases/work-item/work-item.md` Pattern 3
 - `project-docs/phases/work-item/work-item.md` Pitfall A / G
 - `project-docs/phases/work-item/work-item.md`
"""
from __future__ import annotations
from collections.abc import Sequence
from typing import Any
from langchain_core.language_models import GenericFakeChatModel
from langchain_core.messages import AIMessage
from langchain_core.runnables import Runnable
from langchain_core.tools import BaseTool
class FakeChatModel(GenericFakeChatModel):
 """测试用 LangChain BaseChatModel（GenericFakeChatModel 薄包装 + bind_tools override）。
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
 responses: Sequence[str] =,
 tool_calls: Sequence[Sequence[dict[str, Any]]] =,
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
 tool_calls=list(tc) if tc else,
 usage_metadata=dict(default_usage),
 )
 for r, tc in zip(
 responses,
 tool_calls or [] * len(responses),
 strict=False,
 )
 ]
 super.__init__(messages=iter(messages))
 def bind_tools(
 self,
 tools: Sequence[dict[str, Any] | type | Any | BaseTool],
 **kwargs: Any,
 ) -> Runnable:
 """Stub：返回 self（fake 不真走 tool binding；ReAct loop 从预置 tool_calls 回放）。
 Pitfall A 修补 —— 基类 `GenericFakeChatModel.bind_tools` 继承自
 `BaseChatModel.bind_tools` 默认抛 ``NotImplementedError``；
 契约测试需要 `model.bind_tools(tools)` 调用链能正常跑通。
 """
 return self
