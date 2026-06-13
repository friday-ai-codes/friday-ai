"""TRIG-02 trigger_type choices 契约测试（Phase 21 Wave 0 RED）。

D-02 裁定：移除 `schedule` 假触发类型（无 handler / 无画布节点 / 无 dispatch），
而非实现原生定时调度。本文件锁死「choices 不含 schedule、保留 manual/webhook/event」。

注意：`test_trigger_type_choices_exclude_schedule` 在 21-03 移除枚举前预期为 RED
（当前 Workflow.TriggerType 仍含 SCHEDULE）。转绿计划：21-03。
"""

from workflows.models import Workflow


def _choice_values() -> list[str]:
    return [c[0] for c in Workflow.TriggerType.choices]


def test_trigger_type_choices_exclude_schedule():
    """TRIG-02：移除 schedule 后，choices 不应再包含 'schedule'（修复前 RED）。"""
    assert "schedule" not in _choice_values()


def test_trigger_type_choices_keep_others():
    """TRIG-02：manual / webhook / event 仍须保留在 choices 中（回归保护）。"""
    values = _choice_values()
    assert "manual" in values
    assert "webhook" in values
    assert "event" in values
