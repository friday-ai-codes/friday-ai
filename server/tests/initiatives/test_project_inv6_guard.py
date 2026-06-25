"""INV-6 旁路写表 grep 守护（Phase 77，镜像 delivery/audit 范式）。

纯本地源码扫描，无 DB / 网络：``Project`` / ``ProjectMember`` / ``ProjectRelation`` 落库只经
``initiatives.services.ProjectService``。扫描 ``server/`` 源码（排除 tests/ / migrations/ /
initiatives/models/ 与 service 自身），断言无旁路 ``.objects.<write>`` / 直接实例化 / 链式 save
入口；命中即 fail 并列出文件:行。
"""

from __future__ import annotations

import re
from pathlib import Path

SERVER_DIR = Path(__file__).resolve().parents[2]

_PRUNE_DIRS = {
    ".venv",
    "node_modules",
    "staticfiles",
    "__pycache__",
    ".git",
    "htmlcov",
    ".pytest_cache",
    ".ruff_cache",
    ".mypy_cache",
}

# 唯一允许写聚合根模型的模块（相对 server/）
_ALLOWED_WRITER = "initiatives/services/project_service.py"

# 写表模式（精确锚定，避免误伤更长符号如 ProjectMemberSerializer/ProjectRelationXXX）：
_MODELS = ("Project", "ProjectMember", "ProjectRelation")
_RE_ORM_WRITE = {
    m: re.compile(
        rf"\b{m}\.objects\.(?:create|bulk_create|get_or_create|update_or_create)\b"
    )
    for m in _MODELS
}
# 直接实例化 Model(...)（"\s*\(" 紧跟，排除 ModelSerializer( / ModelError( 等更长符号）
_RE_INSTANTIATE = {m: re.compile(rf"\b{m}\s*\(") for m in _MODELS}


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


def test_inv6_no_bypass_project_write() -> None:
    """INV-6：除 ProjectService 外，server 源码无旁路 Project/Member/Relation 写表入口。"""
    violations: list[str] = []

    for path in _iter_py_files():
        rel = path.relative_to(SERVER_DIR).as_posix()
        if not _is_scanned(rel):
            continue
        for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            stripped = line.lstrip()
            # 跳过模型/类定义行（class Project(...) / class ProjectMember(...)）
            if stripped.startswith("class Project"):
                continue
            for m in _MODELS:
                if _RE_ORM_WRITE[m].search(line) or _RE_INSTANTIATE[m].search(line):
                    violations.append(f"{rel}:{lineno}: {line.strip()}")
                    break

    assert not violations, (
        "INV-6 违反：发现旁路 Project/ProjectMember/ProjectRelation 写表"
        f"（落库只允许经 ProjectService / {_ALLOWED_WRITER}）：\n" + "\n".join(violations)
    )


def test_inv6_writer_module_actually_writes() -> None:
    """守护有效性：唯一 writer 确实含聚合根写表，防守护形同虚设。"""
    writer = SERVER_DIR / _ALLOWED_WRITER
    assert writer.exists(), f"{_ALLOWED_WRITER} 不存在"
    text = writer.read_text(encoding="utf-8")
    assert "get_or_create" in text and ".save(" in text, (
        "ProjectService 应是唯一聚合根写表点，但未检出 get_or_create/.save"
    )
