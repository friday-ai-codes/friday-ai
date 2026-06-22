"""implementation Task 1 — graph_capable 路径 golden snapshot 二轮 baseline。

10 条 fixture × 字节级 `final_context` 比对，锁定 plan 落地的 GraphRAG 编排器
（`HybridSearchService._search_graph_capable`）输出契约。

设计与 implementation `tests/codegraph/test_layered_search_golden.py` 同 idiom：

- fixture 文件在 `tests/fixtures/hybrid_graph_capable_golden/{NN}-{slug}.txt`；
- 文件格式 `{body}\n\n# tokens=N source_layer=hybrid final_chunks=K\n`；
- 字节级 `actual.rstrip("\n") == expected_body`（trailing newline 不语义化）；
- 元数据行同时锁定 `total_tokens` 与 `final_chunks`（hop1+hop2 邻居数）。

**Mock 策略**：本测试不依赖真实 ORM / Qdrant / Embedding。直接在
`services.retrieval.hybrid_search` 模块边界 patch：

- `search_rag` → 返回固定 `LayerSnapshot`，items 含 payload.related_chunks
- `resolve_neighbor_metadata` → 返回固定 `list[NeighborMetadata]`（hop=1）
- `expand_hop2` → 返回固定 `list[NeighborMetadata]`（hop=2）
- `LocalProvider.lookup_symbols` → 返回固定 list 或 raise（fixture 9）

这样 fixture 生成完全确定，多次跑结果 byte-equal；无需 DB transaction。

**fixture 更新流程**：

```bash
# 重生成（仅在 production 代码合法改动 final_context 时执行）
cd server && GENERATE_GOLDEN=1 uv run pytest \
  tests/services/retrieval/test_hybrid_graph_capable_golden.py -v
git diff server/tests/fixtures/hybrid_graph_capable_golden/  # 人工 review

# 字节级 verify
cd server && uv run pytest \
  tests/services/retrieval/test_hybrid_graph_capable_golden.py -v
```
"""

from __future__ import annotations

import os
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest
from django.test.utils import override_settings

from services.code_intel.local_provider import LocalProvider
from services.code_intel.null_provider import NullProvider
from services.retrieval import HybridSearchService
from services.retrieval.find_related import explain_neighbor
from services.retrieval.types import (
    HybridSearchResult,
    LayerSnapshot,
    NeighborMetadata,
    RagSearchResult,
)


@pytest.fixture(autouse=True)
def _force_offline_token_estimator(monkeypatch: pytest.MonkeyPatch):
    """固定为离线 ``_FallbackEncoding`` 计数口径，保证 ``total_tokens`` 确定性。

    golden fixtures 在 tiktoken BPE 数据不可用（离线）时生成，统一走
    ``_FallbackEncoding``（commit「fix: keep retrieval tests offline stable」）。
    但 ``estimate_tokens`` 在 tiktoken BPE 数据可用时会改用真实 cl100k_base 编码，
    产出更低的 token 数，导致字节级 body 完全一致、仅 ``total_tokens`` 漂移。
    这里把估算器钉死在离线 fallback，使 CI（离线）与本地（已缓存 BPE）口径一致。
    """
    from services.retrieval import token_budget

    orig_get_encoding = token_budget._get_encoding
    orig_get_encoding.cache_clear()
    monkeypatch.setattr(
        token_budget,
        "_get_encoding",
        lambda encoding=token_budget.DEFAULT_ENCODING: token_budget._FallbackEncoding(),
    )
    yield
    orig_get_encoding.cache_clear()


class _NoExclusionMatcher:
    """no-op 排除匹配器替身（golden 场景无排除规则，永不命中）。"""

    def is_excluded(self, _rel_path: str) -> bool:
        return False

FIXTURE_DIR: Path = (
    Path(__file__).resolve().parent.parent.parent
    / "fixtures"
    / "hybrid_graph_capable_golden"
)

_METADATA_PREFIX = "# tokens="
_GENERATE_MODE: bool = os.environ.get("GENERATE_GOLDEN") == "1"


# ---------------------------------------------------------------------------
# fixture 文件 IO 帮助
# ---------------------------------------------------------------------------


def _split_fixture(text: str) -> tuple[str, str]:
    """切分 `{body}\n\n# tokens=...` 返回 (body, metadata_line)，与 implementation idiom 一致。"""
    stripped = text.rstrip("\n")
    sep = "\n\n" + _METADATA_PREFIX
    idx = stripped.rfind(sep)
    assert idx != -1, "fixture missing `# tokens=` metadata line"
    body = stripped[:idx]
    metadata = stripped[idx + 2 :]
    return body, metadata


def _parse_metadata(metadata_line: str) -> tuple[int, str, int]:
    """解析 `# tokens=N source_layer=hybrid final_chunks=K` → (tokens, source_layer, final_chunks)。"""
    assert metadata_line.startswith(_METADATA_PREFIX), metadata_line
    parts = metadata_line.split()
    kv = {p.split("=", 1)[0]: p.split("=", 1)[1] for p in parts if "=" in p}
    return int(kv["tokens"]), kv["source_layer"], int(kv["final_chunks"])


def _write_fixture(
    path: Path, *, body: str, total_tokens: int, final_chunks: int
) -> None:
    """写 fixture 文件（生成模式）。固定 `source_layer=hybrid`。"""
    metadata = (
        f"# tokens={total_tokens} source_layer=hybrid final_chunks={final_chunks}"
    )
    payload = f"{body.rstrip(chr(10))}\n\n{metadata}\n"
    path.write_text(payload, encoding="utf-8", newline="\n")


# ---------------------------------------------------------------------------
# scenario 数据模型
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class _RagItemSpec:
    """search_rag 返回 LayerSnapshot.items[i] 规格。"""

    chunk_id: str
    file_path: str
    content: str
    score: float = 0.85
    related_chunks: list[tuple[str, str, float]] | None = None
    repository_id: str = "repo-a"
    start_line: int = 1
    end_line: int = 20

    def to_item(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "file_path": self.file_path,
            "content": self.content,
            "language": "python",
            "chunk_index": 0,
            "start_line": self.start_line,
            "end_line": self.end_line,
            "repository_id": self.repository_id,
        }
        if self.related_chunks is not None:
            payload["related_chunks"] = [
                [cid, et, w] for cid, et, w in self.related_chunks
            ]
        return {
            "id": self.chunk_id,
            "score": self.score,
            "payload": payload,
            "repository_id": self.repository_id,
        }


@dataclass(frozen=True)
class _NeighborSpec:
    """mock NeighborMetadata 规格（用于 hop1/hop2 mock 返回）。"""

    chunk_id: str
    file_path: str
    line_start: int | None
    line_end: int | None
    edge_type: str
    weight: float
    hop: int

    def to_neighbor(self) -> NeighborMetadata:
        return NeighborMetadata(
            chunk_id=self.chunk_id,
            file_path=self.file_path,
            line_start=self.line_start,
            line_end=self.line_end,
            edge_type=self.edge_type,
            weight=self.weight,
            reason=explain_neighbor(self.edge_type),
            hop=self.hop,
        )


@dataclass(frozen=True)
class _Scenario:
    """单条 golden snapshot 场景规格。"""

    nn: str
    slug: str
    query: str
    repo_ids: list[str] | None
    rag_items: list[_RagItemSpec]
    hop1_neighbors: list[_NeighborSpec] = field(default_factory=list)
    hop2_neighbors: list[_NeighborSpec] = field(default_factory=list)
    symbol_results: list[dict[str, Any]] = field(default_factory=list)
    max_tokens: int = 8000
    top_k: int = 30
    enable_graph_enrichment: bool = True
    provider_type: str = "local"  # "local" | "null"
    symbol_raises: bool = False
    settings_overrides: dict[str, Any] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# 10 条 fixture 规格（registry）
# ---------------------------------------------------------------------------


def _h1(
    suffix: str,
    file_path: str,
    edge_type: str,
    weight: float,
    line: int = 10,
) -> _NeighborSpec:
    """hop1 邻居 helper（chunk_id 固定 nil-uuid + 后缀，保跨次跑稳定）。"""
    base = uuid.UUID("00000000-0000-0000-0000-000000000000")
    cid = str(uuid.uuid5(base, f"h1-{suffix}"))
    return _NeighborSpec(
        chunk_id=cid,
        file_path=file_path,
        line_start=line,
        line_end=line + 10,
        edge_type=edge_type,
        weight=weight,
        hop=1,
    )


def _h2(
    suffix: str,
    file_path: str,
    edge_type: str,
    weight: float,
    line: int = 42,
) -> _NeighborSpec:
    """hop2 邻居 helper。"""
    base = uuid.UUID("00000000-0000-0000-0000-000000000000")
    cid = str(uuid.uuid5(base, f"h2-{suffix}"))
    return _NeighborSpec(
        chunk_id=cid,
        file_path=file_path,
        line_start=line,
        line_end=line + 10,
        edge_type=edge_type,
        weight=weight,
        hop=2,
    )


def _src(
    slug: str,
    file_path: str,
    content: str,
    score: float = 0.85,
    repo_id: str = "repo-a",
    related: list[_NeighborSpec] | None = None,
) -> _RagItemSpec:
    """rag_item helper：related_chunks 从 hop1 spec 自动派生（仅 chunk_id/edge_type/weight）。"""
    base = uuid.UUID("00000000-0000-0000-0000-000000000000")
    cid = str(uuid.uuid5(base, f"rag-{slug}-{file_path}"))
    rc: list[tuple[str, str, float]] | None
    if related is None:
        rc = None
    else:
        rc = [(n.chunk_id, n.edge_type, n.weight) for n in related]
    return _RagItemSpec(
        chunk_id=cid,
        file_path=file_path,
        content=content,
        score=score,
        related_chunks=rc,
        repository_id=repo_id,
    )


# ---- fixture 01: chat_simple_query --------------------------------------
_F01_H1 = [
    _h1("login-auth-py", "src/auth/authenticate.py", "CALL", 0.92),
    _h1("login-session-py", "src/auth/session.py", "IMPORT", 0.78),
]
_F01 = _Scenario(
    nn="01",
    slug="chat_simple_query",
    query="user login flow",
    repo_ids=["repo-a"],
    rag_items=[
        _src(
            "01-login",
            "src/auth/login.py",
            "def login(req):\n    return authenticate(req.user)",
            score=0.86,
            related=_F01_H1,
        ),
    ],
    hop1_neighbors=_F01_H1,
)

# ---- fixture 02: agent_symbol_query (hop1 + hop2 双段) ------------------
_F02_H1 = [
    _h1("us-list", "src/users/api.py", "CALL", 0.88),
    _h1("us-create", "src/users/admin.py", "TEST_OF", 0.65),
]
_F02_H2 = [
    _h2("us-helper", "src/users/helpers.py", "IMPORT", 0.55),
    _h2("us-db", "src/users/db.py", "SAME_FILE", 0.42),
]
_F02 = _Scenario(
    nn="02",
    slug="agent_symbol_query",
    query="UserService",
    repo_ids=["repo-a"],
    rag_items=[
        _src(
            "02-userservice",
            "src/users/service.py",
            "class UserService:\n    def list(self): ...",
            score=0.92,
            related=_F02_H1,
        ),
    ],
    hop1_neighbors=_F02_H1,
    hop2_neighbors=_F02_H2,
    symbol_results=[
        {"id": "sym-us-1", "name": "UserService", "symbol_type": "CLASS"},
    ],
)

# ---- fixture 03: workflow_multi_repo -------------------------------------
_F03_H1 = [
    _h1("pd-a", "src/pipeline/process.py", "CALL", 0.81, line=12),
    _h1("pd-b", "lib/pipe/run.py", "IMPORT", 0.66, line=8),
]
_F03 = _Scenario(
    nn="03",
    slug="workflow_multi_repo",
    query="ProcessData",
    repo_ids=["repo-a", "repo-b"],
    rag_items=[
        _src(
            "03-pd-a",
            "src/pipeline/process.py",
            "def ProcessData(payload):\n    return transform(payload)",
            score=0.84,
            repo_id="repo-a",
            related=_F03_H1[:1],
        ),
        _src(
            "03-pd-b",
            "lib/pipe/run.py",
            "result = ProcessData(payload)",
            score=0.74,
            repo_id="repo-b",
            related=_F03_H1[1:],
        ),
    ],
    hop1_neighbors=_F03_H1,
)

# ---- fixture 04: empty_repo_graceful (rag_items 空) ----------------------
_F04 = _Scenario(
    nn="04",
    slug="empty_repo_graceful",
    query="totally_nonexistent_query_token_zz",
    repo_ids=["repo-empty"],
    rag_items=[],
)

# ---- fixture 05: null_provider_path (RagSearchResult) -------------------
_F05 = _Scenario(
    nn="05",
    slug="null_provider_path",
    query="user login flow",
    repo_ids=["repo-a"],
    rag_items=[
        _src(
            "05-null",
            "src/auth/login.py",
            "def login(req):\n    return authenticate(req.user)",
            score=0.86,
            related=[
                # NullProvider 路径应忽略 payload.related_chunks
                _h1("ignored", "should-not-appear.py", "CALL", 0.99),
            ],
        ),
    ],
    provider_type="null",
)

# ---- fixture 06: budget_default_8000 -----------------------------------
_F06_H1 = [
    _h1(f"budget-{i}", f"src/budget/m_{i:02d}.py", "CALL", 0.5 + i * 0.03)
    for i in range(8)
]
_F06 = _Scenario(
    nn="06",
    slug="budget_default_8000",
    query="budget allocation probe",
    repo_ids=["repo-a"],
    rag_items=[
        _src(
            "06-budget",
            "src/budget/source.py",
            "def budget_source(): pass",
            score=0.80,
            related=_F06_H1,
        ),
    ],
    hop1_neighbors=_F06_H1,
    max_tokens=8000,
)

# ---- fixture 07: budget_override_07 -------------------------------------
_F07 = _Scenario(
    nn="07",
    slug="budget_override_07",
    query="budget override probe",
    repo_ids=["repo-a"],
    rag_items=[
        _src(
            "07-override",
            "src/budget/source.py",
            "def budget_source(): pass",
            score=0.80,
            related=_F06_H1,
        ),
    ],
    hop1_neighbors=_F06_H1,
    max_tokens=8000,
    settings_overrides={"GRAPHRAG_BUDGET_RATIO": 0.7},
)

# ---- fixture 08: hop2_dedup (hop2 仅独立邻居) ----------------------------
_F08_H1 = [
    _h1("dedup-a", "src/dedup/a.py", "CALL", 0.85),
]
_F08_H2_INDEP = [
    _h2("dedup-indep", "src/dedup/indep.py", "CALL", 0.55),
]
_F08 = _Scenario(
    nn="08",
    slug="hop2_dedup",
    query="dedup probe",
    repo_ids=["repo-a"],
    rag_items=[
        _src(
            "08-dedup",
            "src/dedup/source.py",
            "def dedup(): pass",
            score=0.83,
            related=_F08_H1,
        ),
    ],
    hop1_neighbors=_F08_H1,
    hop2_neighbors=_F08_H2_INDEP,  # mock 已模拟去重后只剩独立 target
)

# ---- fixture 09: symbol_failure_downgrade ------------------------------
_F09_H1 = [
    _h1("fail-1", "src/fail/handler.py", "CALL", 0.80),
]
_F09 = _Scenario(
    nn="09",
    slug="symbol_failure_downgrade",
    query="symbol failure probe",
    repo_ids=["repo-a"],
    rag_items=[
        _src(
            "09-fail",
            "src/fail/source.py",
            "def fail_source(): pass",
            score=0.79,
            related=_F09_H1,
        ),
    ],
    hop1_neighbors=_F09_H1,
    symbol_raises=True,  # provider.lookup_symbols raise
)

# ---- fixture 10: no_payload_neighbors ----------------------------------
_F10 = _Scenario(
    nn="10",
    slug="no_payload_neighbors",
    query="no payload probe",
    repo_ids=["repo-a"],
    rag_items=[
        _src(
            "10-no-payload",
            "src/np/source.py",
            "def np_source(): pass",
            score=0.81,
            related=None,  # 无 related_chunks 字段
        ),
    ],
    # 无 hop1/hop2
)


GRAPH_CAPABLE_SCENARIOS: tuple[_Scenario, ...] = (
    _F01, _F02, _F03, _F04, _F05, _F06, _F07, _F08, _F09, _F10,
)


# ---------------------------------------------------------------------------
# mock 应用 + 跑场景
# ---------------------------------------------------------------------------


async def _run_scenario(
    scenario: _Scenario,
) -> RagSearchResult | HybridSearchResult:
    """根据 scenario 规格 patch mock + 调 HybridSearchService.search。"""
    rag_snapshot = LayerSnapshot(
        layer="L3",
        status="ok" if scenario.rag_items else "ok",
        result_count=len(scenario.rag_items),
        items=[s.to_item() for s in scenario.rag_items],
    )

    hop1_list = [n.to_neighbor() for n in scenario.hop1_neighbors]
    hop2_list = [n.to_neighbor() for n in scenario.hop2_neighbors]

    if scenario.symbol_raises:
        symbol_side_effect: Any = ValueError("simulated lookup_symbols failure")
        lookup_mock = AsyncMock(side_effect=symbol_side_effect)
    else:
        lookup_mock = AsyncMock(return_value=list(scenario.symbol_results))

    provider: LocalProvider | NullProvider
    if scenario.provider_type == "null":
        provider = NullProvider()
    else:
        provider = LocalProvider()

    patches = [
        patch(
            "services.retrieval.hybrid_search.search_rag",
            new=AsyncMock(return_value=rag_snapshot),
        ),
        patch(
            "services.retrieval.hybrid_search.resolve_neighbor_metadata",
            new=AsyncMock(return_value=hop1_list),
        ),
        patch(
            "services.retrieval.hybrid_search.expand_hop2",
            new=AsyncMock(return_value=hop2_list),
        ),
        patch.object(LocalProvider, "lookup_symbols", new=lookup_mock),
        # Phase 22 EXCL-02：graph_capable 路径经 build_matcher_for_repo 过滤被排除邻居。
        # golden 场景的 file_path 均为良性（不命中内置默认），注入 no-op 匹配器保证
        # 既有 byte-eq fixture 不漂移（repo_ids 为合成串，无法走真实 DB 匹配器）。
        patch(
            "services.retrieval.hybrid_search.build_matcher_for_repo",
            new=AsyncMock(return_value=_NoExclusionMatcher()),
        ),
    ]

    async def _call() -> RagSearchResult | HybridSearchResult:
        return await HybridSearchService(provider).search(
            scenario.query,
            repository_ids=scenario.repo_ids,
            max_tokens=scenario.max_tokens,
            top_k=scenario.top_k,
            enable_graph_enrichment=scenario.enable_graph_enrichment,
        )

    # 嵌套应用 patch + override_settings
    from contextlib import ExitStack

    with ExitStack() as stack:
        for p in patches:
            stack.enter_context(p)
        if scenario.settings_overrides:
            stack.enter_context(override_settings(**scenario.settings_overrides))
        result = await _call()
    return result


def _final_chunks_of(result: RagSearchResult | HybridSearchResult) -> int:
    """final_chunks 计数 = hop1+hop2 邻居数（rag_only 路径恒 0）。"""
    if isinstance(result, HybridSearchResult):
        return len(result.hop1_neighbors) + len(result.hop2_neighbors)
    return 0


# ---------------------------------------------------------------------------
# parametrize 主测试
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "scenario",
    GRAPH_CAPABLE_SCENARIOS,
    ids=lambda s: f"{s.nn}-{s.slug}",
)
async def test_graph_capable_golden_byte_equivalence(scenario: _Scenario) -> None:
    """对每条 graph_capable scenario 校验 final_context 与 fixture 字节级一致。

    断言层级：
      1. `result.final_context.rstrip("\\n")` == fixture body（字节级）
      2. `result.total_tokens` == fixture metadata 的 tokens
      3. `final_chunks(result)` == fixture metadata 的 final_chunks
      4. `source_layer == "hybrid"`（固定锚点）

    GENERATE_GOLDEN=1 环境变量下进入"生成模式"：写 fixture + skip 断言。
    """
    fixture_path = FIXTURE_DIR / f"{scenario.nn}-{scenario.slug}.txt"

    result = await _run_scenario(scenario)
    actual_body = result.final_context.rstrip("\n")
    actual_tokens = result.total_tokens
    actual_chunks = _final_chunks_of(result)

    if _GENERATE_MODE:
        FIXTURE_DIR.mkdir(parents=True, exist_ok=True)
        _write_fixture(
            fixture_path,
            body=actual_body,
            total_tokens=actual_tokens,
            final_chunks=actual_chunks,
        )
        pytest.skip(
            f"GENERATE_GOLDEN=1 → wrote fixture {fixture_path.name} "
            f"(tokens={actual_tokens} final_chunks={actual_chunks})"
        )

    assert fixture_path.exists(), (
        f"missing fixture: {fixture_path}; rerun with GENERATE_GOLDEN=1 "
        f"to regenerate"
    )

    text = fixture_path.read_text(encoding="utf-8")
    expected_body, metadata_line = _split_fixture(text)
    expected_tokens, expected_layer, expected_chunks = _parse_metadata(metadata_line)

    assert actual_body == expected_body, (
        f"final_context drift for {scenario.nn}-{scenario.slug}; "
        f"rerun with GENERATE_GOLDEN=1 to regenerate fixture and review diff"
    )
    assert actual_tokens == expected_tokens, (
        f"total_tokens drift for {scenario.nn}-{scenario.slug}: "
        f"actual={actual_tokens} expected={expected_tokens}"
    )
    assert actual_chunks == expected_chunks, (
        f"final_chunks drift for {scenario.nn}-{scenario.slug}: "
        f"actual={actual_chunks} expected={expected_chunks}"
    )
    assert expected_layer == "hybrid", (
        f"source_layer 必须固定 'hybrid'，got {expected_layer!r}"
    )
