r"""INV-6 守护：AuditEvent 落库只经 AuditService（AUDIT-01）。

纯本地源码扫描（无 DB / 网络），逐行镜像 ``test_sdd_spec_inv6_guard.py`` 精确锚定范式：
扫描 ``server/`` 源码（剪 venv/缓存 + 排除 tests/ / migrations/ / audit/models/ 与 writer
自身），断言无旁路 ``AuditEvent`` ``.objects.<write>`` / 直接实例化 / 链式 save 入口；
命中即 fail 列 ``文件:行``。这是 append-only「无旁路写表」第二道防线（模型层守护为第一道）。

唯一允许写 ``AuditEvent`` 的模块 = ``audit/services/audit_service.py``。

精确锚定：负向前瞻 ``(?!Immutable)`` 排除 ``AuditEventImmutableError(`` 异常类，避免误判。
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

# 唯一允许写 AuditEvent 的模块（相对 server/）
_ALLOWED_WRITER = "audit/services/audit_service.py"

# A：AuditEvent.objects.<write>
_RE_ORM_WRITE = re.compile(
    r"\bAuditEvent\.objects\.(?:create|bulk_create|get_or_create|update_or_create|update)\b"
)
# B：直接实例化 AuditEvent(...)（负向前瞻排除 AuditEventImmutableError(）
_RE_INSTANTIATE = re.compile(r"\bAuditEvent(?!Immutable)\s*\(")
# C：链式实例化 + save
_RE_INSTANCE_SAVE = re.compile(r"\bAuditEvent(?!Immutable)\([^)]*\)\.save\(")


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
    if rel.startswith("audit/models/"):
        return False
    return True


def test_inv6_no_bypass_audit_event_write() -> None:
    """INV-6：除 AuditService 外，server 源码无旁路 AuditEvent 写表入口。"""
    violations: list[str] = []

    for path in _iter_py_files():
        rel = path.relative_to(SERVER_DIR).as_posix()
        if not _is_scanned(rel):
            continue
        for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            stripped = line.lstrip()
            # 跳过模型定义行（class AuditEvent / class AuditEventImmutableError）
            if stripped.startswith("class AuditEvent"):
                continue
            if (
                _RE_ORM_WRITE.search(line)
                or _RE_INSTANCE_SAVE.search(line)
                or _RE_INSTANTIATE.search(line)
            ):
                violations.append(f"{rel}:{lineno}: {line.strip()}")

    assert not violations, (
        "INV-6 违反：发现旁路 AuditEvent 写表（落库只允许经 AuditService / "
        f"{_ALLOWED_WRITER}）：\n" + "\n".join(violations)
    )


def test_inv6_audit_writer_actually_writes() -> None:
    """守护有效性：唯一 writer 确实含 AuditEvent.objects.create，防守护形同虚设。"""
    writer = SERVER_DIR / _ALLOWED_WRITER
    assert writer.exists(), f"{_ALLOWED_WRITER} 不存在"
    text = writer.read_text(encoding="utf-8")
    assert _RE_ORM_WRITE.search(text), (
        "AuditService 应是唯一 AuditEvent 写表点，但未检出 AuditEvent.objects.<write>"
    )
