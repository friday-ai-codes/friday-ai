"""INV-6 守护：RepoResearchTask / PartialPlan 落库只经 ResearchService（Phase 39-02）。

纯本地源码扫描（无 DB / 网络），复刻 ``test_plan_session_inv6_guard.py`` 范式：
扫描 ``server/`` 源码（剪 venv/缓存 + 排除 tests/ / migrations/ / delivery/models/
与 service 自身），断言无旁路 ``RepoResearchTask.objects.<write>`` /
``PartialPlan.objects.<write>`` / 实例化 / 链式 save 入口；命中即 fail 列 ``文件:行``。
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

# 唯一允许写两模型的模块（相对 server/）
_ALLOWED_WRITER = "delivery/services/research_service.py"

# A：<Model>.objects.<write>
_RE_ORM_WRITE = re.compile(
    r"\b(?:RepoResearchTask|PartialPlan)\.objects\."
    r"(?:create|bulk_create|get_or_create|update_or_create|update)\b"
)
# B：直接实例化（"\s*\(" 紧跟；case-sensitive 天然排除 RepoResearchTaskStatus( ——
#    它以 RepoResearchTaskStatus 开头，正则用 \b(...)\s*\( 对 RepoResearchTask 会在
#    "Status" 处不匹配 \s*\( 故安全，但显式排除更稳妥）
_RE_INSTANTIATE = re.compile(r"\b(?:RepoResearchTask|PartialPlan)\s*\(")
# C：链式实例化 + save
_RE_INSTANCE_SAVE = re.compile(r"\b(?:RepoResearchTask|PartialPlan)\([^)]*\)\.save\(")


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


def test_inv6_no_bypass_research_write() -> None:
    """INV-6：除 ResearchService 外，server 源码无旁路两模型写表入口。"""
    violations: list[str] = []

    for path in _iter_py_files():
        rel = path.relative_to(SERVER_DIR).as_posix()
        if not _is_scanned(rel):
            continue
        for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            # 跳过模型定义行（class RepoResearchTask(...) / class PartialPlan(...)）；
            # 注意 _RE_INSTANTIATE 的 "\s*\(" 紧跟天然排除 RepoResearchTaskStatus(（枚举非写）。
            stripped = line.lstrip()
            if stripped.startswith("class RepoResearchTask") or stripped.startswith(
                "class PartialPlan"
            ):
                continue
            if (
                _RE_ORM_WRITE.search(line)
                or _RE_INSTANCE_SAVE.search(line)
                or _RE_INSTANTIATE.search(line)
            ):
                violations.append(f"{rel}:{lineno}: {line.strip()}")

    assert not violations, (
        "INV-6 违反：发现旁路 RepoResearchTask/PartialPlan 写表（落库只允许经 "
        f"ResearchService / {_ALLOWED_WRITER}）：\n" + "\n".join(violations)
    )


def test_inv6_writer_actually_writes() -> None:
    """守护有效性：唯一 writer 确实写状态 + 建行，否则守护形同虚设。"""
    writer = SERVER_DIR / _ALLOWED_WRITER
    assert writer.exists(), f"{_ALLOWED_WRITER} 不存在"
    text = writer.read_text(encoding="utf-8")
    assert re.search(r"\.status\s*=", text), (
        "ResearchService 应写 RepoResearchTask.status，但未检出 .status= 赋值"
    )
    assert _RE_ORM_WRITE.search(text), (
        "ResearchService 应包含 RepoResearchTask/PartialPlan.objects.<write>"
    )
