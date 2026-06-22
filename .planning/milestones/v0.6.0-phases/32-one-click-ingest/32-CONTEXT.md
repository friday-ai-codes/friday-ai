# Phase 32: 一键摄取编排 - Context

**Gathered:** 2026-06-15
**Status:** Ready for planning
**Mode:** Smart discuss (autonomous — recommendations auto-accepted)

<domain>
## Phase Boundary

给定 (看板URL, MR URL)，编排：解析看板 URL 拉取工作项（经 `WorkItemService.upsert`）→ PRD/技术方案文档（经 `feishu_document` normalizer 建 `REFERENCES` 边）→ MR diff（经既有 `archive_code_change` RAG）一次入库可检索。配一个最小一键摄取 UI（输入两个 URL → 触发编排 → 展示进度/结果）。

覆盖需求：ING-01（给定 (看板URL, MR URL) → 拉看板工作项 + PRD/技术方案文档 + MR diff 并入库可检索）。
依赖：Phase 28（WorkItem upsert）、Phase 30（Document/REFERENCES + feishu_document normalizer）、既有 MR diff RAG（`CodeChangeArchive` / `archive_code_change`）。
不变量：INV-1/INV-6（工作项经 upsert 收敛）、INV-3（knowledge 投影；操作态经各自 service）。
本 phase 是**编排既有能力**——不新建底层摄取机制，把 P28/P30/既有 diff RAG 串成一次动作。
**Frontend phase（UI hint: yes）**：含最小一键摄取 UI。
</domain>

<decisions>
## Implementation Decisions

### 编排服务（Grey Area 1，ING-01 核心）
- 新增编排入口（如 `server/delivery/services/ingest_orchestrator.py` 的 `ingest_from_urls(board_url, mr_url, *, project=None)`），串联三步、each best-effort 独立降级（任一步失败不阻断其余 + 结构化结果汇总，沿用 §1.4 / normalizer 降级范式）：
  1. **看板工作项**：解析 board URL → (project_key/simple_name, work_item_type, work_item_id) → 解析 Project → `WorkItemService.upsert(identity, source="mr_reverse" 或 "manual", fetch=True)`（Phase 28 单一入口，INV-6）。
  2. **文档**：经 Phase 30 `feishu_document` normalizer 摄取该 work item 的 PRD/技术方案 → Document + `REFERENCES` 边（复用既有 ingestion 管线，不重写）。
  3. **MR diff**：解析 MR URL → 经既有 `archive_code_change`（DiffArchiver）拉 diff 入 `CodeChangeArchive` RAG（既有能力，复用 `get_git_platform_client` + diff 归档）。
- 返回结构化结果：每步 status（ok/failed/skipped）+ 关联 work_item / document / archive 标识 + error，供 UI 展示与 SyncState 记录。
- 触发方式：经 background runner 后台执行（沿用 webhook/upsert 后台范式），REST 立即返回 run 标识 + 后续状态查询（避免请求阻塞，长摄取异步）。

### URL 解析（Grey Area 2）
- 看板/工作项 URL：飞书 `https://project.feishu.cn/{simple_name}/{url_type}/detail/{id}` 模式 → 取 `simple_name`（解析 Project.feishu_project_simple_name / project_key）+ `id`；`work_item_type` 取材策略——优先用既有可靠来源（若 URL type 段不可靠/容器型则降级，**容器型工作项 out of scope**，PF-09 实测 URL 段 ≠ API type）。复用既有 URL 解析 helper（`work_item_context_service` 的 doc ref 提取 / feishu_work_item 的 token 提取范式）。
- MR URL：GitLab/GitHub MR/PR URL → (repo, mr_iid) → 经既有 git platform client 解析（`get_git_platform_client` + repo 匹配，复用 26/diff 既有路径）。
- 解析失败：该步 skipped + 明确 error，不崩，不阻断其余步骤。

### 检索可见（Grey Area 3，ING-01 成功标准 3）
- 摄取完成后：work item（经 upsert + knowledge 投影）、关联文档（Document + REFERENCES + knowledge document 实体）、MR diff（CodeChangeArchive + MODIFIES_CHUNK）均落库且**可被既有检索召回**（复用既有 search_rag / knowledge 检索面，不新建检索）。
- 可测：摄取后断言 WorkItem 落库、Document + REFERENCES 边存在、CodeChangeArchive 存在；经既有检索入口能召回该需求/文档/diff。

### 一键摄取 UI（Grey Area 4，frontend）
- 最小 UI（Vue 3 + TS + Tailwind + reka-ui，沿用 web/ 既有约定）：一个表单页/面板，输入「看板 URL」+「MR URL」→ 提交触发 `ingest_from_urls` → 展示三步进度/结果（工作项 / 文档 / MR diff 各自 ok/failed/skipped + 链接/标识）。
- 经既有 API client（`web/src/api/`）+ TanStack Query 轮询摄取状态（沿用既有派发→轮询范式，如 reconcile/cleanup 面板）。
- i18n 默认中文（vue-i18n），守护测试以真实 zh-CN.json 断言关键文案。
- UI 设计契约由 gsd-ui-phase 产出 UI-SPEC（本 phase frontend）。

### 异步 / 测试（Claude's Discretion 范围内）
- async-first；ORM `sync_to_async`；后台 run_in_background；httpx async。
- 后端测试：pytest-django + factory-boy + respx（mock 飞书/git platform）+ pytest-socket。守护：① 给定 (board, mr) URL 编排三步各自落库（WorkItem upsert / Document+REFERENCES / CodeChangeArchive）；② 任一步失败降级不阻断其余 + 结构化结果；③ URL 解析失败 skipped 不崩；④ 摄取后可检索召回。
- 前端测试：vitest + @vue/test-utils + happy-dom；守护表单提交 + 状态渲染 + i18n 文案。

### Claude's Discretion
- 编排服务文件/命名、REST 端点形状（同步 vs 异步 run + 状态查询）、work_item upsert 的 source 取值（mr_reverse vs manual）、UI 落点页面路径、状态轮询间隔 —— 由实现按既有约定决定。
- work_item_type 在 URL 不可靠时的取材兜底（如先 upsert 占位再补全，或要求用户提供）—— 取最稳妥且不破坏 INV-1 者；容器型不支持。
</decisions>

<code_context>
## Existing Code Insights

### Reusable Assets
- Phase 28 `WorkItemService.upsert`（单一入口，INV-1/6）+ `WorkItemIdentity` + `mr_reverse`/`manual` origin。
- Phase 30 `feishu_document` normalizer（经 `get_normalizer` 注册）+ DocumentService + REFERENCES 边。
- 既有 `server/knowledge/diff_archive.py archive_code_change`（DiffArchiver）→ CodeChangeArchive + MODIFIES_CHUNK；`services.git_platform.get_git_platform_client` + MR diff fetch（复用 26/diff 既有路径）。
- `server/mcp_tools/work_item_context_service.py`（URL/doc ref 提取正则）、`feishu_work_item._extract_doc_token`、feishu URL 模式（DOMAIN §1.5）。
- `services.background_runner.run_in_background`（后台派发）；既有派发→轮询 UI 范式（reconcile/cleanup 面板，web/src/api/reconcile.ts + ReconcilePanel.vue）。
- 既有检索面（search_rag / knowledge 检索），摄取后复用召回，不新建。

### Established Patterns
- delivery service 单一写入 + 后台 best-effort 降级 + 结构化结果（Phase 28/29/30/31）。
- webhook「投 ID → 后台权威回源」+ 派发后轮询状态。
- 前端 Vue3 `<script setup>` + TanStack Query + vue-i18n（zh-CN 默认）+ reka-ui；api barrel `web/src/api/index.ts`。

### Integration Points
- `server/delivery/services/`（编排 + REST）；`server/delivery/api/` + `urls.py`（触发 + 状态端点）。
- `web/src/`（一键摄取页面/面板 + api 模块 + i18n 文案）。
- 复用 P28 upsert / P30 normalizer / 既有 diff archive / 既有检索。
</code_context>

<specifics>
## Specific Ideas

- DOMAIN §1.5 实测：飞书工作项 URL `https://project.feishu.cn/{simple_name}/{url_type}/detail/{id}`，URL 段 ≠ API type_key（容器型 out of scope）；GitLab MR 实测 `target_branch` 非 master + `merge_commit_sha` + `changes[]`。
- 一次动作三产物：WorkItem（脊柱）+ Document（REFERENCES）+ CodeChangeArchive（diff RAG），全部可检索召回。
- best-effort 降级：任一步失败不阻断其余（部分摄取 + 结构化结果，对齐 §1.4）。
</specifics>

<deferred>
## Deferred Ideas

- 容器型工作项 URL 解析 —— out of scope（真实 type_key 未知）。
- Bitable 上线账本批量反查摄取 —— Phase 31 骨架已立，真实数据 REL-03。
- 评论入图 / 片段→需求反查 —— Phase 34。
- 真实飞书/git platform 凭证下的端到端摄取人工验收 —— human-UAT。
</deferred>

---

*Phase: 32-one-click-ingest*
*Context gathered: 2026-06-15 via smart discuss (autonomous)*
