"""项目上下文打包器（RECALL-01/03）。

按项目聚合**需求(WorkItem) + 文字工件(Artifact) + 记忆(ProjectMemory) + 关联知识
(KnowledgeEdge) + 历史(会话消息)**，经 **grep(SQL 精确) + RAG(语义)** 召回 → **排序 →
压缩 → token 预算可降级**，产出可注入 LLM 的项目上下文。

关键约束：
- **fail-closed（RECALL-03）**：``user`` 非 ``ProjectMember`` → 返回空上下文（零召回零泄漏）。
- **token 预算可降级**：按优先级裁剪——记忆/需求 > 工件 > 关联知识/RAG > 历史；超预算丢低优层。
- **RetrievalTrace（RECALL-03）**：上报条数 / 分层耗时 / score，写 ``RetrievalTrace``
  （AI 对话链；MCP/Cursor 链 Phase 81）。best-effort 绝不反噬。
- async ORM 走 ``sync_to_async``；观测 best-effort。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from time import perf_counter
from typing import Any

import structlog
from asgiref.sync import sync_to_async

logger = structlog.get_logger(__name__)

__all__ = ["PackedContext", "pack_project_context"]

_COMPONENT = "initiatives"

# 默认 token 预算（约束注入 system prompt 的项目上下文体量）。
_DEFAULT_TOKEN_BUDGET = 4000

# 分层优先级（数字越小越优先保留；超预算从高数字层开始裁剪）。
# overview 不进入本 budget 裁剪循环（作为强制头部注入，永不裁剪），此处登记仅为
# counts/included_layers 观测对齐。
_PRIORITY = {
    "overview": -1,
    "memory": 0,
    "requirements": 0,
    "features": 1,
    "artifacts": 1,
    "knowledge": 2,
    "rag": 2,
    "history": 3,
}


def _approx_tokens(text: str) -> int:
    """粗略 token 估算（~4 chars/token），用于预算裁剪。"""
    return max(1, len(text) // 4)


@dataclass
class _Layer:
    name: str
    lines: list[str]
    count: int
    elapsed_ms: int
    score: float = 0.0
    included: bool = False


@dataclass
class PackedContext:
    """打包结果。"""

    text: str = ""
    included_layers: list[str] = field(default_factory=list)
    degraded: bool = False
    counts: dict[str, int] = field(default_factory=dict)
    layer_timing_ms: dict[str, int] = field(default_factory=dict)
    scores: dict[str, float] = field(default_factory=dict)
    total_tokens: int = 0


async def _is_member(project_id: Any, user: Any) -> bool:
    from initiatives.models import ProjectMember

    uid = getattr(user, "id", None)
    if uid is None:
        return False
    return await ProjectMember.objects.filter(project_id=project_id, user_id=uid).aexists()


async def pack_project_context(
    project: Any,
    user: Any,
    *,
    query: str = "",
    conversation_id: str = "",
    token_budget: int = _DEFAULT_TOKEN_BUDGET,
    history_messages: list[str] | None = None,
) -> PackedContext:
    """聚合 + 召回 + 排序 + 压缩 + token 预算降级，产出项目上下文（RECALL-01/03）。

    Args:
        project: ``initiatives.Project`` 实例。
        user: 触发用户（非成员 → fail-closed 空上下文）。
        query: 语义召回 query（空则跳过 RAG 层）。
        conversation_id: 会话 id（RetrievalTrace 关联）。
        token_budget: token 预算（超预算按优先级裁剪低优层）。
        history_messages: 会话历史文本（可选，由调用方提供）。
    """
    from initiatives.models import ProjectVisibility

    project_id = getattr(project, "id", project)
    # 纯枚举读不触 DB，async 安全。
    visibility = getattr(project, "visibility", "")
    # WS-02 权限翻转（读半，RECALL-03 visibility 感知）：
    # - 成员（任意 visibility）→ 放行（不回退）
    # - 非成员 + public_org → 放行（全员可读可发起会话）
    # - 非成员 + members_only → fail-closed 零召回零泄漏
    allowed = await _is_member(project_id, user)
    if not allowed and visibility == ProjectVisibility.PUBLIC_ORG:
        allowed = True
    if not allowed:
        logger.info(
            "project_context_pack_denied",
            project_id=str(project_id),
            reason="not_member_members_only",
            visibility=str(visibility),
            component=_COMPONENT,
            category="caller",
        )
        return PackedContext()

    # 项目概览（名称/所属空间/状态/描述）——项目级对话的"我是什么项目"直接由此回答。
    # 作为强制头部注入（不参与 token 预算裁剪，体量极小），保证永远可见、不被降级丢弃。
    overview_layer = await _layer_overview(project)

    layers: list[_Layer] = []
    layers.append(await _layer_memory(project_id))
    layers.append(await _layer_requirements(project_id))
    layers.append(await _layer_features(project_id))
    layers.append(await _layer_artifacts(project_id))
    layers.append(await _layer_knowledge(project))
    if query:
        layers.append(await _layer_rag(query, user, project_id))
    if history_messages:
        layers.append(_layer_history(history_messages))

    # 排序：按优先级（升序）+ score（降序）；同优先级 RAG 命中分高者先。
    layers.sort(key=lambda layer: (_PRIORITY.get(layer.name, 9), -layer.score))

    # 压缩 + token 预算降级：累计 token 超预算的层标记 included=False（裁剪）。
    used = 0
    degraded = False
    for layer in layers:
        if not layer.lines:
            continue
        block = _render_block(layer)
        cost = _approx_tokens(block)
        if used + cost > token_budget and used > 0:
            degraded = True
            continue
        layer.included = True
        used += cost

    sections: list[str] = []
    included_layers: list[str] = []
    if overview_layer.lines:
        sections.append(_render_block(overview_layer))
        included_layers.append("overview")
        used += _approx_tokens(_render_block(overview_layer))
    sections.extend(
        _render_block(layer) for layer in layers if layer.included and layer.lines
    )
    included_layers.extend(
        layer.name for layer in layers if layer.included and layer.lines
    )
    text = ""
    if sections:
        text = "# 项目上下文（自动召回）\n\n" + "\n\n".join(sections)

    result = PackedContext(
        text=text,
        included_layers=included_layers,
        degraded=degraded,
        counts={
            "overview": overview_layer.count,
            **{layer.name: layer.count for layer in layers},
        },
        layer_timing_ms={
            "overview": overview_layer.elapsed_ms,
            **{layer.name: layer.elapsed_ms for layer in layers},
        },
        scores={layer.name: layer.score for layer in layers if layer.score},
        total_tokens=used,
    )

    await _write_trace(
        result,
        query=query,
        conversation_id=conversation_id,
        user=user,
        visibility=str(visibility),
    )
    return result


def _render_block(layer: _Layer) -> str:
    titles = {
        "overview": "## 项目概览",
        "memory": "## 项目记忆",
        "requirements": "## 需求 / 工作项",
        "features": "## Feature 清单（模块）",
        "artifacts": "## 工件",
        "knowledge": "## 关联知识",
        "rag": "## 语义召回",
        "history": "## 对话历史",
    }
    header = titles.get(layer.name, f"## {layer.name}")
    return header + "\n" + "\n".join(layer.lines)


async def _layer_overview(project: Any) -> _Layer:
    """项目概览层：名称/所属空间/状态/描述（回答"我是什么项目"的第一信息源）。

    ``project`` 可能未 ``select_related("space")``——所有属性访问（含 lazy space FK /
    ``get_status_display``）统一在 ``sync_to_async`` 内完成，避免裸 async 触 ORM。
    """
    start = perf_counter()

    @sync_to_async
    def _fetch() -> list[str]:
        lines: list[str] = []
        name = (getattr(project, "name", "") or "").strip()
        if name:
            lines.append(f"- 名称：{name}")
        space = getattr(project, "space", None)
        space_name = (getattr(space, "name", "") or "").strip() if space else ""
        if space_name:
            lines.append(f"- 所属空间：{space_name}")
        try:
            status_display = project.get_status_display()
        except Exception:  # noqa: BLE001 — 状态展示 best-effort，回退原始值
            status_display = getattr(project, "status", "") or ""
        if status_display:
            lines.append(f"- 状态：{status_display}")
        desc = (getattr(project, "description", "") or "").strip()
        if desc:
            lines.append(f"- 描述：{desc[:1000]}")
        return lines

    lines = await _fetch()
    return _Layer("overview", lines, len(lines), _ms(start))


async def _layer_features(project_id: Any) -> _Layer:
    """Feature 清单层：模块名 + 模块介绍 + 功能点名（只取轻量摘要，非全量验收项）。

    经 ``FeatureListService.build_tree`` 统一解析 markdown / 飞书 bitable 两种载体，
    fail-soft：无 feature_list 工件 / 拉取失败 → 空层（不反噬打包）。
    """
    start = perf_counter()
    lines: list[str] = []
    try:
        from initiatives.services.feature_list_service import FeatureListService

        tree = await FeatureListService().build_tree(project_id)
        for mod in (tree.get("modules") or [])[:20]:
            module = str(mod.get("module") or "未分组").strip()
            feats = mod.get("features") or []
            summary = str(mod.get("summary") or "").strip()
            names = "、".join(
                str(f.get("name") or "").strip()
                for f in feats[:8]
                if str(f.get("name") or "").strip()
            )
            line = f"- {module}（{len(feats)} 个功能点）"
            if summary:
                line += f"：{summary[:120]}"
            if names:
                line += f" — {names}"
            lines.append(line)
    except Exception:  # noqa: BLE001 — feature 树召回 best-effort，失败降级空层
        lines = []
    return _Layer("features", lines, len(lines), _ms(start))


async def _layer_memory(project_id: Any) -> _Layer:
    from initiatives.models import ProjectMemory, ProjectMemoryStatus

    start = perf_counter()

    @sync_to_async
    def _fetch() -> list[str]:
        rows = list(
            ProjectMemory.objects.filter(
                project_id=project_id, status=ProjectMemoryStatus.ACTIVE
            ).order_by("-created_at")[:30]
        )
        return [f"- {r.content}" for r in rows if r.content]

    lines = await _fetch()
    return _Layer("memory", lines, len(lines), _ms(start))


async def _layer_requirements(project_id: Any) -> _Layer:
    from initiatives.models import ProjectWorkItemLink

    start = perf_counter()

    @sync_to_async
    def _fetch() -> list[str]:
        links = list(
            ProjectWorkItemLink.objects.filter(project_id=project_id)
            .select_related("work_item")[:50]
        )
        out: list[str] = []
        for link in links:
            wi = link.work_item
            if wi is None:
                continue
            out.append(f"- [{wi.work_item_type}/{wi.work_item_id}] {wi.title}")
        return out

    lines = await _fetch()
    return _Layer("requirements", lines, len(lines), _ms(start))


async def _layer_artifacts(project_id: Any) -> _Layer:
    from initiatives.models import Artifact, TEXT_CARRIERS

    start = perf_counter()

    @sync_to_async
    def _fetch() -> list[str]:
        rows = list(
            Artifact.objects.filter(
                project_id=project_id, carrier__in=list(TEXT_CARRIERS)
            ).select_related("type")[:30]
        )
        out: list[str] = []
        for a in rows:
            snippet = (a.content_ref or "")[:300]
            line = f"- [{a.type.name}] {a.title}"
            if snippet:
                line += f": {snippet}"
            out.append(line)
        return out

    lines = await _fetch()
    return _Layer("artifacts", lines, len(lines), _ms(start))


async def _layer_knowledge(project: Any) -> _Layer:
    start = perf_counter()
    try:
        from initiatives.services.knowledge_graph import ProjectKnowledgeGraphService

        nodes = await ProjectKnowledgeGraphService().query_graph(
            project=project, direction="both", max_hops=1
        )
    except Exception:  # noqa: BLE001 — 召回 best-effort，失败降级空层
        nodes = []
    lines = [
        f"- [{n.get('kind', '')}] {n.get('title', '')}"
        for n in nodes
        if n.get("title")
    ][:30]
    return _Layer("knowledge", lines, len(lines), _ms(start))


async def _layer_rag(query: str, user: Any, project_id: Any) -> _Layer:
    start = perf_counter()
    lines: list[str] = []
    top_score = 0.0
    try:
        from knowledge.retrieval import DeliveryKnowledgeSearchService

        results = await DeliveryKnowledgeSearchService().search_similar(
            query,
            user=user,
            top_k=8,
            # CTX-01：AI 对话链项目上下文同样纳入 DOCUMENT 召回（项目 5 文件/记忆/工件物化），
            # 权限仍由 search_similar 内 allowed_project_ids/visibility 收口，无泄漏。
            include_document_kind=True,
        )
        for r in results:
            title = getattr(getattr(r, "entity", None), "title", "") or ""
            score = float(getattr(r, "score", 0.0) or 0.0)
            top_score = max(top_score, score)
            if title:
                lines.append(f"- {title}（score={score:.3f}）")
    except Exception:  # noqa: BLE001 — RAG best-effort，失败降级空层
        lines = []
    return _Layer("rag", lines, len(lines), _ms(start), score=top_score)


def _layer_history(history_messages: list[str]) -> _Layer:
    recent = [m for m in history_messages if m][-10:]
    lines = [f"- {m[:300]}" for m in recent]
    return _Layer("history", lines, len(lines), 0)


def _ms(start: float) -> int:
    return int((perf_counter() - start) * 1000)


async def _write_trace(
    result: PackedContext,
    *,
    query: str,
    conversation_id: str,
    user: Any,
    visibility: str = "",
) -> None:
    """上报召回条数/分层耗时/score 并写 RetrievalTrace（best-effort）。

    payload 标记 ``visibility``——非成员命中 public_org 召回也写 trace，保证可归因。
    """
    try:
        from interactions.ledger import arecord_retrieval_trace

        await arecord_retrieval_trace(
            kind="chunk",
            payload={
                "query": query,
                "counts": result.counts,
                "layer_timing_ms": result.layer_timing_ms,
                "scores": result.scores,
                "included_layers": result.included_layers,
                "degraded": result.degraded,
                "total_tokens": result.total_tokens,
                "visibility": visibility,
            },
            user_id=str(getattr(user, "id", None)) if getattr(user, "id", None) else None,
            conversation_id=conversation_id or "",
            source="chat_project_context",
        )
        logger.info(
            "project_context_recall_completed",
            counts=result.counts,
            included_layers=result.included_layers,
            degraded=result.degraded,
            total_tokens=result.total_tokens,
            component=_COMPONENT,
            category="sampling",
        )
    except Exception:  # noqa: BLE001 — 观测绝不反噬召回主流程
        pass
