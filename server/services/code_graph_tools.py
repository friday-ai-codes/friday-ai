"""壳层共用的 ORM / 编排**原语**层（Phase 122，IMPACT-05）。

为什么这个文件不在 ``services/code_graph/`` 包内
================================================
**唯一的理由是 ORM 边界（D-01）**。Phase 121 把 ORM 严格收在包内的 ``loader.py``
一处，包内其余模块（``model`` / ``impact`` / ``trace`` / ``symbol_resolve``）零 Django、
零 ORM，纯函数只吃 ``MultiDiGraph``。而本模块**必须**直查 ``Symbol``（候选的
``signature`` 补取）与 ``Repository``（staleness 三态），放进包内即破那条分层。

⛔ **「在包外」不等于「不受观测契约管」**。``tests/services/code_graph/test_access.py::
test_observability_contract`` 原先只 glob 包内 ``*.py``，本文件因此天然落在扫描面之外
——**那是缺口，不是豁免**。该用例已由本 plan（122-05 Task 4）显式扩展扫描面，把本文件
加进 ``_SIBLING_GUARDED_MODULES``：事件名静态可解析、``code_graph_`` 前缀、
``component="code_graph"``、``error=`` 必过 ``redact_secrets_in_text`` 四条判据逐字不变。
⚠️ 顺带更正一条早期表述：本模块声明的**每一个**事件都是 ``category="sampling"``；
``caller`` 类事件要到 122-08 / 122-09 的壳层才出现，「要发 caller 事件」从来不是本文件
留在包外的理由。

装什么
======
两个壳（MCP / 对话）共用的编排原语，一件事一个函数：

- :func:`fetch_graph_for_tool` —— 取图，**种子与深度必传**（D-24）。
- :data:`GRAPH_ERROR_MESSAGES` / :func:`graph_error_to_tool_error` —— ``GraphError``
  逐类翻译成 ``(error_code, 面向 agent 的文案)``（D-03）。
- :func:`staleness_payload` —— 索引新鲜度声明（D-22）。
- :func:`degradation_payload` —— ``GraphMeta`` 上五个降级标记 + **数值**
  ``resolution_rate`` 的透出（D-23）。
- :func:`resolve_symbol_candidates` / :func:`resolution_to_payload` —— 取图**之前**的
  ORM 侧符号解析与重名候选（D-19）。

上半层（:func:`run_impact` / :func:`run_trace`）是两个壳共用的**唯一**编排入口
（D-21）：壳只做校验 → 调它 → 渲染 → 留痕，逻辑不许在壳里分叉。

边界与已知翻车点
================
① **本层不 catch** ``GraphError``（D-03）。原语与内核都不吞，翻译发生在壳层。
   ⛔ 任何调用方都不许把 ``GraphError`` catch 成空结果——空影响面会被 agent 读成
   「改这里没影响」，是本相位最危险的误导形态。

② **``depth`` 与 ``seed_symbol_ids`` 都是必填关键字参数、无默认值**。
   ``GraphService.get_graph`` 的 ``depth`` 缺省是 **2**（``cache.py:93``），而 impact 的
   ``max_depth`` 缺省是 **3**——不显式传就会让子图边界比遍历深度浅一层，d3 莫名残缺。
   签名上不给默认值，是让「忘了传」在写代码时就报错而不是在生产上报错。

③ **子图路径的性能特性与小仓完全不同**（``cache.py:833-845``）：它既不进缓存也不进
   single-flight，大仓每次都重新装配、并发各建各的。这是已知设计，验收时大仓与小仓
   必须分开量，⛔ 不要拿小仓的 p99 去推大仓。

④ **图相关一律经包根 barrel**（D-02）：``from services.code_graph import …``。
   ⛔ 任何形态的 ``loader`` / ``cache`` / ``signature`` / ``access`` 直连都会让
   ``test_no_upper_layer_imports_internal_submodules`` 当场变红；本模块是那道全仓 AST
   守护的第一个真实承压者。ORM 模型走**函数体内 lazy import**（与
   ``tests/services/code_graph/conftest.py`` 同款约定），避免 ``services`` 包在 Django
   app loading 早期触发模型导入。

⑤ **错误细节不出墙**（威胁登记 T-122-错误细节泄漏）：翻译只取映射表常量与
   ``exc.message``，⛔ 不用 ``str(exc)``（``__str__`` 会把 ``details`` 拼上去）、
   ⛔ 不透 ``exc.details``——那里面是 ``estimated_bytes`` / ``max_graph_bytes``
   这类内部内存量。``details`` 只进（已脱敏的）日志。
"""

from __future__ import annotations

import re
import time
from collections.abc import Mapping, Sequence
from typing import Any, Final

import structlog

from common.logging import redact_secrets_in_text
from services.code_graph import (
    LOW_RESOLUTION_THRESHOLD,
    REDACTED_REPOSITORY,
    CodeGraph,
    GraphAccessDenied,
    GraphBuildFailed,
    GraphBuildTimeout,
    GraphError,
    GraphMeta,
    GraphNotIndexed,
    get_graph_service,
)
from services.code_graph.impact import (
    DEFAULT_MAX_DEPTH,
    DEFAULT_RESULT_LIMIT,
    RiskLevel,
    analyze_impact,
    grade_risk,
)
from services.code_graph.symbol_resolve import (
    CANDIDATE_LIMIT,
    SymbolCandidate,
    SymbolResolution,
    resolve_symbol_in_graph,
)
from services.code_graph.trace import DEFAULT_ALT_PATH_CAP, trace_path

logger = structlog.get_logger(__name__)

# 事件名常量（形态对齐包内 ``cache.py`` / ``access.py``）。
# ⚠️ 前缀不得缩写：``code_graph_`` 是观测契约的强制前缀，扫描面已含本文件。
_EVENT_GRAPH_FETCHED: Final[str] = "code_graph_tool_graph_fetched"
_EVENT_CANDIDATES_RESOLVED: Final[str] = "code_graph_tool_candidates_resolved"
_EVENT_DETECT_CHANGES_STARTED: Final[str] = "code_graph_detect_changes_started"
_EVENT_DETECT_CHANGES_COMPLETED: Final[str] = "code_graph_detect_changes_completed"
_EVENT_DETECT_CHANGES_FAILED: Final[str] = "code_graph_detect_changes_failed"

# compare 形参：完整 40 位 hex（大小写均可）→ ensure_mirror_sha；否则当分支名。
_FULL_SHA_RE: Final[re.Pattern[str]] = re.compile(r"^[0-9a-f]{40}$", re.IGNORECASE)

# 候选条目上 ``signature`` 的字符上限（D-17 的 token 纪律）。``Symbol.signature`` 是
# TextField、可长达数 KB，一次 20 条候选原样吐出去就能吃掉几千 token，而 agent 消歧只
# 需要看个大概形状。超出时截断并补省略号，让「这条被截过」肉眼可见。
CANDIDATE_SIGNATURE_MAX_CHARS: Final[int] = 200

# ``异常类 → (error_code, 面向 agent 的文案)``。形态照本仓唯一的同类先例
# ``mcp_tools/views.py::_MIRROR_ERROR_STATUS``（异常码 → HTTP 码的字面量表）。
#
# 🚨 文案是**给 agent 读的下一步指引**，不是排障信息：每一条都要能回答「我现在该做
# 什么」。⛔ 表里不得出现任何内部量（字节数、预算值、内部模块名）。
GRAPH_ERROR_MESSAGES: Final[Mapping[type[GraphError], tuple[str, str]]] = {
    GraphNotIndexed: (
        "repository_not_indexed",
        "仓库尚未建立索引，无法分析影响面；请先完成索引后重试",
    ),
    GraphAccessDenied: ("repository_access_denied", "无权访问该仓库"),
    GraphBuildTimeout: ("graph_build_timeout", "代码图构建超时，请稍后重试"),
    GraphBuildFailed: ("graph_build_failed", "代码图构建失败"),
    GraphError: (
        "graph_unavailable",
        "代码图当前不可用；若为超大仓库，请先定位起点符号再查影响面",
    ),
}

# 按需子图种子深度（``run_trace``）：子图路径按 ``radius = depth + 1`` 扩张，3
# 已能覆盖绝大多数「两点之间几跳」的实际查询；更深的路径在按需子图上可能查不到，
# 无路径结果里必须如实声明（见 :func:`run_trace` 第 ⑤ 步）。
_TRACE_SEED_DEPTH: Final[int] = 3

# 按需子图上「无路径」时的补充声明——⛔ 不把「子图里没查到」说成「确实无路径」。
_SUBGRAPH_NO_PATH_DECLARATION: Final[str] = (
    "本次在按需子图上查询，超出子图覆盖范围的更长路径可能未被检出"
)

__all__ = [
    "CANDIDATE_SIGNATURE_MAX_CHARS",
    "GRAPH_ERROR_MESSAGES",
    "degradation_payload",
    "fetch_graph_for_tool",
    "graph_error_to_tool_error",
    "resolution_to_payload",
    "resolve_symbol_candidates",
    "resolve_tool_graph_branch",
    "run_detect_changes",
    "run_impact",
    "run_trace",
    "staleness_payload",
    "tool_trace_payload",
]


# 埋点自成函数、事件名常量直接写在 ``logger.debug`` 的第一个位置实参上，
# ⛔ 不抽成 ``_emit(event, **fields)`` 那样的通用转发器：观测契约要求事件名在**该调用
# 点**可静态解析成字面量，包一层后 AST 只看得到一个形参名（Phase 121 有四个 plan 各踩
# 过一次）。观测 best-effort —— 任何异常吞掉，绝不反噬取图主流程。


def _log_graph_fetched(
    *,
    repository_id: str,
    node_count: int,
    edge_count: int,
    degraded: str,
    seed_count: int,
    depth: int,
    duration_ms: float,
) -> None:
    """一次取图的结构化埋点。

    取 DEBUG + ``category="sampling"``：取图是两个工具每次调用都会走的高频步骤，
    INFO 会直接刷屏（``.cursor/rules/observability-logging.mdc`` 的级别纪律）。
    ⛔ 不记符号名、不记文件路径、不记种子 id——只记计数与档位（威胁登记
    T-122-exclusion 回流 / T-122-日志放大）。
    """
    try:
        logger.debug(
            _EVENT_GRAPH_FETCHED,
            component="code_graph",
            category="sampling",
            repository_id=repository_id,
            node_count=node_count,
            edge_count=edge_count,
            degraded=degraded,
            seed_count=seed_count,
            depth=depth,
            duration_ms=duration_ms,
        )
    except Exception:  # noqa: BLE001 — 观测失败绝不反噬业务（不是安全降级分支）
        pass


def _log_candidates_resolved(
    *, total_candidates: int, truncated: bool, by_uid: bool, duration_ms: float
) -> None:
    """ORM 侧符号解析的结构化埋点。

    🚨 **只记计数与两个布尔量，⛔ 不记符号名、不记 ``file_path``、不逐候选打日志**
    （威胁登记 T-122-exclusion 回流 / T-122-日志放大）。符号名与路径是本函数唯一的外泄
    面；重名是 19.3% 的主路径，逐候选打日志等于按候选数放大日志量。
    """
    try:
        logger.debug(
            _EVENT_CANDIDATES_RESOLVED,
            component="code_graph",
            category="sampling",
            total_candidates=total_candidates,
            truncated=truncated,
            by_uid=by_uid,
            duration_ms=duration_ms,
        )
    except Exception:  # noqa: BLE001 — 观测失败绝不反噬业务（不是安全降级分支）
        pass


def graph_error_to_tool_error(exc: GraphError) -> tuple[str, str]:
    """把一个 ``GraphError`` 翻译成 ``(error_code, 面向 agent 的文案)``（D-03）。

    按 ``type(exc).__mro__`` 顺序在 :data:`GRAPH_ERROR_MESSAGES` 里查**最具体**的一项，
    查不到时落到 ``GraphError`` 兜底档。新增子类不加表项时行为是「降级到父类文案」，
    不是崩——但那属于遗漏，应当补表。

    🚨 **⛔ 任何调用方都不许把** ``GraphError`` **catch 成空结果**。未索引仓的 impact
    必须是错误响应而不是 ``{"affected": []}``：空影响面会被 agent 读成「改这里没影响」，
    进而得出「这次改动安全」的结论——那是本相位最危险的误导形态。Phase 121 已经把
    「绝不返回空图」写成硬约束（``model.py::GraphNotIndexed`` 的 docstring），本函数
    是那条约束在工具面的延续：**翻译**它，不要**吞**它。

    🚨 文案只取表里的常量与 ``exc.message``。⛔ **不得**把 ``str(exc)`` 或
    ``exc.details`` 直出给 agent——``GraphError.__str__`` 会把 ``details`` 拼上去，而
    那里面是 ``estimated_bytes`` / ``max_graph_bytes`` 这类内部内存量（威胁登记
    T-122-错误细节泄漏）。``details`` 只进（已脱敏的）日志。
    """
    code, base = GRAPH_ERROR_MESSAGES[GraphError]
    for klass in type(exc).__mro__:
        entry = GRAPH_ERROR_MESSAGES.get(klass)
        if entry is not None:
            code, base = entry
            break

    # ``exc.message`` 是本仓自己写死的短句（``access.py`` / ``cache.py`` 的 raise 点），
    # 不含任何内部量；``details`` 才是内部量的所在，此处刻意不碰。
    detail = (exc.message or "").strip()
    if detail and detail not in base:
        return code, f"{base}（{detail}）"
    return code, base


async def fetch_graph_for_tool(
    repository_id: str,
    branch: str,
    *,
    user: Any | None,
    seed_symbol_ids: Sequence[str],
    depth: int,
    include_low_confidence: bool = False,
) -> CodeGraph:
    """取一张供 impact / trace 使用的图——**种子与深度必传**（D-24）。

    :param repository_id: 仓库主键。
    :param branch: ``""`` = base 分支（与 ``Symbol.branch_name`` 同口径）。
    :param user: 触发用户；``None`` 表示后台/系统路径。**每次调用**都会在
        ``get_graph`` 内部跑一遍 ``ensure_repository_readable``，⛔ 不因缓存命中跳过。
    :param seed_symbol_ids: 起点符号 id。**必填关键字参数、无默认值**——D-24 不是
        优化而是必经分支：Phase 121 的 ``get_graph`` 对超预算大仓在**无种子**时直接
        抛 ``GraphError``（``cache.py:970``），而 impact / trace 天然有种子，忘传就会
        在大仓上凭空多出一类失败。签名不给默认值，是让「忘了传」在写代码时报错。
    :param depth: 调用方随后要在图上走的跳数。**同样必填**：``get_graph`` 的缺省是
        **2**（``cache.py:93``）而 impact 的 ``max_depth`` 缺省是 **3**，省略会让子图
        边界比遍历深度浅一层——d3 那层节点看起来像叶子，影响面在边界处莫名残缺，
        且没有任何信号。
    :param include_low_confidence: 是否装载裸名边（默认否，是缓存键的一维）。

    :raises GraphError: 及其四个子类，**原样上抛**。⛔ 本函数不 catch（D-03 的分层：
        内核与原语不吞，壳层调 :func:`graph_error_to_tool_error` 翻译）。

    .. note::
       **子图路径的性能特性与全量路径完全不同**（``cache.py:833-845``）：带种子的请求
       既**不查也不进缓存**（缓存键里没有种子与深度这两维，种子空间无界），也**不进
       single-flight**（让不同种子的并发请求共用一个占位，等待者拿到的会是别人种子的
       子图——那是错图不是慢图）。因此大仓上每次调用都是一次全新装配、并发各建各的。
       验收时大仓与小仓必须分开量，⛔ 不要拿小仓的缓存命中率去推大仓。
    """
    seeds = list(seed_symbol_ids)
    started = time.perf_counter()
    graph = await get_graph_service().get_graph(
        repository_id,
        branch,
        user=user,
        include_low_confidence=include_low_confidence,
        seed_symbol_ids=seeds,
        depth=depth,
    )
    _log_graph_fetched(
        repository_id=str(repository_id),
        node_count=graph.meta.node_count,
        edge_count=graph.meta.edge_count,
        degraded=graph.meta.degraded,
        seed_count=len(seeds),
        depth=depth,
        duration_ms=round((time.perf_counter() - started) * 1000, 2),
    )
    return graph


async def staleness_payload(repo: Any) -> dict[str, Any]:
    """索引新鲜度声明——「你看到的结论是哪一版代码的」（D-22）。

    :param repo: 一个 ``repositories.models.Repository`` 实例（已由调用方取好）。

    三态（``fresh`` / ``stale`` / ``unknown``）一律走
    ``repositories.freshness_service.compute_freshness_status``，⛔ 不自己比 sha：那张
    决策表里「``remote_head_checked_at is None`` ⇒ unknown」这条最容易漏，漏了就会把
    「从没查过远端」误报成 ``fresh``。

    ⛔ **请求路径不起 git 子进程**。``behind_commits`` 是定时任务
    ``update_behind_commits_for_stale_repos`` 预先算好的库字段；现算一次是两个
    ``create_subprocess_exec`` 加 30s / 15s 两段超时，放在工具调用路径上不可接受。

    🚨 ``behind_commits is None`` 是**真实可达**的分支，不是理论情形：
    ``_calculate_commit_distance`` 在本地没有 clone 时返回 ``None``
    （``freshness_service.py:88-94``），而那个定时任务只覆盖 ``auto_index_enabled=True``
    的仓。此时降级为只报 ``as_of <sha 前 12 位>`` 并明说落后数未知——
    ⛔ **绝不编造一个数字**：一个凭空的「落后 3 commits」会让 agent 以为索引只差一点点，
    而真相可能是差了三百个 commit。
    """
    from repositories.freshness_service import compute_freshness_status

    status = compute_freshness_status(repo)
    as_of = repo.last_indexed_commit_sha or ""
    behind = repo.behind_commits
    calculated_at = repo.behind_commits_calculated_at

    if behind is None:
        short = as_of[:12]
        declaration = (
            f"索引 as_of {short}；落后提交数未知"
            if short
            else "索引水位未知；落后提交数未知"
        )
    elif behind == 0:
        declaration = "索引与远端一致"
    else:
        declaration = f"索引落后 {behind} commits"

    return {
        "as_of": as_of,
        "freshness": status,
        "behind_commits": behind,
        "behind_commits_calculated_at": (
            calculated_at.isoformat() if calculated_at is not None else None
        ),
        "declaration": declaration,
    }


def degradation_payload(meta: GraphMeta) -> dict[str, Any]:
    """把 ``GraphMeta`` 上「🔔 上层工具必须透出」的字段原样搬进工具输出（D-23）。

    键名与 :class:`~services.code_graph.GraphMeta` 的字段名**逐字一致**：两边各起一个
    名字，下一个人就得在两处之间做心算映射，而这些字段恰恰是「结论有多可信」的全部
    依据，映射错一个就是一次静默的误导。

    🚨 ``resolution_rate`` 是**数值**且**必带**，``declarations`` 里的解析率声明同样
    **无条件**追加——⛔ 不得只在 ``low_resolution is True`` 时才提醒。121-10 在生产
    218 个仓上实测：解析率中位数只有 **0.17**，全库最高的一个仓也才 0.56，没有任何一个
    仓「解析得好」。在这个常态下 ``low_resolution`` 表达的是「**比本仓常态更差**」，
    布尔量本身没有信息量，区分不出 0.17 与 0.55——而这两者对影响面结论的可信度是天壤
    之别。

    ``degraded`` 的两个子档措辞**必须不同**：``on_demand_subgraph`` 的子图在其深度内是
    完整的（「影响面就这么大」这句话在该深度内说得出口），
    ``on_demand_subgraph_truncated`` 则缺了一部分邻接（同一句话说不出口）。合成一句会让
    上层无从分辨自己能不能下那个结论。
    """
    unresolved_pct = round((1.0 - meta.resolution_rate) * 100)
    declarations: list[str] = [
        f"本仓约 {unresolved_pct}% 的调用边未解析到具体符号，影响面结论偏保守"
    ]

    if meta.low_resolution:
        declarations.append(
            f"本仓解析率 {meta.resolution_rate:.2f} 低于 {LOW_RESOLUTION_THRESHOLD:.2f}"
            "，比本仓常态更差，结论请按更保守的口径采信"
        )
    if meta.partial_edges:
        reason = f"（在途原因：{meta.partial_reason}）" if meta.partial_reason else ""
        declarations.append(f"边构建在途，结果可能不完整{reason}")
    if meta.degraded == "on_demand_subgraph":
        declarations.append(
            "已降级为按需子图，覆盖面小于全图（该子图在其深度内是完整的）"
        )
    elif meta.degraded == "on_demand_subgraph_truncated":
        declarations.append("按需子图的某一轮邻接被截断，结论可能在边界处断掉")
    if meta.cross_repo_unresolved_count > 0:
        # ⚠️ 这个数是**装配时**丢弃的跨仓边条数，与 122-06「本次 ORM 查到 N 条跨仓调用」
        #    是两个不同的数，键名与文案都不许混。
        declarations.append(
            f"装配时有 {meta.cross_repo_unresolved_count} 条跨仓边无法定位到符号，已丢弃"
        )
    if meta.cross_repo_branch_unfiltered:
        declarations.append("跨仓边无法按分支过滤")

    return {
        "resolution_rate": meta.resolution_rate,
        "low_resolution": meta.low_resolution,
        "partial_edges": meta.partial_edges,
        "partial_reason": meta.partial_reason,
        "degraded": meta.degraded,
        "cross_repo_unresolved_count": meta.cross_repo_unresolved_count,
        "cross_repo_branch_unfiltered": meta.cross_repo_branch_unfiltered,
        "include_low_confidence": meta.include_low_confidence,
        "node_count": meta.node_count,
        "edge_count": meta.edge_count,
        "excluded_file_count": meta.excluded_file_count,
        "declarations": declarations,
    }


def _truncate_signature(raw: str) -> str:
    """把 ``Symbol.signature`` 截到 :data:`CANDIDATE_SIGNATURE_MAX_CHARS`。

    超出时补一个省略号，让「这条被截过」在渲染结果里肉眼可见——静默截断会让 agent 以为
    自己看到的是完整签名，进而按一个残缺的形参表做判断。
    """
    text = (raw or "").strip()
    if len(text) <= CANDIDATE_SIGNATURE_MAX_CHARS:
        return text
    return text[:CANDIDATE_SIGNATURE_MAX_CHARS] + "…"


def _code_graph_access():
    """取 ``access`` 子模块——包外兄弟不得 ``from services.code_graph.access import …``。

    AST 红线（``test_no_upper_layer_imports_internal_submodules``）拦的是静态
    ``ImportFrom``；这里用 ``importlib`` 取同一模块，与 MCP 测试 fixture 同款，避免
    绕过 ``get_graph`` 的**写法**进入扫描面，同时仍复用 exclusion / ACL 单一事实源。
    """
    import importlib

    return importlib.import_module("services.code_graph.access")


async def _exclusion_matcher_for_repo(repository_id: str):
    """异步取 exclusion matcher（与 ``services.exclusion`` 单一事实源同源）。

    ⛔ 不走 ``access.build_matcher_and_fingerprint``：那是给 ``sync_to_async`` 包着的
    取图热路径用的同步 API，在 async ORM 解析里直接调会炸 ``SynchronousOnlyOperation``。
    """
    from services.exclusion import build_matcher_for_repo

    return await build_matcher_for_repo(str(repository_id))


async def resolve_symbol_candidates(
    *,
    repository_id: str,
    branch_names: Sequence[str],
    symbol_id: str | None = None,
    name: str | None = None,
    file_path: str | None = None,
    symbol_type: str | None = None,
) -> SymbolResolution:
    """在 **ORM** 上定位符号：uid 优先，重名给带 ``signature`` 的候选列表（D-19）。

    这是「图内定位」的**前置**一半，回答的是「取图**之前**，我该拿哪个 ``symbol_id``
    当种子」——D-24 的鸡生蛋问题：解析需要图，取图需要种子，所以第一遍解析只能在 ORM
    上做。图内那一半由 122-02 的 ``resolve_symbol_in_graph`` 承担，两者返回同一个
    :class:`~services.code_graph.symbol_resolve.SymbolResolution` 契约。

    :param repository_id: 仓库主键。
    :param branch_names: 分支口径，形如 ``["", graph_branch]``（overlay 语义：feature
        分支图 = base 全量 + 分支增量）。``""`` = base，与 ``Symbol.branch_name`` 同口径。
    :param symbol_id: 符号 uid。**给了就只走这条路**：只确认这一行存在且归属本仓，
        ⛔ 绝不在落空时退化去按名字搜——那会让「带 uid 回来」这个消歧闭环失去意义。
    :param name: 符号名，大小写敏感精确匹配。
    :param file_path: 可选收窄——相等，或卡在 ``/`` 边界上的路径后缀。
    :param symbol_type: 可选收窄——大小写不敏感（各产出器口径不一，不该让调用方猜）。

    🚨 ⛔ **任何路径下都不取第一条**。生产 distinct ``(repository_id, name)`` 有 202,661
    组，其中 39,031 组（**19.3%**）非唯一，``(repo, file, name)`` 三元组仍有 24,312 组
    冲突——候选列表是**主路径**而不是异常兜底。本仓的反面教材是
    ``mcp_tools/views.py::FindRelatedChunksView._resolve_source_chunk``：它对重名
    ``.afirst()`` 静默取第一个，正是 D-19 明令禁止的形态，有一条 AST 断言守着本函数
    不重蹈覆辙。

    🚨 **exclusion 与「不存在」合并**（T-122-exclusion）：被 exclusion 挡掉的
    ``file_path`` 视为不存在——不得通过 ``symbol_not_in_graph`` / 歧义候选的
    ``file_path``+``signature`` 泄漏「索引里有、图里没有」。

    预算：先扫可见候选拿未截断总数，再只物化前 :data:`CANDIDATE_LIMIT` 条
    （威胁登记 T-122-遍历 DoS）。⛔ 不物化全量候选——热点名字可能对应上千行。
    """
    # ORM 模型与查询原语一律**函数体内 lazy import**（与
    # ``tests/services/code_graph/conftest.py`` 同款约定）：``services`` 包可能在 Django
    # app loading 早期被 import，模块级触发模型导入会炸在应用注册表上。
    from django.core.exceptions import ValidationError
    from django.db.models import Q

    from codegraph.models import Symbol

    started = time.perf_counter()
    matcher = await _exclusion_matcher_for_repo(repository_id)

    if symbol_id:
        try:
            row = await Symbol.objects.filter(
                id=symbol_id, repository_id=repository_id
            ).values_list("id", "file_path").afirst()
        except (ValidationError, ValueError, TypeError):
            # uid 来自 agent，是不可信入参：非法 UUID 当作「没有这个符号」，
            # ⛔ 不冒泡成 500，也 ⛔ 不退化去按名字搜。
            row = None
        # 被 exclusion 挡掉的路径与「不存在」同一出口——不得区分预言机。
        visible = (
            row is not None and not matcher.is_excluded(str(row[1] or ""))
        )
        _log_candidates_resolved(
            total_candidates=1 if visible else 0,
            truncated=False,
            by_uid=True,
            duration_ms=round((time.perf_counter() - started) * 1000, 2),
        )
        return SymbolResolution(
            resolved=symbol_id if visible else None,
            candidates=(),
            total_candidates=1 if visible else 0,
            truncated=False,
            query=symbol_id,
        )

    if not name:
        return SymbolResolution(
            resolved=None, candidates=(), total_candidates=0, truncated=False, query=""
        )

    queryset = Symbol.objects.filter(
        repository_id=repository_id,
        branch_name__in=list(branch_names),
        name=name,
    )
    if symbol_type:
        queryset = queryset.filter(symbol_type__iexact=symbol_type.strip())
    if file_path:
        wanted = file_path.strip().lstrip("./")
        if wanted:
            # 后缀匹配卡在 ``/`` 边界上：裸 ``endswith`` 会让 ``r.go`` 匹上 ``user.go``，
            # 「收窄参数反而放进不相干的符号」比不支持后缀更糟（同 symbol_resolve 口径）。
            queryset = queryset.filter(
                Q(file_path=wanted) | Q(file_path__endswith=f"/{wanted}")
            )
    # 稳定排序：第三项 ``id`` 不是凑数——生产 24,312 组同文件同名符号在前两项上完全打平，
    # 少了它，同一次查询在两个 worker 上可能给出不同的前 20 条。
    queryset = queryset.order_by("file_path", "start_line", "id")

    # 先取 id+file_path 做 exclusion 过滤（不含 signature，控制物化成本），
    # 再按可见集决定唯一命中 / 歧义 / 截断。
    path_rows = [
        row async for row in queryset.values_list("id", "file_path")
    ]
    visible_ids = [
        str(sym_id)
        for sym_id, path in path_rows
        if not matcher.is_excluded(str(path or ""))
    ]
    total = len(visible_ids)
    if total == 0:
        _log_candidates_resolved(
            total_candidates=0,
            truncated=False,
            by_uid=False,
            duration_ms=round((time.perf_counter() - started) * 1000, 2),
        )
        return SymbolResolution(
            resolved=None, candidates=(), total_candidates=0, truncated=False, query=name
        )

    if total == 1:
        _log_candidates_resolved(
            total_candidates=1,
            truncated=False,
            by_uid=False,
            duration_ms=round((time.perf_counter() - started) * 1000, 2),
        )
        # 唯一命中不构造候选列表，与 ``SymbolResolution`` 的不变式一致：
        # ``resolved`` 非空 ⇒ 候选必空。
        return SymbolResolution(
            resolved=visible_ids[0],
            candidates=(),
            total_candidates=1,
            truncated=False,
            query=name,
        )

    # ``signature`` 与其余五列由**同一次**查询取出：图节点属性里没有它
    # （``loader.py:354-356`` 刻意不取 TextField），再回一次 ORM 就是白白多一趟。
    keep_ids = visible_ids[:CANDIDATE_LIMIT]
    detail_qs = Symbol.objects.filter(id__in=keep_ids).values_list(
        "id", "name", "symbol_type", "file_path", "start_line", "signature"
    )
    by_id: dict[str, tuple[Any, ...]] = {}
    async for row in detail_qs:
        by_id[str(row[0])] = row
    rows = [by_id[sid] for sid in keep_ids if sid in by_id]

    candidates = tuple(
        SymbolCandidate(
            symbol_id=str(row[0]),
            name=str(row[1] or ""),
            symbol_type=str(row[2] or ""),
            file_path=str(row[3] or ""),
            start_line=int(row[4] or 0),
            signature=_truncate_signature(str(row[5] or "")),
        )
        for row in rows
    )
    _log_candidates_resolved(
        total_candidates=total,
        truncated=total > CANDIDATE_LIMIT,
        by_uid=False,
        duration_ms=round((time.perf_counter() - started) * 1000, 2),
    )
    return SymbolResolution(
        resolved=None,
        candidates=candidates,
        total_candidates=total,
        truncated=total > CANDIDATE_LIMIT,
        query=name,
    )


def resolution_to_payload(resolution: SymbolResolution) -> dict[str, Any]:
    """把 :class:`SymbolResolution` 摊成两个壳共用的 dict 形态。

    ``hint`` 在歧义时给出**可执行**的下一步（带 uid 回来，或补 ``file_path`` /
    ``symbol_type`` 收窄），而不是一句「符号不唯一」就把球踢回去——RESEARCH Pitfall 2 §4
    要求「能一次收敛就不要往返两轮」，指引写清楚才有可能一轮收敛。
    """
    ambiguous = bool(resolution.candidates)
    return {
        "resolved": resolution.resolved,
        "ambiguous": ambiguous,
        "candidates": [
            {
                "symbol_id": candidate.symbol_id,
                "name": candidate.name,
                "symbol_type": candidate.symbol_type,
                "file_path": candidate.file_path,
                "start_line": candidate.start_line,
                "signature": candidate.signature,
            }
            for candidate in resolution.candidates
        ],
        "total_candidates": resolution.total_candidates,
        "truncated": resolution.truncated,
        "hint": (
            "符号名不唯一；请带 symbol_id 重试，或补 file_path / symbol_type 收窄"
            if ambiguous
            else ""
        ),
    }


def _branch_label(repo: Any, graph_branch: str | None) -> str:
    """输出信封上的分支展示名：feature 用 ``graph_branch``，否则回退 base/default。"""
    if graph_branch:
        return graph_branch
    return getattr(repo, "base_branch", None) or getattr(repo, "default_branch", "") or ""


def _query_descriptor(
    *,
    symbol_id: str | None,
    symbol: str | None,
    file_path: str | None,
    symbol_type: str | None,
) -> dict[str, Any]:
    """落空 / 歧义响应里回显的查询描述，便于 agent 对照自己刚发的参数。"""
    return {
        "symbol_id": symbol_id,
        "symbol": symbol,
        "file_path": file_path,
        "symbol_type": symbol_type,
    }


def _seed_from_graph(graph: Any, symbol_id: str) -> dict[str, Any]:
    """从图节点属性抽出种子描述块。"""
    attrs = graph.nodes[symbol_id]
    return {
        "symbol_id": symbol_id,
        "name": attrs.get("name", ""),
        "symbol_type": attrs.get("symbol_type", ""),
        "file_path": attrs.get("file_path", ""),
        "start_line": int(attrs.get("start_line") or 0),
    }


def _crosses_repo_from_entries(cross: Sequence[Mapping[str, Any]]) -> bool:
    """穿仓是否成立：任一成功条目或折叠条目即可（unavailable 不算）。

    成功条目带 ``impact``；折叠条目只有 ``repository == REDACTED_REPOSITORY``
    （D-30，无 ``affected_count``）。unavailable 表示「权限已过但对端图不可用」，
    不算进风险分级的穿仓输入——那会把一次临时故障抬成 HIGH。
    """
    return any(
        "impact" in entry or entry.get("repository") == REDACTED_REPOSITORY
        for entry in cross
    )


def _regrade_with_cross_repo(
    impact: Mapping[str, Any], *, crosses_repo: bool
) -> tuple[str, dict[str, Any]]:
    """用跨仓一跳结果重算 ``risk_level`` 与 ``risk_inputs``（D-15 第二个输入）。"""
    d1_count = int(impact["risk_inputs"]["d1_count"])
    best_path_tier = int(impact["risk_inputs"]["best_path_tier"])
    risk = grade_risk(
        d1_count=d1_count,
        crosses_repo=crosses_repo,
        best_path_tier=best_path_tier,
    )
    # 「若证据很强会不会更高」——用 resolved 档序 3 做对照，与内核同口径。
    uncapped = grade_risk(
        d1_count=d1_count, crosses_repo=crosses_repo, best_path_tier=3
    )
    risk_inputs = {
        "d1_count": d1_count,
        "crosses_repo": crosses_repo,
        "best_path_tier": best_path_tier,
        "capped_by_weak_evidence": risk is RiskLevel.MEDIUM
        and uncapped in (RiskLevel.HIGH, RiskLevel.CRITICAL),
    }
    return risk.value, risk_inputs


async def run_impact(
    *,
    repository_id: str,
    repo: Any,
    graph_branch: str | None,
    user: Any,
    symbol_id: str | None = None,
    symbol: str | None = None,
    file_path: str | None = None,
    symbol_type: str | None = None,
    max_depth: int = DEFAULT_MAX_DEPTH,
    min_confidence: float = 1.0,
    include_low_confidence: bool = False,
    limit: int = DEFAULT_RESULT_LIMIT,
    max_cross_repo_hops: int | None = None,
    exclude_test_files: bool = False,
) -> dict[str, Any]:
    """影响面分析的**唯一**编排入口——MCP 与对话两面都只调这一个函数（D-21）。

    ``ok`` / ``error_code`` / ``error`` 三个键构成两面共用的失败语义：同一故障在
    两侧必须落成同一形状，⛔ 不许一面折成空结果、一面报工具坏了。

    ``GraphError``（及子类）是**唯一**从本函数向上冒泡的异常类型——原样上抛，由壳
    层调 :func:`graph_error_to_tool_error` 翻译；其余一切失败（未找到 / 重名 /
    不在图内）都在 ``ok=False`` 里表达。``ok=False`` 且 ``error_code`` 为
    ``ambiguous_symbol`` 时是一次**成功的工具响应**（把消歧权交回 agent），不是
    工具故障（D-19）。

    :param user: **必填**关键字参数。两面的用户来源不同且无共同抽象，在此收敛为
        显式入参，一路透传到取图与跨仓一跳的权限复核。
    :param repo: 已经过索引校验的 ``Repository`` 实例，只用于
        :func:`staleness_payload`。
    :param graph_branch: ``None`` 表示 base 分支（与 MCP
        ``_resolve_graph_branch`` 同口径）；传给取图时转成 ``""``。
    """
    # 延迟导入：``code_graph_cross_repo`` 在模块顶层反向依赖本文件的取图原语，
    # 顶层互引会在任一侧首次 import 时炸成部分初始化。
    from services.code_graph_cross_repo import (
        DEFAULT_MAX_CROSS_REPO_HOPS,
        collect_cross_repo_impact,
    )

    if max_cross_repo_hops is None:
        max_cross_repo_hops = DEFAULT_MAX_CROSS_REPO_HOPS

    query = _query_descriptor(
        symbol_id=symbol_id,
        symbol=symbol,
        file_path=file_path,
        symbol_type=symbol_type,
    )
    branch_names = ["", graph_branch] if graph_branch else [""]

    # ⓪ 仓级 ACL 闸必须在 ORM 解析之前（T-122-exclusion / ME-03）：
    # ambiguous / not_found 会回显 signature，不得在 ensure_repository_readable 之前触碰 Symbol。
    await _code_graph_access().ensure_repository_readable(user, repository_id)

    # ① ORM 先行解析（D-24 鸡生蛋：取图需要种子，解析却要在取图之前）。
    resolution = await resolve_symbol_candidates(
        repository_id=repository_id,
        branch_names=branch_names,
        symbol_id=symbol_id,
        name=symbol,
        file_path=file_path,
        symbol_type=symbol_type,
    )
    if resolution.total_candidates == 0:
        return {
            "ok": False,
            "error_code": "symbol_not_found",
            "error": "未找到匹配的符号；请检查符号名 / symbol_id / file_path",
            "query": query,
        }
    if resolution.candidates:
        # 🚨 在取图之前短路（D-19）——重名是主路径，白建一张图没有意义。
        return {
            "ok": False,
            "error_code": "ambiguous_symbol",
            "error": "符号名不唯一；请带 symbol_id 重试，或补 file_path / symbol_type 收窄",
            "query": query,
            **resolution_to_payload(resolution),
        }

    sid = resolution.resolved
    assert sid is not None  # total==1 且无 candidates ⇒ resolved 必非空

    # ② 取图。⛔ 不 catch GraphError——原样上抛给壳层翻译（D-03）。
    graph = await fetch_graph_for_tool(
        repository_id,
        graph_branch or "",
        user=user,
        seed_symbol_ids=[sid],
        depth=max_depth,
        include_low_confidence=include_low_confidence,
    )

    # ③ 图内确认：种子不在本次图里（按需子图边界等）与「未找到」合并出口——
    # ⛔ 不得再用 symbol_not_in_graph 区分「索引有 / 图没有」（T-122-exclusion 预言机）。
    in_graph = resolve_symbol_in_graph(graph.graph, symbol_id=sid)
    if in_graph.resolved is None:
        return {
            "ok": False,
            "error_code": "symbol_not_found",
            "error": "未找到匹配的符号；请检查符号名 / symbol_id / file_path",
            "query": query,
        }

    # ④ 内核（本文件内唯一调用点；跨仓一跳里对端仓那次不在本文件）。
    impact = analyze_impact(
        graph.graph,
        sid,
        max_depth=max_depth,
        min_confidence=min_confidence,
        include_low_confidence=include_low_confidence,
        limit=limit,
        exclude_test_files=exclude_test_files,
    )

    seed = _seed_from_graph(graph.graph, sid)

    # ⑤ 跨仓一跳 + 声明。折叠 / unavailable 条目原样透传（D-12 / D-14 / D-30）。
    cross = await collect_cross_repo_impact(
        local_repository_id=repository_id,
        symbol_file_path=str(seed["file_path"]),
        symbol_name=str(seed["name"]),
        user=user,
        max_hops=max_cross_repo_hops,
        max_depth=max_depth,
        min_confidence=min_confidence,
        include_low_confidence=include_low_confidence,
    )
    crosses_repo = _crosses_repo_from_entries(cross)
    risk_level, risk_inputs = _regrade_with_cross_repo(
        impact, crosses_repo=crosses_repo
    )

    return {
        "ok": True,
        "tool": "impact_analysis",
        "repository_id": str(repository_id),
        "branch": _branch_label(repo, graph_branch),
        "seed": seed,
        "query": {
            "max_depth": max_depth,
            "min_confidence": min_confidence,
            "include_low_confidence": include_low_confidence,
            "limit": limit,
            "max_cross_repo_hops": max_cross_repo_hops,
            "exclude_test_files": exclude_test_files,
        },
        "groups": impact["groups"],
        "risk_level": risk_level,
        "risk_inputs": risk_inputs,
        "summary": impact["summary"],
        "cross_repo": cross,
        "affected_processes": [],
        "staleness": await staleness_payload(repo),
        "graph": degradation_payload(graph.meta),
    }


async def run_trace(
    *,
    repository_id: str,
    repo: Any,
    graph_branch: str | None,
    user: Any,
    source_symbol_id: str | None = None,
    source: str | None = None,
    source_file_path: str | None = None,
    target_symbol_id: str | None = None,
    target: str | None = None,
    target_file_path: str | None = None,
    min_confidence: float = 1.0,
    include_low_confidence: bool = False,
    alt_path_cap: int = DEFAULT_ALT_PATH_CAP,
) -> dict[str, Any]:
    """调用路径追踪的**唯一**编排入口——与 :func:`run_impact` 同构（D-21）。

    ``ok`` 回答「这次查询做成了吗」；``found`` 回答「两点之间有路吗」。
    ``found is False`` 时 ``ok`` **仍为** ``True``——「确实没有调用关系」是一次成功的
    查询结果，不是工具故障（D-20）。⛔ 把 ``found=False`` 映射成 ``ok=False`` 会让
    agent 把「没有调用关系」误读成「工具坏了」。

    失败语义与 :func:`run_impact` 共用 ``ok`` / ``error_code`` / ``error`` 三键；
    ``GraphError`` 同样是唯一向上冒泡的异常类型。
    """
    branch_names = ["", graph_branch] if graph_branch else [""]

    # ⓪ 仓级 ACL 闸必须在 ORM 解析之前——与 :func:`run_impact` 同序（ME-03）。
    await _code_graph_access().ensure_repository_readable(user, repository_id)

    source_res = await resolve_symbol_candidates(
        repository_id=repository_id,
        branch_names=branch_names,
        symbol_id=source_symbol_id,
        name=source,
        file_path=source_file_path,
    )
    target_res = await resolve_symbol_candidates(
        repository_id=repository_id,
        branch_names=branch_names,
        symbol_id=target_symbol_id,
        name=target,
        file_path=target_file_path,
    )

    if source_res.total_candidates == 0:
        return {
            "ok": False,
            "error_code": "symbol_not_found",
            "error": "未找到 source 端匹配的符号；请检查 source / source_symbol_id / source_file_path",
            "end": "source",
            "query": {
                "source_symbol_id": source_symbol_id,
                "source": source,
                "source_file_path": source_file_path,
                "target_symbol_id": target_symbol_id,
                "target": target,
                "target_file_path": target_file_path,
            },
        }
    if target_res.total_candidates == 0:
        return {
            "ok": False,
            "error_code": "symbol_not_found",
            "error": "未找到 target 端匹配的符号；请检查 target / target_symbol_id / target_file_path",
            "end": "target",
            "query": {
                "source_symbol_id": source_symbol_id,
                "source": source,
                "source_file_path": source_file_path,
                "target_symbol_id": target_symbol_id,
                "target": target,
                "target_file_path": target_file_path,
            },
        }

    if source_res.candidates or target_res.candidates:
        # 🚨 在取图之前短路（D-19）。哪端歧义填哪端 resolution，另一端给已解析 id。
        payload: dict[str, Any] = {
            "ok": False,
            "error_code": "ambiguous_symbol",
            "error": "符号名不唯一；请带 symbol_id 重试，或补 file_path 收窄",
        }
        if source_res.candidates:
            payload["source_resolution"] = resolution_to_payload(source_res)
        else:
            payload["source"] = source_res.resolved
        if target_res.candidates:
            payload["target_resolution"] = resolution_to_payload(target_res)
        else:
            payload["target"] = target_res.resolved
        return payload

    source_sid = source_res.resolved
    target_sid = target_res.resolved
    assert source_sid is not None and target_sid is not None

    # ② 两端都是种子（D-24）；深度见 :data:`_TRACE_SEED_DEPTH`。
    graph = await fetch_graph_for_tool(
        repository_id,
        graph_branch or "",
        user=user,
        seed_symbol_ids=[source_sid, target_sid],
        depth=_TRACE_SEED_DEPTH,
        include_low_confidence=include_low_confidence,
    )

    # ③ 内核（本文件内唯一调用点）。
    traced = trace_path(
        graph.graph,
        source_sid,
        target_sid,
        min_confidence=min_confidence,
        alt_path_cap=alt_path_cap,
    )

    graph_payload = degradation_payload(graph.meta)
    # ⑤ 按需子图 + 无路径：追加补充声明，⛔ 不编造「确实无路径」的更强结论。
    if (
        str(graph.meta.degraded).startswith("on_demand_subgraph")
        and traced.get("found") is False
    ):
        graph_payload = {
            **graph_payload,
            "declarations": [
                *list(graph_payload["declarations"]),
                _SUBGRAPH_NO_PATH_DECLARATION,
            ],
        }

    return {
        "ok": True,
        "tool": "trace_call_path",
        "repository_id": str(repository_id),
        "branch": _branch_label(repo, graph_branch),
        "query": {
            "min_confidence": min_confidence,
            "include_low_confidence": include_low_confidence,
            "alt_path_cap": alt_path_cap,
        },
        **traced,
        "staleness": await staleness_payload(repo),
        "graph": graph_payload,
    }


async def run_detect_changes(
    *,
    repository_id: str,
    repo: Any,
    user: Any,
    compare: str,
    base_ref: str | None = None,
    max_depth: int = DEFAULT_MAX_DEPTH,
    min_confidence: float = 1.0,
    include_low_confidence: bool = False,
    limit: int = DEFAULT_RESULT_LIMIT,
) -> dict[str, Any]:
    """变更检测的**唯一**编排入口——MCP / 对话两面只调这一个函数（D-13）。

    流程：ACL → 校验索引水位 → pin base（``last_indexed_commit_sha``）→ 解析 head
    → ``diff_mirror`` → ORM Symbol（``branch_name=""``）→ exclusion → 纯交叠内核
    → 阈值闸 → 顺序 ``run_impact`` → 122 同形信封。

    ``base_ref`` **只声明透出**，绝不参与 diff 左端（D-02 / T-123-BASE）。

    当 ``compare`` 解析后的 head sha 与 base（索引水位）相同时，返回
    ``ok=False, error_code="empty_diff_range"``——⛔ 不静默假装「无改动且可信」
    （Pitfall 6）。

    :param user: 必填；ACL 与 batch impact 权限复核同源。
    :param repo: 已取好的 ``Repository``，供 staleness / 索引水位读取。
    :raises GraphAccessDenied: ACL 失败原样上抛（壳层翻译；⛔ 不折成空清单）。
    """
    # 延迟导入：内核 / mirror 不在模块顶层，避免 services 早期加载与测试 patch 点漂移。
    from services.code_graph.detect_changes import (
        DETECT_CHANGES_MAX_SYMBOLS_FOR_IMPACT,
        SymbolRecord,
        detect_affected_symbols,
        parse_unified_diff,
    )
    from services.repo_mirror import (
        MirrorError,
        diff_mirror,
        ensure_mirror_commit,
        ensure_mirror_sha,
    )

    started = time.perf_counter()
    repository_id = str(repository_id)
    try:
        logger.info(
            _EVENT_DETECT_CHANGES_STARTED,
            component="code_graph",
            category="caller",
            repository_id=repository_id,
        )
    except Exception:  # noqa: BLE001 — 观测永不反噬
        pass

    def _duration_ms() -> float:
        return round((time.perf_counter() - started) * 1000, 2)

    def _log_failed(error_code: str, error: str) -> None:
        try:
            logger.info(
                _EVENT_DETECT_CHANGES_FAILED,
                component="code_graph",
                category="caller",
                repository_id=repository_id,
                error_code=error_code,
                error=redact_secrets_in_text(error)[:500],
                duration_ms=_duration_ms(),
            )
        except Exception:  # noqa: BLE001
            pass

    def _log_completed(**fields: Any) -> None:
        try:
            logger.info(
                _EVENT_DETECT_CHANGES_COMPLETED,
                component="code_graph",
                category="caller",
                repository_id=repository_id,
                duration_ms=_duration_ms(),
                **fields,
            )
        except Exception:  # noqa: BLE001
            pass

    # ① ACL 必须在 mirror / ORM 之前（T-123-ACL）——失败上抛，不 catch。
    await _code_graph_access().ensure_repository_readable(user, repository_id)

    indexed_sha = str(getattr(repo, "last_indexed_commit_sha", None) or "").strip()
    if not indexed_sha:
        err = "仓库尚未建立索引，无法检测变更；请先完成索引后重试"
        _log_failed("repository_not_indexed", err)
        return {
            "ok": False,
            "error_code": "repository_not_indexed",
            "error": err,
            "tool": "detect_changes",
            "repository_id": repository_id,
        }

    # ② base 强制 pin 索引水位（D-01 / D-03）：按 sha 锚定，禁止分支 tip / 缓存回退。
    try:
        base = await ensure_mirror_sha(repository_id, indexed_sha.lower())
    except MirrorError as exc:
        _log_failed(exc.code, exc.detail)
        return {
            "ok": False,
            "error_code": exc.code,
            "error": exc.detail,
            "tool": "detect_changes",
            "repository_id": repository_id,
        }
    if base.commit_sha.lower() != indexed_sha.lower():
        err = "无法将 diff base 锚定到索引水位 commit"
        _log_failed("mirror_fetch_failed", err)
        return {
            "ok": False,
            "error_code": "mirror_fetch_failed",
            "error": err,
            "tool": "detect_changes",
            "repository_id": repository_id,
        }

    compare_s = (compare or "").strip()
    try:
        if _FULL_SHA_RE.match(compare_s):
            head = await ensure_mirror_sha(repository_id, compare_s.lower())
        else:
            head = await ensure_mirror_commit(repository_id, branch=compare_s)
    except MirrorError as exc:
        _log_failed(exc.code, exc.detail)
        out: dict[str, Any] = {
            "ok": False,
            "error_code": exc.code,
            "error": exc.detail,
            "tool": "detect_changes",
            "repository_id": repository_id,
            "diff_base_sha": base.commit_sha,
        }
        if base_ref:
            out["base_ref"] = base_ref
        return out

    if head.commit_sha == base.commit_sha:
        err = "compare 与索引水位相同，无可信变更区间可分析"
        _log_failed("empty_diff_range", err)
        out = {
            "ok": False,
            "error_code": "empty_diff_range",
            "error": err,
            "tool": "detect_changes",
            "repository_id": repository_id,
            "diff_base_sha": base.commit_sha,
            "diff_head_sha": head.commit_sha,
        }
        if base_ref:
            out["base_ref"] = base_ref
        return out

    # ③ tree-to-tree diff；MirrorError 折信封（双面同形，D-03）。
    try:
        diff = await diff_mirror(base, head)
    except MirrorError as exc:
        _log_failed(exc.code, exc.detail)
        out = {
            "ok": False,
            "error_code": exc.code,
            "error": exc.detail,
            "tool": "detect_changes",
            "repository_id": repository_id,
            "diff_base_sha": base.commit_sha,
            "diff_head_sha": head.commit_sha,
        }
        if base_ref:
            out["base_ref"] = base_ref
        return out

    parsed = parse_unified_diff(diff.unified_diff)
    touched: set[str] = set()
    for fc in parsed:
        if fc.old_path:
            touched.add(fc.old_path)
        if fc.new_path:
            touched.add(fc.new_path)

    # ④ exclusion 后再交叠（T-123-EXCL / GRAPH-04 fail-closed）。
    matcher = await _exclusion_matcher_for_repo(repository_id)
    allowed_paths = sorted(p for p in touched if not matcher.is_excluded(p))

    from codegraph.models import Symbol

    symbols_by_path: dict[str, list[SymbolRecord]] = {}
    if allowed_paths:
        rows = [
            row
            async for row in Symbol.objects.filter(
                repository_id=repository_id,
                branch_name="",
                file_path__in=allowed_paths,
            ).values_list(
                "id",
                "name",
                "symbol_type",
                "file_path",
                "start_line",
                "end_line",
            )
        ]
        for uid, name, stype, fpath, start, end in rows:
            path = str(fpath or "")
            if matcher.is_excluded(path):
                continue
            symbols_by_path.setdefault(path, []).append(
                SymbolRecord(
                    uid=str(uid),
                    name=str(name or ""),
                    symbol_type=str(stype or ""),
                    file_path=path,
                    start_line=int(start or 0),
                    end_line=int(end or 0),
                )
            )

    overlap = detect_affected_symbols(
        parsed_diff=parsed,
        symbols_by_path=symbols_by_path,
    )
    files = list(overlap.get("files") or [])
    # 再滤一遍文件组：排除路径不得出现在输出（T-123-EXCL）。
    files = [f for f in files if not matcher.is_excluded(str(f.get("path") or ""))]

    seed_ids: list[str] = []
    for group in files:
        for sym in group.get("symbols") or []:
            if not isinstance(sym, Mapping):
                continue
            if sym.get("impact_seed") and sym.get("changeType") != "formatting_only":
                uid = str(sym.get("uid") or "")
                if uid:
                    seed_ids.append(uid)

    affected_symbol_count = sum(
        len(g.get("symbols") or []) for g in files if isinstance(g, Mapping)
    )
    impact_seed_count = len(seed_ids)
    truncated = impact_seed_count > DETECT_CHANGES_MAX_SYMBOLS_FOR_IMPACT
    not_expanded = truncated

    async def _graph_payload_for(seed: str | None) -> dict[str, Any]:
        """截断 / 成功路径都要有数值 resolution_rate（D-14 / A5）。"""
        if not seed:
            # 无种子：轻量占位，仍带数值 resolution_rate，声明未展开。
            return {
                "resolution_rate": 0.0,
                "low_resolution": False,
                "partial_edges": False,
                "partial_reason": "",
                "degraded": "not_expanded" if not_expanded else "",
                "cross_repo_unresolved_count": 0,
                "cross_repo_branch_unfiltered": False,
                "include_low_confidence": include_low_confidence,
                "node_count": 0,
                "edge_count": 0,
                "excluded_file_count": 0,
                "declarations": [
                    "本次未取图或无可作种子的受影响符号；结论按更保守口径采信"
                ],
            }
        try:
            graph = await fetch_graph_for_tool(
                repository_id,
                "",  # base 图坐标（graph_branch=None）
                user=user,
                seed_symbol_ids=[seed],
                depth=1,
                include_low_confidence=include_low_confidence,
            )
            return degradation_payload(graph.meta)
        except GraphError:
            return {
                "resolution_rate": 0.0,
                "low_resolution": False,
                "partial_edges": False,
                "partial_reason": "",
                "degraded": "not_expanded" if not_expanded else "",
                "cross_repo_unresolved_count": 0,
                "cross_repo_branch_unfiltered": False,
                "include_low_confidence": include_low_confidence,
                "node_count": 0,
                "edge_count": 0,
                "excluded_file_count": 0,
                "declarations": ["取图失败；变更检测结论不含影响面展开"],
            }

    impacts: list[dict[str, Any]] = []
    graph_payload: dict[str, Any]

    if truncated:
        # D-08 / T-123-DOS：零次 run_impact；仍填 graph（A5）。
        any_uid = seed_ids[0] if seed_ids else None
        if any_uid is None:
            for group in files:
                for sym in group.get("symbols") or []:
                    if isinstance(sym, Mapping) and sym.get("uid"):
                        any_uid = str(sym["uid"])
                        break
                if any_uid:
                    break
        graph_payload = await _graph_payload_for(any_uid)
        impacts = []
        # D-08：阈值后改文件级摘要，清空 per-symbol 清单（计数保留在 summary）。
        files = [
            {**dict(g), "symbols": []} if isinstance(g, Mapping) else g for g in files
        ]
    else:
        # D-09/D-10/D-11：顺序 for-loop，默认参数与 impact_analysis 一致。
        graph_payload = {}
        for sid in seed_ids:
            try:
                one = await run_impact(
                    repository_id=repository_id,
                    repo=repo,
                    graph_branch=None,
                    user=user,
                    symbol_id=sid,
                    max_depth=max_depth,
                    min_confidence=min_confidence,
                    include_low_confidence=include_low_confidence,
                    limit=limit,
                )
                impacts.append({"symbol_id": sid, "impact": one})
                if not graph_payload and isinstance(one.get("graph"), Mapping):
                    graph_payload = dict(one["graph"])
            except GraphError as exc:
                code, msg = graph_error_to_tool_error(exc)
                impacts.append(
                    {
                        "symbol_id": sid,
                        "impact_error": code,
                        "unavailable_reason": msg,
                    }
                )
        if not graph_payload:
            graph_payload = await _graph_payload_for(seed_ids[0] if seed_ids else None)

    staleness = await staleness_payload(repo)
    # D-04：behind 大时加强 declaration，不硬拒。
    behind = staleness.get("behind_commits")
    if isinstance(behind, int) and behind >= 20:
        decl = str(staleness.get("declaration") or "")
        extra = f"；索引明显落后（{behind} commits），变更交叠相对旧水位"
        if extra.strip("；") not in decl:
            staleness = {**staleness, "declaration": decl + extra}

    summary = {
        "affected_symbol_count": affected_symbol_count,
        "impact_seed_count": impact_seed_count,
        "truncated": truncated,
        "not_expanded": not_expanded,
        "file_count": len(files),
        "file_level_only": truncated,
    }

    result: dict[str, Any] = {
        "ok": True,
        "tool": "detect_changes",
        "repository_id": repository_id,
        "diff_base_sha": diff.base_sha,
        "diff_head_sha": diff.head_sha,
        "files": files,
        "impacts": impacts,
        "summary": summary,
        "affected_processes": [],
        "staleness": staleness,
        "graph": graph_payload,
    }
    if base_ref:
        result["base_ref"] = base_ref

    _log_completed(
        affected_symbol_count=affected_symbol_count,
        impact_seed_count=impact_seed_count,
        truncated=truncated,
        impacts_ok=sum(1 for i in impacts if "impact" in i),
        impacts_failed=sum(1 for i in impacts if "impact_error" in i),
    )
    return result


# ---------------------------------------------------------------------------
# 两面共用的壳层原语（122-08）——分支口径与留痕 payload
# ---------------------------------------------------------------------------

# 这些键名刻意放在函数体外：``tool_trace_payload`` 的 AST 守卫禁止函数体内出现
# ``groups`` / ``hops`` / ``items`` 等字符串常量（那会把正文键带进留痕面）。
_TRACE_KEY_GROUPS: Final[str] = "groups"
_TRACE_KEY_HOPS: Final[str] = "hops"
_TRACE_KEY_CROSS_REPO: Final[str] = "cross_repo"
_TRACE_KEY_FILES: Final[str] = "files"
_TRACE_KEY_IMPACTS: Final[str] = "impacts"
_TRACE_SUMMARY_AFFECTED: Final[str] = "affected_symbol_count"
_TRACE_SUMMARY_SEEDS: Final[str] = "impact_seed_count"
_TRACE_SUMMARY_TRUNCATED: Final[str] = "truncated"
_CONF_DIST_KEYS: Final[tuple[str, ...]] = (
    "resolved",
    "bare_name",
    "cross_repo",
    "other",
)


async def resolve_tool_graph_branch(
    repository_id: str,
    repo: Any,
    branch: str | None,
) -> str | None:
    """两面共用的图分支解析——返回 ``None`` 表示 base 分支。

    口径与 MCP ``McpToolView._resolve_graph_branch`` 的分支段一致，但**不**返回
    Qdrant ``collection_name``（本相位不需要）。两个壳必须调同一个本函数：分支口径
    一旦分叉，两面就会在不同的图上跑出不同的 ``data``，而 ``test_two_surfaces_same_payload``
    （122-10）只覆盖被测的那一组输入，抓不住所有漂移。

    返回 ``None`` 时，传给 ``get_graph`` / ``run_impact`` / ``run_trace`` 由编排层内部
    转成 ``""``（base）。⛔ 不要改 ``McpToolView._resolve_graph_branch``——40+ 既有
    工具仍走那条含 collection 的路径。
    """
    from services.branch_utils import resolve_branch_for_query

    effective_branch, _branch_index = await resolve_branch_for_query(
        repository_id, branch or None
    )
    base_branch = repo.base_branch or repo.default_branch
    if not effective_branch or effective_branch == base_branch:
        return None
    return effective_branch


def tool_trace_payload(
    result: dict[str, Any],
    *,
    tool: str,
    duration_ms: int,
    orchestration_ms: int,
) -> dict[str, Any]:
    """从编排信封萃取**计数与分布**，产出一条汇总留痕 payload。

    ⛔ 不得出现符号名、路径、源码正文、候选列表、任何 item 正文——只出计数、
    分档分布与耗时（Pitfall 8 + T-122-日志放大 + T-122-exclusion 回流）。

    更细的分层耗时不在这里造：内核的 ``sampling`` 事件
    （``code_graph_impact_analyzed`` / ``code_graph_tool_graph_fetched``）各自带
    ``duration_ms``，按 ``request_id`` / ``run_id`` 关联查——这是 LOGGING-SPEC
    「指标与留痕分离、用关联键串起来」的既定分工，⛔ 不在留痕里复制一份。
    """
    ok = bool(result.get("ok"))
    error_code = str(result.get("error_code") or "") if not ok else ""
    summary = result.get("summary") if isinstance(result.get("summary"), Mapping) else {}
    graph = result.get("graph") if isinstance(result.get("graph"), Mapping) else {}

    conf_dist = {k: 0 for k in _CONF_DIST_KEYS}
    path_conf_max = 0.0
    result_count = 0
    total_found = 0
    risk_level = ""
    cross_repo_entry_count = 0
    files_touched = 0
    impacts_ok = 0
    impacts_failed = 0
    truncated_flag = 0

    if tool == "impact_analysis":
        result_count = int(summary.get("returned") or 0) if summary else 0
        total_found = int(summary.get("total_found") or 0) if summary else 0
        risk_level = str(result.get("risk_level") or "")
        groups = result.get(_TRACE_KEY_GROUPS)
        if isinstance(groups, Mapping):
            for depth_rows in groups.values():
                if not isinstance(depth_rows, Sequence) or isinstance(depth_rows, (str, bytes)):
                    continue
                for row in depth_rows:
                    if not isinstance(row, Mapping):
                        continue
                    via = row.get("via")
                    conf = ""
                    if isinstance(via, Mapping):
                        conf = str(via.get("confidence") or "")
                    if conf in conf_dist:
                        conf_dist[conf] += 1
                    else:
                        conf_dist["other"] += 1
                    try:
                        pc = float(row.get("path_confidence") or 0.0)
                    except (TypeError, ValueError):
                        pc = 0.0
                    if pc > path_conf_max:
                        path_conf_max = pc
        cross = result.get(_TRACE_KEY_CROSS_REPO)
        if isinstance(cross, Sequence) and not isinstance(cross, (str, bytes)):
            cross_repo_entry_count = len(cross)
        elif isinstance(cross, Mapping):
            # 编排成功态 ``cross_repo`` 是 list；兼容 mapping 包装时取 entries 长度
            entries = cross.get("entries")
            if isinstance(entries, Sequence) and not isinstance(entries, (str, bytes)):
                cross_repo_entry_count = len(entries)
    elif tool == "detect_changes":
        # 只计数（T-123-TRACE）：符号数 / 种子数 / 文件数 / impact 成败 / 截断。
        # ⛔ 不读 files[*].path、符号名、diff 正文进 payload。
        result_count = int(summary.get(_TRACE_SUMMARY_AFFECTED) or 0) if summary else 0
        total_found = int(summary.get(_TRACE_SUMMARY_SEEDS) or 0) if summary else 0
        truncated_flag = (
            1 if summary and bool(summary.get(_TRACE_SUMMARY_TRUNCATED)) else 0
        )
        files = result.get(_TRACE_KEY_FILES)
        if isinstance(files, Sequence) and not isinstance(files, (str, bytes)):
            files_touched = len(files)
            if result_count == 0:
                # summary 缺失时回退：只累加每组 symbols 长度，不读正文键。
                for group in files:
                    if not isinstance(group, Mapping):
                        continue
                    syms = group.get("symbols")
                    if isinstance(syms, Sequence) and not isinstance(syms, (str, bytes)):
                        result_count += len(syms)
        impacts = result.get(_TRACE_KEY_IMPACTS)
        if isinstance(impacts, Sequence) and not isinstance(impacts, (str, bytes)):
            for row in impacts:
                if not isinstance(row, Mapping):
                    continue
                if "impact_error" in row:
                    impacts_failed += 1
                elif "impact" in row:
                    impacts_ok += 1
        # confidence / risk 对本工具无意义，保持零值与空串。
        risk_level = ""
        cross_repo_entry_count = 0
    else:
        hops = result.get(_TRACE_KEY_HOPS)
        if isinstance(hops, Sequence) and not isinstance(hops, (str, bytes)):
            result_count = len(hops)
            for hop in hops:
                if not isinstance(hop, Mapping):
                    continue
                conf = str(hop.get("confidence") or "")
                if conf in conf_dist:
                    conf_dist[conf] += 1
                else:
                    conf_dist["other"] += 1
        try:
            path_conf_max = float(result.get("path_confidence") or 0.0)
        except (TypeError, ValueError):
            path_conf_max = 0.0

    shell_ms = max(duration_ms - orchestration_ms, 0)
    payload: dict[str, Any] = {
        "source": tool,
        "ok": ok,
        "error_code": error_code,
        "repository_id": str(result.get("repository_id") or ""),
        "branch": str(result.get("branch") or ""),
        "result_count": result_count,
        "total_found": total_found,
        "confidence_distribution": conf_dist,
        "path_confidence_max": path_conf_max,
        "risk_level": risk_level,
        "cross_repo_entry_count": cross_repo_entry_count,
        "degraded": graph.get("degraded") if graph else "",
        "resolution_rate": float(graph.get("resolution_rate") or 0.0) if graph else 0.0,
        "duration_ms": duration_ms,
        "layer_durations_ms": {
            "orchestration": orchestration_ms,
            "shell": shell_ms,
        },
    }
    if tool == "detect_changes":
        payload["files_touched"] = files_touched
        payload["impacts_ok"] = impacts_ok
        payload["impacts_failed"] = impacts_failed
        payload["truncated"] = truncated_flag
    return payload
