"""EdgeBuilder 抽象基类（per contract）。

所有 6 类 builder 必须继承本基类并实现 `async def build(...)`，
返回未保存的 `ChunkEdge` 实例列表（不直接写库；orchestrator 在 plan 07
汇总后调 `storage.bulk_insert_edges(...)` 统一入库 per contract）。
"""

from __future__ import annotations

import abc
import uuid
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from code_relations.models import ChunkEdge
    from repositories.models import Repository

__all__ = ["BaseEdgeBuilder"]


class BaseEdgeBuilder(abc.ABC):
    """所有 EdgeBuilder 的抽象基类。

    子类必须实现 `build(repository, dirty_chunk_ids, *, branch_name="")`：
    - `repository` 为 `repositories.Repository` 实例（带 .id / .git_url 等）。
    - `dirty_chunk_ids` 为本次索引刚写入或更新的 chunk_id 列表（来源：indexer
      `_upsert_chunk_registry_batch` 返回的 registry_rows，plan 07 转换）。
    - `branch_name` 为写入侧归一化后的分支名（""=base，initial implementation 透传链）。
      子类据此对 Symbol/ChunkRegistry/ChunkEdge 查询加 branch 过滤，并把
      branch_name 打到产出的 ChunkEdge 上（base 路径 "" 保持字节不变）。
    - 返回 `list[ChunkEdge]`：**未 save 的实例**，统一交由 orchestrator 走
      `storage.bulk_insert_edges(...)` 落库（避免每 builder 触发独立写事务）。

    builder 失败时直接抛异常；orchestrator 用 `asyncio.gather(..., return_exceptions=True)`
    捕获并记 structlog error（per contract），不阻塞其他 builder。
    """

    edge_type_label: str
    """子类必填：用于 structlog 日志的 builder 标识（如 'CallEdge'）。"""

    @abc.abstractmethod
    async def build(
        self,
        repository: "Repository",
        dirty_chunk_ids: list[uuid.UUID],
        *,
        branch_name: str = "",
    ) -> list["ChunkEdge"]:
        """构建本 builder 负责的 ChunkEdge 实例列表（未 save）。"""
