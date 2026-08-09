"""内存符号图的**装配层** —— ORM 批量取数 + ``MultiDiGraph`` 组装（Phase 121，GRAPH-01/GRAPH-04）。

问题背景
========
上层的每一个图分析工具（impact / trace / detect_changes / rename_preview …）都需要
同一张「符号 → 符号」的有向图，而这张图的原料散在四张表里、带两套分支语义、还要
先过 exclusion。如果每个工具各自取数，10 万级行数下的取数写法差异（``list(qs)``
实例化模型 vs ``values_list + iterator``）就是数量级的差异，而 exclusion 只要漏接
一处就会把 ``.env`` / ``*.pem`` 的符号名泄漏出去。

方案（ORM 独占 + 装配阶段过滤）
================================
本模块是本相位**唯一碰 ORM 的地方**，全同步，由 ``cache.py`` 一次性
``sync_to_async`` 包裹（RESEARCH Pattern 1：一次跳转，且同步侧可以放心用
``threading`` 锁而不必担心持锁 await）。取数一律 ``values_list(...).iterator(...)``，
FK 走 attname（``caller_symbol_id``）避免隐式 JOIN。

⛔ **纯算法层不得碰 ORM**：Phase 122 起的遍历/影响面算法只接受一个装配好的
``CodeGraph``，把 ORM 混进算法会让那些算法无法单测（要拉起 Django + 造数据才能跑
一次 BFS）。这条分层是本模块存在的理由。

边界
====
① **图对象是 ``MultiDiGraph``**（121-CONTEXT D-01），⛔ 不是 ``DiGraph``。实测确认
   ``DiGraph.add_edge(u, v, ...)`` 对同一对节点的第二次调用是**静默覆盖**——三条
   不同 ``kind`` 的 A→B 边最终只剩最后一条，四档边契约直接失效。代价 +224 字节/边
   （+44% 内存）已在 CONTEXT 接受。

② **属性个数是内存契约**：节点恒 5 个（``name`` / ``symbol_type`` / ``file_path`` /
   ``start_line`` / ``end_line``），⛔ 绝不取 ``Symbol.signature``（TextField 可长达数
   KB，放进节点属性会让线性内存估算彻底失准）。边恒 3 个（见 Plan 121-05 Task 3）。

③ **分支语义是 overlay**：``""`` 是 base 全量，feature 分支只写增量行。取数必须
   ``branch_name__in=["", branch]``，去重键取**整文件**（D-06）。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Final

import networkx as nx
import structlog

logger = structlog.get_logger(__name__)

# ORM 批量取数的游标批大小（Postgres 上走服务端游标）。与 RESEARCH §Code Examples 1
# 给出的形状一致；不做成 settings —— 它是取数实现细节，不是运维旋钮。
_SYMBOL_CHUNK_SIZE: Final[int] = 5000

# 节点属性键集合。个数写死在这里供用例引用：**恒 5 个**，多一个就会让
# ``NODE_COST_BYTES`` 的标定假设失效（RESEARCH §Byte Estimation 的属性敏感性表）。
_NODE_ATTR_KEYS: Final[frozenset[str]] = frozenset(
    {"name", "symbol_type", "file_path", "start_line", "end_line"}
)


def _branch_filter(branch: str) -> list[str]:
    """overlay 分支过滤器 —— 空 branch 只取 base，非空取 base ∪ 本分支。

    🚨 RESEARCH Pitfall 3：本仓的分支语义是 **overlay**，``branch_name=""`` 是 base
    全量、feature 分支只写**增量**行。照 ``filter(branch_name="feature/x")`` 只取本
    分支，得到的只有该分支改动过的那几个文件里的符号——绝大多数调用边的另一端在
    base 上，图会碎成一地。

    写法照抄本仓权威先例 ``services/code_intel/local_provider.py:55``（⚠️ 只照抄这
    一行；那边的 ``sync_to_async(list)(qs.select_related(...))`` 返回模型实例，10 万
    级行数下必须换成 ``values_list + iterator``，不要一起抄）。
    """
    return ["", branch] if branch else [""]


@dataclass(frozen=True, slots=True)
class _SymbolNodeIndex:
    """符号装配的产物：图已就地填好节点，另附两个供建边阶段复用的索引。"""

    # 已进入图的节点键全集。建边时任一端不在此集合内 ⇒ 整条边丢弃
    # （被排除节点连同其邻接边一并消失的落点）。
    node_ids: set[str]
    # ``(归一后的 file_path, name) -> symbol_id``。裸名边的目标解析与
    # Plan 121-06 的跨仓边二次解析都靠它。
    by_file_and_name: dict[tuple[str, str], str]
    # 被 exclusion 拦掉的**去重文件数**（不是符号数）。
    excluded_file_count: int
    # 因 exclusion 被丢弃的符号行数（仅用于日志汇总，不进 GraphMeta 契约）。
    dropped_symbol_count: int
    # 被 feature 分支整文件覆盖而丢弃的 base 行数（同上，仅用于日志汇总）。
    overlay_shadowed_count: int


def _feature_shadowed_files(repository_id: str, branch: str) -> set[str]:
    """收集 feature 分支写过的 ``file_path`` 全集 —— overlay 去重的判据（D-06）。

    **去重键是整文件，不含行号**（121-CONTEXT D-06）。理由：索引侧的增量语义就是
    「per-file delete + rebuild」（``CallEdge`` 的 docstring 明写 per-file 幂等删除按
    ``caller_file`` 走），feature 分支一旦碰过某个文件，该文件的 base 行就整体作废；
    而行号在分支间会漂移，按 ``start_line`` 去重会漏掉「函数上移了两行」这类情况，
    同一个符号会在图里出现两次。

    **取数形态的选择**（plan 把这个权衡显式留给执行方，此处记录选了哪种及理由）：
    plan 给的两个选项是「两趟 ``iterator``」或「一趟收进内存后再筛」。这里选的是
    **第三种、严格更省的一种**：只对 ``branch_name=branch`` 这一个窄条件做一次
    ``values_list("file_path", flat=True).distinct()``。

    - 它不是第二趟全表扫：feature 分支只有**增量**行，通常是几十到几百行，而 base
      是十万级；
    - 也不必把十万行元组先攒进内存再筛；
    - ``branch == ""`` 时根本不查（base 不会被任何东西覆盖），直接返回空集。

    命中索引 ``Index(fields=["repository", "branch_name", "file_path"])`` 的
    ``(repository, branch_name)`` 前缀。
    """
    if not branch:
        # base 分支自己就是全量，没有「被谁覆盖」这回事。
        return set()

    from codegraph.models import Symbol

    return set(
        Symbol.objects.filter(repository_id=repository_id, branch_name=branch)
        .values_list("file_path", flat=True)
        .distinct()
    )


def _load_symbol_nodes(
    graph: nx.MultiDiGraph,
    *,
    repository_id: str,
    branch: str,
    is_excluded: Callable[[str], bool],
) -> _SymbolNodeIndex:
    """把 ``Symbol`` 行装配成图节点（overlay 去重 + exclusion 过滤）。

    :param graph: 就地填充的 ``MultiDiGraph``（⛔ 不是 ``DiGraph``，见模块 docstring ①）。
    :param repository_id: 仓库主键。
    :param branch: 缓存键里的分支名，``""`` = base。
    :param is_excluded: 由 ``access.make_path_exclusion_memo(matcher)`` 产出的记忆化
        排除判定闭包。⛔ 本模块**不自行解析规则**，matcher 一律由 ``cache.py`` 注入。
    """
    from codegraph.models import Symbol
    from services.exclusion import normalize_rel_path

    shadowed_files = _feature_shadowed_files(repository_id, branch)

    node_ids: set[str] = set()
    by_file_and_name: dict[tuple[str, str], str] = {}
    dropped_symbol_count = 0
    overlay_shadowed_count = 0

    # ⚠️ 字段清单即节点属性来源，**不含 signature**（TextField，数 KB）、
    #    也不含 chunk_id（chunk 关联由 Plan 121-06 的旁挂映射解决，不占节点属性名额）。
    rows = (
        Symbol.objects.filter(
            repository_id=repository_id, branch_name__in=_branch_filter(branch)
        )
        .values_list(
            "id",
            "name",
            "symbol_type",
            "file_path",
            "start_line",
            "end_line",
            "branch_name",
        )
        .iterator(chunk_size=_SYMBOL_CHUNK_SIZE)
    )

    for (
        symbol_id,
        name,
        symbol_type,
        file_path,
        start_line,
        end_line,
        row_branch,
    ) in rows:
        # overlay 去重（D-06）：feature 碰过的文件，其 base 行整体作废。
        if row_branch == "" and file_path in shadowed_files:
            overlay_shadowed_count += 1
            continue

        if is_excluded(file_path):
            dropped_symbol_count += 1
            continue

        norm_path = normalize_rel_path(file_path)
        if norm_path is None:
            dropped_symbol_count += 1
            continue

        node_id = str(symbol_id)
        # 节点属性**恰好 5 个**（内存契约，见模块 docstring ②）。
        graph.add_node(
            node_id,
            name=name,
            symbol_type=symbol_type,
            file_path=file_path,
            start_line=start_line,
            end_line=end_line,
        )
        node_ids.add(node_id)
        by_file_and_name[(norm_path, name)] = node_id

    excluded_files = getattr(is_excluded, "excluded_files", ())
    return _SymbolNodeIndex(
        node_ids=node_ids,
        by_file_and_name=by_file_and_name,
        excluded_file_count=len(excluded_files),
        dropped_symbol_count=dropped_symbol_count,
        overlay_shadowed_count=overlay_shadowed_count,
    )
