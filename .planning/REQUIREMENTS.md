# Requirements: Friday AI — v0.6.0 领域脊柱 + 知识图谱补全

**Defined:** 2026-06-15
**Core Value:** 让团队"开箱即用、安全地"把需求自动变成代码；v0.6.0 立起以飞书 work item 为中心的 `delivery` 操作态脊柱，把知识图谱补全到"可沉淀历史、可反查、可吃多源输入"——作为 v0.7/v0.8/v0.9 方案/编码/SDD 的数据底座。

> 设计底座：`.planning/ROADMAP-vNext.md` §v0.6、`.planning/DOMAIN-MODEL.md`（脊柱/状态机/产物/事件 taxonomy/实测飞书字段附录）、`.planning/PREFLIGHT.md`（PF-08~12）。
> 不变量：INV-1（飞书三元组唯一→单一 canonical WorkItem）、INV-3（knowledge 是检索投影非操作态事实源）、INV-6（落库只经 WorkItemService.upsert，禁旁路写表）。

## v1 Requirements

本里程碑提交范围。每条映射到 roadmap 某个 phase。

### 飞书接口前置修复（FIX）

> should-fix-before-v0.6：`WorkItemService.upsert` 依赖这些飞书接口先修对（PF-09/10/11/12）。

- [x] **FIX-01**: 系统按真实 `work_item_type`（issue / story / 容器型）拉取工作项与评论，不再默认 `story` 取错或取空（PF-09）
- [x] **FIX-02**: 工作项间关系改为从 `work_item_related_multi_select` 关联字段派生（所属项目/迭代/版本），失效的独立 relation 端点降级为可选（PF-10）
- [x] **FIX-03**: 修复 `get_comments` 端点，能成功拉取并解析飞书工作项评论（PF-11）
- [x] **FIX-04**: `get_work_item` 保留完整 `fields[]` 对象（`field_name`/`field_type_key`/`field_alias`），不再拍平丢元数据（PF-12）

### WorkItem 脊柱（WIT）

- [x] **WIT-01**: 同一飞书工作项无论从 webhook / 手动输入 / Bitable 导入 / MR反查进入，都收敛到唯一 canonical `WorkItem`（三元组幂等，INV-1）
- [x] **WIT-02**: 所有 `WorkItem` 落库只经 `WorkItemService.upsert` 单一入口（INV-6），按 mirror/friday_enhanced/writeback 三分类刷新（sync 覆盖 mirror、绝不动 enhanced）
- [x] **WIT-03**: 每次 upsert 按 facet 记录来源完整度 `WorkItemSyncState`（complete/partial/missing/stale），部分 facet 失败不回滚整体、落 error + 重试标记
- [x] **WIT-04**: 系统从 story 关联字段正确派生父子/迭代/版本关系（`WorkItemRelation`），目标未落库时以 `target_external_id` 占位
- [x] **WIT-05**: 工作项状态变更记为 append-only `WorkItemStatusEvent`（cur/pre state_key），非就地改写

### 评论事件流（CMT）

- [x] **CMT-01**: 工作项评论以 append-only `WorkItemCommentEvent` 流式入库（created/replied/edited/deleted/approval），保留可追溯历史
- [x] **CMT-02**: 系统可从评论事件流投影出当前评论树（线程结构），编辑/删除作为事件不就地改写

### 文档（DOC）

- [ ] **DOC-01**: 系统区分外部飞书文档与内部生成文档（`document_type`/`source_kind`/`content_storage`），PRD/技术方案落独立 `Document` 实体
- [ ] **DOC-02**: `feishu_document` normalizer 把飞书 docx（PRD/技术方案）摄取入库并建 `REFERENCES` 边关联 `WorkItem`

### Release 账本（REL）

- [ ] **REL-01**: Release 账本宽容模型（`ReleaseBatch`/`ReleaseRecord`/`ReleaseArtifact`）落地，保留 Bitable 原始行 `raw_row`，adapter 演进不丢数据
- [ ] **REL-02**: 飞书 Bitable client/adapter 骨架就位（开放平台 `tenant_access_token` 解析独立于项目 plugin token），natural key `{app_token}:{table_id}:{record_id}`（数据映射待开放平台凭证后填）

### 一键摄取（ING）

- [ ] **ING-01**: 给定 (看板URL, MR URL)，系统能拉看板工作项 + PRD/技术方案文档 + MR diff 并入库可检索

### 历史 diff 时效（HDIFF）

- [ ] **HDIFF-01**: 历史 MR diff 冻结为 commit 锚定快照（用 MR `target_branch` + `merge_commit_sha`，不假设 master）
- [ ] **HDIFF-02**: master 演进后，重索引对账把过期 `MODIFIES_CHUNK` 边置 `invalid_at`，查询按 as-of 区分历史/当前（PF-08）

### 反查（RREF）

- [ ] **RREF-01**: 给定 code chunk / 模块，系统能反查关联的需求/文档（片段→需求反查 API/MCP，依赖 v0.5 行号回填）
- [ ] **RREF-02**: 评论摄取进知识投影（评论入图），可被检索关联到 `WorkItem`

### 截图识别（VIS）

- [ ] **VIS-01**: 用户上传截图，系统经多模态 LLM 提取文字/UI/业务语义 → 文本 query → 召回对应需求（非图片向量库）

## v2 Requirements

延后到后续里程碑，已记录但不在本 roadmap。

### 方案编排 / 编码（PLAN / CODE）— v0.7 / v0.8

- **PLAN-01**: canonical `TechnicalPlan` + `TechnicalPlanService` + 旧 3 路径软链/迁移（v0.7）
- **PLAN-02**: `PlanSession` 编排状态机 + 并行调研子 agent + 架构师融合 + `PlanValidator`（v0.7）
- **CODE-01**: `RepoCodingTask` 多仓 wave 编码 + 跨仓产物注入 + 融合 PR（v0.8）

### Bitable 数据落地（REL-x）— 待开放平台凭证

- **REL-03**: Bitable 真实多维表格列映射 + `ReleaseRecord` 粒度定型（需开放平台 `app_id/secret` + 列头/样例行）

## Out of Scope

明确排除，附理由，避免反复回炉。

| Feature | Reason |
|---------|--------|
| 图片向量库（视觉相似 / 标注重） | 截图识别走多模态 LLM（vision→文本→RAG），向量库太重且场景不匹配，留 backlog |
| canonical `TechnicalPlan` / 方案编排 | v0.7 主题；本里程碑只立数据脊柱，不做方案生成收敛 |
| 多仓 wave 编码 → 融合 PR | v0.8 主题 |
| SDD / OpenSpec spec 状态机 | v0.9 主题；v0.6 不预埋 SDD 字段 |
| 统一 `AuditEvent` 操作审计模型 | v0.10 横切治理 |
| Bitable 真实数据全量入库 | 缺开放平台 `tenant_access_token` + 列结构样例；本里程碑只建 adapter 骨架 + 宽容模型 |
| 容器型工作项类型完整支持 | 真实 `type_key` 未知（URL 段 `project` ≠ API type），待查"工作项类型"接口或字段反推后补 |
| 评论触发方案再生成 | 评论事件边界本里程碑建好（挂 created/replied/approval），实际触发再生成属 v0.7 编排 |

## Traceability

哪个 phase 覆盖哪些需求。roadmap 创建时填充。

| Requirement | Phase | Status |
|-------------|-------|--------|
| FIX-01 | Phase 27 | Complete |
| FIX-02 | Phase 27 | Complete |
| FIX-03 | Phase 27 | Complete |
| FIX-04 | Phase 27 | Complete |
| WIT-01 | Phase 28 | Complete |
| WIT-02 | Phase 28 | Complete |
| WIT-03 | Phase 28 | Complete |
| WIT-04 | Phase 28 | Complete |
| WIT-05 | Phase 28 | Complete |
| CMT-01 | Phase 29 | Complete |
| CMT-02 | Phase 29 | Complete |
| DOC-01 | Phase 30 | Pending |
| DOC-02 | Phase 30 | Pending |
| REL-01 | Phase 31 | Pending |
| REL-02 | Phase 31 | Pending |
| ING-01 | Phase 32 | Pending |
| HDIFF-01 | Phase 33 | Pending |
| HDIFF-02 | Phase 33 | Pending |
| RREF-01 | Phase 34 | Pending |
| RREF-02 | Phase 34 | Pending |
| VIS-01 | Phase 35 | Pending |

**Coverage:**

- v1 requirements: 21 total
- Mapped to phases: 21/21 ✓
- Unmapped: 0

---
*Requirements defined: 2026-06-15*
*Last updated: 2026-06-15 after milestone v0.6.0 definition*
