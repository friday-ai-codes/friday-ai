"""Pitfall 3 防御 grep gate（per initial implementation contract）。

SemanticEdgeBuilder 唯一允许的 query 模式是
    qdrant.query_points(query=v, limit=20, score_threshold=0.85, query_filter=...)
禁止 qdrant.retrieve(ids=..., with_vectors=True) + numpy/sklearn 全量两两 cosine
（O(n²) trap）。
"""

from __future__ import annotations

import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
TARGET_DIR = REPO_ROOT / "server" / "code_relations"

RETRIEVE_WITH_VECTORS_PATTERN = r"\.retrieve\s*\([^)]*with_vectors\s*=\s*True"


def test_no_qdrant_retrieve_with_vectors() -> None:
    """server/code_relations/ 内不得出现 qdrant retrieve(..., with_vectors=True)。"""
    result = subprocess.run(
        [
            "rg",
            "-U",
            "--multiline-dotall",
            "-P",
            RETRIEVE_WITH_VECTORS_PATTERN,
            str(TARGET_DIR),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 1, (
        "Pitfall 3 violation：server/code_relations/ 出现 qdrant.retrieve(..., "
        "with_vectors=True) 调用，违反 SemanticEdgeBuilder 唯一 API 约束（contract）。\n"
        "改用 QdrantService.get_client().query_points(query=v, limit=20, "
        "score_threshold=0.85, query_filter=Filter(must_not=[...])).\n"
        f"ripgrep stdout:\n{result.stdout}"
    )
