"""内存符号图的**存储层 + 取图入口** —— 字节预算 LRU、签名复校、半新图防护与
single-flight（Phase 121，GRAPH-01/02/03）。

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

② **临界区全同步，锁内绝不 await**（121-CONTEXT D-04 / RESEARCH Pitfall 7）。整条取图
   链路（解析 exclusion → 算签名 → 判在途 → 命中或重建 → 准入或降级 → 记账入缓存）
   是一个同步函数 :meth:`GraphService._get_graph_sync`，由 :meth:`GraphService.get_graph`
   用**唯一一次** ``sync_to_async`` 包在外面。本模块因此只有那**一个** ``async def``，
   其余方法一律同步——「持锁」与「await」在物理上不可能重叠，是这条分层最省心的性质。

③ **锁原语一律 ``threading``，⛔ 不用 ``asyncio.Lock`` / ``asyncio.Event``**。本仓同时
   存在三类 event loop（ASGI 主循环、``services/background_runner.py`` 的常驻 daemon
   线程循环、workflow engine ``_run_in_thread`` 的每次执行独立循环），而
   :class:`GraphService` 是**进程级**单例、会被三者共用；``asyncio`` 原语绑定创建它的
   loop，跨 loop 使用直接 ``RuntimeError``（D-04 / Pitfall 8）。

④ **存储侧与编排侧分层清楚**。存储侧（``estimate_graph_bytes`` / :class:`_Entry` /
   ``_put`` / ``_evict_until_within_budget``）只认字节数，不知道图从哪来；编排侧
   （:meth:`GraphService.get_graph` / :meth:`GraphService._get_graph_sync`）只通过
   ``access`` / ``signature`` / ``loader`` 三个模块的公开函数取事实。⛔ 本模块内
   **不另写**任何一份可读性判据、在途判据或 exclusion 判定——那样迟早会与唯一事实源
   漂移（尤其是 in-flight：121-CONTEXT D-03 记过一次「照字面读 ``PENDING``」的翻车）。
"""

from __future__ import annotations

import threading
import time
from collections import OrderedDict
from collections.abc import Sequence
from dataclasses import dataclass, replace
from datetime import datetime
from typing import Any, Final

import structlog
from asgiref.sync import sync_to_async
from django.conf import settings

from common.logging import redact_secrets_in_text
from services.code_graph import access, loader, signature
from services.code_graph.model import (
    CodeGraph,
    GraphBuildFailed,
    GraphBuildTimeout,
    GraphError,
)

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

# 调用方未指定 ``depth`` 时按需子图的默认跳数（loader 内部按 ``depth + 1`` 收敛，
# 多留的那一跳保证边界节点邻接完整）。取 2 与 Phase 122 的默认影响面半径一致。
_DEFAULT_SUBGRAPH_DEPTH: Final[int] = 2

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
# 编排侧埋点
# =============================================================================
#
# 每个事件各成一个函数、事件名常量直接写在 ``logger.*`` 的**第一个位置实参**上，
# ⛔ 不抽 ``_emit(event, **kw)`` 转发器（理由见上方常量段）。观测 best-effort ——
# 任何异常吞掉，绝不反噬取图主流程。


def _initiated_by(user: Any | None) -> str:
    """取触发用户标识；无触发用户（后台/预热路径）记 ``system``（LOGGING-SPEC §3）。

    与 ``access.py`` 的同名私有助手同形。刻意各写一份而不是跨模块 import 私有名：
    两处都只有四行，而 import 私有名会把 ``access`` 的内部约定变成 ``cache`` 的
    公开依赖。
    """
    if user is None:
        return "system"
    user_id = getattr(user, "id", None) or getattr(user, "pk", None)
    return str(user_id) if user_id is not None else "system"


def _log_stale_watermark(
    *, repository_id: str, branch: str, cached_signature: str, current_signature: str
) -> None:
    """签名不一致导致条目被丢弃。

    低频（只在真的失效时发），INFO 可接受。🚨 **只记签名前 12 位**：签名的明文
    分量里含水位 sha、两条轨的行 id 与状态、以及 exclusion 规则指纹，全量落日志
    等于把仓库内部状态摊开（威胁登记 T-121-异常泄密）。前缀足够人工比对「是不是
    同一个签名」，这正是排障时唯一需要的信息。
    """
    try:
        logger.info(
            _EVENT_STALE_WATERMARK,
            component="code_graph",
            category="sampling",
            repository_id=repository_id,
            branch=branch or "-",
            cached_signature=cached_signature[:12],
            current_signature=current_signature[:12],
            reason="signature_mismatch",
        )
    except Exception:  # noqa: BLE001 — 观测失败绝不反噬业务（不是安全降级分支）
        pass


def _log_build_started(
    *, repository_id: str, branch: str, initiated_by_user_id: str
) -> None:
    """装配开始。取 DEBUG —— 每次未命中都发，INFO 会违反级别纪律。"""
    try:
        logger.debug(
            _EVENT_BUILD_STARTED,
            component="code_graph",
            category="sampling",
            repository_id=repository_id,
            branch=branch or "-",
            initiated_by_user_id=initiated_by_user_id,
        )
    except Exception:  # noqa: BLE001 — 观测失败绝不反噬业务（不是安全降级分支）
        pass


def _log_build_completed(
    *,
    repository_id: str,
    branch: str,
    duration_ms: float,
    node_count: int,
    edge_count: int,
    estimated_bytes: int,
    resolution_rate: float,
    partial_edges: bool,
    degraded: str,
    cross_repo_unresolved_count: int,
    cached: bool,
    initiated_by_user_id: str,
) -> None:
    """装配完成。INFO：一次一图的低频关键生命周期事件，且规范强制带 ``duration_ms``。

    kv 里同时带 ``partial_edges`` / ``degraded``，是为了让「这张图为什么不可全信」
    在日志里能直接答出来——否则排障要回头翻三个模块的 DEBUG 事件拼。
    """
    try:
        logger.info(
            _EVENT_BUILD_COMPLETED,
            component="code_graph",
            category="sampling",
            repository_id=repository_id,
            branch=branch or "-",
            duration_ms=duration_ms,
            node_count=node_count,
            edge_count=edge_count,
            estimated_bytes=estimated_bytes,
            resolution_rate=resolution_rate,
            partial_edges=partial_edges,
            degraded=degraded,
            cross_repo_unresolved_count=cross_repo_unresolved_count,
            cached=cached,
            initiated_by_user_id=initiated_by_user_id,
        )
    except Exception:  # noqa: BLE001 — 观测失败绝不反噬业务（不是安全降级分支）
        pass


def _log_build_failed(
    *,
    repository_id: str,
    branch: str,
    error: str,
    error_type: str,
    duration_ms: float,
    waiters: int,
    initiated_by_user_id: str,
) -> None:
    """装配失败。WARNING —— 领头失败会连带让全部等待者一起失败，值得被看见。

    ``waiters`` 记的是失败时挂在同一个占位上的等待者数：它把「一次瞬时故障波及了几个
    请求」这件事直接答出来，否则只能从零散的 ``GraphBuildFailed`` 里数。

    异常文本过 ``redact_secrets_in_text`` 后截断 500 字符：装配路径上的异常可能带
    上游连接串或凭证片段（威胁登记 T-121-异常泄密）。
    """
    try:
        logger.warning(
            _EVENT_BUILD_FAILED,
            component="code_graph",
            category="sampling",
            repository_id=repository_id,
            branch=branch or "-",
            error=redact_secrets_in_text(error)[:500],
            error_type=error_type,
            duration_ms=duration_ms,
            waiters=waiters,
            initiated_by_user_id=initiated_by_user_id,
        )
    except Exception:  # noqa: BLE001 — 观测失败绝不反噬业务（不是安全降级分支）
        pass


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


@dataclass
class _InFlight:
    """per-key single-flight 占位：领头装配期间，同键的后来者挂在这里等同一个结果。

    🚨 ``event`` 必须是 ``threading.Event``，⛔ **绝不能是 ``asyncio.Event``**
    （121-CONTEXT D-04 / RESEARCH Pitfall 8）：本仓同时存在 ASGI 主循环、
    ``background_runner`` 常驻 daemon 线程循环、workflow engine ``_run_in_thread``
    的每次执行独立循环三类 loop，而 :class:`GraphService` 是进程级单例、会被三者共用；
    ``asyncio`` 原语绑定创建它的那个 loop，跨 loop 使用直接 ``RuntimeError``。
    ``threading.Event`` 与 loop 无关，是这里唯一稳妥的形态。

    ⚠️ ``event.wait()`` 是**阻塞**调用，但它只会跑在 ``sync_to_async`` 派发的执行器
    线程上、不在 event loop 线程上，所以不阻塞 loop（RESEARCH Pitfall 7）。若将来有人
    要从协程里直接等待占位，必须走 ``await asyncio.to_thread(ev.wait, timeout)``，
    ⛔ 不得在协程里直接 ``ev.wait()``。

    ⛔ **失败不留痕**：占位在 ``finally`` 中无条件从 ``_inflight`` 弹出，失败也不写进
    缓存——不做失败缓存是刻意的，一次瞬时故障不该毒化后续所有请求。
    """

    event: threading.Event
    result: CodeGraph | None = None
    error: BaseException | None = None
    # 失败埋点用：这次故障一共波及了几个等待者。
    waiters: int = 0


class GraphService:
    """进程内、按**字节预算**逐出的图缓存（GRAPH-03）。

    与本仓既有两套缓存先例的关键差异：``codegraph/lsp/volar_pool.py`` 按**条目数**逐出
    且一次只逐一个，``codegraph/galaxy/cache.py`` 按**文件**记账；本类按字节预算**循环**
    逐出——因为「4 张图」在这里可以是 40MB 也可以是 1GB，条目数根本约束不住 worker RSS。

    线程安全：所有读写 ``_cache`` / ``_total_bytes`` 的路径都要持 :attr:`_lock`。锁是
    ``RLock`` 而非 ``Lock``，因为 Plan 121-08 的编排路径会在同一线程内嵌套进入
    （取图 → 未命中 → 装配 → 回写），``Lock`` 在那里会自死锁。

    ⛔ 除 :meth:`get_graph` 这**唯一一个** async 外壳外，本类全部方法均为同步、不含任何
    ``await``：外壳只做「校验 + 一次 ``sync_to_async``」，其余一切在同步侧完成，
    「持锁」与「await」因此在物理上不可能重叠（121-CONTEXT D-04 / RESEARCH Pitfall 7）。
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
        # per-key single-flight 占位（键 → 领头请求的等待原语）。与 ``_cache`` 一样，
        # 只有这个 map **本身**受 ``_lock`` 保护；装配全程在锁外进行。
        self._inflight: dict[CacheKey, _InFlight] = {}

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

    # ── 取图入口（GRAPH-01/02/03 在同一条链路上收口） ────────────────────────

    async def get_graph(
        self,
        repository_id: str,
        branch: str = "",
        *,
        user: Any | None = None,
        include_low_confidence: bool = False,
        seed_symbol_ids: Sequence[str] | None = None,
        depth: int | None = None,
    ) -> CodeGraph:
        """取一张 ``(repository, branch)`` 的内存符号图（全仓唯一的图访问入口）。

        本方法只做两件事：**每次调用都跑一遍可读性校验**，然后把整条取图链路交给
        一次 ``sync_to_async``。

        🚨 ``ensure_repository_readable`` 绝不因缓存命中而跳过。缓存键是
        ``(repository_id, branch)``，键本身不带用户维度——命中即返回意味着任何拿得到
        ``repository_id`` 的调用方都能读到别人建好的图，跨仓串图与 ACL 撤销滞后就都成了
        真（威胁登记 T-121-串图）。⛔ **不要**为了「命中更快」把这一行挪进未命中分支：
        它是这条链路上唯一的权限防线，而它的成本只是一次带主键索引的单行取值。

        .. note::
           **``thread_sensitive=True`` 的代价（如实记录，不传该参数就是取这个默认值）**：
           ``sync_to_async`` 默认把同步体排到**同一个**执行器线程上，与全仓其余 ORM
           调用共用。这意味着一次 2–4 秒的大图装配会阻塞该执行器上排在后面的其他 ORM
           工作。之所以仍取默认值而不是 ``thread_sensitive=False``：本仓的 sync ORM 调用
           一律跑在 Django 主线程（先例见 ``code_relations/lifecycle.py`` L52–55 的注释
           ——避免 SQLite 多线程写锁竞争），单独把图服务放到新线程会破坏这条一致性。

           阻塞风险靠**三层缓解**收敛，而不是靠换参数：① single-flight 让同一 key 的 N
           个并发请求只装配一次；② LRU 让建过的图不再重建；③ 超预算大仓走按需子图
           ——第三层才是大仓的真正防线，因为前两层只降频次、不降单次时长。

        :param repository_id: 仓库主键。
        :param branch: ``""`` = base 分支（与 ``Symbol.branch_name`` 同口径）。
        :param user: 触发用户；``None`` 表示后台/系统路径，埋点记 ``system``。
        :param include_low_confidence: 是否装载裸名边（默认否）。
        :param seed_symbol_ids: 非空时走**按需子图**路径——⛔ 既不查缓存也不进缓存
            （子图内容依赖种子与深度，而缓存键里没有这两维；把种子塞进键会让缓存
            退化成一次一建）。
        :param depth: 调用方随后要在图上走的跳数，仅子图路径使用（缺省 2）。
        :raises GraphAccessDenied: 仓库不可读，或 exclusion matcher 构造失败（fail-closed）。
        :raises GraphNotIndexed: 仓库尚未建立索引（⛔ 不返回空图）。
        """
        await access.ensure_repository_readable(user, repository_id)
        return await sync_to_async(self._get_graph_sync)(
            str(repository_id),
            branch,
            include_low_confidence,
            tuple(seed_symbol_ids) if seed_symbol_ids else (),
            depth,
            _initiated_by(user),
        )

    def _get_graph_sync(
        self,
        repository_id: str,
        branch: str,
        include_low_confidence: bool,
        seed_symbol_ids: tuple[str, ...],
        depth: int | None,
        user_id: str,
    ) -> CodeGraph:
        """全同步：锁、ORM、networkx 装配都在这里，不存在 await-under-lock 的可能。

        **步骤顺序是契约，不是实现细节**：

        ③ 解析 exclusion（本次调用内**只此一次**，随后向下注入）
        ④ 算复合签名
        ⑤ 判边构建是否在途 —— 🚨 **在命中返回之前**
        ⑥ 命中判定（签名一致 **且** 不在途才算命中）
        ⑦ 签名不一致 → 驱逐条目并走重建

        ⑤ 与 ⑥ 的先后是 GRAPH-02 的全部要害，详见步骤 ⑤ 处的注释。
        """
        key: CacheKey = (repository_id, branch)

        # ③ exclusion 规则**本次调用只解析编译一次**，随后作为关键字参数注入 loader。
        #    ⛔ 绝不让 loader 自己再调一次 ``build_matcher_and_fingerprint``：那是一次
        #    ``_resolve_effective_specs`` 的 DB 读 + 该仓全部 glob/regex 重新编译
        #    （``services/exclusion.py`` L157–207），而这条同步路径**吃不到**
        #    ``build_matcher_for_repo`` 的 60s ``_matcher_cache``，省不掉。跨调用的复用由
        #    ``access.py`` 自带的 TTL memo 负责，本层只保证「一次调用一次解析」。
        #    fail-closed：构造失败在 access 侧就抛 GraphAccessDenied，这里不兜。
        matcher, exclusion_fingerprint = access.build_matcher_and_fingerprint(
            repository_id
        )

        # ④ 复合签名：水位 ‖ 两条边构建轨 ‖ 计数 ‖ exclusion 规则指纹。
        current_sig = signature.compute_signature(
            repository_id, branch, exclusion_fingerprint=exclusion_fingerprint
        )

        # ⑤ 🚨 in-flight 闸门**必须**在命中返回之前跑，位置不可调整。
        #    要挡的恰恰是「签名分量尚未推进、但边正在写入」这个窗口：此时签名会
        #    **恰好一致**，若先返回命中就永远走不到这一步，GRAPH-02 的保证等于零。
        #    签名比对与在途判定是两道**独立**的闸，不是同一道闸的两种写法——前者答
        #    「数据变了吗」，后者答「现在正在写吗」。
        #    ⛔ 不要为了「命中更快」把这一行挪进未命中分支。
        in_flight, in_flight_reason = signature.detect_edge_build_in_flight(
            repository_id, branch
        )

        # 子图路径既不查缓存也不进缓存（种子与深度无法进缓存键，见 get_graph 文档）。
        if not seed_symbol_ids:
            with self._lock:
                entry = self._cache.get(key)
                if entry is not None:
                    if entry.built_signature != current_sig:
                        # ⑦ 签名不一致：条目已被证伪，移除并扣账后重建。
                        self._cache.pop(key, None)
                        self._total_bytes -= entry.estimated_bytes
                        _log_stale_watermark(
                            repository_id=repository_id,
                            branch=branch,
                            cached_signature=entry.built_signature,
                            current_signature=current_sig,
                        )
                    elif not in_flight:
                        # ⑥ 命中：签名一致 **且** 不在途。
                        self._get_entry(key)
                        return entry.graph
                    # 签名一致但在途 → 落到下面的重建路径。此处**只绕过、不驱逐**：
                    # 该条目本身没有被证伪，边构建完成后签名自然会推进并触发正常替换；
                    # 驱逐只会白白丢掉一份可能马上又要用的图。

        build_kwargs: dict[str, Any] = {
            "key": key,
            "repository_id": repository_id,
            "branch": branch,
            "include_low_confidence": include_low_confidence,
            "seed_symbol_ids": seed_symbol_ids,
            "depth": depth,
            "matcher": matcher,
            "exclusion_fingerprint": exclusion_fingerprint,
            "current_sig": current_sig,
            "in_flight": in_flight,
            "in_flight_reason": in_flight_reason,
            "user_id": user_id,
        }

        if seed_symbol_ids:
            # ⛔ 子图请求**不进** single-flight：占位键是 ``(repository_id, branch)``，
            # 里面没有种子与深度这两维。让不同种子的并发请求共用同一个占位，等待者拿到的
            # 会是领头那份**别人种子**的子图——那是错图，不是慢图，比重复装配严重得多。
            return self._build_graph(**build_kwargs)

        return self._build_single_flight(key, build_kwargs)

    def _build_single_flight(
        self, key: CacheKey, build_kwargs: dict[str, Any]
    ) -> CodeGraph:
        """同键并发只装配一次：领头真建，其余等同一个结果（威胁登记 T-121-风暴）。

        锁纪律：:attr:`_lock` **只**保护 ``_inflight`` / ``_cache`` 两个 map 本身，装配
        （2–4 秒纯 CPU + ORM）一律在锁外——放进锁内会让所有**其它仓库**的取图一起排队。
        """
        with self._lock:
            existing = self._inflight.get(key)
            if existing is None:
                inflight = _InFlight(event=threading.Event())
                self._inflight[key] = inflight
                is_leader = True
            else:
                existing.waiters += 1
                inflight = existing
                is_leader = False

        if not is_leader:
            return self._wait_for_inflight(inflight, key=key)

        started = time.perf_counter()
        result: CodeGraph | None = None
        error: BaseException | None = None
        try:
            result = self._build_graph(**build_kwargs)
            return result
        except BaseException as exc:  # noqa: BLE001 — 记录并唤醒等待者后原样抛出
            error = exc
            raise
        finally:
            # 无条件弹出占位：⛔ 不做失败缓存，下一个请求会重新竞争占位并重新构建，
            # 一次瞬时故障因此不会毒化后续所有请求（威胁登记 T-121-毒化）。
            with self._lock:
                inflight.result = result
                inflight.error = error
                self._inflight.pop(key, None)
                waiters = inflight.waiters
            inflight.event.set()
            if error is not None:
                _log_build_failed(
                    repository_id=key[0],
                    branch=key[1],
                    error=str(error),
                    error_type=type(error).__name__,
                    duration_ms=round((time.perf_counter() - started) * 1000, 2),
                    waiters=waiters,
                    initiated_by_user_id=build_kwargs["user_id"],
                )

    def _wait_for_inflight(self, inflight: _InFlight, *, key: CacheKey) -> CodeGraph:
        """等领头把图建出来。**超时是必需的，不是可选的**。

        领头请求随时可能被 kill（最典型的是 ASGI 断连取消），届时占位虽然会在
        ``finally`` 里弹出、``event`` 也会被 set，但若领头连 ``finally`` 都没跑到
        （进程级中断），等待者不能就此永久挂住。上界取
        ``settings.CODE_GRAPH_BUILD_WAIT_TIMEOUT_SECONDS``。

        ⚠️ 这里的 ``event.wait()`` 是阻塞调用，运行在 ``sync_to_async`` 派发的执行器
        线程上、不在 event loop 线程上，所以不阻塞 loop（RESEARCH Pitfall 7）。
        """
        timeout = float(getattr(settings, "CODE_GRAPH_BUILD_WAIT_TIMEOUT_SECONDS", 120))
        if not inflight.event.wait(timeout):
            raise GraphBuildTimeout(
                "等待同键的图构建超时",
                {
                    "repository_id": key[0],
                    "branch": key[1],
                    "timeout_seconds": timeout,
                },
            )
        if inflight.error is not None:
            # 包一层再抛：等待者拿到的是「领头失败了」这个事实，原异常留在 __cause__ 里
            # 供排障，⛔ 不返回任何降级结果（宁可显式失败也不给半成品）。
            raise GraphBuildFailed(
                "领头请求的图构建失败",
                {
                    "repository_id": key[0],
                    "branch": key[1],
                    "error_type": type(inflight.error).__name__,
                },
            ) from inflight.error
        if inflight.result is None:
            raise GraphBuildFailed(
                "领头请求既未产出图也未记录异常",
                {"repository_id": key[0], "branch": key[1]},
            )
        return inflight.result

    def _build_graph(
        self,
        *,
        key: CacheKey,
        repository_id: str,
        branch: str,
        include_low_confidence: bool,
        seed_symbol_ids: tuple[str, ...],
        depth: int | None,
        matcher: Any,
        exclusion_fingerprint: str,
        current_sig: str,
        in_flight: bool,
        in_flight_reason: str,
        user_id: str,
    ) -> CodeGraph:
        """装配一张图并按规则决定是否入缓存。**不得在持锁状态下调用**（装配 2–4 秒）。

        两道判定在这里落地：

        - **半新图防护（GRAPH-02）**：消费 :meth:`_get_graph_sync` 步骤 ⑤ 已算好的
          ``in_flight``。⛔ **不在这里重新调一次** ``detect_edge_build_in_flight``
          ——那等于把闸门挪到命中判定之后，「签名恰好一致但边正在写」的窗口就漏了，
          而那恰恰是 GRAPH-02 要挡的那一类。
        - **装配前准入（GRAPH-03）**：先用 COUNT 估一把再决定装不装。⛔ 不能「先装配
          再看多大」——那就是「先 OOM 再逐出」，OOM 之后逐出已经救不回来了。
        """
        started = time.perf_counter()
        _log_build_started(
            repository_id=repository_id, branch=branch, initiated_by_user_id=user_id
        )

        _, _, admission_bytes = self._estimate_admission(repository_id, branch)
        over_budget = admission_bytes > self._max_graph_bytes

        if over_budget and not seed_symbol_ids:
            # ⛔ 不返回空图、也不返回截断的全量图：两者都会被上层读成「影响面就这么大」，
            # 而真相是「这仓大到装不下」。显式抛错并把出路写进消息里。
            raise GraphError(
                "本仓超出单图内存预算，请改用带 seed_symbol_ids 的按需子图查询",
                {
                    "repository_id": repository_id,
                    "branch": branch,
                    "estimated_bytes": admission_bytes,
                    "max_graph_bytes": self._max_graph_bytes,
                },
            )

        if over_budget or seed_symbol_ids:
            # 降级路径：种子相关，⛔ 不进缓存（缓存键里没有种子与深度这两维，
            # 而种子空间无界——塞进键会让缓存退化成一次一建）。
            # ``degraded="on_demand_subgraph"`` 由 loader 置成终值，此处不覆写；
            # ``code_graph_degraded_subgraph`` 事件同样由 loader 发，不重复。
            graph = loader.load_subgraph(
                repository_id,
                branch,
                seed_symbol_ids=list(seed_symbol_ids),
                depth=_DEFAULT_SUBGRAPH_DEPTH if depth is None else depth,
                matcher=matcher,
                exclusion_fingerprint=exclusion_fingerprint,
                include_low_confidence=include_low_confidence,
            )
            cacheable = False
        else:
            graph = loader.load_graph(
                repository_id,
                branch,
                matcher=matcher,
                exclusion_fingerprint=exclusion_fingerprint,
                include_low_confidence=include_low_confidence,
            )
            # 在途时这张图是「半新」的：如实打标记，且**不写进缓存**——缓存下来会让
            # 后续命中一直返回半新图，污染面比这一次大得多。
            cacheable = not in_flight

        # 记账用**实际** node/edge 计数重算（准入用的是 COUNT 估算，两者可能因 exclusion
        # 过滤而不同）；同一个数必须同时写进 GraphMeta 与 _Entry，否则 LRU 记的与元数据
        # 声明的对不上（121-07 handoff 点名的那条）。
        estimated_bytes = estimate_graph_bytes(
            graph.graph.number_of_nodes(), graph.graph.number_of_edges()
        )
        result = replace(
            graph,
            meta=replace(
                graph.meta,
                estimated_bytes=estimated_bytes,
                built_signature=current_sig,
                partial_edges=in_flight,
                partial_reason=in_flight_reason if in_flight else "",
            ),
        )

        if cacheable:
            with self._lock:
                self._put(
                    key,
                    _Entry(
                        graph=result,
                        estimated_bytes=estimated_bytes,
                        built_signature=current_sig,
                        built_at=result.meta.built_at,
                    ),
                )

        _log_build_completed(
            repository_id=repository_id,
            branch=branch,
            duration_ms=round((time.perf_counter() - started) * 1000, 2),
            node_count=result.meta.node_count,
            edge_count=result.meta.edge_count,
            estimated_bytes=estimated_bytes,
            resolution_rate=result.meta.resolution_rate,
            partial_edges=result.meta.partial_edges,
            degraded=result.meta.degraded,
            cross_repo_unresolved_count=result.meta.cross_repo_unresolved_count,
            cached=cacheable,
            initiated_by_user_id=user_id,
        )
        return result

    def _estimate_admission(self, repository_id: str, branch: str) -> tuple[int, int, int]:
        """装配**前**的准入估算，返回 ``(node_count, edge_count, estimated_bytes)``。

        🚨 **这两条 COUNT 是 ``_get_graph_sync`` 里除签名/in-flight/exclusion 之外仅剩的
        DB 触点**，封在这一个方法里是刻意的：并发用例只需 stub 这一个接缝就能做到「全程
        不碰数据库」（4 个线程并发打 SQLite 文件测试库必然 flaky）。⛔ 不要把 COUNT 内联
        回 ``_build_graph``——那会让那条零查询断言无处下手。

        ``branch_name__in`` 取 overlay 语义（与 ``signature._count_parts`` 同口径）：
        feature 分支的图是「base 全量 + 分支增量」，两个分支的行都要计入。
        """
        from codegraph.models import CallEdge, Symbol

        branch_filter = ["", branch] if branch else [""]
        node_count = Symbol.objects.filter(
            repository_id=repository_id, branch_name__in=branch_filter
        ).count()
        edge_count = CallEdge.objects.filter(
            repository_id=repository_id, branch_name__in=branch_filter
        ).count()
        return node_count, edge_count, estimate_graph_bytes(node_count, edge_count)


# =============================================================================
# 模块级单例
# =============================================================================
#
# 为什么是 ``threading`` 原语而不是 ``asyncio``：本仓同时存在**三类** event loop
# ——ASGI 主循环、``services/background_runner.py`` 的常驻 daemon 线程循环、以及
# workflow engine ``_run_in_thread`` 每次执行新建的独立循环——而下面这个
# :class:`GraphService` 是**进程级**单例，会被三者共用。``asyncio.Lock`` /
# ``asyncio.Event`` 绑定创建它们的那个 loop，跨 loop 使用直接 ``RuntimeError``
# （121-CONTEXT D-04 / RESEARCH Pitfall 8）。本仓已有 11 处模块级 ``threading.Lock``
# 先例，这里照同一个形态走。

_GRAPH_SERVICE: GraphService | None = None
_SINGLETON_LOCK: Final[threading.Lock] = threading.Lock()


def get_graph_service() -> GraphService:
    """模块级单例；**lazy 实例化让 settings 加载顺序安全**。

    形态照 ``codegraph/lsp/volar_pool.py::get_volar_pool()``：预算值在**首次调用时**才
    从 settings 读，而不是在 import 时求值——模块 import 可能发生在 Django settings
    完全就绪之前，那时求值会拿到默认值并永久固化，``override_settings`` 也再改不动。
    """
    global _GRAPH_SERVICE
    with _SINGLETON_LOCK:
        if _GRAPH_SERVICE is None:
            _GRAPH_SERVICE = GraphService(
                max_bytes=int(
                    getattr(settings, "CODE_GRAPH_CACHE_MAX_BYTES", 512 * 1024 * 1024)
                ),
                max_graph_bytes=int(
                    getattr(settings, "CODE_GRAPH_MAX_GRAPH_BYTES", 256 * 1024 * 1024)
                ),
            )
        return _GRAPH_SERVICE


def _reset_for_tests() -> None:
    """测试钩子：丢弃模块级单例并清空其状态，下次 :func:`get_graph_service` 会重建。

    **严禁在生产代码里调用。** 在线上把单例换掉意味着整个 worker 的图缓存瞬间清零，
    紧接着的每个请求都要冷建 2–4 秒的大图——那是一次自伤的拒绝服务。

    形态照 ``services/background_runner.py::_reset_for_tests()``。之所以既置 ``None``
    **又**清空旧实例的内部状态：别处可能已经把旧实例的引用拿在手上（例如某个用例先
    ``svc = get_graph_service()`` 再触发重置），只换指针会让那份引用继续带着上一个用例
    的条目跑，用例间污染照旧。
    """
    global _GRAPH_SERVICE
    with _SINGLETON_LOCK:
        stale = _GRAPH_SERVICE
        _GRAPH_SERVICE = None
    if stale is not None:
        with stale._lock:
            stale._cache.clear()
            stale._total_bytes = 0
            stale._inflight.clear()


__all__ = [
    "EDGE_COST_BYTES",
    "NODE_COST_BYTES",
    "GraphService",
    "estimate_graph_bytes",
    "get_graph_service",
]
