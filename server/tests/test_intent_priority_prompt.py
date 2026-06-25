"""implementation 三 slug resync migration 契约测试。

测试策略：``transaction=True`` 模式下每个 test 都会 flush DB（pytest-django 跑
``migrate`` 时已经执行过的 RunPython data migration 在事务回滚后数据丢失），
本文件不依赖 prompts seed 已存在；fixture 自己造一份 seed 状态后再调 0006
``forwards`` 验证幂等 + body 一致 + change_note 锚点三个核心契约。

Migration 用 importlib 动态加载（Django 文件名以数字开头，无法 ``from
prompts.migrations import 0006_...``）。
"""
from __future__ import annotations

import importlib
from collections.abc import Iterator

import pytest
from django.apps import apps as django_apps

from chat.conversation_service import (
    ROLE_PROMPTS,
    _CODING_GUIDANCE,
    _STRATEGY_DEFAULT,
)
from prompts.models import Prompt, PromptVersion

# Django migration 文件名以数字开头，必须用 importlib 加载。
resync = importlib.import_module(
    "prompts.migrations.0006_intent_priority_resync"
)


_THREE_SLUGS = (
    "chat.system.developer",
    "chat.strategy.default",
    "chat.coding_guidance",
)


def _ensure_seed_with_stale_body() -> None:
    """造（或回退）三 slug 的「旧版」种子状态。

    背景：``transaction=True`` 模式下 pytest-django 在 test 之间 ``flush`` 数据，
    seed 数据（0002 migration）可能丢失；本 helper 同时支持两种状态：
    - 已存在 → ``update()`` 改 body
    - 不存在 → ``create()`` 一份最小可用 seed

    直接走 SQL 写 row，避免触发 active_version 自增等业务副作用。
    """
    for slug in _THREE_SLUGS:
        prompt, created = Prompt.objects.get_or_create(
            slug=slug,
            scope="system",
            space=None,
            defaults={
                "category": "chat_agent",
                "title": f"seed-{slug}",
                "description": "test seed",
                "is_builtin": True,
            },
        )
        if created or prompt.active_version is None:
            version = PromptVersion.objects.create(
                prompt=prompt,
                version=1,
                body=f"OLD_BODY_FOR_{slug}",
                variables_schema={},
                change_note="test seed v1",
            )
            prompt.active_version = version
            prompt.save(update_fields=["active_version", "updated_at"])
        else:
            PromptVersion.objects.filter(pk=prompt.active_version.pk).update(
                body=f"OLD_BODY_FOR_{slug}",
            )


@pytest.fixture
def revert_three_slugs_to_stale_body() -> Iterator[None]:
    """每个 test 进入时确保 fixture 状态可用（兼容 transaction flush）。"""
    _ensure_seed_with_stale_body()
    yield None


def _count_versions(slug: str) -> int:
    return PromptVersion.objects.filter(prompt__slug=slug).count()


def _active_body(slug: str) -> str:
    prompt = Prompt.objects.get(slug=slug, scope="system", space=None)
    assert prompt.active_version is not None
    return prompt.active_version.body


@pytest.mark.django_db
class TestIntentPriorityResyncMigration:
    """0006_intent_priority_resync forwards 契约：幂等 + body 字节级 + audit。"""

    def test_forwards_upserts_three_slugs_to_current_fallback(
        self,
        revert_three_slugs_to_stale_body: None,
    ) -> None:
        """旧 body → 调 forwards 后三 slug active body 与 fallback 字节级一致。"""
        resync.forwards(django_apps, None)

        assert _active_body("chat.system.developer") == ROLE_PROMPTS["developer"]
        assert _active_body("chat.strategy.default") == _STRATEGY_DEFAULT
        assert _active_body("chat.coding_guidance") == _CODING_GUIDANCE

    def test_forwards_appends_new_version_per_slug(
        self,
        revert_three_slugs_to_stale_body: None,
    ) -> None:
        """每个 slug append 1 个新 PromptVersion（旧 +1）。"""
        before = {slug: _count_versions(slug) for slug in _THREE_SLUGS}
        resync.forwards(django_apps, None)
        after = {slug: _count_versions(slug) for slug in _THREE_SLUGS}
        for slug in _THREE_SLUGS:
            assert after[slug] == before[slug] + 1, (
                f"{slug} 应 append 1 个新版本：before={before[slug]} after={after[slug]}"
            )

    def test_forwards_is_idempotent_on_second_invocation(
        self,
        revert_three_slugs_to_stale_body: None,
    ) -> None:
        """连续两次 forwards 不再 append PromptVersion（已对齐 fallback 应 skip）。"""
        resync.forwards(django_apps, None)
        counts_after_first = {slug: _count_versions(slug) for slug in _THREE_SLUGS}
        resync.forwards(django_apps, None)
        counts_after_second = {slug: _count_versions(slug) for slug in _THREE_SLUGS}
        assert counts_after_first == counts_after_second

    def test_forwards_change_note_marks_intent_04(
        self,
        revert_three_slugs_to_stale_body: None,
    ) -> None:
        """新版本的 change_note 应含 work item + 准确性优先原则两枚 audit 锚点。"""
        resync.forwards(django_apps, None)

        for slug in _THREE_SLUGS:
            prompt = Prompt.objects.get(slug=slug, scope="system", space=None)
            assert prompt.active_version is not None
            note = prompt.active_version.change_note
            assert "work item" in note, f"{slug} change_note 缺 work item: {note!r}"
            assert "准确性优先原则" in note, (
                f"{slug} change_note 缺「准确性优先原则」: {note!r}"
            )

    def test_forwards_skips_when_prompt_not_exists(self) -> None:
        """对不存在的 slug，``_resync_one`` 静默 skip 不抛错（与 0004 / 0005 一致）。

        Prompt.DoesNotExist 路径用一个不存在的 slug 触发即可，无需打整张表。
        """
        resync._resync_one(
            django_apps,
            "chat.system.developer.NONEXISTENT",
            lambda: "irrelevant",
            "test note",
        )
