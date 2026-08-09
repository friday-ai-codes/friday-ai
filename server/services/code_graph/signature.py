"""内存图服务的**缓存有效性判据** —— 复合签名与 in-flight 边构建判定（Phase 121，GRAPH-02）。

问题背景
========
图对象缓存在 per-worker 进程内存里，命中与否只能靠一个廉价的判据来决定。本仓已有
一个可照抄的范式：``codegraph/galaxy/cache.py::GalaxyGraphCache.compute_signature``
——每张源表一条聚合、拼成带 ``label:`` 前缀的明文串、再取 sha256。

但 Galaxy 的签名只回答一个问题：**「数据变了吗」**。本服务必须额外回答第二个问题：
**「边建完了吗」**。GRAPH-02 的「绝不返回水位已推进但边还没建完的半新图」就落在
后半句上——只答前半句会让缓存在「索引刚完成、边构建正在跑」的窗口里返回一张
少了一半边的图，而上层 impact 工具会把「查不到调用方」直接读成「改这里没有影响」。

方案（同结构不同分量 + 一个独立的在途判定）
==========================================
:func:`compute_signature` —— 与 ``GalaxyGraphCache.compute_signature`` **同结构、
不同分量**：水位 ‖ 轨 A 代数 ‖ 轨 B 代数（含兜底）‖ 计数 ‖ exclusion 规则指纹。
分量顺序固定，每项带 ``label:`` 前缀（明文串可直接 print 出来排障，比对着一堆
sha256 猜哪个分量变了要省事得多）。

:func:`detect_edge_build_in_flight` —— 签名答不了的那半句。签名只能告诉调用方
「和上次不一样」，告诉不了「现在正在写」；后者要读状态机。

边界与已知翻车点
================
① **两条边构建轨互相独立，必须都纳入**（121-CONTEXT D-02）。见
   :func:`compute_signature` docstring 里的对照表。只看轨 A 会漏掉「Symbol/CallEdge
   被重新抽取但 ChunkEdge 没变」——而 ``CallEdge`` 恰恰是本相位图的**主边源**。

② **``IndexHistory.graph_build_status`` 的模型默认值就是 ``PENDING``**
   （121-CONTEXT D-03）。照字面把 ``PENDING`` 当在途，会让**从未触发过边构建**的
   仓库永久带 ``partial_edges: true``。降级标记一旦长鸣就等于没有——上层看见它
   永远为真，很快就会学会无视它。判据见 :func:`detect_edge_build_in_flight`。

③ **在途判定必须带超时兜底**：卡住的 RUNNING 孤儿行会让该仓每次查询都重建
   2–4 秒的大图。复用既有的 ``settings.GRAPH_BUILD_ORPHAN_TIMEOUT_MINUTES``，
   ⛔ 不新增配置项（两个阈值一旦漂移就会出现「孤儿已被回收但图服务仍判在途」）。

④ **全同步**：本模块的两个函数都跑在 ``cache.py`` 用 ``sync_to_async`` 一次性包裹的
   同步上下文里，不要在这里做 async ORM 调用（RESEARCH Pitfall 7：持锁 await 会
   把整个 worker 停摆）。
"""

from __future__ import annotations

import hashlib
from typing import Any, Final

import structlog
from django.utils import timezone

logger = structlog.get_logger(__name__)

# 事件名常量（形态对齐 ``access.py`` / ``codegraph/lsp/volar_pool.py``）。
# ⚠️ 前缀不得缩写：``graph_build_*`` 已被 ``services/graph_builder.py`` 占用。
_EVENT_SIGNATURE_COMPUTED: Final[str] = "code_graph_signature_computed"

# 无 history 行时的占位分量长度（与各自 ``values_list`` 的字段数严格一致）。
# 长度一致才能保证「无行」与「有行但字段全为空」不会碰撞成同一个分量串；
# 而两者绝不会互相冒充，因为真实行的第一项是 ``id``（UUID），永远不是 ``"-"``。
_TRACK_A_FIELDS: Final[int] = 6
_TRACK_B_FIELDS: Final[int] = 5

__all__ = [
    "compute_signature",
]


def _emit(event: str, **fields: Any) -> None:
    """DEBUG 级埋点。观测 best-effort —— 任何异常吞掉，绝不反噬取图主流程。

    取 DEBUG 而非 INFO：这两个函数在**每次** ``get_graph`` 都会跑（含缓存命中的
    那些），INFO 会直接违反 ``.cursor/rules/observability-logging.mdc`` 的级别纪律。
    """
    try:
        logger.debug(event, component="code_graph", category="sampling", **fields)
    except Exception:  # noqa: BLE001 — 观测失败绝不反噬业务（不是安全降级分支）
        pass


def _watermark_part(repository_id: str, branch: str) -> str:
    """① 水位分量 ``wm:`` —— 索引推进到哪个 commit。

    🚨 **分支键翻译**（RESEARCH Pitfall 6）：``RepositoryBranchIndex.branch_name``
    存的是**真实分支名**，base 分支由 ``is_base_branch=True`` 标识（写入方见
    ``services/indexer.py::_update_branch_index_record``），**从不是空串**；而缓存键
    与 ``Symbol``/``CallEdge`` 那套用 ``""`` 表示 base。两套语义不可混用。

    ⛔ 绝不能拿 ``branch_name=""`` 去查 ``RepositoryBranchIndex`` —— 那永远查不到，
    本分量会静默退化成「永远走 ``Repository`` 回落」，分支级水位形同虚设。
    """
    from repositories.models import Repository, RepositoryBranchIndex

    qs = RepositoryBranchIndex.objects.filter(repository_id=repository_id)
    qs = qs.filter(is_base_branch=True) if not branch else qs.filter(branch_name=branch)
    row = qs.values_list("last_indexed_commit_sha", "last_indexed_at").first()

    if row and row[0]:
        stamp = row[1].isoformat() if row[1] else "-"
        return f"wm:{row[0]}:{stamp}"

    # 回落：没有分支索引行（或行上没写 sha）的老仓走仓库级水位。
    repo_sha = (
        Repository.objects.filter(id=repository_id)
        .values_list("last_indexed_commit_sha", flat=True)
        .first()
    )
    return f"wm:{repo_sha or '-'}"


def _track_a_part(repository_id: str) -> str:
    """② 轨 A 代数 ``ihA:`` —— ChunkEdge 构建轨（``IndexHistory``）。

    依 ``IndexHistory.Meta.ordering = ["-created_at"]`` 取最近一条，纳入
    ``id`` / ``graph_build_status`` / ``status`` / ``finished_at`` /
    ``payload_synced_at`` / ``edge_count`` 六项：新一轮索引会换 ``id``，边构建推进
    会改 ``graph_build_status``，payload 回写会改 ``payload_synced_at``，边数变化
    会改 ``edge_count`` —— 任何一处动了都换签名。

    ⛔ **刻意不纳入 ``started_at``**：它是 in-flight 判定的专用判据
    （:func:`detect_edge_build_in_flight` 要求 ``started_at >= cutoff``）。把它拼进
    签名会让「同一轮构建的在途/超时状态翻转」也变成一次缓存失效，两个判据就纠缠
    在一起了——签名答「数据变了吗」，在途判定答「现在正在写吗」，二者必须各管各的。
    """
    from repositories.models import IndexHistory

    row = (
        IndexHistory.objects.filter(repository_id=repository_id)
        .values_list(
            "id",
            "graph_build_status",
            "status",
            "finished_at",
            "payload_synced_at",
            "edge_count",
        )
        .first()
    )
    values = row if row else ("-",) * _TRACK_A_FIELDS
    return "ihA:" + ":".join(str(v) for v in values)


def _track_b_parts(repository_id: str, branch: str) -> list[str]:
    """③ 轨 B 代数 ``ghB:`` + 兜底 ``repoG:`` —— Symbol/CallEdge/Endpoint 抽取轨。

    依 ``GraphBuildHistory.Meta.ordering = ["-started_at"]`` 取该分支最近一条
    （``Index(["repository", "-started_at"])`` 覆盖，单行取值走索引）。
    ``GraphBuildHistory`` 比 ``Repository.graph_last_built_at`` 更好的地方在于它
    **按分支隔离**，且带 ``symbols_count`` / ``calls_count`` 两个产物计数。

    ``repoG:`` 兜底**无条件追加**：没有任何 history 行的老仓（``GraphBuildHistory``
    是后来才引入的）在轨 B 上只剩 ``Repository`` 的聚合态可看，少了这一分量它们的
    重建会完全不反映在签名里。
    """
    from repositories.models import GraphBuildHistory, Repository

    row = (
        GraphBuildHistory.objects.filter(
            repository_id=repository_id, branch_name=branch
        )
        .values_list("id", "status", "finished_at", "symbols_count", "calls_count")
        .first()
    )
    values = row if row else ("-",) * _TRACK_B_FIELDS
    parts = ["ghB:" + ":".join(str(v) for v in values)]

    repo_g = (
        Repository.objects.filter(id=repository_id)
        .values_list("graph_build_status", "graph_last_built_at")
        .first()
    )
    parts.append("repoG:" + ":".join(str(v) for v in (repo_g or ("-", "-"))))
    return parts


def _count_parts(repository_id: str, branch: str) -> list[str]:
    """④ 计数分量 ``nsym:`` / ``ncall:`` —— 照 Galaxy 的 count 思路兜底。

    两条轨的状态机都只在走 lifecycle 时才推进。计数分量捕捉的是**绕过 lifecycle 的
    裸写入**（管理命令、数据修复脚本、以及 ``enqueue_edge_build_for_history`` 在
    ``history_id is None`` 时的透传路径）——那些场景下状态字段一动不动，但表里的行
    实实在在变了。

    ``branch_name__in`` 取 overlay 语义（RESEARCH Pitfall 3）：feature 分支图是
    「base 全量 + 分支增量」，所以两个分支的行都要计入；base 分支只计 ``""``。
    """
    from codegraph.models import CallEdge, Symbol

    branch_filter = ["", branch] if branch else [""]
    n_sym = Symbol.objects.filter(
        repository_id=repository_id, branch_name__in=branch_filter
    ).count()
    n_call = CallEdge.objects.filter(
        repository_id=repository_id, branch_name__in=branch_filter
    ).count()
    return [f"nsym:{n_sym}", f"ncall:{n_call}"]


def compute_signature(
    repository_id: str, branch: str, *, exclusion_fingerprint: str
) -> str:
    """算出 ``(repository, branch)`` 的复合缓存签名（sha256 十六进制串）。

    分量顺序固定，逐项带 ``label:`` 前缀后 ``"|".join`` 再哈希：

    ==========  ====================================================
    ``wm:``     索引水位（分支索引行优先，回落 ``Repository``）
    ``ihA:``    轨 A 代数：ChunkEdge 构建（``IndexHistory``）
    ``ghB:``    轨 B 代数：Symbol/CallEdge 抽取（``GraphBuildHistory``）
    ``repoG:``  轨 B 兜底：无 history 行的老仓
    ``nsym:``   ``Symbol`` 行数（overlay 口径）
    ``ncall:``  ``CallEdge`` 行数（overlay 口径）
    ``excl:``   exclusion 有效规则集指纹（调用方传入）
    ==========  ====================================================

    🚨 **本仓的「边构建」是两条互相独立的轨，签名必须都纳入**（121-CONTEXT D-02）。
    两条轨的写入方是完全不同的代码路径：

    ===  ==========================  ================================  =====================================  ==========================================
    轨   跟踪对象                    状态字段                          时间戳                                 写入方
    ===  ==========================  ================================  =====================================  ==========================================
    A    ``ChunkEdge``               ``IndexHistory.graph_build_status``  ``finished_at`` / ``payload_synced_at``  ``code_relations/lifecycle.py::enqueue_edge_build_for_history``
    B    ``Symbol``/``CallEdge``/``Endpoint``  ``Repository.graph_build_status`` + ``GraphBuildHistory.status``  ``graph_last_built_at`` / ``GraphBuildHistory.finished_at``  ``services/graph_builder.py::{reset_repository_graph_progress, mark_repository_graph_terminal}``
    ===  ==========================  ================================  =====================================  ==========================================

    ⛔ 只纳入轨 A 会漏掉「``Symbol``/``CallEdge`` 被重新抽取但 ``ChunkEdge`` 没变」
    的失效场景——而 ``CallEdge`` 恰恰是本相位图的**主边源**，那种漏失效意味着图里
    的调用边整整旧了一代，上层 impact 分析会据此给出过时结论。

    成本：全部是带索引的单行取值与 COUNT，毫秒级，与 Galaxy 的 7 条聚合同量级。

    :param repository_id: 仓库主键。
    :param branch: 分支名；``""`` 表示 base（与 ``Symbol.branch_name`` 同口径，
        **不是** ``RepositoryBranchIndex`` 的口径，见 :func:`_watermark_part`）。
    :param exclusion_fingerprint: exclusion 有效规则集指纹，由
        :func:`services.code_graph.access.build_matcher_and_fingerprint` 产出。
        **刻意由调用方传入、不在本函数内自己算**：loader 无论如何都要拿 matcher，
        在这里重复解析一遍规则集纯属浪费。这一分量是 GRAPH-04「规则改动后旧图自动
        失效」的落点——``_matcher_cache`` 的 60s TTL 只决定「何时重建 matcher」，
        不产生任何可比对的版本标识，**不足以**作为唯一防线（RESEARCH Pitfall 9）。
    """
    started = timezone.now()
    parts: list[str] = [_watermark_part(repository_id, branch)]
    parts.append(_track_a_part(repository_id))
    parts.extend(_track_b_parts(repository_id, branch))
    parts.extend(_count_parts(repository_id, branch))
    parts.append(f"excl:{exclusion_fingerprint}")

    digest = hashlib.sha256("|".join(parts).encode("utf-8")).hexdigest()
    _emit(
        _EVENT_SIGNATURE_COMPUTED,
        repository_id=str(repository_id),
        branch=branch or "-",
        duration_ms=int((timezone.now() - started).total_seconds() * 1000),
    )
    return digest
