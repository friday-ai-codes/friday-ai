"""INV-6 守护：PlanSession.status / 落库只经 PlanSessionService（ORCH-02）。

纯本地源码扫描（无 DB / 网络），复刻 ``tests/delivery/test_inv6_guard.py`` 范式：
扫描 ``server/`` 源码（剪 venv/缓存 + 排除 tests/ / migrations/ / delivery/models/
与 service 自身），断言无旁路 ``PlanSession.objects.<write>`` / 实例化 ``PlanSession(``
/ ``.save()`` 入口；命中即 fail 并列出 ``文件:行``。

engine（36-03）经 ``PlanSessionService.transition`` 驱动转移、不直接写 status，
故不应被本守护命中——若被命中即真实违规，应失败暴露。
"""

from __future__ import annotations

import re
from pathlib import Path

# server/ 根目录（tests/delivery/test_plan_session_inv6_guard.py → parents[2]）
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

# 唯一允许写 PlanSession 的模块（相对 server/）
_ALLOWED_WRITER = "delivery/services/plan_session_service.py"

# A：PlanSession.objects.<write>（紧跟 ".objects" 确保是类本体，
#    case-sensitive 天然排除 PlanSessionStatus/PlanSessionEntrypoint）
_RE_ORM_WRITE = re.compile(
    r"\bPlanSession\.objects\.(?:create|bulk_create|get_or_create|update_or_create|update)\b"
)
# B：直接实例化 PlanSession(...)（"\s*\(" 紧跟，天然排除
#    PlanSessionService(/PlanSessionStatus(/PlanSessionEntrypoint( 等更长符号）
_RE_INSTANTIATE = re.compile(r"\bPlanSession\s*\(")
# C：链式实例化 + save（PlanSession(...).save(...)）
_RE_INSTANCE_SAVE = re.compile(r"\bPlanSession\([^)]*\)\.save\(")


def _iter_py_files() -> list[Path]:
    files: list[Path] = []
    for path in SERVER_DIR.rglob("*.py"):
        if any(part in _PRUNE_DIRS for part in path.relative_to(SERVER_DIR).parts):
            continue
        files.append(path)
    return files


def _is_scanned(rel: str) -> bool:
    """扫描范围：排除 tests/ / migrations/ / delivery/models/ 与 service 自身。"""
    if rel == _ALLOWED_WRITER:
        return False
    if rel.startswith("tests/") or "/tests/" in rel:
        return False
    if "/migrations/" in rel:
        return False
    if rel.startswith("delivery/models/"):
        return False
    return True


def test_inv6_no_bypass_plan_session_write() -> None:
    """INV-6：除 PlanSessionService 外，server 源码无旁路 PlanSession 写表入口。"""
    violations: list[str] = []

    for path in _iter_py_files():
        rel = path.relative_to(SERVER_DIR).as_posix()
        if not _is_scanned(rel):
            continue
        for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            # 跳过模型定义行（class PlanSession(models.Model):）
            if line.lstrip().startswith("class PlanSession"):
                continue
            # 仅扫描代码部分：剥离行内注释，避免注释中提及 PlanSession(...) 被误判为旁路写入。
            code_part = line.split("#", 1)[0]
            if (
                _RE_ORM_WRITE.search(code_part)
                or _RE_INSTANCE_SAVE.search(code_part)
                or _RE_INSTANTIATE.search(code_part)
            ):
                violations.append(f"{rel}:{lineno}: {line.strip()}")

    assert not violations, (
        "INV-6 违反：发现旁路 PlanSession 写表（状态变更/落库只允许经 "
        f"PlanSessionService / {_ALLOWED_WRITER}）：\n" + "\n".join(violations)
    )


def test_inv6_writer_module_actually_writes_status() -> None:
    """守护有效性：唯一 writer 确实写 status（含 .status = 赋值），否则守护形同虚设。"""
    writer = SERVER_DIR / _ALLOWED_WRITER
    assert writer.exists(), f"{_ALLOWED_WRITER} 不存在"
    text = writer.read_text(encoding="utf-8")
    assert re.search(r"\.status\s*=", text), (
        "PlanSessionService 应是唯一 PlanSession status 写入点，但未检出 .status= 赋值"
    )
    assert _RE_ORM_WRITE.search(text), (
        "PlanSessionService 应包含 PlanSession.objects.<write>（create_session）"
    )
