"""per-entry 运行时开关 + 「实参必须是字面量」源码扫描守卫（Phase 116-01 Task 1）。

守六件事：

1. **默认**：无设置 ⇒ 四个 entry 全返 ``technical_plan``（参数化四条）。
2. **正路 + per-entry 独立性**：只把 ``mcp`` 切到 ``technical_blueprint`` ⇒ 其余三个仍
   留在旧链（**正反并列**，只断言 mcp 那一条不算数）。
3. **畸形**：非 JSON 串 / JSON 数组 / ``null`` 三种都回默认且不抛。
4. **内层非法值**：``aget_json_setting`` **只保证外层是 dict**
   （``system/settings_service.py:139-153``）⇒ 值域外 / 非字符串 / ``null`` 一律回落。
5. **未知 entry**：``aresolve_entry_process_type("cron")`` 回旧链且不抛。
6. ⭐ **``ast`` 源码扫描守卫（两条谓词）+ 「守护的守护」**：
   - 谓词 ①：``aresolve_entry_process_type`` 的实参必须是 ``ast.Constant``；
   - 谓词 ②：``start_orchestration`` / ``start_blueprint_orchestration`` 上任何
     ``entry_key=`` 的值也必须是 ``ast.Constant``；
   - 「守护的守护」：合成源码里两条反面各一行，断言扫描器**都**报违规
     （形态照 ``tests/delivery/test_blueprint_log_redaction_guard.py:94-115``）。
   - 另加一条：``blueprint_entry_switch.py`` 源码里 ``error=`` 零命中（该模块刻意不进
     ``_SCANNED_MODULES``，代价就是异常文本一律不进日志）。
"""

from __future__ import annotations

import ast
import json
import re
from pathlib import Path

import pytest

from services.process_runtime.blueprint_entry_switch import (
    DEFAULT_ENTRY_SWITCH,
    ENTRY_KEYS,
    PROCESS_TECHNICAL_BLUEPRINT,
    PROCESS_TECHNICAL_PLAN,
    aresolve_entry_process_type,
)

_SERVER_DIR = Path(__file__).resolve().parents[3]
_SWITCH_REL = "services/process_runtime/blueprint_entry_switch.py"


def _save_setting(key: str, value: str) -> None:
    from system.models import SystemSetting

    SystemSetting.objects.update_or_create(key=key, defaults={"value": value})


def _clear_blueprint_settings() -> None:
    """清掉 blueprint.* 设置行与其 60s 缓存（``sync_to_async`` 写在独立连接里提交）。"""
    from django.core.cache import cache

    from system.models import SettingKeys, SystemSetting
    from system.settings_service import _cache_key

    SystemSetting.objects.filter(key__startswith="blueprint.").delete()
    cache.delete(_cache_key(SettingKeys.BLUEPRINT_ENTRY_SWITCH))


@pytest.fixture(autouse=True)
def _isolate_blueprint_settings(request: pytest.FixtureRequest):
    """仅对需要 DB 的用例前后清设置（源码扫描类用例不碰 DB）。"""
    if request.node.get_closest_marker("django_db") is None:
        yield
        return
    request.getfixturevalue("db")
    _clear_blueprint_settings()
    yield
    _clear_blueprint_settings()


async def _asave(value: str) -> None:
    from asgiref.sync import sync_to_async

    from system.models import SettingKeys

    await sync_to_async(_save_setting)(SettingKeys.BLUEPRINT_ENTRY_SWITCH, value)


# ═══════════════════════════════════════════════════════════════════════════
# 1-5. aresolve_entry_process_type 的四层 fail-soft
# ═══════════════════════════════════════════════════════════════════════════


def test_default_switch_is_all_old_chain() -> None:
    """⭐ 默认四键全 ``technical_plan``：不配置 = 与切换前逐字等价（安全默认）。"""
    assert set(DEFAULT_ENTRY_SWITCH) == set(ENTRY_KEYS)
    assert set(DEFAULT_ENTRY_SWITCH.values()) == {PROCESS_TECHNICAL_PLAN}


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
@pytest.mark.parametrize("entry", list(ENTRY_KEYS))
async def test_unconfigured_entry_falls_back_to_old_chain(entry: str) -> None:
    assert await aresolve_entry_process_type(entry) == PROCESS_TECHNICAL_PLAN


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_per_entry_independence_only_flips_the_configured_entry() -> None:
    """⭐ per-entry 独立性的**正反并列**：切了 mcp，其余三个必须原地不动。

    这正是「⛔ 不从 ``session.entrypoint`` 反推」要保住的性质——MCP 入口记的
    ``entrypoint`` 实测是 ``"workflow"``，反推会让打开 workflow 键把 MCP 一起切走。
    """
    await _asave(json.dumps({"mcp": PROCESS_TECHNICAL_BLUEPRINT}))

    assert await aresolve_entry_process_type("mcp") == PROCESS_TECHNICAL_BLUEPRINT
    for entry in ("workflow", "chat", "feature_list"):
        assert await aresolve_entry_process_type(entry) == PROCESS_TECHNICAL_PLAN


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
@pytest.mark.parametrize("raw", ["not-json-at-all", "[1, 2, 3]", "null", '"a string"'])
async def test_malformed_setting_falls_back_without_raising(raw: str) -> None:
    await _asave(raw)
    assert await aresolve_entry_process_type("workflow") == PROCESS_TECHNICAL_PLAN


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
@pytest.mark.parametrize("value", ["blueprint", "", 123, None, True, {"nested": 1}])
async def test_inner_illegal_value_falls_back(value: object) -> None:
    """⚠️ ``aget_json_setting`` 只保证**外层**是 dict ⇒ 内层必须逐键强转 + 值域校验。"""
    await _asave(json.dumps({"workflow": value}))
    assert await aresolve_entry_process_type("workflow") == PROCESS_TECHNICAL_PLAN


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
@pytest.mark.parametrize("entry", ["cron", "", "WORKFLOW", "webhook"])
async def test_unknown_entry_falls_back_without_raising(entry: str) -> None:
    assert await aresolve_entry_process_type(entry) == PROCESS_TECHNICAL_PLAN


# ═══════════════════════════════════════════════════════════════════════════
# 6. ⭐ ast 字面量扫描守卫（两条谓词）+ 守护的守护
# ═══════════════════════════════════════════════════════════════════════════

# 扫描面 = process_runtime 全目录 + 四个入口文件（116-03 新增调用点自动纳入）
_SCANNED_ENTRY_FILES = (
    "workflows/nodes/ai/plan_research.py",
    "agents/tools/plan_research_tools.py",
    "mcp_tools/orchestration_delegate.py",
    "initiatives/services/feature_solution_service.py",
)

_RESOLVER_NAME = "aresolve_entry_process_type"
_START_NAMES = ("start_orchestration", "start_blueprint_orchestration")


def _scanned_files() -> list[Path]:
    paths = sorted((_SERVER_DIR / "services" / "process_runtime").glob("*.py"))
    paths += [_SERVER_DIR / rel for rel in _SCANNED_ENTRY_FILES]
    return [p for p in paths if p.exists()]


def _func_tail_name(func: ast.expr) -> str:
    if isinstance(func, ast.Attribute):
        return func.attr
    if isinstance(func, ast.Name):
        return func.id
    return ""


def _is_str_literal(node: ast.expr | None) -> bool:
    return isinstance(node, ast.Constant) and isinstance(node.value, str)


def _literal_violations(src: str, rel: str) -> list[str]:
    """两条谓词共用的判据：实参不是字符串字面量即违规。"""
    violations: list[str] = []
    for node in ast.walk(ast.parse(src)):
        if not isinstance(node, ast.Call):
            continue
        name = _func_tail_name(node.func)
        if name == _RESOLVER_NAME:
            arg: ast.expr | None = node.args[0] if node.args else None
            if arg is None:
                arg = next((kw.value for kw in node.keywords if kw.arg == "entry"), None)
            if arg is not None and not _is_str_literal(arg):
                violations.append(f"{rel}:{arg.lineno}: {_RESOLVER_NAME}({ast.unparse(arg)})")
        elif name in _START_NAMES:
            # ⚠️ 没有 entry_key keyword **不算违规**：默认空串是 116-03 之前的合法过渡态。
            value = next((kw.value for kw in node.keywords if kw.arg == "entry_key"), None)
            if value is not None and not _is_str_literal(value):
                violations.append(f"{rel}:{value.lineno}: entry_key={ast.unparse(value)}")
    return violations


def test_entry_argument_is_always_a_literal_constant() -> None:
    """⭐ 谓词 ①：``aresolve_entry_process_type`` 的实参必须是字面量常量。

    ⛔ 写成 ``aresolve_entry_process_type(session.entrypoint)`` 会让「只打开 workflow 键」
    把 MCP 一起切走 —— MCP 入口给 ``start_orchestration`` 传的 ``entrypoint`` 实测就是
    ``"workflow"``（``mcp_tools/orchestration_delegate.py:171-178`` 的既有约定）。
    """
    violations: list[str] = []
    for path in _scanned_files():
        rel = str(path.relative_to(_SERVER_DIR))
        violations += [
            v
            for v in _literal_violations(path.read_text(encoding="utf-8"), rel)
            if "entry_key=" not in v
        ]
    assert not violations, "entry 实参必须是字面量常量：\n  " + "\n  ".join(violations)


def test_entry_key_keyword_is_always_a_literal_constant() -> None:
    """⭐ 谓词 ②（同一陷阱的另一半）：``entry_key=`` 的值也必须是字面量常量。

    ``entry_key=session.entrypoint`` 会让 ``technical_plan_entry_used`` 的分桶从第一天起
    就错（MCP 记进 workflow 桶）、**静默且永不报错** —— 而这正是引入 ``entry_key`` 这个
    新形参本来要解决的问题本身。
    """
    violations: list[str] = []
    for path in _scanned_files():
        rel = str(path.relative_to(_SERVER_DIR))
        violations += [
            v
            for v in _literal_violations(path.read_text(encoding="utf-8"), rel)
            if "entry_key=" in v
        ]
    assert not violations, "entry_key= 实参必须是字面量常量：\n  " + "\n  ".join(violations)


def test_the_guard_actually_catches_both_reverse_forms(tmp_path: Path) -> None:
    """守护的守护：两条反面各一行，扫描器必须**都**报出来。

    ⛔ 没有这一条，本守卫在 116-03 补齐调用点之前是空扫描、形同虚设。
    """
    sample = tmp_path / "sample.py"
    sample.write_text(
        "async def f(session):\n"
        "    await aresolve_entry_process_type(session.entrypoint)\n"
        "    await start_orchestration('chat', 'x', entry_key=session.entrypoint)\n"
        "    await aresolve_entry_process_type('mcp')\n"
        "    await start_orchestration('chat', 'x', entry_key='chat')\n"
        "    await start_orchestration('chat', 'x')\n",
        encoding="utf-8",
    )
    violations = _literal_violations(sample.read_text(encoding="utf-8"), "sample.py")

    assert len(violations) == 2, violations
    assert any(f"{_RESOLVER_NAME}(session.entrypoint)" in v for v in violations)
    assert any("entry_key=session.entrypoint" in v for v in violations)


def test_switch_module_never_passes_an_error_kwarg() -> None:
    """⭐ 「不进 ``_SCANNED_MODULES`` 的代价」：本模块零 ``error=`` 实参。"""
    src = (_SERVER_DIR / _SWITCH_REL).read_text(encoding="utf-8")
    assert re.search(r"\berror\s*=", src) is None, "开关模块的兜底分支不得把异常文本写进日志"


def test_switch_module_never_imports_system_at_module_level() -> None:
    """懒 import 纪律：``process_runtime`` 不在模块级依赖 ``system``。"""
    src = (_SERVER_DIR / _SWITCH_REL).read_text(encoding="utf-8")
    assert re.search(r"(?m)^(from system|import system)", src) is None
