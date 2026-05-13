"""Phase Plan — Pitfall 4 golden snapshot baseline 测试。
本文件锁定 `LayeredSearchService.search` 在确定性 mock 下的 `final_context`
字节级行为，作为后续每个 plan（Provider 抽象 / RAG 解耦 / 4 callsite 切换）的
**唯一 acceptance gate**：
 pytest server/tests/codegraph/test_layered_search_golden.py -v
只要 20/20 全绿，就证明本 phase 的拆分阶段没有引入任何语义漂移。
每次 mock 数据或 LayeredSearchService 内部格式变化导致 fixture 需要更新时，
重新跑（项目根）：
 cd server && uv run python -m tests.codegraph._generate_golden_fixtures
然后人工 review `git diff server/tests/fixtures/layered_search_golden/` 确认所有
变化是预期的，再 commit。
per / / 。
"""
from __future__ import annotations
from pathlib import Path
import pytest
from codegraph.services.layered_search import LayeredSearchService
from tests.codegraph.conftest import GOLDEN_QUERIES_REGISTRY, GoldenQueryEntry
FIXTURE_DIR: Path = (
 Path(__file__).resolve.parent.parent / "fixtures" / "layered_search_golden"
)
_METADATA_PREFIX = "# tokens="
def _split_fixture(text: str) -> tuple[str, str]:
 """把 fixture 全文切成 (final_context_body, metadata_line)。
 fixture 文件格式（per _generate_golden_fixtures.py）：
 {final_context.rstrip("\\n")}
 \\n ← 空行视觉分隔
 # tokens=N source_layer=L final_chunks=K\\n
 回读 body 不含末尾换行。比对时 `actual = result.final_context.rstrip("\\n")`
 与 expected_body 字节级一致即认定零漂移（trailing 换行不影响 LLM 上下文语义）。
 """
 stripped = text.rstrip("\n")
 sep = "\n\n" + _METADATA_PREFIX
 idx = stripped.rfind(sep)
 assert idx != -1, "fixture missing `# tokens=` metadata line"
 body = stripped[:idx]
 metadata = stripped[idx + 2:]
 return body, metadata
def _parse_metadata(metadata_line: str) -> tuple[int, str, int]:
 """解析 `# tokens=N source_layer=L final_chunks=K` 返回 (tokens, source_layer, final_chunks)。"""
 assert metadata_line.startswith(_METADATA_PREFIX), metadata_line
 parts = metadata_line.split
 kv = {p.split("=", 1)[0]: p.split("=", 1)[1] for p in parts if "=" in p}
 return int(kv["tokens"]), kv["source_layer"], int(kv["final_chunks"])
def _compute_source_layer(layers: list) -> str:
 """与 _generate_golden_fixtures.py 同算法：L2 → L4 → L3 优先级首个 result_count > 0。"""
 by_layer = {lr.layer: lr for lr in layers}
 for tag in ("L2", "L4", "L3"):
 lr = by_layer.get(tag)
 if lr is not None and lr.result_count > 0:
 return tag
 return "EMPTY"
def _compute_final_chunks(layers: list) -> int:
 by = {lr.layer: lr.result_count for lr in layers}
 return by.get("L2", 0) + by.get("L3", 0) + by.get("L4", 0)
@pytest.mark.asyncio
@pytest.mark.parametrize(
 "entry",
 GOLDEN_QUERIES_REGISTRY,
 ids=lambda e: f"{e.nn}-{e.slug}",
)
async def test_golden_final_context_byte_equivalence(
 entry: GoldenQueryEntry,
 golden_mock_environment,
) -> None:
 """对每条 golden query 校验 LayeredSearchService 输出与已 commit fixture 字节一致。
 断言层级：
 1. `result.final_context` == fixture body（字节级）
 2. `result.total_tokens` == fixture metadata 的 tokens
 3. `_compute_source_layer(result.layers)` == fixture metadata 的 source_layer
 4. `_compute_final_chunks(result.layers)` == fixture metadata 的 final_chunks
 """
 fixture_path = FIXTURE_DIR / f"{entry.nn}-{entry.slug}.txt"
 assert fixture_path.exists, f"missing fixture: {fixture_path}"
 text = fixture_path.read_text(encoding="utf-8")
 expected_body, metadata_line = _split_fixture(text)
 expected_tokens, expected_layer, expected_chunks = _parse_metadata(metadata_line)
 repo_ids = list(entry.repository_ids) if entry.repository_ids else None
 result = await LayeredSearchService.search(
 entry.query,
 repository_ids=repo_ids,
 project_id=entry.project_id,
 branch_name=entry.branch_name,
 max_tokens=entry.max_tokens,
 top_k=entry.top_k,
 )
 # 1. 字节级 final_context 对比（最关键的零漂移断言）
 actual_body = result.final_context.rstrip("\n")
 assert actual_body == expected_body, (
 f"final_context drift for {entry.nn}-{entry.slug}; "
 f"regenerate via `python -m tests.codegraph._generate_golden_fixtures` "
 f"and review the diff if drift is intentional."
 )
 # 2. token 计数（tiktoken cl100k_base 确定性）
 assert result.total_tokens == expected_tokens, (
 f"total_tokens drift for {entry.nn}-{entry.slug}: "
 f"actual={result.total_tokens} expected={expected_tokens}"
 )
 # 3. source_layer 优先级算法一致
 actual_layer = _compute_source_layer(result.layers)
 assert actual_layer == expected_layer, (
 f"source_layer drift for {entry.nn}-{entry.slug}: "
 f"actual={actual_layer} expected={expected_layer}"
 )
 # 4. final_chunks 计数一致
 actual_chunks = _compute_final_chunks(result.layers)
 assert actual_chunks == expected_chunks, (
 f"final_chunks drift for {entry.nn}-{entry.slug}: "
 f"actual={actual_chunks} expected={expected_chunks}"
 )
