"""chat.strategy.default route-first prompt resync migration tests."""
from __future__ import annotations

import importlib
from collections.abc import Iterator

import pytest
from django.apps import apps as django_apps

from chat.conversation_service import _STRATEGY_DEFAULT
from prompts.models import Prompt, PromptVersion

resync = importlib.import_module(
    "prompts.migrations.0008_resync_chat_strategy_route_first"
)


@pytest.fixture
def stale_strategy_default_prompt() -> Iterator[None]:
    """Ensure ``chat.strategy.default`` exists with a stale active body."""
    prompt, created = Prompt.objects.get_or_create(
        slug="chat.strategy.default",
        scope="system",
        space=None,
        defaults={
            "category": "chat_agent",
            "title": "seed-chat.strategy.default",
            "description": "test seed",
            "is_builtin": True,
        },
    )
    if created or prompt.active_version is None:
        version = PromptVersion.objects.create(
            prompt=prompt,
            version=1,
            body="OLD_ROUTE_PROMPT",
            variables_schema={},
            change_note="test seed v1",
        )
        prompt.active_version = version
        prompt.save(update_fields=["active_version", "updated_at"])
    else:
        PromptVersion.objects.filter(pk=prompt.active_version.pk).update(
            body="OLD_ROUTE_PROMPT",
        )
    yield None


@pytest.mark.django_db
class TestChatStrategyRouteFirstMigration:
    def test_forwards_resyncs_default_strategy_to_route_first_body(
        self,
        stale_strategy_default_prompt: None,
    ) -> None:
        resync.forwards(django_apps, None)

        prompt = Prompt.objects.get(slug="chat.strategy.default", scope="system", space=None)
        assert prompt.active_version is not None
        assert prompt.active_version.body == _STRATEGY_DEFAULT
        assert "代码理解" in prompt.active_version.body
        assert "当前仓库只是入口" in prompt.active_version.body
        assert "route-first" in prompt.active_version.change_note
