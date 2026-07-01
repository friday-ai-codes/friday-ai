---
phase: 99-association-visualization-crosslink
reviewed: 2026-07-01T21:10:00Z
depth: deep
files_reviewed: 10
files_reviewed_list:
  - server/initiatives/views.py
  - server/initiatives/serializers.py
  - server/knowledge/api/repository_artifacts.py
  - server/knowledge/api/urls.py
  - web/src/api/knowledge.ts
  - web/src/api/artifacts.ts
  - web/src/api/projectGalaxy.ts
  - web/src/components/knowledge/EntityAssociationsCard.vue
  - web/src/pages/knowledge/entities/[id].vue
  - web/src/components/project/warroom/ProjectGalaxyCard.vue
  - web/src/components/project/workbench/DependenciesSection.vue
  - web/src/locales/zh-CN.json
findings:
  blocker: 0
  high: 0
  medium: 0
  low: 2
  info: 2
  total: 4
status: findings
---

# Phase 99: 关联可视化与交叉入口 — Code Review Report

**Reviewed:** 2026-07-01T21:10:00Z
**Depth:** deep（跨文件调用链 + STRIDE + 异步/可观测）
**Files Reviewed:** 10 源文件（+ locale/tests 校验）
**Status:** findings（无 BLOCKER / HIGH / MEDIUM；2 LOW + 2 INFO）

## Summary

Phase 99 在既有星图与知识实体详情之上叠加「工件/能力节点 + 双向可导航关联入口」，实现质量高，未发现阻断性缺陷。对照评审重点逐项核验结论：

- **Correctness（PASS）**：星图工件节点注入经末尾统一 `nodes[:max_nodes]` 截断，无无界增长；`USES_REPO` 在 MR 来源与 verified `RepoAssociation` 来源之间通过新增 `edge_seen (source,target,relation)` 集合去重，同 repo 仅一条边；工件/关联分支整体包裹于 `try/except`（`noqa: BLE001`）并只记 warning，异常绝不反噬既有 project/feature/work_item/MR/repo 星图；反查端点 `find_artifacts_by_repository` 返回结构正确并补确定性 `entity_id`；`generate_entity_id(DOCUMENT,"artifact",id)` 在 serializer / 反查端点 / `get_artifact_associations` 三处完全一致，符合 `models.py:92` locked 自然键规则（Phase 96/98）。
- **Security / STRIDE（PASS）**：星图入口 `_aget_project_for_read` 项目成员 fail-closed；`_agather_artifact_assocs` 逐工件走 `get_artifact_associations`（`resolve_allowed_project_ids` + space 校验），不可见工件返回 `None` 跳过；反查端点 `IsAuthenticated` + `resolve_allowed_repository_ids` + 二次 space 过滤（双维 fail-closed），越权返回空集不泄漏；异常/上游文本经 `redact_secrets_in_text` 脱敏，无凭证入日志；全链 READ-ONLY，未引入任何关联真值写入。
- **Observability（PASS）**：星图 `project_galaxy_built`（category=caller, component=initiatives.galaxy, +duration_ms, +artifact_nodes/edges）；best-effort 分支 `project_galaxy_artifact_branch_failed` / `_assoc_failed`（category=sampling）；反查端点 `repository_artifacts_api_started/completed`（category=caller, component=knowledge, +duration_ms）。事件名 snake_case、kv 字段规范。
- **Async（PASS）**：`_agather_artifact_assocs` 全程 await 异步 service，唯一 ORM 访问包在 `sync_to_async` lambda；`_build_project_galaxy`（含 `Artifact` / `RepoAssociation` 同步 ORM）经 `sync_to_async` 包裹调用——异步上下文内无裸同步 ORM。
- **Frontend（PASS，含 2 处 LOW）**：类型齐备（`ArtifactAssociations` / `RepositoryArtifact`），loading/error/empty 三态完整，i18n zh-CN 全部新键存在，节点色 `#f59e0b`/`#ec4899` 走 force-graph 十六进制（无需 safelist），`icon-[lucide--brain]` / `bg-amber-500/10` 等均为字面量完整 class 命中扫描，RouterLink 目标路由 `/repositories/[id]`、`/knowledge/entities/[id]` 均存在。

## Blocker Issues

无。

## High Issues

无。

## Medium Issues

无。

## Low

### LOW-01: 反查文档图标用 `type_key` 查 carrier 图标表，恒回退默认图标

**File:** `web/src/components/knowledge/EntityAssociationsCard.vue:164`（配合 `:33` `CARRIER_ICON`）
**Issue:** 反向分支渲染相关交付文档时用 `carrierIcon(doc.type_key)` 取图标，但 `CARRIER_ICON` 以**载体**（`feishu_doc`/`markdown`/`repo_file`…）为键，而 `RepositoryArtifact`（`web/src/api/knowledge.ts:152`）与后端 `_hydrate_artifacts`（`server/knowledge/artifact_associations.py:308`）返回的是**工件类型 key**（如 `prototype`/`spec`），二者语义域不同。结果：反查文档条目图标恒命中 `?? 'icon-[lucide--file]'` 兜底，永远显示同一个通用文件图标，与正向/工作台按载体区分图标的视觉一致性不符。纯展示缺陷，不崩溃、不影响导航。
**Fix:** 二选一——(a) 后端反查行补 `carrier` 字段（`_hydrate_artifacts` 增 `"carrier": a.carrier`，`RepositoryArtifact` 加 `carrier: ArtifactCarrier`，前端改 `carrierIcon(doc.carrier)`）；(b) 若无需按载体区分，反查分支直接用固定文档图标（如 `icon-[lucide--file-text]`），移除对 `type_key` 的误用调用。

### LOW-02: 仓库节点跨三来源去重依赖 repository id 字符串格式完全一致

**File:** `server/initiatives/views.py:1789-1836`
**Issue:** 仓库节点 id 由三处拼装——MR 来源 `f"repository:{mr.repository_id}"`、`RepoAssociation` 来源 `f"repository:{repo.id}"`、工件关联来源 `f"repository:{rid}"`（`rid` 来自 `KnowledgeEntity.source_id`）。`add_node`/`add_edge` 的去重完全依赖这三处产出**逐字符相同**的字符串。当前三者均为 UUID 的 `str()` 表示，一致；但 `source_id` 是 `CharField`，一旦上游写入格式漂移（大小写/带 dash 与否/前缀），将产生重复仓库节点与重复 `ARTIFACT_REPO`/`USES_REPO` 边。属健壮性隐患，非当前缺陷。
**Fix:** 可在 `add_node` 内对 repository id 归一化（如统一 `str(uuid.UUID(rid))`），或在契约测试中显式断言三来源 repo id 同源同格式，锁死不变量。

## Info

### IN-01: 未使用的 i18n 键 `knowledge.entity.associations.title`

**File:** `web/src/locales/zh-CN.json:381`
**Issue:** 新增 `associations.title: "关联"` 未被任何组件引用（区块标题走 `knowledge.entity.sections.associations`，卡片内小标题走各自子键）。全仓 grep 无命中，属死键。
**Fix:** 删除该键，或若计划用于卡片主标题则在 `EntityAssociationsCard.vue` 接入。

### IN-02: `_agather_artifact_assocs` 逐工件 N+1 异步关联查询

**File:** `server/initiatives/views.py:1885-1892`
**Issue:** 对项目内每个工件各发一次 `get_artifact_associations`（内含实体查询 + `graph_store.neighbors` + repo 标题补全），大项目工件数多时星图接口延迟随工件数线性增长。性能问题属 v1 out-of-scope，仅记录。
**Fix:**（可选，后续优化）批量化：一次性取项目全部工件 document 实体的 `RELATES_TO` 出边聚合，替代逐工件单跳；或对星图工件关联做上限/采样。

---

_Reviewed: 2026-07-01T21:10:00Z_
_Reviewer: Claude (gsd-code-reviewer)_
_Depth: deep_
