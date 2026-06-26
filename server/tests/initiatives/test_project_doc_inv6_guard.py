"""INV-6 旁路写表 grep 守护（Phase 82）：``ProjectDoc`` / ``ProjectDocBlockMap`` /
``ProjectStateApi`` 落库只经 ``initiatives.services.ProjectDocService``。

镜像 ``test_artifact_inv6_guard`` 多模型范式：纯本地源码扫描，无 DB / 网络。扫描 ``server/``
源码（排除 tests/ / migrations/ / initiatives/models/ 与 service 自身），断言无旁路写表入口；
命中即 fail 并列出文件:行。

前缀重叠处理：``ProjectDoc`` 与 ``ProjectDocBlockMap`` 前缀重叠——锚定正则不会误伤
``ProjectDocBlockMap``（其后随 "BlockMap" 而非括号/点号），但仍保留 artifact guard 同款
跳过逻辑作防御。
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

_ALLOWED_WRITER = "initiatives/services/project_doc_service.py"

_MODELS = ("ProjectDoc", "ProjectDocBlockMap", "ProjectStateApi")
_RE_ORM_WRITE = {
    m: re.compile(
        rf"\b{m}\.objects\.(?:create|bulk_create|get_or_create|update_or_create)\b"
    )
    for m in _MODELS
}
# 直接实例化 Model(...)（紧跟 "(" 排除 ProjectDocBlockMap( 误伤 ProjectDoc 等更长符号）
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


def test_inv6_no_bypass_project_doc_write() -> None:
    """INV-6：除 ProjectDocService 外，server 源码无旁路三模型写表入口。"""
    violations: list[str] = []
    for path in _iter_py_files():
        rel = path.relative_to(SERVER_DIR).as_posix()
        if not _is_scanned(rel):
            continue
        for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            stripped = line.lstrip()
            if stripped.startswith("class ProjectDoc") or stripped.startswith(
                "class ProjectStateApi"
            ):
                continue
            for m in _MODELS:
                # ProjectDocBlockMap 命中时跳过 ProjectDoc 的 instantiate 误报
                if m == "ProjectDoc" and _RE_INSTANTIATE["ProjectDocBlockMap"].search(line):
                    continue
                if _RE_ORM_WRITE[m].search(line) or _RE_INSTANTIATE[m].search(line):
                    violations.append(f"{rel}:{lineno}: {line.strip()}")
                    break

    assert not violations, (
        "INV-6 违反：发现旁路 ProjectDoc/ProjectDocBlockMap/ProjectStateApi 写表"
        f"（落库只允许经 ProjectDocService / {_ALLOWED_WRITER}）：\n" + "\n".join(violations)
    )


def test_inv6_writer_module_actually_writes() -> None:
    """守护有效性：唯一 writer 确实含三模型写表，防守护形同虚设。"""
    writer = SERVER_DIR / _ALLOWED_WRITER
    assert writer.exists(), f"{_ALLOWED_WRITER} 不存在"
    text = writer.read_text(encoding="utf-8")
    for m in _MODELS:
        assert f"{m}.objects" in text, (
            f"ProjectDocService 应是唯一写表点，但未检出 {m}.objects 写入"
        )
