"""Agent tool 输入/输出 Pydantic v2 schema 包 —— per implementation contract / contract。

本包集中所有 agent tool 的字段冻结契约：

- ``FindRelatedCodeInput`` / ``FindRelatedCodeOutput`` / ``NeighborOutput``
  （per implementation 01 / success criterion-#3）
- ``SearchRepositoryCodeInput`` / ``SearchRepositoryCodeOutput``
  （per implementation contract / contract）

字段冻结由 ``tests/agents/test_tool_contracts.py`` 的 snapshot 测试守护
（per contract）：任何字段名 / 类型 / 默认值漂移都会立即触发 fixture diff。
"""

from __future__ import annotations

from agents.tools.schemas.find_related_code import (
    FindRelatedCodeInput,
    FindRelatedCodeOutput,
    NeighborOutput,
)
from agents.tools.schemas.repository_relevance import (
    RepositoryRelevanceCandidate,
    RepositoryRelevanceInput,
    RepositoryRelevanceOutput,
)
from agents.tools.schemas.search_repository_code import (
    SearchRepositoryCodeInput,
    SearchRepositoryCodeOutput,
)

__all__ = [
    "FindRelatedCodeInput",
    "FindRelatedCodeOutput",
    "NeighborOutput",
    "RepositoryRelevanceCandidate",
    "RepositoryRelevanceInput",
    "RepositoryRelevanceOutput",
    "SearchRepositoryCodeInput",
    "SearchRepositoryCodeOutput",
]
