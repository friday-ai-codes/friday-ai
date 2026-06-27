"""群聊提问卡片模板测试。"""

from feishu.cards.chat_question_card import (
    build_chat_answered_card,
    build_chat_question_card,
    build_chat_reminder_card,
    build_clarification_card,
)


def _clarification_form_submit_value(card: dict) -> dict:
    """从澄清卡中取 form_submit 按钮的 value（回调路由锚）。"""
    for el in card["elements"]:
        if el.get("tag") == "form":
            for fe in el["elements"]:
                if fe.get("action_type") == "form_submit":
                    return fe["value"]
    raise AssertionError("no form_submit element in clarification card")


class TestBuildClarificationCardAction:
    """build_clarification_card 回调 action 前缀参数化测试（92-02 Task 2）。"""

    def test_default_action_is_plan_clarify_answer(self) -> None:
        """Test 1（向后兼容）：不传 action → value.action == 'plan_clarify_answer'（91 路由不变）。"""
        card = build_clarification_card(
            [{"question": "涉及哪些仓库？", "options": ["api", "web"], "recommended": "api"}],
            execution_id="exec-1",
            node_id="node-1",
            clarification_id="cid",
        )
        assert _clarification_form_submit_value(card)["action"] == "plan_clarify_answer"

    def test_custom_action_routes_to_standalone_callback(self) -> None:
        """Test 2（standalone 路由）：传 action='clarify_card_answer' → value.action 切换。"""
        card = build_clarification_card(
            [{"question": "涉及哪些仓库？", "options": ["api", "web"], "recommended": "api"}],
            execution_id="exec-1",
            node_id="node-1",
            clarification_id="cid",
            action="clarify_card_answer",
        )
        assert _clarification_form_submit_value(card)["action"] == "clarify_card_answer"

    def test_value_carries_routing_anchors(self) -> None:
        """Test 3：value 仍并列携 execution_id/node_id/clarification_id（92-03 据其定位本节点）。"""
        card = build_clarification_card(
            [{"question": "q", "options": ["a"], "recommended": "a"}],
            execution_id="exec-9",
            node_id="node-8",
            clarification_id="clar-7",
            action="clarify_card_answer",
        )
        value = _clarification_form_submit_value(card)
        assert value["execution_id"] == "exec-9"
        assert value["node_id"] == "node-8"
        assert value["clarification_id"] == "clar-7"


class TestBuildChatQuestionCard:
    """build_chat_question_card 测试。"""

    def test_basic_card_structure(self) -> None:
        """Test 1: 生成包含 header（blue 主题）、question markdown、form 的卡片。"""
        card = build_chat_question_card(
            question="选择哪个方案？",
            execution_id="exec-1",
            node_id="node-1",
        )

        assert card["config"]["wide_screen_mode"] is True
        assert card["header"]["template"] == "blue"
        assert "Friday 提问" in card["header"]["title"]["content"]

        elements = card["elements"]
        # 应包含 question markdown
        md_elements = [e for e in elements if e.get("tag") == "markdown"]
        assert any("选择哪个方案？" in e["content"] for e in md_elements)

        # 应包含 form
        form_elements = [e for e in elements if e.get("tag") == "form"]
        assert len(form_elements) == 1
        assert form_elements[0]["name"] == "chat_answer_form"

    def test_options_create_action_buttons(self) -> None:
        """Test 2: 传入 options 时卡片包含 action 按钮。"""
        card = build_chat_question_card(
            question="选择语言",
            options=["Python", "Go"],
            execution_id="exec-1",
            node_id="node-1",
        )

        elements = card["elements"]
        action_elements = [e for e in elements if e.get("tag") == "action"]
        assert len(action_elements) == 1
        actions = action_elements[0]["actions"]
        assert len(actions) == 2
        assert actions[0]["text"]["content"] == "Python"
        assert actions[1]["text"]["content"] == "Go"

    def test_button_value_contains_routing_info(self) -> None:
        """Test 3: 按钮 value 包含 action='chat_question_answer' + execution_id + node_id。"""
        card = build_chat_question_card(
            question="选择",
            options=["A"],
            execution_id="exec-123",
            node_id="node-456",
        )

        action_el = [e for e in card["elements"] if e.get("tag") == "action"][0]
        button_value = action_el["actions"][0]["value"]
        assert button_value["action"] == "chat_question_answer"
        assert button_value["execution_id"] == "exec-123"
        assert button_value["node_id"] == "node-456"
        assert button_value["answer"] == "A"

    def test_form_submit_value_contains_routing_info(self) -> None:
        """Test 4: 表单提交 value 同样包含 action='chat_question_answer'。"""
        card = build_chat_question_card(
            question="输入",
            execution_id="exec-1",
            node_id="node-1",
        )

        form_el = [e for e in card["elements"] if e.get("tag") == "form"][0]
        submit_btn = [
            e for e in form_el["elements"]
            if e.get("tag") == "button" and e.get("action_type") == "form_submit"
        ][0]
        assert submit_btn["value"]["action"] == "chat_question_answer"
        assert submit_btn["value"]["execution_id"] == "exec-1"
        assert submit_btn["value"]["node_id"] == "node-1"

    def test_work_item_name_in_header(self) -> None:
        """Test 5: work_item_name 显示在 header title 中。"""
        card = build_chat_question_card(
            question="问题",
            execution_id="e",
            node_id="n",
            work_item_name="work item 修复登录",
        )

        title = card["header"]["title"]["content"]
        assert "work item 修复登录" in title

    def test_history_section(self) -> None:
        """额外测试: history 参数生成历史 Q&A 区块。"""
        card = build_chat_question_card(
            question="下一步？",
            execution_id="e",
            node_id="n",
            history=[{"question": "选什么？", "answer": "A"}],
        )

        elements = card["elements"]
        # 应有 hr 分隔线
        hr_elements = [e for e in elements if e.get("tag") == "hr"]
        assert len(hr_elements) >= 1
        # 历史内容
        md_elements = [e for e in elements if e.get("tag") in ("div", "markdown")]
        history_text = " ".join(
            e.get("content", "") or e.get("text", {}).get("content", "")
            for e in md_elements
        )
        assert "选什么？" in history_text


    def test_mention_user_id(self) -> None:
        """Test: mention_user_id 时卡片包含 <at> 标签。"""
        card = build_chat_question_card(
            question="请确认方案",
            execution_id="exec-1",
            node_id="node-1",
            mention_user_id="ou_user123",
        )

        elements = card["elements"]
        # 第一个元素应该是 @mention markdown
        md_elements = [e for e in elements if e.get("tag") == "markdown"]
        mention_texts = [e["content"] for e in md_elements if "<at" in e.get("content", "")]
        assert len(mention_texts) > 0
        assert '<at id="ou_user123">' in mention_texts[0]

    def test_no_mention(self) -> None:
        """Test: mention_user_id 为 None 时不包含 @mention。"""
        card = build_chat_question_card(
            question="一般问题",
            execution_id="exec-1",
            node_id="node-1",
        )

        elements = card["elements"]
        all_content = " ".join(
            e.get("content", "") for e in elements if e.get("tag") == "markdown"
        )
        assert "<at" not in all_content

    def test_reminder_card(self) -> None:
        """Test: build_chat_reminder_card 生成 orange 主题提醒卡片。"""
        card = build_chat_reminder_card(
            question="这是一个很长的问题需要截断测试" * 20,
            work_item_name="work item",
            remaining_minutes=15,
        )

        assert card["header"]["template"] == "orange"
        assert "提醒" in card["header"]["title"]["content"]

        elements = card["elements"]
        all_content = " ".join(
            e.get("content", "")
            for e in elements
            if e.get("tag") == "markdown"
        )
        # 问题摘要应被截断到 200 字
        assert len(all_content) < 500
        assert "15" in all_content  # 剩余时间
        # 不应包含按钮或表单
        form_elements = [e for e in elements if e.get("tag") in ("form", "action")]
        assert len(form_elements) == 0


class TestBuildChatAnsweredCard:
    """build_chat_answered_card 测试。"""

    def test_answered_card_grey_theme(self) -> None:
        """Test 6: 生成灰色主题卡片，显示问题、回答、回复者。"""
        card = build_chat_answered_card(
            question="选择方案",
            answer="方案 A",
            responder_name="张三",
            work_item_name="work item",
        )

        assert card["header"]["template"] == "grey"
        assert "已收到回复" in card["header"]["title"]["content"]

        elements = card["elements"]
        content = " ".join(
            e.get("content", "") for e in elements if e.get("tag") == "markdown"
        )
        assert "选择方案" in content
        assert "方案 A" in content
        assert "张三" in content
        # 处理中提示
        assert "处理中" in content
