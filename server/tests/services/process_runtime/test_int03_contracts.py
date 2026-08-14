"""Phase 132 INT-03 — 契约不回归包入口 + 接线级角色坍塌→反思修复。

契约包一键命令（在 server/ 下）::

    uv run pytest \\
      tests/services/process_runtime/test_funnel_team_gate.py \\
      tests/services/process_runtime/test_funnel_shortlist.py \\
      tests/services/process_runtime/test_funnel_placement.py \\
      tests/services/process_runtime/test_funnel_gates.py \\
      tests/services/process_runtime/test_funnel_gates_wiring.py \\
      tests/services/process_runtime/test_reflection.py \\
      tests/services/process_runtime/test_gaosan_eval.py \\
      tests/services/process_runtime/test_gaosan_funnel_regression.py \\
      tests/services/process_runtime/test_int03_contracts.py \\
      tests/mcp_tools/test_mcp_read_flow.py \\
      -q --tb=line --reuse-db

D-11/D-12/D-13：不回归 128–131；接线级 collapse 修复；不改 repo_router_v2。
"""

from __future__ import annotations

from pathlib import Path

import pytest

# 相对 server/ 的契约路径（D-11）
INT03_CONTRACT_PATHS: list[str] = [
    "tests/services/process_runtime/test_funnel_team_gate.py",
    "tests/services/process_runtime/test_funnel_shortlist.py",
    "tests/services/process_runtime/test_funnel_placement.py",
    "tests/services/process_runtime/test_funnel_gates.py",
    "tests/services/process_runtime/test_funnel_gates_wiring.py",
    "tests/services/process_runtime/test_reflection.py",
    "tests/services/process_runtime/test_gaosan_eval.py",
    "tests/services/process_runtime/test_gaosan_funnel_regression.py",
    "tests/services/process_runtime/test_int03_contracts.py",
    "tests/mcp_tools/test_mcp_read_flow.py",
]


def test_int03_contract_paths_exist_and_nonempty():
    """契约包文件列表非空且路径存在。"""
    assert INT03_CONTRACT_PATHS, "contract path list must be non-empty"
    server_root = Path(__file__).resolve().parents[3]
    missing = [
        p for p in INT03_CONTRACT_PATHS if not (server_root / p).is_file()
    ]
    assert not missing, f"missing contract files: {missing}"


def test_int03_imports_smoke_key_modules():
    """关键漏斗/反思模块可导入（聚合守卫）。"""
    from services.process_runtime import (  # noqa: F401
        funnel_gates,
        place_units,
        reflection,
        role_map,
    )
    from services.process_runtime.gaosan_eval import score_placement_bar  # noqa: F401

    assert callable(score_placement_bar)
