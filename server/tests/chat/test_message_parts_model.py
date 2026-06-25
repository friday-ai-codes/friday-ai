"""parts contract：``server/chat/parts.py`` PartsCollector
状态机 + Pydantic Part 模型单测。

测试矩阵（contract 测试要求 ≥ 8 条）：
1. text → tool → text 序列：tool_use_start 必须封口当前 text，之后开新 text
2. thinking 与 text 切换不互相封口（thinking 是旁注，逻辑独立）
3. 并行 tool_use 共享 batch_id（同 LLM response 多 tool_call）
4. flush_all 把所有 streaming part 标 done（text/thinking）；running tool_use 标 error+cancelled
5. to_message_payload.content == 所有 text part 拼接（强同源）
6. to_message_payload.tool_calls == tool_use parts 抽取（强同源）
7. complete_tool_use 收到未知 tool_call_id 时记 warning 不抛
8. Pydantic Part 模型 round-trip 序列化（用 discriminated union）
"""

from __future__ import annotations

import pytest

from chat.parts import (
    ImagePart,
    PartsCollector,
    TextPart,
    ThinkingPart,
    ToolUsePart,
    part_from_dict,
    part_to_dict,
)


def test_collector_text_then_tool_then_text() -> None:
    """Anthropic content blocks 语义：text 在 tool_use 时封口，之后开新 part。"""
    collector = PartsCollector()
    collector.append_text("Hello ")
    collector.append_text("world")
    collector.start_tool_use(
        tool_call_id="tc-1", name="search", input={"q": "x"}, batch_id=None,
    )
    collector.append_text("Result: ok")
    collector.complete_tool_use(tool_call_id="tc-1", success=True, result="found")

    payload = collector.to_message_payload()
    parts = payload["parts"]

    assert [p["type"] for p in parts] == ["text", "tool_use", "text"]
    assert parts[0]["text"] == "Hello world"
    assert parts[0]["state"] == "done"  # tool_use 封口
    assert parts[1]["name"] == "search"
    assert parts[1]["status"] == "done"  # complete_tool_use 已调
    assert parts[1]["result"] == "found"
    assert parts[2]["text"] == "Result: ok"
    assert parts[2]["state"] == "streaming"
    # index 单调
    assert [p["index"] for p in parts] == [0, 1, 2]


def test_collector_thinking_does_not_close_text() -> None:
    """thinking 是旁注；与 text 切换互不封口，各自独立 part。"""
    collector = PartsCollector()
    collector.append_text("正在思考...")
    collector.append_thinking("中间推理 A")
    collector.append_text("继续输出")
    collector.append_thinking("中间推理 B")

    payload = collector.to_message_payload()
    parts = payload["parts"]

    types = [p["type"] for p in parts]
    assert types == ["text", "thinking", "text", "thinking"]
    # text 未被 thinking 封口，仍是 streaming
    assert parts[0]["state"] == "streaming"
    assert parts[2]["state"] == "streaming"
    # 同样 thinking 之间也不封口
    assert parts[1]["state"] == "streaming"
    assert parts[3]["state"] == "streaming"


def test_collector_parallel_tool_use_batch_id_propagates() -> None:
    """同 batch（一次 LLM response 多个 tool_call）共享 batch_id。"""
    collector = PartsCollector()
    collector.start_tool_use(
        tool_call_id="tc-a", name="foo", input={"a": 1}, batch_id="batch_xyz",
    )
    collector.start_tool_use(
        tool_call_id="tc-b", name="bar", input={"b": 2}, batch_id="batch_xyz",
    )

    parts = collector.to_message_payload()["parts"]
    assert len(parts) == 2
    assert parts[0]["batch_id"] == "batch_xyz"
    assert parts[1]["batch_id"] == "batch_xyz"
    # 第二个 start_tool_use 不能错误地"封口"第一个 tool_use part
    assert parts[0]["status"] == "running"
    assert parts[1]["status"] == "running"


def test_collector_flush_all_marks_streaming_done_and_tool_cancelled() -> None:
    """R4 风险缓解：flush_all 处理 streaming text/thinking → done，running tool_use → error+cancelled。"""
    collector = PartsCollector()
    collector.append_text("partial text")
    collector.append_thinking("partial thinking")
    collector.start_tool_use(
        tool_call_id="tc-1", name="foo", input={}, batch_id=None,
    )

    collector.flush_all()
    parts = collector.to_message_payload()["parts"]

    text_part = next(p for p in parts if p["type"] == "text")
    thinking_part = next(p for p in parts if p["type"] == "thinking")
    tool_part = next(p for p in parts if p["type"] == "tool_use")

    assert text_part["state"] == "done"
    assert thinking_part["state"] == "done"
    # 未完成的 tool_use 在 flush 时不能标 done（与 R1 缓解一致）
    assert tool_part["status"] == "error"
    assert tool_part["result"] == "cancelled"


def test_collector_to_message_payload_content_equals_concat_of_text_parts() -> None:
    """content 字段 = 所有 text part 拼接（contract 强同源契约）。"""
    collector = PartsCollector()
    collector.append_text("Hello ")
    collector.start_tool_use(
        tool_call_id="t1", name="foo", input={}, batch_id=None,
    )
    collector.complete_tool_use(tool_call_id="t1", success=True, result="r1")
    collector.append_text("world!")

    payload = collector.to_message_payload()
    assert payload["content"] == "Hello world!"


def test_collector_to_message_payload_tool_calls_extracted_from_tool_use_parts() -> None:
    """tool_calls 字段 = 所有 tool_use part 抽取（contract 强同源契约）。"""
    collector = PartsCollector()
    collector.start_tool_use(
        tool_call_id="tc-1", name="search", input={"q": "django"}, batch_id=None,
    )
    collector.complete_tool_use(tool_call_id="tc-1", success=True, result="hit")
    collector.start_tool_use(
        tool_call_id="tc-2", name="browse", input={"path": "x.py"}, batch_id=None,
    )
    collector.complete_tool_use(
        tool_call_id="tc-2", success=False, result='{"is_error": true}',
    )

    payload = collector.to_message_payload()
    tcs = payload["tool_calls"]
    assert len(tcs) == 2
    assert tcs[0] == {
        "id": "tc-1",
        "name": "search",
        "input": {"q": "django"},
        "result": "hit",
        "status": "done",
    }
    assert tcs[1]["status"] == "error"
    assert tcs[1]["result"] == '{"is_error": true}'


def test_collector_complete_tool_use_unknown_id_logs_warning_no_raise() -> None:
    """未知 tool_call_id 不能抛异常（防御主流程，warning 即可）。"""
    collector = PartsCollector()
    # 不开 tool_use 直接 complete，应静默返回 None 不抛
    idx = collector.complete_tool_use(
        tool_call_id="unknown-tc", success=True, result="x",
    )
    assert idx is None
    # collector 状态没被污染
    assert collector.to_message_payload()["parts"] == []


def test_part_pydantic_serialization_round_trip() -> None:
    """Pydantic discriminated union 序列化 round-trip（D1 schema versioning 基础）。"""
    text = TextPart(id="p1", index=0, text="hello", state="done")
    tool = ToolUsePart(
        id="p2",
        index=1,
        tool_call_id="tc",
        name="search",
        input={"q": "x"},
        status="done",
        result="ok",
        batch_id=None,
    )
    thinking = ThinkingPart(id="p3", index=2, text="reasoning", state="done")

    for part in (text, tool, thinking):
        as_dict = part_to_dict(part)
        restored = part_from_dict(as_dict)
        assert part_to_dict(restored) == as_dict


def test_image_part_pydantic_serialization_round_trip() -> None:
    """ImagePart 是一等 parts 成员，序列化不影响旧 text/tool/thinking 分支。"""
    image = ImagePart(
        id="p-img",
        index=0,
        mime_type="image/png",
        size_bytes=128,
        width=16,
        height=16,
        detail="auto",
        storage_ref="chat_images/p-img.png",
        source_url="",
        alt_text="界面截图",
    )

    as_dict = part_to_dict(image)
    restored = part_from_dict(as_dict)

    assert as_dict["type"] == "image"
    assert as_dict["mime_type"] == "image/png"
    assert as_dict["storage_ref"] == "chat_images/p-img.png"
    assert part_to_dict(restored) == as_dict


def test_collector_content_ignores_image_parts() -> None:
    """Message.content 只由 text part 派生，图片 part 不进入大字段。"""
    collector = PartsCollector()
    collector.parts = [
        {"type": "text", "id": "p1", "index": 0, "text": "请分析", "state": "done"},
        {
            "type": "image",
            "id": "p2",
            "index": 1,
            "mime_type": "image/png",
            "size_bytes": 128,
            "width": None,
            "height": None,
            "detail": "auto",
            "storage_ref": "chat_images/p2.png",
            "source_url": "",
            "alt_text": "",
        },
        {"type": "text", "id": "p3", "index": 2, "text": "这张图", "state": "done"},
    ]

    payload = collector.to_message_payload()

    assert payload["content"] == "请分析这张图"
    assert payload["parts"][1]["type"] == "image"
    assert payload["tool_calls"] == []


def test_collector_append_text_returns_is_new_part_flag() -> None:
    """append_text 第一次创建 part 返回 is_new_part=True；第二次 append 返回 False。"""
    collector = PartsCollector()
    id1, idx1, new1 = collector.append_text("a")
    id2, idx2, new2 = collector.append_text("b")
    assert new1 is True
    assert new2 is False
    assert id1 == id2
    assert idx1 == idx2 == 0


def test_collector_thinking_then_text_opens_new_text_part() -> None:
    """thinking 不封口 text，但反过来 thinking → text 时也要开新 text part（如果当前 streaming 是 thinking）。"""
    collector = PartsCollector()
    collector.append_thinking("reasoning...")
    _, idx, new = collector.append_text("answer")
    # text 与 thinking 是不同 type，必须新开
    assert new is True
    assert idx == 1


@pytest.mark.django_db
def test_message_parts_field_default_empty_list() -> None:
    """Message.parts 必须 default=[] 且可读可写。"""
    from chat.models import Conversation, Message
    from projects.models import Space

    project = Space.objects.create(name="t")
    conv = Conversation.objects.create(space=project, title="t")

    msg = Message.objects.create(
        conversation=conv,
        role=Message.Role.ASSISTANT,
        content="hi",
    )
    # 默认值
    assert msg.parts == []

    # 可写
    msg.parts = [{"type": "text", "id": "p1", "index": 0, "text": "hi", "state": "done"}]
    msg.save(update_fields=["parts"])
    msg.refresh_from_db()
    assert isinstance(msg.parts, list)
    assert msg.parts[0]["type"] == "text"
