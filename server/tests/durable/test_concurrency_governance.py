"""并发治理设计契约守护（CONC-01/02/03）。

锁定「按资源分治、不设全局总上限」的设计不变式：
- 索引/图谱：durable defer 支持 Procrastinate 原生 lock（槽位锁池，跨进程）。
- LLM：ProviderCredential.max_concurrency 凭证级（默认 50）。
- 容器：runner.concurrent（DB 持久化 + Go scheduler 信号量）。
- MCP：不限。
- 不存在全局总并发上限设置项。
"""

from __future__ import annotations

import inspect


def test_durable_defer_supports_lock_passthrough() -> None:
    """CONC-01：DurableTaskService.defer / 后端 defer 均含 lock 参数（doing 并发槽）。"""
    from durable.backends import InProcessBackend, ProcrastinateBackend
    from durable.service import DurableTaskService

    for fn in (DurableTaskService.defer, ProcrastinateBackend.defer, InProcessBackend.defer):
        sig = inspect.signature(fn)
        assert "lock" in sig.parameters, f"{fn.__qualname__} 缺 lock 参数（CONC-01 槽位锁池）"


def test_concurrency_setting_keys_exist() -> None:
    """CONC-01：索引/图谱并发上限设置键存在。"""
    from system.models import SettingKeys

    assert SettingKeys.CONCURRENCY_INDEX_MAX == "concurrency_index_max"
    assert SettingKeys.CONCURRENCY_GRAPH_MAX == "concurrency_graph_max"


def test_provider_credential_has_max_concurrency_field() -> None:
    """CONC-02：凭证级 LLM 并发上限字段存在，默认 50。"""
    from system.models import ProviderCredential

    field = ProviderCredential._meta.get_field("max_concurrency")
    assert field.default == 50


def test_runner_has_container_concurrency_field() -> None:
    """CONC-03：容器并发经 Runner.concurrent（DB 持久化 + Go scheduler 信号量约束）。"""
    from runners.models import Runner

    assert Runner._meta.get_field("concurrent") is not None


def test_no_global_total_concurrency_cap_setting() -> None:
    """CONC-03：明确不设「所有任务总并发」全局硬上限——无对应设置键。"""
    from system.models import SettingKeys

    keys = {
        v
        for k, v in vars(SettingKeys).items()
        if not k.startswith("_") and isinstance(v, str)
    }
    forbidden_substrings = ("global_concurrency", "total_concurrency", "max_total_concurrency")
    offending = {key for key in keys for sub in forbidden_substrings if sub in key}
    assert not offending, f"不应存在全局总并发上限设置键：{offending}"
