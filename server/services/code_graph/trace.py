"""两个符号之间「谁怎么调到谁」的**纯算法内核** —— 有向最短路 + 逐跳渲染（Phase 122，IMPACT-05）。

问题背景
========
``impact`` 回答的是「改这里会影响谁」，``trace`` 回答的是另一个方向的问题：「A 到底
是**怎么**调到 B 的」。后者的输出形态比前者更容易写错，而且两种写错都会让 agent
得出与事实相反的结论：

- **不可达时返回空数组**——agent 读到的是「工具坏了 / 我参数传错了」，而不是
  「这两个符号之间确实没有调用关系」。而后者才是一条可以据以决策的结论（D-20）。
- **有多条等长路径时只给第一条**——agent 会以为自己看到的是**唯一**的调用链，据此
  改一处就以为改全了。等长多解在真实代码里很常见（同一个 handler 被两个 wrapper
  各调一次），⛔ 不声明多解就是静默隐瞒（D-18）。

所以本模块的两条输出契约（显式无路径结构、等长多解声明）不是优化项，是正确性要求。

方案（置信度视图 + 有向最短路 + 逐跳渲染）
==========================================
:func:`trace_path` 在一张**冻结**的 ``MultiDiGraph`` 上做三件事：

- **先建视图再找路**：按 ``min_confidence`` 用 :func:`networkx.subgraph_view` 过滤出
  一张「只有合格边」的**只读视图**，再在视图上跑 :func:`networkx.shortest_path`。
  默认 ``min_confidence=1.0`` 即 D-18 的「只走 ``resolved`` 边」。
- **逐跳渲染**：``shortest_path`` 返回的是**节点序列**、不含边 key，MultiDiGraph 上
  同一符号对可并存多档边，因此每一跳都要自己在 ``view[u][v]`` 里挑一条（挑置信度
    **最高**的那条），再取出 ``file:line`` + 边类型 + 置信档 + 现推的 ``reason``。

边界与已知翻车点
================
① ⚠️ **本模块运行期 import ``networkx``，这不违反 adapter seam**。``model.py`` 的
   那条纪律（``networkx`` 只在 ``TYPE_CHECKING`` 里）约束的是**契约层**——它要保证
   上层写输出结构时不必碰图库。本模块是算法内核，``nx.subgraph_view`` /
   ``nx.shortest_path`` 就是它的实现本体，把它们藏进 ``TYPE_CHECKING`` 既做不到也
   没有意义。换图库时本模块与 ``loader.py`` 一起改，那正是 seam 的设计意图。
   ⛔ 零 Django、零 ORM 这一条**不放松**（威胁登记 T-122-绕闸）。

② 🚨 **绝不复制图**（D-01）。入参图是跨请求共享的冻结对象。RESEARCH 在 30k 节点 /
   100k 边上实测：``subgraph_view`` 建视图 **0.013ms**、``reverse(copy=False)``
   **0.004ms**，而 ``graph.copy()`` / ``reverse(copy=True)`` 要 **330–690ms**——差五个
   数量级。⛔ 不 ``copy()``、⛔ 不 ``copy=True``（有 AST 断言守着）。

③ **``reason`` 现推不存**（D-09）：输出时调
   :func:`~services.code_graph.derive_reason` 生成，⛔ 不在图边属性上新增第四个属性。

④ **输出是结构化 dict，不是渲染好的字符串**（D-10）。渲染留给壳层，让 MCP（JSON）
   与对话（markdown）两面各自决定形态。

⑤ **不吞 ``GraphError``**（D-03）：本模块根本不取图，没有可吞的异常。「没有路径」与
   「查询失败」在输出上是两种形态，翻译归壳层。
"""

from __future__ import annotations

import time
from collections.abc import Mapping
from typing import Any, Final

import networkx as nx
import structlog

from services.code_graph import EdgeConfidence, EdgeKind, confidence_score, derive_reason

logger = structlog.get_logger(__name__)

# 等长路径计数的默认上限。``nx.all_shortest_paths`` 是生成器，在高扇出图上等长解的
# 条数可以是天文数字（每一跳的并行分支相乘）——把它数完既没有意义也会打爆内存，
# agent 需要的只是「不止一条」这个事实与一个量级。取 10：够区分「两条」与「很多条」，
# 又不会让计数本身变成一次全解集遍历。
DEFAULT_ALT_PATH_CAP: Final[int] = 10

_EVENT_TRACE_COMPLETED: Final[str] = "code_graph_trace_completed"

__all__ = [
    "DEFAULT_ALT_PATH_CAP",
    "trace_path",
]


# 埋点自成函数、事件名常量直接写在 ``logger.debug`` 的第一个位置实参上，
# ⛔ 不抽成 ``_emit(event, **fields)`` 那样的通用转发器：``test_observability_contract``
# 要求事件名在**该调用点**可静态解析成字面量，包一层后 AST 只看得到一个形参名
# （D-04 明写 Phase 121 有四个 plan 各踩过一次）。
#
# 取 DEBUG 而非 INFO：agent 一次任务可能连着 trace 很多对符号，INFO 会直接刷屏，
# 违反 ``.cursor/rules/observability-logging.mdc`` 的级别纪律。


def _log_trace_completed(
    *, found: bool, hop_count: int, min_confidence: float, duration_ms: int
) -> None:
    """一次 :func:`trace_path` 恰**一条**结构化埋点。

    🚨 **只记结果形态与耗时，⛔ 不记符号名、不记文件路径、不记路径明细**
    （威胁登记 T-122-exclusion 回流：被排除文件的符号本就不在图里，埋点也不给它们
    留任何回流通道）；🚨 **逐跳循环内零 ``logger.*``**（威胁登记 T-122-日志放大）。
    """
    try:
        logger.debug(
            _EVENT_TRACE_COMPLETED,
            component="code_graph",
            category="sampling",
            found=found,
            hop_count=hop_count,
            min_confidence=min_confidence,
            duration_ms=duration_ms,
        )
    except Exception:  # noqa: BLE001 — 观测失败绝不反噬业务（不是安全降级分支）
        pass


def _edge_score(attrs: Mapping[str, Any]) -> float:
    """一条边的置信度数值，供 ``min_confidence`` 过滤与逐跳挑边使用。

    ⚠️ ``impact.py`` 里有一份**同口径的**四行实现，这不是重复代码待清理——
    ``impact`` 与 ``trace`` 是**平级**内核，任何一方 import 另一方都会在两个本可独立
    演进的模块之间造出一条无谓的依赖边。两份都只是
    :func:`~services.code_graph.confidence_score` 的一层薄封装，真正的数值表只有
    ``model.py`` **一处**，不存在两边漂移的风险。

    ⛔ **不要在这里自建 ``{"resolved": 1.0, …}`` 数值表**：``cross_repo`` 档的分值是
    该行的 ``match_confidence`` **原值**（D-13），自建常量表会把跨仓边的可信度静默
    抹成一个常量。

    :raises ValueError: ``cross_repo`` 档缺 ``match_confidence``（``confidence_score``
        刻意抛错而非静默兜底），或档位未登记。
    """
    confidence = EdgeConfidence(attrs["confidence"])
    if confidence is EdgeConfidence.CROSS_REPO:
        return confidence_score(confidence, match_confidence=attrs["match_confidence"])
    return confidence_score(confidence)


def _confidence_view(graph: nx.MultiDiGraph, min_confidence: float) -> nx.MultiDiGraph:
    """按 ``min_confidence`` 过滤出「只有合格边」的**只读视图**。

    D-18 的默认口径是 ``min_confidence=1.0``，即只有 ``resolved`` 档（分值 1.0）能过，
    也就是「trace 默认只走已解析的边」。放宽到 0.3 会把 ``bare_name`` 档一并放进来
    ——那一档是凭名字连出来的弱证据，用它连出的「调用链」可能整条都是假的。

    🚨 **必须是视图，⛔ 不是副本**：入参图跨请求共享且已 ``nx.freeze``，改不得也复制
    不起。实测建视图 **0.013ms**、复制 **330–690ms**（RESEARCH §Alternatives
    Considered）。视图本身仍然 frozen，``is_multigraph()`` 仍为真，四档边契约不丢。

    ⚠️ ``filter_edge`` 在 **MultiDiGraph** 上的签名是 ``(u, v, k)`` 三参（DiGraph 上是
    两参）——少一个形参会在第一次遍历时抛 ``TypeError``。
    """

    def keep(u: str, v: str, k: Any) -> bool:
        return _edge_score(graph.edges[u, v, k]) >= min_confidence

    return nx.subgraph_view(graph, filter_edge=keep)


def _node_descriptor(graph: nx.MultiDiGraph, node_id: str) -> dict[str, Any]:
    """把一个符号 id 渲染成「这一端是什么」的描述块，供无路径结构回显两端用（D-20）。

    ``in_graph`` 为假时其余字段一律留空——**只回显调用方自己传进来的 id**，⛔ 不做
    任何模糊匹配、不提示「你是不是想找 X」（威胁登记 T-122-exclusion 回流：被排除
    文件的符号不在图里，任何「找不到但像这个」的提示都会把它们的存在性泄漏出去）。
    """
    if node_id not in graph:
        return {
            "symbol_id": node_id,
            "name": "",
            "symbol_type": "",
            "file_path": "",
            "start_line": 0,
            "in_graph": False,
        }
    attrs = graph.nodes[node_id]
    return {
        "symbol_id": node_id,
        "name": str(attrs.get("name") or ""),
        "symbol_type": str(attrs.get("symbol_type") or ""),
        "file_path": str(attrs.get("file_path") or ""),
        "start_line": int(attrs.get("start_line") or 0),
        "in_graph": True,
    }


def _render_hop(
    graph: nx.MultiDiGraph, caller_id: str, callee_id: str, attrs: Mapping[str, Any]
) -> dict[str, Any]:
    """把一跳渲染成输出条目。

    🚨 **``from_line`` 与 ``call_line`` 是两个不同的行号，字段名必须分开**：

    - ``from_file`` / ``from_line`` 取节点属性 ``file_path`` / ``start_line``，是这个
      符号**定义**在哪儿；
    - ``call_line`` 取边属性 ``line_number``，是**调用点**在哪一行。

    一个函数体几十行长，定义处与调用点差出几十行是常态。合成一个 ``line`` 字段的话，
    agent 打开文件跳过去看到的会是函数签名而不是那次调用，且它无从察觉自己看错了。

    ``kind`` / ``confidence`` 取边属性**原值**（字符串标签），⛔ 不折算成数值——三档
    语义标签才是契约，数值只是排序/过滤辅助（``model.py::EdgeConfidence`` 的明文
    要求）。``reason`` 由 :func:`~services.code_graph.derive_reason` 现推（D-09）。
    """
    kind = EdgeKind(attrs["kind"])
    confidence = EdgeConfidence(attrs["confidence"])
    caller_attrs = graph.nodes[caller_id]
    callee_name = str(graph.nodes[callee_id].get("name") or callee_id)
    return {
        "from": caller_id,
        "to": callee_id,
        "from_file": str(caller_attrs.get("file_path") or ""),
        "from_line": int(caller_attrs.get("start_line") or 0),
        "call_line": int(attrs.get("line_number") or 0),
        "kind": attrs["kind"],
        "confidence": attrs["confidence"],
        "reason": derive_reason(
            kind,
            confidence,
            callee_name=callee_name,
            match_confidence=attrs.get("match_confidence"),
        ),
    }


def trace_path(
    graph: nx.MultiDiGraph,
    source_symbol_id: str,
    target_symbol_id: str,
    *,
    min_confidence: float = 1.0,
    alt_path_cap: int = DEFAULT_ALT_PATH_CAP,
) -> dict[str, Any]:
    """求 ``source → target`` 的**有向**最短调用路径，逐跳给出 ``file:line`` 与边属性。

    **方向就是语义**：``trace_path(g, "D", "A")`` 问的是「D 怎么调到 A」，
    ``trace_path(g, "A", "D")`` 问的是反过来那件事。图是有向的，两者可以一个有解
    一个无解，⛔ 不要把无解的那一侧当成 bug。

    三种结果形态，靠 ``found`` 与 ``reason`` 区分（D-20：**任何一种都不是空数组**
    ——空数组会被 agent 读成「工具坏了」而不是「确实没有调用关系」）：

    ===================================  ==========================================
    ``found=False, reason=…``            含义
    ===================================  ==========================================
    ``"node_not_in_graph"``              至少一端不在图里（uid 打错 / 被 exclusion
                                         挡掉 / 不在按需子图内）。看 ``source`` /
                                         ``target`` 的 ``in_graph`` 判断是哪一端。
    ``"no_path"``                        两端都在图里，但在 ``min_confidence`` 过滤后
                                         的视图上**确实**没有从 source 到 target 的
                                         有向路径。这是一条可据以决策的结论。
    ===================================  ==========================================

    命中时（``found=True``）额外给出：

    - ``path``：节点 id 序列；``hops``：逐跳明细（字段见 :func:`_render_hop`）。
    - ``path_confidence``：整条路径各跳分值的**最小值**（D-07 同口径，弱边决定强度）。
      ⛔ 不取平均——一条 ``resolved`` 边会把 ``bare_name`` 洗白。零跳的平凡路径
      （``source == target``）取 1.0。
    :param graph: 已过 ``GraphService.get_graph()`` 三道闸的冻结 ``MultiDiGraph``。
        本函数只读，⛔ 不修改、⛔ 不复制。
    :param source_symbol_id: 起点符号 id（调用方）。
    :param target_symbol_id: 终点符号 id（被调方）。
    :param min_confidence: 边的置信度门槛，默认 1.0 即只走 ``resolved`` 边（D-18）。
    :param alt_path_cap: 等长路径的计数上限，见 :data:`DEFAULT_ALT_PATH_CAP`。
        小于 1 的取值按 1 处理——0 会让「至少 0 条」这种无意义声明流到输出上。
    """
    started_at = time.perf_counter()
    # ⚠️ 两端描述块在**任何**分支里都要给（D-20 的「含两端解析结果」），所以先算，
    # 不要塞进各个 return 里各写一遍。
    endpoints: dict[str, Any] = {
        "source": _node_descriptor(graph, source_symbol_id),
        "target": _node_descriptor(graph, target_symbol_id),
        "min_confidence": min_confidence,
    }

    def _elapsed_ms() -> int:
        return int((time.perf_counter() - started_at) * 1000)

    if not endpoints["source"]["in_graph"] or not endpoints["target"]["in_graph"]:
        _log_trace_completed(
            found=False,
            hop_count=0,
            min_confidence=min_confidence,
            duration_ms=_elapsed_ms(),
        )
        return {"found": False, "reason": "node_not_in_graph", **endpoints}

    view = _confidence_view(graph, min_confidence)
    try:
        path: list[str] = nx.shortest_path(view, source_symbol_id, target_symbol_id)
    except nx.NetworkXNoPath:
        _log_trace_completed(
            found=False,
            hop_count=0,
            min_confidence=min_confidence,
            duration_ms=_elapsed_ms(),
        )
        return {"found": False, "reason": "no_path", **endpoints}
    except nx.NodeNotFound:
        # 上面的 in_graph 检查已挡掉绝大多数情形，这里是兜底：视图语义若在未来的
        # networkx 版本上变化（例如孤立节点被过滤掉），也要落到显式结构而不是异常
        # 穿透到壳层。
        _log_trace_completed(
            found=False,
            hop_count=0,
            min_confidence=min_confidence,
            duration_ms=_elapsed_ms(),
        )
        return {"found": False, "reason": "node_not_in_graph", **endpoints}

    hops: list[dict[str, Any]] = []
    hop_scores: list[float] = []
    for caller_id, callee_id in zip(path, path[1:]):
        # MultiDiGraph 上同一符号对可并存多档边，``shortest_path`` 只给节点序列、
        # 不给边 key ⇒ 必须自己挑一条。挑**置信度最高**的那条：⛔ 随便取第一个会让
        # 同一条路径的渲染结果取决于建图时的插入顺序，而且可能把一条 resolved 边
        # 存在的事实说成 bare_name。
        attrs = max(view[caller_id][callee_id].values(), key=_edge_score)
        hop_scores.append(_edge_score(attrs))
        hops.append(_render_hop(graph, caller_id, callee_id, attrs))

    _log_trace_completed(
        found=True,
        hop_count=len(hops),
        min_confidence=min_confidence,
        duration_ms=_elapsed_ms(),
    )

    return {
        "found": True,
        "reason": "",
        **endpoints,
        "path": path,
        "hops": hops,
        # D-07 同口径：整条路径的强度由最弱的那一跳决定。零跳（source == target）
        # 没有任何边可以拉低它，取 1.0。
        "path_confidence": min(hop_scores, default=1.0),
    }
