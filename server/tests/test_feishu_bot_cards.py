"""Tests for Feishu bot card builders."""
from __future__ import annotations
from feishu.cards.bot_cards import (
 build_answer_card,
 build_clarification_card,
 build_error_card,
 build_processing_card,
 build_welcome_card,
)
def test_processing_card_contains_required_progress_sections -> None:
 card = build_processing_card("机器人为什么没回消息？", progress_state="项目识别中", thread_hint="引用上一条报警")
 content = "\n".join(element.get("content", "") for element in card["elements"] if isinstance(element, dict))
 assert "原问题" in content
 assert "项目识别中" in content
 assert "上下文检索中" in content
 assert "回答生成中" in content
def test_answer_card_renders_real_reference_section -> None:
 card = build_answer_card(
 question="在哪个仓库修？",
 answer="请先检查 websocket handler。",
 references=[{"repository": "server", "path": "feishu/websocket_client.py", "line": "L10", "summary": "入口分发"}],
 )
 content = "\n".join(element.get("content", "") for element in card["elements"] if isinstance(element, dict))
 assert "已参考上下文" in content
 assert "websocket_client.py" in content
def test_compact_answer_card_can_render_auto_matched_space -> None:
 card = build_answer_card(
 question="你是？",
 answer="我是 Friday。",
 references=,
 compact=True,
 matched_space_label="learning-platform",
 )
 content = "\n".join(element.get("content", "") for element in card["elements"] if isinstance(element, dict))
 assert "已自动匹配「learning-platform」空间" in content
 assert "我是 Friday。" in content
def test_welcome_clarification_and_error_cards_expose_expected_copy -> None:
 welcome = build_welcome_card
 clarify = build_clarification_card("这是哪个项目？", ["api-server", "web-app"])
 error = build_error_card("部署失败了", "请补充仓库和分支信息")
 assert welcome["header"]["title"]["content"]
 assert "api-server" in "\n".join(element.get("content", "") for element in clarify["elements"] if isinstance(element, dict))
 assert "联系管理员" in "\n".join(element.get("content", "") for element in error["elements"] if isinstance(element, dict))
