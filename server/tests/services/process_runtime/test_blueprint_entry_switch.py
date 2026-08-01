"""per-entry 运行时开关 + 「实参必须是字面量」源码扫描守卫（Phase 116-01 Task 1）。

守六件事（⭐ **同步点 2 收尾已翻默认**：四键从 ``technical_plan`` 翻到
``technical_blueprint``，本文件的默认向断言随之翻面，并补上「显式回滚」那一向）：

1. **默认**：无设置 ⇒ 四个 entry 全返 ``technical_blueprint``（参数化四条）。
2. **正路 + per-entry 独立性 · 双向**：
   - 只把 ``mcp`` 显式回滚到 ``technical_plan`` ⇒ 其余三个仍在蓝图链（运维单入口回滚）；
   - 只把 ``mcp`` 显式置成 ``technical_blueprint`` ⇒ 与默认同值、其余三个不受影响。
   两向**正反并列**，只断言一向都不算数。
3. **畸形**：非 JSON 串 / JSON 数组 / ``null`` 三种都回该入口默认且不抛。
4. **内层非法值**：``aget_json_setting`` **只保证外层是 dict**
   （``system/settings_service.py:139-153``）⇒ 值域外 / 非字符串 / ``null`` 一律回落。
   ⭐ 回落落点是 :func:`_default_for`（该入口的声明默认值），⛔ **不再硬回旧链** ——
   否则一次设置抖动或一个拼错的值就把流量静默送回**已退役**的 process。
5. **未知 entry**：``aresolve_entry_process_type("cron")`` 回旧链且不抛（唯一保留旧链的
   分支：它不是入口、没有声明默认值，且不构成「某个入口的默认」）。
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


def test_default_switch_is_all_blueprint() -> None:
    """⭐ 默认四键全 ``technical_blueprint``（同步点 2 收尾翻的就是这四行）。

    翻默认的前提是 G1 / G3 / G4 三道消费方接缝与终态映射都已修正 —— 先翻就等于把它们
    直接暴露给第一次真实请求。⛔ 旧链**不再是任何入口的默认**（退役收口的行为面判据）。
    """
    assert set(DEFAULT_ENTRY_SWITCH) == set(ENTRY_KEYS)
    assert set(DEFAULT_ENTRY_SWITCH.values()) == {PROCESS_TECHNICAL_BLUEPRINT}
    assert PROCESS_TECHNICAL_PLAN not in DEFAULT_ENTRY_SWITCH.values()


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
@pytest.mark.parametrize("entry", list(ENTRY_KEYS))
async def test_unconfigured_entry_now_resolves_to_the_blueprint_chain(entry: str) -> None:
    """不配置 = 走蓝图链（四个入口逐一参数化）。"""
    assert await aresolve_entry_process_type(entry) == PROCESS_TECHNICAL_BLUEPRINT


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_per_entry_rollback_only_affects_the_configured_entry() -> None:
    """⭐ **运维单入口回滚**：把 mcp 显式置回旧链，其余三个必须仍在蓝图链。

    这是翻默认之后开关最重要的一向 —— 「回滚是改一个设置值而不是回滚一次发布」这条
    承诺就落在这条用例上。同时它仍在守「⛔ 不从 ``session.entrypoint`` 反推」：MCP 入口
    记的 ``entrypoint`` 实测是 ``"workflow"``，反推会让改 workflow 键把 MCP 一起带走。
    """
    await _asave(json.dumps({"mcp": PROCESS_TECHNICAL_PLAN}))

    assert await aresolve_entry_process_type("mcp") == PROCESS_TECHNICAL_PLAN
    for entry in ("workflow", "chat", "feature_list"):
        assert await aresolve_entry_process_type(entry) == PROCESS_TECHNICAL_BLUEPRINT


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_per_entry_explicit_blueprint_matches_the_default() -> None:
    """反向并列：显式置成蓝图 == 默认值，且不影响其余三个入口。"""
    await _asave(json.dumps({"mcp": PROCESS_TECHNICAL_BLUEPRINT}))

    for entry in ENTRY_KEYS:
        assert await aresolve_entry_process_type(entry) == PROCESS_TECHNICAL_BLUEPRINT


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_rollback_is_per_entry_not_global() -> None:
    """⭐ 只回滚两个入口 ⇒ 另两个原地不动（两向在**同一份配置**里并列）。"""
    await _asave(json.dumps({"workflow": PROCESS_TECHNICAL_PLAN, "chat": PROCESS_TECHNICAL_PLAN}))

    assert await aresolve_entry_process_type("workflow") == PROCESS_TECHNICAL_PLAN
    assert await aresolve_entry_process_type("chat") == PROCESS_TECHNICAL_PLAN
    assert await aresolve_entry_process_type("mcp") == PROCESS_TECHNICAL_BLUEPRINT
    assert await aresolve_entry_process_type("feature_list") == PROCESS_TECHNICAL_BLUEPRINT


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_an_absent_key_is_silent_not_an_invalid_value_event(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """⭐ 「该键缺席」是**正常态**，⛔ 不得落 ``invalid_value`` 事件。

    ``aget_json_setting`` 原样回落库的 dict、**不与默认合并** ⇒ 运维只写要 override 的那
    一两个键（正常做法）时，其余入口在解析里读到的就是「没有这个键」。若把它当非法值处理，
    每一次未配置入口的编排都会刷一条 warning —— 把绝大多数正常请求渲染成异常。

    ⚠️ 与下一条**并列**：真正写了非法值时事件必须落，否则运维手滑就再也没有信号。
    """
    from services.process_runtime import blueprint_entry_switch as module

    events: list[str] = []
    monkeypatch.setattr(module, "_safe_log", lambda event, **_: events.append(event))

    await _asave(json.dumps({"mcp": PROCESS_TECHNICAL_PLAN}))

    assert await aresolve_entry_process_type("workflow") == PROCESS_TECHNICAL_BLUEPRINT
    assert events == [], f"未配置的键不该产生事件，实际：{events}"


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_an_illegal_value_does_emit_the_invalid_value_event(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """反面并列：写了值域外的值 ⇒ 事件必须落（运维手滑要有信号）。"""
    from services.process_runtime import blueprint_entry_switch as module

    events: list[str] = []
    monkeypatch.setattr(module, "_safe_log", lambda event, **_: events.append(event))

    await _asave(json.dumps({"workflow": "blueprint"}))

    assert await aresolve_entry_process_type("workflow") == PROCESS_TECHNICAL_BLUEPRINT
    assert events == ["blueprint_entry_switch_invalid_value"]


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
@pytest.mark.parametrize("raw", ["not-json-at-all", "[1, 2, 3]", "null", '"a string"'])
async def test_malformed_setting_falls_back_without_raising(raw: str) -> None:
    """⭐ 畸形整段 ⇒ 回**该入口的声明默认值**，⛔ 不是硬回旧链。

    硬回旧链会让一次设置抖动把流量静默送进已退役的 process —— 而降级路径恰恰最少
    被人盯着。回滚必须是**显式且合法**的值，不能靠「敲错了正好回退」。
    """
    await _asave(raw)
    assert await aresolve_entry_process_type("workflow") == PROCESS_TECHNICAL_BLUEPRINT


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
@pytest.mark.parametrize("value", ["blueprint", "", 123, None, True, {"nested": 1}])
async def test_inner_illegal_value_falls_back_to_the_entry_default(value: object) -> None:
    """⚠️ ``aget_json_setting`` 只保证**外层**是 dict ⇒ 内层必须逐键强转 + 值域校验。

    ⭐ 回落落点同上：该入口的声明默认值。注意 ``"blueprint"``（少了 ``technical_`` 前缀）
    这一档 —— 它是最真实的运维手滑形态，回落到默认比「碰巧回退」正确。
    """
    await _asave(json.dumps({"workflow": value}))
    assert await aresolve_entry_process_type("workflow") == PROCESS_TECHNICAL_BLUEPRINT


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
@pytest.mark.parametrize("entry", ["cron", "", "WORKFLOW", "webhook"])
async def test_unknown_entry_falls_back_to_the_old_chain(entry: str) -> None:
    """⭐ 唯一保留旧链的分支：未知 entry 不是入口，没有声明默认值。

    生产不可达（``ast`` 扫描强制字面量常量），走到这里意味着调用方有 bug。它**不构成
    「某个入口的默认」**，与退役这条不冲突；把一个身份不明的调用方送进需要
    ``project_id`` 的蓝图链只会换一种失败形态。
    """
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
