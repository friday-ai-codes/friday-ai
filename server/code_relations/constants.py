"""代码关系图谱常量。
**Pitfall 1：`NAMESPACE_REPO` 永不变更**，否则历史全量 chunk_id 漂移导致
Qdrant payload 与 ChunkRegistry 全军覆没；若需要更换命名空间策略请走
"数据迁移 + 全量 reindex" 双写过渡，不允许直接改值。
"""
from __future__ import annotations
import uuid
NAMESPACE_REPO: uuid.UUID = uuid.UUID("00000000-0000-5000-a000-000000000001")
"""chunk_id 生成所用的 uuid5 命名空间常量（v5 namespace，固定不变）。
与 `uuid.NAMESPACE_DNS` / `uuid.NAMESPACE_URL` 同等级；定义详见 。
"""
