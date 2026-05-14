"""hop1_reader 性能 gate —— Phase Plan perf 基准（per ROADMAP ）。
1000 rag_items × 平均 5 邻居 → ``extract_hop1_neighbors_raw`` +
``resolve_neighbor_metadata`` 总耗时 < 100ms（单次 in_bulk + 5000 元素 dict
操作）。
CI 默认 ``-m 'not perf'`` deselect；本地或性能 job 用 ``-m perf`` 运行
（per Phase）。
"""
from __future__ import annotations
import time
import uuid
import pytest
from code_relations.models import ChunkRegistry
from services.retrieval.hop1_reader import (
 extract_hop1_neighbors_raw,
 resolve_neighbor_metadata,
)
def _stub_reason(
 edge_type: str,
 source_file: str | None,
 target_file: str | None,
 metadata: dict,
) -> str:
 """ 后 ReasonFn 新签名（4 参数）。perf 测试不关心 reason 内容质量，
 仅验证 in_bulk 单次拉满 + 时延上限。"""
 return f"{edge_type} from {target_file}"
@pytest.mark.perf
@pytest.mark.django_db(transaction=True)
async def test_hop1_extract_plus_resolve_under_100ms_for_1000_chunks(
 repository,
) -> None:
 """1000 rag_items × 5 邻居指向 100 真实 ChunkRegistry rows，总耗时 < 100ms。"""
 registry_chunk_ids: list[uuid.UUID] = [uuid.uuid4 for _ in range(100)]
 rows = [
 ChunkRegistry(
 chunk_id=cid,
 content_hash=f"{i:064x}",
 repository=repository,
 file_path=f"src/perf/file_{i % 20}.py",
 chunk_index=i,
 line_start=i * 5,
 line_end=i * 5 + 4,
 )
 for i, cid in enumerate(registry_chunk_ids)
 ]
 await ChunkRegistry.objects.abulk_create(rows)
 registry_str_ids = [str(c) for c in registry_chunk_ids]
 rag_items: list[dict] =
 for i in range(1000):
 source_chunk_id = str(uuid.uuid4)
 neighbors = [
 [
 registry_str_ids[(i + k) % 100],
 "CALL",
 0.9 - k * 0.05,
 ]
 for k in range(5)
 ]
 rag_items.append(
 {
 "id": source_chunk_id,
 "score": 0.5,
 "payload": {
 "file_path": f"src/source_{i}.py",
 "chunk_index": 0,
 "content": "...",
 "related_chunks": neighbors,
 },
 "repository_id": str(repository.id),
 }
 )
 start = time.perf_counter
 raw = extract_hop1_neighbors_raw(rag_items)
 metadata = await resolve_neighbor_metadata(raw, hop=1, reason_fn=_stub_reason)
 elapsed = time.perf_counter - start
 assert len(raw) == 1000
 assert len(metadata) > 0
 assert all(m.hop == 1 for m in metadata)
 assert elapsed < 0.10, (
 f"hop1 extract+resolve {elapsed * 1000:.2f}ms > 100ms gate "
 f"(rag_items=1000, registry_rows=100, total_neighbors={sum(len(v) for v in raw.values)})"
 )
 print(
 f"\n[hop1_perf] 1000 rag_items × 5 邻居 / 100 registry rows: "
 f"{elapsed * 1000:.2f}ms (gate < 100ms)"
 )
