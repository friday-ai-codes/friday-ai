# Roadmap: Friday AI

## Milestones

- 🚧 **v0.6.0 领域脊柱 + 知识图谱补全** — Phases 27–35 (in progress)
- ✅ **v0.5.0 索引检索地基与排除文件** — Phases 22–26 (shipped 2026-06-15) — [archive](./milestones/v0.5.0-ROADMAP.md)
- ✅ **v0.4.0 工作流系统契约重构** — Phases 17–21 (shipped 2026-06-13) — [archive](./milestones/v0.4.0-ROADMAP.md)
- ✅ **v0.3.0 交付知识图谱** — Phases 12–16 (shipped 2026-06-12) — [archive](./milestones/v0.3.0-ROADMAP.md)
- ✅ **v0.2.0 用户身份令牌与 Agent 工具打通** — Phases 6–11 (shipped 2026-06-10) — [archive](./milestones/v0.2.0-ROADMAP.md)
- ✅ **v0.1.0 首启初始化向导** — Phases 1–5 (shipped 2026-06-09) — [archive](./milestones/v0.1.0-ROADMAP.md)

> 跨里程碑前瞻路线（v0.6–v0.11）与设计底座见 `ROADMAP-vNext.md`、`DOMAIN-MODEL.md`、`PREFLIGHT.md`。

## Phases

<details>
<summary>✅ v0.5.0 索引检索地基与排除文件 (Phases 22–26) — SHIPPED 2026-06-15</summary>

- [x] Phase 22: 排除配置与统一过滤（fail-closed） (7/6 plans) — EXCL-01, EXCL-02 (+PF-04) — completed 2026-06-14
- [x] Phase 23: 清理对账（普通/敏感两模式） (4/4 plans) — EXCL-04, EXCL-05, EXCL-06 (+PF-03, PF-05) — completed 2026-06-14
- [x] Phase 24: 敏感文件 AI 识别建议名单 (4/4 plans) — EXCL-03 — completed 2026-06-14
- [x] Phase 25: Commit 历史索引 + 行号反查 (4/4 plans) — IDX-01, IDX-02 — completed 2026-06-14
- [x] Phase 26: 多仓凭证统一 + MCP 多仓参数 (6/5 plans) — REPO-01, REPO-02 — completed 2026-06-15

完整阶段详情见 [milestones/v0.5.0-ROADMAP.md](./milestones/v0.5.0-ROADMAP.md)。

</details>

### 🚧 v0.6.0 领域脊柱 + 知识图谱补全 (In Progress)

**Milestone Goal:** 立起 `delivery` 操作态脊柱（以飞书 work item 为中心），并把知识图谱补全到「可沉淀历史、可反查、可吃多源输入」——这是 v0.7/v0.8/v0.9 方案/编码/SDD 的数据底座。详细数据模型见 `DOMAIN-MODEL.md`，前置修复台账见 `PREFLIGHT.md`（PF-08~12），不变量 INV-1/INV-3/INV-6。

**依赖链：** FIX → WIT 脊柱 → {CMT 评论流 · DOC 文档 · REL Release 账本 · ING 一键摄取} → {HDIFF 历史 diff · RREF 反查 · VIS 截图}。

- [x] **Phase 27: 飞书接口前置修复** - 修对 work_item_type 取数 / 关系字段派生 / 评论端点 / 完整 fields[] 元数据（PF-09/10/11/12），WorkItem upsert 的依赖前置 (completed 2026-06-15)
- [x] **Phase 28: WorkItem 脊柱 + 单一 upsert 入口** - delivery app 操作态脊柱：canonical WorkItem + WorkItemService.upsert + 三分类 + SyncState + Relation 派生 + StatusEvent (completed 2026-06-15)
- [x] **Phase 29: 评论事件流** - append-only WorkItemCommentEvent 流式入库 + 当前评论树投影 (completed 2026-06-15)
- [x] **Phase 30: Document + REFERENCES 边** - 外部飞书/内部生成文档区分 + feishu_document normalizer 摄取 PRD/技术方案 + 关联 WorkItem (completed 2026-06-15)
- [x] **Phase 31: Release 账本 + Bitable adapter 骨架** - 宽容模型（保留 raw_row）+ 开放平台凭证独立解析的 Bitable client/adapter 骨架 (completed 2026-06-15)
- [x] **Phase 32: 一键摄取编排** - (看板URL, MR URL) → 拉看板工作项 + PRD/技术方案文档 + MR diff 并入库可检索 (completed 2026-06-15)
- [x] **Phase 33: 历史 diff 冻结 + bi-temporal 失效** - commit 锚定快照 + 重索引对账置 invalid_at + as-of 区分历史/当前（PF-08） (completed 2026-06-15)
- [ ] **Phase 34: 评论入图 + 片段→需求反查** - 评论摄取进知识投影 + code chunk/模块 → 需求/文档反查 API/MCP（依赖 v0.5 行号回填）
- [ ] **Phase 35: 截图识别需求** - 多模态 LLM：vision → 文本 query → 召回需求（非图片向量库）

## Phase Details

### Phase 27: 飞书接口前置修复

**Goal**: 修对 4 个飞书工作项/评论接口缺陷（PF-09/10/11/12），为 `WorkItemService.upsert` 提供可靠的真实数据回源——本里程碑一切数据底座的前置依赖。
**Depends on**: Nothing（首个 phase，WIT 脊柱的依赖前置）
**Requirements**: FIX-01, FIX-02, FIX-03, FIX-04
**Success Criteria** (what must be TRUE):

  1. 系统能按真实 `work_item_type`（issue / story / 容器型）拉取工作项与评论，不再默认 `story` 取错或取空（PF-09）
  2. `get_work_item` 返回保留完整 `fields[]` 对象（`field_name`/`field_type_key`/`field_alias`），不再拍平成 `{field_key: field_value}` 丢元数据（PF-12）
  3. `get_comments` 端点修复后能成功拉取并解析飞书工作项评论（PF-11）
  4. 工作项间关系可从 `work_item_related_multi_select` 关联字段读出（所属项目/迭代/版本），失效的独立 relation 端点降级为可选（PF-10）

**Plans**: 3 plans

- [x] 27-01-PLAN.md — 共享解析 helper（防御 JSON / 完整 fields[] / 关系派生 / 评论解析 纯函数 + 单测）
- [x] 27-02-PLAN.md — 接入 canonical client `services/feishu.py`（FIX-01/02/03/04）
- [x] 27-03-PLAN.md — 接入 near-dup client `feishu/client.py`（FIX-01/03/04，与 canonical 行为对齐）

### Phase 28: WorkItem 脊柱 + 单一 upsert 入口

**Goal**: 新增 Django `delivery` app，立起操作态脊柱——唯一 canonical `WorkItem` + `WorkItemService.upsert` 单一写入入口 + source-of-truth 三分类（mirror/friday_enhanced/writeback）+ `WorkItemSyncState` 来源完整度 + `WorkItemRelation` 字段派生 + `WorkItemStatusEvent` 状态事件流。
**Depends on**: Phase 27（依赖修对的飞书接口回源）
**Requirements**: WIT-01, WIT-02, WIT-03, WIT-04, WIT-05
**Success Criteria** (what must be TRUE):

  1. 同一飞书工作项无论从 webhook / 手动输入 / Bitable 导入 / MR 反查进入，都收敛到唯一 canonical `WorkItem`（三元组幂等，INV-1）
  2. 所有 `WorkItem` 落库只经 `WorkItemService.upsert` 单一入口（INV-6），sync 覆盖 mirror、绝不动 friday_enhanced
  3. 每次 upsert 按 facet 记录来源完整度 `WorkItemSyncState`（complete/partial/missing/stale），部分 facet 失败不回滚整体、落 error + 重试标记
  4. 系统从 story 关联字段正确派生父子/迭代/版本关系（`WorkItemRelation`），目标未落库时以 `target_external_id` 占位
  5. 工作项状态变更记为 append-only `WorkItemStatusEvent`（cur/pre state_key），非就地改写

**Plans**: 3 plans

- [x] 28-01-PLAN.md — delivery app + 四模型（WorkItem/SyncState/Relation/StatusEvent）+ 初始 migration（INV-1 unique_together）
- [x] 28-02-PLAN.md — WorkItemService.upsert 单一写入入口 + 派生（mirror-only/SyncState/Relation 占位/StatusEvent append）
- [x] 28-03-PLAN.md — 最小 REST + 飞书 webhook 接线后台 upsert + INV-6/INV-3 守护测试

### Phase 29: 评论事件流

**Goal**: 工作项评论以 append-only `WorkItemCommentEvent` 流式入库，再投影出当前评论树——为灰区讨论/方案再生成提供清晰事件边界，而非快照。
**Depends on**: Phase 27（FIX-03 评论端点修复）、Phase 28（WorkItem 脊柱）
**Requirements**: CMT-01, CMT-02
**Success Criteria** (what must be TRUE):

  1. 工作项评论以 append-only `WorkItemCommentEvent` 流式入库（created/replied/edited/deleted/approval），保留可追溯历史
  2. 系统可从评论事件流投影出当前评论树（线程结构），编辑/删除作为事件不就地改写
  3. 审批语义（approve/reject）作为事件被记录，为后续「评论触发方案再生成」提供清晰触发边界（v0.7 消费）

**Plans**: 3 plans

- [x] 29-01-PLAN.md — WorkItemCommentEvent 模型 + 0002 迁移 + 模型层 append-only 单测（CMT-01/02）
- [x] 29-02-PLAN.md — CommentEventService 单一 append 入口 + 幂等去重 + 拉取摄取 + approval 判定 + 评论树投影
- [x] 29-03-PLAN.md — webhook 评论事件后台 append + 评论树只读 REST + INV-6 评论旁路写表守护

### Phase 30: Document + REFERENCES 边

**Goal**: 区分外部飞书与内部生成文档落独立 `Document`/`DocumentVersion` 实体，新增 `feishu_document` normalizer 摄取飞书 docx（PRD/技术方案）并建 `REFERENCES` 边关联 `WorkItem`。
**Depends on**: Phase 28（`REFERENCES` 边 + `Document.work_item` FK 关联脊柱）
**Requirements**: DOC-01, DOC-02
**Success Criteria** (what must be TRUE):

  1. 系统区分外部飞书文档与内部生成文档（`document_type`/`source_kind`/`content_storage`），PRD/技术方案落独立 `Document` 实体
  2. `feishu_document` normalizer 把飞书 docx（PRD/技术方案）摄取入库，并建 `REFERENCES` 边关联到对应 `WorkItem`
  3. 给定一个带 `prd_url` 的 `WorkItem`，可经文档实体检索到其 PRD 正文快照

**Plans**: 4 plans

- [x] 30-01-PLAN.md — Document/DocumentVersion 模型 + 0004 迁移（DOC-01 模型位：external/internal + document_type + content_storage + supersedes 版本链）
- [x] 30-02-PLAN.md — DocumentService 单一写入入口（去重 + hash 不翻版本 + facet）+ Document INV-6 grep 守护
- [x] 30-03-PLAN.md — feishu_document normalizer（复用取材产出操作态 Document + knowledge document 实体 + REFERENCES 边）+ 注册
- [x] 30-04-PLAN.md — PRD 正文快照只读 REST 检索端点（DOC-02 成功标准 3）

### Phase 31: Release 账本 + Bitable adapter 骨架

**Goal**: 落地 Release 账本宽容模型（`ReleaseBatch`/`ReleaseRecord`/`ReleaseArtifact` + `raw_row`），并搭飞书 Bitable client/adapter 骨架；开放平台 `tenant_access_token` 解析独立于项目 plugin token。真实列映射待开放平台凭证后填（v2 REL-03）。
**Depends on**: Phase 28（`ReleaseRecord` 关联 `WorkItem`）
**Requirements**: REL-01, REL-02
**Success Criteria** (what must be TRUE):

  1. Release 账本宽容模型落地，保留 Bitable 原始行 `raw_row`，adapter 演进不丢数据
  2. 飞书 Bitable client/adapter 骨架就位，开放平台 `tenant_access_token` 凭证来源独立于项目 plugin token 解析
  3. Bitable 记录以 natural key `{app_token}:{table_id}:{record_id}` 标识（本 phase 不要求真实列结构全量映射——那是 v2 REL-03 待开放平台凭证）

**Plans**: 3 plans

Plans:

- [x] 31-01-PLAN.md — Release 宽容模型三表（raw_row 无损）+ migration 0006 [BLOCKING] + 模型守护单测
- [x] 31-02-PLAN.md — ReleaseService 账本单一写入入口（ingest/幂等/work_item 反查）+ INV-6 grep 守护 + 行为测试
- [x] 31-03-PLAN.md — BitableClient（开放平台 token 复用，解耦 plugin token）+ BitableReleaseAdapter 骨架 + respx/adapter 测试

### Phase 32: 一键摄取编排

**Goal**: 给定 (看板URL, MR URL)，编排拉看板工作项（经 upsert）→ PRD/技术方案文档（建 REFERENCES）→ MR diff（既有 RAG），一次入库可检索。
**Depends on**: Phase 28（WorkItem upsert）、Phase 30（Document/REFERENCES）、既有 MR diff RAG（`CodeChangeArchive`）
**Requirements**: ING-01
**Success Criteria** (what must be TRUE):

  1. 给定 (看板URL, MR URL)，系统能解析看板 URL 拉取工作项并经 `WorkItemService.upsert` 收敛入库
  2. 同一摄取动作能拉取 PRD/技术方案文档并建 `REFERENCES` 边、拉取 MR diff 入 RAG
  3. 摄取完成后该需求及其关联文档/diff 均可被检索召回

**Plans**: 3 plans
**UI hint**: yes

Plans:

- [x] 32-01-PLAN.md — IngestRun 状态模型 + 看板/MR URL 解析 helper（迁移 0008）
- [x] 32-02-PLAN.md — ingest_from_urls 三步编排（工作项/文档+REFERENCES/MR diff，best-effort）+ dispatch/status REST
- [x] 32-03-PLAN.md — 一键摄取前端面板 `/knowledge/ingest`（派发→轮询三步结果，i18n + 守护测试）

### Phase 33: 历史 diff 冻结 + bi-temporal 失效

**Goal**: 把历史 MR diff 冻结为 commit 锚定快照，master 演进后重索引对账把过期 `MODIFIES_CHUNK` 边置 `invalid_at`，查询按 as-of 区分历史/当前（PF-08）。相对独立，依赖既有 `CodeChangeArchive`。
**Depends on**: 既有 `CodeChangeArchive` / diff 归档（可较晚做，不强依赖前序 delivery phase）
**Requirements**: HDIFF-01, HDIFF-02
**Success Criteria** (what must be TRUE):

  1. 历史 MR diff 冻结为 commit 锚定快照（用 MR `target_branch` + `merge_commit_sha`，不假设 master）
  2. master 演进后，重索引对账把过期 `MODIFIES_CHUNK` 边置 `invalid_at`
  3. 查询按 as-of 区分历史/当前关联（历史"当年成立"的边不污染当前视图）

**Plans**: 2 plans

- [x] 33-01-PLAN.md — commit 锚定冻结：MR 元数据拉取（merge_commit_sha/target_branch）+ 一键摄取 WR-02 修复 + MODIFIES_CHUNK 边冻结 chunk 指纹（HDIFF-01）
- [x] 33-02-PLAN.md — bi-temporal 失效对账：重索引钩子置过期边 invalid_at + as-of 查询 helper（HDIFF-02，PF-08）

### Phase 34: 评论入图 + 片段→需求反查

**Goal**: 把评论摄取进 knowledge 投影（评论入图），并提供 code chunk/模块 → 需求/文档的反查 API/MCP，依赖 v0.5 已交付的 `ChunkRegistry` 行号回填。
**Depends on**: Phase 28（WorkItem）、Phase 29（评论事件流）、v0.5 行号回填（已交付）
**Requirements**: RREF-01, RREF-02
**Success Criteria** (what must be TRUE):

  1. 给定 code chunk / 模块，系统能反查关联的需求/文档（片段→需求反查 API/MCP）
  2. 评论摄取进知识投影（评论入图），可被检索关联到 `WorkItem`
  3. 反查结果可经 MCP/REST 暴露给 agent / 客户端调用

**Plans**: TBD

### Phase 35: 截图识别需求

**Goal**: 用户上传截图，经多模态 LLM 提取文字/UI/业务语义 → 文本 query → 召回对应需求（复用现有 work_item/知识库 RAG，非图片向量库）。相对独立，多模态 LLM 路线，最后做。
**Depends on**: 相对独立（多模态 LLM 路线；召回复用既有 RAG 与 WorkItem 脊柱）
**Requirements**: VIS-01
**Success Criteria** (what must be TRUE):

  1. 用户上传截图，系统经多模态 LLM 提取文字/UI/业务语义
  2. 提取的语义转为文本 query，召回对应需求（复用现有 work_item/知识库 RAG）
  3. 全程不建图片向量库（视觉相似/标注向量库列 backlog）

**Plans**: TBD
**UI hint**: yes

### 📋 Next milestone

v0.7.0 方案编排（需求 → 多 agent 调研 → 架构师融合主方案）见 `ROADMAP-vNext.md` §v0.7。

## Progress

**Execution Order:** 27 → 28 → {29, 30, 31, 32} → {33, 34, 35}（按依赖链；29/30/31 在 28 后可并行，32 需 30，33/34/35 相对靠后）

| Phase | Milestone | Plans Complete | Status | Completed |
|-------|-----------|----------------|--------|-----------|
| 22. 排除配置与统一过滤 | v0.5.0 | 7/6 | Complete | 2026-06-14 |
| 23. 清理对账（两模式） | v0.5.0 | 4/4 | Complete | 2026-06-14 |
| 24. 敏感文件 AI 识别 | v0.5.0 | 4/4 | Complete | 2026-06-14 |
| 25. Commit 历史索引 + 行号反查 | v0.5.0 | 4/4 | Complete | 2026-06-14 |
| 26. 多仓凭证统一 + MCP 多仓参数 | v0.5.0 | 6/5 | Complete | 2026-06-15 |
| 27. 飞书接口前置修复 | v0.6.0 | 3/3 | Complete    | 2026-06-15 |
| 28. WorkItem 脊柱 + 单一 upsert 入口 | v0.6.0 | 3/3 | Complete    | 2026-06-15 |
| 29. 评论事件流 | v0.6.0 | 3/3 | Complete    | 2026-06-15 |
| 30. Document + REFERENCES 边 | v0.6.0 | 4/4 | Complete    | 2026-06-15 |
| 31. Release 账本 + Bitable adapter 骨架 | v0.6.0 | 3/3 | Complete    | 2026-06-15 |
| 32. 一键摄取编排 | v0.6.0 | 3/3 | Complete    | 2026-06-15 |
| 33. 历史 diff 冻结 + bi-temporal 失效 | v0.6.0 | 2/2 | Complete    | 2026-06-15 |
| 34. 评论入图 + 片段→需求反查 | v0.6.0 | 0/TBD | Not started | - |
| 35. 截图识别需求 | v0.6.0 | 0/TBD | Not started | - |

---
*Previous milestones archived in .planning/milestones/*
