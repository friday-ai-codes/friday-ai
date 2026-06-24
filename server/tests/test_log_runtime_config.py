"""运行时日志配置 + 分类/采样测试（LOG-05 / LOG-06）。

覆盖：
- Task 1（LOG-06）：``SettingKeys.LOG_*`` + ``settings_service`` json/float helper；
  改 ``log.level`` 经 signal 即时调整过滤级别（无需重启，capfd 断言）；
  ``_resolve_structlog_level`` 读 DB 优先、env 回退；settings 写时缓存失效。
- Task 2（LOG-05）：``annotate_category_component`` 兜底 category/component；
  ``log_sink`` 采样（首 N 全记 + 比例；caller 全记不采样）；落库行带 category/component。

断言策略：用 ``configure_structlog()`` + ``capfd`` 捕获 stdout（JSON / Console 容错），
或直接断言 processor 返回 dict / ``SystemLogEntry`` 落库行字段。
"""

from __future__ import annotations

from typing import Any

import pytest
import structlog
from django.core.cache import cache

from common.logging import (
    annotate_category_component,
    bound_logger,
    configure_structlog,
)
from system import log_sink
from system.models import SettingKeys, SystemLogEntry, SystemSetting
from system.settings_service import (
    _cache_key,
    get_float_setting,
    get_json_setting,
    get_setting,
)

_LOG_KEYS = [
    SettingKeys.LOG_LEVEL,
    SettingKeys.LOG_COMPONENT_LEVELS,
    SettingKeys.LOG_STACK_THRESHOLD,
    SettingKeys.LOG_SAMPLING_INITIAL,
    SettingKeys.LOG_SAMPLING_RATE,
    SettingKeys.LOG_RETENTION_DAYS,
    SettingKeys.LOG_RETENTION_SIZE,
]


def _clear_log_caches() -> None:
    for key in _LOG_KEYS:
        try:
            cache.delete(_cache_key(key))
        except Exception:  # noqa: BLE001
            pass


@pytest.fixture(autouse=True)
def _isolate() -> Any:
    """隔离：清 LOG_* 缓存 + contextvars + sink；teardown 复位过滤级别防污染后续测试。"""
    _clear_log_caches()
    structlog.contextvars.clear_contextvars()
    log_sink._reset_for_tests()
    yield
    _clear_log_caches()
    structlog.contextvars.clear_contextvars()
    log_sink._reset_for_tests()
    # 热更新测试可能把 wrapper 调到 WARNING/DEBUG；复位为默认（DB 已回滚、缓存已清 → env/INFO）。
    configure_structlog()


def _save_setting(key: str, value: str) -> None:
    """写设置并触发 post_save signal（用 instance.save()，非 queryset.update()）。"""
    obj, created = SystemSetting.objects.get_or_create(key=key, defaults={"value": value})
    if not created:
        obj.value = value
        obj.save()


# === Task 1（LOG-06）：运行时配置 + 热更新级别 ===


@pytest.mark.django_db
def test_log_level_hot_reload_via_signal(capfd: Any) -> None:
    """改 log.level=DEBUG 经 signal 即时放开 debug；改回 WARNING 即时收紧（无需重启）。"""
    configure_structlog()

    _save_setting(SettingKeys.LOG_LEVEL, "DEBUG")  # signal → apply_log_level()
    structlog.get_logger("system.hot_reload_test").debug("hot_debug_evt")
    out = capfd.readouterr()
    assert "hot_debug_evt" in (out.out + out.err)

    _save_setting(SettingKeys.LOG_LEVEL, "WARNING")  # signal → 即时收紧
    structlog.get_logger("system.hot_reload_test").debug("hidden_debug_evt")
    out2 = capfd.readouterr()
    assert "hidden_debug_evt" not in (out2.out + out2.err)


@pytest.mark.django_db
def test_component_level_filter_via_signal(capfd: Any) -> None:
    """LOG_COMPONENT_LEVELS={"noisy_component":"ERROR"}：经 signal 即时生效——
    noisy_component 的 INFO 被丢弃、其它 component 的 INFO 放行；noisy 的 ERROR 仍放行。"""
    configure_structlog()
    # signal → 失效缓存 → 下一条事件即读到新 map（无需重启/reconfigure）。
    _save_setting(SettingKeys.LOG_COMPONENT_LEVELS, '{"noisy_component": "ERROR"}')

    log = structlog.get_logger("component_filter_test")
    log.bind(component="noisy_component").info("noisy_info_evt")
    log.bind(component="quiet_component").info("quiet_info_evt")
    out = capfd.readouterr()
    combined = out.out + out.err
    assert "noisy_info_evt" not in combined  # noisy INFO < ERROR → 丢弃
    assert "quiet_info_evt" in combined  # 未配置 component → 回退全局放行

    # noisy_component 达到阈值（ERROR）仍放行。
    log.bind(component="noisy_component").error("noisy_error_evt")
    out2 = capfd.readouterr()
    assert "noisy_error_evt" in (out2.out + out2.err)


@pytest.mark.django_db
def test_stack_threshold_gate_via_signal(capfd: Any) -> None:
    """LOG_STACK_THRESHOLD=ERROR：经 signal 即时生效——WARNING 事件剥除 stack/exc，
    ERROR 事件保留异常 traceback（无需重启/reconfigure）。"""
    configure_structlog()
    _save_setting(SettingKeys.LOG_STACK_THRESHOLD, "ERROR")

    log = structlog.get_logger("system.stack_threshold_test")

    try:
        raise ValueError("boom_marker_xyz")
    except ValueError:
        log.warning("warn_with_exc", exc_info=True)
    out = capfd.readouterr()
    combined = out.out + out.err
    assert "warn_with_exc" in combined
    assert "boom_marker_xyz" not in combined  # WARNING < ERROR → 异常/堆栈被剥除

    try:
        raise ValueError("boom_marker_xyz")
    except ValueError:
        log.error("error_with_exc", exc_info=True)
    out2 = capfd.readouterr()
    combined2 = out2.out + out2.err
    assert "error_with_exc" in combined2
    assert "boom_marker_xyz" in combined2  # ERROR >= ERROR → 保留异常信息


@pytest.mark.django_db
def test_resolve_level_prefers_db_over_env(monkeypatch: Any) -> None:
    """_resolve_structlog_level 读 DB 优先；DB 空回退 env。"""
    import logging

    from common.logging import _resolve_structlog_level

    monkeypatch.setenv("FRIDAY_STRUCTLOG_LEVEL", "DEBUG")
    # DB 空 → 回退 env=DEBUG
    assert _resolve_structlog_level() == logging.DEBUG
    # DB 设 ERROR → DB 优先
    _save_setting(SettingKeys.LOG_LEVEL, "ERROR")
    assert _resolve_structlog_level() == logging.ERROR


@pytest.mark.django_db
def test_get_json_setting_parses_and_falls_back() -> None:
    _save_setting(SettingKeys.LOG_COMPONENT_LEVELS, '{"rag": "DEBUG", "indexing": "WARNING"}')
    assert get_json_setting(SettingKeys.LOG_COMPONENT_LEVELS) == {
        "rag": "DEBUG",
        "indexing": "WARNING",
    }
    # 非法 JSON → 回默认
    _save_setting(SettingKeys.LOG_COMPONENT_LEVELS, "not-json{")
    assert get_json_setting(SettingKeys.LOG_COMPONENT_LEVELS, {"x": "INFO"}) == {"x": "INFO"}
    # 非 dict（JSON 数组）→ 回默认
    _save_setting(SettingKeys.LOG_COMPONENT_LEVELS, "[1, 2]")
    assert get_json_setting(SettingKeys.LOG_COMPONENT_LEVELS) == {}


@pytest.mark.django_db
def test_get_float_setting_parses_and_falls_back() -> None:
    _save_setting(SettingKeys.LOG_SAMPLING_RATE, "0.25")
    assert get_float_setting(SettingKeys.LOG_SAMPLING_RATE) == 0.25
    _save_setting(SettingKeys.LOG_SAMPLING_RATE, "abc")
    assert get_float_setting(SettingKeys.LOG_SAMPLING_RATE, 0.7) == 0.7


@pytest.mark.django_db
def test_setting_cache_invalidated_on_write() -> None:
    """与 _invalidate_setting_cache 协同：写后下次读到新值。"""
    assert get_setting(SettingKeys.LOG_LEVEL, "") == ""  # 缓存 __none__
    _save_setting(SettingKeys.LOG_LEVEL, "ERROR")  # signal 失效缓存
    assert get_setting(SettingKeys.LOG_LEVEL) == "ERROR"


# === Task 2（LOG-05）：category / component 推断 ===


def test_annotate_defaults_sampling_and_infers_component() -> None:
    ev = annotate_category_component(None, "info", {"event": "x", "logger": "system.signals"})
    assert ev["category"] == "sampling"
    assert ev["component"] == "system"


def test_annotate_keeps_explicit_caller_and_component() -> None:
    ev = annotate_category_component(
        None,
        "info",
        {"event": "x", "category": "caller", "component": "mcp", "logger": "whatever"},
    )
    assert ev["category"] == "caller"
    assert ev["component"] == "mcp"


def test_annotate_unknown_logger_leaves_component_empty() -> None:
    ev = annotate_category_component(None, "info", {"event": "x", "logger": "random_thing.sub"})
    assert ev.get("component", "") == ""
    assert ev["category"] == "sampling"


@pytest.mark.django_db
def test_bound_logger_infers_and_overrides_component(capfd: Any) -> None:
    configure_structlog()
    # 首段命中 §5 清单 → 推断 component=workflows
    bound_logger("workflows.engine.scheduler").warning("bl_infer_evt")
    out = capfd.readouterr()
    assert "bl_infer_evt" in (out.out + out.err)
    assert "workflows" in (out.out + out.err)

    # 显式覆盖（logger 首段不在清单，annotate 推不出 → component 必来自 bound_logger）
    bound_logger("anything_unknown", component="rag").warning("bl_override_evt")
    out2 = capfd.readouterr()
    assert "bl_override_evt" in (out2.out + out2.err)
    assert "rag" in (out2.out + out2.err)


# === Task 2（LOG-05）：采样行为 ===


@pytest.mark.django_db
def test_sampling_initial_then_dropped() -> None:
    """LOG_SAMPLING_INITIAL=2 + RATE=0：同 (component,event) 前 2 条入队、第 3 条采样丢弃。"""
    log_sink._reset_for_tests()
    _save_setting(SettingKeys.LOG_SAMPLING_INITIAL, "2")
    _save_setting(SettingKeys.LOG_SAMPLING_RATE, "0")

    for _ in range(3):
        log_sink.enqueue_system_log(
            {"event": "loop_step", "component": "rag", "category": "sampling"}
        )
    counters = log_sink.snapshot_counters()
    assert counters["enqueued"] == 2
    assert counters["sampled_out"] == 1
    assert counters["dropped"] == 0  # 采样丢弃不计入队列满 dropped


@pytest.mark.django_db
def test_caller_never_sampled() -> None:
    """category=caller 不受采样影响全量入队（即便 INITIAL=0 + RATE=0）。"""
    log_sink._reset_for_tests()
    _save_setting(SettingKeys.LOG_SAMPLING_INITIAL, "0")
    _save_setting(SettingKeys.LOG_SAMPLING_RATE, "0")

    for _ in range(5):
        log_sink.enqueue_system_log(
            {"event": "user_call", "component": "mcp", "category": "caller"}
        )
    counters = log_sink.snapshot_counters()
    assert counters["enqueued"] == 5
    assert counters["sampled_out"] == 0


@pytest.mark.django_db
def test_emitted_log_carries_category_component(capfd: Any) -> None:
    """capfd：bound_logger 携 component + annotate 兜底 category 进渲染输出。"""
    configure_structlog()
    # bound_logger 显式 bind component（地基 helper，存量渐进迁移的统一入口）；
    # category 由 annotate processor 兜底为 sampling。
    bound_logger("system.emit_test").warning("emit_evt")
    raw = capfd.readouterr()
    output = raw.out + raw.err
    assert "emit_evt" in output
    assert "category" in output and "sampling" in output
    assert "component" in output and "system" in output


@pytest.mark.django_db
def test_persisted_entry_has_category_component() -> None:
    """落库行带 component/category（bound_logger bind + annotate 兜底 + fan-out 落库）。"""
    log_sink._reset_for_tests()
    configure_structlog()
    bound_logger("system.persist_test").warning("persist_evt")
    log_sink.flush_now()

    entry = SystemLogEntry.objects.filter(event="persist_evt").first()
    assert entry is not None
    assert entry.category == "sampling"
    assert entry.component == "system"
