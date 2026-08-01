"""旧 ``technical_plan`` process 的退役收口守卫（同步点 2 收尾 · 第三步）。

**退役在本仓的定义**（⛔ 三条缺一不可，任何一条被破坏都不算退役）：

1. **不再是任何入口的默认** —— ``DEFAULT_ENTRY_SWITCH`` 四键无它；
2. **注册仍在，且写明了为什么还在** —— 在途会话续驱与显式回滚 override 都要它；
   注销即崩，且回滚路径会一起断。
3. **状态是程序可查的**，不是只写在注释里 —— 落在 ``ProcessDefinition.config``。

⛔ **退役 ≠ 删除**：六个 technical_plan 冻结文件（``decompose_segments`` /
``research_adapter`` / ``architect_merge_adapter`` / ``merged_plan`` /
``clarify_adapter`` / ``render``）一行不改，本文件另有一条源码级断言守住这一点。
"""

from __future__ import annotations

from pathlib import Path

import pytest

_SERVER_DIR = Path(__file__).resolve().parents[3]

# 六个冻结文件（审计 §4.1 与本次任务硬约束 1 逐字点名）。
_FROZEN_TECHNICAL_PLAN_FILES = (
    "services/process_runtime/decompose_segments.py",
    "services/process_runtime/research_adapter.py",
    "services/process_runtime/architect_merge_adapter.py",
    "services/process_runtime/merged_plan.py",
    "services/process_runtime/clarify_adapter.py",
    "services/process_runtime/render.py",
)


# ═══════════════════════════════════════════════════════════════════════════
# 1. 退役标记本身
# ═══════════════════════════════════════════════════════════════════════════


def test_old_process_is_marked_retired_in_its_registration() -> None:
    """⭐ 注册面：``get_process_definition("technical_plan").config`` 说得出「我退役了」。

    「可查」是本条的要害：写在注释里的退役状态对任何程序、任何看板、任何下一个接手的
    人都不可见。落在 ``config``（既有字段，零迁移）之后，它是数据。
    """
    from services.process_runtime.registry import get_process_definition

    definition = get_process_definition("technical_plan")
    assert definition is not None, "⛔ 退役 ≠ 注销：注册被摘掉会让在途会话续驱直接崩"

    config = definition.config
    assert config.get("retired") is True
    assert config.get("successor") == "technical_blueprint"
    assert config.get("retired_in") == "v0.20.0"
    # 「为什么还留着」必须写进数据，避免下一个人当成残留顺手清理。
    assert config.get("retained_reason")
    # 残余流量的观察口径也在数据里（116-01 落的埋点）。
    assert config.get("residual_traffic_event") == "technical_plan_entry_used"


def test_the_successor_is_registered_and_not_retired() -> None:
    """反面对照：继任者已注册且**没有**退役标记（证明这个标记不是人人都有的装饰）。"""
    from services.process_runtime.registry import get_process_definition

    successor = get_process_definition("technical_blueprint")
    assert successor is not None
    assert successor.config.get("retired") is not True


# ═══════════════════════════════════════════════════════════════════════════
# 2. 退役的行为面：不再是任何入口的默认
# ═══════════════════════════════════════════════════════════════════════════


def test_no_entry_defaults_to_the_retired_process() -> None:
    """⭐ 退役与翻默认是**同一件事的两面**，这条把它们钉在一起。

    只有注册面的标记而默认没翻，等于挂了个牌子说退役、流量照旧全走它；只翻默认而不标
    退役，则下一个人看不出这条链的处境。两条必须同时成立。
    """
    from services.process_runtime.blueprint_entry_switch import (
        DEFAULT_ENTRY_SWITCH,
        ENTRY_KEYS,
        PROCESS_TECHNICAL_PLAN,
    )
    from services.process_runtime.registry import get_process_definition

    retired = {
        ptype
        for ptype in ("technical_plan", "technical_blueprint", "echo")
        if (get_process_definition(ptype) or None) is not None
        and (get_process_definition(ptype).config or {}).get("retired") is True  # type: ignore[union-attr]
    }
    assert retired == {"technical_plan"}

    defaults = {DEFAULT_ENTRY_SWITCH[entry] for entry in ENTRY_KEYS}
    assert not (defaults & retired), f"⛔ 仍有入口以已退役的 process 为默认：{defaults & retired}"
    assert PROCESS_TECHNICAL_PLAN in retired


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_residual_traffic_is_an_explicit_override_not_a_default() -> None:
    """⭐ 「残余流量是 override 而不是默认」这句话的**可执行**形态。

    不配置 ⇒ 四个入口一个都不落到旧链；显式写 ``technical_plan`` 才落 —— 那正是
    「override」的定义。
    """
    import json

    from asgiref.sync import sync_to_async
    from django.core.cache import cache

    from services.process_runtime.blueprint_entry_switch import (
        ENTRY_KEYS,
        PROCESS_TECHNICAL_PLAN,
        aresolve_entry_process_type,
    )
    from system.models import SettingKeys, SystemSetting
    from system.settings_service import _cache_key

    def _clear() -> None:
        SystemSetting.objects.filter(key=SettingKeys.BLUEPRINT_ENTRY_SWITCH).delete()
        cache.delete(_cache_key(SettingKeys.BLUEPRINT_ENTRY_SWITCH))

    def _save(value: str) -> None:
        SystemSetting.objects.update_or_create(
            key=SettingKeys.BLUEPRINT_ENTRY_SWITCH, defaults={"value": value}
        )

    await sync_to_async(_clear)()
    try:
        for entry in ENTRY_KEYS:
            assert await aresolve_entry_process_type(entry) != PROCESS_TECHNICAL_PLAN

        await sync_to_async(_save)(json.dumps({"chat": PROCESS_TECHNICAL_PLAN}))
        assert await aresolve_entry_process_type("chat") == PROCESS_TECHNICAL_PLAN
    finally:
        await sync_to_async(_clear)()


def test_the_retirement_flag_is_read_from_the_registry_not_recopied() -> None:
    """观测侧读的是注册表那一份标记（⛔ 不在 ``entrypoint.py`` 复制第二份）。

    复制一份的后果是它永远不会被更新 —— 将来真把旧链摘掉时，那条事件会一直报
    ``process_retired=True`` 或一直报 ``False``，两种都是错的。
    """
    from services.process_runtime.entrypoint import _technical_plan_retired

    src = (_SERVER_DIR / "services/process_runtime/entrypoint.py").read_text(encoding="utf-8")
    assert "get_process_definition" in src
    assert '"retired"' in src
    # ⛔ 本模块不得出现第二份「退役了」的硬编码结论。
    assert "retired = True" not in src
    assert _technical_plan_retired() is True


# ═══════════════════════════════════════════════════════════════════════════
# 3. 退役 ≠ 删除：六个冻结文件与在途会话
# ═══════════════════════════════════════════════════════════════════════════


@pytest.mark.parametrize("rel", list(_FROZEN_TECHNICAL_PLAN_FILES))
def test_frozen_technical_plan_files_still_exist(rel: str) -> None:
    """⭐ 六个冻结文件一个都不许消失：在途会话的 stage handler 全在它们里面。"""
    assert (_SERVER_DIR / rel).exists(), f"⛔ 冻结文件被删：{rel}（在途会话续驱即崩）"


def test_all_stage_handlers_of_the_retired_process_are_still_wired() -> None:
    """退役后 stage 图仍然完整：每个 stage 都有可调用的 handler。

    「注册还在但 handler 被摘空」是最坏的中间态 —— 在途会话不会报「未注册」，
    而是安静地空转到 ``advance_step_limit``。
    """
    from services.process_runtime.registry import get_process_definition

    definition = get_process_definition("technical_plan")
    assert definition is not None
    assert definition.initial_stage in definition.stages
    for key, stage in definition.stages.items():
        assert callable(stage.handler), f"stage {key} 的 handler 不可调用"
