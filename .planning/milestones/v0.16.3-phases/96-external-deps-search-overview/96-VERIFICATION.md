---
phase: 96-external-deps-search-overview
verified: 2026-07-01T09:13:48Z
status: human_needed
score: 3/3 must-haves verified
overrides_applied: 0
human_verification:

  - test: "在配置了 Qdrant 的运行环境执行 /knowledge 搜索，输入 ragable 工件正文关键词，确认工件命中并显示类型徽标；输入非 ragable（UI 稿）的标题/类型关键词，确认元数据关键词层可命中（召回弱属预期）。"
    expected: "ragable 工件走向量 hybrid 召回命中；非 ragable 至少靠 title/type/url 元数据关键词兜底命中；结果项带类型徽标 + 所属项目名 + 一键查看/打开外链。"
    why_human: "本地测试环境 --disable-socket 无 Qdrant，无法真跑向量 hybrid 召回；召回质量需真实向量库环境验证。"

  - test: "浏览器打开 /knowledge?tab=overview，检查「交付文档 / 外部依赖」区块：类型计数磁贴、区块内即时搜索、空态、加载骨架、与仓库/域指标区块的视觉一致性。"
    expected: "区块与现有指标区块并列、风格一致；有数据显示类型计数磁贴 + 条目列表；无数据显示优雅空态（非空网格）；加载显示骨架。"
    why_human: "视觉呈现、风格一致性与空/加载态需人工目视确认，grep/类型检查无法覆盖。"

  - test: "浏览器在搜索结果命中工件项点击「查看」（feishu_doc/markdown 载体）与「打开外链」（external_link 载体）。"
    expected: "文字载体弹出 markdown 渲染查看弹窗；external_link 在新标签打开（rel=noopener noreferrer）。"
    why_human: "弹窗渲染、新标签打开为运行时 UI 行为，需人工交互验证。"
audit_acknowledged:
  milestone: v0.25.0
  at: 2026-08-31
  status: human_needed
---

# Phase 96: 外部依赖进检索与总览 Verification Report

**Phase Goal:** 让全部类型的外部依赖工件都能在知识体系里被发现——搜索能命中并标注类型、一键跳查看，知识总览把「交付文档/外部依赖」纳入大盘统计与入口。
**Verified:** 2026-07-01T09:13:48Z
**Status:** human_needed
**Re-verification:** No — initial verification

## Goal Achievement

### Observable Truths

| # | Truth | Status | Evidence |
| --- | ------- | ---------- | -------------- |
| 1 (KDEP-01) | 所有 `ArtifactType`（含非 ragable UI 稿）在知识体系登记为可发现条目：ragable 走向量摄取；非 ragable 登记 title/type/url 进可搜索层，无类型遗漏 | ✓ VERIFIED | `artifact_service.py:368-394` `_maybe_schedule_ingestion` 移除 `_should_ingest` 预筛，对全部工件调 `aschedule_ingestion(source_kind="artifact")`；`sources/artifact.py:202` `vectorize = ragable and carrier in TEXT_CARRIERS`，非 ragable 分支（`:215-248`）仍产 `IngestionEvent`（`KnowledgeEntity(kind=document)` + `REFERENCES→project` 边，携 title/type/carrier/url payload）但 `vectorize=False`；`ingestion.py:216/253/293/562-574` 非 vectorize 时跳过 collection 自检/chunk/embed、`qdrant_point_ids=[]`、`toc_tree=[]`、`vector_synced=True`（零 Qdrant 向量）。测试 `test_artifact_source.py::test_graphic_artifact_metadata_only_registered` 通过 |
| 2 (KDEP-02) | `/knowledge` 搜索命中工件时标注类型 + 一键跳查看，跨项目按 `access_scope` 过滤 | ✓ VERIFIED | 后端：`api/views.py:107` `include_document_kind=True` 启用 document 召回（权限不放宽，仍受 `allowed_project_ids/allowed_repository_ids` 收口）；`retrieval_types.py:55` `EntityMetadata.artifact`；`metadata_hydrate.py:15/42/182-206` 批量 `_resolve_artifact_maps` + `_build_artifact_meta`（避免 N+1）；`exposure.py:97-99` `serialize_search_result` 输出 `origin/source_kind/artifact`。前端：`pages/knowledge/index.vue:255-304` 工件类型徽标 + 所属项目名 + external_link 新标签打开 / 其余 `openArtifactView` 弹窗（`:121-129` 调 `artifactsApi.view`）。测试 `test_knowledge_api.py::test_search_artifact_hit_carries_metadata`、`test_search_non_member_no_visible_artifacts` 通过 |
| 3 (KDEP-03) | `KnowledgeDashboard` 新增「交付文档/外部依赖」区块（类型计数 + 入口 + 即时搜索），风格一致 | ✓ VERIFIED | 后端：`api/artifact_overview.py:101-154` `ArtifactOverviewView`（access_scope fail-closed、SQL annotate 计数、`_ITEM_LIMIT=500` 截断、best-effort 不 500）；`api/urls.py:16` 路由 `artifacts/overview/`。前端：`KnowledgeDashboard.vue:242-284` `overviewQuery`/`depTypes`/`depItems`/`goToDepType`/`openDepItem`，`:593-671` 区块 header + 计数磁贴 + 即时搜索 + `CompactEmptyState` 空态 + truncated 提示；`api/knowledge.ts:147-158` `getArtifactOverview`。测试 `test_artifact_overview_api.py`（3 用例）通过 |

**Score:** 3/3 truths verified

### Required Artifacts

| Artifact | Expected | Status | Details |
| -------- | ----------- | ------ | ------- |
| `server/knowledge/ingestion.py` | `IngestionEvent.vectorize` 开关 + 元数据-only 分支 | ✓ VERIFIED | `:115` 字段；`:216/253/293/562-574` 分支（跳过 collection/chunk/embed，空点/树，vector_synced=True，旧点 tombstone 清理） |
| `server/knowledge/sources/artifact.py` | 非 ragable → vectorize=False 事件（实体+边，无向量） | ✓ VERIFIED | `:202` vectorize 判定；`:215-248` 元数据文本 + REFERENCES 边 + `vectorize=vectorize`。（注：`:171` 函数级 docstring 残留旧句「非 ragable 返回空」与实现不符，仅注释瑕疵，见 Anti-Patterns） |
| `server/initiatives/services/artifact_service.py` | 全类型工件调度摄取 | ✓ VERIFIED | `:368-394` 全类型调度，无预筛；`artifact_rag_scheduled` 补 `ragable` 字段 |
| `server/knowledge/retrieval_types.py` | `EntityMetadata.artifact` | ✓ VERIFIED | `:55` `artifact: dict | None = None` |
| `server/knowledge/metadata_hydrate.py` | 批量补全工件元数据 | ✓ VERIFIED | `:15/42` helper；`:182-206` `hydrate_many` 批量解析 |
| `server/knowledge/exposure.py` | 序列化输出 origin/source_kind/artifact | ✓ VERIFIED | `:97-99` |
| `server/knowledge/api/views.py` | 搜索启用 document 召回 | ✓ VERIFIED | `:107` `include_document_kind=True` |
| `server/knowledge/api/artifact_overview.py` | 聚合接口（access_scope + 类型分组计数） | ✓ VERIFIED | 新建，154 行，实质实现 |
| `server/knowledge/api/urls.py` | `/api/knowledge/artifacts/overview/` 路由 | ✓ VERIFIED | `:16` |
| `web/src/api/knowledge.ts` | `getArtifactOverview` + 搜索工件字段类型 | ✓ VERIFIED | `:48/67-69/81-96/147-158` |
| `web/src/pages/knowledge/index.vue` | 搜索结果徽标 + 一键查看 | ✓ VERIFIED | `:117-129/255-304` |
| `web/src/components/knowledge/KnowledgeDashboard.vue` | 交付文档区块 | ✓ VERIFIED | `:242-284/593-671` |
| `web/src/locales/zh-CN.json` | 新增文案键 | ✓ VERIFIED | `knowledge.search.{owningProject,view,openExternal}`、`knowledge.overview.deps.*` |

### Key Link Verification

| From | To | Via | Status | Details |
| ---- | --- | --- | ------ | ------- |
| `ArtifactService._maybe_schedule_ingestion` | `knowledge.ingestion.aschedule_ingestion` | `source_kind="artifact"` | ✓ WIRED | `artifact_service.py:389` |
| `sources/artifact.normalize` | `KnowledgeEntity(document)` + `REFERENCES` 边 | `IngestionEvent(edges=…, vectorize=…)` | ✓ WIRED | `artifact.py:228-248` |
| `KnowledgeSearchView` | hydrate → serialize | `include_document_kind=True` → `serialize_search_result` | ✓ WIRED | `views.py:107` → `exposure.py:97-99` |
| `KnowledgeDashboard.vue` | `GET /knowledge/artifacts/overview/` | `knowledgeApi.getArtifactOverview` | ✓ WIRED | `KnowledgeDashboard.vue:244` → `knowledge.ts:147-158` |
| `index.vue` 搜索结果 | `artifactsApi.view` | `openArtifactView(item)` | ✓ WIRED | `index.vue:121-129/304` |

### Data-Flow Trace (Level 4)

| Artifact | Data Variable | Source | Produces Real Data | Status |
| -------- | ------------- | ------ | ------------------ | ------ |
| `KnowledgeDashboard.vue` 区块 | `depTypes/depItems` | `overviewQuery` → `/knowledge/artifacts/overview/` → `_aggregate` SQL `annotate(Count)` + `Artifact` 查询 | ✓（真实 PG 聚合，非静态） | ✓ FLOWING |
| `index.vue` 搜索结果 `item.artifact` | `artifact` 元数据 | `hydrate_many` → DB `ArtifactType/Project` 批量解析 | ✓（真实 DB hydrate） | ✓ FLOWING |

### Behavioral Spot-Checks

| Behavior | Command | Result | Status |
| -------- | ------- | ------ | ------ |
| 后端 knowledge 测试 | `uv run pytest tests/knowledge -q` | 331 passed, 3 failed（失败与本阶段无关，见下）, 1 deselected | ✓ PASS（本阶段范围内） |
| Phase 96 专项测试 | `uv run pytest test_artifact_source/test_artifact_overview_api/test_knowledge_api/test_exposure/test_ingestion/test_artifact_service -q` | **50 passed** | ✓ PASS |
| 前端类型检查 | `pnpm exec vue-tsc --noEmit` | exit 0，无错误 | ✓ PASS |

### Requirements Coverage

| Requirement | Source Plan | Description | Status | Evidence |
| ----------- | ---------- | ----------- | ------ | -------- |
| KDEP-01 | 96-01 | 全类型工件登记可发现（ragable 向量 / 非 ragable 元数据-only），无遗漏 | ✓ SATISFIED | Truth 1 |
| KDEP-02 | 96-02, 96-04 | 搜索命中标类型 + 一键查看，跨项目 access_scope 过滤 | ✓ SATISFIED | Truth 2 |
| KDEP-03 | 96-03, 96-05 | Dashboard「交付文档/外部依赖」区块（计数+入口+即时搜索） | ✓ SATISFIED | Truth 3 |

### Anti-Patterns Found

| File | Line | Pattern | Severity | Impact |
| ---- | ---- | ------- | -------- | ------ |
| `server/knowledge/sources/artifact.py` | 171 | `normalize` 函数级 docstring 残留旧句「非 ragable 返回空」，与新实现（非 ragable 产 `vectorize=False` 事件）不符 | ℹ️ Info | 仅注释瑕疵，模块级 docstring（`:7-10`）已正确描述新行为；不影响功能，建议后续顺手订正 |

无 🛑 Blocker / ⚠️ Warning 级反模式。未发现未引用的 `TBD/FIXME/XXX` 调试标记（`deferred-items.md` 记录的两项 `ruff I001` 与 INV-6 guard 失败均为预存在、非本阶段引入）。

### 与本阶段无关的预存在失败

`tests/knowledge/test_triggers.py` 3 个用例失败（`test_workflow_plan_generation_delivers_on_success` / `_zero_delivery_on_failure` / `_survives_runner_failure`），根因 `ModuleNotFoundError: No module named 'workflows.nodes.ai.plan_generation'`。该模块在早于 Phase 96 的重构提交 `83a0c349 refactor(workflow): 合并 ai_plan_approval 进 human_approval` 被合并/改名。Phase 96 的 5 个提交（`0b80c792`/`72fe40a6`/`c0b91c6d`/`5347df66`/`3aeb66b0`）未触碰任何 `workflows/` 文件，故与本阶段无关，属预存在失败，不计入本阶段 gap。

### Human Verification Required

以下项需真实运行环境 / 浏览器人工验证（deferred，不作失败）：

1. **真实 Qdrant 向量召回** — 在配置 Qdrant 的环境搜索 ragable 工件正文关键词确认向量 hybrid 命中；非 ragable 靠 title/type/url 元数据关键词层兜底命中（召回弱属预期）。本地测试 `--disable-socket` 无 Qdrant，无法真跑。
2. **Dashboard 区块视觉** — `/knowledge?tab=overview`「交付文档/外部依赖」区块的计数磁贴 / 即时搜索 / 空态 / 骨架 / 风格一致性目视确认。
3. **搜索结果一键查看/打开** — 文字载体弹 markdown 查看弹窗、external_link 新标签打开（运行时 UI 交互）。

### Gaps Summary

无阻断 gap。三条 Success Criteria（KDEP-01/02/03）均在代码中落地并有实质实现 + wiring + 真实数据流，Phase 96 专项 50 项自动化测试全绿、前端 `vue-tsc` 通过。仅存 1 处注释瑕疵（info 级）与 3 项需真实环境/浏览器的人工验证项（deferred）。由于存在人工验证项，按判定规则总体状态为 `human_needed` 而非 `passed`；无需 gap 修复即可推进后续阶段（Phase 97 依赖的登记/查看跳转已就绪）。

---

_Verified: 2026-07-01T09:13:48Z_
_Verifier: Claude (gsd-verifier)_
