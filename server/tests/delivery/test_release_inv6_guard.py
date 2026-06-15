r"""Release 三模型旁路写表 INV-6 grep 守护（Phase 31-02 Task 2）。

纯本地源码扫描，无 DB / 网络（沿用 test_inv6_guard.py / test_document_inv6_guard.py
精确锚定范式，独立文件避免与既有守护文件所有权冲突）：

- **INV-6**：``ReleaseBatch`` / ``ReleaseRecord`` / ``ReleaseArtifact`` 落库只经
  ``ReleaseService``（``delivery/services/release_service.py``）。扫描 ``server/``
  源码（排除 tests/ / migrations/ / delivery/models/ 与 writer 自身），断言无旁路
  ``<Model>.objects.create``/``<Model>(...)``/.save() 写表入口；命中即 fail 并列出文件:行。
- **writer 有效性**：断言 release_service.py 确实含 Release 写表（否则守护形同虚设）。

精确锚定避免误伤更长符号与读路径：``\b<Model>\s*\(`` 的 ``\s*\(`` 紧跟天然排除
``ReleaseArtifactType(`` / ``ReleaseRecordSerializer(`` / ``ReleaseService(`` 等更长符号；
case-sensitive；``<Model>\.objects\.<write>`` 锚定类本体且不命中 ``.objects.filter/get``
读路径。
"""

from __future__ import annotations

import re
from pathlib import Path

# server/ 根目录（tests/delivery/test_release_inv6_guard.py → parents[2]）
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

# 唯一允许写 Release 三模型的模块（相对 server/）
_ALLOWED_RELEASE_WRITER = "delivery/services/release_service.py"

# Release 三模型名（用于精确锚定正则构造）。
_RELEASE_MODELS = ("ReleaseBatch", "ReleaseRecord", "ReleaseArtifact")

# 每个模型三类精确正则：
# A：<Model>.objects.<write>（紧跟 ".objects" 锚定类本体；.filter/.get 读路径不命中）
# B：直接实例化 <Model>(...)（"\s*\(" 紧跟，天然排除 ReleaseArtifactType( / ReleaseRecordSerializer( 等）
# C：链式实例化 + save（<Model>(...).save(...)）
_PATTERNS: list[re.Pattern[str]] = []
for _model in _RELEASE_MODELS:
    _PATTERNS.append(
        re.compile(
            rf"\b{_model}\.objects\.(?:create|bulk_create|get_or_create|update_or_create)\b"
        )
    )
    _PATTERNS.append(re.compile(rf"\b{_model}\s*\("))
    _PATTERNS.append(re.compile(rf"\b{_model}\([^)]*\)\.save\("))


def _iter_py_files() -> list[Path]:
    """遍历 server/ 下 .py 文件（剪掉 venv/缓存/静态目录）。"""
    files: list[Path] = []
    for path in SERVER_DIR.rglob("*.py"):
        if any(part in _PRUNE_DIRS for part in path.relative_to(SERVER_DIR).parts):
            continue
        files.append(path)
    return files


def _is_scanned_for_release_inv6(rel: str) -> bool:
    """Release INV-6 扫描范围：排除 writer 自身 / tests/ / migrations/ / delivery/models/。"""
    if rel == _ALLOWED_RELEASE_WRITER:
        return False
    if rel.startswith("tests/") or "/tests/" in rel:
        return False
    if "/migrations/" in rel:
        return False
    if rel.startswith("delivery/models/"):
        return False
    return True


def test_inv6_no_bypass_release_write() -> None:
    """INV-6：除 ReleaseService 外，server 源码无旁路 Release 三模型写表入口。"""
    violations: list[str] = []

    for path in _iter_py_files():
        rel = path.relative_to(SERVER_DIR).as_posix()
        if not _is_scanned_for_release_inv6(rel):
            continue
        for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            stripped = line.lstrip()
            # 跳过模型定义行（class ReleaseBatch / class ReleaseRecord / class ReleaseArtifact）
            if stripped.startswith("class Release"):
                continue
            if any(pattern.search(line) for pattern in _PATTERNS):
                violations.append(f"{rel}:{lineno}: {line.strip()}")

    assert not violations, (
        "INV-6 违反：发现旁路 Release 写表（落库只允许经 "
        f"ReleaseService / {_ALLOWED_RELEASE_WRITER}）：\n" + "\n".join(violations)
    )


def test_inv6_release_writer_module_actually_writes() -> None:
    """守护有效性：唯一允许的 writer 确实含 Release 写表（否则断言形同虚设）。"""
    writer = SERVER_DIR / _ALLOWED_RELEASE_WRITER
    assert writer.exists(), f"{_ALLOWED_RELEASE_WRITER} 不存在"
    text = writer.read_text(encoding="utf-8")
    # ReleaseRecord 经 get_or_create / 实例化收口（幂等 upsert）
    record_orm = re.compile(
        r"\bReleaseRecord\.objects\.(?:create|bulk_create|get_or_create|update_or_create)\b"
    )
    record_inst = re.compile(r"\bReleaseRecord\s*\(")
    assert record_orm.search(text) or record_inst.search(text), (
        "ReleaseService 应是唯一 Release 写表点，但未检出 ReleaseRecord 写表"
    )
