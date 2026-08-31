---
phase: 32-one-click-ingest
verified: 2026-06-15T11:55:00Z
status: human_needed
score: 12/12 must-haves verified
overrides_applied: 0
human_verification:

  - test: "用真实飞书项目加密凭证 + 真实 git platform 凭证，对真实 (看板URL, MR URL) 跑一次一键摄取"
    expected: "三步均 ok：WorkItem 经 upsert 落库、PRD/技术方案 Document + REFERENCES 边建立、MR diff 归档并入 RAG；该需求与关联文档/diff 可经现有检索/MCP 召回"
    why_human: "需真实飞书/git 平台凭证与活数据，自动化测试以 mock seam（mock_embedding/qdrant/git_platform）+ 实体/边/归档行存在为可测代理，无法替代端到端真实回源"

  - test: "在浏览器打开 /knowledge/ingest，提交两个 URL 并观察派发→2s 轮询→三步结果渲染"
    expected: "侧边栏「一键摄取」入口可达；表单校验、派发成功 toast、running spinner、2s 轮询、三步语义色结果（identifier/「查看」外链/error）、partial/完成提示视觉正确"
    why_human: "视觉外观、轮询实时行为、toast 与无障碍语义需人工目视确认，grep/单测只能验结构与文案不能验观感"
audit_acknowledged:
  milestone: v0.25.0
  at: 2026-08-31
  status: human_needed
---

# Phase 32: 一键摄取编排 Verification Report

**Phase Goal:** 给定 (看板URL, MR URL)，编排拉看板工作项（经 upsert）→ PRD/技术方案文档（建 REFERENCES）→ MR diff（既有 RAG），一次入库可检索；最小一键摄取 UI (`/knowledge/ingest`)。ING-01。纯编排既有能力。INV-1/3/6。
**Verified:** 2026-06-15T11:55:00Z
**Status:** human_needed
**Re-verification:** No — initial verification

## Goal Achievement

### Observable Truths

| #  | Truth | Status | Evidence |
| -- | ----- | ------ | -------- |
| 1 | (ROADMAP SC1) 解析看板 URL 拉工作项并经 `WorkItemService.upsert` 收敛入库 | ✓ VERIFIED | `ingest_orchestrator.py:108` 调 `WorkItemService().upsert(WorkItemIdentity, source="mr_reverse", fetch=True)`；`work_item_service.py:107` upsert 签名匹配；`parse_board_url` 产出三元组（`ingest_parsing.py:81`） |
| 2 | (ROADMAP SC2) 拉 PRD/技术方案文档建 REFERENCES + 拉 MR diff 入 RAG | ✓ VERIFIED | 步2 `await ingest(IngestionRequest("feishu_document", "{pk}:{wt}:{wid}", ...))`（line 152，复用 P30 normalizer 投影 document+REFERENCES）；步3 `archive_code_change(...)`（line 225）+ `ingest_events([code_change])`（line 281） |
| 3 | (ROADMAP SC3) 摄取后需求/文档/diff 可被检索召回 | ✓ VERIFIED | 编排经既有 ingestion/diff RAG 管线投影 knowledge 实体+边+归档行；测试以 KnowledgeEntity(work_item/document/code_change)+REFERENCES 边+CodeChangeArchive 行存在为可测代理（`test_ingest_orchestrator.py` 8 例全绿）。真实 Qdrant 召回 → human_needed |
| 4 | run 状态可持久化 (running/completed/failed) 按 run_id 查询 | ✓ VERIFIED | `IngestRun` 模型 Status TextChoices（`ingest_run.py:50`）+ UUID pk + `GET /delivery/ingest/{run_id}/` 回流 |
| 5 | 每个 IngestRun 携带三步结构化结果 (status/identifier/link/error) | ✓ VERIFIED | `default_steps()` 固定 {work_item,document,mr_diff}×{status,identifier,link,error}（line 29-39）；`_write_step` 逐步持久化 |
| 6 | 看板 URL 解析三元组；不可靠/容器型 → None 不崩 | ✓ VERIFIED | `parse_board_url` 返回 `BoardRef`/None，非飞书域/缺段/非数字 id 返回 None（test_ingest_parsing 26 例） |
| 7 | MR URL 解析并匹配已落库 Repository；无匹配 → None 不崩 | ✓ VERIFIED | `aresolve_repo_and_mr`（line 170）复用 git_platform helper 归一比对，无匹配 → None（SSRF 边界 T-32-01） |
| 8 | 三步 best-effort 独立降级，逐步落 steps | ✓ VERIFIED | 每步独立 try/except + `_write_step` 即时 save（line 297-300）；编排级异常 → status=failed+脱敏 error |
| 9 | POST 立即返回 run_id(202)+后台执行；GET 回流真实步骤 | ✓ VERIFIED | `IngestDispatchView.post` → `run_in_background` + 202（views.py:247-254）；`IngestRunDetailView.get` 回流/404 |
| 10 | /knowledge/ingest 可访问 + 侧边栏入口 | ✓ VERIFIED | `pages/knowledge/ingest.vue`（file-based route）+ `AppSidebar.vue:86` `{ to: '/knowledge/ingest', '一键摄取' }` |
| 11 | 表单两 URL + CTA；空/非 http(s) 内联校验不发请求 | ✓ VERIFIED | `IngestPanel.vue` `validateUrl` + `onSubmit` 校验失败 return 不 dispatch（line 48-58）；spec 用例 (b) 守护 |
| 12 | 合法提交 dispatch→2s 轮询；三步语义色 + partial/完成提示 | ✓ VERIFIED | `useMutation(dispatch)` + `useQuery(getRun)` `refetchInterval` 2s/running（line 76）；固定三行 StepRow + allOk/isPartial 提示；spec 5 例全绿 |

**Score:** 12/12 truths verified

### Required Artifacts

| Artifact | Expected | Status | Details |
| -------- | -------- | ------ | ------- |
| `server/delivery/models/ingest_run.py` | IngestRun 持久化模型 | ✓ VERIFIED | `class IngestRun` + `default_steps()`，Status/steps/project/error/时间戳 |
| `server/delivery/migrations/0008_ingestrun.py` | 建表迁移 | ✓ VERIFIED | CreateModel IngestRun，依赖 0007 + projects 0009；`makemigrations --check` = No changes |
| `server/delivery/services/ingest_parsing.py` | URL 解析 + Repo 匹配 | ✓ VERIFIED | `parse_board_url`/`parse_mr_url`/`aresolve_repo_and_mr` + 复用 git_platform helper |
| `server/delivery/services/ingest_orchestrator.py` | ingest_from_urls 三步编排 | ✓ VERIFIED | `async def ingest_from_urls` best-effort 三步 + 脱敏 error |
| `server/delivery/api/views.py` | dispatch + status 视图 | ✓ VERIFIED | `IngestDispatchView`/`IngestRunDetailView`，IsAuthenticated |
| `server/delivery/urls.py` | ingest 路由 | ✓ VERIFIED | `ingest/` + `ingest/<uuid:run_id>/`（字面段在通配前） |
| `web/src/api/ingest.ts` | ingestApi + 类型 | ✓ VERIFIED | `ingestApi.dispatch/getRun` + 5 类型，字段对齐后端 |
| `web/src/components/knowledge/IngestPanel.vue` | 表单+派发→轮询+三步 | ✓ VERIFIED | 完整实现，无 v-html，外链 rel=noopener |
| `web/src/pages/knowledge/ingest.vue` | 薄壳页 | ✓ VERIFIED | PageContainer + IngestPanel |

### Key Link Verification

| From | To | Via | Status | Details |
| ---- | -- | --- | ------ | ------- |
| ingest_orchestrator | work_item_service | `WorkItemService().upsert(...source="mr_reverse")` | ✓ WIRED | orchestrator.py:108 |
| ingest_orchestrator | knowledge.ingestion | `ingest(feishu_document)` + `ingest_events([code_change])` | ✓ WIRED | orchestrator.py:152, 281 |
| ingest_orchestrator | knowledge.diff_archive | `archive_code_change` + `aarchive_exists` | ✓ WIRED | orchestrator.py:225,239；diff_archive.py:517,529 |
| api/views | background_runner | `run_in_background(lambda: ingest_from_urls(...))` | ✓ WIRED | views.py:247 |
| IngestPanel.vue | api/ingest.ts | `ingestApi.dispatch` + `useQuery(getRun)` | ✓ WIRED | IngestPanel.vue:44,73 |
| api/index.ts | api/ingest.ts | `export * from './ingest'` | ✓ WIRED | index.ts:18 |
| AppSidebar.vue | /knowledge/ingest | mainNavItems 导航项 | ✓ WIRED | AppSidebar.vue:86 |

### Behavioral Spot-Checks

| Behavior | Command | Result | Status |
| -------- | ------- | ------ | ------ |
| 后端 phase 测试（parsing/model/orchestrator/api） | `pytest tests/delivery/test_ingest_*` | 47 passed in 373.61s | ✓ PASS |
| 迁移无漂移 | `manage.py makemigrations --check --dry-run` | No changes detected (exit 0) | ✓ PASS |
| 前端守护测试 | `pnpm vitest run .../IngestPanel.spec.ts` | 5 passed | ✓ PASS |

### Requirements Coverage

| Requirement | Source Plan | Description | Status | Evidence |
| ----------- | ----------- | ----------- | ------ | -------- |
| ING-01 | 32-01/02/03 | 给定 (看板URL, MR URL) 拉工作项+文档+MR diff 并入库可检索 | ✓ SATISFIED | 三步编排 + REST + UI 全部落地并测试通过；REQUIREMENTS.md 已标 Complete |

### Anti-Patterns Found

| File | Line | Pattern | Severity | Impact |
| ---- | ---- | ------- | -------- | ------ |
| — | — | 无 TBD/FIXME/XXX/v-html/stub | — | delivery/*.py 与 IngestPanel.vue 均无债务标记或占位实现 |

### Human Verification Required

1. **真实凭证端到端摄取** — 用真实飞书 + git platform 凭证对真实 (看板URL, MR URL) 跑一次，确认三步 ok 且需求/文档/diff 可经真实检索/MCP 召回。自动化以 mock seam + 实体/边/归档行存在为可测代理，无法替代真实回源。
2. **可视化 UI 确认** — 浏览器打开 `/knowledge/ingest`，目视确认侧边栏入口、派发 toast、2s 轮询、三步语义色结果与 partial/完成提示的观感与无障碍语义。

### Gaps Summary

无阻断性缺口。Phase 32 的全部 12 条可观察真相均在代码中验证落地，47 个后端测试 + 5 个前端测试全绿，迁移无漂移，无债务标记/占位实现。INV-3（delivery 不引用 knowledge 模型，读访问收口为 `aarchive_exists`）、INV-6（落库经 `upsert`/`ingest`/`ingest_events`/`archive_code_change` 单一入口）、SSRF 边界（MR 必须匹配已落库 Repository）、T-32-02 脱敏均到位。

剩余两项（真实凭证端到端摄取、可视化 UI 确认）按指示归为 human-UAT，不计为 gaps。

---

_Verified: 2026-06-15T11:55:00Z_
_Verifier: Claude (gsd-verifier)_
