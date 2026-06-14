"""代码关系图谱跨 phase 接口类型定义。

定义 implementation ↔ implementation 间共享的 TypedDict / Protocol，作为「Plan 同源契约」
的强制载体（替代纯文档约束），让 mypy 在调用方误传字段名时静态拦截。
"""

from __future__ import annotations

import uuid
from typing import TypedDict

__all__ = ["ChunkRegistryRow"]


class ChunkRegistryRow(TypedDict):
    """`IndexerService._build_points` 返回的 ChunkRegistry 写入行结构（per contract）。

    与 ChunkRegistry 模型字段一一对应：
    - `chunk_id`：uuid5 同源稳定 PK（per contract / contract）
    - `content_hash`：sha256 hex of chunk content（64 字节）
    - `repository_id`：`str(repo.id)`，indexer 不解析为 UUID（contract 写法）
    - `file_path`：相对仓库根的路径字符串
    - `chunk_index`：≥0 整数，同 file_path 内 chunk 出现次序
    - `branch_name`：分支隔离维度（work item / implementation）。``""``=base，
      feature 为归一化后的分支名；与 ChunkRegistry.branch_name 字段对齐，供
      EdgeBuilder 分支过滤（contract）使用。
    - `line_start` / `line_end`：chunk 源码起止行（1-based 闭区间），与
      ChunkRegistry.line_start/line_end 对齐（IDX-02 行号反查地基）。``None``
      表示历史未回填 / 非 AST 切分回退；DB 层 ``chunkreg_line_range_valid``
      约束保证任一为 None 或 line_end>=line_start。

    implementation EdgeBuilder 可直接 `from code_relations.types import ChunkRegistryRow`
    在自身签名上复用，避免 typo `chunkid` / `contenthash` 滑过 mypy 直到运行期才 KeyError。
    """

    chunk_id: uuid.UUID
    content_hash: str
    repository_id: str
    file_path: str
    chunk_index: int
    branch_name: str
    line_start: int | None
    line_end: int | None
