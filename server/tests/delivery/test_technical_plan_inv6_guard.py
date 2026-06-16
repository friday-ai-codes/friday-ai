r"""INV-6 守护：canonical TechnicalPlan/PlanVersion 落库只经 TechnicalPlanService。

纯本地源码扫描（无 DB / 网络），复刻 ``test_plan_session_inv6_guard.py`` 范式：
扫描 ``server/`` 源码（剪 venv/缓存 + 排除 tests/ / migrations/ / delivery/models/
与 service 自身），断言无旁路 ``TechnicalPlan.objects.<write>`` /
``PlanVersion.objects.<write>`` / 实例化 ``TechnicalPlan(`` / ``PlanVersion(`` 入口。

正则用 ``\bTechnicalPlan\(``（紧跟 ``(`` 无空格）天然排除 ``TechnicalPlanService(`` /
``TechnicalPlanStatus`` / ``TechnicalPlanOrigin`` 与 mcp 的 ``McpWorkItemTechnicalPlan``
（前者无 ``\b`` 边界）。
"""

from __future__ import annotations

import re
from pathlib import Path

# server/ 根目录（tests/delivery/test_technical_plan_inv6_guard.py → parents[2]）
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

# 唯一允许写 canonical 表的模块（相对 server/）
_ALLOWED_WRITER = "delivery/services/technical_plan_service.py"

# 同名但不相关的模块：``workflows/schemas/technical_plan.py`` 定义了一个**dataclass**
# ``TechnicalPlan``（LLM 输出 schema，PF-02），与 delivery 的 Django 模型同名但完全无关。
# 其 ``dict_to_technical_plan`` 实例化该 dataclass（``return TechnicalPlan(...)``）不是
# canonical 写表，按文件白名单豁免（无法仅凭名字区分 dataclass vs model）。
_NAME_COLLISION_EXEMPT = {"workflows/schemas/technical_plan.py"}

# A：TechnicalPlan.objects.<write> / PlanVersion.objects.<write>
_RE_ORM_WRITE = re.compile(
    r"\b(?:TechnicalPlan|PlanVersion)\.objects\."
    r"(?:create|bulk_create|get_or_create|update_or_create|update)\b"
)
# B：直接实例化 TechnicalPlan(...) / PlanVersion(...)（紧跟 "(" 无空格——
#    天然排除 TechnicalPlanService(/TechnicalPlanStatus(/TechnicalPlanOrigin( 等更长符号）
_RE_INSTANTIATE = re.compile(r"\b(?:TechnicalPlan|PlanVersion)\(")
# C：链式实例化 + save
_RE_INSTANCE_SAVE = re.compile(r"\b(?:TechnicalPlan|PlanVersion)\([^)]*\)\.save\(")


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
    if rel in _NAME_COLLISION_EXEMPT:
        return False
    if rel.startswith("tests/") or "/tests/" in rel:
        return False
    if "/migrations/" in rel:
        return False
    if rel.startswith("delivery/models/"):
        return False
    return True


def test_inv6_no_bypass_canonical_plan_write() -> None:
    """INV-6：除 TechnicalPlanService 外，server 源码无旁路 canonical 写表入口。"""
    violations: list[str] = []

    for path in _iter_py_files():
        rel = path.relative_to(SERVER_DIR).as_posix()
        if not _is_scanned(rel):
            continue
        for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            stripped = line.lstrip()
            # 跳过模型定义行
            if stripped.startswith("class TechnicalPlan") or stripped.startswith(
                "class PlanVersion"
            ):
                continue
            if (
                _RE_ORM_WRITE.search(line)
                or _RE_INSTANCE_SAVE.search(line)
                or _RE_INSTANTIATE.search(line)
            ):
                violations.append(f"{rel}:{lineno}: {line.strip()}")

    assert not violations, (
        "INV-6 违反：发现旁路 canonical 方案写表（落库/版本只允许经 "
        f"TechnicalPlanService / {_ALLOWED_WRITER}）：\n" + "\n".join(violations)
    )


def test_inv6_writer_module_actually_writes_canonical() -> None:
    """守护有效性：唯一 writer 确实写 TechnicalPlan + PlanVersion，否则守护形同虚设。"""
    writer = SERVER_DIR / _ALLOWED_WRITER
    assert writer.exists(), f"{_ALLOWED_WRITER} 不存在"
    text = writer.read_text(encoding="utf-8")
    assert re.search(r"\bTechnicalPlan\.objects\.create\b", text), (
        "TechnicalPlanService 应含 TechnicalPlan.objects.create"
    )
    assert re.search(r"\bPlanVersion\.objects\.create\b", text), (
        "TechnicalPlanService 应含 PlanVersion.objects.create"
    )
