"""Agent tool 输入/输出 Pydantic v2 schema 包 —— per Phase / 。
本包集中所有 agent tool 的字段冻结契约：
- `SearchRepositoryCodeInput` / `SearchRepositoryCodeOutput`（per / ）
字段冻结由 `tests/agents/test_tool_contracts.py` 的 snapshot 测试守护
（per ）：任何字段名 / 类型 / 默认值漂移都会立即触发 fixture diff。
"""
from __future__ import annotations
from agents.tools.schemas.search_repository_code import (
 SearchRepositoryCodeInput,
 SearchRepositoryCodeOutput,
)
__all__ = [
 "SearchRepositoryCodeInput",
 "SearchRepositoryCodeOutput",
]
