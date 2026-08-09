"""Phase 125 冻结面守卫（MOD-04 / D-13）。

社区/摘要/signal 等本相位新增内核不得 import ``repo_router_v2``；
本相位提交不得改写 ``mcp/`` submodule（允许 ``server/mcp_tools/views.py``）。
"""

from __future__ import annotations

import ast
import subprocess
from pathlib import Path

import pytest

_SERVER_ROOT = Path(__file__).resolve().parents[3]
_REPO_ROOT = _SERVER_ROOT.parent

# 本相位新增内核 —— 严禁 import 冻结 router（既有 adapter 调用方除外）
_NO_ROUTER_IMPORT = (
    "services/code_graph/community.py",
    "services/code_graph/module_summary.py",
    "services/module_summary_signal.py",
    "services/process_runtime/artifact_injection.py",
    "services/community_enqueue.py",
)

# adapter / 接线面：允许既有「只调不改」import，但仍禁止写 mcp submodule 包
_PHASE_ADAPTERS = (
    "services/process_runtime/blueprint_route.py",
    "services/process_runtime/blueprint_research_adapter.py",
    "agents/tools/repository_relevance.py",
    "mcp_tools/views.py",
)


def _forbidden_router_imports(path: Path) -> list[str]:
    source = path.read_text(encoding="utf-8")
    tree = ast.parse(source, filename=str(path))
    hits: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module and "repo_router_v2" in node.module:
            hits.append(f"from {node.module}")
        elif isinstance(node, ast.Import):
            for alias in node.names:
                if "repo_router_v2" in alias.name:
                    hits.append(f"import {alias.name}")
    return hits


def _forbidden_mcp_package_imports(path: Path) -> list[str]:
    """禁止 ``import mcp`` / ``from mcp...``（submodule）；``mcp_tools`` 合法。"""
    source = path.read_text(encoding="utf-8")
    tree = ast.parse(source, filename=str(path))
    hits: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            if node.module == "mcp" or node.module.startswith("mcp."):
                hits.append(f"from {node.module}")
        elif isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name == "mcp" or alias.name.startswith("mcp."):
                    hits.append(f"import {alias.name}")
    return hits


def test_phase_125_does_not_touch_repo_router_v2() -> None:
    """静态：社区/摘要/signal 模块不 import ``repo_router_v2``；可选 git 守卫。

    （Req: MOD-04, 决策: D-13）
    """
    violations: list[str] = []
    for rel in _NO_ROUTER_IMPORT:
        path = _SERVER_ROOT / rel
        if not path.is_file():
            continue
        for hit in _forbidden_router_imports(path):
            violations.append(f"{rel}: {hit}")
    assert violations == [], f"frozen surface import violations: {violations}"

    # 可选：125-04 相关 commit 的文件列表不得含冻结路径（无 git / 无匹配时不 fail）
    try:
        result = subprocess.run(
            [
                "git",
                "log",
                "--grep=125-04",
                "--name-only",
                "--pretty=format:",
                "-40",
            ],
            cwd=_REPO_ROOT,
            capture_output=True,
            text=True,
            check=False,
        )
    except FileNotFoundError:
        pytest.skip("git unavailable")
    if result.returncode != 0:
        return
    phase_files = {n.strip() for n in (result.stdout or "").splitlines() if n.strip()}
    bad = [
        n
        for n in phase_files
        if n == "server/codegraph/services/repo_router_v2.py" or n.startswith("mcp/")
    ]
    assert bad == [], f"125-04 commits touched frozen paths: {bad}"


def test_phase_125_does_not_modify_mcp_submodule() -> None:
    """生产代码路径不引用 ``mcp/`` 包内改写（本相位只允许改 ``server/mcp_tools/views.py``）。

    （Req: MOD-04, 决策: D-13）
    """
    violations: list[str] = []
    for rel in (*_NO_ROUTER_IMPORT, *_PHASE_ADAPTERS):
        path = _SERVER_ROOT / rel
        if not path.is_file():
            continue
        for hit in _forbidden_mcp_package_imports(path):
            violations.append(f"{rel}: {hit}")
    assert violations == [], f"mcp submodule import violations: {violations}"

    try:
        result = subprocess.run(
            [
                "git",
                "log",
                "--grep=125-04",
                "--name-only",
                "--pretty=format:",
                "-40",
            ],
            cwd=_REPO_ROOT,
            capture_output=True,
            text=True,
            check=False,
        )
    except FileNotFoundError:
        pytest.skip("git unavailable")
    if result.returncode != 0:
        return
    phase_files = {n.strip() for n in (result.stdout or "").splitlines() if n.strip()}
    bad = [n for n in phase_files if n == "mcp" or n.startswith("mcp/")]
    assert bad == [], f"125-04 commits touched mcp/ submodule: {bad}"
