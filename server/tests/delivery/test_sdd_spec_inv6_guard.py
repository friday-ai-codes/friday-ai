r"""INV-6 守护：SddSpec 落库只经 SddSpecService（Phase 49-02 Task 2）。

纯本地源码扫描（无 DB / 网络），逐行镜像 ``test_architect_merge_inv6_guard.py`` 精确锚定
范式：扫描 ``server/`` 源码（剪 venv/缓存 + 排除 tests/ / migrations/ / delivery/models/ 与
writer 自身），断言无旁路 ``SddSpec`` / ``SddSpecReview`` ``.objects.<write>`` / 直接实例化 /
链式 save 入口；命中即 fail 列 ``文件:行``。

唯一允许写 ``SddSpec`` 与 ``SddSpecReview``（评审 append-only，D-50-2）的模块同为
``delivery/services/sdd_spec_service.py``。

精确锚定：负向前瞻 ``(?!Status|ChangeKind|Service|Synthesizer)`` 排除
``SddSpecStatus(`` / ``SddSpecChangeKind(`` / ``SddSpecService(`` / ``SddSpecSynthesizer(``；
``LLMSddSpecSynthesizer(`` 前接 ``LLM`` 无词边界天然不命中。
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

# 唯一允许写 SddSpec / SddSpecReview 的模块（相对 server/，同 writer）
_ALLOWED_WRITER = "delivery/services/sdd_spec_service.py"

# A：SddSpec.objects.<write>
_RE_ORM_WRITE = re.compile(
    r"\bSddSpec\.objects\.(?:create|bulk_create|get_or_create|update_or_create|update)\b"
)
# B：直接实例化 SddSpec(...)（负向前瞻排除更长符号）
_RE_INSTANTIATE = re.compile(r"\bSddSpec(?!Status|ChangeKind|Service|Synthesizer)\s*\(")
# C：链式实例化 + save
_RE_INSTANCE_SAVE = re.compile(
    r"\bSddSpec(?!Status|ChangeKind|Service|Synthesizer)\([^)]*\)\.save\("
)

# SddSpecReview 旁路写守护（D-50-2，append-only 不可篡改；同 writer = SddSpecService）。
# A'：SddSpecReview.objects.<write>
_RE_REVIEW_ORM_WRITE = re.compile(
    r"\bSddSpecReview\.objects\.(?:create|bulk_create|get_or_create|update_or_create|update)\b"
)
# B'：直接实例化 SddSpecReview(...)（无 Status/Service 等更长后缀，简单词边界即可）
_RE_REVIEW_INSTANTIATE = re.compile(r"\bSddSpecReview\s*\(")
# C'：链式实例化 + save
_RE_REVIEW_INSTANCE_SAVE = re.compile(r"\bSddSpecReview\([^)]*\)\.save\(")


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


def test_inv6_no_bypass_sdd_spec_write() -> None:
    """INV-6：除 SddSpecService 外，server 源码无旁路 SddSpec 写表入口。"""
    violations: list[str] = []

    for path in _iter_py_files():
        rel = path.relative_to(SERVER_DIR).as_posix()
        if not _is_scanned(rel):
            continue
        for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            stripped = line.lstrip()
            # 跳过模型定义行（class SddSpec / class SddSpecStatus / ...）
            if stripped.startswith("class SddSpec"):
                continue
            if (
                _RE_ORM_WRITE.search(line)
                or _RE_INSTANCE_SAVE.search(line)
                or _RE_INSTANTIATE.search(line)
                or _RE_REVIEW_ORM_WRITE.search(line)
                or _RE_REVIEW_INSTANCE_SAVE.search(line)
                or _RE_REVIEW_INSTANTIATE.search(line)
            ):
                violations.append(f"{rel}:{lineno}: {line.strip()}")

    assert not violations, (
        "INV-6 违反：发现旁路 SddSpec 写表（落库只允许经 SddSpecService / "
        f"{_ALLOWED_WRITER}）：\n" + "\n".join(violations)
    )


def test_inv6_sdd_spec_writer_actually_writes() -> None:
    """守护有效性：唯一 writer 确实含 SddSpec.objects.get_or_create，防形同虚设。"""
    writer = SERVER_DIR / _ALLOWED_WRITER
    assert writer.exists(), f"{_ALLOWED_WRITER} 不存在"
    text = writer.read_text(encoding="utf-8")
    assert _RE_ORM_WRITE.search(text), (
        "SddSpecService 应是唯一 SddSpec 写表点，但未检出 SddSpec.objects.<write>"
    )


def test_inv6_sdd_spec_review_writer_actually_writes() -> None:
    """守护有效性：唯一 writer 确实含 SddSpecReview.objects.create，防守护形同虚设。"""
    writer = SERVER_DIR / _ALLOWED_WRITER
    assert writer.exists(), f"{_ALLOWED_WRITER} 不存在"
    text = writer.read_text(encoding="utf-8")
    assert _RE_REVIEW_ORM_WRITE.search(text), (
        "SddSpecService 应是唯一 SddSpecReview 写表点，但未检出 SddSpecReview.objects.<write>"
    )
