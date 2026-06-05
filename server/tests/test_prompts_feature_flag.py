"""PROMPT_CENTER_DISABLED_KEYS 灰度开关测试（contract）。"""
from __future__ import annotations

import pytest

from prompts.exceptions import PromptVariableMissingError
from prompts.models import Prompt, PromptCategory, PromptScope
from prompts.services import _get_disabled_keys, append_version, render_prompt


class TestGetDisabledKeys:
    """`_get_disabled_keys` 的纯函数行为。"""

    def test_empty_env_var_returns_empty_set(self, monkeypatch) -> None:
        monkeypatch.delenv("PROMPT_CENTER_DISABLED_KEYS", raising=False)
        assert _get_disabled_keys() == set()

    def test_single_key(self, monkeypatch) -> None:
        monkeypatch.setenv(
            "PROMPT_CENTER_DISABLED_KEYS", "chat.system.developer"
        )
        assert _get_disabled_keys() == {"chat.system.developer"}

    def test_multiple_comma_separated_keys(self, monkeypatch) -> None:
        monkeypatch.setenv(
            "PROMPT_CENTER_DISABLED_KEYS",
            "chat.system.developer,aux.title_generation,repo.summary_generator",
        )
        assert _get_disabled_keys() == {
            "chat.system.developer",
            "aux.title_generation",
            "repo.summary_generator",
        }

    def test_whitespace_trimmed(self, monkeypatch) -> None:
        monkeypatch.setenv(
            "PROMPT_CENTER_DISABLED_KEYS", "  a.b ,  c.d  "
        )
        assert _get_disabled_keys() == {"a.b", "c.d"}

    def test_empty_segments_ignored(self, monkeypatch) -> None:
        monkeypatch.setenv("PROMPT_CENTER_DISABLED_KEYS", ",a.b,,,c.d,")
        assert _get_disabled_keys() == {"a.b", "c.d"}


@pytest.mark.django_db(transaction=True)
class TestPromptCenterDisabledKeys:
    async def test_env_var_hit_bypasses_db(
        self, admin_user, monkeypatch
    ) -> None:
        """DB 有记录,但环境变量命中 -> 走 fallback 路径。"""
        prompt = await Prompt.objects.acreate(
            slug="chat.system.developer",
            category=PromptCategory.CHAT_AGENT,
            scope=PromptScope.SYSTEM,
            title="t",
            created_by=admin_user,
        )
        await append_version(prompt, "DB_BODY", admin_user)

        monkeypatch.setenv(
            "PROMPT_CENTER_DISABLED_KEYS", "chat.system.developer"
        )
        result = await render_prompt(
            slug="chat.system.developer",
            variables={},
            fallback="FALLBACK_BODY",
        )
        assert result == "FALLBACK_BODY"
        assert "DB_BODY" not in result

    async def test_empty_env_var_allows_db_path(
        self, admin_user, monkeypatch
    ) -> None:
        """未设置环境变量时走 DB 路径。"""
        prompt = await Prompt.objects.acreate(
            slug="chat.system.developer",
            category=PromptCategory.CHAT_AGENT,
            scope=PromptScope.SYSTEM,
            title="t",
            created_by=admin_user,
        )
        await append_version(prompt, "DB_BODY", admin_user)

        monkeypatch.delenv("PROMPT_CENTER_DISABLED_KEYS", raising=False)
        result = await render_prompt(
            slug="chat.system.developer",
            variables={},
            fallback="FALLBACK_BODY",
        )
        # DB 路径:原 body 被 Jinja2 渲染(无变量)
        assert result == "DB_BODY"

    async def test_disabled_key_still_runs_declared_var_check(
        self, monkeypatch
    ) -> None:
        """灰度命中时 fallback 路径仍做声明校验(contract 约束)。"""
        monkeypatch.setenv(
            "PROMPT_CENTER_DISABLED_KEYS", "test.missing"
        )
        with pytest.raises(PromptVariableMissingError) as exc_info:
            await render_prompt(
                slug="test.missing",
                variables={},  # 缺 name
                fallback="Hello {{name}}",
            )
        assert exc_info.value.missing == ["name"]

    async def test_multiple_comma_separated_keys_hit(
        self, admin_user, monkeypatch
    ) -> None:
        """多个逗号分隔的 key 都命中时,各 slug 独立走 fallback。"""
        # 两条 prompt
        for slug in ("aux.title_generation", "aux.commit_message"):
            prompt = await Prompt.objects.acreate(
                slug=slug,
                category=PromptCategory.AUX_MODEL,
                scope=PromptScope.SYSTEM,
                title=slug,
                created_by=admin_user,
            )
            await append_version(prompt, f"DB_{slug}", admin_user)

        monkeypatch.setenv(
            "PROMPT_CENTER_DISABLED_KEYS",
            "aux.title_generation,aux.commit_message",
        )
        r1 = await render_prompt(
            slug="aux.title_generation",
            variables={},
            fallback="FB_TITLE",
        )
        r2 = await render_prompt(
            slug="aux.commit_message",
            variables={},
            fallback="FB_COMMIT",
        )
        assert r1 == "FB_TITLE"
        assert r2 == "FB_COMMIT"
