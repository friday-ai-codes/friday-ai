"""图内**符号解析器** —— uid 优先 + 重名候选列表（Phase 122，IMPACT-05 / D-19）。

问题背景
========
生产库 base 分支 562,465 个符号里，``(repository_id, name)`` 只有 **80.7%** 是唯一的
——**19.3% 的名字在仓内重名**，其中 2,436 个名字（1.2%）对应 >20 个符号。也就是说
「按名字找符号」这件事，**五次里有一次会撞上多个答案**。

所以候选列表是**主路径**，不是异常兜底。impact 与 trace 两个内核如果各写一份解析，
「⛔ 绝不静默取第一个」这条 REQUIREMENTS 明文要求必然会在其中一处漂移——本模块因此
单独成文件，两个内核共用。

方案（两段式：uid 直命中 / 名字收窄后给候选）
============================================
:func:`resolve_symbol_in_graph` 只有两条路径：

- 传了 ``symbol_id`` ⇒ **uid 优先**，在图里就直接命中，不在图里就明确落空。
  这条分支**绝不**退化去按名字搜——agent 拿到过一次候选列表后带 uid 回来，就该拿到
  确定的答案，而不是又一轮模糊匹配。
- 只传 ``name`` ⇒ 精确匹配节点 ``name``，再用可选的 ``file_path`` / ``symbol_type``
  一次性收窄（RESEARCH Pitfall 2 §4：能一次收敛就不要往返两轮）。命中多个时返回
  排序且限条数的候选列表，**永不**替调用方做选择。

与 Phase 121 ``loader.py`` 的 ``_AMBIGUOUS`` 哨兵语义相反、方向一致：loader 遇同文件
同名撞车时**放弃解析**返回 ``None``，本模块遇歧义**返回候选列表**——两者都拒绝静默
取第一个，只是一个交给调用方消歧、一个直接认输。

边界与已知翻车点
================
① **纯函数、零 I/O**：运行期只 import stdlib + ``structlog``，⛔ 零 Django、零 ORM、
   零运行期 ``networkx``（图对象只在 ``TYPE_CHECKING`` 里注解，照 ``model.py`` 的
   adapter seam 做法）。本模块只吃一张**已经过 ``GraphService.get_graph()`` 三道闸**
   的图，自己没有任何一条通往数据库的路（威胁登记 T-122-绕闸）。

② **``signature`` 在图内恒为空串**：``loader.py:354-356`` 明确不取 ``Symbol.signature``
   （TextField，可长达数 KB），节点属性恒 5 个。D-19 要求候选条目带 ``signature``，
   那一列只能由壳层用 ``Symbol.objects.filter(id__in=…)`` 回 ORM 补取。见
   :attr:`SymbolCandidate.signature`。

③ **不进 barrel**（D-28）：本模块与 ``impact`` / ``trace`` 同属「经 ``get_graph`` 拿到
   图之后的纯消费者」，壳层直连合法。理由写在 ``__init__.py`` 的 docstring 里。

④ **埋点不记符号名与文件路径**（威胁登记 T-122-exclusion 回流）：被排除文件的符号本
   就不在图里（``loader.py:401`` 装配阶段已过滤），日志侧也不给第二条泄漏通路。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Final

import structlog

if TYPE_CHECKING:
    # 仅供类型注解使用。⛔ 运行期绝不 import networkx —— 与 ``model.py`` 同一道
    # adapter seam：换图库时只需改 ``loader.py`` 与类型注解。
    import networkx as nx

logger = structlog.get_logger(__name__)

# 候选列表条数上限。取 20 的依据是生产分布（RESEARCH Pitfall 2 的重名直方图）：
# 只有 **1.2%** 的名字对应 >20 个符号，20 条已覆盖绝大多数消歧场景；真超出时靠
# :attr:`SymbolResolution.total_candidates` 与 :attr:`SymbolResolution.truncated`
# 让 agent 知道自己看到的不是全部——⛔ 不能让它以为候选就这么多而在错的集合里挑。
CANDIDATE_LIMIT: Final[int] = 20

# 事件名常量（形态对齐 ``signature.py`` / ``access.py``）。
# ⚠️ 前缀不得缩写：``code_graph_`` 是本包观测契约的强制前缀。
_EVENT_SYMBOL_AMBIGUOUS: Final[str] = "code_graph_symbol_ambiguous"

__all__ = [
    "CANDIDATE_LIMIT",
    "SymbolCandidate",
    "SymbolResolution",
    "resolve_symbol_in_graph",
]


# 埋点自成函数、事件名常量直接写在 ``logger.debug`` 的第一个位置实参上，
# ⛔ 不抽成 ``_emit(event, **fields)`` 那样的通用转发器：``test_observability_contract``
# 要求事件名在**该调用点**可静态解析成字面量，包一层后 AST 只看得到一个形参名。
#
# 取 DEBUG 而非 INFO：重名是 19.3% 的主路径，INFO 会直接刷屏，违反
# ``.cursor/rules/observability-logging.mdc`` 的级别纪律。
# 观测 best-effort —— 任何异常吞掉，绝不反噬解析主流程。


def _log_symbol_ambiguous(
    *, name_length: int, candidate_count: int, total_candidates: int
) -> None:
    """重名歧义的结构化埋点。

    🚨 **只记长度与计数，⛔ 不记符号名本身、不记 ``file_path``、不逐候选打日志**
    （威胁登记 T-122-exclusion 回流 / T-122-日志放大）。符号名与路径是本模块唯一的
    外泄面，而计数已足够回答运维要问的那个问题：「重名消歧被触发得有多频繁、
    候选面有多大」。
    """
    try:
        logger.debug(
            _EVENT_SYMBOL_AMBIGUOUS,
            component="code_graph",
            category="sampling",
            name_length=name_length,
            candidate_count=candidate_count,
            total_candidates=total_candidates,
        )
    except Exception:  # noqa: BLE001 — 观测失败绝不反噬业务（不是安全降级分支）
        pass


@dataclass(frozen=True, slots=True)
class SymbolCandidate:
    """重名消歧时交给 agent 的**一条**候选，字段面对齐 D-19 的明文要求。

    ``file_path`` + ``start_line`` 合起来就是 D-19 要的 ``file:line``——agent 靠它加
    ``symbol_type`` 就能在多数场景下二选一，不必回头读源码。
    """

    symbol_id: str
    name: str
    symbol_type: str
    file_path: str
    start_line: int
    # 🚨 本模块产出的候选里，这一项**恒为空串**，不是 bug。
    # ``loader.py:354-356``：``Symbol.signature`` 是 TextField、可长达数 KB，装配图时
    # **刻意不取**，节点属性恒 5 个（name / symbol_type / file_path / start_line /
    # end_line）里根本没有它。D-19 要求候选带 signature，那一列只能由壳层用
    # ``Symbol.objects.filter(id__in=[c.symbol_id …]).values_list("id", "signature")``
    # 回 ORM 补取并截断到 200 字符（D-17 的 token 纪律）。
    # ⛔ 不要为了「填上它」而在本模块里 import ORM —— 那会一次性破掉 D-01 分层与
    # 本模块的零 I/O 契约。
    signature: str = ""


@dataclass(frozen=True, slots=True)
class SymbolResolution:
    """一次解析的完整结果。

    不变式（两个内核与壳层都可以依赖）::

        resolved is not None  ⇒  candidates == () and total_candidates == 1
        candidates != ()      ⇒  resolved is None and total_candidates >= 2

    换句话说：**要么给出唯一答案，要么把选择权交回去**，绝不存在「给了 resolved
    又附一堆候选」这种让调用方误以为可以直接用第一个的中间态。
    """

    # 唯一命中的 ``symbol_id``；歧义或落空时为 ``None``。
    resolved: str | None
    # 歧义时的候选列表（已排序、已截断）；其余情形恒为空元组。
    candidates: tuple[SymbolCandidate, ...]
    # **截断前**的命中总数。落空 0 / 唯一命中 1 / 歧义 ≥2。
    total_candidates: int
    # ``total_candidates > CANDIDATE_LIMIT`` ⇒ 调用方看到的不是全部。
    truncated: bool
    # 本次解析用的查询词（uid 分支是 ``symbol_id``，名字分支是 ``name``），供壳层回显。
    query: str


def _file_path_matches(node_path: str, wanted: str) -> bool:
    """``file_path`` 收窄判据：相等，或调用方给的是一段**路径后缀**。

    兼容 agent 只记得 ``api/user.go`` 而图里存的是 ``internal/api/user.go`` 的情形。

    ⚠️ 后缀匹配必须卡在 ``/`` 边界上：裸 ``endswith`` 会让 ``r.go`` 匹上
    ``user.go``，那种「收窄参数反而放进了不相干的符号」比不支持后缀更糟——调用方
    会以为自己已经消歧成功。
    """
    wanted = wanted.strip().lstrip("./")
    if not wanted:
        return True
    return node_path == wanted or node_path.endswith("/" + wanted)


def resolve_symbol_in_graph(
    graph: nx.MultiDiGraph,
    *,
    symbol_id: str | None = None,
    name: str | None = None,
    file_path: str | None = None,
    symbol_type: str | None = None,
) -> SymbolResolution:
    """在**图内**定位一个符号：uid 优先，重名给候选列表（D-19）。

    :param graph: 已经过 ``GraphService.get_graph()`` 三道闸的只读图。本函数**只读**，
        不修改任何节点或边（入参图通常是冻结的）。
    :param symbol_id: 符号 uid。**给了就只走这条路**，见下方「uid 优先」。
    :param name: 符号名，**大小写敏感**精确匹配（``Handler`` ≠ ``handler``：本仓
        Go/TS 里首字母大小写是导出与否的语义差别，模糊掉它等于把两个不同的符号混为
        一谈）。
    :param file_path: 可选收窄——相等或路径后缀，见 :func:`_file_path_matches`。
    :param symbol_type: 可选收窄——**大小写不敏感**（``function`` / ``FUNCTION`` 在
        各产出器之间口径不一，这里不该让调用方猜）。

    **uid 优先**（``symbol_id`` 非空时）：

    - 在图里 ⇒ ``resolved=symbol_id``、``candidates=()``、``total_candidates=1``。
    - 不在图里 ⇒ ``resolved=None``、``total_candidates=0``。让壳层能把「这个符号不
      存在」与「存在但被 exclusion 挡掉 / 不在本次子图内」当作同一件事来报——两者
      对调用方的建议是一样的（换个符号或换个仓库再试），而**区分它们会泄漏被排除
      文件的存在性**。
    - ⛔ 这条分支**绝不**因为 uid 落空就退化成按 ``name`` 搜：那会让「带 uid 回来」
      这个消歧闭环失去意义，agent 拿不准自己收到的到底是不是自己点的那一个。

    **名字路径**：命中 0 个 ⇒ 三项全空；恰 1 个 ⇒ ``resolved`` 置该 id；≥2 个 ⇒
    ``resolved=None``，按 ``(file_path, start_line, symbol_id)`` 稳定排序后取前
    :data:`CANDIDATE_LIMIT` 条。``total_candidates`` 记的是**未截断前**的总数。

    🚨 排序键的第三项 ``symbol_id`` 不是凑数：同文件同名多符号（生产 24,312 组）在
    前两项上完全打平，少了它候选顺序就依赖 ``graph.nodes`` 的插入序，同一次查询在两个
    worker 上可能给出不同的前 20 条。
    """
    if symbol_id:
        found = symbol_id in graph
        return SymbolResolution(
            resolved=symbol_id if found else None,
            candidates=(),
            total_candidates=1 if found else 0,
            truncated=False,
            query=symbol_id,
        )

    if not name:
        return SymbolResolution(
            resolved=None, candidates=(), total_candidates=0, truncated=False, query=""
        )

    wanted_type = symbol_type.strip().lower() if symbol_type else None

    matches: list[SymbolCandidate] = []
    for node_id, attrs in graph.nodes(data=True):
        if attrs.get("name") != name:
            continue
        node_path = str(attrs.get("file_path") or "")
        if file_path and not _file_path_matches(node_path, file_path):
            continue
        if wanted_type and str(attrs.get("symbol_type") or "").lower() != wanted_type:
            continue
        matches.append(
            SymbolCandidate(
                symbol_id=str(node_id),
                name=name,
                symbol_type=str(attrs.get("symbol_type") or ""),
                file_path=node_path,
                start_line=int(attrs.get("start_line") or 0),
                # 恒空串，由壳层回 ORM 补取，理由见字段注释。
                signature="",
            )
        )

    total = len(matches)
    if total == 0:
        return SymbolResolution(
            resolved=None,
            candidates=(),
            total_candidates=0,
            truncated=False,
            query=name,
        )
    if total == 1:
        return SymbolResolution(
            resolved=matches[0].symbol_id,
            candidates=(),
            total_candidates=1,
            truncated=False,
            query=name,
        )

    matches.sort(key=lambda c: (c.file_path, c.start_line, c.symbol_id))
    kept = tuple(matches[:CANDIDATE_LIMIT])
    _log_symbol_ambiguous(
        name_length=len(name), candidate_count=len(kept), total_candidates=total
    )
    return SymbolResolution(
        resolved=None,
        candidates=kept,
        total_candidates=total,
        truncated=total > CANDIDATE_LIMIT,
        query=name,
    )
