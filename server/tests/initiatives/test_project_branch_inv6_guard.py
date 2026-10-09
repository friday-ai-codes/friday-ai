"""INV-6 旁路写表 grep 守护（Phase 85）：``ProjectBranch`` 落库只经
``initiatives.services.ProjectBranchService``。

镜像 ``test_memory_inv6_guard`` 范式：纯本地源码扫描，无 DB / 网络。扫描 ``server/``
源码（排除 tests/ / migrations/ / initiatives/models/ 与 service 自身），断言无旁路
``ProjectBranch.objects.<write>`` / 直接实例化入口；并正向断言 service 确实写入。
"""

from __future__ import annotations

import ast
from pathlib import Path

SERVER_DIR = Path(__file__).resolve().parents[2]

_PRUNE_DIRS = {
    ".venv",
    "node_modules",
    "data",
    "staticfiles",
    "__pycache__",
    ".git",
    "htmlcov",
    ".pytest_cache",
    ".ruff_cache",
    ".mypy_cache",
}

_ALLOWED_WRITER = "initiatives/services/project_branch_service.py"

_MODELS = ("ProjectBranch",)


def _is_bypass_call(node: ast.AST) -> bool:
    if not isinstance(node, ast.Call):
        return False
    target = ast.unparse(node.func)
    return target in _MODELS or target in {
        f"{model}.objects.{method}"
        for model in _MODELS
        for method in ("create", "bulk_create", "get_or_create", "update_or_create")
    }


def _iter_py_files() -> list[Path]:
    files: list[Path] = []
    for path in SERVER_DIR.rglob("*.py"):
        if any(part in _PRUNE_DIRS for part in path.relative_to(SERVER_DIR).parts):
            continue
        files.append(path)
    return files


def _is_scanned(rel: str) -> bool:
    if rel == _ALLOWED_WRITER:
        return False
    if rel.startswith("tests/") or "/tests/" in rel:
        return False
    if "/migrations/" in rel:
        return False
    if rel.startswith("initiatives/models/"):
        return False
    return True


def test_inv6_no_bypass_project_branch_write() -> None:
    """INV-6：除 ProjectBranchService 外，server 源码无旁路 ProjectBranch 写表入口。"""
    violations: list[str] = []
    for path in _iter_py_files():
        rel = path.relative_to(SERVER_DIR).as_posix()
        if not _is_scanned(rel):
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if _is_bypass_call(node):
                violations.append(f"{rel}:{node.lineno}: {ast.unparse(node.func)}")

    assert not violations, (
        "INV-6 违反：发现旁路 ProjectBranch 写表"
        f"（落库只允许经 ProjectBranchService / {_ALLOWED_WRITER}）：\n" + "\n".join(violations)
    )


def test_inv6_writer_module_actually_writes() -> None:
    """守护有效性：唯一 writer 确实含 ProjectBranch 写表，防守护形同虚设。"""
    writer = SERVER_DIR / _ALLOWED_WRITER
    assert writer.exists(), f"{_ALLOWED_WRITER} 不存在"
    text = writer.read_text(encoding="utf-8")
    assert "ProjectBranch.objects.get_or_create" in text


def test_guard_ignores_documentation_but_detects_multiline_writes() -> None:
    documentation = ast.parse('"""ProjectBranch(source=manual)"""')
    assert not any(_is_bypass_call(n) for n in ast.walk(documentation))
    for source in (
        "ProjectBranch(source='manual')",
        "ProjectBranch.objects.create(\n source='manual'\n)",
    ):
        assert any(_is_bypass_call(n) for n in ast.walk(ast.parse(source)))
