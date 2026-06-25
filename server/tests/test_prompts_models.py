"""Prompt + PromptVersion ORM 基础测试（Wave Task 3 填充）。"""
from __future__ import annotations

import uuid

import pytest
from django.db import IntegrityError

from prompts.models import Prompt, PromptCategory, PromptScope, PromptVersion


@pytest.mark.django_db
class TestPromptModel:
    def test_prompt_uses_uuid_primary_key(self, admin_user) -> None:
        # implementation 注意：chat.system.developer 已由 0002 seed 种入测试 DB，
        # 需先清除才能测试本测试用例关注的 PK 类型（而非种子行为）
        Prompt.objects.filter(slug="chat.system.developer", scope=PromptScope.SYSTEM).delete()
        p = Prompt.objects.create(
            slug="chat.system.developer",
            category=PromptCategory.CHAT_AGENT,
            scope=PromptScope.SYSTEM,
            title="开发者 Agent",
            created_by=admin_user,
        )
        assert isinstance(p.id, uuid.UUID)

    def test_system_slug_unique_constraint_enforced(self, admin_user) -> None:
        # 清除 seed 以隔离单元测试的 unique 约束断言
        Prompt.objects.filter(slug="chat.system.developer", scope=PromptScope.SYSTEM).delete()
        Prompt.objects.create(
            slug="chat.system.developer",
            category=PromptCategory.CHAT_AGENT,
            scope=PromptScope.SYSTEM,
            title="v1",
            created_by=admin_user,
        )
        with pytest.raises(IntegrityError):
            Prompt.objects.create(
                slug="chat.system.developer",
                category=PromptCategory.CHAT_AGENT,
                scope=PromptScope.SYSTEM,
                title="v2",
                created_by=admin_user,
            )

    def test_project_slug_unique_per_project(self, admin_user, project) -> None:
        # project 作用域不冲突 seed（seed 仅 SYSTEM），但保持一致风格 preemptive clean
        Prompt.objects.filter(
            slug="chat.system.developer",
            scope=PromptScope.PROJECT,
            space=project,
        ).delete()
        Prompt.objects.create(
            slug="chat.system.developer",
            category=PromptCategory.CHAT_AGENT,
            scope=PromptScope.PROJECT,
            space=project,
            title="p1",
            created_by=admin_user,
        )
        with pytest.raises(IntegrityError):
            Prompt.objects.create(
                slug="chat.system.developer",
                category=PromptCategory.CHAT_AGENT,
                scope=PromptScope.PROJECT,
                space=project,
                title="p2",
                created_by=admin_user,
            )

    def test_same_slug_can_coexist_system_and_project(
        self, admin_user, project
    ) -> None:
        Prompt.objects.create(
            slug="shared.key",
            category=PromptCategory.CHAT_AGENT,
            scope=PromptScope.SYSTEM,
            title="sys",
            created_by=admin_user,
        )
        Prompt.objects.create(
            slug="shared.key",
            category=PromptCategory.CHAT_AGENT,
            scope=PromptScope.PROJECT,
            space=project,
            title="proj",
            created_by=admin_user,
        )
        assert Prompt.objects.filter(slug="shared.key").count() == 2

    def test_prompt_version_ordering_desc(self, admin_user) -> None:
        p = Prompt.objects.create(
            slug="ordering.test",
            category=PromptCategory.AUX_MODEL,
            scope=PromptScope.SYSTEM,
            title="t",
            created_by=admin_user,
        )
        PromptVersion.objects.create(prompt=p, version=1, body="v1")
        PromptVersion.objects.create(prompt=p, version=2, body="v2")
        PromptVersion.objects.create(prompt=p, version=3, body="v3")
        versions = list(p.versions.all())
        assert [v.version for v in versions] == [3, 2, 1]

    def test_active_version_fk_set_null_on_delete(self, admin_user) -> None:
        p = Prompt.objects.create(
            slug="null.test",
            category=PromptCategory.AUX_MODEL,
            scope=PromptScope.SYSTEM,
            title="t",
            created_by=admin_user,
        )
        v = PromptVersion.objects.create(prompt=p, version=1, body="x")
        p.active_version = v
        p.save()
        v.delete()
        p.refresh_from_db()
        assert p.active_version is None
