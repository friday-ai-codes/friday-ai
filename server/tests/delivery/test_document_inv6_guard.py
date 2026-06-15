r"""Document / DocumentVersion 旁路写表 INV-6 grep 守护（Phase 30-02 Task 2）。

纯本地源码扫描，无 DB / 网络（沿用 test_inv6_guard.py 精确锚定范式，独立文件避免与
Phase 28 文件所有权冲突）：

- **INV-6**：Document / DocumentVersion 落库只经 ``DocumentService.upsert_from_feishu``。
  扫描 ``server/`` 源码（排除 tests/ / migrations/ / delivery/models/ 与 writer 自身），
  断言无旁路 ``Document.objects.create``/``Document(...)``/.save() 与同款
  ``DocumentVersion`` 写表入口；命中即 fail 并列出文件:行。
- **writer 有效性**：断言 document_service.py 确实含 Document/DocumentVersion 写表
  （否则守护形同虚设）。

精确锚定避免误伤更长符号与读路径：``\bDocument\s*\(`` 的 ``\s*\(`` 紧跟天然排除
``DocumentVersion(`` / ``DocumentType(`` / ``DocumentService(`` / ``DocumentSerializer(``；
``Document\.objects\.<write>`` 紧跟 ``.objects`` 锚定 Document 类本体（非 DocumentVersion），
且不命中 ``Document.objects.filter/get`` 读路径。
"""

from __future__ import annotations

import re
from pathlib import Path

# server/ 根目录（tests/delivery/test_document_inv6_guard.py → parents[2]）
SERVER_DIR = Path(__file__).resolve().parents[2]

# 遍历时剪掉的目录（venv / 缓存 / 静态产物 / vcs）
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

# 唯一允许写 Document / DocumentVersion 的模块（相对 server/）
_ALLOWED_DOCUMENT_WRITER = "delivery/services/document_service.py"

# Document 旁路写表模式（精确锚定，避免误伤 DocumentVersion/DocumentType/DocumentService 等）：
# A：Document.objects.<write>（紧跟 ".objects" 锚定 Document 类本体，非 DocumentVersion；
#    .objects.filter/get 读路径不命中）
_RE_DOC_ORM_WRITE = re.compile(
    r"\bDocument\.objects\.(?:create|bulk_create|get_or_create|update_or_create)\b"
)
# B：直接实例化 Document(...)（"\s*\(" 紧跟，天然排除 DocumentVersion(/DocumentType(/
#    DocumentService(/DocumentSerializer(/DocumentSourceKind( 等更长符号）
_RE_DOC_INSTANTIATE = re.compile(r"\bDocument\s*\(")
# C：链式实例化 + save（Document(...).save(...)）
_RE_DOC_INSTANCE_SAVE = re.compile(r"\bDocument\([^)]*\)\.save\(")

# DocumentVersion 旁路写表模式（同款精确锚定）：
_RE_DOCVER_ORM_WRITE = re.compile(
    r"\bDocumentVersion\.objects\.(?:create|bulk_create|get_or_create|update_or_create)\b"
)
_RE_DOCVER_INSTANTIATE = re.compile(r"\bDocumentVersion\s*\(")
_RE_DOCVER_INSTANCE_SAVE = re.compile(r"\bDocumentVersion\([^)]*\)\.save\(")


def _iter_py_files() -> list[Path]:
    """遍历 server/ 下 .py 文件（剪掉 venv/缓存/静态目录）。"""
    files: list[Path] = []
    for path in SERVER_DIR.rglob("*.py"):
        if any(part in _PRUNE_DIRS for part in path.relative_to(SERVER_DIR).parts):
            continue
        files.append(path)
    return files


def _is_scanned_for_document_inv6(rel: str) -> bool:
    """Document INV-6 扫描范围：排除 writer 自身 / tests/ / migrations/ / delivery/models/。"""
    if rel == _ALLOWED_DOCUMENT_WRITER:
        return False
    if rel.startswith("tests/") or "/tests/" in rel:
        return False
    if "/migrations/" in rel:
        return False
    if rel.startswith("delivery/models/"):
        return False
    return True


def test_inv6_no_bypass_document_write() -> None:
    """INV-6：除 DocumentService 外，server 源码无旁路 Document/DocumentVersion 写表入口。"""
    violations: list[str] = []

    for path in _iter_py_files():
        rel = path.relative_to(SERVER_DIR).as_posix()
        if not _is_scanned_for_document_inv6(rel):
            continue
        for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            stripped = line.lstrip()
            # 跳过模型定义行（class Document / class DocumentVersion）
            if stripped.startswith("class Document"):
                continue
            if (
                _RE_DOC_ORM_WRITE.search(line)
                or _RE_DOC_INSTANCE_SAVE.search(line)
                or _RE_DOC_INSTANTIATE.search(line)
                or _RE_DOCVER_ORM_WRITE.search(line)
                or _RE_DOCVER_INSTANCE_SAVE.search(line)
                or _RE_DOCVER_INSTANTIATE.search(line)
            ):
                violations.append(f"{rel}:{lineno}: {line.strip()}")

    assert not violations, (
        "INV-6 违反：发现旁路 Document/DocumentVersion 写表（落库只允许经 "
        f"DocumentService.upsert_from_feishu / {_ALLOWED_DOCUMENT_WRITER}）：\n"
        + "\n".join(violations)
    )


def test_inv6_document_writer_module_actually_writes() -> None:
    """守护有效性：唯一允许的 writer 确实含 Document/DocumentVersion 写表（否则断言形同虚设）。"""
    writer = SERVER_DIR / _ALLOWED_DOCUMENT_WRITER
    assert writer.exists(), f"{_ALLOWED_DOCUMENT_WRITER} 不存在"
    text = writer.read_text(encoding="utf-8")
    # Document 经 get_or_create 收口；DocumentVersion 经 .objects.create 翻版本
    assert "get_or_create" in text, (
        "DocumentService 应是唯一 Document 写表点，但未检出 get_or_create"
    )
    assert _RE_DOCVER_ORM_WRITE.search(text) or _RE_DOCVER_INSTANTIATE.search(text), (
        "DocumentService 应是唯一 DocumentVersion 写表点，但未检出 DocumentVersion 写表"
    )
