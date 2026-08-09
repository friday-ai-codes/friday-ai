"""跨仓 impact 一跳：``CrossRepoApiCall`` ORM 直查 + 对端仓 ``get_graph``（Phase 122，IMPACT-03）。

为什么不能沿图边穿仓（D-25）
==========================
图里 ``kind == "cross_repo"`` 的边**从来不跨仓**。``loader._load_cross_repo_edges``
只在 ``call_site.repository_id`` **与** ``endpoint.repository_id`` **同时等于本仓**时才
``add_edge``；凡有一端在别的仓库的行一律 ``unresolved_count += 1; continue``——真跨仓
的行 100% 落在 ``cross_repo_unresolved_count`` 里、永不入图。因此跨仓 impact **必须**
走一次 ``CrossRepoApiCall`` ORM 直查，再对每个对端仓走一次 ``fetch_graph_for_tool``
（内部 ``get_graph`` 每次都跑 ``ensure_repository_readable``）。

⛔ **不许改 ``loader.py`` 的建边口径来「顺手修好」**。那是 Phase 121 已验证的冻结行为；
本模块存在的全部理由就是接受那条事实并在壳层组合。

装什么
======
- :data:`DEFAULT_MAX_CROSS_REPO_HOPS` —— 跨仓跳数上限，默认 1（D-11：改后端
  ``Endpoint`` → 列出前端调用点，正是一跳；多跳会把尚未验证命中率的
  ``(file_path, name)`` 二次解析误差累乘）。
- :func:`collect_cross_repo_impact` —— 公开入口：ORM 分组 → 逐仓权限复核 → 三种显式
  条目（成功 / ``REDACTED_REPOSITORY`` 折叠 / ``unavailable_reason``）。
- 私有 :func:`_find_peer_call_sites` —— 只查**真跨仓**行并按对端仓分组。

边界与已知翻车点
================
① **生产零样本（D-26）**：生产库 ``CrossRepoApiCall`` / ``ApiCallSite`` /
   ``ApiWrapper`` 均为 0 行（``Endpoint`` 6,014）。上游产出器依赖 volar LSP 而
   server 镜像无 Node（LSP-01 / Phase 127）。本模块的四条分支全部由合成数据覆盖；
   ⛔ 不得表述成「跨仓 impact 已上线可用」。``(file_path, name)`` 二次解析的真实命中率
   在 Phase 127 之前根本不可测。

② **折叠条目只有两键（D-30 / T-122-折叠泄漏）**：无权限对端仓折叠为
   ``{"cross_repo": True, "repository": REDACTED_REPOSITORY}``——⛔ 不带
   ``repository_id``、⛔ 不带 ``affected_count``、⛔ 不带仓名/路径/符号。计数是存在性
   预言机，会泄漏一个调用方无权访问的仓库的内部规模。折叠携带的信息止于
   「这里有一个你无权看的仓库」。

③ **fail-soft 但必须显式声明（D-14）**：对端 ``GraphNotIndexed`` /
   ``GraphBuildTimeout`` 等产出带 ``unavailable_reason`` 的条目，本仓结果照常返回。
   ⛔ 不静默 ``continue``（那是 ``SearchRagChunksView`` 的做法，本相位必须在此分叉）。

④ **``match_confidence`` 原值透传（D-13）**：跨仓边的可信度来源与本仓完全不同，
   ⛔ 不归一化到 ``1.0`` / ``0.3`` 之类的本仓档位常量。

⑤ **观测契约**：本文件是包外兄弟模块，必须挂进
   ``test_access._SIBLING_GUARDED_MODULES``。事件名模块级 ``Final[str]``，异常文本过
   ``redact_secrets_in_text(str(exc))[:500]``；``_log_cross_repo_peer_redacted``
   **不记**对端 ``repository_id``。
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Final

import structlog

from common.logging import redact_secrets_in_text
from services.code_graph import (
    REDACTED_REPOSITORY,
    GraphAccessDenied,
    GraphBuildFailed,
    GraphBuildTimeout,
    GraphError,
    GraphNotIndexed,
)
from services.code_graph.impact import analyze_impact
from services.code_graph_tools import (
    fetch_graph_for_tool,
    graph_error_to_tool_error,
    resolve_symbol_candidates,
)

logger = structlog.get_logger(__name__)

# D-11：改后端 Endpoint → 列出前端调用点，正是一跳。多跳会把尚未验证命中率的
# ``(file_path, name)`` 二次解析误差累乘——生产 CrossRepoApiCall 样本为零（D-26）。
DEFAULT_MAX_CROSS_REPO_HOPS: Final[int] = 1

# 事件名常量（形态对齐 ``code_graph_tools.py`` / 包内 ``cache.py``）。
# ⚠️ 前缀不得缩写：``code_graph_`` 是观测契约的强制前缀，扫描面已含本文件。
_EVENT_CROSS_REPO_HOP: Final[str] = "code_graph_cross_repo_hop_completed"
_EVENT_CROSS_REPO_REDACTED: Final[str] = "code_graph_cross_repo_peer_redacted"
_EVENT_CROSS_REPO_UNAVAILABLE: Final[str] = "code_graph_cross_repo_peer_unavailable"

__all__ = [
    "DEFAULT_MAX_CROSS_REPO_HOPS",
    "collect_cross_repo_impact",
]


@dataclass(slots=True)
class _PeerHits:
    """一个对端仓上、指向本仓某 Endpoint 的全部调用点。"""

    call_sites: list[dict[str, Any]] = field(default_factory=list)
    max_match_confidence: float = 0.0


async def _find_peer_call_sites(
    *,
    local_repository_id: str,
    symbol_file_path: str,
    symbol_name: str,
) -> dict[str, _PeerHits]:
    """查本仓 Endpoint 被**别的仓**调用的 ``CrossRepoApiCall`` 行，按对端仓分组。

    方向与 ``agents/tools/find_api_callers.py`` 一致：后端 handler → 前端调用点。
    三点必须补上它没做的：按对端仓分组、``.exclude`` 同仓行、后续由调用方做权限复核。

    ``.exclude(call_site__repository_id=local_repository_id)`` 是 D-25 的核心——只要
    **真跨仓**的行；同仓行已经在图里（两端同仓时 loader 才会建 ``cross_repo`` 边），
    重复计入会让同一条影响被数两遍。

    ``match_confidence`` **原值透传**（D-13）：⛔ 不归一化到本仓档位数值。
    """
    # ORM 模型一律函数体内 lazy import（与 ``code_graph_tools.py`` / conftest 同款约定）。
    from codegraph.models import CrossRepoApiCall

    local_id = str(local_repository_id)
    grouped: dict[str, _PeerHits] = {}

    rows = (
        CrossRepoApiCall.objects.filter(
            endpoint__repository_id=local_id,
            endpoint__file_path=symbol_file_path,
            endpoint__handler_name=symbol_name,
        )
        .exclude(call_site__repository_id=local_id)
        .values_list(
            "call_site__repository_id",
            "call_site__caller_file",
            "call_site__caller_function",
            "call_site__line_number",
            "match_confidence",
        )
    )

    async for (
        peer_repo_id,
        caller_file,
        caller_function,
        line_number,
        match_confidence,
    ) in rows:
        peer_key = str(peer_repo_id)
        hits = grouped.get(peer_key)
        if hits is None:
            hits = _PeerHits()
            grouped[peer_key] = hits
        conf = float(match_confidence)
        hits.call_sites.append(
            {
                "caller_file": caller_file,
                "caller_function": caller_function,
                "line_number": line_number,
                "match_confidence": conf,
            }
        )
        if conf > hits.max_match_confidence:
            hits.max_match_confidence = conf

    for hits in grouped.values():
        hits.call_sites.sort(
            key=lambda site: (site["caller_file"], site["line_number"])
        )

    return grouped


def _merge_impact_payloads(impacts: list[dict[str, Any]]) -> dict[str, Any]:
    """合并多个种子上的 ``analyze_impact`` 结果，只保留 ``groups`` / ``summary``。"""
    if not impacts:
        return {
            "groups": {},
            "summary": {
                "total_found": 0,
                "returned": 0,
                "truncated_by_depth": {},
                "truncated_by_nodes": False,
                "result_limit": 0,
            },
        }
    if len(impacts) == 1:
        return {
            "groups": impacts[0]["groups"],
            "summary": impacts[0]["summary"],
        }

    items: list[dict[str, Any]] = []
    seen: set[str] = set()
    truncated_by_nodes = False
    max_depth = 0
    result_limit = int(impacts[0]["summary"].get("result_limit", 0))
    for impact in impacts:
        max_depth = max(max_depth, int(impact.get("max_depth") or 0))
        truncated_by_nodes = truncated_by_nodes or bool(
            impact["summary"].get("truncated_by_nodes")
        )
        for item in impact["items"]:
            sid = item["symbol_id"]
            if sid in seen:
                continue
            seen.add(sid)
            items.append(item)

    groups = {
        depth: [item for item in items if item["depth"] == depth]
        for depth in range(1, max_depth + 1)
    }
    return {
        "groups": groups,
        "summary": {
            "total_found": len(items),
            "returned": len(items),
            "truncated_by_depth": {depth: 0 for depth in range(1, max_depth + 1)},
            "truncated_by_nodes": truncated_by_nodes,
            "result_limit": result_limit,
        },
    }


def _log_cross_repo_hop(
    *,
    local_repository_id: str,
    peer_repository_id: str,
    call_site_count: int,
    unresolved_call_sites: int,
    duration_ms: float,
) -> None:
    """一次对端仓 hop 成功的结构化埋点。每个对端仓至多一条（T-122-日志放大）。"""
    try:
        logger.debug(
            _EVENT_CROSS_REPO_HOP,
            component="code_graph",
            category="sampling",
            local_repository_id=local_repository_id,
            peer_repository_id=peer_repository_id,
            call_site_count=call_site_count,
            unresolved_call_sites=unresolved_call_sites,
            duration_ms=duration_ms,
        )
    except Exception:  # noqa: BLE001 — 观测失败绝不反噬业务
        pass


def _log_cross_repo_peer_redacted(
    *, local_repository_id: str, redacted_count: int
) -> None:
    """无权限对端仓折叠埋点。

    🚨 **不得**记对端 ``repository_id``——那正是折叠要藏的东西（T-122-折叠泄漏）。
    只记本仓 id 与本轮累计折叠数。
    """
    try:
        logger.info(
            _EVENT_CROSS_REPO_REDACTED,
            component="code_graph",
            category="sampling",
            local_repository_id=local_repository_id,
            redacted_count=redacted_count,
        )
    except Exception:  # noqa: BLE001 — 观测失败绝不反噬业务
        pass


def _log_cross_repo_peer_unavailable(
    *,
    local_repository_id: str,
    peer_repository_id: str,
    unavailable_reason: str,
    exc: BaseException,
) -> None:
    """对端仓不可用（未索引 / 超时 / 构建失败）的结构化埋点。"""
    try:
        logger.info(
            _EVENT_CROSS_REPO_UNAVAILABLE,
            component="code_graph",
            category="sampling",
            local_repository_id=local_repository_id,
            peer_repository_id=peer_repository_id,
            unavailable_reason=unavailable_reason,
            error=redact_secrets_in_text(str(exc))[:500],
        )
    except Exception:  # noqa: BLE001 — 观测失败绝不反噬业务
        pass


async def collect_cross_repo_impact(
    *,
    local_repository_id: str,
    symbol_file_path: str,
    symbol_name: str,
    user: Any,
    max_hops: int = DEFAULT_MAX_CROSS_REPO_HOPS,
    max_depth: int,
    min_confidence: float,
    include_low_confidence: bool = False,
) -> list[dict[str, Any]]:
    """对本仓一个 Endpoint 符号做跨仓一跳 impact（D-11 / D-12 / D-14 / D-25）。

    ``max_hops`` 的语义是**一跳，不递归**：对端仓的 impact 结果里**不会**再触发第二轮
    穿仓——函数体内没有对自身的调用。``max_hops <= 0`` 时直接返回 ``[]``（不查库、
    不取图）。

    条目排序：成功（按 ``repository_id``）→ unavailable（按 ``repository_id``）→
    redacted（按出现顺序，无标识符可排）。
    """
    if max_hops <= 0:
        return []

    local_id = str(local_repository_id)
    grouped = await _find_peer_call_sites(
        local_repository_id=local_id,
        symbol_file_path=symbol_file_path,
        symbol_name=symbol_name,
    )

    success_entries: list[dict[str, Any]] = []
    unavailable_entries: list[dict[str, Any]] = []
    redacted_entries: list[dict[str, Any]] = []
    redacted_count = 0

    # access 经 importlib：包外兄弟不得 ``from services.code_graph.access import …``。
    import importlib

    access = importlib.import_module("services.code_graph.access")

    for peer_repo_id, hits in grouped.items():
        started = time.perf_counter()

        # HI-01：权限复核必须在 ORM 解析对端 Symbol **之前**。
        # denied 路径不得触碰 peer Symbol（含 signature）。
        try:
            await access.ensure_repository_readable(user, peer_repo_id)
        except GraphAccessDenied:
            # D-30：折叠条目**只有**这两个键。⛔ 不带 repository_id / affected_count /
            # 仓名 / 路径 / 符号——计数是存在性预言机，会泄漏一个调用方无权访问的仓库
            # 的内部规模。折叠携带的信息止于「这里有一个你无权看的仓库」。
            redacted_count += 1
            redacted_entries.append(
                {"cross_repo": True, "repository": REDACTED_REPOSITORY}
            )
            _log_cross_repo_peer_redacted(
                local_repository_id=local_id, redacted_count=redacted_count
            )
            continue
        except GraphNotIndexed as exc:
            # D-14 fail-soft：未索引对端在取图前就能判定，不必再碰 Symbol / get_graph。
            reason, _message = graph_error_to_tool_error(exc)
            unavailable_entries.append(
                {
                    "cross_repo": True,
                    "repository_id": peer_repo_id,
                    "unavailable_reason": reason,
                }
            )
            _log_cross_repo_peer_unavailable(
                local_repository_id=local_id,
                peer_repository_id=peer_repo_id,
                unavailable_reason=reason,
                exc=exc,
            )
            continue

        seed_ids: list[str] = []
        unresolved = 0
        for site in hits.call_sites:
            resolution = await resolve_symbol_candidates(
                repository_id=peer_repo_id,
                branch_names=[""],
                name=site["caller_function"],
                file_path=site["caller_file"],
            )
            if resolution.resolved is not None:
                seed_ids.append(resolution.resolved)
            else:
                # 落空或歧义一律计数不丢；⛔ 绝不静默取第一条（D-19 / Phase 121 D-05）。
                unresolved += 1

        try:
            # D-12：get_graph 仍会再跑一遍 ensure_repository_readable（缓存命中也不跳过）。
            peer_graph = await fetch_graph_for_tool(
                peer_repo_id,
                "",
                user=user,
                seed_symbol_ids=seed_ids,
                depth=max_depth,
                include_low_confidence=include_low_confidence,
            )
        except GraphAccessDenied:
            # 竞态：ensure 通过后权限被收回——仍按 D-30 折叠，不泄漏仓标识。
            redacted_count += 1
            redacted_entries.append(
                {"cross_repo": True, "repository": REDACTED_REPOSITORY}
            )
            _log_cross_repo_peer_redacted(
                local_repository_id=local_id, redacted_count=redacted_count
            )
            continue
        except (GraphNotIndexed, GraphBuildTimeout, GraphBuildFailed, GraphError) as exc:
            # D-14 fail-soft：该仓折叠为一条带原因的条目，本仓结果照常返回。
            # ⚠️ 此分支保留 repository_id 是安全的——ensure_repository_readable 已先跑过，
            # 能走到这里说明调用方对该仓有读权限，只是它没索引好。⛔ 不要「统一一下」
            # 把它也抹成 REDACTED。
            reason, _message = graph_error_to_tool_error(exc)
            unavailable_entries.append(
                {
                    "cross_repo": True,
                    "repository_id": peer_repo_id,
                    "unavailable_reason": reason,
                }
            )
            _log_cross_repo_peer_unavailable(
                local_repository_id=local_id,
                peer_repository_id=peer_repo_id,
                unavailable_reason=reason,
                exc=exc,
            )
            continue

        impacts = [
            analyze_impact(
                peer_graph.graph,
                seed_id,
                max_depth=max_depth,
                min_confidence=min_confidence,
                include_low_confidence=include_low_confidence,
                crosses_repo=True,
            )
            for seed_id in seed_ids
        ]
        success_entries.append(
            {
                "cross_repo": True,
                "repository_id": peer_repo_id,
                "match_confidence": hits.max_match_confidence,
                "call_sites": list(hits.call_sites),
                "unresolved_call_sites": unresolved,
                "impact": _merge_impact_payloads(impacts),
            }
        )
        _log_cross_repo_hop(
            local_repository_id=local_id,
            peer_repository_id=peer_repo_id,
            call_site_count=len(hits.call_sites),
            unresolved_call_sites=unresolved,
            duration_ms=round((time.perf_counter() - started) * 1000, 2),
        )

    success_entries.sort(key=lambda entry: entry["repository_id"])
    unavailable_entries.sort(key=lambda entry: entry["repository_id"])
    return success_entries + unavailable_entries + redacted_entries
