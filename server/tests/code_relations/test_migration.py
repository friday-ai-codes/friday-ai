"""`code_relations` 0001_initial migration sqlmigrate stdout 正则断言（contract）。

针对 sqlmigrate 输出做 grep 锚点测试，规避因 DB engine 差异导致的语法变体：
- UNIQUE (source_chunk_id, target_chunk_id, edge_type) —— 可能是 `CREATE UNIQUE INDEX`
  也可能是 `CONSTRAINT ... UNIQUE (...)` 内联（SQLite 风格）。
- CREATE INDEX (target_chunk_id) —— 反向 fan-in
- CREATE INDEX (repository_id, source_chunk_id) —— fan-out
- ORDER BY weight DESC（top-K，PostgreSQL/SQLite 排序索引语法变体）

实现说明：用 subprocess 调 `uv run python manage.py sqlmigrate` 子进程，规避
pytest-django 内 `call_command("sqlmigrate", ...)` 在 SQLite 上因 FK 启用 +
transaction.atomic 冲突触发 `NotSupportedError` 的限制。
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path


def test_sqlmigrate_outputs_four_ddl() -> None:
    """sqlmigrate stdout 必须同时命中 4 个 DDL 锚点（per contract / contract）。"""
    server_root = Path(__file__).resolve().parents[2]  # → server/
    result = subprocess.run(
        ["uv", "run", "python", "manage.py", "sqlmigrate", "code_relations", "0001"],
        cwd=server_root,
        capture_output=True,
        text=True,
        check=True,
    )
    text = result.stdout

    uniq_inline = re.search(
        r'(?:CONSTRAINT\s+"?uniq_chunkedge_triple"?\s+)?UNIQUE\s*\('
        r'\s*"?source_chunk_id"?\s*,\s*"?target_chunk_id"?\s*,\s*"?edge_type"?\s*\)',
        text,
    )
    uniq_create_index = re.search(
        r'CREATE\s+UNIQUE\s+INDEX[^;]*source_chunk_id[^;]*target_chunk_id[^;]*edge_type',
        text,
        re.IGNORECASE,
    )
    assert uniq_inline or uniq_create_index, (
        f"missing unique (source_chunk_id, target_chunk_id, edge_type): {text}"
    )

    assert re.search(
        r'CREATE\s+INDEX\s+"?idx_chunkedge_target"?[^;]*"?target_chunk_id"?',
        text,
        re.IGNORECASE,
    ), f"missing fan-in target index: {text}"

    assert re.search(
        r'CREATE\s+INDEX\s+"?idx_chunkedge_fanout"?[^;]*'
        r'"?repository_id"?\s*,\s*"?source_chunk_id"?',
        text,
        re.IGNORECASE,
    ), f"missing fan-out index: {text}"

    assert re.search(
        r'CREATE\s+INDEX\s+"?idx_chunkedge_topk"?[^;]*"?weight"?\s+DESC',
        text,
        re.IGNORECASE,
    ), f"missing top-K weight DESC index: {text}"

    assert "chunkedge_weight_range" in text, (
        f"missing chunkedge_weight_range check constraint: {text}"
    )
