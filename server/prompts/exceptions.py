"""Prompt 渲染异常体系。HTTP 状态码映射见 views.py 的 exception handler。"""
from __future__ import annotations
class PromptError(Exception):
 """基类。"""
class PromptNotFoundError(PromptError):
 """slug 在代码中引用但 DB 无记录且无 fallback（404）。"""
 def __init__(self, slug: str):
 self.slug = slug
 super.__init__(f"prompt_not_found: {slug}")
class PromptVariableMissingError(PromptError):
 """调用方传入变量不覆盖 body 声明的变量集（422）。
 Preview / 运行时调用点都应对 422 做用户友好提示。
 """
 def __init__(self, slug: str, missing: list[str]):
 self.slug = slug
 self.missing = missing
 super.__init__(
 f"prompt_variable_missing: slug={slug} missing={missing}"
 )
class PromptRenderError(PromptError):
 """Jinja2 沙箱渲染内部故障（500）。通常是 body 模板语法错误或属性穿透。"""
 def __init__(self, slug: str, reason: str):
 self.slug = slug
 self.reason = reason
 super.__init__(f"prompt_render_error: slug={slug} reason={reason}")
