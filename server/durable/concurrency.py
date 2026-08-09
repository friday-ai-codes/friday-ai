"""并发治理：索引/图谱的 Procrastinate 原生 `lock` 槽位锁池（CONC-01）。

按资源分治引入可配置并发上限——索引/图谱 job 入队时带
``lock=index-slot-{slot}`` / ``graph-slot-{slot}``，其中
``slot = stable_hash(repo_id) % N``，N 从 ``SystemSetting`` 实时读取
（``CONCURRENCY_INDEX_MAX`` 默认 5 / ``CONCURRENCY_GRAPH_MAX`` 默认 3）。

设计要点（见 .planning/STATE.md CONC 决策）：

- Procrastinate 原生 ``lock`` 控制 **doing** 并发（同 lock 串行），与
  ``queueing_lock``（= ``idempotency_key``，控 **todo** 去重）正交并存。
- N 个 slot → 至多 N 个索引并发；超限 job 原生留 ``todo`` 排队、worker
  自动跳过、零空转，**不与 KEDA ``todo`` 深度伸缩形成空转扩容反馈环**。
- **稳定 hash**：用 ``hashlib``（非内置 ``hash()``，后者受 ``PYTHONHASHSEED``
  影响逐进程变化），保证同一 ``repo_id`` 跨进程/副本恒定映射到同一 slot →
  同仓天然串行，防重复索引。
- N<=0 防御：clamp 到 1（至少一个 slot，退化为该类全局串行，绝不除零）。

本模块顶层只放 stdlib 导入（对齐 durable.service 的循环 import 约束）；
``SystemSetting`` 读取一律放函数体内局部 import。
"""

from __future__ import annotations

import hashlib

# 槽位上限默认值（无 SystemSetting 配置时生效，开箱即用）
DEFAULT_INDEX_CONCURRENCY = 5
DEFAULT_GRAPH_CONCURRENCY = 3
DEFAULT_SUMMARY_CONCURRENCY = 8
DEFAULT_FEATURE_PARSE_CONCURRENCY = 4
DEFAULT_SCAN_CONCURRENCY = 2

_INDEX_SLOT_PREFIX = "index-slot-"
_GRAPH_SLOT_PREFIX = "graph-slot-"
_SUMMARY_SLOT_PREFIX = "summary-slot-"
_FEATURE_PARSE_SLOT_PREFIX = "featparse-slot-"
_SCAN_SLOT_PREFIX = "scan-slot-"


def _stable_slot(repo_id: str, n: int) -> int:
    """跨进程稳定的 slot 序号：``stable_hash(repo_id) % max(n, 1)``。

    用 md5（仅作非加密的稳定散列）而非内置 ``hash()``——后者受
    ``PYTHONHASHSEED`` 影响逐进程不同，会破坏「同仓恒定同槽串行」不变式。
    """
    clamped = n if n and n > 0 else 1
    digest = hashlib.md5(str(repo_id).encode("utf-8")).hexdigest()
    return int(digest, 16) % clamped


def index_slot_lock(repo_id: str, n: int) -> str:
    """计算索引槽位 lock 值：``index-slot-{stable_hash(repo_id) % N}``。"""
    return f"{_INDEX_SLOT_PREFIX}{_stable_slot(repo_id, n)}"


def graph_slot_lock(repo_id: str, n: int) -> str:
    """计算图谱槽位 lock 值：``graph-slot-{stable_hash(repo_id) % N}``。"""
    return f"{_GRAPH_SLOT_PREFIX}{_stable_slot(repo_id, n)}"


def summary_slot_lock(repo_id: str, n: int) -> str:
    """计算 repo_summary 派发槽位 lock 值：``summary-slot-{stable_hash(repo_id) % N}``。"""
    return f"{_SUMMARY_SLOT_PREFIX}{_stable_slot(repo_id, n)}"


def feature_parse_slot_lock(key: str, n: int) -> str:
    """计算 feature list 逐模块解析槽位 lock 值：``featparse-slot-{stable_hash(key) % N}``。

    ``key`` 取 ``{draft_id}:{module_index}`` 稳定映射到某个槽位——全局至多 N 个模块并发
    打 LLM，超限者原生留 todo 排队、worker 自动跳过（与 index/graph 槽位池同构）。
    """
    return f"{_FEATURE_PARSE_SLOT_PREFIX}{_stable_slot(key, n)}"


def scan_slot_lock(repo_id: str, n: int) -> str:
    """计算 Semgrep 扫描槽位 lock 值：``scan-slot-{stable_hash(repo_id) % N}``。"""
    return f"{_SCAN_SLOT_PREFIX}{_stable_slot(repo_id, n)}"


def _read_int_setting_sync(key: str, default: int) -> int:
    """同步读取整型 SystemSetting，缺失/非法回退 default（clamp >=1）。"""
    from system.models import SystemSetting

    try:
        row = SystemSetting.objects.filter(key=key).values_list("value", flat=True).first()
    except Exception:
        return default
    return _coerce_positive_int(row, default)


async def _read_int_setting_async(key: str, default: int) -> int:
    """异步读取整型 SystemSetting，缺失/非法回退 default（clamp >=1）。"""
    from system.models import SystemSetting

    try:
        row = (
            await SystemSetting.objects.filter(key=key)
            .values_list("value", flat=True)
            .afirst()
        )
    except Exception:
        return default
    return _coerce_positive_int(row, default)


def _coerce_positive_int(raw: object, default: int) -> int:
    if raw is None:
        return default
    try:
        value = int(str(raw).strip())
    except (TypeError, ValueError):
        return default
    return value if value > 0 else default


def get_index_concurrency_sync() -> int:
    from system.models import SettingKeys

    return _read_int_setting_sync(SettingKeys.CONCURRENCY_INDEX_MAX, DEFAULT_INDEX_CONCURRENCY)


def get_graph_concurrency_sync() -> int:
    from system.models import SettingKeys

    return _read_int_setting_sync(SettingKeys.CONCURRENCY_GRAPH_MAX, DEFAULT_GRAPH_CONCURRENCY)


async def aget_index_concurrency() -> int:
    from system.models import SettingKeys

    return await _read_int_setting_async(
        SettingKeys.CONCURRENCY_INDEX_MAX, DEFAULT_INDEX_CONCURRENCY
    )


async def aget_graph_concurrency() -> int:
    from system.models import SettingKeys

    return await _read_int_setting_async(
        SettingKeys.CONCURRENCY_GRAPH_MAX, DEFAULT_GRAPH_CONCURRENCY
    )


async def aget_summary_concurrency() -> int:
    from system.models import SettingKeys

    return await _read_int_setting_async(
        SettingKeys.CONCURRENCY_SUMMARY_MAX, DEFAULT_SUMMARY_CONCURRENCY
    )


async def aget_feature_parse_concurrency() -> int:
    from system.models import SettingKeys

    return await _read_int_setting_async(
        SettingKeys.CONCURRENCY_FEATURE_PARSE_MAX, DEFAULT_FEATURE_PARSE_CONCURRENCY
    )


async def aget_scan_concurrency() -> int:
    from system.models import SettingKeys

    return await _read_int_setting_async(
        SettingKeys.CONCURRENCY_SCAN_MAX, DEFAULT_SCAN_CONCURRENCY
    )


async def afeature_parse_lock(key: str) -> str:
    """读取 N 并返回该模块的 feature list 解析槽位 lock（async 入队点用）。"""
    return feature_parse_slot_lock(key, await aget_feature_parse_concurrency())


async def asummary_lock(repo_id: str) -> str:
    """读取 N 并返回该仓库的 repo_summary 派发槽位 lock（async 入队点用）。"""
    return summary_slot_lock(repo_id, await aget_summary_concurrency())


async def aindex_lock(repo_id: str) -> str:
    """读取 N 并返回该仓库的索引槽位 lock（async 入队点用）。"""
    return index_slot_lock(repo_id, await aget_index_concurrency())


async def agraph_lock(repo_id: str) -> str:
    """读取 N 并返回该仓库的图谱槽位 lock（async 入队点用）。"""
    return graph_slot_lock(repo_id, await aget_graph_concurrency())


async def ascan_lock(repo_id: str) -> str:
    """读取 N 并返回该仓库的 Semgrep 扫描槽位 lock（async 入队点用）。"""
    return scan_slot_lock(repo_id, await aget_scan_concurrency())


def index_lock_sync(repo_id: str) -> str:
    """同步路径的索引槽位 lock。"""
    return index_slot_lock(repo_id, get_index_concurrency_sync())


def graph_lock_sync(repo_id: str) -> str:
    """同步路径的图谱槽位 lock。"""
    return graph_slot_lock(repo_id, get_graph_concurrency_sync())


__all__ = [
    "DEFAULT_INDEX_CONCURRENCY",
    "DEFAULT_GRAPH_CONCURRENCY",
    "DEFAULT_SUMMARY_CONCURRENCY",
    "DEFAULT_FEATURE_PARSE_CONCURRENCY",
    "DEFAULT_SCAN_CONCURRENCY",
    "index_slot_lock",
    "graph_slot_lock",
    "summary_slot_lock",
    "feature_parse_slot_lock",
    "scan_slot_lock",
    "get_index_concurrency_sync",
    "get_graph_concurrency_sync",
    "aget_index_concurrency",
    "aget_graph_concurrency",
    "aget_summary_concurrency",
    "aget_feature_parse_concurrency",
    "aget_scan_concurrency",
    "aindex_lock",
    "agraph_lock",
    "asummary_lock",
    "afeature_parse_lock",
    "ascan_lock",
    "index_lock_sync",
    "graph_lock_sync",
]
