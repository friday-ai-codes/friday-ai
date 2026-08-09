"""LSP 孤儿进程收割验收桩（D-14；归属 127-05）。

Wave 0：节点名可收集；实现由 127-05 去 skip。
"""

from __future__ import annotations

import pytest

_SKIP = pytest.mark.skip(reason="Wave 0 桩：由 127-05 落地")


@_SKIP
def test_reap_orphan_lsp_processes_counts_and_best_effort() -> None:
    """reap_orphan_lsp_processes 计数并 best-effort（不 raise）。

    （Req: LSP-01, 决策: D-14；威胁: T-127-04）
    """
    pytest.fail("Wave 0 桩")


@_SKIP
def test_supervisor_stop_invoked_on_index_path_finally() -> None:
    """索引路径 finally 调 stop + reap（契约/静态）。

    （Req: LSP-01, 决策: D-13/D-14）
    """
    pytest.fail("Wave 0 桩")
