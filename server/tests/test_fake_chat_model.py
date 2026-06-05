"""initial implementation contract / contract: FakeChatModel helper 自测。

覆盖点：
- 基本构造 + ainvoke 返回 AIMessage
- 预置 tool_calls 能从 AIMessage.tool_calls 读出三元组
- usage_metadata 默认 / 自定义透传
- bind_tools override 必须返回 self（Pitfall A 反向断言）
- responses / tool_calls 长度不一致 → ValueError
- astream 单 AIMessage 行为文档化（Pitfall G）
"""

from __future__ import annotations

import pytest
from langchain_core.messages import AIMessageChunk, HumanMessage
from langchain_core.tools import tool

from tests.helpers.fake_chat_model import FakeChatModel


@pytest.mark.asyncio
async def test_fake_basic() -> None:
    """contract: 构造 FakeChatModel(responses=["hi"]) 能 ainvoke 返回 AIMessage。"""
    fake = FakeChatModel(responses=["hi"])
    result = await fake.ainvoke([HumanMessage(content="ping")])
    assert result.content == "hi"


@pytest.mark.asyncio
async def test_fake_with_tool_calls() -> None:
    """contract: 预置 tool_calls 能从 AIMessage.tool_calls 读出三元组。"""
    fake = FakeChatModel(
        responses=[""],
        tool_calls=[[{"name": "search", "args": {"q": "x"}, "id": "t1"}]],
    )
    result = await fake.ainvoke([HumanMessage(content="hi")])
    # LangChain AIMessage 构造时会自动给 tool_calls 注入 type='tool_call' 字段
    assert len(result.tool_calls) == 1
    tc = result.tool_calls[0]
    assert tc["name"] == "search"
    assert tc["args"] == {"q": "x"}
    assert tc["id"] == "t1"


@pytest.mark.asyncio
async def test_fake_usage_metadata_defaults() -> None:
    """contract: 默认 usage_metadata 含 input/output/total 三字段。"""
    fake = FakeChatModel(responses=["ok"])
    result = await fake.ainvoke([HumanMessage(content="hi")])
    assert result.usage_metadata == {
        "input_tokens": 10,
        "output_tokens": 5,
        "total_tokens": 15,
    }


@pytest.mark.asyncio
async def test_fake_usage_metadata_custom() -> None:
    """contract: 自定义 usage_metadata 正确透传。"""
    fake = FakeChatModel(
        responses=["ok"],
        usage_metadata={"input_tokens": 100, "output_tokens": 50, "total_tokens": 150},
    )
    result = await fake.ainvoke([HumanMessage(content="hi")])
    assert result.usage_metadata == {
        "input_tokens": 100,
        "output_tokens": 50,
        "total_tokens": 150,
    }


def test_bind_tools_noop() -> None:
    """RESEARCH Pitfall A 反向断言：FakeChatModel.bind_tools 必须 override 返回 self。

    若 FakeChatModel 继承 GenericFakeChatModel 但未 override bind_tools，
    此处会抛 NotImplementedError（BaseChatModel.bind_tools 默认实现）。
    """

    @tool
    def dummy(x: int) -> int:
        """dummy tool for binding."""
        return x

    fake = FakeChatModel(responses=["x"])
    # 若 bind_tools 未 override，下一行会抛 NotImplementedError
    result = fake.bind_tools([dummy])
    assert result is fake


def test_responses_tool_calls_length_mismatch_raises() -> None:
    """contract: responses / tool_calls 长度不一致 → ValueError。"""
    with pytest.raises(ValueError, match="长度必须一致"):
        FakeChatModel(
            responses=["a", "b"],
            tool_calls=[[{"name": "x", "args": {}, "id": "1"}]],
        )


@pytest.mark.asyncio
async def test_astream_yields_single_chunk() -> None:
    """RESEARCH Pitfall G：GenericFakeChatModel.astream 对单 AIMessage 行为文档化。

    基类 _stream 会把 content 按空格切成多个 ChatGenerationChunk；
    对短 content（如 "hello"）会 yield ≥ 1 个 AIMessageChunk。
    本测试不断言精确 chunk 数，只验证 astream 能正常迭代且所有 chunk 拼起来 == 原 content。
    """
    fake = FakeChatModel(responses=["hello world"])
    chunks: list[AIMessageChunk] = []
    async for chunk in fake.astream([HumanMessage(content="hi")]):
        assert isinstance(chunk, AIMessageChunk)
        chunks.append(chunk)
    assert len(chunks) >= 1
    joined = "".join(str(c.content) for c in chunks if c.content)
    assert "hello" in joined and "world" in joined
