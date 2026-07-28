"""builtin prompt 漂移运维命令测试。"""

from __future__ import annotations

from io import StringIO

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError

from chat.conversation_service import _CODING_GUIDANCE
from prompts.builtin_contract import detect_builtin_prompt_drift
from prompts.models import Prompt, PromptVersion


def _make_coding_guidance_stale() -> Prompt:
    prompt = Prompt.objects.select_related("active_version").get(
        slug="chat.coding_guidance",
        scope="system",
        space=None,
    )
    assert prompt.active_version is not None
    PromptVersion.objects.filter(pk=prompt.active_version.pk).update(body="STALE_CODING_GUIDANCE")
    prompt.refresh_from_db()
    return prompt


@pytest.mark.django_db
class TestCheckBuiltinPromptDrift:
    def test_detect_returns_hashes_for_stale_body(self) -> None:
        _make_coding_guidance_stale()

        drift = detect_builtin_prompt_drift()

        item = next(item for item in drift if item["slug"] == "chat.coding_guidance")
        assert item["reason"] == "body_mismatch"
        assert item["py_sha256"] != item["db_sha256"]
        assert item["py_length"] == len(_CODING_GUIDANCE)

    def test_command_succeeds_without_drift(self) -> None:
        stdout = StringIO()

        call_command("check_builtin_prompt_drift", stdout=stdout)

        assert "零漂移" in stdout.getvalue()

    def test_command_raises_and_lists_slug_when_drift_exists(self) -> None:
        _make_coding_guidance_stale()
        stdout = StringIO()

        with pytest.raises(CommandError):
            call_command("check_builtin_prompt_drift", stdout=stdout)

        assert "chat.coding_guidance" in stdout.getvalue()

    def test_fix_appends_version_and_restores_clean_check(self) -> None:
        prompt = _make_coding_guidance_stale()
        version_count = prompt.versions.count()

        call_command("check_builtin_prompt_drift", fix=True, stdout=StringIO())

        prompt.refresh_from_db()
        assert prompt.active_version is not None
        assert prompt.active_version.body == _CODING_GUIDANCE
        assert prompt.versions.count() == version_count + 1
        assert detect_builtin_prompt_drift() == []
        call_command("check_builtin_prompt_drift", stdout=StringIO())
