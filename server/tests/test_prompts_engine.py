"""Jinja2 ImmutableSandboxedEnvironment 单例与沙箱行为测试。"""
from __future__ import annotations

import pytest
from jinja2 import StrictUndefined
from jinja2.exceptions import SecurityError, UndefinedError
from jinja2.sandbox import ImmutableSandboxedEnvironment

from prompts.engine import get_jinja_env
from prompts.exceptions import (
    PromptError,
    PromptNotFoundError,
    PromptRenderError,
    PromptVariableMissingError,
)


class TestJinjaEngine:
    def test_env_singleton_returns_same_instance(self) -> None:
        env1 = get_jinja_env()
        env2 = get_jinja_env()
        assert env1 is env2

    def test_env_is_immutable_sandboxed(self) -> None:
        env = get_jinja_env()
        assert isinstance(env, ImmutableSandboxedEnvironment)

    def test_env_uses_strict_undefined(self) -> None:
        env = get_jinja_env()
        assert env.undefined is StrictUndefined

    def test_env_autoescape_is_false(self) -> None:
        """autoescape=False 时,HTML 特殊字符保留原样(不做 &lt; 转义)。

        Rule 1 修正:Plan 原断言 "<b><script></script></b>" 系字符串拼接笔误。
        模板 "<b>{{x}}</b>" 在 x="<script>" 时渲染结果为 "<b><script></b>"
        (纯字面量替换,无闭合标签自动补全)。关键验证点是输出含原始 "<script>"
        字面量而非 "&lt;script&gt;" 实体,证明 autoescape=False。
        """
        env = get_jinja_env()
        result = env.from_string("<b>{{x}}</b>").render(x="<script>")
        assert result == "<b><script></b>"
        assert "&lt;" not in result  # 关键:未做 HTML 转义

    def test_env_strict_undefined_raises_on_missing_var(self) -> None:
        env = get_jinja_env()
        tmpl = env.from_string("{{ missing_var }}")
        with pytest.raises(UndefinedError):
            tmpl.render()

    def test_immutable_sandbox_blocks_mutator_call(self) -> None:
        """ImmutableSandboxedEnvironment 必须拒绝对 dict/list/set 调用 mutate 方法。"""
        env = get_jinja_env()
        tmpl = env.from_string("{{ d.update({'x': 1}) }}")
        with pytest.raises(SecurityError):
            tmpl.render(d={})

    def test_sandbox_blocks_dunder_access(self) -> None:
        """SandboxedEnvironment 必须拒绝访问 Python 内置 dunder 属性。"""
        env = get_jinja_env()
        tmpl = env.from_string("{{ ''.__class__.__mro__ }}")
        with pytest.raises(SecurityError):
            tmpl.render()


class TestPromptExceptions:
    def test_variable_missing_error_shape(self) -> None:
        e = PromptVariableMissingError("slug.x", ["a", "b"])
        assert e.slug == "slug.x"
        assert e.missing == ["a", "b"]
        assert isinstance(e, PromptError)

    def test_not_found_error_shape(self) -> None:
        e = PromptNotFoundError("slug.x")
        assert e.slug == "slug.x"
        assert isinstance(e, PromptError)

    def test_render_error_shape(self) -> None:
        e = PromptRenderError("slug.x", "undefined_variable: name")
        assert e.slug == "slug.x"
        assert "undefined" in e.reason
        assert isinstance(e, PromptError)
