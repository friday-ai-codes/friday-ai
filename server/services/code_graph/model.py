"""``code_graph`` 契约层 —— 边种类、四档置信度与 ``reason`` 现推函数。

（模块 docstring 由 Plan 121-02 Task 3 补齐为「问题背景 / 方案 / 边界」三段式，
并写入三条要传给 Phase 122+ 的跨相位纪律。）
"""

from __future__ import annotations

from collections.abc import Mapping
from enum import Enum
from types import MappingProxyType
from typing import TYPE_CHECKING, Final

if TYPE_CHECKING:
    # 仅供类型注解使用。⛔ 运行期绝不 import networkx：这是为「未来换 rustworkx」
    # 保留的 adapter seam，上层只 import 本模块的契约类型即可写出输出结构。
    import networkx as nx  # noqa: F401


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
