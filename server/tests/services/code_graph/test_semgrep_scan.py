"""Semgrep CLI / fail-open 验收（TAINT-01；D-01..D-04；归属 127-03）。"""

from __future__ import annotations

import ast
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from django.test import override_settings

_SCAN_MOD = Path(__file__).resolve().parents[3] / "services" / "code_graph" / "semgrep_scan.py"


def test_semgrep_argv_uses_baseline_commit_merge_base() -> None:
    """argv 含 scan、--baseline-commit=<merge-base>；禁止 ci 子命令；bin 来自 SEMGREP_BIN。

    （Req: TAINT-01, 决策: D-01..D-03）
    """
    from services.code_graph.semgrep_scan import build_semgrep_argv

    argv = build_semgrep_argv(
        bin_path="/opt/semgrep/bin/semgrep",
        baseline_commit="abc123def456abc123def456abc123def456abcd",
        configs=["p/python", "p/django"],
        timeout=5,
    )
    assert argv[0] == "/opt/semgrep/bin/semgrep"
    assert "scan" in argv
    assert "ci" not in argv
    assert "--baseline-commit" in argv
    idx = argv.index("--baseline-commit")
    assert argv[idx + 1] == "abc123def456abc123def456abc123def456abcd"
    assert "--json" in argv
    assert "--quiet" in argv


def test_semgrep_never_imports_semgrep_module() -> None:
    """静态读 semgrep_scan.py 无 import semgrep（CLI only；不进 uv.lock）。

    （Req: TAINT-01, 决策: D-01）
    """
    assert _SCAN_MOD.is_file(), f"missing {_SCAN_MOD}"
    source = _SCAN_MOD.read_text(encoding="utf-8")
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                assert alias.name != "semgrep" and not alias.name.startswith("semgrep.")
        elif isinstance(node, ast.ImportFrom):
            mod = node.module or ""
            assert mod != "semgrep" and not mod.startswith("semgrep.")
    # 仅检查语句级导入；文档字面量不算
    assert "import semgrep\n" not in source
    assert "from semgrep " not in source
    assert "from semgrep." not in source


@pytest.mark.asyncio
@override_settings(SEMGREP_BIN="/opt/semgrep/bin/semgrep", SEMGREP_TASK_TIMEOUT=1)
async def test_semgrep_fail_open_on_timeout_and_unavailable() -> None:
    """timeout/mirror/CLI → 稳定 error_code；不 raise 到建 MR。

    （Req: TAINT-01, 决策: D-04；威胁: T-127-02）
    """
    from services.code_graph.semgrep_scan import run_semgrep_scan
    from services.repo_mirror import MirrorError

    source_sha = "a" * 40
    target_sha = "b" * 40

    with (
        patch(
            "services.code_graph.semgrep_scan.ensure_mirror_sha",
            new=AsyncMock(
                return_value=MagicMock(repo_dir=Path("/tmp/mirror"), commit_sha=source_sha)
            ),
        ),
        patch(
            "services.code_graph.semgrep_scan.ensure_worktree_for_scan",
            new=AsyncMock(side_effect=MirrorError("mirror_unavailable", "boom")),
        ),
    ):
        result = await run_semgrep_scan(
            repository_id="repo-1",
            source_sha=source_sha,
            target_sha=target_sha,
            mr_key="mr-1",
        )
    assert result.error_code in {"unavailable", "mirror_failed", "mirror_unavailable"}
    assert result.findings_count == 0

    with (
        patch(
            "services.code_graph.semgrep_scan.ensure_worktree_for_scan",
            new=AsyncMock(return_value=Path("/tmp/wt")),
        ),
        patch(
            "services.code_graph.semgrep_scan.ensure_mirror_sha",
            new=AsyncMock(
                return_value=MagicMock(repo_dir=Path("/tmp/mirror"), commit_sha=source_sha)
            ),
        ),
        patch(
            "services.code_graph.semgrep_scan._resolve_merge_base",
            new=AsyncMock(return_value="c" * 40),
        ),
        patch(
            "services.code_graph.semgrep_scan._resolve_app_token",
            return_value="",
        ),
        patch(
            "services.code_graph.semgrep_scan._run_semgrep_cli",
            new=AsyncMock(side_effect=TimeoutError("wall clock")),
        ),
    ):
        timed_out = await run_semgrep_scan(
            repository_id="repo-1",
            source_sha=source_sha,
            target_sha=target_sha,
            mr_key="mr-1",
        )
    assert timed_out.error_code == "timeout"
    assert timed_out.findings_count == 0


@pytest.mark.asyncio
async def test_semgrep_cli_timeout_reaps_child_process(monkeypatch) -> None:
    """墙钟超时必须回收子进程：⛔ 不留带 SEMGREP_APP_TOKEN 的孤儿。

    （Req: TAINT-01, 决策: D-04；威胁: T-127-01/T-127-02）
    """
    import asyncio
    import os
    import shutil

    from services.code_graph.semgrep_scan import _run_semgrep_cli

    sleep_bin = shutil.which("sleep")
    if not sleep_bin:
        pytest.skip("sleep 不可用")

    spawned: list = []
    real_exec = asyncio.create_subprocess_exec

    async def _spy(*args, **kwargs):
        proc = await real_exec(*args, **kwargs)
        spawned.append(proc)
        return proc

    monkeypatch.setattr(asyncio, "create_subprocess_exec", _spy)

    with pytest.raises(TimeoutError):
        await _run_semgrep_cli(
            [sleep_bin, "30"],
            cwd=Path.cwd(),
            env={"PYTHONUNBUFFERED": "1", "SEMGREP_APP_TOKEN": "sgp_secret"},
            wall_timeout=0.3,
        )

    assert spawned, "子进程未被创建"
    proc = spawned[0]
    # 已回收退出码（信号终止为负值），且 OS 层进程确实不存在
    assert proc.returncode is not None
    with pytest.raises(ProcessLookupError):
        os.kill(proc.pid, 0)


def test_semgrep_packs_from_semgrep_configs_setting() -> None:
    """SEMGREP_CONFIGS CSV → 多个 --config。

    （Req: TAINT-01, 决策: D-02）
    """
    from services.code_graph.semgrep_scan import build_semgrep_argv, parse_semgrep_configs

    packs = parse_semgrep_configs("p/python, p/django ,p/golang")
    assert packs == ["p/python", "p/django", "p/golang"]

    argv = build_semgrep_argv(
        bin_path="/opt/semgrep/bin/semgrep",
        baseline_commit="d" * 40,
        configs=packs,
        timeout=5,
    )
    config_values = [argv[i + 1] for i, a in enumerate(argv) if a == "--config"]
    assert config_values == ["p/python", "p/django", "p/golang"]
