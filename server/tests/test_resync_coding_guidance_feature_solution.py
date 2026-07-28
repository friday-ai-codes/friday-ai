"""chat builtin prompt feature-solution resync migration tests。"""

from __future__ import annotations

import importlib

import pytest
from django.apps import apps as django_apps

from chat.conversation_service import _CODING_GUIDANCE, _STRATEGY_DEFAULT
from prompts.models import Prompt, PromptVersion

resync = importlib.import_module("prompts.migrations.0011_resync_coding_guidance_feature_solution")


def _set_stale_body(slug: str) -> Prompt:
    prompt = Prompt.objects.select_related("active_version").get(
        slug=slug,
        scope="system",
        space=None,
    )
    assert prompt.active_version is not None
    PromptVersion.objects.filter(pk=prompt.active_version.pk).update(body=f"STALE:{slug}")
    prompt.refresh_from_db()
    return prompt


@pytest.mark.django_db
class TestResyncCodingGuidanceFeatureSolution:
    def test_forwards_resyncs_both_builtin_prompts(self) -> None:
        _set_stale_body("chat.coding_guidance")
        _set_stale_body("chat.strategy.default")

        resync.forwards(django_apps, None)

        coding = Prompt.objects.select_related("active_version").get(
            slug="chat.coding_guidance",
            scope="system",
            space=None,
        )
        strategy = Prompt.objects.select_related("active_version").get(
            slug="chat.strategy.default",
            scope="system",
            space=None,
        )
        assert coding.active_version is not None
        assert coding.active_version.body == _CODING_GUIDANCE
        assert "start_feature_solution" in coding.active_version.body
        assert strategy.active_version is not None
        assert strategy.active_version.body == _STRATEGY_DEFAULT

    def test_forwards_is_idempotent_after_resync(self) -> None:
        coding = _set_stale_body("chat.coding_guidance")
        strategy = _set_stale_body("chat.strategy.default")
        resync.forwards(django_apps, None)
        counts_after_resync = {
            coding.slug: coding.versions.count(),
            strategy.slug: strategy.versions.count(),
        }

        resync.forwards(django_apps, None)

        assert coding.versions.count() == counts_after_resync[coding.slug]
        assert strategy.versions.count() == counts_after_resync[strategy.slug]

    def test_forwards_skips_missing_prompts(self) -> None:
        Prompt.objects.filter(
            slug__in=["chat.coding_guidance", "chat.strategy.default"],
            scope="system",
            space=None,
        ).delete()

        resync.forwards(django_apps, None)
