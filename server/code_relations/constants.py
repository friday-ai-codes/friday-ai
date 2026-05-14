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
MAX_HOPS: int = 2
"""HybridSearchService 图谱扩散最大跳数硬上限（per / ROADMAP ）。
字面赋值、**禁止 env 覆盖**——LLM 通过 MCP tool 传 hops=10 时直接抛 ValueError,
不允许通过环境变量绕过；Phase Plan / Plan `find_related` 入口须显式
校验 `if hops > MAX_HOPS: raise ValueError(...)`。
"""
TOP_NEIGHBORS_PER_HOP1: int = 10
"""一跳邻居（payload `related_chunks` 直读快照）二次裁剪上限（per ）。
Phase payload aggregator 已按 weight desc 截断到 20（`MAX_NEIGHBORS_PER_CHUNK`），
Phase 编排器读快照后再按 weight desc 截到 10，保 graph_context markdown
长度不爆 budget；字面赋值、禁 env 覆盖。
"""
TOP_NEIGHBORS_PER_HOP2: int = 50
"""二跳邻居（ChunkEdge ORM aiter）单次 ORM 拉满上限（per ）。
Phase 编排器 `_expand_hop2` 用
`ChunkEdge.objects.filter(...).order_by('-weight')[:TOP_NEIGHBORS_PER_HOP2]`
单次 ORM 拉满；上限防 hop1 = 10 chunks × 二跳爆炸式查询；字面赋值、禁 env 覆盖。
"""
CANDIDATE_EXTENSIONS: tuple[str, ...] = (
 ".py",
 ".ts",
 ".tsx",
 ".js",
 ".jsx",
 ".go",
)
"""ImportEdgeBuilder 候选文件扩展名（per ）。
新增语言（如 ``.rs`` / ``.java``）时改本常量并重启 worker 即可，无需触碰
builder 实现；如需改为运行时配置，可读 ``settings.CODEGRAPH_CANDIDATE_EXTENSIONS``
覆盖。
"""
