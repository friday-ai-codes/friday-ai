"""INV-6 守护：RepoCodingTask 落库只经 RepoCodingTaskService（Phase 44-03）。

纯本地源码扫描（无 DB / 网络），镜像 ``test_research_inv6_guard.py`` 范式：
扫描 ``server/`` 源码（剪 venv/缓存 + 排除 tests/ / migrations/ / delivery/models/
与 service 自身），断言无旁路 ``RepoCodingTask.objects.<write>`` / 实例化 / 链式 save
入口；命中即 fail 列 ``文件:行``。
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

# 唯一允许写模型的模块（相对 server/）
_ALLOWED_WRITER = "delivery/services/repo_coding_task_service.py"

# A：RepoCodingTask.objects.<write>
_RE_ORM_WRITE = re.compile(
    r"\bRepoCodingTask\.objects\."
    r"(?:create|bulk_create|get_or_create|update_or_create|update)\b"
)
# B：直接实例化（"\s*\(" 紧跟；case-sensitive 天然排除 RepoCodingTaskStatus( ——
#    它以 RepoCodingTaskStatus 开头，正则 \bRepoCodingTask\s*\( 在 "Status" 处不匹配
#    \s*\( 故安全，枚举非写）
_RE_INSTANTIATE = re.compile(r"\bRepoCodingTask\s*\(")
# C：链式实例化 + save
_RE_INSTANCE_SAVE = re.compile(r"\bRepoCodingTask\([^)]*\)\.save\(")
# D-14：字段级旁路写守护——实例属性赋值 `xxx.produced_artifacts = ...`（排除 `==` 比较）。
#   service 的 `.objects.update(produced_artifacts=...)` 是 kwarg（无前导 `.`）不命中本正则；
#   模型层 `produced_artifacts = models.JSONField(...)` 同样无前导 `.` 不命中——故两处天然安全。
#   命中即「实例字段旁路写」（如 `task.produced_artifacts = {...}; task.save()`），必拦。
_RE_FIELD_WRITE = re.compile(r"\.produced_artifacts\s*=(?!=)")


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


def test_inv6_no_bypass_repo_coding_task_write() -> None:
    """INV-6：除 RepoCodingTaskService 外，server 源码无旁路 RepoCodingTask 写表入口。"""
    violations: list[str] = []

    for path in _iter_py_files():
        rel = path.relative_to(SERVER_DIR).as_posix()
        if not _is_scanned(rel):
            continue
        for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            # 跳过模型定义行（class RepoCodingTask(...)）；注意 _RE_INSTANTIATE 的 "\s*\("
            # 紧跟天然排除 RepoCodingTaskStatus(（枚举非写）。
            stripped = line.lstrip()
            if stripped.startswith("class RepoCodingTask"):
                continue
            if (
                _RE_ORM_WRITE.search(line)
                or _RE_INSTANCE_SAVE.search(line)
                or _RE_INSTANTIATE.search(line)
            ):
                violations.append(f"{rel}:{lineno}: {line.strip()}")

    assert not violations, (
        "INV-6 违反：发现旁路 RepoCodingTask 写表（落库只允许经 "
        f"RepoCodingTaskService / {_ALLOWED_WRITER}）：\n" + "\n".join(violations)
    )


def test_inv6_no_bypass_produced_artifacts_field_write() -> None:
    """INV-6 字段级守护（D-14）：``.produced_artifacts =`` 实例旁路写只允许在 service / models。

    现有 grep 守护覆盖 ``.objects.<write>`` / 实例化 / 链式 save，但拦不住
    ``some_task.produced_artifacts = {...}; some_task.save()`` 实例字段赋值旁路（Pitfall 6）。
    本守护补盲区：除唯一 writer（service）与 ``delivery/models/``（模型字段定义）外，源码出现
    带前导 ``.`` 的 ``produced_artifacts`` 赋值即 fail（``record_produced_artifacts`` 走
    ``.objects.filter().update(produced_artifacts=...)`` kwarg，不触本正则）。
    """
    violations: list[str] = []

    for path in _iter_py_files():
        rel = path.relative_to(SERVER_DIR).as_posix()
        if not _is_scanned(rel):
            continue
        for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            if _RE_FIELD_WRITE.search(line):
                violations.append(f"{rel}:{lineno}: {line.strip()}")

    assert not violations, (
        "INV-6 违反（D-14 字段级）：发现 produced_artifacts 实例旁路写（落库只允许经 "
        f"RepoCodingTaskService.record_produced_artifacts / {_ALLOWED_WRITER}）：\n"
        + "\n".join(violations)
    )


def test_inv6_writer_actually_writes() -> None:
    """守护有效性：唯一 writer 确实写状态 + 建行，否则守护形同虚设。"""
    writer = SERVER_DIR / _ALLOWED_WRITER
    assert writer.exists(), f"{_ALLOWED_WRITER} 不存在"
    text = writer.read_text(encoding="utf-8")
    assert re.search(r"\.status\s*=", text), (
        "RepoCodingTaskService 应写 RepoCodingTask.status，但未检出 .status= 赋值"
    )
    assert _RE_ORM_WRITE.search(text), "RepoCodingTaskService 应包含 RepoCodingTask.objects.<write>"
    # Phase 51：gate 拦截写入只经 service（D-51-3 / INV-6 唯一入口）。
    assert "def mark_gate_blocked" in text, (
        "RepoCodingTaskService 应提供 mark_gate_blocked（gate 拦截唯一写入入口）"
    )
