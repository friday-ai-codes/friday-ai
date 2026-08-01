"""蓝图（``delivery.Artifact`` 的 ``blueprint/v1`` content）→ 交付知识图谱 normalizer
（Phase 116-04 / VIEW-04 / SC-4）。

产出**一个** ``KnowledgeEntity(kind=tech_plan, source_kind="blueprint")``
（natural key = ``generate_entity_id("tech_plan", "blueprint", artifact_id)``，⛔ 不新建
``EntityKind`` —— ``source_kind`` 区分子类是 Phase 100 已定的惯例）与**两类出边**：

- ``citations`` → ``REFERENCES``（``exclusive=False``、**append-only**：新版本删掉某条引用
  **不**失效旧边 —— bi-temporal 下「v2 曾经引用过它」仍然是事实）；
- ``meta.project_id`` → 项目图谱节点 ``RELATES_TO``（``exclusive=True``）。

四条结构约束（每条都对应一个「断言全绿而功能为零」的失败形态，各配一条用例）：

⭐ **约束 ①：citation 派生的目标实体不存在时，spec 必须在交给 ``apply_edge_specs`` 之前
就被过滤掉。** ``KnowledgeEdge.target_entity`` 是**真 FK**（``knowledge/models.py:305-311``）
⇒ 目标不存在时 ``add_edge`` 抛 ``IntegrityError``，被 ``apply_edge_specs:435-443`` 吞成一条
``knowledge_ingest_edge_conflict`` warning，**边静默消失**；更糟的是该分支与「撞
``uniq_kedge_active``（并发已建，良性）」**共用同一个 except**，日志里根本分不出「边丢了」
和「本来就有」。⇒ 一次批量存在性查询预过滤 + 丢弃计数进 ``sampling`` 事件。
⛔ 该过滤器**只作用于 citation 派生的目标**：项目边的目标经
``ProjectKnowledgeGraphService.ensure_project_node``（幂等 get_or_create）拿到，节点必然存在；
把它塞进过滤器会在「项目节点尚未被别的路径建过」的生产场景里把边静默吃掉，而任何测试夹具
都会顺手把节点建出来 ⇒ 「``RELATES_TO`` 恰好 1 条」永久恒绿。

⭐ **约束 ②：同一个目标的多条 citation 必须聚合成一条 ``EdgeSpec``。**
``uniq_kedge_active`` 是 ``(source_entity, target_entity, relation)`` 唯一
（``models.py:335-339``）⇒ 「一条 citation 一条边」的朴素写法从第二条起**稳定撞约束**并被吞成
warning。⇒ 按 target 分组，``metadata`` 累积 ``citation_ids`` / ``source_types``。

⭐ **约束 ③：``RELATES_TO`` 出边有且只有项目这一条。**
``exclusive=True`` 的作用域是 ``(source, relation)`` **不含目标类型**
（``apply_edge_specs:423-426`` 的实现逐字如此）⇒ 多条 ``RELATES_TO`` 出边会互相
``invalidate_edge``，而且走的是**正常路径**（不是异常、不是 warning）—— **完全静默**。
将来若想加「蓝图 → 仓库」的 ``RELATES_TO``，必须先解决这条。

⭐ **约束 ④：边 metadata 里 ⛔ 不放 ``first_seen_version_no``。**
重摄取时 ``apply_edge_specs:412-422`` 对已有活跃边调 ``update_edge_metadata`` **整体覆盖**，
而 normalizer 只能看到当前版本的 content、拿不到既有边 metadata ⇒ 该字段每次都会被刷成当前
版本号，**字段名与语义直接对不上**，成为一条会误导排查的假数据。它的信息量已由
``KnowledgeEdge.valid_at`` / ``created_at`` 承载。

降级语义（缺料一律 warning + **返回空列表**，⛔ 不产半截事件）：artifact / 当前版本 /
``schema_version`` 判别 / ``meta.project_id`` / ``Project.space_id`` 任一取不到即整体不入图。
⭐ 特别地 **space 反查不到为什么是「整体不入图」**：``fetch_related_entities`` 有**两处**
``space_id is None`` 短路（``related.py:40-41`` 判起点实体、``:79-80`` 判每个对端实体）
⇒ space 为空的实体既查不出邻居、也不会出现在别人的邻居里，是一个**双向不可见**的孤儿节点。
「入了图却永远查不出来」是对它最精确的描述，比不入图难排查得多。

**脱敏不可绕过**：蓝图正文是半可信内容（LLM 合成 + 用户输入），入图前经
``redact_secrets_in_text``；日志只记 id 与计数，⛔ 绝不记正文。
观测：``blueprint_knowledge_normalize_started/completed`` + ``duration_ms``
（``category="sampling"`` / ``component="knowledge"``）。
"""

from __future__ import annotations

import time
import uuid
from collections import Counter
from datetime import datetime
from typing import Any

import structlog
from django.utils import timezone

from common.logging import redact_secrets_in_text
from knowledge.ingestion import EdgeSpec, IngestionEvent, IngestionRequest
from knowledge.models import (
    EdgeRelation,
    EntityKind,
    EntityOrigin,
    KnowledgeEntity,
    generate_entity_id,
)

logger = structlog.get_logger(__name__)

__all__ = ["blueprint_entity_id", "normalize"]

_COMPONENT = "knowledge"
# 正文提炼上界：只为 embedding 服务，⛔ 不做全文归档（全文在 ArtifactVersion.content）。
_MAX_CONTENT_CHARS = 60_000


def _aware(value: datetime | None) -> datetime | None:
    """naive datetime 补当前时区（边写入层 ``require_aware`` 防线前置）。"""
    if value is None:
        return None
    return timezone.make_aware(value) if timezone.is_naive(value) else value


def _as_uuid(raw: Any) -> uuid.UUID | None:
    """畸形输入防御：非 UUID 一律 None（半可信 citation 的 source_id 直接来自 LLM 产物）。"""
    if isinstance(raw, uuid.UUID):
        return raw
    try:
        return uuid.UUID(str(raw))
    except (AttributeError, TypeError, ValueError):
        return None


def blueprint_entity_id(artifact_id: Any) -> uuid.UUID:
    """蓝图实体 natural key（``generate_entity_id`` 唯一入口，⛔ 不复刻 id 派生规则）。

    ⭐ **公开**给读侧换算用（``delivery/api/blueprint_doc_views.py`` 的第 8 键）：
    INV-3 禁止 delivery app 直接 import ``knowledge`` 的模型层，而 natural key 又只能有
    一份定义 ⇒ 由拥有这条 natural key 的本模块对外暴露一个派生函数
    （与 ``initiatives.services.knowledge_graph.project_node_id`` 同款分工）。
    """
    return generate_entity_id(EntityKind.TECH_PLAN, "blueprint", str(artifact_id))


def _work_item_triple(citation: dict) -> str | None:
    """还原飞书工作项三元组 ``{project_key}:{type_key}:{item_id}``；还原不出返回 None。

    ``source_id`` 已是三元组时直取；否则从 ``locator`` 的三个键拼。natural key 规则表
    （``knowledge/models.py`` ``generate_entity_id`` docstring）锁定该格式，⛔ 不自造锚格式。
    """
    source_id = str(citation.get("source_id") or "")
    if source_id.count(":") == 2 and all(source_id.split(":")):
        return source_id
    locator = citation.get("locator")
    if not isinstance(locator, dict):
        return None
    project_key = str(locator.get("project_key") or "")
    type_key = str(locator.get("work_item_type_key") or locator.get("work_item_type") or "")
    item_id = str(locator.get("work_item_id") or locator.get("item_id") or "")
    if not (project_key and type_key and item_id):
        return None
    return f"{project_key}:{type_key}:{item_id}"


def _repository_id(citation: dict) -> uuid.UUID | None:
    """仓库类引用（``repo_file`` / ``rag_chunk`` / ``repo_charter``）的 repo id。

    先取 ``locator``（``repository_id`` / ``repo_id``），再退到 ``source_id``
    （``repo_charter`` 的引用条目把 repo id 放在这里，见 ``blueprint_route.py:791``）；
    都还原不出即返回 None ⇒ 丢弃并计数（``repo_file`` 的 ``source_id`` 是文件路径，属此列）。
    """
    locator = citation.get("locator")
    if isinstance(locator, dict):
        for key in ("repository_id", "repo_id"):
            hit = _as_uuid(locator.get(key))
            if hit is not None:
                return hit
    return _as_uuid(citation.get("source_id"))


async def _aresolve_target_entity_id(citation: dict) -> uuid.UUID | None:
    """九种 ``source_type`` → 目标实体 id；还原不出（含 ``url``）一律 None ⇒ 丢弃并计数。

    仓库类三种统一落 ``initiatives.services.knowledge_graph.repository_node_id``
    —— 它就是 ``generate_entity_id(EntityKind.REPOSITORY, "repository", …)`` 的既有唯一派生
    入口（``:57-58``），⛔ 不在本模块写一份会漂移的内联副本。
    """
    from initiatives.services.knowledge_graph import repository_node_id

    source_type = str(citation.get("source_type") or "")
    source_id = str(citation.get("source_id") or "")

    if source_type == "knowledge_entity":
        return _as_uuid(source_id)
    if source_type == "work_item":
        triple = _work_item_triple(citation)
        if triple is None:
            return None
        return generate_entity_id(EntityKind.WORK_ITEM, "feishu_work_item", triple)
    if source_type == "feishu_doc":
        token = source_id or str((citation.get("locator") or {}).get("token") or "")
        if not token:
            return None
        return generate_entity_id(EntityKind.DOCUMENT, "feishu_document", token)
    if source_type == "blueprint":
        artifact_id = _as_uuid(source_id)
        return None if artifact_id is None else blueprint_entity_id(artifact_id)
    if source_type == "artifact_version":
        from delivery.models import ArtifactVersion

        version_id = _as_uuid(source_id)
        if version_id is None:
            return None
        artifact_id = (
            await ArtifactVersion.objects.filter(id=version_id)
            .values_list("artifact_id", flat=True)
            .afirst()
        )
        return None if artifact_id is None else blueprint_entity_id(artifact_id)
    if source_type in ("repo_file", "rag_chunk", "repo_charter"):
        repo_id = _repository_id(citation)
        return None if repo_id is None else repository_node_id(repo_id)
    # ``url``（以及任何未知 source_type）⛔ 不成边：图里没有对应节点，
    # 建边只会撞 FK 被吞成 warning。
    return None


async def _abuild_reference_edges(
    citations: Any, *, artifact_id: str
) -> tuple[list[EdgeSpec], dict[str, Any]]:
    """citations 引用池 → 聚合后的 ``REFERENCES`` EdgeSpec 列表 + 丢弃统计。

    三步：逐条换算目标（约束 ④：metadata 里不放会被重摄取刷成谎言的版本号字段）→ **按 target
    分组聚合成一条 spec**（约束 ②）→ **一次批量存在性预过滤**（约束 ①）。
    ``citation_ids`` / ``source_types`` 排序后写入，保证重摄取时 metadata 幂等。
    """
    pool = citations if isinstance(citations, dict) else {}
    grouped: dict[uuid.UUID, dict[str, Any]] = {}
    dropped: Counter[str] = Counter()

    for citation in pool.values():
        if not isinstance(citation, dict):
            continue
        citation_id = str(citation.get("citation_id") or "")
        source_type = str(citation.get("source_type") or "unknown")
        if not citation_id:
            dropped[source_type] += 1
            continue
        target_id = await _aresolve_target_entity_id(citation)
        if target_id is None:
            dropped[source_type] += 1
            continue
        bucket = grouped.setdefault(target_id, {"citation_ids": set(), "source_types": Counter()})
        bucket["citation_ids"].add(citation_id)
        bucket["source_types"][source_type] += 1

    # 存在性预过滤（约束 ①）：一次批量查，⛔ 不逐条查。
    existing: set[uuid.UUID] = set()
    if grouped:
        existing = {
            row
            async for row in KnowledgeEntity.objects.filter(id__in=list(grouped)).values_list(
                "id", flat=True
            )
        }

    specs: list[EdgeSpec] = []
    for target_id in sorted(grouped, key=str):
        bucket = grouped[target_id]
        if target_id not in existing:
            dropped.update(bucket["source_types"])
            continue
        specs.append(
            EdgeSpec(
                relation=EdgeRelation.REFERENCES,
                target_entity_id=target_id,
                exclusive=False,
                metadata={
                    "source": "blueprint",
                    "citation_ids": sorted(bucket["citation_ids"]),
                    "source_types": sorted(bucket["source_types"]),
                },
            )
        )

    stats = {
        "artifact_id": artifact_id,
        "kept_count": len(specs),
        "dropped_count": sum(dropped.values()),
        "dropped_by_source_type": dict(sorted(dropped.items())),
    }
    return specs, stats


def _content_text(content: dict) -> str:
    """提炼 embedding 正文：标题 + 逐段 block 文本（按 ``iter_blocks`` 的确定性走查）。

    ⭐ 块取文本口径必须与 ``blueprint_anchor._block_text`` **同源**（``text`` →
    ``code.source`` → ``rows`` 的**字段优先级**，⛔ 不按 block 的类型字段分派）——
    否则与 114 的锚点坐标系分叉，同一个块在两处会取出不同文本。
    """
    from delivery.services.blueprint_anchor import _block_text
    from services.process_runtime.blueprint_schema import iter_blocks

    meta = content.get("meta") if isinstance(content.get("meta"), dict) else {}
    lines: list[str] = [f"# {meta.get('title') or '未命名技术蓝图'}"]
    current_section = ""
    for section_path, block in iter_blocks(content):
        section = section_path.split(".", 1)[0]
        if section != current_section:
            current_section = section
            lines.append(f"\n## {section}")
        text = _block_text(block).strip()
        if text:
            lines.append(text)
    return "\n".join(lines)[:_MAX_CONTENT_CHARS]


async def normalize(request: IngestionRequest) -> list[IngestionEvent]:
    """蓝图 artifact id → 单 tech_plan 事件（携 REFERENCES + RELATES_TO 出边）。

    缺料（artifact / 版本 / ``blueprint/v1`` 判别 / project / space）一律 warning +
    返回空列表——⛔ 不产半截事件，尤其不产 ``space_id`` 为空的双向不可见孤儿节点。
    """
    from delivery.models import Artifact, ArtifactVersion
    from initiatives.models import Project
    from initiatives.services.knowledge_graph import ProjectKnowledgeGraphService
    from services.process_runtime.blueprint_schema import BLUEPRINT_SCHEMA_VERSION

    started = time.perf_counter()
    logger.info(
        "blueprint_knowledge_normalize_started",
        source_id=request.source_id,
        trigger=request.trigger,
        component=_COMPONENT,
        category="sampling",
    )

    artifact_id = _as_uuid(request.source_id)
    artifact = (
        None if artifact_id is None else await Artifact.objects.filter(id=artifact_id).afirst()
    )
    version = (
        None
        if artifact is None
        else await ArtifactVersion.objects.filter(artifact_id=artifact_id)
        .order_by("-version_no")
        .afirst()
    )
    if artifact is None or version is None:
        logger.warning(
            "knowledge_normalize_source_missing",
            source_kind=request.source_kind,
            source_id=request.source_id,
            trigger=request.trigger,
        )
        return []

    content = version.content if isinstance(version.content, dict) else {}
    if content.get("schema_version") != BLUEPRINT_SCHEMA_VERSION:
        # v0（旧 MergedPlan 隐式无 schema_version）不建蓝图实体——它没有 citations 池
        # 与 meta.project_id，入图只会产出一个查不出任何邻居的空节点。
        logger.warning(
            "blueprint_knowledge_normalize_schema_mismatch",
            source_id=request.source_id,
            trigger=request.trigger,
            schema_version=str(content.get("schema_version") or ""),
        )
        return []

    meta = content.get("meta") if isinstance(content.get("meta"), dict) else {}
    project_id = _as_uuid(meta.get("project_id"))
    project = None if project_id is None else await Project.objects.filter(id=project_id).afirst()
    if project is None or project.space_id is None:
        # space 反查不到即整体不入图（见模块 docstring：双向不可见的孤儿节点）。
        logger.warning(
            "knowledge_normalize_blueprint_space_unresolved",
            source_id=request.source_id,
            trigger=request.trigger,
            project_id=str(meta.get("project_id") or ""),
        )
        return []

    entity_id = blueprint_entity_id(artifact_id)
    # 脱敏不可绕过：半可信正文入图（进 embedding）前先过 redact_secrets_in_text。
    content_text = redact_secrets_in_text(_content_text(content))
    citations = content.get("citations")
    edge_specs, drop_stats = await _abuild_reference_edges(citations, artifact_id=str(artifact_id))
    logger.info(
        "blueprint_knowledge_edges_resolved",
        trigger=request.trigger,
        component=_COMPONENT,
        category="sampling",
        **drop_stats,
    )

    # 项目 RELATES_TO 边（约束 ③：恰好 1 条）。目标节点经该 service 的幂等 get_or_create
    # 取得——它是 PROJECT/REPOSITORY/SPACE 参考节点的**唯一写者**
    # （``initiatives/services/knowledge_graph.py:1-7``），与 ``project_doc.py:110`` /
    # ``project_memory.py:90`` / ``artifact.py:396`` 三处逐字同形。
    # ⛔ 绝不写成「查一下、查不到就丢弃」：那样在项目节点尚未被别的路径建过时边会被静默吃掉。
    project_node_id = await ProjectKnowledgeGraphService().ensure_project_node(project)
    edge_specs.append(
        EdgeSpec(
            relation=EdgeRelation.RELATES_TO,
            target_entity_id=project_node_id,
            exclusive=True,
            metadata={"source": "blueprint", "project_id": str(project.id)},
        )
    )

    payload = {
        "artifact_id": str(artifact_id),
        "version_no": int(getattr(version, "version_no", 0) or 0),
        "project_id": str(project.id),
        # ⛔ 不快照蓝图生命周期状态：INV-6 把该字段的读写面收在
        # BlueprintLifecycleService 的 CAS update 一处，图谱侧复制一份既违纪又必然过期。
        "status": str(getattr(artifact, "status", "") or ""),
        "citation_count": len(citations) if isinstance(citations, dict) else 0,
        "reference_edge_count": len(edge_specs) - 1,
    }
    event = IngestionEvent(
        kind=EntityKind.TECH_PLAN,
        origin=EntityOrigin.ARTIFACT,
        source_kind="blueprint",
        source_id=str(artifact_id),
        title=str(meta.get("title") or artifact.title or "未命名技术蓝图")[:500],
        content=content_text,
        payload=payload,
        space_id=str(project.space_id),
        repository_id=None,
        event_time=_aware(version.created_at) or timezone.now(),
        edges=tuple(edge_specs),
    )

    logger.info(
        "blueprint_knowledge_normalize_completed",
        source_id=request.source_id,
        entity_id=str(entity_id),
        trigger=request.trigger,
        version_no=payload["version_no"],
        content_length=len(content_text),
        edge_count=len(edge_specs),
        duration_ms=round((time.perf_counter() - started) * 1000, 2),
        component=_COMPONENT,
        category="sampling",
    )
    return [event]
