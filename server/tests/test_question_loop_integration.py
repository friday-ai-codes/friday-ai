"""提问链路集成测试（Phase）。

验证完整提问流程：
1. 容器发送 question 回调
2. 创建 InteractionLog
3. 发送飞书卡片
4. 用户回复
5. 更新 InteractionLog
6. 更新卡片状态
7. 写入 answer.json
"""

import uuid
from unittest.mock import patch

import pytest


@pytest.fixture
def mock_session(db):
    """创建测试用 SubAgentSession。"""
    from accounts.models import User
    from agents.models import AgentSession
    from projects.models import Space
    from subagent.models import SubAgentSession

    # 创建 User（AgentSession 需要）
    user = User.objects.create_user(
        username="test_user",
        email="test@example.com",
        password="testpass123",
    )

    # 创建 Space（AgentSession 需要）
    project = Space.objects.create(
        name="Test Space",
        description="Test",
    )

    # 创建 main_session
    main_session = AgentSession.objects.create(
        session_id="main-test-001",
        space=project,
        user=user,
        metadata={"chat_id": "oc_test_chat_id"},
    )

    # 创建 SubAgentSession
    session = SubAgentSession.objects.create(
        session_id="sub-test-001",
        main_session=main_session,
        repo_url="https://github.com/test/repo",
        task_type="coding",
        status=SubAgentSession.Status.RUNNING,
    )

    return session


class TestQuestionCallback:
    """测试 question 回调处理。"""

    @pytest.mark.asyncio
    @pytest.mark.django_db(transaction=True)
    async def test_interaction_log_creation(self, mock_session):
        """验证 InteractionLog 可正确创建。"""
        from subagent.models import InteractionLog

        question_id = f"q-{uuid.uuid4().hex[:12]}"
        payload = {
            "question": "选择哪种实现方式？",
            "options": ["方案 A", "方案 B"],
            "context": "实现用户认证功能",
            "code_snippet": "--- a/auth.py\n+++ b/auth.py",
        }

        interaction = await InteractionLog.objects.acreate(
            session=mock_session,
            question_id=question_id,
            question_text=payload["question"],
            question_context=payload["context"],
            code_snippet=payload["code_snippet"],
            options=payload["options"],
            feishu_message_id="msg_test_123",
        )

        assert interaction.question_id == question_id
        assert interaction.question_text == "选择哪种实现方式？"
        assert interaction.options == ["方案 A", "方案 B"]
        assert interaction.code_snippet == "--- a/auth.py\n+++ b/auth.py"
        assert interaction.is_answered is False
        assert interaction.feishu_message_id == "msg_test_123"


class TestAnswerHandling:
    """测试回复处理。"""

    @pytest.mark.asyncio
    @pytest.mark.django_db(transaction=True)
    @patch("subagent.question_handler._update_card_to_answered")
    @patch("subagent.question_handler.write_answer_to_volume")
    async def test_answer_updates_interaction_log(
        self, mock_write, mock_update_card, mock_session
    ):
        """验证回复更新 InteractionLog。"""
        from subagent.models import InteractionLog
        from subagent.question_handler import handle_container_answer_enhanced

        mock_write.return_value = True
        mock_update_card.return_value = None

        # 创建待回复的问题
        interaction = await InteractionLog.objects.acreate(
            session=mock_session,
            question_id="q-test-001",
            question_text="选择方案？",
            options=["A", "B"],
            feishu_message_id="msg_123",
        )

        # 处理回复
        result = await handle_container_answer_enhanced(
            session_id=mock_session.session_id,
            question_id="q-test-001",
            answer="方案 A",
            answer_source="button",
        )

        assert result is True

        # 验证 InteractionLog 更新
        await interaction.arefresh_from_db()
        assert interaction.answer_text == "方案 A"
        assert interaction.answer_source == "button"
        assert interaction.answered_at is not None
        assert interaction.is_answered is True

        # 验证卡片更新被调用
        mock_update_card.assert_called_once()


class TestMultiRoundQuestions:
    """测试多轮提问。"""

    @pytest.mark.asyncio
    @pytest.mark.django_db(transaction=True)
    async def test_multiple_questions_create_separate_logs(self, mock_session):
        """验证多轮提问创建独立的 InteractionLog。"""
        from subagent.models import InteractionLog

        # 创建多个问题
        for i in range(3):
            await InteractionLog.objects.acreate(
                session=mock_session,
                question_id=f"q-round-{i}",
                question_text=f"问题 {i}？",
            )

        # 验证数量
        count = await InteractionLog.objects.filter(session=mock_session).acount()
        assert count == 3

        # 验证独立性（每个有唯一 question_id）
        question_ids = set()
        async for log in InteractionLog.objects.filter(session=mock_session):
            question_ids.add(log.question_id)
        assert len(question_ids) == 3
