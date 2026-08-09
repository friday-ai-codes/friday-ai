"""LSP 孤儿进程收割验收（D-14；归属 127-05）。

（Req: LSP-01, 决策: D-13/D-14；威胁: T-127-04）
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import psutil
import pytest


def test_reap_orphan_lsp_processes_counts_and_best_effort(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """reap_orphan_lsp_processes 计数并 best-effort（不 raise）。

    （Req: LSP-01, 决策: D-14；威胁: T-127-04）
    """
    from codegraph.lsp import orphan_reap

    live = SimpleNamespace(
        pid=100,
        info={
            "pid": 100,
            "name": "gopls",
            "cmdline": ["gopls"],
            "ppid": 1,
        },
        terminate=MagicMock(),
        kill=MagicMock(),
        wait=MagicMock(),
    )
    orphan = SimpleNamespace(
        pid=200,
        info={
            "pid": 200,
            "name": "gopls",
            "cmdline": ["gopls", "-mode=stdio"],
            "ppid": 99999,
        },
        terminate=MagicMock(),
        kill=MagicMock(),
        wait=MagicMock(side_effect=psutil.TimeoutExpired(seconds=1)),
    )
    noisy = SimpleNamespace(
        pid=300,
        info={
            "pid": 300,
            "name": "python",
            "cmdline": ["python", "manage.py"],
            "ppid": 1,
        },
        terminate=MagicMock(),
        kill=MagicMock(),
        wait=MagicMock(),
    )
    raising = SimpleNamespace(
        pid=400,
        info=MagicMock(side_effect=RuntimeError("boom")),
        terminate=MagicMock(),
        kill=MagicMock(),
        wait=MagicMock(),
    )

    monkeypatch.setattr(
        orphan_reap.psutil,
        "process_iter",
        lambda attrs=None: [live, orphan, noisy, raising],
    )
    monkeypatch.setattr(
        orphan_reap.psutil,
        "pid_exists",
        lambda pid: pid != 99999,
    )

    count = orphan_reap.reap_orphan_lsp_processes(live_pids={100})
    assert count == 1
    orphan.terminate.assert_called_once()
    orphan.kill.assert_called_once()
    live.terminate.assert_not_called()
    noisy.terminate.assert_not_called()

    # Best-effort: process_iter itself exploding must not raise.
    monkeypatch.setattr(
        orphan_reap.psutil,
        "process_iter",
        MagicMock(side_effect=RuntimeError("iter boom")),
    )
    assert orphan_reap.reap_orphan_lsp_processes() == 0


def test_supervisor_stop_invoked_on_index_path_finally() -> None:
    """索引路径 finally 调 stop + reap（契约/静态）。

    （Req: LSP-01, 决策: D-13/D-14）
    """
    pool_src = Path(__file__).resolve().parents[1] / "volar_pool.py"
    init_src = Path(__file__).resolve().parents[1] / "__init__.py"
    pool_text = pool_src.read_text(encoding="utf-8")
    init_text = init_src.read_text(encoding="utf-8")
    assert "reap_orphan" in pool_text or "orphan_reap" in pool_text
    assert "reap_orphan" in init_text or "orphan_reap" in init_text
    assert ".stop" in pool_text or "sup.stop" in pool_text
    assert "supervisor.stop" in init_text or ".stop" in init_text
