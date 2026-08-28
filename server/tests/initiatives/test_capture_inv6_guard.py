"""Phase 141：SessionCapture 仅允许 CaptureService 写入的 INV-6 守卫。"""

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

_ALLOWED_WRITER = "initiatives/services/capture_service.py"

_RE_ORM_WRITE = re.compile(
    r"\bSessionCapture\.objects\."
    r"(?:create|bulk_create|get_or_create|update_or_create|update)\b"
)
_RE_CHAINED_UPDATE = re.compile(
    r"\bSessionCapture\.objects\.(?:filter|all)\([^)]*\)\.update\s*\("
)
_RE_INSTANTIATE = re.compile(r"\bSessionCapture\s*\(")
_RE_INSTANCE_SAVE = re.compile(r"\bSessionCapture\([^)]*\)\.save\s*\(")


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


def test_inv6_no_bypass_capture_write() -> None:
    """INV-6：除 CaptureService 外，server 源码无 SessionCapture 写入口。"""
    violations: list[str] = []

    for path in _iter_py_files():
        rel = path.relative_to(SERVER_DIR).as_posix()
        if not _is_scanned(rel):
            continue
        for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            if line.lstrip().startswith("class SessionCapture"):
                continue
            if (
                _RE_ORM_WRITE.search(line)
                or _RE_CHAINED_UPDATE.search(line)
                or _RE_INSTANCE_SAVE.search(line)
                or _RE_INSTANTIATE.search(line)
            ):
                violations.append(f"{rel}:{lineno}: {line.strip()}")

    assert not violations, (
        "INV-6 违反：发现旁路 SessionCapture 写表"
        f"（落库只允许经 CaptureService / {_ALLOWED_WRITER}）：\n" + "\n".join(violations)
    )


def test_inv6_writer_module_actually_writes() -> None:
    """守护有效性：唯一 writer 必须实际创建 SessionCapture。"""
    writer = SERVER_DIR / _ALLOWED_WRITER
    assert writer.exists(), f"{_ALLOWED_WRITER} 不存在"
    text = writer.read_text(encoding="utf-8")
    assert "SessionCapture.objects.create" in text


def test_writer_does_not_call_deferred_sinks() -> None:
    """Phase 141 writer 不得提前接入评估、入图、Memory 或项目分支解析。"""
    writer = SERVER_DIR / _ALLOWED_WRITER
    assert writer.exists(), f"{_ALLOWED_WRITER} 不存在"
    text = writer.read_text(encoding="utf-8")
    forbidden = (
        "aschedule_ingestion",
        "MemoryService",
        "record_hook_writeback",
        "background_runner",
        "_resolve_report_project_id",
        "lookup_project_by_branch",
        "arecord_tool_call",
    )
    found = [symbol for symbol in forbidden if symbol in text]
    assert found == [], f"CaptureService 不得调用延迟/旁路入口：{found}"
