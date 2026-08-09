"""rename_preview 只读双源验收（RENAME-01 / D-09/D-10/D-11；T-126-01/02/05）。

126-04：去 skip，钉死 applied=false / 二值 confidence / 同 file:line 取 graph /
grep_mirror 路径 / 消歧失败 ok=False / coverage_limitations。
"""

from __future__ import annotations

import ast
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import networkx as nx
import pytest

from services.code_graph.symbol_resolve import SymbolCandidate, SymbolResolution

_SERVER_ROOT = Path(__file__).resolve().parents[3]
_KERNEL = _SERVER_ROOT / "services" / "code_graph" / "rename_preview.py"
_ORCH = _SERVER_ROOT / "services" / "code_graph_tools.py"


def _tiny_graph() -> nx.MultiDiGraph:
    g = nx.MultiDiGraph()
    g.add_node(
        "seed",
        name="old_fn",
        symbol_type="function",
        file_path="pkg/a.py",
        start_line=10,
    )
    g.add_node(
        "caller",
        name="caller_fn",
        symbol_type="function",
        file_path="pkg/b.py",
        start_line=20,
    )
    g.add_edge("caller", "seed", confidence="resolved", match_confidence=1.0)
    return g


def test_applied_always_false() -> None:
    """applied 恒为 false；本相位无 apply/rewrite API。

    （Req: RENAME-01, 决策: D-09, 威胁: T-126-05）
    """
    from services.code_graph.rename_preview import (
        collect_graph_edit_sites,
        merge_dual_source_edits,
    )

    sites = collect_graph_edit_sites(_tiny_graph(), "seed")
    merged = merge_dual_source_edits(
        graph_sites=sites,
        text_matches=[],
        old_name="old_fn",
        new_name="new_fn",
    )
    assert merged["applied"] is False
    for path in (_KERNEL, _ORCH):
        assert path.is_file(), f"missing {path}"
        src = path.read_text(encoding="utf-8")
        assert "def apply_rename" not in src
        assert "def rewrite_rename" not in src
        assert "run_rename_apply" not in src


def test_dual_source_confidence_graph_or_text_search() -> None:
    """置信标签二值：graph | text_search。

    （Req: RENAME-01, 决策: D-10）
    """
    from services.code_graph.rename_preview import (
        collect_graph_edit_sites,
        merge_dual_source_edits,
    )

    sites = collect_graph_edit_sites(_tiny_graph(), "seed")
    text = [
        {
            "file_path": "pkg/c.py",
            "line": 5,
            "kind": "match",
            "content": "old_fn()",
        }
    ]
    merged = merge_dual_source_edits(
        graph_sites=sites,
        text_matches=text,
        old_name="old_fn",
        new_name="new_fn",
    )
    confidences = {e["confidence"] for f in merged["files"] for e in f["edits"]}
    assert confidences <= {"graph", "text_search"}
    assert "graph" in confidences
    assert "text_search" in confidences
    assert merged["summary"]["graph_edits"] >= 1
    assert merged["summary"]["text_search_edits"] >= 1


def test_same_file_line_prefers_graph() -> None:
    """同 file:line 双源命中时保留一条并以 graph 为准。

    （Req: RENAME-01, 决策: D-10）
    """
    from services.code_graph.rename_preview import merge_dual_source_edits

    sites = [
        {
            "file_path": "pkg/a.py",
            "line": 10,
            "symbol_id": "seed",
            "name": "old_fn",
            "kind": "definition",
        }
    ]
    text = [
        {
            "file_path": "pkg/a.py",
            "line": 10,
            "kind": "match",
            "content": "def old_fn():",
        }
    ]
    merged = merge_dual_source_edits(
        graph_sites=sites,
        text_matches=text,
        old_name="old_fn",
        new_name="new_fn",
    )
    edits = [e for f in merged["files"] if f["file_path"] == "pkg/a.py" for e in f["edits"]]
    assert len(edits) == 1
    assert edits[0]["confidence"] == "graph"
    assert "graph" in edits[0]["sources"]
    assert "text_search" in edits[0]["sources"]
    assert merged["summary"]["total_edits"] == 1
    assert merged["summary"]["graph_edits"] == 1
    assert merged["summary"]["text_search_edits"] == 0


def test_grep_half_uses_grep_mirror_not_bare() -> None:
    """源文件静态禁止另起 walk/re 裸扫；须走 grep_mirror。

    （Req: RENAME-01, 决策: D-11, 威胁: T-126-01）
    """
    assert _KERNEL.is_file(), "rename_preview.py must exist"
    kernel_src = _KERNEL.read_text(encoding="utf-8")
    orch_src = _ORCH.read_text(encoding="utf-8")
    assert "grep_mirror" in (kernel_src + "\n" + orch_src)

    for forbidden in ("os.walk", "os.scandir", ".rglob("):
        assert forbidden not in kernel_src, f"kernel must not use {forbidden}"

    tree = ast.parse(kernel_src, filename=str(_KERNEL))
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module == "re":
            pytest.fail("rename_preview kernel must not import re for bare scan")
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name == "re":
                    pytest.fail("rename_preview kernel must not import re for bare scan")


@pytest.mark.asyncio
async def test_disambiguation_or_unindexed_ok_false_not_fake_empty(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """消歧/未索引失败 → ok=False，不静默空清单假装零引用。

    （Req: RENAME-01, 决策: D-11, 威胁: T-126-02）
    """
    from services.code_graph_tools import run_rename_preview

    repo = MagicMock()
    repo.last_indexed_commit_sha = "a" * 40
    repo.default_branch = "main"

    monkeypatch.setattr(
        "services.code_graph_tools.resolve_symbol_candidates",
        AsyncMock(
            return_value=SymbolResolution(
                resolved=None,
                candidates=(
                    SymbolCandidate(
                        symbol_id="u1",
                        name="dup",
                        symbol_type="function",
                        file_path="a.py",
                        start_line=1,
                        signature="def dup()",
                    ),
                    SymbolCandidate(
                        symbol_id="u2",
                        name="dup",
                        symbol_type="function",
                        file_path="b.py",
                        start_line=1,
                        signature="def dup()",
                    ),
                ),
                total_candidates=2,
                truncated=False,
                query="dup",
            )
        ),
    )
    monkeypatch.setattr(
        "services.code_graph_tools._code_graph_access",
        lambda: MagicMock(ensure_repository_readable=AsyncMock(return_value=None)),
    )

    result = await run_rename_preview(
        repository_id="00000000-0000-0000-0000-000000000001",
        repo=repo,
        graph_branch=None,
        user=MagicMock(id=1),
        symbol="dup",
        new_name="renamed",
    )
    assert result["ok"] is False
    assert result.get("error_code") == "ambiguous_symbol"
    assert result.get("applied") is False
    assert not (result.get("ok") is True and result.get("files") == [])


def test_coverage_limitations_declared() -> None:
    """输出声明动态引用覆盖限制。

    （Req: RENAME-01, 决策: D-11）
    """
    from services.code_graph.rename_preview import (
        COVERAGE_LIMITATIONS,
        merge_dual_source_edits,
    )

    assert COVERAGE_LIMITATIONS
    merged = merge_dual_source_edits(
        graph_sites=[],
        text_matches=[],
        old_name="x",
        new_name="y",
    )
    assert merged["coverage_limitations"]
    assert merged["coverage_limitations"] == COVERAGE_LIMITATIONS
