"""代码关系图谱常量。
**Pitfall 1：`NAMESPACE_REPO` 永不变更**，否则历史全量 chunk_id 漂移导致
Qdrant payload 与 ChunkRegistry 全军覆没；若需要更换命名空间策略请走
"数据迁移 + 全量 reindex" 双写过渡，不允许直接改值。
"""
from __future__ import annotations
import uuid
NAMESPACE_REPO: uuid.UUID = uuid.UUID("00000000-0000-5000-a000-000000000001")
"""chunk_id 生成所用的 uuid5 命名空间常量（固定字面值，永不变更）。
按 RFC 4122 §4.3，namespace 常量本身不要求特定 version（参考 `uuid.NAMESPACE_DNS
= UUID('6ba7b810-9dad-11d1-80b4-00c04fd430c8')`，那是 v1 时间型 UUID）；此值是
项目自选的随机常量，字面值里的 `5` 仅是 nibble 数字，与 RFC version 字段无关，
不要据此误以为 namespace 必须是 v5。
与 `uuid.NAMESPACE_DNS` / `uuid.NAMESPACE_URL` 同等级；定义详见 。
"""
MAX_NEIGHBORS_PER_CHUNK: int = 20
"""payload `related_chunks` 一跳快照的 top-K 上限（per Phase）。
Phase payload aggregator 按 weight desc 取前 N 条邻居写入 Qdrant
payload；Phase HybridSearchService 一跳扩散直读此快照。
"""
MAX_PAYLOAD_SIZE_BYTES: int = 5 * 1024
"""单 point payload 字节上限（per Phase，5 KB）。
Phase payload aggregator 在写 Qdrant 前用 `len(json.dumps(...).encode)`
测长，超限则继续把 related_chunks 截到 15 / 10 / 5 直至达标，避免单 point
payload 失控放大 Qdrant 内存压力。
"""
