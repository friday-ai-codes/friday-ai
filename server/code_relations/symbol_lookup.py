"""Symbol → chunk_id 反查（initial implementation EdgeBuilder 共用）。

contract 决策：initial implementation ChunkRegistry 不存 line_start/line_end；codegraph.Symbol
无 chunk_id 字段。**唯一可行方案**是 Qdrant payload（indexer _build_points 已写
file_path/start_line/end_line）+ 内存 bisect。SymbolChunkResolver 在每次 builder
构建时实例化一次，lazy scroll 一遍 Qdrant 拉 payload，构建 dict[file_path,
list[(line_start, line_end, chunk_id)]] 内存索引，单文件 N chunks 二分查找。

内存预估：10k chunks × (str×40 + int×16 + uuid×16) ≈ 0.7 MB，可接受。
"""

from __future__ import annotations

import bisect
import uuid
from typing import Any

import structlog
from asgiref.sync import sync_to_async

from services.branch_utils import get_effective_collection_name
from services.qdrant_service import QdrantService

logger = structlog.get_logger(__name__)

__all__ = ["SymbolChunkResolver"]


class SymbolChunkResolver:
    """文件级 line→chunk_id 二分查找解析器。

    每个 builder build() 内实例化一次；lazy load + 全 builder 调用期 cache。
    initial implementation 不跨 builder 共享（避免 cache 一致性复杂度），instances 与
    builder 实例 1:1。
    """

    def __init__(self, repository_id: str, *, branch_name: str = "") -> None:
        self.repository_id = repository_id
        # initial implementation：feature 分支的 chunk 向量在 overlay collection；base（""）
        # 落到旧 collection（字节不变）。base→base collection，feature→overlay。
        self.branch_name = branch_name
        self._index: dict[str, list[tuple[int, int, uuid.UUID]]] | None = None

    async def resolve(self, file_path: str, line_number: int) -> uuid.UUID | None:
        """返回 file_path 中包含 line_number 的 chunk_id；否则 None。

        包含语义：`chunk.line_start <= line_number <= chunk.line_end`。

        work item 注：``bisect_right(keys, line_number) - 1`` 假设 chunk 区间不
        重叠。initial implementation chunker 实测多数情况下相邻 chunk 严格非重叠，但跨
        语言（tree-sitter docstring 块）偶尔可能区间相交，此时仅返回最后
        一个 start <= line_number 的 entry，错过其他覆盖该 line 的 chunk。
        initial implementation 接受该简化；如需严格命中所有覆盖区间，应改为线性扫描。
        """
        if self._index is None:
            self._index = await self._load_index()
        entries = self._index.get(file_path)
        if not entries:
            return None
        keys = [e[0] for e in entries]
        idx = bisect.bisect_right(keys, line_number) - 1
        if idx < 0:
            return None
        line_start, line_end, cid = entries[idx]
        if line_start <= line_number <= line_end:
            return cid
        return None

    @sync_to_async
    def _load_index(self) -> dict[str, list[tuple[int, int, uuid.UUID]]]:
        client = QdrantService.get_client()
        collection = get_effective_collection_name(
            self.repository_id, self.branch_name
        )
        index: dict[str, list[tuple[int, int, uuid.UUID]]] = {}
        offset: Any = None
        count = 0
        while True:
            points, next_offset = client.scroll(
                collection_name=collection,
                scroll_filter=None,
                limit=1000,
                offset=offset,
                with_payload=["file_path", "start_line", "end_line"],
                with_vectors=False,
            )
            for p in points:
                payload = p.payload or {}
                fp = payload.get("file_path")
                ls = payload.get("start_line")
                le = payload.get("end_line")
                if fp is None or ls is None or le is None:
                    continue
                try:
                    cid = uuid.UUID(str(p.id))
                except (TypeError, ValueError):
                    continue
                index.setdefault(fp, []).append((int(ls), int(le), cid))
                count += 1
            if next_offset is None:
                break
            offset = next_offset
        for fp in index:
            index[fp].sort(key=lambda t: t[0])
        logger.info(
            "symbol_chunk_resolver_loaded",
            repository_id=self.repository_id,
            files=len(index),
            chunks=count,
        )
        return index
