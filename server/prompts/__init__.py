"""Prompts app — 统一提示词管理基础设施 (v19.0 Phase)。
本 App 提供：
- `Prompt` / `PromptVersion` 模型（append-only 版本化）
- `render_prompt` 统一渲染入口（Jinja2 ImmutableSandboxedEnvironment 沙箱）
- `PromptSlugs` 命名空间常量（Phase 调用点直接 import）
- CRUD REST API（Plan）
调用方应通过 `from prompts.services import render_prompt` 使用渲染功能，
通过 `from prompts.keys import PromptSlugs` 引用 slug 常量。
"""
