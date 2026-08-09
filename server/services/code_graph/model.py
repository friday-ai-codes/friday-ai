"""``code_graph`` 契约层 —— 边种类、四档置信度与 ``reason`` 现推函数。

（模块 docstring 由 Plan 121-02 Task 3 补齐为「问题背景 / 方案 / 边界」三段式，
并写入三条要传给 Phase 122+ 的跨相位纪律。）
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from types import MappingProxyType
from typing import TYPE_CHECKING, Final

if TYPE_CHECKING:
    # 仅供类型注解使用。⛔ 运行期绝不 import networkx：这是为「未来换 rustworkx」
    # 保留的 adapter seam，上层只 import 本模块的契约类型即可写出输出结构。
    import networkx as nx


class EdgeKind(str, Enum):
    """边的**种类**（数据来源维度），与 :class:`EdgeConfidence` 正交。

    取 ``(str, Enum)`` 而非 ``models.TextChoices``：本模块是 service 层契约、
    不落库（写法对齐 ``agents/call_source.py::CallSource``）。
    """

    CALL = "call"
    CHUNK = "chunk"
    CROSS_REPO = "cross_repo"


class EdgeConfidence(str, Enum):
    """边的**可信度**四档（本相位定型，Phase 122–127 全部上层工具复用）。

    四档的来源与「默认是否参与扩散」：

    - ``resolved``：``CallEdge.callee_symbol IS NOT NULL``，被调方已解析到具体
      ``Symbol`` 外键。**默认参与扩散**。
    - ``bare_name``：``CallEdge.callee_symbol IS NULL``，只有 ``callee_name``
      字符串兜底。**默认不参与扩散**——须调用方显式
      ``include_low_confidence=True`` 才装载，且装载时仍要过三道过滤
      （同目录优先 / ``callee_qualifier`` 匹配 / :data:`BARE_NAME_BLACKLIST`）。
    - ``cross_repo``：``CrossRepoApiCall``，携带该行的 ``match_confidence``
      **原值**（1.0 / 0.7 / 0.4 三档），不归一化。**默认参与扩散**。
    - ``chunk_level``：ChunkEdge 粒度的共现证据，与 ``bare_name`` 语义等价档。
      **默认关**——chunk 与 symbol 是不同粒度，只作补充证据面旁挂
      （见 :class:`ChunkEvidence`），不进图的边集。

    ⚠️ **三档语义标签才是契约**，:func:`confidence_score` 的数值只是排序/过滤
    辅助。上层不要把数值写进面向用户的输出，要写标签。
    """

    RESOLVED = "resolved"
    BARE_NAME = "bare_name"
    CROSS_REPO = "cross_repo"
    CHUNK_LEVEL = "chunk_level"


# 静态数值映射（供 ``min_confidence`` 过滤与结果排序用）。
# ⚠️ CROSS_REPO **刻意不入表**：它取边自带的 match_confidence 原值，不归一化，
#    所以 confidence_score() 对该档要求显式传参，缺参直接抛错而非静默取默认。
_STATIC_CONFIDENCE_SCORE: Final[Mapping[EdgeConfidence, float]] = MappingProxyType(
    {
        EdgeConfidence.RESOLVED: 1.0,
        EdgeConfidence.BARE_NAME: 0.3,
        # chunk_level 与 bare_name 同为「弱证据」语义等价档，取同一数值。
        EdgeConfidence.CHUNK_LEVEL: 0.3,
    }
)


def confidence_score(
    confidence: EdgeConfidence,
    *,
    match_confidence: float | None = None,
) -> float:
    """把置信度档位折算成 ``[0, 1]`` 数值，供 ``min_confidence`` 过滤/排序使用。

    **三档语义标签才是契约，数值只是排序/过滤辅助**——不要让数值反向定义档位，
    也不要在用户可见输出里用数值替代标签。

    :param confidence: 置信度档位。
    :param match_confidence: 仅 ``cross_repo`` 档需要，取 ``CrossRepoApiCall``
        行上的原值（不归一化）。该档缺参视为调用方 bug，抛 ``ValueError``
        而非静默兜底——静默兜底会让跨仓边的可信度凭空变成常量。
    :raises ValueError: ``cross_repo`` 档未传 ``match_confidence``，或档位未登记。
    """
    if confidence is EdgeConfidence.CROSS_REPO:
        if match_confidence is None:
            raise ValueError(
                "cross_repo 档必须显式传入 match_confidence（取 CrossRepoApiCall 原值，不归一化）"
            )
        return float(match_confidence)
    try:
        return _STATIC_CONFIDENCE_SCORE[confidence]
    except KeyError:
        raise ValueError(f"未登记数值映射的置信度档：{confidence!r}") from None


def derive_reason(
    kind: EdgeKind,
    confidence: EdgeConfidence,
    *,
    callee_name: str | None = None,
    match_confidence: float | None = None,
) -> str:
    """现推一条边的人类可读理由，供工具输出直接引用。

    🚨 **D-08 纪律：``reason`` 在输出时现推，不得作为第 4 个边属性写进图。**
    RESEARCH 实测（networkx 3.6.1 / CPython 3.14）：边属性 1–3 个的内存成本
    **完全相同**（CPython 小字典预分配），第 4 个属性才跳一级
    （+143 B/边 vs +120 B/边）。边属性维持在 ``kind`` / ``confidence`` /
    ``line_number`` 三个以内，30 万边可省约 6.9MB，且零功能损失——理由字符串
    本来就只在输出那一刻才需要。

    :param kind: 边种类，仅用于未登记档位的兜底文案。
    :param confidence: 置信度档位，决定文案形态。
    :param callee_name: ``bare_name`` 档的被调名（会嵌进文案供人核对）。
    :param match_confidence: ``cross_repo`` 档的原值。
    """
    if confidence is EdgeConfidence.RESOLVED:
        return "callee_symbol resolved via FK"
    if confidence is EdgeConfidence.BARE_NAME:
        return f"name-only match on '{callee_name or '<unknown>'}'"
    if confidence is EdgeConfidence.CROSS_REPO:
        if match_confidence is None:
            return "cross-repo api match_confidence=unknown"
        return f"cross-repo api match_confidence={match_confidence:g}"
    if confidence is EdgeConfidence.CHUNK_LEVEL:
        return "chunk-level co-occurrence evidence"
    # 未来新增档位时的兜底：仍给出可读字符串，绝不抛错打断输出链路。
    return f"{kind.value} edge, confidence={confidence.value}"


# 裸名边的常见名黑名单：跨目录同名命中率极高，纳入扩散会制造假阳性灾难
# （研究 Pitfall「裸名边假阳性」）。仅在 include_low_confidence=True 时才会走到
# 裸名装载，即便如此这些名字也一律丢弃。
BARE_NAME_BLACKLIST: Final[frozenset[str]] = frozenset(
    {
        "get",
        "set",
        "run",
        "handle",
        "main",
        "init",
        "new",
        "close",
        "read",
        "write",
        "start",
        "stop",
        "send",
        "parse",
        "format",
        "String",
        "Error",
    }
)

# resolved / (resolved + bare_name) 低于该值时，图元数据置 low_resolution=True，
# 上层工具须在输出头部声明「本仓解析率偏低，影响面可能偏保守」。
# ⚠️ 经验值，由 Plan 121-10 的「per repo / per language 解析率统计」交付物复校
#    （RESEARCH Gap A5）。改动前先看那份数据，不要凭感觉调。
LOW_RESOLUTION_THRESHOLD: Final[float] = 0.6

# 跨仓遍历穿到未授权仓库时，整仓折叠成该占位符（不泄漏仓库名/符号名/文件路径）。
# 折叠动作本身在 Phase 122 的跨仓 impact 里实现，本相位先把契约字面量定好，
# 避免两边各写一个字符串导致前后端/工具间对不上。
REDACTED_REPOSITORY: Final[str] = "redacted_repository"


@dataclass(frozen=True, slots=True)
class ChunkEvidence:
    """ChunkEdge 的**旁挂证据面**——按 ``symbol_id`` 索引，⛔ 不进图的边集。

    为什么不展开成符号级边：``ChunkEdge`` 连的是 ``source_chunk_id`` /
    ``target_chunk_id``（UUID 软引用，无 FK），要挂到符号上只能靠
    ``Symbol.chunk_id`` 反查；而**一个 chunk 通常含多个 Symbol**，两端各 k 个
    符号时一条 chunk 边会展开成 k² 条符号边（RESEARCH Pitfall 2 的笛卡尔爆炸）。
    chunk 与 symbol 本就是不同粒度，强行对齐既贵又不准。

    因此本类型是与 :class:`CodeGraph.graph` **并列**的第二数据面：上层工具可以
    把它当补充证据引用（"这两个符号所在的 chunk 有共现关系"），但不参与符号级
    扩散，档位记 :attr:`EdgeConfidence.CHUNK_LEVEL`，默认关。
    """

    source_chunk_id: str
    target_chunk_id: str
    edge_type: str
    weight: float
    # 跨仓 chunk 边的对端仓库；同仓边为 None。
    target_repository_id: str | None


@dataclass(frozen=True, slots=True)
class GraphMeta:
    """一张图的元数据——上层工具向用户/agent 声明「结果有多可信」的唯一依据。

    四个**标记类**字段（:attr:`partial_edges` / :attr:`degraded` /
    :attr:`low_resolution` / :attr:`cross_repo_unresolved_count`）刻意设为必填、
    无默认值：漏透出会在 review 阶段暴露，而不是变成一次静默的错误结论。

    仅凭本对象就能写出四条输出声明：本仓解析率偏低 / 边未建完 / 已降级为按需
    子图 / N 条跨仓边无法定位。
    """

    repository_id: str
    branch: str

    node_count: int
    edge_count: int
    # nodes * NODE_COST + edges * EDGE_COST 的线性估算（非 sys.getsizeof 递归）。
    estimated_bytes: int

    # resolved / (resolved + bare_name)。
    resolution_rate: float
    # 🔔 上层工具必须透出：低于 LOW_RESOLUTION_THRESHOLD，影响面可能偏保守。
    low_resolution: bool

    # 🔔 上层工具必须透出：水位已推进但边未建完，图是「半新」的。
    partial_edges: bool
    # partial_edges 为真时的在途原因（供排障）；非在途为空串，不用 None
    # ——省掉上层一次 Optional 判空，空串即「无」。
    partial_reason: str

    # 🔔 上层工具必须透出："" 或 "on_demand_subgraph"（超预算大仓不缓存、
    # 只装配种子符号周边的诱导子图，结论覆盖面小于全图）。
    degraded: str

    # 🔔 上层工具必须透出：CrossRepoApiCall 两端只有 (file_path, name) 字符串、
    # 没有 Symbol FK，二次解析失败的边直接丢弃（D-05，不建虚拟节点污染深度分组），
    # 这里如实上报被丢弃的条数。
    cross_repo_unresolved_count: int
    # 语义缺口，必须如实声明：ApiCallSite 没有 branch_name 字段，跨仓边无法按
    # 分支过滤——feature 分支上看到的跨仓边其实是全分支合集。
    cross_repo_branch_unfiltered: bool

    # 被 exclusion 规则拦掉的文件数（节点连同邻接边一并丢弃，装配阶段就过滤）。
    excluded_file_count: int

    # 复合签名：水位 ‖ 两条边构建轨 ‖ 计数 ‖ exclusion 规则指纹。取图时复算比对。
    built_signature: str
    built_at: datetime


@dataclass(frozen=True, slots=True)
class CodeGraph:
    """一次装配的产物：元数据 + 符号图 + 旁挂的 chunk 证据面。

    **图对象是 ``MultiDiGraph`` 而非 ``DiGraph``**（D-01）：实测确认 ``DiGraph``
    对同一符号对的第二条边是**静默覆盖**——三条不同 ``kind`` 的 A→B 边最终只剩
    最后一条，四档边契约会直接失效。代价是 +224 字节/边（100k 节点 / 300k 边下
    153.88MB → 221.08MB，**+44%**），已接受，``EDGE_COST`` 常数按 MultiDiGraph 标定。

    属性个数是**内存契约**，不要随手加字段：

    - 节点属性恒为 5 个：``name`` / ``symbol_type`` / ``file_path`` /
      ``start_line`` / ``end_line``。⛔ ``Symbol.signature`` 是 TextField、可长达
      数 KB，绝不放进节点属性。
    - 边属性恒为 3 个：``kind`` / ``confidence`` / ``line_number``。**唯一例外**
      是 ``cross_repo`` 边额外带 ``match_confidence``——该档边数量在千级，第 4
      个属性的阶跃成本可忽略。
    - ``reason`` **不在其中**，由 :func:`derive_reason` 在输出时现推（D-08）。
    """

    meta: GraphMeta
    graph: nx.MultiDiGraph
    # 键 = symbol_id。值用 tuple 而非 list：本对象 frozen，证据面同样不可变，
    # 免得上层拿到后就地 append 污染缓存里的同一张图。
    chunk_evidence: Mapping[str, tuple[ChunkEvidence, ...]] = field(default_factory=dict)
