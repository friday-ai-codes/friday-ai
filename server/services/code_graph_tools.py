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

上半层（``run_impact`` / ``run_trace`` 两个唯一编排入口）由 122-07 追加到本文件。

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

import time
from collections.abc import Mapping, Sequence
from typing import Any, Final

import structlog

from services.code_graph import (
    CodeGraph,
    GraphAccessDenied,
    GraphBuildFailed,
    GraphBuildTimeout,
    GraphError,
    GraphNotIndexed,
    get_graph_service,
)

logger = structlog.get_logger(__name__)

# 事件名常量（形态对齐包内 ``cache.py`` / ``access.py``）。
# ⚠️ 前缀不得缩写：``code_graph_`` 是观测契约的强制前缀，扫描面已含本文件。
_EVENT_GRAPH_FETCHED: Final[str] = "code_graph_tool_graph_fetched"

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

__all__ = [
    "GRAPH_ERROR_MESSAGES",
    "fetch_graph_for_tool",
    "graph_error_to_tool_error",
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
