"""INV-6 守护：ArchitectMerge 落库只经融合 adapter（Phase 40-02 Task 3）。

纯本地源码扫描（无 DB / 网络），复刻 ``test_research_inv6_guard.py`` 范式：扫描
``server/`` 源码（剪 venv/缓存 + 排除 tests/ / migrations/ / delivery/models/ 与
writer 自身），断言无旁路 ``ArchitectMerge.objects.<write>`` / 直接实例化 /
链式 save 入口；命中即 fail 列 ``文件:行``。

唯一允许写 ``ArchitectMerge`` 的模块 = 融合 adapter
``services/process_runtime/architect_merge_adapter.py``。
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

# 唯一允许写 ArchitectMerge 的模块（融合 service/adapter，相对 server/）
_ALLOWED_WRITER = "services/process_runtime/architect_merge_adapter.py"

# A：ArchitectMerge.objects.<write>
_RE_ORM_WRITE = re.compile(
    r"\bArchitectMerge\.objects\."
    r"(?:create|bulk_create|get_or_create|update_or_create|update)\b"
)
# B：直接实例化 ArchitectMerge(...)；显式负向前瞻排除 ArchitectMergeStatus( / ArchitectMergeAdapter(
_RE_INSTANTIATE = re.compile(r"\bArchitectMerge(?!Status|Adapter)\s*\(")
# C：链式实例化 + save
_RE_INSTANCE_SAVE = re.compile(r"\bArchitectMerge(?!Status|Adapter)\([^)]*\)\.save\(")


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
    if rel.startswith("delivery/models/"):
        return False
    return True


def test_inv6_no_bypass_architect_merge_write() -> None:
    """INV-6：除融合 adapter 外，server 源码无旁路 ArchitectMerge 写表入口。"""
    violations: list[str] = []

    for path in _iter_py_files():
        rel = path.relative_to(SERVER_DIR).as_posix()
        if not _is_scanned(rel):
            continue
        for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            stripped = line.lstrip()
            # 跳过模型定义行（class ArchitectMerge(...) / class ArchitectMergeStatus(...)）
            if stripped.startswith("class ArchitectMerge"):
                continue
            if (
                _RE_ORM_WRITE.search(line)
                or _RE_INSTANCE_SAVE.search(line)
                or _RE_INSTANTIATE.search(line)
            ):
                violations.append(f"{rel}:{lineno}: {line.strip()}")

    assert not violations, (
        "INV-6 违反：发现旁路 ArchitectMerge 写表（落库只允许经融合 adapter / "
        f"{_ALLOWED_WRITER}）：\n" + "\n".join(violations)
    )


def test_inv6_writer_actually_writes() -> None:
    """守护有效性：唯一 writer 确实写 ArchitectMerge + validation_status，防形同虚设。"""
    writer = SERVER_DIR / _ALLOWED_WRITER
    assert writer.exists(), f"{_ALLOWED_WRITER} 不存在"
    text = writer.read_text(encoding="utf-8")
    assert _RE_ORM_WRITE.search(text), (
        "融合 adapter 应含 ArchitectMerge.objects.create"
    )
    assert "validation_status" in text, (
        "融合 adapter 应写 ArchitectMerge.validation_status"
    )
