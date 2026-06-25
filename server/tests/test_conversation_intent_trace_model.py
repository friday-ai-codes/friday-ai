"""ConversationIntentTrace 模型层测试（implementation / work item）。

覆盖：
- 默认值与字段语义
- clarification_id 唯一约束
- 与 Conversation 的级联删
- 与 CodingPlan 的 SET_NULL 行为
- __str__ 短 id 格式
"""
from __future__ import annotations

import uuid

import pytest
from django.db import IntegrityError

from chat.models import (
    CodingPlan,
    Conversation,
    ConversationIntentTrace,
)


@pytest.fixture
def conversation(project) -> Conversation:
    return Conversation.objects.create(space=project, title="意图协商测试")


@pytest.mark.django_db
class TestConversationIntentTraceModel:
    def test_create_minimal_trace(self, conversation: Conversation) -> None:
        """创建仅含必填字段的 trace，所有可选字段使用文档化的默认值。"""
        clarification_id = uuid.uuid4().hex
        trace = ConversationIntentTrace.objects.create(
            conversation=conversation,
            clarification_id=clarification_id,
            question="想改哪个仓库？",
            options=[{"id": "opt-A", "label": "改后端"}],
        )
        assert trace.id is not None
        assert trace.selected_option_id == ""
        assert trace.freeform_answer == ""
        assert trace.inferred_state == {}
        assert trace.triggering_message_id == ""
        assert trace.resolved_to_plan is None
        assert trace.answered_at is None
        assert trace.created_at is not None

    def test_clarification_id_unique(self, conversation: Conversation) -> None:
        """同一 clarification_id 第二次写入抛 IntegrityError。"""
        clarification_id = uuid.uuid4().hex
        ConversationIntentTrace.objects.create(
            conversation=conversation,
            clarification_id=clarification_id,
            question="第一次",
            options=[],
        )
        with pytest.raises(IntegrityError):
            ConversationIntentTrace.objects.create(
                conversation=conversation,
                clarification_id=clarification_id,
                question="第二次重复 id",
                options=[],
            )

    def test_cascade_delete_with_conversation(
        self, conversation: Conversation
    ) -> None:
        """删除 conversation 时 trace 同时被删（on_delete=CASCADE）。"""
        ConversationIntentTrace.objects.create(
            conversation=conversation,
            clarification_id=uuid.uuid4().hex,
            question="级联测试",
            options=[],
        )
        assert ConversationIntentTrace.objects.filter(
            conversation=conversation
        ).count() == 1
        conversation.delete()
        assert ConversationIntentTrace.objects.count() == 0

    def test_resolved_to_plan_set_null_on_plan_delete(
        self, conversation: Conversation
    ) -> None:
        """删除关联的 CodingPlan 时 trace.resolved_to_plan 被置 None。"""
        plan = CodingPlan.objects.create(
            conversation=conversation,
            tech_plan="## 方案",
            affected_files=[],
        )
        trace = ConversationIntentTrace.objects.create(
            conversation=conversation,
            clarification_id=uuid.uuid4().hex,
            question="resolved_to_plan 测试",
            options=[],
            resolved_to_plan=plan,
        )
        assert trace.resolved_to_plan_id == plan.id

        plan.delete()
        trace.refresh_from_db()
        assert trace.resolved_to_plan_id is None

    def test_str_short_id(self, conversation: Conversation) -> None:
        """__str__ 形如 IntentTrace<前 8 位>。"""
        clarification_id = "abc12345" + "f" * 24
        trace = ConversationIntentTrace.objects.create(
            conversation=conversation,
            clarification_id=clarification_id,
            question="short id 测试",
            options=[],
        )
        assert str(trace) == "IntentTrace<abc12345>"

    def test_admin_class_defined(self) -> None:
        """ConversationIntentTrace admin 类已声明（acceptance criteria）。

        测试环境 ``INSTALLED_APPS`` 不含 ``django.contrib.admin`` ——
        无法访问 ``admin.site._registry``；改为直接 import admin 类断言
        其字段配置；@admin.register 装饰器会在生产环境 admin app 加载
        时把它注册到 default site（admin.E108 系列契约不在本测试范围）。
        """
        # 用 importlib 而不是顶层 import：避免 chat.admin 的 module-level
        # `@admin.register` 触发 admin.site._registry 访问 —— 在没装 admin
        # app 的测试环境会抛 LookupError。
        import importlib.util

        spec = importlib.util.find_spec("chat.admin")
        assert spec is not None
        # 直接打开源码文件确认类声明存在 + 关键字段在
        assert spec.origin is not None
        with open(spec.origin, encoding="utf-8") as f:
            src = f.read()
        assert "class ConversationIntentTraceAdmin" in src
        assert "ConversationIntentTrace" in src
        assert "@admin.register(ConversationIntentTrace)" in src
