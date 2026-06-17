"""Tests for Feishu bot card builders."""

from __future__ import annotations

from feishu.cards.bot_cards import (
    build_answer_card,
    build_answer_markdown,
    build_clarification_card,
    build_error_card,
    build_processing_card,
    build_streaming_card_v2,
    build_welcome_card,
)


def test_processing_card_contains_required_progress_sections() -> None:
    card = build_processing_card("机器人为什么没回消息？", progress_state="项目识别中", thread_hint="引用上一条报警")
    content = "\n".join(element.get("content", "") for element in card["elements"] if isinstance(element, dict))

    assert "原问题" in content
    assert "项目识别中" in content
    assert "上下文检索中" in content
    assert "回答生成中" in content


def test_answer_card_renders_real_reference_section() -> None:
    card = build_answer_card(
        question="在哪个仓库修？",
        answer="请先检查 websocket handler。",
        references=[{"repository": "server", "path": "feishu/websocket_client.py", "line": "L10", "summary": "入口分发"}],
    )
    content = "\n".join(element.get("content", "") for element in card["elements"] if isinstance(element, dict))

    assert "已参考上下文" in content
    assert "websocket_client.py" in content


def test_compact_answer_card_can_render_auto_matched_space() -> None:
    card = build_answer_card(
        question="你是？",
        answer="我是 Friday。",
        references=[],
        compact=True,
        matched_space_label="learning-platform",
    )
    content = "\n".join(element.get("content", "") for element in card["elements"] if isinstance(element, dict))

    assert "已自动匹配「learning-platform」空间" in content
    assert "我是 Friday。" in content


def test_streaming_card_v2_is_schema_2_0_with_streaming_element() -> None:
    card = build_streaming_card_v2()

    assert card["schema"] == "2.0"
    assert card["config"]["streaming_mode"] is True
    assert card["config"]["update_multi"] is True
    assert "streaming_config" in card["config"]
    element = card["body"]["elements"][0]
    assert element["tag"] == "markdown"
    assert element["element_id"] == "md_body"
    assert element["content"] == "思考中..."
    assert 1 <= len(element["element_id"]) <= 20


def test_streaming_card_v2_honors_custom_element_id() -> None:
    card = build_streaming_card_v2(initial_text="开始", element_id="md_x")

    element = card["body"]["elements"][0]
    assert element["element_id"] == "md_x"
    assert element["content"] == "开始"


def test_answer_markdown_contains_answer_references_and_usage() -> None:
    result = build_answer_markdown(
        answer="请先检查 websocket handler。",
        references=[{"repository": "server", "path": "feishu/websocket_client.py"}],
        usage={"input_tokens": 100, "output_tokens": 50, "cost_usd": 0.0012},
        matched_space_label="learning-platform",
    )

    assert isinstance(result, str)
    assert "**回答**" in result
    assert "请先检查 websocket handler。" in result
    assert "已参考上下文" in result
    assert "server" in result
    assert "💰" in result
    assert "100" in result
    assert "已自动匹配「learning-platform」空间" in result


def test_answer_markdown_handles_empty_references_fallback() -> None:
    result = build_answer_markdown(answer="只基于概览。", references=[])

    assert isinstance(result, str)
    assert "未引用具体代码上下文" in result
    assert "💰" not in result


def test_welcome_clarification_and_error_cards_expose_expected_copy() -> None:
    welcome = build_welcome_card()
    clarify = build_clarification_card("这是哪个项目？", ["api-server", "web-app"])
    error = build_error_card("部署失败了", "请补充仓库和分支信息")

    assert welcome["header"]["title"]["content"]
    assert "api-server" in "\n".join(element.get("content", "") for element in clarify["elements"] if isinstance(element, dict))
    assert "联系管理员" in "\n".join(element.get("content", "") for element in error["elements"] if isinstance(element, dict))
