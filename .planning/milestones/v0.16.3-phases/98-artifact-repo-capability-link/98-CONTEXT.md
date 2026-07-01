# Phase 98: 工件↔仓库/能力/关键词关联 - Context

**Gathered:** 2026-07-01
**Status:** Ready for planning
**Mode:** Smart discuss (autonomous — grey areas auto-decided，决策原则「优雅、好用」，用户已授权不逐项确认)

<domain>
## Phase Boundary

为外部依赖工件建立与代码仓库、业务能力、关键词的结构化关联，并把已确认的项目仓库关联同步进知识图谱，使关联可查询（后端图谱 + 路由为主，无前端 UI）。

1. KDEP-07：ragable 文字工件在摄取/更新时经 `RepoRouterV2` 路由正文 → matched 仓库 + `matched_node_paths`（能力树节点路径）+ 关键词，落 `KnowledgeEdge(RELATES_TO)` + `metadata={source:artifact, artifact_id, node_paths, keywords, score}`，**单一写入入口**、`call_source` 观测、fail-soft 绝不反噬。
2. KDEP-08：verified `RepoAssociation` 同步为项目/工件↔仓库的图谱边（扩展 `sync_relations_from_operational` / `link_repository`），`RepoAssociation` 仍是**唯一真相源**、图谱边单向派生、不新建重复真相源。
3. KDEP-09：关联可查询——给定工件列出相关仓库/能力/关键词；给定能力/关键词/仓库反查相关文档；查询走 `graph_store` 收口。

**边界内**：工件正文路由建边、verified RepoAssociation 同步边、双向查询 API/服务。
**边界外**：星图/实体详情/作战室可视化与交叉入口（Phase 99）；关键词/能力升级为一等实体表（v2）。
</domain>

<decisions>
## Implementation Decisions

### 工件正文路由建边（KDEP-07）
- 在**工件摄取/更新的单一写入路径**（Phase 96 已收口的 `knowledge/sources/artifact.py` normalizer / ingestion 完成回调处）挂一个 best-effort 后置步骤：对 **ragable 文字工件**取正文调用 `RepoRouterV2.route()`，得 matched 仓库 + `matched_node_paths` + keywords + score。
- 落边：对每个 matched 仓库建 `KnowledgeEdge(relation="RELATES_TO", from=artifact document 实体, to=repository 实体)`，`metadata={source:"artifact", artifact_id, node_paths:[...], keywords:[...], score}`。能力/关键词**不建独立实体节点**，用边 metadata 承载（research §2.4 锁定）。
- 写入收口：统一走 `ProjectKnowledgeGraphService` / `graph_store.add_edge` + `EdgeSpec`（单一写入入口）；幂等——同 artifact→repo 边按 (artifact_id, repo) upsert，重跑不产生重复边、metadata 覆盖为最新路由结果。
- fail-soft：路由/建边任何异常吞掉（`except: pass` 语义）+ 结构化 failed 日志，**绝不打断工件摄取主流程**（best-effort，反噬零容忍）。
- 观测：新增 LLM/路由调用点赋 `call_source`（RepoRouterV2 若走 LLM 用其既有 call_source；建边步骤 component=knowledge，category=sampling 因随摄取高频），started/completed/failed + `duration_ms` + 命中仓库数/节点路径数/关键词数。
- 非 ragable 工件无正文 → 跳过路由（不建 RELATES_TO 边，仅保留 Phase 96 的 REFERENCES→project 边），属预期。

### verified RepoAssociation 同步为图谱边（KDEP-08）
- 扩展 `sync_relations_from_operational`（或 `link_repository`）：当 `RepoAssociation.status == verified` 时，派生项目↔仓库图谱边（如 `RELATES_TO` 或既有语义边），`metadata` 标注 `source:"repo_association", association_id, score, confidence, matched_node_paths`。
- `RepoAssociation` 保持**唯一真相源**，图谱边单向派生：状态从 verified 变为 rejected/撤销时，同步移除/失效对应派生边（保持一致性）。不新建与 RepoAssociation 重复的真相表。
- 触发点：在 RepoAssociation 状态流转到 verified 的服务方法（`RepoAssociationService`）里调用同步（单一入口），best-effort + 观测。
- 幂等：按 association_id 派生，重复同步不产生重复边。

### 关联可查询（KDEP-09）
- 查询走既有图谱遍历收口 `graph_store`，不绕过。提供服务层双向查询能力：
  - 给定工件 → 相关仓库 / 能力（node_paths）/ 关键词（遍历该 artifact 实体的 RELATES_TO 出边 + 读 metadata）。
  - 给定仓库/能力/关键词 → 反查相关工件（反向遍历 / metadata 过滤）。
- 暴露方式：优先在服务层提供可复用查询方法（供 Phase 99 可视化与后续接口调用）；若本阶段需要最小可验证入口，加一个只读查询接口 `GET /api/knowledge/artifacts/{id}/associations/`（access_scope 过滤），保持「优雅」——最小面积、能力就位即可，重可视化留给 Phase 99。
- 权限：查询强制 access_scope 过滤，越权工件/仓库不可见。

### 横切
- INV-6 单一写入入口；async ORM 一律 `sync_to_async`；不新建重复真相源。
- 观测规范：structlog kv started/completed/failed + `duration_ms`、category（caller 接口 / sampling 摄取内步骤）+ component、`call_source`（路由/LLM）；召回/路由若涉及内容按需写 `RetrievalTrace`（RepoRouterV2 既有链路复用）；脱敏走既有 processor。best-effort 不反噬。
- 不改 `delivery_knowledge` 向量 schema；边与 metadata 承载新增关联。

### Claude's Discretion
- 具体边 relation 语义命名（RELATES_TO vs 更细）、同步的精确 hook 位置、查询接口是否本阶段暴露 vs 仅服务层、metadata 字段命名由 plan/execute 按既有 `EdgeSpec`/`graph_store` 约定自定，遵循「优雅、好用」：单一写入、单向派生、幂等、fail-soft、复用既有路由与图谱设施。
</decisions>

<code_context>
## Existing Code Insights

### Reusable Assets
- 路由：`server/codegraph/services/repo_router_v2.py`（`RepoRouterV2.route()` → matched repo + `matched_node_paths` + keywords + score）。
- 真相源：`server/initiatives/services/repo_association_service.py`（`RepoAssociation` proposed→confirmed→verifying→verified|rejected，带 score/confidence/matched_node_paths）；`link_repository`（已有方法、未被业务调用）。
- 图谱写入/遍历收口：`server/initiatives/services/knowledge_graph.py`（`ProjectKnowledgeGraphService`，`sync_relations_from_operational` 扩展点）+ `server/knowledge/graph_store.py`（`add_edge` / `EdgeSpec` / 遍历）；`KnowledgeEntity.kind` 含 document/repository/project；`KnowledgeEdge.relation` 含 REFERENCES/RELATES_TO（bi-temporal + metadata JSON）。
- 摄取单一入口（Phase 96 收口）：`server/knowledge/sources/artifact.py` + `server/knowledge/ingestion.py`（工件 document 实体 + REFERENCES→project 边已在此建）。
- 权限：`server/knowledge/access_scope.py`。

### Established Patterns
- 摄取经 durable 调度 + normalizer；建边走 EdgeSpec + graph_store 收口；bi-temporal 边 upsert。
- 观测 kv + call_source（RepoRouterV2 既有）；async ORM `sync_to_async`；best-effort fail-soft。

### Integration Points
- 建边挂 artifact ingestion 完成路径（`sources/artifact.py` / ingestion 回调）。
- 同步挂 `RepoAssociationService` verified 状态流转 + `sync_relations_from_operational`。
- 查询走 `graph_store` 遍历；可选只读接口挂 `server/knowledge/api/`。
</code_context>

<specifics>
## Specific Ideas

- 关键词/能力用边 metadata 承载，不建独立实体表（research §2.4）。
- RepoAssociation 是唯一真相源，图谱边单向派生（KDEP-08 硬约束）。
- 工件正文路由召回质量需实测；无匹配则只保留 project 边（fail-soft，research §4）。
- 本阶段以「加边 + 同步 + 可查询」为主，重可视化留 Phase 99。
</specifics>

<deferred>
## Deferred Ideas

- 星图纳入 artifact 节点/边、知识实体图/详情展示关联、作战室交叉入口 → Phase 99。
- 关键词/能力升级为一等实体表（KDEPX-01）→ v2。
- 关联查询的富前端展示 → Phase 99。
</deferred>
