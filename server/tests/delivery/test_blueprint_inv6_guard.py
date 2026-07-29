r"""蓝图三模型 + blueprint_status 字段旁路写 INV-6 grep 守护（Phase 111-02 Task 3）。

纯本地源码扫描（无 DB / 网络），镜像 ``test_sdd_spec_inv6_guard.py`` 三正则精确锚定
范式 + ``test_inv6_guard.py`` 的 feishu_chat_id 字段级守护先例：

- **模型级**：``BlueprintThread`` / ``BlueprintThreadMessage`` / ``BlueprintReviewer``
  的 ``.objects.<write>`` / 直接实例化 / 链式 save，唯一允许模块 =
  ``delivery/services/blueprint_lifecycle_service.py``；
- **字段级**：``Artifact.blueprint_status`` 的赋值/kwarg 写（含 CAS update kwargs 与
  ``filter(blueprint_status=...)`` 条件——后者虽是读路径，但出现在 writer 之外通常
  意味着有人在自己拼 CAS 旁路，一并锁死），排除字段定义（delivery/models/）、
  migrations、tests 后仅允许出现在同一 writer。

命中即 fail 并列 ``文件:行``；「守护的守护」反向断言 writer 确实在写（正则真的能命中），
防形同虚设。
"""

from __future__ import annotations

import re
from pathlib import Path

# server/ 根目录（tests/delivery/test_blueprint_inv6_guard.py → parents[2]）
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

# 唯一允许写蓝图三模型与 blueprint_status 字段的模块（相对 server/，INV-6）
_ALLOWED_WRITER = "delivery/services/blueprint_lifecycle_service.py"

# A：<Model>.objects.<write>（同步 + a 前缀异步变体；.filter/.aget 读路径不命中）
_RE_ORM_WRITE = re.compile(
    r"\b(?:BlueprintThread|BlueprintThreadMessage|BlueprintReviewer)"
    r"\.objects\.(?:a?create|a?bulk_create|a?get_or_create|a?update_or_create|a?update)\b"
)
# B：直接实例化（负向前瞻排除更长符号 BlueprintThreadMessage；
#    BlueprintStatus( / ThreadKind( 等枚举类名前缀不同，天然不命中）
_RE_INSTANTIATE = re.compile(
    r"\b(?:BlueprintThread(?!Message)|BlueprintThreadMessage|BlueprintReviewer)\s*\("
)
# C：链式实例化 + save
_RE_INSTANCE_SAVE = re.compile(
    r"\b(?:BlueprintThread(?!Message)|BlueprintThreadMessage|BlueprintReviewer)\([^)]*\)\.a?save\("
)

# 字段级（镜像 feishu_chat_id 先例）：blueprint_status 赋值/kwarg（排除 ==/!= 等比较）
_RE_FIELD_WRITE = re.compile(r"\bblueprint_status\s*=\s*[^=]")


def _iter_py_files() -> list[Path]:
    """遍历 server/ 下 .py 文件（剪掉 venv/缓存/静态目录）。"""
    files: list[Path] = []
    for path in SERVER_DIR.rglob("*.py"):
        if any(part in _PRUNE_DIRS for part in path.relative_to(SERVER_DIR).parts):
            continue
        files.append(path)
    return files


def _is_scanned(rel: str) -> bool:
    """扫描范围：排除 writer 自身 / tests/ / migrations/ / delivery/models/（字段与模型定义）。"""
    if rel == _ALLOWED_WRITER:
        return False
    if rel.startswith("tests/") or "/tests/" in rel:
        return False
    if "/migrations/" in rel:
        return False
    if rel.startswith("delivery/models/"):
        return False
    return True


def test_inv6_no_bypass_blueprint_model_write() -> None:
    """INV-6：除 BlueprintLifecycleService 外，server 源码无旁路蓝图三模型写表入口。"""
    violations: list[str] = []

    for path in _iter_py_files():
        rel = path.relative_to(SERVER_DIR).as_posix()
        if not _is_scanned(rel):
            continue
        for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            stripped = line.lstrip()
            # 跳过模型/枚举定义行（class BlueprintThread / class BlueprintReviewer ...）
            if stripped.startswith("class Blueprint"):
                continue
            if (
                _RE_ORM_WRITE.search(line)
                or _RE_INSTANCE_SAVE.search(line)
                or _RE_INSTANTIATE.search(line)
            ):
                violations.append(f"{rel}:{lineno}: {line.strip()}")

    assert not violations, (
        "INV-6 违反：发现旁路蓝图模型写表（落库只允许经 BlueprintLifecycleService / "
        f"{_ALLOWED_WRITER}）：\n" + "\n".join(violations)
    )


def test_inv6_no_bypass_blueprint_status_field_write() -> None:
    """INV-6 字段级：除唯一 writer 外，server 源码无 ``blueprint_status=`` 赋值/kwarg。

    ``Artifact.blueprint_status`` 的唯一合法写路径是 BlueprintLifecycleService 的
    CAS ``filter(...).update(blueprint_status=...)``；其它模块出现该 kwarg/赋值即视
    为旁路（绕过转移表守卫与并发 CAS），命中即 fail 并列出文件:行。
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
        "INV-6 违反：发现旁路写 Artifact.blueprint_status（状态写只允许经 "
        f"{_ALLOWED_WRITER} 的 CAS update）：\n" + "\n".join(violations)
    )


def test_inv6_blueprint_writer_actually_writes() -> None:
    """守护的守护：唯一 writer 确实含 blueprint_status= 写入与 aget_or_create——
    正则真的能命中 writer 的写法，防守护形同虚设。"""
    writer = SERVER_DIR / _ALLOWED_WRITER
    assert writer.exists(), f"{_ALLOWED_WRITER} 不存在"
    text = writer.read_text(encoding="utf-8")
    assert _RE_FIELD_WRITE.search(text), (
        "BlueprintLifecycleService 应是唯一 blueprint_status 写点，但未检出 blueprint_status= 写入"
    )
    assert _RE_ORM_WRITE.search(text), (
        "BlueprintLifecycleService 应是唯一 BlueprintReviewer 写表点，"
        "但未检出 .objects.<write>（aget_or_create）"
    )
