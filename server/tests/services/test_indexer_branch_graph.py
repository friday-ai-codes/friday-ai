"""implementation contract indexer 图谱轨分支透传集成测试。

覆盖三条核心契约：

- `_resolve_write_branch`：写入侧分支归一化（None/""/==base_branch/==default_branch
  → ""，feature 名原样），保 base chunk_id 字节不变（Pitfall 4）。
- `_extract_and_write_graph` 的 history_id 透传：形参非 None 时**优先用透传值**，
  跳过「查最近 RUNNING IndexHistory」fallback（Pitfall 3）。
- `_build_points` chunk_id 分支命名空间：feature 分支产出的 chunk_id 与 base 不同，
  base 路径（branch_name=None / is_base_branch）chunk_id 与不传 branch 字节一致
  （Critical 1 根因修复，293 golden 不回归）。
"""

from __future__ import annotations

import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from code_relations.utils import generate_chunk_id
from services.code_chunk import CodeChunk
from services.indexer import IndexerService, _resolve_write_branch

# ---------------------------------------------------------------------------
# test_resolve_write_branch —— 集中式归一化（无 DB，纯函数）
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "base_branch, default_branch, branch_name, expected",
    [
        # base_branch 优先：== base_branch → ""
        ("main", "develop", "main", ""),
        # base_branch 为空回退 default_branch：== default_branch → ""
        ("", "main", "main", ""),
        # None / 空串 → ""
        ("", "main", None, ""),
        ("", "main", "", ""),
        # feature 分支名原样返回
        ("", "main", "feature/x", "feature/x"),
        ("main", "develop", "feature/y", "feature/y"),
        # branch_name 等于 default 但 base_branch 非空且不同时仍归一化（base_branch 优先）
        ("release", "main", "main", "main"),
    ],
)
def test_resolve_write_branch(
    base_branch: str, default_branch: str, branch_name: str | None, expected: str
) -> None:
    """contract：None/""/==base_branch/==default_branch → ""，feature 名原样。"""
    repo = SimpleNamespace(base_branch=base_branch, default_branch=default_branch)
    assert _resolve_write_branch(repo, branch_name) == expected  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# test_feature_chunk_id_namespaced —— _build_points chunk_id 分支分流（无 DB）
# ---------------------------------------------------------------------------


def _make_chunk(file_path: str = "src/a.py", content: str = "print(1)\n") -> CodeChunk:
    return CodeChunk(
        content=content,
        file_path=file_path,
        file_hash="h" * 64,
        language="python",
        start_line=1,
        end_line=1,
        node_type="module",
        context_header="ctx",
    )


def test_feature_chunk_id_namespaced() -> None:
    """contract / Critical 1：feature chunk_id 与 base 分流，base 路径字节不变。"""
    repo_id = str(uuid.uuid4())
    chunk = _make_chunk()
    embeddings: list[list[float] | None] = [[0.1, 0.2, 0.3]]

    # base 路径（branch_name=None，默认 is_base_branch=False）→ 归一化为 ""
    base_points, base_rows = IndexerService._build_points(
        [chunk], embeddings, None, False, repository_id=repo_id, branch_name=None
    )
    # base 路径（显式 is_base_branch=True，传入非空 base 分支名）→ 仍归一化为 ""
    base2_points, base2_rows = IndexerService._build_points(
        [chunk], embeddings, None, False,
        repository_id=repo_id, branch_name="main", is_base_branch=True,
    )
    # feature 路径
    feat_points, feat_rows = IndexerService._build_points(
        [chunk], embeddings, None, False,
        repository_id=repo_id, branch_name="feature/x", is_base_branch=False,
    )

    base_cid = base_rows[0]["chunk_id"]
    base2_cid = base2_rows[0]["chunk_id"]
    feat_cid = feat_rows[0]["chunk_id"]

    # base 路径 chunk_id == 不传 branch 的 generate_chunk_id（字节不变，293 golden 不回归）
    assert base_cid == generate_chunk_id(repo_id, "src/a.py", 0)
    # is_base_branch=True 即便 branch_name 非空也归一化为 base，chunk_id 与 base 一致
    assert base2_cid == base_cid
    # feature chunk_id == 分支命名空间 generate_chunk_id，且与 base 必然不同（PK 不碰撞）
    assert feat_cid == generate_chunk_id(repo_id, "src/a.py", 0, "feature/x")
    assert feat_cid != base_cid

    # registry_row.branch_name 归一化写入：base→""，feature→分支名
    assert base_rows[0]["branch_name"] == ""
    assert base2_rows[0]["branch_name"] == ""
    assert feat_rows[0]["branch_name"] == "feature/x"
    # point id 与 chunk_id 同源
    assert base_points[0]["id"] == str(base_cid)
    assert feat_points[0]["id"] == str(feat_cid)


# ---------------------------------------------------------------------------
# test_history_id_threaded —— _extract_and_write_graph history_id 透传优先于 fallback
# ---------------------------------------------------------------------------


@pytest.mark.django_db(transaction=True)
async def test_history_id_threaded(repository, settings, monkeypatch) -> None:
    """contract / Pitfall 3：history_id 非 None 时用透传值，不走 fallback 查询。"""
    settings.ENABLE_CODEGRAPH = True

    idx = IndexerService(str(repository.id))
    # 预置非 None 图谱服务，使 _init_graph_services 成 no-op、避免 unavailable 早退；
    # file_paths=[] 空循环不会真正调用 write_bundle。
    idx._graph_extractor = object()  # type: ignore[assignment]
    idx._graph_writer = object()  # type: ignore[assignment]
    # 注入 dirty chunk 触发 enqueue 透传分支
    idx._session_dirty_chunk_ids = {uuid.uuid4()}

    captured: dict[str, object] = {}

    async def _fake_enqueue(
        repo_id: str,
        dirty: list[uuid.UUID],
        history: object,
        *,
        branch_name: str = "",
    ) -> None:
        captured["history"] = history
        captured["branch_name"] = branch_name

    monkeypatch.setattr(
        "code_relations.lifecycle.enqueue_edge_build_for_history", _fake_enqueue
    )

    # fallback 查询守门：history_id 透传时不应触发 IndexHistory **fallback 读**
    # （filter(...).order_by(...).values_list(...)）。但 implementation 的
    # per-run delta 回填会合法地调 filter(id=running_history).aupdate(...) 写本次
    # delta —— 该写路径应放行，只拦截 fallback 读路径。
    from repositories.models import IndexHistory

    class _BackfillOnlyQuerySet:
        async def aupdate(self, **kwargs: object) -> int:
            # per-run delta 回填写（keyed by 已知 history_id），放行
            return 1

        def order_by(self, *args: object, **kwargs: object) -> object:
            raise AssertionError(
                "history_id 透传时不应触发 IndexHistory fallback 读查询"
            )

    class _FallbackGuardManager:
        def filter(self, *args: object, **kwargs: object) -> object:
            return _BackfillOnlyQuerySet()

    monkeypatch.setattr(IndexHistory, "objects", _FallbackGuardManager())

    # 后置 backfill hook 屏蔽，保测试快速且隔离 DB/Service
    monkeypatch.setattr(
        "code_relations.symbol_chunk_binding.backfill_symbol_chunk_ids",
        AsyncMock(return_value=0),
    )
    monkeypatch.setattr(
        "codegraph.resolver.wiring.backfill_symbol_resolution",
        lambda *a, **k: {},
    )

    known_history_id = str(uuid.uuid4())
    await idx._extract_and_write_graph(
        repo_path="/tmp/nonexistent",
        file_paths=[],
        repository_id=str(repository.id),
        branch_name="feature/x",
        history_id=known_history_id,
    )

    assert captured["history"] == known_history_id
    assert captured["branch_name"] == "feature/x"
