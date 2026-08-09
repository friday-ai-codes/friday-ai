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

from typing import Final

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
