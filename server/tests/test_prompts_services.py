"""render_prompt / get_active_prompt / get_declared_variables / append_version 测试。"""
from __future__ import annotations

import pytest

from prompts.exceptions import (
    PromptNotFoundError,
    PromptVariableMissingError,
)
from prompts.models import Prompt, PromptCategory, PromptScope
from prompts.services import (
    VARIABLE_MAX_LENGTH,
    append_version,
    get_declared_variables,
    render_prompt,
)


class TestGetDeclaredVariables:
    def test_extracts_ordered_unique_vars(self) -> None:
        assert get_declared_variables("{{a}} {{b}} {{a}}") == ["a", "b"]

    def test_ignores_attribute_access(self) -> None:
        assert get_declared_variables("{{ns.attr}}") == []

    def test_handles_spaces_around_var(self) -> None:
        assert get_declared_variables("{{  name  }}") == ["name"]

    def test_empty_body_returns_empty_list(self) -> None:
        assert get_declared_variables("") == []

    def test_no_placeholders_returns_empty(self) -> None:
        assert get_declared_variables("plain text no vars") == []


@pytest.mark.django_db(transaction=True)
class TestRenderPrompt:
    async def test_fallback_when_db_empty(self) -> None:
        result = await render_prompt(
            slug="nonexistent",
            variables={},
            fallback="HELLO",
        )
        assert result == "HELLO"

    async def test_fallback_substitutes_variables(self) -> None:
        result = await render_prompt(
            slug="nonexistent",
            variables={"name": "Alice"},
            fallback="Hello {{name}}",
        )
        assert result == "Hello Alice"

    async def test_fallback_raises_on_missing_var(self) -> None:
        with pytest.raises(PromptVariableMissingError) as exc_info:
            await render_prompt(
                slug="nonexistent",
                variables={},
                fallback="Hello {{name}}",
            )
        assert exc_info.value.missing == ["name"]

    async def test_raises_not_found_without_fallback(self) -> None:
        with pytest.raises(PromptNotFoundError):
            await render_prompt(slug="nonexistent", variables={})

    async def test_db_path_wraps_variables_in_xml_tags(self, admin_user) -> None:
        prompt = await Prompt.objects.acreate(
            slug="test.xml_wrap",
            category=PromptCategory.AUX_MODEL,
            scope=PromptScope.SYSTEM,
            title="t",
            created_by=admin_user,
        )
        await append_version(prompt, "Name: {{name}}", admin_user)
        result = await render_prompt(
            slug="test.xml_wrap",
            variables={"name": "Alice"},
        )
        assert "<name>Alice</name>" in result

    async def test_truncates_long_variable_value(self, admin_user) -> None:
        prompt = await Prompt.objects.acreate(
            slug="test.truncate",
            category=PromptCategory.AUX_MODEL,
            scope=PromptScope.SYSTEM,
            title="t",
            created_by=admin_user,
        )
        await append_version(prompt, "{{v}}", admin_user)
        long_val = "A" * (VARIABLE_MAX_LENGTH + 500)
        result = await render_prompt(
            slug="test.truncate",
            variables={"v": long_val},
        )
        # 结果含 tag 包裹 + 截断后的 A 串（总长小于原始）
        assert "A" * VARIABLE_MAX_LENGTH in result
        assert "A" * (VARIABLE_MAX_LENGTH + 1) not in result

    async def test_escapes_double_brace_in_value(self, admin_user) -> None:
        prompt = await Prompt.objects.acreate(
            slug="test.double_brace",
            category=PromptCategory.AUX_MODEL,
            scope=PromptScope.SYSTEM,
            title="t",
            created_by=admin_user,
        )
        await append_version(prompt, "{{v}}", admin_user)
        result = await render_prompt(
            slug="test.double_brace",
            variables={"v": "{{x}}"},
        )
        # 双花括号被 HTML entity 转义
        assert "&#123;&#123;" in result
        assert "&#125;&#125;" in result

    async def test_variable_missing_raises_typed_error_db_path(
        self, admin_user
    ) -> None:
        prompt = await Prompt.objects.acreate(
            slug="test.missing_var",
            category=PromptCategory.AUX_MODEL,
            scope=PromptScope.SYSTEM,
            title="t",
            created_by=admin_user,
        )
        await append_version(prompt, "Hello {{name}} from {{place}}", admin_user)
        with pytest.raises(PromptVariableMissingError) as exc_info:
            await render_prompt(
                slug="test.missing_var",
                variables={"name": "Alice"},
            )
        assert exc_info.value.slug == "test.missing_var"
        assert exc_info.value.missing == ["place"]

    async def test_project_override_precedence(
        self, admin_user, project
    ) -> None:
        sys_p = await Prompt.objects.acreate(
            slug="shared.override",
            category=PromptCategory.AUX_MODEL,
            scope=PromptScope.SYSTEM,
            title="sys",
            created_by=admin_user,
        )
        await append_version(sys_p, "SYSTEM", admin_user)
        proj_p = await Prompt.objects.acreate(
            slug="shared.override",
            category=PromptCategory.AUX_MODEL,
            scope=PromptScope.PROJECT,
            space=project,
            title="proj",
            created_by=admin_user,
        )
        await append_version(proj_p, "PROJECT", admin_user)

        result_sys = await render_prompt(slug="shared.override", variables={})
        result_proj = await render_prompt(
            slug="shared.override",
            project_id=str(project.id),
            variables={},
        )
        assert result_sys == "SYSTEM"
        assert result_proj == "PROJECT"
