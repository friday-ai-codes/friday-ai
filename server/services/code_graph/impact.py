"""反向依赖影响面的**纯算法内核** —— 分层反向 BFS + path-min 置信度（Phase 122，IMPACT-01/02/04）。

问题背景
========
「改这个函数会破坏什么」是 agent 最常问的一句话，而它最容易被答错的方式不是漏答，
是**答得太满**：生产 1,585,137 条调用边里只有 **18.8%** 解析到了具体 ``Symbol``，
其余靠名字兜底。一条凭名字连出来的假边看起来与真边毫无区别，却能让影响面凭空
膨胀一整个子树（研究 Pitfall 1「裸名边假阳性灾难」）。

所以本模块的产出不是「一串受影响的符号」，是「一串**带可信度分层**的受影响符号」。
Phase 121 已经把四档 :class:`~services.code_graph.EdgeConfidence` 做进了装配层，
本模块负责把档位**一路透到 agent 眼前**——中间任何一层把档位抹平，这条纪律就断了。

方案（分层反向 BFS + 三重预算 + 确定性分级）
============================================
:func:`analyze_impact` 在一张**冻结**的 ``MultiDiGraph`` 上做逐层反向展开：

- **深度即分组**（D-05）：d1/d2/d3 直接对应 ``WILL_BREAK`` / ``LIKELY_AFFECTED`` /
  ``MAY_NEED_TESTING``，不做打分排序。同一符号在多层出现时取**最浅**那层
  （最坏情况优先），BFS 的首次访问天然就是最浅层。
- **path-min 置信度**（D-07）：一条路径的可信度取沿途各边的**最小值**——弱边决定
  强度。⛔ 不取平均（一条 ``resolved`` 边会把 ``bare_name`` 洗白），⛔ 不取乘积
  （深层路径的分数会塌到无法与浅层比较）。同层多条到达路径时取那些最小值里的
  **最大**者（widest-path 的层受限形式）。
- **三重预算**（威胁登记 T-122-遍历 DoS）：``max_depth`` 限层、``max_nodes`` 限遍历
  规模、``limit`` 限输出条数，三者各有独立标记，撞哪个都能在 ``summary`` 里看出来。
- **确定性风险四级**（D-15 + D-29）：:func:`grade_risk` 是纯函数，阈值写成模块级
  常量表，⛔ 不走 LLM。弱证据（全路径最高档只到 ``bare_name``）封顶 MEDIUM。

边界与已知翻车点
================
① **零 I/O、零 Django、零 ORM、零运行期 networkx**：本模块只吃一张已经过
   ``GraphService.get_graph()`` 三道闸的图对象，自己没有任何一条通往数据库的路
   （威胁登记 T-122-绕闸）。``networkx`` 只在 ``TYPE_CHECKING`` 里注解，照
   ``model.py`` 的 adapter seam 做法。

② 🚨 **绝不复制图**（D-01）。入参图是**跨请求共享**的冻结对象，缓存命中时所有调用方
   拿到的是同一个实例。本模块只读遍历，⛔ 不 ``graph.copy()``、⛔ 不
   ``graph.reverse(copy=True)``——RESEARCH 在 30k 节点 / 100k 边上实测：只读视图
   0.004ms，而复制要 330–690ms，**差五个数量级**。反向展开一律走
   ``graph.predecessors()``。也**不用** ``nx.bfs_layers``：它只给节点、给不出经由哪条
   边，而 path-min（D-07）与逐跳渲染两条都需要边信息。

③ 🚨 **源码正文永不出现在输出里**（D-17）。本内核只出 ``file:line`` 与符号名，正文
   由 agent 自己按需要再去读文件（既有 ``get_repository_file`` MCP 工具）。token 纪律
   是 agent 工具的生命线：生产热点符号的 d1 就能到 2,803 条，× 一段源码就是上下文爆炸。

④ **``reason`` 现推不存**（D-09）：输出时调 :func:`~services.code_graph.derive_reason`
   生成，⛔ 不在图边属性上新增第四个属性。

⑤ **输出是结构化 dict，不是渲染好的字符串**（D-10）。渲染留给壳层，让 MCP（JSON）
   与对话（markdown）两面各自决定形态。

⑥ **不吞 ``GraphError``**（D-03）：本模块根本不取图，没有可吞的异常。「``total_found``
   为 0」与「查询失败」在输出上是两种形态，翻译归壳层。
"""

from __future__ import annotations

import time
from collections import deque
from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType
from typing import TYPE_CHECKING, Any, Final

import structlog

from services.code_graph import EdgeConfidence, EdgeKind, confidence_score, derive_reason

if TYPE_CHECKING:
    # 仅供类型注解使用。⛔ 运行期绝不 import networkx —— 与 ``model.py`` 同一道
    # adapter seam：换图库时只需改 ``loader.py`` 与类型注解。
    import networkx as nx

logger = structlog.get_logger(__name__)

# 反向展开的默认层数上限（D-05）。取 3 不是为了省时间，是因为**超过 3 层对 agent
# 没有行动价值**：d4 之外的「受影响」在实践中已经弱到无法据以决定要不要改测试，
# 反而把真正该看的 d1 淹掉（GitNexus 同款纪律）。
DEFAULT_MAX_DEPTH: Final[int] = 3

# 输出条数上限（D-16）。生产解析边入度 max 2,803 / p99 25，热点符号上**必然触发**
# ——这不是理论边界，截断计数与排序是会被真实用到的功能。
DEFAULT_RESULT_LIMIT: Final[int] = 200

# 遍历规模软上限（威胁登记 T-122-遍历 DoS）。**输出截断挡不住遍历本身**：d1 就能到
# 近 3,000 条，d2/d3 是指数级，等到排序截断那一步内存与耗时已经花掉了。撞上本上限时
# 停止继续展开并置 ``summary["truncated_by_nodes"]``，让调用方知道影响面比看到的更大。
DEFAULT_MAX_NODES: Final[int] = 2000

# 深度 → 语义标签（D-05）。标签才是给 agent 看的契约，深度数字只是内部键。
DEPTH_LABELS: Final[Mapping[int, str]] = MappingProxyType(
    {
        1: "WILL_BREAK",
        2: "LIKELY_AFFECTED",
        3: "MAY_NEED_TESTING",
    }
)

# 置信档的**可比序**，D-15 第三个输入「路径最高置信档」的载体。
#
# ⚠️ 这与 ``confidence_score()`` 的**数值**是两个量，不要混用：
#   - **数值**（``resolved=1.0`` / ``bare_name=0.3`` / ``cross_repo=match_confidence``
#     原值）用于 ``min_confidence`` 过滤与 path-min 计算——它是连续量，且 cross_repo
#     档的值逐边不同。
#   - **档序**（本表）用于 D-29 的封顶判据——它回答的是「这条路径上出现过的最强证据
#     是哪一档」，是个离散的类别序。用数值代替档序会出错：一条 match_confidence=1.0
#     的跨仓边数值上与 resolved 打平，但它的证据强度并不等价。
_CONFIDENCE_TIER_RANK: Final[Mapping[EdgeConfidence, int]] = MappingProxyType(
    {
        EdgeConfidence.CHUNK_LEVEL: 0,
        EdgeConfidence.BARE_NAME: 1,
        EdgeConfidence.CROSS_REPO: 2,
        EdgeConfidence.RESOLVED: 3,
    }
)

# ``exclude_test_files=True`` 时用来识别测试文件的路径特征（启发式，非精确判定）。
# 各语言约定混在一起：Go 的 ``*_test.go``、Python 的 ``test_*.py`` 与 ``tests/`` 目录、
# 前端的 ``*.spec.ts`` / ``*.test.ts``。
_TEST_PATH_HINTS: Final[tuple[str, ...]] = ("_test.", "test_", "/tests/", ".spec.", ".test.")

# 事件名常量（形态对齐 ``signature.py`` / ``symbol_resolve.py``）。
# ⚠️ 前缀不得缩写：``code_graph_`` 是本包观测契约的强制前缀。
_EVENT_IMPACT_ANALYZED: Final[str] = "code_graph_impact_analyzed"

__all__ = [
    "DEFAULT_MAX_DEPTH",
    "DEFAULT_MAX_NODES",
    "DEFAULT_RESULT_LIMIT",
    "DEPTH_LABELS",
    "analyze_impact",
]


# 埋点自成函数、事件名常量直接写在 ``logger.debug`` 的第一个位置实参上，
# ⛔ 不抽成 ``_emit(event, **fields)`` 那样的通用转发器：``test_observability_contract``
# 要求事件名在**该调用点**可静态解析成字面量，包一层后 AST 只看得到一个形参名。
#
# 取 DEBUG 而非 INFO：agent 一次任务可能调几百次 impact，INFO 会直接刷屏，违反
# ``.cursor/rules/observability-logging.mdc`` 的级别纪律。
# 观测 best-effort —— 任何异常吞掉，绝不反噬分析主流程。


def _log_impact_analyzed(
    *, depth: int, returned: int, total_found: int, duration_ms: int
) -> None:
    """一次 :func:`analyze_impact` 恰**一条**结构化埋点。

    🚨 **只记计数与耗时，⛔ 不记符号名、不记文件路径、不记路径明细**
    （威胁登记 T-122-exclusion 回流）；🚨 **BFS 循环内零 ``logger.*``**
    （威胁登记 T-122-日志放大）——热点符号一次查询能走几千个节点，循环内哪怕
    DEBUG 也是日志放大。
    """
    try:
        logger.debug(
            _EVENT_IMPACT_ANALYZED,
            component="code_graph",
            category="sampling",
            depth=depth,
            returned=returned,
            total_found=total_found,
            duration_ms=duration_ms,
        )
    except Exception:  # noqa: BLE001 — 观测失败绝不反噬业务（不是安全降级分支）
        pass


@dataclass(frozen=True, slots=True)
class _Reach:
    """反向 BFS 里「到达一个符号的最优方式」。

    ``path_confidence`` 与 ``path_top_tier`` 描述的是**同一条**被选中的路径：前者是
    沿途最小值（D-07），后者是沿途最高档（D-29 的输入）。两个量方向相反不是笔误
    ——一条 ``resolved → bare_name`` 的路径，其强度由 ``bare_name`` 决定（min），
    但它「路上见过 resolved 这一档证据」也是事实（max），风险封顶要看后者。
    """

    depth: int
    path_confidence: float
    path_top_tier: int
    # 到达本符号所经的那条边，已渲染成输出形态（from/to/line_number/kind/confidence/reason）。
    via: dict[str, Any]


def _edge_score(attrs: Mapping[str, Any]) -> float:
    """一条边的置信度数值，供 ``min_confidence`` 过滤与 path-min 计算。

    ⛔ **不要在这里自建 ``{"resolved": 1.0, …}`` 数值表**：``cross_repo`` 档的分值是
    该行的 ``match_confidence`` **原值**（D-13，1.0 / 0.7 / 0.4 三档实测存在），自建
    常量表会把跨仓边的可信度静默抹成一个常量——而跨仓边恰恰是本相位可信度分层最需要
    如实透出的那一档。

    :raises ValueError: ``cross_repo`` 档缺 ``match_confidence``（``confidence_score``
        刻意抛错而非静默兜底，见其 docstring）；或档位未登记。
    """
    confidence = EdgeConfidence(attrs["confidence"])
    if confidence is EdgeConfidence.CROSS_REPO:
        return confidence_score(confidence, match_confidence=attrs["match_confidence"])
    return confidence_score(confidence)


def _bare_name_allowed(*, include_low_confidence: bool, min_confidence: float) -> bool:
    """D-08 的**双闸**：两道都开，``bare_name`` 边才参与扩散。

    两道闸问的是**两个不同的问题**，缺一不可：

    - ``include_low_confidence`` 问的是「这张图里到底有没有裸名边」。它是 Phase 121
      ``get_graph`` 的**缓存键分量之一**——为假时装配阶段根本没把裸名边装进图，本内核
      再怎么放宽门槛也无边可走。所以它表达的是**装配口径**。
    - ``min_confidence`` 问的是「本次查询愿不愿意看这一档」。同一张含裸名边的图，一次
      查询可以只看 ``resolved``，下一次可以把弱证据一并看进来；这是**查询口径**，与图
      怎么装的无关。

    单开任何一道都不足以放行。装配口径开着但查询门槛卡在 1.0 时，调用方要的是「只看
    强证据」，此时把 0.3 分的裸名边放进扩散会直接违背它的显式意图；反过来查询门槛降到
    0 但装配口径关着时，图里压根没有这一档边，放行也只是个空动作——但真正的风险在于
    它会让人以为「门槛调低了就等于看到了全部弱证据」，从而对一份其实缺了整档边的结果
    产生虚假的完整感。

    做成两道而不是一道，是为了让**一次误配置不足以**把裸名边的假阳性放出来（研究
    Pitfall 1）：生产解析率中位数只有 0.17，裸名边的基数远大于解析边，一旦它们无门槛
    地参与扩散，影响面会凭空膨胀整整几个子树，而假边在输出里与真边看起来毫无区别。

    :returns: 两道闸同时满足时为真。第二道的判据是「查询门槛不高于 ``bare_name`` 档的
        分值」——⛔ 不写死 ``0.3``，走 :func:`~services.code_graph.confidence_score`，
        免得 Phase 121 调整档位数值时本模块悄悄失配。
    """
    return include_low_confidence and min_confidence <= confidence_score(
        EdgeConfidence.BARE_NAME
    )


def _depth_label(depth: int) -> str:
    """深度 → 语义标签；超出 :data:`DEPTH_LABELS` 登记范围时落到最弱的那一档。

    ``max_depth`` 是调用方可传的参数，理论上能超过 3；标签表只登记到 3，超出部分
    并入 ``MAY_NEED_TESTING``——⛔ 不返回空串或 ``None``，那会让壳层渲染出一条没有
    档位的条目，等于把分层纪律在最外圈漏掉。
    """
    return DEPTH_LABELS.get(depth, "MAY_NEED_TESTING")


def _looks_like_test_file(file_path: str) -> bool:
    """``file_path`` 是否命中 :data:`_TEST_PATH_HINTS` 的测试文件特征（启发式）。"""
    lowered = file_path.lower()
    return any(hint in lowered for hint in _TEST_PATH_HINTS)


def _render_via(
    graph: nx.MultiDiGraph, caller_id: str, callee_id: str, attrs: Mapping[str, Any]
) -> dict[str, Any]:
    """把一条边渲染成输出条目里的 ``via`` 段。

    ``confidence`` / ``kind`` 取边属性**原值**（字符串），不折算成数值——三档语义标签
    才是契约，数值只是排序辅助（``model.py::EdgeConfidence`` docstring 的明文要求）。
    ``reason`` 由 :func:`~services.code_graph.derive_reason` 现推（D-09）。
    """
    kind = EdgeKind(attrs["kind"])
    confidence = EdgeConfidence(attrs["confidence"])
    callee_name = str(graph.nodes[callee_id].get("name") or callee_id)
    return {
        "from": caller_id,
        "to": callee_id,
        # 边上的 line_number 是**调用点**行号，与节点上的 start_line（定义处）不是一回事。
        "line_number": int(attrs.get("line_number") or 0),
        "kind": attrs["kind"],
        "confidence": attrs["confidence"],
        "reason": derive_reason(
            kind,
            confidence,
            callee_name=callee_name,
            match_confidence=attrs.get("match_confidence"),
        ),
    }


def _reverse_layers(
    graph: nx.MultiDiGraph,
    seed_id: str,
    *,
    max_depth: int,
    min_confidence: float,
    allow_bare_name: bool,
    max_nodes: int,
) -> tuple[dict[str, _Reach], bool]:
    """分层反向 BFS。返回 ``({symbol_id: _Reach}, truncated_by_nodes)``。

    返回值带第二项而不是只返 dict：``max_nodes`` 撞顶与「真的只有这么多」在结果
    形态上完全一样，不显式带出来，调用方就只能猜——而这正是 T-122-遍历 DoS 要求
    「三重预算各有独立标记」的那一条。

    实现纪律（逐条对应一个已知翻车点）：

    - 用 ``graph.predecessors(node)`` 逐层展开。⛔ **绝不** ``graph.copy()`` /
      ``graph.reverse(copy=True)``（实测 330–690ms，比只读视图慢五个数量级），
      也**不用** ``nx.bfs_layers``（给不出经由哪条边，D-07 与逐跳渲染两条都要）。
    - **首次访问即最浅层**（BFS 天然性质）⇒ 已在 ``best`` 里的节点直接跳过，这就是
      D-05 的「同符号多层出现取最浅」。
    - MultiDiGraph 上同一对符号可**并存多档边** ⇒ 必须
      ``for attrs in graph[pred][node].values()`` 逐条取。⛔ 不能把 ``graph[pred][node]``
      当单个属性 dict 用，那会把四档边契约在遍历这一层就丢掉。
    - 不合格的边**不参与扩散**（不是只在输出时过滤）：``score < min_confidence`` 或
      ``bare_name`` 档未获放行时直接跳过。因此提高 ``min_confidence`` 一定让结果集
      **单调收缩**。
    """
    if seed_id not in graph:
        # ⛔ 不能直接往下走：``graph.predecessors`` 对不存在的节点抛 ``NetworkXError``，
        # 而「符号不在图里」是调用方完全可能撞上的正常输入（被 exclusion 挡掉 / 不在
        # 本次子图内 / uid 打错），不该以异常形态穿透到壳层。
        return {}, False

    # 种子自身记 depth=0、path_confidence=1.0（空路径的最小值取幺元）、
    # path_top_tier 取最弱档（它不是「见过」任何证据，只是起点）。
    best: dict[str, _Reach] = {
        seed_id: _Reach(depth=0, path_confidence=1.0, path_top_tier=0, via={})
    }
    truncated_by_nodes = False
    frontier: deque[str] = deque([seed_id])

    for depth in range(1, max_depth + 1):
        # 本层的候选：pred -> (path_confidence, path_top_tier, 边属性, 被调方 node)
        candidates: dict[str, tuple[float, int, Mapping[str, Any], str]] = {}
        while frontier:
            node = frontier.popleft()
            node_reach = best[node]
            for pred in graph.predecessors(node):
                if pred in best:
                    continue
                for attrs in graph[pred][node].values():
                    confidence = EdgeConfidence(attrs["confidence"])
                    if not allow_bare_name and confidence is EdgeConfidence.BARE_NAME:
                        continue
                    score = _edge_score(attrs)
                    if score < min_confidence:
                        continue
                    # D-07：整条路径取最小值；同层多条到达路径取那些最小值里的最大者。
                    path_confidence = min(node_reach.path_confidence, score)
                    path_top_tier = max(
                        node_reach.path_top_tier, _CONFIDENCE_TIER_RANK[confidence]
                    )
                    previous = candidates.get(pred)
                    if previous is None or path_confidence > previous[0]:
                        candidates[pred] = (path_confidence, path_top_tier, attrs, node)

        if not candidates:
            break

        accepted: list[str] = []
        for pred, (path_confidence, path_top_tier, attrs, node) in candidates.items():
            if len(best) >= max_nodes:
                truncated_by_nodes = True
                break
            best[pred] = _Reach(
                depth=depth,
                path_confidence=path_confidence,
                path_top_tier=path_top_tier,
                via=_render_via(graph, pred, node, attrs),
            )
            accepted.append(pred)
        if truncated_by_nodes:
            break
        frontier = deque(accepted)

    return best, truncated_by_nodes


def _build_item(graph: nx.MultiDiGraph, symbol_id: str, reach: _Reach) -> dict[str, Any]:
    """一条输出条目。🚨 只出 ``file:line`` 与符号名，⛔ 永不带源码正文（D-17）。"""
    node = graph.nodes[symbol_id]
    return {
        "symbol_id": symbol_id,
        "name": str(node.get("name") or ""),
        "symbol_type": str(node.get("symbol_type") or ""),
        "file_path": str(node.get("file_path") or ""),
        "start_line": int(node.get("start_line") or 0),
        "depth": reach.depth,
        "label": _depth_label(reach.depth),
        "path_confidence": reach.path_confidence,
        "path_top_tier": reach.path_top_tier,
        "via": reach.via,
    }


def analyze_impact(
    graph: nx.MultiDiGraph,
    seed_symbol_id: str,
    *,
    max_depth: int = DEFAULT_MAX_DEPTH,
    min_confidence: float = 1.0,
    include_low_confidence: bool = False,
    limit: int = DEFAULT_RESULT_LIMIT,
    max_nodes: int = DEFAULT_MAX_NODES,
    exclude_test_files: bool = False,
    crosses_repo: bool = False,
) -> dict[str, Any]:
    """对一个符号做反向依赖分析，返回**结构化 dict**（D-10，渲染归壳层）。

    :param graph: 已经过 ``GraphService.get_graph()`` 三道闸的**冻结**只读图。本函数
        全程只读，⛔ 不复制、不修改（D-01）。
    :param seed_symbol_id: 种子符号的 uid。不在图里时返回空结果并置
        ``seed_in_graph=False``——「符号不存在」与「没有影响」必须能被壳层区分开，
        后者才是可以据以决定「改这里安全」的结论。
    :param max_depth: 反向展开层数上限，默认 :data:`DEFAULT_MAX_DEPTH`。
    :param min_confidence: 边的置信度数值下限，按 ``confidence_score()`` 的数值映射比较
        （D-06）。两条语义要记住：① 过滤发生在**扩散**阶段而不是输出阶段——不合格的边
        不参与 BFS 推进，因此提高本参数一定让结果集**单调收缩**（这是条可测性质）；
        ② ``cross_repo`` 档参与比较时用该行的 ``match_confidence`` **原值**，⛔ 不归一化
        到本仓的档位数值（D-13）——跨仓边的可信度来源与本仓完全不同，折算成同一个常量
        再比较，比较出来的东西没有意义。
    :param include_low_confidence: 声明本次查询愿意看 ``bare_name`` 档。⚠️ 单开它
        **不足以**放行，另一道闸见 :func:`_bare_name_allowed`。
    :param limit: 输出条数上限，默认 :data:`DEFAULT_RESULT_LIMIT`。
    :param max_nodes: 遍历规模软上限，默认 :data:`DEFAULT_MAX_NODES`。
    :param exclude_test_files: 为真时在**输出**阶段丢弃测试文件里的符号。⛔ 它不影响
        扩散——测试文件里的调用同样是真实调用链的一环，在扩散阶段砍掉会把「经由测试
        文件到达的生产代码」整段切没。
    :param crosses_repo: 本次分析是否穿了仓，由壳层透传（内核自己不感知跨仓，D-25：
        图里 ``kind == "cross_repo"`` 的边两端其实都在本仓）。
    """
    started = time.perf_counter()

    allow_bare_name = _bare_name_allowed(
        include_low_confidence=include_low_confidence, min_confidence=min_confidence
    )
    reached, truncated_by_nodes = _reverse_layers(
        graph,
        seed_symbol_id,
        max_depth=max_depth,
        min_confidence=min_confidence,
        allow_bare_name=allow_bare_name,
        max_nodes=max_nodes,
    )

    items = [
        _build_item(graph, symbol_id, reach)
        for symbol_id, reach in reached.items()
        if symbol_id != seed_symbol_id
    ]
    if exclude_test_files:
        items = [item for item in items if not _looks_like_test_file(item["file_path"])]

    # 排序键必须在截断之前算完（D-16），否则截掉的可能正是最该看的那几条。
    # 第三键 ``symbol_id`` 保证同深度同置信度时的顺序在不同 worker 上可复现。
    items.sort(key=lambda item: (item["depth"], -item["path_confidence"], item["symbol_id"]))

    groups: dict[int, list[dict[str, Any]]] = {
        depth: [item for item in items if item["depth"] == depth]
        for depth in range(1, max_depth + 1)
    }

    duration_ms = int((time.perf_counter() - started) * 1000)
    _log_impact_analyzed(
        depth=max_depth,
        returned=len(items),
        total_found=len(items),
        duration_ms=duration_ms,
    )

    return {
        "seed_symbol_id": seed_symbol_id,
        "seed_in_graph": seed_symbol_id in graph,
        "max_depth": max_depth,
        "min_confidence": min_confidence,
        "include_low_confidence": include_low_confidence,
        # 两道闸的**合成结果**，与上面那个入参分开透出：调用方传了
        # include_low_confidence=True 却因为门槛太高而没看到任何裸名边时，得能一眼看出
        # 是自己把第二道闸关着，而不是「这个符号确实没有弱证据调用方」。
        "bare_name_included": allow_bare_name,
        "crosses_repo": crosses_repo,
        "truncated_by_nodes": truncated_by_nodes,
        "items": items,
        "groups": groups,
    }
