"""INV-6 旁路写表 grep 守护（Phase 80）：``ProjectMemory`` / ``ProjectMemoryRevision`` /
``ProjectMemoryDraft`` 落库只经 ``initiatives.services.MemoryService``。

镜像 ``test_artifact_inv6_guard`` 范式：纯本地源码扫描，无 DB / 网络。
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

_ALLOWED_WRITER = "initiatives/services/memory_service.py"

_MODELS = ("ProjectMemory", "ProjectMemoryRevision", "ProjectMemoryDraft")
_RE_ORM_WRITE = {
    m: re.compile(
        rf"\b{m}\.objects\.(?:create|bulk_create|get_or_create|update_or_create)\b"
    )
    for m in _MODELS
}
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


def test_inv6_no_bypass_memory_write() -> None:
    """INV-6：除 MemoryService 外，server 源码无旁路 ProjectMemory* 写表入口。"""
    violations: list[str] = []
    for path in _iter_py_files():
        rel = path.relative_to(SERVER_DIR).as_posix()
        if not _is_scanned(rel):
            continue
        for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            if line.lstrip().startswith("class ProjectMemory"):
                continue
            for m in _MODELS:
                if _RE_ORM_WRITE[m].search(line) or _RE_INSTANTIATE[m].search(line):
                    violations.append(f"{rel}:{lineno}: {line.strip()}")
                    break

    assert not violations, (
        "INV-6 违反：发现旁路 ProjectMemory* 写表"
        f"（落库只允许经 MemoryService / {_ALLOWED_WRITER}）：\n" + "\n".join(violations)
    )


def test_inv6_writer_module_actually_writes() -> None:
    """守护有效性：唯一 writer 确实含记忆写表，防守护形同虚设。"""
    writer = SERVER_DIR / _ALLOWED_WRITER
    assert writer.exists()
    text = writer.read_text(encoding="utf-8")
    assert "ProjectMemory.objects.create" in text
    assert "ProjectMemoryRevision.objects.create" in text
    assert "ProjectMemoryDraft.objects.create" in text
