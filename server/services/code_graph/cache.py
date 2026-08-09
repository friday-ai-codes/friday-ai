"""内存符号图的**存储层** —— 字节估算、字节预算 LRU 与进程内单例（Phase 121，GRAPH-03）。

问题背景
========
一张 10 万符号级的图冷建一次要 2 秒纯 CPU（20 万级约 4 秒，还不含 ORM 取数），
每个图分析工具各建一次是不可接受的；但把图无限缓存又会把 worker 打 OOM——本仓已有
的两套缓存先例都不按字节算（``codegraph/lsp/volar_pool.py`` 按**条目数**逐出、
``codegraph/galaxy/cache.py`` 按**文件**），而「4 个条目」在这里可以是 40MB 也可以
是 1GB。GRAPH-03 要的是「按字节预算逐出 + 进程不 OOM」，条目数管不住这件事。

方案（线性估算 + 字节预算 LRU）
================================
用 ``OrderedDict`` + ``threading.RLock`` 维护一个**按字节记账**的 LRU：命中
``move_to_end``，写入后循环 ``popitem(last=False)`` 直到总字节回到预算内。字节数不用
``sys.getsizeof`` 递归求——那对 networkx 既不准（漏共享引用）也慢（40 万对象要数秒）——
而用本相位实测标定的确定性线性模型 :func:`estimate_graph_bytes`，它在 10k→200k 节点
（20 倍跨度）上误差恒定，可以在**装配前**用 ``COUNT`` 当准入判据，避免「先 OOM 再逐出」。

边界
====
① **per-worker 纯内存，刻意不落盘**。图对象无法廉价序列化（``MultiDiGraph`` +
   十万级节点属性字典），而落盘会引入一致性的第二个事实源：磁盘上的图与 DB 水位何时
   算一致、谁来失效，都是新问题。多 worker 各持一份是**已知且接受**的代价，靠
   ``CODE_GRAPH_CACHE_MAX_BYTES`` 这条 per-worker 预算约束住上界（4 worker 最坏 4×）。

② **全同步，锁内绝不 await**（121-CONTEXT D-04 / RESEARCH Pitfall 7）。本模块的方法
   一律是同步方法，异步外壳由 Plan 121-08 用一次 ``sync_to_async`` 包在外面。「持锁」
   与「await」在物理上不可能重叠，是这条分层最省心的性质。

③ **锁原语一律 ``threading``，⛔ 不用 ``asyncio.Lock`` / ``asyncio.Event``**。本仓同时
   存在三类 event loop（ASGI 主循环、``services/background_runner.py`` 的常驻 daemon
   线程循环、workflow engine ``_run_in_thread`` 的每次执行独立循环），而
   :class:`GraphService` 是**进程级**单例、会被三者共用；``asyncio`` 原语绑定创建它的
   loop，跨 loop 使用直接 ``RuntimeError``（D-04 / Pitfall 8）。

④ **本模块只做存储侧**。签名复校、in-flight 闸门、single-flight、准入与降级全部是
   Plan 121-08 的编排职责；⛔ 本 plan 交付的部分**不 import** ``loader.py``，也**不
   import** ``signature.py``。
"""

from __future__ import annotations

import threading
from collections import OrderedDict
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Final

import structlog

from services.code_graph.model import CodeGraph

logger = structlog.get_logger(__name__)

# 事件名常量（形态对齐 ``loader.py`` / ``signature.py`` / ``codegraph/lsp/volar_pool.py``）。
# 🚨 前缀**不得缩写**：``graph_build_started/completed/failed`` 已被
# ``services/graph_builder.py`` 占用，``galaxy_cache_*`` 已被 ``codegraph/galaxy/cache.py``
# 占用；缩写会让两条完全不同的链路在日志里混成一摊。
# ⚠️ 常量必须直接写在 ``logger.*`` 的第一个位置实参上，⛔ 不得抽 ``_emit(event, **kw)``
# 转发器——``tests/services/code_graph/test_access.py::test_observability_contract`` 要求
# 事件名可静态解析，转发器只会让它看到一个形参名（Plan 121-04 实际被这条契约拦下过一次）。
_EVENT_CACHE_HIT: Final[str] = "code_graph_cache_hit"
_EVENT_CACHE_EVICTED: Final[str] = "code_graph_cache_evicted"
_EVENT_STALE_WATERMARK: Final[str] = "code_graph_stale_watermark"
_EVENT_BUILD_STARTED: Final[str] = "code_graph_build_started"
_EVENT_BUILD_COMPLETED: Final[str] = "code_graph_build_completed"
_EVENT_BUILD_FAILED: Final[str] = "code_graph_build_failed"

# =============================================================================
# 字节估算（实测标定）
# =============================================================================

# 标定自 networkx 3.6.1 / CPython 3.14 / ``MultiDiGraph`` / UUID 字符串节点键。
# 测量方式：tracemalloc 峰值增量；10k–200k 节点跨度上线性误差**恒为 −5%**（不是随
# 规模发散，这正是线性模型可用的最强证据），故常数已按 ×1.05 上调、自带 5% 安全裕度。
# 形态假设：节点 ≤5 个属性、边 ≤3 个属性；超出会**低估**——CPython 小字典预分配 8 槽，
# 1–3 个属性成本完全相同，第 4 个才跳一级（这是阶跃函数，不是线性的）。
# ⚠️ 两个常数必须在 Plan 121-10 的「最大仓实测」交付物中复校，并按 **RSS**（而非
# tracemalloc）修正：tracemalloc 计的是 Python 分配器请求的字节数，不含 arena 碎片与
# 解释器开销，真实 RSS 通常更高；比值显著 > 1 时需要再上调。
NODE_COST_BYTES: Final[int] = 640  # 实测 598 × 1.05 ≈ 630，取整到 640 更保守
EDGE_COST_BYTES: Final[int] = 560  # MultiDiGraph 实测约 515（3 属性）× 1.05 ≈ 540，取整到 560

# ⛔ 两个「优化」已被本仓实测**证伪**，别再花预算试：
#   - 字符串驻留 ``file_path``：只省 6.3MB / 4%，不值得为此加一层池化代码。
#   - 把 UUID 字符串节点键换成 int 索引：实测**反而多用 12.5MB**（158.64 vs 146.18MB）。
#     反直觉，但数据如此——不要在没有实测的情况下把它当优化做。


def estimate_graph_bytes(node_count: int, edge_count: int) -> int:
    """按线性模型估算一张图的常驻字节数。

    **纯函数**：不读 settings、不碰图对象、无副作用、无 I/O。这一点是刻意的，因为它
    要服务两个时机完全不同的场合：

    1. **装配前的准入判据** —— 用 ``Symbol.count()`` + ``CallEdge.count()`` 先估一把，
       超过 ``CODE_GRAPH_MAX_GRAPH_BYTES`` 就直接走降级路径，而不是把图装配出来、
       撑爆内存之后再逐出（「先 OOM 再逐出」根本救不回来）。
    2. **装配后的 LRU 记账** —— 用实际的 ``node_count`` / ``edge_count`` 重算，写进
       :attr:`~services.code_graph.model.GraphMeta.estimated_bytes` 与缓存条目。

    两处必须用**同一个**函数：各自复制一份常数必然漂移，届时准入放行的图会在 LRU 里
    被记成另一个数，预算就形同虚设。

    Args:
        node_count: 图的节点数，须 ≥ 0。
        edge_count: 图的边数，须 ≥ 0（``MultiDiGraph`` 下同一对节点的多条边各计一条）。

    Returns:
        估算字节数 ``node_count * NODE_COST_BYTES + edge_count * EDGE_COST_BYTES``。

    Raises:
        ValueError: 任一入参为负数。负计数只可能来自调用方的算术错误，静默取 0 会让
            一张大图被记成 0 字节、永远逐不出去。
    """
    if node_count < 0 or edge_count < 0:
        raise ValueError(
            f"节点数与边数必须 >= 0，收到 node_count={node_count} edge_count={edge_count}"
        )
    return node_count * NODE_COST_BYTES + edge_count * EDGE_COST_BYTES


# =============================================================================
# 字节预算 LRU
# =============================================================================

# 缓存键 = ``(repository_id, branch_name)``。``branch_name`` 沿用既有模型语义——
# ``""`` 就是基线分支，⛔ **不做归一化别名**（不把 ``"main"`` 折成 ``""``）：默认分支名
# 因仓库而异（``main`` / ``master`` / ``trunk``），一旦别名折错就是两张不同的图共用一个
# 键，返回的会是另一个分支的结论。
CacheKey = tuple[str, str]


@dataclass
class _Entry:
    """一条缓存条目：图本体 + 记账所需的三项元数据。

    刻意把 ``estimated_bytes`` 冗余在条目上（而不是每次从 ``graph`` 现算）：逐出时
    要在持锁状态下做减法，现算意味着在锁内遍历图；而条目一旦写入就不再变形，冗余的
    这个数不会与图本身漂移。
    """

    graph: CodeGraph
    estimated_bytes: int
    built_signature: str
    built_at: datetime


class GraphService:
    """进程内、按**字节预算**逐出的图缓存（GRAPH-03）。

    与本仓既有两套缓存先例的关键差异：``codegraph/lsp/volar_pool.py`` 按**条目数**逐出
    且一次只逐一个，``codegraph/galaxy/cache.py`` 按**文件**记账；本类按字节预算**循环**
    逐出——因为「4 张图」在这里可以是 40MB 也可以是 1GB，条目数根本约束不住 worker RSS。

    线程安全：所有读写 ``_cache`` / ``_total_bytes`` 的路径都要持 :attr:`_lock`。锁是
    ``RLock`` 而非 ``Lock``，因为 Plan 121-08 的编排路径会在同一线程内嵌套进入
    （取图 → 未命中 → 装配 → 回写），``Lock`` 在那里会自死锁。

    ⛔ 本类**全部方法均为同步**，不含任何 ``await``：异步外壳由 Plan 121-08 用一次
    ``sync_to_async`` 包在外面，「持锁」与「await」因此在物理上不可能重叠
    （121-CONTEXT D-04 / RESEARCH Pitfall 7）。
    """

    def __init__(self, max_bytes: int, max_graph_bytes: int) -> None:
        if max_bytes <= 0:
            raise ValueError(f"max_bytes 必须 > 0，收到 {max_bytes}")
        if max_graph_bytes <= 0:
            raise ValueError(f"max_graph_bytes 必须 > 0，收到 {max_graph_bytes}")
        self._max_bytes = max_bytes
        self._max_graph_bytes = max_graph_bytes
        # OrderedDict 的**头部是 LRU 端、尾部是 MRU 端**：命中 move_to_end 推到尾部，
        # 逐出 popitem(last=False) 从头部取。
        self._cache: OrderedDict[CacheKey, _Entry] = OrderedDict()
        self._total_bytes: int = 0
        # 只保护 map 本身（以及 _total_bytes 这个伴随它的计数），不保护建图过程——
        # 建图要 2–4 秒，放进锁内会让所有其它仓库的取图一起排队。
        self._lock = threading.RLock()
        # single-flight 占位。Plan 121-08 填充（键 → 领头请求的等待原语）。
        self._inflight: dict[CacheKey, Any] = {}

    def _get_entry(self, key: CacheKey) -> _Entry | None:
        """取条目并把它移到 MRU 端。**调用方必须已持锁**（:attr:`_lock`）。

        🚨 命中事件走 **DEBUG**：这条路径在每次取图时都会跑，INFO 会直接违反
        ``.cursor/rules/observability-logging.mdc`` 的级别纪律（高频循环禁止 INFO 刷屏）。
        """
        entry = self._cache.get(key)
        if entry is None:
            return None
        self._cache.move_to_end(key)
        logger.debug(
            _EVENT_CACHE_HIT,
            component="code_graph",
            category="sampling",
            repository_id=key[0],
            branch=key[1],
            estimated_bytes=entry.estimated_bytes,
            total_bytes=self._total_bytes,
            cache_size=len(self._cache),
        )
        return entry

    def _put(self, key: CacheKey, entry: _Entry) -> None:
        """写入/覆盖条目，然后逐出到预算内。**调用方必须已持锁**（:attr:`_lock`）。

        覆盖同一个键时**先减旧条目字节再加新条目**：漏掉这一步的话，同一个仓库反复
        重建就会让 ``_total_bytes`` 单调虚增，最终把整个缓存逐空还是「超预算」
        （威胁登记 T-121-记账漂移）。
        """
        existing = self._cache.get(key)
        if existing is not None:
            self._total_bytes -= existing.estimated_bytes
        self._cache[key] = entry
        self._cache.move_to_end(key)
        self._total_bytes += entry.estimated_bytes
        self._evict_until_within_budget()

    def _evict_until_within_budget(self) -> None:
        """从 LRU 端循环逐出，直到总字节回到预算内。**调用方必须已持锁**（:attr:`_lock`）。

        ⚠️ 是 ``while`` 而不是 ``if``：一个接近单图上限的新条目可能一次性挤掉**两张
        以上**旧图，逐一次只会让缓存长期停在超预算状态——那正是 OOM 的形状。
        """
        while self._total_bytes > self._max_bytes and self._cache:
            evicted_key, evicted = self._cache.popitem(last=False)
            self._total_bytes -= evicted.estimated_bytes
            # 低频事件（只在预算真的被撑破时发），INFO 可接受，且它是排查
            # 「为什么缓存命中率突然掉了」的第一手线索。
            logger.info(
                _EVENT_CACHE_EVICTED,
                component="code_graph",
                category="sampling",
                repository_id=evicted_key[0],
                branch=evicted_key[1],
                evicted_bytes=evicted.estimated_bytes,
                total_bytes=self._total_bytes,
                max_bytes=self._max_bytes,
                cache_size=len(self._cache),
                reason="budget_exceeded",
            )

    def stats(self) -> dict[str, int]:
        """当前缓存的记账快照（供诊断接口与用例断言）。"""
        with self._lock:
            return {
                "entries": len(self._cache),
                "total_bytes": self._total_bytes,
                "max_bytes": self._max_bytes,
            }
