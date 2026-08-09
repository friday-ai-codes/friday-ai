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
   KB，放进节点属性会让线性内存估算彻底失准）。边恒 3 个（``kind`` / ``confidence`` /
   ``line_number``），⛔ **不存 ``reason``**（D-08：1–3 个边属性成本完全相同，第 4 个
   才跳一级；30 万边多花约 6.9MB，而 ``reason`` 只是展示文案，由
   ``model.derive_reason()`` 在输出时现推）。**唯一例外**是 ``cross_repo`` 档的第 4
   个属性 ``match_confidence``（理由见 :func:`_load_cross_repo_edges`）。

③ **分支语义是 overlay**：``""`` 是 base 全量，feature 分支只写增量行。取数必须
   ``branch_name__in=["", branch]``，去重键取**整文件**（D-06）。

④ 🚨 **matcher 与 exclusion 指纹一律由 ``cache.py`` 解析并向下注入，loader 是纯
   装配层、不做规则解析**。⛔ 本模块**绝不**调用
   ``access.build_matcher_and_fingerprint`` —— ``cache.py`` 在一次取图里已经解析过
   一遍，loader 再调一次就是同一次请求内重复做「``_resolve_effective_specs`` 的 DB
   读 + 该仓全部 glob/regex 重新编译」（``services/exclusion.py:157-207``），而且这条
   同步路径**不经过** ``build_matcher_for_repo`` 的 60s ``_matcher_cache``，省不掉。
   跨调用的复用由 ``access.py`` 自带的 TTL memo 负责。

⑤ **exclusion 过滤发生在装配阶段，不是输出阶段**（GRAPH-04 的真正落点）：命中排除
   的 ``Symbol.file_path`` 对应的节点**根本不进节点集**，建边时任一端点不在
   :attr:`_SymbolNodeIndex.node_ids` 内即**整条边丢弃**——被排除节点连同其所有邻接
   边一并消失。输出阶段裁剪挡不住计数、深度分组这类旁路泄漏。
   ⛔ 判定本身一律走 ``services/exclusion.py``（全仓唯一事实源），本模块**不自写**
   任何 glob/regex 匹配：那边内含 ReDoS 静态拒绝、global 规则大小写不敏感、basename
   兜底匹配、运行期异常 fail-closed 四层语义，重写必漏。

⑥ **装配循环是 10 万级迭代，循环内零 per-item 日志**。``exclusion.blocked``（INFO）
   由 ``make_path_exclusion_memo`` 的闭包按「每个新的被排除 ``file_path`` 至多一次」
   控制；本模块只在装配结束后补一条 DEBUG 汇总事件。
"""

from __future__ import annotations

import time
from collections.abc import Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING, Callable, Final

import networkx as nx
import structlog
from django.utils import timezone

from services.code_graph.access import make_path_exclusion_memo
from services.code_graph.model import (
    BARE_NAME_BLACKLIST,
    LOW_RESOLUTION_THRESHOLD,
    ChunkEvidence,
    CodeGraph,
    EdgeConfidence,
    EdgeKind,
    GraphMeta,
)

if TYPE_CHECKING:
    from services.exclusion import ExclusionMatcher

logger = structlog.get_logger(__name__)

# 事件名常量（形态对齐 ``access.py`` / ``signature.py`` / ``codegraph/lsp/volar_pool.py``）。
# ⚠️ 前缀不得缩写：``graph_build_*`` 已被 ``services/graph_builder.py`` 占用。
_EVENT_EXCLUSION_APPLIED: Final[str] = "code_graph_exclusion_applied"
_EVENT_ASSEMBLED: Final[str] = "code_graph_assembled"
_EVENT_DEGRADED_SUBGRAPH: Final[str] = "code_graph_degraded_subgraph"

# ORM 批量取数的游标批大小（Postgres 上走服务端游标）。与 RESEARCH §Code Examples 1
# 给出的形状一致；不做成 settings —— 它是取数实现细节，不是运维旋钮。
_SYMBOL_CHUNK_SIZE: Final[int] = 5000
_CALL_EDGE_CHUNK_SIZE: Final[int] = 5000
# 跨仓边的量级比 ``CallEdge`` 小两三个数量级（千级），且每行都跨两个 JOIN，
# 批大小取小一档（形状与 RESEARCH §Code Examples 1 的 ``cross_rows`` 一致）。
_CROSS_REPO_CHUNK_SIZE: Final[int] = 2000
_CHUNK_EDGE_CHUNK_SIZE: Final[int] = 5000

# 单个符号最多挂多少条 chunk 证据，超出即截断并计数。
# 防的是「热点 chunk」：``SEMANTIC`` / ``CO_CHANGED`` 这类边在一个高频改动的 chunk 上
# 可以有成百上千条，而同一个 chunk 里的每个符号都会各挂一份——不设上限，证据面本身
# 就会把内存吃穿（而且第 51 条之后对人/agent 的判断也不再增加信息）。
CHUNK_EVIDENCE_MAX_PER_SYMBOL: Final[int] = 50

# 按需子图每轮 frontier 的上限，超出即截断并计数。
# 防的是「种子选在超级枢纽符号上」——一个被全仓调用的 ``logger.info`` 级别的符号，
# 一跳就能把半个仓拉进来，子图当场退化成全图，降级路径也就白设了。
SUBGRAPH_FRONTIER_LIMIT: Final[int] = 5000

# 节点属性键集合。个数写死在这里供用例引用：**恒 5 个**，多一个就会让
# ``NODE_COST_BYTES`` 的标定假设失效（RESEARCH §Byte Estimation 的属性敏感性表）。
_NODE_ATTR_KEYS: Final[frozenset[str]] = frozenset(
    {"name", "symbol_type", "file_path", "start_line", "end_line"}
)
# 边属性键集合，**恒 3 个**。⛔ ``reason`` 不在其中（D-08）。
_EDGE_ATTR_KEYS: Final[frozenset[str]] = frozenset({"kind", "confidence", "line_number"})
# ``cross_repo`` 档是**唯一**允许 4 个边属性的档位，多出来的是 ``match_confidence``。
_CROSS_REPO_EDGE_ATTR_KEYS: Final[frozenset[str]] = _EDGE_ATTR_KEYS | {"match_confidence"}

__all__ = ["load_graph", "load_subgraph"]


# 埋点写成专用函数、事件名常量直接写在 ``logger.debug`` 的第一个位置实参上，
# ⛔ 不抽 ``_emit(event, **fields)`` 通用转发器：``test_observability_contract`` 要求
# 事件名**可静态解析**成字面量，转发器会让 AST 只看到一个形参名（121-04 实际被拦过）。
# 取 DEBUG：这是 10 万级装配循环的收尾汇总，INFO 会违反级别纪律。
# 观测 best-effort —— 任何异常吞掉，绝不反噬装配主流程。


def _log_exclusion_applied(
    *,
    repository_id: str,
    branch: str,
    excluded_file_count: int,
    dropped_symbol_count: int,
) -> None:
    try:
        logger.debug(
            _EVENT_EXCLUSION_APPLIED,
            component="code_graph",
            category="sampling",
            repository_id=str(repository_id),
            branch=branch or "-",
            excluded_file_count=excluded_file_count,
            dropped_symbol_count=dropped_symbol_count,
        )
    except Exception:  # noqa: BLE001 — 观测失败绝不反噬业务（不是安全降级分支）
        pass


def _log_assembled(
    *,
    repository_id: str,
    branch: str,
    node_count: int,
    edge_count: int,
    resolution_rate: float,
    duration_ms: float,
    overlay_shadowed_count: int,
    dropped_no_caller_count: int,
    dropped_missing_node_count: int,
    dropped_bare_filtered_count: int,
    chunk_evidence_truncated_count: int = 0,
) -> None:
    try:
        logger.debug(
            _EVENT_ASSEMBLED,
            component="code_graph",
            category="sampling",
            repository_id=str(repository_id),
            branch=branch or "-",
            node_count=node_count,
            edge_count=edge_count,
            resolution_rate=resolution_rate,
            duration_ms=duration_ms,
            # 下面几项只进日志、不进 GraphMeta 契约：它们是排障线索
            # （「这仓怎么边这么少」），不是上层工具要向用户声明的可信度标记。
            overlay_shadowed_count=overlay_shadowed_count,
            dropped_no_caller_count=dropped_no_caller_count,
            dropped_missing_node_count=dropped_missing_node_count,
            dropped_bare_filtered_count=dropped_bare_filtered_count,
            chunk_evidence_truncated_count=chunk_evidence_truncated_count,
        )
    except Exception:  # noqa: BLE001 — 观测失败绝不反噬业务（不是安全降级分支）
        pass


def _log_degraded_subgraph(
    *,
    repository_id: str,
    branch: str,
    seed_count: int,
    depth: int,
    node_count: int,
    edge_count: int,
    frontier_truncated: bool,
    duration_ms: float,
    chunk_evidence_truncated_count: int = 0,
) -> None:
    """降级为按需子图的埋点。

    取 INFO 而非 DEBUG：这是**低频**事件（只有超预算大仓才走到），且它对应一个
    上层必须向用户透出的可信度标记（``degraded="on_demand_subgraph"`` 意味着结论
    覆盖面小于全图）。级别纪律禁止的是高频循环刷屏，不是这种一次一图的关键事件。

    ``initiated_by_user_id`` 取 ``system``：loader 是纯同步装配层，触发用户的绑定
    由 ``cache.py`` 在异步侧完成（它才拿得到 ``user``），本层如实记系统行为。
    """
    try:
        logger.info(
            _EVENT_DEGRADED_SUBGRAPH,
            component="code_graph",
            category="sampling",
            repository_id=str(repository_id),
            branch=branch or "-",
            seed_count=seed_count,
            depth=depth,
            node_count=node_count,
            edge_count=edge_count,
            frontier_truncated=frontier_truncated,
            duration_ms=duration_ms,
            # 与全量路径的 ``code_graph_assembled`` 对齐：同一个排障信号不该只在一条
            # 路径上存在（否则「这仓怎么证据面这么少」在降级路径上无从答起）。
            chunk_evidence_truncated_count=chunk_evidence_truncated_count,
            initiated_by_user_id="system",
        )
    except Exception:  # noqa: BLE001 — 观测失败绝不反噬业务（不是安全降级分支）
        pass


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
    # 跨仓边二次解析都靠它。
    by_file_and_name: dict[tuple[str, str], str]
    # ``str(Symbol.chunk_id) -> [symbol_id, …]``，chunk 旁挂证据面的挂载索引。
    # 🚨 **不是节点属性**：``chunk_id`` 一旦进节点属性就把节点从 5 个属性推到 6 个，
    #    直接破掉内存契约；而它只在装配 ``chunk_evidence`` 时用一次，做成独立的
    #    旁挂映射即可。一个 chunk 常含多个 Symbol，所以值是**列表**。
    chunk_to_symbols: dict[str, list[str]]
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
    restrict_symbol_ids: set[str] | None = None,
) -> _SymbolNodeIndex:
    """把 ``Symbol`` 行装配成图节点（overlay 去重 + exclusion 过滤）。

    :param graph: 就地填充的 ``MultiDiGraph``（⛔ 不是 ``DiGraph``，见模块 docstring ①）。
    :param repository_id: 仓库主键。
    :param branch: 缓存键里的分支名，``""`` = base。
    :param is_excluded: 由 ``access.make_path_exclusion_memo(matcher)`` 产出的记忆化
        排除判定闭包。⛔ 本模块**不自行解析规则**，matcher 一律由 ``cache.py`` 注入。
    :param restrict_symbol_ids: 仅 :func:`load_subgraph` 使用——把取数收敛到 SQL 侧
        已经收敛出来的那批 ``symbol_id``。``None`` = 全量装配。
    """
    from codegraph.models import Symbol
    from services.exclusion import normalize_rel_path

    shadowed_files = _feature_shadowed_files(repository_id, branch)

    node_ids: set[str] = set()
    by_file_and_name: dict[tuple[str, str], str] = {}
    chunk_to_symbols: dict[str, list[str]] = {}
    dropped_symbol_count = 0
    overlay_shadowed_count = 0

    # ⚠️ 字段清单**不等于**节点属性来源：``signature``（TextField，数 KB）根本不取；
    #    ``chunk_id`` 取但**不进节点属性**——它只喂 :attr:`_SymbolNodeIndex.chunk_to_symbols`
    #    这个旁挂映射，节点属性仍恒 5 个。
    symbol_qs = Symbol.objects.filter(
        repository_id=repository_id, branch_name__in=_branch_filter(branch)
    )
    if restrict_symbol_ids is not None:
        symbol_qs = symbol_qs.filter(id__in=restrict_symbol_ids)

    rows = (
        symbol_qs
        .values_list(
            "id",
            "name",
            "symbol_type",
            "file_path",
            "start_line",
            "end_line",
            "branch_name",
            "chunk_id",
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
        chunk_id,
    ) in rows:
        # overlay 去重（D-06）：feature 碰过的文件，其 base 行整体作废。
        if row_branch == "" and file_path in shadowed_files:
            overlay_shadowed_count += 1
            continue

        # exclusion 在**装配阶段**生效（GRAPH-04）：命中即不进节点集，而不是「先进
        # 了再删」，也不是输出阶段裁剪。
        # ⚠️ 判定喂的是**原始** file_path：``ExclusionMatcher.is_excluded`` 内部自己
        #    做归一，归一失败（绝对路径 / ``..`` 越界 / 空）一律 fail-closed 返回
        #    ``True``，并被记忆化闭包计进 ``excluded_files``——「归一失败」与「命中
        #    规则」由此共用同一个去重文件计数口径。
        # 🚨 循环内**没有** per-item 日志：``exclusion.blocked``（INFO）由闭包按
        #    「每个新的被排除 file_path 至多一次」控制，汇总事件在函数收尾统一发。
        if is_excluded(file_path):
            dropped_symbol_count += 1
            continue

        norm_path = normalize_rel_path(file_path)
        if norm_path is None:
            # 上一行的 fail-closed 已覆盖这条路径；显式保留是为了把「归一失败即排除」
            # 写成本模块自己的契约，而不是默默依赖 matcher 的实现细节——将来若 matcher
            # 被替换成不 fail-closed 的实现，这道防线仍在。
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
        # ``Symbol.chunk_id`` 是**软引用且 null=True**（历史数据 / 未命中任何 chunk）。
        # 为空的符号直接跳过——它不会出现在 ``chunk_evidence`` 的键里，这是正常态，
        # 不是缺失。
        if chunk_id is not None:
            chunk_to_symbols.setdefault(str(chunk_id), []).append(node_id)

    # ``excluded_files`` 是闭包附带的**活动只读视图**：这里读到的是本次装配真实命中
    # 排除的**去重文件数**（不是符号数），直接喂 ``GraphMeta.excluded_file_count``。
    excluded_files = getattr(is_excluded, "excluded_files", ())
    excluded_file_count = len(excluded_files)
    _log_exclusion_applied(
        repository_id=repository_id,
        branch=branch,
        excluded_file_count=excluded_file_count,
        dropped_symbol_count=dropped_symbol_count,
    )
    return _SymbolNodeIndex(
        node_ids=node_ids,
        by_file_and_name=by_file_and_name,
        chunk_to_symbols=chunk_to_symbols,
        excluded_file_count=excluded_file_count,
        dropped_symbol_count=dropped_symbol_count,
        overlay_shadowed_count=overlay_shadowed_count,
    )


# ── 裸名边的三道过滤（CONTEXT Area 3；三个谓词各自可单测） ──────────────────
#
# 为什么裸名边默认不装载、装载了还要再过三道：跨目录同名的命中率极高，一条假的
# `handle → handle` 边会让 impact 的影响面凭空膨胀一整个子树，而 agent 读到的是
# 「改这里会波及这些地方」这种听起来很确定的结论。假阳性比漏报危险得多。


def _directory_of(file_path: str | None) -> str | None:
    """取归一后路径的目录部分；仓库根下的文件返回 ``""``。

    路径为空 / 归一失败（绝对路径、``..`` 越界）→ ``None``，调用方据此丢弃。
    """
    from services.exclusion import normalize_rel_path

    if not file_path:
        return None
    norm = normalize_rel_path(file_path)
    if norm is None:
        return None
    head, sep, _tail = norm.rpartition("/")
    return head if sep else ""


def _is_same_directory(caller_file: str | None, callee_file: str | None) -> bool:
    """过滤 ① —— 同目录/同文件优先，跨目录同名一律丢弃。

    任一侧缺失或归一失败即返回 ``False``（丢弃）：没有 ``callee_file`` 就无从判断
    这个名字指的是哪个文件里的符号，此时保留等于凭名字瞎连。
    """
    caller_dir = _directory_of(caller_file)
    callee_dir = _directory_of(callee_file)
    if caller_dir is None or callee_dir is None:
        return False
    return caller_dir == callee_dir


def _qualifier_matches(callee_qualifier: str | None, callee_file: str | None) -> bool:
    """过滤 ② —— ``callee_qualifier`` 非空时，候选文件必须与该限定符对得上。

    ``callee_qualifier`` 是 selector / 对象调用的限定符：Go ``pkg.Func()`` 的 ``pkg``
    （包目录名）、Python ``mod.func()`` 的 ``mod``（模块文件名去扩展名）、
    ``obj.method()`` 的 ``obj``（局部变量名）。

    判据（保守）：限定符须等于候选文件的**模块名**（basename 去扩展名）或其**父目录
    名**（包名）。``obj.method()`` 这类对象调用两者都对不上 → 丢弃。这是有意为之：
    本函数只在「已经没有 FK、只剩一个字符串」的裸名档上生效，对不上就说明我们并不
    知道它指向谁，宁可少一条边也不要一条编造的边。

    限定符为空（绝大多数直接调用）→ 恒 ``True``，本道过滤不参与判定。
    """
    if not callee_qualifier:
        return True

    from services.exclusion import normalize_rel_path

    if not callee_file:
        return False
    norm = normalize_rel_path(callee_file)
    if norm is None:
        return False

    head, sep, basename = norm.rpartition("/")
    module_name = basename.rsplit(".", 1)[0] if "." in basename else basename
    package_name = head.rsplit("/", 1)[-1] if sep else ""
    return callee_qualifier in {module_name, package_name}


def _is_blacklisted_bare_name(callee_name: str | None) -> bool:
    """过滤 ③ —— 常见名黑名单（``get`` / ``handle`` / ``main`` …）。

    黑名单本体在 ``model.BARE_NAME_BLACKLIST``（契约层常量，17 项），⛔ 不在本模块
    另抄一份：两处各写一份必然漂移。
    """
    return (callee_name or "") in BARE_NAME_BLACKLIST


@dataclass(frozen=True, slots=True)
class _CallEdgeStats:
    """一次 ``CallEdge`` 装配的统计量。"""

    # 🚨 下面两项统计的是**全部** CallEdge 行，与 ``include_low_confidence``
    #    以及任何丢弃动作都无关——否则关掉裸名装载时解析率会恒为 1.0，
    #    变成一个「本仓解析得很好」的假信号。
    resolved_count: int
    bare_name_count: int

    loaded_count: int
    # 模块级调用（``caller_symbol_id IS NULL``）无处挂载，丢弃并计数。
    dropped_no_caller_count: int
    # 端点符号不在节点集内（被 exclusion 拦掉、或裸名解析不到候选）。
    dropped_missing_node_count: int
    # 过了 ``include_low_confidence`` 开关、但被三道过滤挡下的裸名边。
    dropped_bare_filtered_count: int

    @property
    def resolution_rate(self) -> float:
        """``resolved / (resolved + bare_name)``；分母为 0 时定义为 ``1.0``。

        分母为 0 意味着这个仓一条调用边都没有（空仓 / 只索引了符号）。此时取 ``1.0``
        而不是 ``0.0``：``0.0`` 会让 ``low_resolution`` 对每个空仓都为真，把「无从判断」
        误报成「解析质量差」，降级标记一长鸣上层就学会无视它了。
        """
        total = self.resolved_count + self.bare_name_count
        if total == 0:
            return 1.0
        return self.resolved_count / total


def _load_call_edges(
    graph: nx.MultiDiGraph,
    *,
    repository_id: str,
    branch: str,
    nodes: _SymbolNodeIndex,
    include_low_confidence: bool,
    restrict_caller_ids: set[str] | None = None,
) -> _CallEdgeStats:
    """把 ``CallEdge`` 行装配成图边（解析边 / 裸名边双档）。

    **分档判据**：``callee_symbol_id IS NOT NULL`` ⇒ :attr:`EdgeConfidence.RESOLVED`；
    为 ``NULL`` ⇒ :attr:`EdgeConfidence.BARE_NAME`。
    ⛔ 不要去找 ``CallEdge.match_confidence`` —— **该字段不存在**，全仓只有
    ``CrossRepoApiCall`` 有 ``match_confidence``。

    **``caller_symbol_id IS NULL``（模块级调用，不在任何函数体内）**：整条边丢弃。
    ⛔ 不用 ``caller_file`` 造虚拟节点 —— 与 D-05 同理，虚拟节点会污染上层 impact 的
    深度分组与计数，且无法给出 ``file:line``，对 agent 没有行动价值。

    :param restrict_caller_ids: 仅 :func:`load_subgraph` 使用。收敛条件只加在**主叫**
        侧就够了：任何幸存的边都必须先满足 ``caller_symbol_id ∈ node_ids``，而
        ``node_ids ⊆ restrict_caller_ids``，所以再加一个 callee 侧的 ``OR`` 只会多捞
        一批注定被丢弃的行。⚠️ 此时 :attr:`_CallEdgeStats.resolution_rate` 的口径随之
        变成「该子图内的解析率」，而非全仓解析率——这是子图路径的固有语义。
    """
    from codegraph.models import CallEdge
    from services.exclusion import normalize_rel_path

    node_ids = nodes.node_ids
    by_file_and_name = nodes.by_file_and_name

    resolved_count = 0
    bare_name_count = 0
    loaded_count = 0
    dropped_no_caller_count = 0
    dropped_missing_node_count = 0
    dropped_bare_filtered_count = 0

    # ⚠️ FK 一律用 attname（``caller_symbol_id`` / ``callee_symbol_id``）取列：
    #    写成 ``caller_symbol`` 会产生隐式 JOIN，30 万行上是数量级差异。
    call_qs = CallEdge.objects.filter(
        repository_id=repository_id, branch_name__in=_branch_filter(branch)
    )
    if restrict_caller_ids is not None:
        call_qs = call_qs.filter(caller_symbol_id__in=restrict_caller_ids)

    rows = (
        call_qs
        .values_list(
            "caller_symbol_id",
            "callee_symbol_id",
            "caller_file",
            "callee_name",
            "callee_file",
            "callee_qualifier",
            "call_type",
            "line_number",
        )
        .iterator(chunk_size=_CALL_EDGE_CHUNK_SIZE)
    )

    for (
        caller_symbol_id,
        callee_symbol_id,
        caller_file,
        callee_name,
        callee_file,
        callee_qualifier,
        _call_type,  # 取列保持与 RESEARCH §Code Examples 1 的查询形状一致；
        # ⛔ 不进边属性（边属性恒 3 个，见模块 docstring ②）。
        line_number,
    ) in rows:
        # 解析率先统计、后过滤：口径是**全部**落库的 CallEdge 行。
        if callee_symbol_id is not None:
            resolved_count += 1
        else:
            bare_name_count += 1

        if caller_symbol_id is None:
            dropped_no_caller_count += 1
            continue

        caller_node = str(caller_symbol_id)
        if caller_node not in node_ids:
            # 主叫符号被 exclusion 拦掉（或不在本分支的 overlay 里）⇒ 整条边消失。
            dropped_missing_node_count += 1
            continue

        if callee_symbol_id is not None:
            callee_node = str(callee_symbol_id)
            if callee_node not in node_ids:
                dropped_missing_node_count += 1
                continue
            confidence = EdgeConfidence.RESOLVED
        else:
            # 裸名边**默认不装载**：只有调用方显式 include_low_confidence=True 才进来。
            if not include_low_confidence:
                continue
            # …进来了也仍须过三道过滤（CONTEXT Area 3）。
            if (
                not _is_same_directory(caller_file, callee_file)
                or not _qualifier_matches(callee_qualifier, callee_file)
                or _is_blacklisted_bare_name(callee_name)
            ):
                dropped_bare_filtered_count += 1
                continue
            norm_callee_file = normalize_rel_path(callee_file or "")
            resolved_node = (
                by_file_and_name.get((norm_callee_file, callee_name))
                if norm_callee_file is not None
                else None
            )
            if resolved_node is None:
                # 三道过滤全过，但 (file, name) 在本次装配的节点集里找不到候选
                # ——被 exclusion 拦掉，或该符号压根没被索引。丢弃。
                dropped_missing_node_count += 1
                continue
            callee_node = resolved_node
            confidence = EdgeConfidence.BARE_NAME

        # 边属性**恰好 3 个**。⛔ 没有 ``reason``（D-08，由 derive_reason() 现推）。
        graph.add_edge(
            caller_node,
            callee_node,
            kind=EdgeKind.CALL.value,
            confidence=confidence.value,
            line_number=line_number,
        )
        loaded_count += 1

    return _CallEdgeStats(
        resolved_count=resolved_count,
        bare_name_count=bare_name_count,
        loaded_count=loaded_count,
        dropped_no_caller_count=dropped_no_caller_count,
        dropped_missing_node_count=dropped_missing_node_count,
        dropped_bare_filtered_count=dropped_bare_filtered_count,
    )


@dataclass(frozen=True, slots=True)
class _CrossRepoStats:
    """一次 ``CrossRepoApiCall`` 装配的统计量。"""

    loaded_count: int
    # 🚨 D-05：两端有任一侧无法在本图内解析到符号节点的边，被**丢弃**并计进这里。
    #    该计数是 ``GraphMeta.cross_repo_unresolved_count`` 的唯一来源，上层工具据此
    #    向用户声明「有 N 条跨仓边无法定位」。
    unresolved_count: int


def _load_cross_repo_edges(
    graph: nx.MultiDiGraph,
    *,
    repository_id: str,
    nodes: _SymbolNodeIndex,
) -> _CrossRepoStats:
    """把 ``CrossRepoApiCall`` 装配成第三档 ``cross_repo`` 边（D-05）。

    **为什么要「二次解析」**（RESEARCH Pitfall 1）：``CrossRepoApiCall`` 只有两个 FK
    —— ``call_site → ApiCallSite``、``endpoint → Endpoint``，**两端都不是 ``Symbol``**。
    ``ApiCallSite`` 手上只有 ``caller_file`` + ``caller_function`` 两个字符串，
    ``Endpoint`` 只有 ``file_path`` + ``handler_name``。要把这条边挂到图里的符号节点
    上，只能拿 ``(归一后 file_path, name)`` 去查 :attr:`_SymbolNodeIndex.by_file_and_name`。

    **按仓过滤只能走反查**：``CrossRepoApiCall`` **自身没有 ``repository`` 字段**，
    所以过滤条件是 ``Q(call_site__repository_id=…) | Q(endpoint__repository_id=…)``
    —— 与 ``codegraph/galaxy/cache.py:62`` 登记的
    ``("cross_repo_api_call", CrossRepoApiCall, "call_site__repository_id", …)``
    是同一个做法，不是本模块自创。

    🚨 **D-05：解析不上的边直接丢弃 + 计数，⛔ 绝不建 ``external`` / ``unresolved``
    虚拟节点。** 虚拟节点会污染上层 impact 的**深度分组与计数**（凭空多出一层"受影响
    的东西"），而且它给不出 ``file:line``——agent 拿到它既不能读也不能改，没有任何行动
    价值。丢弃 + 如实计数则让 Phase 122 能在输出里声明「另有 N 条跨仓边无法定位」，
    把"不知道"诚实地表达成"不知道"。

    🚨 **每一侧只在它确实属于本仓时才解析**（按行上的 ``call_site__repository_id`` /
    ``endpoint__repository_id`` 判定）。⛔ **不得**拿对端仓的 ``(file_path, name)`` 去
    撞本仓的 :attr:`_SymbolNodeIndex.by_file_and_name`：那张索引里只有**本仓**符号，
    而微服务仓之间路径与 handler 命名高度同构，撞上就会在两个本仓符号之间造出一条
    **伪造的** ``cross_repo`` 边——还带着原值 ``match_confidence`` 的高可信度标签、
    默认参与扩散、且 ``unresolved_count`` 不会 +1，上层完全无从打折。

    **对端仓的符号不在本图内**：本相位**不做多仓合并大图**（CONTEXT Area 1），跨仓
    impact 由 Phase 122 通过「按需再取对端仓的图」组合。因此一条边的两端里，只有**两端
    都在本仓**的那些行才可能建成边；只要有一侧落在别的仓，这条边就整条丢弃并计数
    （D-05：丢弃 + 如实计数，⛔ 绝不建虚拟节点）。

    :returns: 装配与丢弃的计数（喂 ``GraphMeta``）。
    """
    from django.db.models import Q

    from codegraph.models import CrossRepoApiCall
    from services.exclusion import normalize_rel_path

    by_file_and_name = nodes.by_file_and_name

    loaded_count = 0
    unresolved_count = 0

    rows = (
        CrossRepoApiCall.objects.filter(
            Q(call_site__repository_id=repository_id)
            | Q(endpoint__repository_id=repository_id)
        )
        .values_list(
            "call_site__repository_id",
            "call_site__caller_file",
            "call_site__caller_function",
            "call_site__line_number",
            "endpoint__repository_id",
            "endpoint__file_path",
            "endpoint__handler_name",
            "endpoint__http_method",
            "endpoint__url_path",
            "endpoint__branch_name",
            "match_confidence",
        )
        .iterator(chunk_size=_CROSS_REPO_CHUNK_SIZE)
    )

    local_repository_id = str(repository_id)

    for (
        call_site_repository_id,
        caller_file,
        caller_function,
        call_line_number,
        endpoint_repository_id,
        endpoint_file_path,
        handler_name,
        _http_method,  # 取列保持与 RESEARCH §Code Examples 1 的查询形状一致；
        _url_path,  # ⛔ 不进边属性（``cross_repo`` 档也只有 4 个属性）。
        _endpoint_branch_name,  # ⚠️ ApiCallSite 侧**没有** branch_name，见下方说明。
        match_confidence,
    ) in rows:
        # 🚨 **每一侧只在它确实属于本仓时才解析**。``by_file_and_name`` 里装的全是
        #    **本仓**符号，拿对端仓的 ``(file_path, name)`` 去撞这张索引就是在凭同名
        #    造边：微服务仓之间路径与 handler 命名高度同构（``internal/handler/user.go``
        #    + ``GetUser``、``src/api/views.py`` + ``order_create``），一旦撞上就会在
        #    两个**本仓**符号之间加一条 ``cross_repo`` 边。这条伪造边比裸名假阳性更难
        #    发现：它带着原值 ``match_confidence`` 这种高可信度标签、本档还默认参与
        #    扩散，而 ``unresolved_count`` **不会** +1（它"解析成功"了），上层因此拿不
        #    到任何可用来打折的信号。
        caller_node = (
            _resolve_by_file_and_name(
                by_file_and_name, caller_file, caller_function, normalize_rel_path
            )
            if str(call_site_repository_id) == local_repository_id
            else None
        )
        callee_node = (
            _resolve_by_file_and_name(
                by_file_and_name, endpoint_file_path, handler_name, normalize_rel_path
            )
            if str(endpoint_repository_id) == local_repository_id
            else None
        )
        if caller_node is None or callee_node is None:
            unresolved_count += 1
            continue

        # 边属性 4 个 —— 本档是唯一例外。理由：``cross_repo`` 边的量级在**千级**
        # （``CallEdge`` 是十万到三十万级），第 4 个属性的阶跃成本（约 +143 B/边 vs
        # +120 B/边）在这个量级上可忽略；而 ``match_confidence`` 是
        # ``model.confidence_score()`` 对本档的**必需入参**（缺参会抛 ValueError，
        # 刻意不做静默兜底），不存就等于把跨仓边的可信度抹成常量。
        # ⚠️ 原值透传（1.0 / 0.7 / 0.4 三档），⛔ 不归一化。
        graph.add_edge(
            caller_node,
            callee_node,
            kind=EdgeKind.CROSS_REPO.value,
            confidence=EdgeConfidence.CROSS_REPO.value,
            line_number=call_line_number,
            match_confidence=match_confidence,
        )
        loaded_count += 1

    return _CrossRepoStats(loaded_count=loaded_count, unresolved_count=unresolved_count)


def _load_chunk_evidence(
    *,
    repository_id: str,
    branch: str,
    nodes: _SymbolNodeIndex,
) -> tuple[dict[str, tuple[ChunkEvidence, ...]], int]:
    """把 ``ChunkEdge`` 装配成**旁挂证据面**，⛔ 绝不写进 ``MultiDiGraph`` 的边集。

    🚨 **Pitfall 2（笛卡尔爆炸）**：``ChunkEdge`` 连的是 ``source_chunk_id`` /
    ``target_chunk_id``（UUID **软引用、无 FK**），要挂到符号上只能靠
    ``Symbol.chunk_id`` 反查；而**一个 chunk 通常含多个 Symbol**——一条 chunk 边在
    两端各有 k 个符号时，展开成符号级边就是 **k² 条**。chunk 与 symbol 本就是不同
    粒度，强行对齐既贵又不准。

    本相位的裁决是「装配但默认不参与符号级扩散，仅作为补充证据面」，落地形态就是
    这个 ``symbol_id -> (ChunkEvidence, …)`` 的旁挂 dict：一条 chunk 边挂到两端各
    k 个符号上是 **k + k 条记录**（线性），而不是 k² 条边。

    🔔 **写给 Phase 122 的实现者**：:attr:`EdgeConfidence.CHUNK_LEVEL` 档在本相位
    **不产生任何图中的边**——去 ``graph.edges`` 里找 ``kind == "chunk"`` 是找不到的。
    该档位只是给上层工具在渲染 :attr:`CodeGraph.chunk_evidence` 时标注置信档用的。

    :returns: ``(证据面, 因 fan-out 上限被截断的记录数)``。
    """
    from code_relations.models import ChunkEdge

    chunk_to_symbols = nodes.chunk_to_symbols

    evidence: dict[str, list[ChunkEvidence]] = {}
    truncated_count = 0

    # 索引覆盖：``idx_chunkedge_branch_fanout (repository, branch_name, source_chunk_id)``
    # 的 ``(repository, branch_name)`` 前缀。
    rows = (
        ChunkEdge.objects.filter(
            repository_id=repository_id, branch_name__in=_branch_filter(branch)
        )
        .values_list(
            "source_chunk_id",
            "target_chunk_id",
            "edge_type",
            "weight",
            "target_repository_id",
        )
        .iterator(chunk_size=_CHUNK_EDGE_CHUNK_SIZE)
    )

    for (
        source_chunk_id,
        target_chunk_id,
        edge_type,
        weight,
        target_repository_id,
    ) in rows:
        source_key = str(source_chunk_id)
        target_key = str(target_chunk_id)

        # 两端的符号都挂：证据面回答的是「哪些符号被这条共现关系触及」，单挂源侧会
        # 让被调侧的符号看不到自己身上的证据。跨仓边的 target chunk 不在本仓，
        # ``chunk_to_symbols`` 自然查不到，天然只挂得上源侧。
        touched: list[str] = list(chunk_to_symbols.get(source_key, ()))
        if target_key != source_key:
            touched.extend(chunk_to_symbols.get(target_key, ()))
        if not touched:
            continue

        record = ChunkEvidence(
            source_chunk_id=source_key,
            target_chunk_id=target_key,
            edge_type=edge_type,
            weight=weight,
            target_repository_id=(
                str(target_repository_id) if target_repository_id is not None else None
            ),
        )
        for symbol_id in touched:
            bucket = evidence.setdefault(symbol_id, [])
            if len(bucket) >= CHUNK_EVIDENCE_MAX_PER_SYMBOL:
                truncated_count += 1
                continue
            bucket.append(record)

    # 值收成 tuple：``CodeGraph`` 是 frozen，证据面同样不可变——否则上层拿到后就地
    # ``append`` 会污染缓存里的同一张图。
    return {key: tuple(items) for key, items in evidence.items()}, truncated_count


def _resolve_by_file_and_name(
    by_file_and_name: dict[tuple[str, str], str],
    file_path: str | None,
    name: str | None,
    normalize: Callable[[str], str | None],
) -> str | None:
    """``(file_path, name)`` → 已装载的 ``symbol_id``；解析不到返回 ``None``。

    两侧路径必须**同口径归一**后才能比对：索引里的键是
    ``normalize_rel_path(Symbol.file_path)``，这里的入参是 ``ApiCallSite.caller_file``
    / ``Endpoint.file_path`` 的原始值，写法上很容易一侧带 ``./`` 前缀、一侧不带。
    """
    if not file_path or not name:
        return None
    norm = normalize(file_path)
    if norm is None:
        return None
    return by_file_and_name.get((norm, name))


def _expand_seed_ids(
    *,
    repository_id: str,
    branch: str,
    seed_symbol_ids: Sequence[str],
    radius: int,
) -> tuple[set[str], bool]:
    """从种子出发在 **SQL 侧**逐跳扩张，返回 ``(可达 symbol_id 集合, 是否发生截断)``。

    🚨 **收敛必须发生在 SQL 侧**，⛔ **不是**「先全量装配再裁剪」——全量装配正是本
    路径要避开的那 2–4 秒纯 CPU 与内存尖峰（RESEARCH §Byte Estimation：10 万符号仓
    一次冷建图约 2.07 秒、20 万约 4.03 秒），而 ``thread_sensitive=True`` 意味着这段
    时间会**阻塞同一执行器上的其他 ORM 工作**。先装配再裁剪等于把代价全额付掉之后
    再把结果扔掉。

    每轮只取 ``(caller_symbol_id, callee_symbol_id)`` 两列（命中
    ``Index(fields=["repository","branch_name","caller_file"])`` 的
    ``(repository, branch_name)`` 前缀），把新出现的对端收进下一轮 frontier；
    ``visited`` 去重同时也是**防环**——没有它，一个 ``a → b → a`` 的循环调用会让
    这个循环永远跑下去。

    :param radius: 跳数上限。调用方传的是 ``depth + 1``，理由见 :func:`load_subgraph`。
    :returns: ``visited`` 含种子本身；``truncated`` 为真表示某一轮 frontier 撞上
        :data:`SUBGRAPH_FRONTIER_LIMIT` 被截断，子图不完整。
    """
    from django.db.models import Q

    from codegraph.models import CallEdge

    visited: set[str] = {str(seed) for seed in seed_symbol_ids}
    frontier: set[str] = set(visited)
    truncated = False

    for _hop in range(radius):
        if not frontier:
            # 提前收敛：这一圈没有新节点，再查也只会得到空集。
            break

        rows = CallEdge.objects.filter(
            repository_id=repository_id, branch_name__in=_branch_filter(branch)
        ).filter(
            Q(caller_symbol_id__in=frontier) | Q(callee_symbol_id__in=frontier)
        ).values_list("caller_symbol_id", "callee_symbol_id")

        next_frontier: set[str] = set()
        for caller_symbol_id, callee_symbol_id in rows.iterator(
            chunk_size=_CALL_EDGE_CHUNK_SIZE
        ):
            for endpoint in (caller_symbol_id, callee_symbol_id):
                if endpoint is None:
                    # 模块级调用（``caller_symbol_id IS NULL``）无处挂载，
                    # 与全量路径同口径丢弃，⛔ 不造虚拟节点。
                    continue
                node_id = str(endpoint)
                if node_id not in visited:
                    next_frontier.add(node_id)

        if len(next_frontier) > SUBGRAPH_FRONTIER_LIMIT:
            # 截断是**有损**的：子图会缺一部分邻接。如实置标记，由上层与日志透出。
            next_frontier = set(list(next_frontier)[:SUBGRAPH_FRONTIER_LIMIT])
            truncated = True

        visited |= next_frontier
        frontier = next_frontier

    return visited, truncated


def load_subgraph(
    repository_id: str,
    branch: str = "",
    *,
    seed_symbol_ids: Sequence[str],
    depth: int,
    matcher: ExclusionMatcher,
    exclusion_fingerprint: str,
    include_low_confidence: bool = False,
) -> CodeGraph:
    """装配以种子符号为中心、深度受限的**诱导子图**（GRAPH-03 的降级路径）。

    超预算大仓（单图估算 > ``CODE_GRAPH_MAX_GRAPH_BYTES``）不走 :func:`load_graph`
    而走这里。这**不是可选优化**：全量装配的 2–4 秒纯 CPU 会在
    ``thread_sensitive=True`` 的共享执行器上阻塞其他 ORM 工作，子图才是大仓不拖垮
    进程的真正防线。

    **半径取 ``depth + 1``**：调用方拿到子图之后还要在上面做 ``depth`` 跳遍历，多留
    一跳才能保证边界节点的邻接是完整的——否则第 ``depth`` 层的节点会因为「它的邻居
    没被装进来」而看起来像叶子，上层得出的影响面会在边界处莫名截断。

    🚨 与 :func:`load_graph` 同款契约：``matcher`` 与 ``exclusion_fingerprint`` 是
    **必填关键字参数**，由 ``cache.py`` 解析一次后注入。⛔ 本函数**不得**调用
    ``access.build_matcher_and_fingerprint`` —— 同一次请求内二次解析 = 一次 DB 读 +
    该仓全部 glob/regex 重新编译，且这条同步路径吃不到 ``build_matcher_for_repo``
    的 60s ``_matcher_cache``（模块 docstring ④）。

    :param seed_symbol_ids: 查询种子。⚠️ 由调用方传入，**超级枢纽种子会让子图退化
        成全图**——每轮 frontier 因此设了 :data:`SUBGRAPH_FRONTIER_LIMIT` 上限。
    :param depth: 调用方随后要在子图上走的跳数；本函数按 ``depth + 1`` 收敛。

    .. note::
       **传给下游的遍历纪律**（RESEARCH Pitfall 10）：拿到这张子图后，深度受限遍历
       一律用 ``nx.bfs_tree(g, src, depth_limit=d)`` 或
       ``itertools.islice(nx.bfs_layers(g, [src]), d)``；⛔ **绝不**写
       ``list(nx.bfs_layers(...))[:d]`` —— ``bfs_layers`` 是生成器，``list()`` 会先
       物化整个可达分量再切片，实测 97.3ms vs 0.0ms（结果完全相同）。反向遍历用
       ``g.reverse(copy=False)`` 只读视图（建视图 0.1ms），⛔ 不要 ``copy=True``
       （完整复制，内存翻倍）。

    .. note::
       与 :func:`load_graph` 相同，``estimated_bytes`` / ``partial_edges`` 由
       ``cache.py`` 覆写；``degraded`` 在这里就已经是终值——``"on_demand_subgraph"``，
       或 frontier 撞上 :data:`SUBGRAPH_FRONTIER_LIMIT` 时的
       ``"on_demand_subgraph_truncated"``（后者意味着子图**缺了一部分邻接**）。
    """
    started = time.perf_counter()

    graph: nx.MultiDiGraph = nx.MultiDiGraph()
    is_excluded = make_path_exclusion_memo(matcher)

    reachable_ids, frontier_truncated = _expand_seed_ids(
        repository_id=str(repository_id),
        branch=branch,
        seed_symbol_ids=seed_symbol_ids,
        # 多留一跳，让边界节点的邻接完整。
        radius=depth + 1,
    )

    # 只按最终 symbol_id 集合取 ``Symbol`` 行 —— exclusion 与 overlay 去重与全量路径
    # 完全同口径（同一个记忆化闭包、同一个整文件去重键），子图路径不存在「泄漏面比
    # 全量路径宽」的可能。
    nodes = _load_symbol_nodes(
        graph,
        repository_id=str(repository_id),
        branch=branch,
        is_excluded=is_excluded,
        restrict_symbol_ids=reachable_ids,
    )
    edges = _load_call_edges(
        graph,
        repository_id=str(repository_id),
        branch=branch,
        nodes=nodes,
        include_low_confidence=include_low_confidence,
        restrict_caller_ids=reachable_ids,
    )
    cross_repo = _load_cross_repo_edges(
        graph,
        repository_id=str(repository_id),
        nodes=nodes,
    )
    chunk_evidence, chunk_evidence_truncated_count = _load_chunk_evidence(
        repository_id=str(repository_id),
        branch=branch,
        nodes=nodes,
    )

    resolution_rate = edges.resolution_rate
    duration_ms = round((time.perf_counter() - started) * 1000, 2)

    meta = GraphMeta(
        repository_id=str(repository_id),
        branch=branch,
        node_count=graph.number_of_nodes(),
        edge_count=graph.number_of_edges(),
        estimated_bytes=0,
        resolution_rate=resolution_rate,
        low_resolution=resolution_rate < LOW_RESOLUTION_THRESHOLD,
        partial_edges=False,
        partial_reason="",
        # 🔔 上层工具必须透出：结论的覆盖面小于全图。
        # 🚨 截断是**第二档**语义，必须与「完整的深度受限子图」区分开：撞上
        #    ``SUBGRAPH_FRONTIER_LIMIT`` 的子图**缺了一大块邻接**，而日志不是给 agent
        #    看的。复用 ``degraded`` 承载这一档，避免为此再动 16 字段契约。
        degraded=(
            "on_demand_subgraph_truncated" if frontier_truncated else "on_demand_subgraph"
        ),
        cross_repo_unresolved_count=cross_repo.unresolved_count,
        cross_repo_branch_unfiltered=cross_repo.loaded_count > 0,
        excluded_file_count=nodes.excluded_file_count,
        # 如实声明装配口径：这张图是按「装载裸名边」还是「安全默认值」建的。
        include_low_confidence=include_low_confidence,
        built_signature=exclusion_fingerprint,
        built_at=timezone.now(),
    )

    _log_degraded_subgraph(
        repository_id=str(repository_id),
        branch=branch,
        seed_count=len(seed_symbol_ids),
        depth=depth,
        node_count=meta.node_count,
        edge_count=meta.edge_count,
        frontier_truncated=frontier_truncated,
        duration_ms=duration_ms,
        chunk_evidence_truncated_count=chunk_evidence_truncated_count,
    )

    return CodeGraph(meta=meta, graph=graph, chunk_evidence=chunk_evidence)


def load_graph(
    repository_id: str,
    branch: str = "",
    *,
    matcher: ExclusionMatcher,
    exclusion_fingerprint: str,
    include_low_confidence: bool = False,
) -> CodeGraph:
    """装配 ``(repository, branch)`` 的内存符号图。

    全同步：本函数连同其调用的一切由 ``cache.py`` **一次性** ``sync_to_async`` 包裹
    （RESEARCH Pattern 1 / Pitfall 7 —— 让「持锁」与「await」在物理上不可能重叠）。

    :param repository_id: 仓库主键。调用方须**已经**过了
        ``access.ensure_repository_readable``（本函数不重复校验可读性）。
    :param branch: ``""`` = base；非空时取 base ∪ 本分支的 overlay。
    :param matcher: exclusion 匹配器。🚨 **必填关键字参数，由 ``cache.py`` 解析后注入**
        ——⛔ 本模块不调 ``build_matcher_and_fingerprint``，理由见模块 docstring ④。
    :param exclusion_fingerprint: 该仓有效规则集的 16 位指纹，同样由 ``cache.py`` 注入。
        本函数只把它写进 :attr:`GraphMeta.built_signature`，**不重算**。
    :param include_low_confidence: 是否装载裸名边（默认否）。开启时裸名边仍须过三道
        过滤。⚠️ 本开关**不影响** :attr:`GraphMeta.resolution_rate` 的取值。

    :returns: :class:`CodeGraph` 单值——指纹既然是入参，就不必再作为返回值往回传。

    .. note::
       ⚠️ **跨仓边无法按分支过滤**：``CrossRepoApiCall`` 的调用侧
       ``ApiCallSite`` **没有 ``branch_name`` 字段**（``Endpoint`` 侧有），所以
       ``branch`` 入参对 ``cross_repo`` 档不起作用——feature 分支上看到的跨仓边其实
       是**全分支合集**。这是数据模型缺口，本相位不改表，改为在装配到跨仓边时把
       :attr:`GraphMeta.cross_repo_branch_unfiltered` 置 ``True`` 如实声明，由上层
       工具透出。

    .. note::
       ``partial_edges`` / ``degraded`` / ``estimated_bytes`` 由 ``cache.py``
       （Plan 121-07 / 121-08）在装配后按实际情况覆写。
    """
    started = time.perf_counter()

    graph: nx.MultiDiGraph = nx.MultiDiGraph()
    is_excluded = make_path_exclusion_memo(matcher)

    nodes = _load_symbol_nodes(
        graph,
        repository_id=str(repository_id),
        branch=branch,
        is_excluded=is_excluded,
    )
    edges = _load_call_edges(
        graph,
        repository_id=str(repository_id),
        branch=branch,
        nodes=nodes,
        include_low_confidence=include_low_confidence,
    )
    cross_repo = _load_cross_repo_edges(
        graph,
        repository_id=str(repository_id),
        nodes=nodes,
    )
    chunk_evidence, chunk_evidence_truncated_count = _load_chunk_evidence(
        repository_id=str(repository_id),
        branch=branch,
        nodes=nodes,
    )

    resolution_rate = edges.resolution_rate
    duration_ms = round((time.perf_counter() - started) * 1000, 2)

    meta = GraphMeta(
        repository_id=str(repository_id),
        branch=branch,
        node_count=graph.number_of_nodes(),
        edge_count=graph.number_of_edges(),
        # 字节记账归 ``cache.py``（Plan 121-07 的 ``estimate_graph_bytes`` 与
        # ``NODE_COST_BYTES`` / ``EDGE_COST_BYTES`` 常数都在那边）：装配后由它按
        # **实际** node/edge 计数重算并覆写。⛔ loader 不复制那两个常数——两处各存
        # 一份必然漂移，而准入判据与 LRU 记账必须用同一个估算函数。
        estimated_bytes=0,
        resolution_rate=resolution_rate,
        low_resolution=resolution_rate < LOW_RESOLUTION_THRESHOLD,
        # 半新图判定（GRAPH-02）由 ``cache.py`` 在取图链路上做——它才看得见
        # ``detect_edge_build_in_flight`` 的结果。loader 只如实报「我装配了什么」。
        partial_edges=False,
        partial_reason="",
        degraded="",
        cross_repo_unresolved_count=cross_repo.unresolved_count,
        # 语义缺口如实声明：``ApiCallSite`` **没有 ``branch_name`` 字段**，跨仓边无从
        # 按分支过滤——feature 分支上看到的跨仓边其实是全分支合集。只有真的装配到
        # 跨仓边时才置真：没有跨仓边就不存在这个缺口，长鸣的标记等于失效的标记。
        cross_repo_branch_unfiltered=cross_repo.loaded_count > 0,
        excluded_file_count=nodes.excluded_file_count,
        # 如实声明装配口径：这张图是按「装载裸名边」还是「安全默认值」建的。上层据此
        # 自检手上这张图是否可能含 bare_name 边，⛔ 不必去遍历边集反推。
        include_low_confidence=include_low_confidence,
        # loader 手上只有 exclusion 这一个分量；完整的复合签名（水位 ‖ 两条边构建轨 ‖
        # 计数 ‖ 规则指纹）由 ``cache.py`` 用 ``signature.compute_signature`` 算好后覆写。
        built_signature=exclusion_fingerprint,
        built_at=timezone.now(),
    )

    _log_assembled(
        repository_id=str(repository_id),
        branch=branch,
        node_count=meta.node_count,
        edge_count=meta.edge_count,
        resolution_rate=resolution_rate,
        duration_ms=duration_ms,
        overlay_shadowed_count=nodes.overlay_shadowed_count,
        dropped_no_caller_count=edges.dropped_no_caller_count,
        dropped_missing_node_count=edges.dropped_missing_node_count,
        dropped_bare_filtered_count=edges.dropped_bare_filtered_count,
        chunk_evidence_truncated_count=chunk_evidence_truncated_count,
    )

    return CodeGraph(meta=meta, graph=graph, chunk_evidence=chunk_evidence)
