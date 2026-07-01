---
phase: 96-external-deps-search-overview
reviewed: 2026-07-01T09:21:48Z
depth: deep
files_reviewed: 13
files_reviewed_list:
  - server/knowledge/ingestion.py
  - server/knowledge/sources/artifact.py
  - server/initiatives/services/artifact_service.py
  - server/knowledge/retrieval_types.py
  - server/knowledge/metadata_hydrate.py
  - server/knowledge/exposure.py
  - server/knowledge/api/views.py
  - server/knowledge/api/artifact_overview.py
  - server/knowledge/api/urls.py
  - web/src/api/knowledge.ts
  - web/src/pages/knowledge/index.vue
  - web/src/components/knowledge/KnowledgeDashboard.vue
  - web/src/locales/zh-CN.json
findings:
  blocker: 0
  high: 0
  medium: 3
  low: 4
  info: 3
  total: 10
status: clean
---

# Phase 96: 外部依赖进检索与总览 — Code Review Report

**Reviewed:** 2026-07-01T09:21:48Z
**Depth:** deep（跨文件调用链 + 权限收口追踪）
**Files Reviewed:** 13
**Status:** clean（无 BLOCKER / HIGH；含 3 MEDIUM / 4 LOW / 3 INFO）

## Summary

Phase 96 把「全类型工件登记为可发现实体（含非 ragable 元数据-only 摄取）」「搜索召回纳入工件 + 类型/项目元数据补全」「交付文档聚合接口 + 前端总览区块」三条链打通。整体质量高：

- **安全核心诉求全部通过**。重点关注的「跨项目工件泄漏」不存在——`/api/knowledge/artifacts/overview/` 走 `IsAuthenticated` + `resolve_allowed_project_ids` fail-closed，聚合仅 `project__space_id__in=allowed`；`allowed` 为空时零 DB 查询直接返回空结构。搜索侧 `include_document_kind=True` 不放宽权限闸（`recall_similar_chunks` 在 `allowed_project_ids` 为空时零 Qdrant 调用）。查询参数 `type_key` / `limit` 经 ORM 参数化 + clamp，无注入面。
- **幂等性成立**。非 ragable 工件的 `entity_id = generate_entity_id(DOCUMENT, "artifact", artifact_id)` 按 artifact_id 确定性派生；`content_hash` 由 title/type/carrier/url 拼接派生，重复 create/update 命中 pre-embed 短路（`vector_synced=True` → skipped），天然幂等。
- **N+1 已规避（工件富化部分）**。`metadata_hydrate.hydrate_many` 批量收集 `type_key`/`project_id` 后经 `_resolve_artifact_maps` 一次性解析映射；`artifact_overview._aggregate` 的 items 走 `select_related("type", "project")`。
- **观测基本合规**。`started/completed/failed` + `duration_ms` + `category`/`component` 齐备，best-effort 吞异常不反噬主流程。

主要遗留集中在前端总览的两个功能耦合缺陷（M1/M2）与一个预存在的权限 id 语义错配（M3，根因在 Phase 96 范围外的 `access_scope.py`，且为「少召回」的 fail-closed 方向，非泄漏）。这些均不构成 BLOCKER/HIGH，故 `status: clean`。

## Narrative Findings (AI reviewer)

---

### Medium

#### MED-01: `dep_type` 预筛参数被推送但从未被消费（承诺的类型预筛静默失效）

**File:** `web/src/components/knowledge/KnowledgeDashboard.vue:278-281`，`web/src/pages/knowledge/index.vue:50-59`
**Issue:** 类型磁贴点击调用 `goToDepType(typeKey)`：

```ts
function goToDepType(typeKey: string) {
  router.push({ query: { tab: 'search', dep_type: typeKey } })
}
```

注释声称「跳搜索 Tab 预筛该类型（?dep_type= 预填，供搜索侧消费）」，但 `index.vue` 仅 `watch(() => route.query.tab, ...)`，从不读取 `route.query.dep_type`；`searchDeliveryKnowledge()` 也没有类型过滤参数。结果：点击类型磁贴只切到搜索 Tab，搜索框空、无任何预筛/自动检索，与文案承诺不符。
**Fix:** 二选一——（a）在搜索 Tab 消费 `route.query.dep_type`（预填搜索或加类型 facet 过滤，需后端/前端补类型过滤能力）；（b）若本期不做预筛，移除 `dep_type` 参数与误导性注释，改为纯 `emit('navigate', 'search')` 或直接跳到该类型的说明。

#### MED-02: 交付文档区块被 `isEmpty`（仓库为空）连坐隐藏——无仓库但有工件的工作区看不到新功能

**File:** `web/src/components/knowledge/KnowledgeDashboard.vue:307,316,591`
**Issue:** `isEmpty = !isLoading && repos.value.length === 0`（基于 `getKnowledgeTree()` 的仓库数）。整段交付文档区块（line 591）位于 `<template v-else>`（line 316）之内，即「非 loading 且非 isEmpty」才渲染。因此当工作区**有工件但无已纳管/索引仓库**时，`isEmpty` 为 true，整个 Dashboard 落到全局空态（line 307），交付文档总览区块完全不渲染——即便 `overviewQuery` 已返回非空数据。交付文档与代码仓库彼此独立，不应被仓库存在性连坐。
**Fix:** 将交付文档区块从 `repos` 驱动的 `isEmpty` 解耦。例如把该 `<section>` 提到 `v-else` 之外、以自身 `depLoading`/`depEmpty`/`depTotal` 独立控制显隐；或在全局空态分支内也渲染 deps 区块（`v-if="!isLoading && (repos.length || depTotal)"`）。

#### MED-03: public_org 工件对非成员在总览中不可见（access_scope 混用 Space id 与 initiatives.Project id）；overview docstring 描述与实现不符

**File:** `server/knowledge/api/artifact_overview.py:7-8,53`；根因 `server/knowledge/access_scope.py:21-30,47-54`
**Issue:** `resolve_allowed_project_ids` 返回的 `allowed` 集合语义不一致：

- membership 分支：`PermissionService.get_user_projects(user)` 返回 `QuerySet[Space]` → `.values_list("id")` 是 **Space id**；
- public_org 分支：`_public_org_project_ids()` 查 `initiatives.models.Project.filter(visibility=PUBLIC_ORG).values_list("id")` → 是 **initiatives.Project id**。

overview 聚合按 `Artifact.objects.filter(project__space_id__in=allowed)` 过滤（`project.space_id` 是 Space id）。membership 的 Space id 能命中（正确）；但 public_org 并入的是 Project id（与随机 UUID 的 Space id 不可能相等），因此**非成员用户看不到本应「全员可读」的 public_org 项目工件**。同一错配也影响向量召回（Qdrant payload 的 `project_id` 实为 Space id）。方向为「少召回 / fail-closed」，**不构成泄漏**，但属功能正确性缺陷；且 `artifact_overview.py` docstring 断言「resolve_allowed_project_ids 返回可见 Space id（membership ∪ public_org）」与实现不符（public_org 段返回的是 Project id）。
**Note:** 根因位于 Phase 96 文件范围外的 `access_scope.py`（Phase 15 / WS-02 引入），本条按「新端点直接依赖且 docstring 明确背书了错误行为」纳入。
**Fix:** 让 `_public_org_project_ids()` 返回 public_org 项目对应的 **Space id**（`Project.filter(visibility=PUBLIC_ORG).values_list("space_id", flat=True)`），使并入集合与 membership 同为 Space id；同步修正 overview docstring。（属跨相位改动，建议单独 issue 跟踪。）

---

### Low

#### LOW-01: 飞书正文拉取失败日志 `error=str(exc)` 未过 `redact_secrets_in_text`（上游异常文本可能夹带 token/URL）

**File:** `server/knowledge/sources/artifact.py:138-146,157-165`
**Issue:** `_fetch_body` 对飞书 doc/bitable 拉取失败记 `error=str(exc)`，未经 `redact_secrets_in_text` 手动脱敏。项目强制规范（`.cursor/rules/observability-logging.mdc`）要求「上游响应体/异常文本手动用 `redact_secrets_in_text`」。飞书客户端异常消息可能内嵌带 token 的 URL。自动 processor `redact_credentials` 可兜底常见凭证形态，且该 `error=str(exc)` 写法在全仓普遍存在，故降为 LOW。
**Fix:**
```python
from common.logging import redact_secrets_in_text
logger.warning("artifact_rag_doc_fetch_failed", ..., error=redact_secrets_in_text(str(exc)))
```

#### LOW-02: `icon-[lucide--table]`（feishu_bitable）未纳入 `main.css` safelist，动态拼接类可能不生成

**File:** `web/src/components/knowledge/KnowledgeDashboard.vue:269`（`DEP_CARRIER_ICON.feishu_bitable = 'lucide--table'`）
**Issue:** 图标类以 `:class="`icon-[${depCarrierIcon(...)}]`"` 动态拼接。`web/src/styles/main.css` 通过 `@source inline(...)` 手动 safelist 动态图标，但**缺 `icon-[lucide--table]`**（`file-text`/`external-link`/`file-code`/`file` 均已在列）。Tailwind v4 + `@iconify/tailwind4` 不会为运行时拼接、源码中无字面量的类生成样式，feishu_bitable 的类型磁贴/条目将无图标。此为与 `DependenciesSection.vue:149`、`ArtifactsTab.vue:48` 共享的**预存在 safelist 缺口**，Phase 96 新 UI 继承之。
**Fix:** 在 `main.css` 的 `@source inline(...)` 增补 `icon-[lucide--table]`。

#### LOW-03: 前端 `ArtifactOverviewItem.updated_at` 类型不可空，后端可返回 `null`

**File:** `web/src/api/knowledge.ts:90` vs `server/knowledge/api/artifact_overview.py:88`
**Issue:** 后端 `"updated_at": a.updated_at.isoformat() if a.updated_at else None` 可能返回 `null`；TS 接口声明 `updated_at: string`（非空）。类型契约不严；虽然 `updated_at` 为 `auto_now` 实际几乎恒有值，但 DTO 允许 null。
**Fix:** `updated_at: string | null`（或后端保证非空）。

#### LOW-04: `artifact_overview_failed` warning 缺 `duration_ms`，与 started/completed 观测不一致

**File:** `server/knowledge/api/artifact_overview.py:136-142`
**Issue:** `completed` 分支带 `duration_ms`，`failed` 分支未带，关键生命周期时延观测不完整。
**Fix:** 在 `artifact_overview_failed` 补 `duration_ms=round((time.perf_counter() - started) * 1000, 2)`。

---

### Info

#### INF-01: 预存在失败，明确 out-of-scope（与 `deferred-items.md` 一致）

- `tests/initiatives/test_artifact_inv6_guard.py::test_inv6_no_bypass_artifact_write`：guard 的 grep 扫到 `delivery` app 同名 `Artifact`（与 `initiatives.Artifact` 无关），干净树同样失败。
- `knowledge/ingestion.py` 预存在 `ruff I001`（import 块排序，位于本相位未改动的 import 段）。
两者均为预存在、非 Phase 96 引入，不在本相位修复。

#### INF-02: 仅 `artifact.version` 变更（title/url/carrier 不变）时知识版本 `payload.version` 会滞后

**File:** `server/knowledge/sources/artifact.py:218-226` + `server/initiatives/services/artifact_service.py:323-331`
**Issue:** 元数据-only content 文本不含 `version`，故仅 version 递增不改变 `content_hash` → 命中 skipped、不产生新知识版本 → 知识侧 `payload.version` 保留旧值。对总览无影响（总览直读 `initiatives.Artifact`，不读知识 payload），仅为知识 payload 内元数据轻微陈旧。可接受。

#### INF-03: `hydrate_many` 仍存在与工件无关的逐版本查询（预存在 N+1）

**File:** `server/knowledge/metadata_hydrate.py:79-113,205-227`
**Issue:** `_build_provenance`（CODE_CHANGE 的 `CodeChangeArchive.filter().first()`）与 `_superseded_hint` 在每个 key 的 `sync_to_async(_build_one)` 内逐版本查询，构成预存在 N+1。**本相位新增的工件类型/项目名映射解析已正确批量化**（`_resolve_artifact_maps` 单次），故工件富化本身无 N+1。逐版本 provenance/superseded 查询属 Phase 15 既有实现，out-of-scope。

---

_Reviewed: 2026-07-01T09:21:48Z_
_Reviewer: Claude (gsd-code-reviewer)_
_Depth: deep_
