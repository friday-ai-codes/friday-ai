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
_PHASE_143_PIPELINE = (
    "initiatives/services/session_capture_eval.py",
    "initiatives/services/session_capture_enqueue.py",
    "durable/tasks_impl.py",
    "knowledge/sources/session_capture.py",
)
_FORBIDDEN_PIPELINE_SYMBOLS = (
    "MemoryService",
    "record_hook_writeback",
    "aschedule_ingestion",
    "background_runner",
)
_FORBIDDEN_DIRECT_SINKS = (
    "KnowledgeEntity.objects.create",
    "KnowledgeEntity.objects.update",
    "QdrantService",
)

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
    """唯一 writer 只负责状态落库，durable enqueue 必须位于独立边界。"""
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


def test_eval_enqueue_worker_and_normalizer_do_not_bypass_inv6() -> None:
    """Phase 143 流水线不得直写 Capture、Memory 或平行摄取入口。"""
    missing = [relative for relative in _PHASE_143_PIPELINE if not (SERVER_DIR / relative).exists()]
    assert missing == [], f"Phase 143 流水线文件尚未建立：{missing}"

    violations: list[str] = []
    for relative in _PHASE_143_PIPELINE:
        text = (SERVER_DIR / relative).read_text(encoding="utf-8")
        for symbol in _FORBIDDEN_PIPELINE_SYMBOLS + _FORBIDDEN_DIRECT_SINKS:
            if symbol in text:
                violations.append(f"{relative}: forbidden {symbol}")
        for lineno, line in enumerate(text.splitlines(), 1):
            if (
                _RE_ORM_WRITE.search(line)
                or _RE_CHAINED_UPDATE.search(line)
                or _RE_INSTANCE_SAVE.search(line)
                or _RE_INSTANTIATE.search(line)
            ):
                violations.append(f"{relative}:{lineno}: {line.strip()}")

    assert violations == [], "INV-6 / ingestion 边界违反：\n" + "\n".join(violations)


def test_enqueue_boundary_owns_durable_defer_not_capture_writer() -> None:
    """persist writer 不投递；独立 enqueue helper 是 durable 边界。"""
    enqueue_path = SERVER_DIR / "initiatives/services/session_capture_enqueue.py"
    assert enqueue_path.exists()
    enqueue_text = enqueue_path.read_text(encoding="utf-8")
    writer_text = (SERVER_DIR / _ALLOWED_WRITER).read_text(encoding="utf-8")

    assert "DurableTaskService.defer" in enqueue_text
    assert "DurableTaskService.defer" not in writer_text
    assert "enqueue_session_capture_eval" not in writer_text
