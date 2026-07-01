# Roadmap: Friday AI

## Milestones

- 🟡 **v0.16.3 外部依赖接入知识体系（可检索 + 知识树 + 关联图谱）** — Phases 96–99 (planning) — 把项目外部依赖（`Artifact`：PRD/埋点评审/UI 文档等）接入知识总览/搜索/知识树，并与关键词/业务能力/仓库建关联 — [roadmap](./milestones/v0.16.3-ROADMAP.md) · [requirements](./REQUIREMENTS.md) · [research](./research/v0.16.3-external-deps-knowledge.md)
- ✅ **v0.16.1 统一 AI 技术方案生成（图编排归一 + 插槽式澄清拼接 + 能力完善）** — Phases 90–95 (shipped 2026-06-28) — 里程碑审计 tech_debt（18/18 需求满足 / integration_ok / 0 gaps / 0 BLOCKER；遗留真机·真实 provider·画布视觉端到端验收 + INFO 欠债）见 [audit](./milestones/v0.16.1-MILESTONE-AUDIT.md) — [archive](./milestones/v0.16.1-ROADMAP.md)
- ✅ **v0.16.0 项目工作区（飞书文档双向同步 + IDE 上下文闭环 + feature list 交付流水线）** — Phases 82–89 (shipped 2026-06-26) — 里程碑审计 tech_debt（37/37 需求满足 / integration_ok；遗留真机/live-platform 验收 + 既有并发测试欠债）见 [audit](./milestones/v0.16.0-MILESTONE-AUDIT.md) — [archive](./milestones/v0.16.0-ROADMAP.md)
- ✅ **v0.15.0 项目（交付上下文聚合根）** — Phases 76–81 (shipped 2026-06-26) — 里程碑审计 passed（38/38 需求满足 / integration_ok）见 [audit](./milestones/v0.15.0-MILESTONE-AUDIT.md) — [archive](./milestones/v0.15.0-ROADMAP.md)
- ✅ **v0.14.0 可观测性与日志治理** — Phases 71–75 (shipped 2026-06-24) — 里程碑审计 passed（34/34 需求满足 / integration_ok）见 [audit](./milestones/v0.14.0-MILESTONE-AUDIT.md) — [archive](./milestones/v0.14.0-ROADMAP.md)
- ✅ **v0.13.0 并发治理与索引体验** — Phases 65–70 (shipped 2026-06-23) — 里程碑审计 tech_debt（11/11 需求满足、integration_ok；遗留既有前端测试失败 + URL 拆段拼接 UI + 真机人工验收）见 [audit](./milestones/v0.13.0-MILESTONE-AUDIT.md) — [archive](./milestones/v0.13.0-ROADMAP.md)
- ✅ **v0.12.0 弹性任务底座（durable 任务队列与多副本就绪）** — Phases 60–64 (shipped 2026-06-20) — 里程碑审计 tech_debt（16/16 需求满足、integration_ok；遗留真机/真实平台运行期人工验收）见 [audit](./milestones/v0.12.0-MILESTONE-AUDIT.md) — [archive](./milestones/v0.12.0-ROADMAP.md)
- ✅ **v0.11.0 开放与协作** — Phases 56–59 (shipped 2026-06-17) — 里程碑审计 PASS（6/6 需求、INV-5/INV-6 成立）见 [audit](./milestones/v0.11.0-MILESTONE-AUDIT.md) — [archive](./milestones/v0.11.0-ROADMAP.md)
- ✅ **v0.10.0 操作审计治理** — Phases 53–55 (shipped 2026-06-17) — [archive](./milestones/v0.10.0-ROADMAP.md)
- ✅ **v0.9.0 SDD / OpenSpec 支持（重型）** — Phases 48–52 (shipped 2026-06-17) — [archive](./milestones/v0.9.0-ROADMAP.md)
- ✅ **v0.8.0 多仓串行编码 → 融合 PR** — Phases 43–47 (shipped 2026-06-17) — [archive](./milestones/v0.8.0-ROADMAP.md)
- ✅ **v0.7.0 方案编排（需求 → 主方案）** — Phases 36–42 (shipped 2026-06-16) — [archive](./milestones/v0.7.0-ROADMAP.md)
- ✅ **v0.6.0 领域脊柱 + 知识图谱补全** — Phases 27–35 (shipped 2026-06-15) — [archive](./milestones/v0.6.0-ROADMAP.md)
- ✅ **v0.5.0 索引检索地基与排除文件** — Phases 22–26 (shipped 2026-06-15) — [archive](./milestones/v0.5.0-ROADMAP.md)
- ✅ **v0.4.0 工作流系统契约重构** — Phases 17–21 (shipped 2026-06-13) — [archive](./milestones/v0.4.0-ROADMAP.md)
- ✅ **v0.3.0 交付知识图谱** — Phases 12–16 (shipped 2026-06-12) — [archive](./milestones/v0.3.0-ROADMAP.md)
- ✅ **v0.2.0 用户身份令牌与 Agent 工具打通** — Phases 6–11 (shipped 2026-06-10) — [archive](./milestones/v0.2.0-ROADMAP.md)
- ✅ **v0.1.0 首启初始化向导** — Phases 1–5 (shipped 2026-06-09) — [archive](./milestones/v0.1.0-ROADMAP.md)

> 历史里程碑详情归档在 `.planning/milestones/`，要点见 `MILESTONES.md`。

## Phases

### 🟡 v0.16.3 外部依赖接入知识体系（可检索 + 知识树 + 关联图谱）(Phases 96–99) — PLANNING

- [ ] Phase 96: 外部依赖进检索与总览 — 全类型工件登记可发现 + 搜索命中标类型可跳查看 + 知识总览加「交付文档」区块（KDEP-01/02/03）
- [ ] Phase 97: 交付文档知识树视图 — `/knowledge` 树页并行「交付文档」树（项目→类型→工件）+ 树内搜索/查看 + 后端树数据 API（KDEP-04/05/06）
- [ ] Phase 98: 工件↔仓库/能力/关键词关联 — RepoRouterV2 路由工件正文落 RELATES_TO 边 + 同步 verified RepoAssociation + 关联可查询（KDEP-07/08/09）
- [ ] Phase 99: 关联可视化与交叉入口 — 星图纳入 artifact 节点/边 + 知识实体图/详情展示关联 + 作战室↔知识闭环（KDEP-10/11/12）

完整阶段详情（Goal / Success Criteria / 依赖链）见 [milestones/v0.16.3-ROADMAP.md](./milestones/v0.16.3-ROADMAP.md)；需求 KDEP-01~12 见 [REQUIREMENTS.md](./REQUIREMENTS.md)；现状探查 + 架构决策见 [research/v0.16.3-external-deps-knowledge.md](./research/v0.16.3-external-deps-knowledge.md)。**执行顺序 96 → 97 → 98 → 99。** 下一步：`$gsd-autonomous`（或 `$gsd-plan-phase 96`）。

#### Phase Details (v0.16.3)

### Phase 96: 外部依赖进检索与总览

**Goal**: 让全部类型的外部依赖工件都能在知识体系里被发现——搜索能命中并标注类型、一键跳查看，知识总览把「交付文档/外部依赖」纳入大盘统计与入口。
**Depends on**: v0.16.0/v0.15.0 已交付的 Artifact + delivery_knowledge 摄取链路。
**Requirements**: KDEP-01, KDEP-02, KDEP-03
**Success Criteria** (what must be TRUE):

  1. 所有 `ArtifactType`（含非 ragable 的 UI 稿）都在知识体系登记为可发现条目：ragable 文字工件走既有向量摄取；非 ragable 至少登记 title/type/url 进关键词可搜索层，无类型遗漏。
  2. `/knowledge` 搜索 Tab 命中工件时，结果项标注工件类型并可一键跳转到工件查看（markdown 渲染 / 飞书打开），跨项目按 `access_scope` 过滤。
  3. `KnowledgeDashboard` 增加「交付文档/外部依赖」区块：按类型计数 + 入口 + 即时搜索，风格与现有仓库/域指标一致。

**UI hint**: yes（知识总览区块 + 搜索结果项，`/gsd-ui-phase` 可介入）
**Plans**: TBD（discuss/plan-phase 生成）

### Phase 97: 交付文档知识树视图

**Goal**: 在 `/knowledge` 知识树页提供一棵并行的「交付文档」树，按 项目 → 工件类型 → 工件 组织，可搜索、可点开查看，与代码能力树并列切换而不污染它。
**Depends on**: Phase 96（登记 + 查看跳转复用）
**Requirements**: KDEP-04, KDEP-05, KDEP-06
**Success Criteria** (what must be TRUE):

  1. 知识树页新增「交付文档」树视图（项目→类型→工件），与代码能力树切换/并列，PageIndex 能力树数据不变。
  2. 交付文档树支持树内搜索/过滤 + 点击叶子查看工件（复用查看弹窗），空态优雅、层级清晰分明。
  3. 后端提供交付文档树数据 API：按用户可见 project 聚合 `Artifact`，分组 项目→类型→工件，带权限过滤与节点上限保护。

**UI hint**: yes（知识树新视图，`/gsd-ui-phase` 应介入）
**Plans**: TBD

### Phase 98: 工件↔仓库/能力/关键词关联

**Goal**: 为外部依赖工件建立与代码仓库、业务能力、关键词的结构化关联，并把已确认的项目仓库关联同步进知识图谱，使关联可查询。
**Depends on**: Phase 96（工件已在知识实体层）
**Requirements**: KDEP-07, KDEP-08, KDEP-09
**Success Criteria** (what must be TRUE):

  1. ragable 文字工件在摄取/更新时经 `RepoRouterV2` 路由正文 → matched 仓库 + `matched_node_paths` + 关键词，落 `KnowledgeEdge(RELATES_TO)` + `metadata`，单一写入入口、`call_source` 观测、fail-soft 绝不反噬。
  2. verified `RepoAssociation` 同步为项目/工件↔仓库的图谱边（扩展 `sync_relations_from_operational` / `link_repository`），`RepoAssociation` 仍是唯一真相源、边单向派生。
  3. 关联可查询：给定工件列出相关仓库/能力/关键词；给定能力/关键词/仓库反查相关文档；查询走 `graph_store` 收口。

**UI hint**: no（后端图谱 + 路由为主）
**Plans**: TBD

### Phase 99: 关联可视化与交叉入口

**Goal**: 把工件↔仓库/能力/关键词的关联可视化到星图与知识图谱，并在作战室外部依赖区与知识体系之间打通双向交叉入口。
**Depends on**: Phase 98（关联边已存在）
**Requirements**: KDEP-10, KDEP-11, KDEP-12
**Success Criteria** (what must be TRUE):

  1. `_build_project_galaxy` 纳入 `artifact` 节点与边（`HAS_ARTIFACT` / `ARTIFACT_REPO` / `ARTIFACT_CAPABILITY`）；关联仓库来源并入 `RepoAssociation`（不再仅 MR）。
  2. 知识实体图 / 实体详情页展示工件↔仓库/能力/关键词关联；仓库/能力视角反向展示相关交付文档（双向可导航）。
  3. 作战室「外部依赖」区查看工件处可跳知识实体/关联视图，形成「作战室↔知识」闭环。

**UI hint**: yes（星图 + 实体详情 + 作战室交叉入口，`/gsd-ui-phase` 可介入）
**Plans**: TBD

<details>
<summary>✅ v0.16.1 统一 AI 技术方案生成（图编排归一 + 插槽式澄清拼接 + 能力完善）(Phases 90–95) — SHIPPED 2026-06-28 — 审计 tech_debt</summary>

- [x] Phase 90: 澄清能力层 (4/4 plans) — CLARIFY-01/02/03 — completed 2026-06-27
- [x] Phase 91: 澄清出口面 + 回流 resume (5/5 plans) — CLARIFY-04/05/06/07 — completed 2026-06-27
- [x] Phase 92: 插槽系统（后端） (3/3 plans) — SLOT-01/02 — completed 2026-06-27
- [x] Phase 93: 插槽编辑器（前端） (7/7 plans) — SLOT-03/04 — completed 2026-06-27
- [x] Phase 94: 入口统一 (5/5 plans) — UNIFY-01~06 — completed 2026-06-27
- [x] Phase 95: 拆分完善 (3/3 plans) — DECOMP-01 — completed 2026-06-27

完整阶段详情见 [milestones/v0.16.1-ROADMAP.md](./milestones/v0.16.1-ROADMAP.md)；里程碑审计 tech_debt（18/18 需求满足 / integration_ok / 0 gaps / 0 BLOCKER；遗留真机·真实 provider·画布视觉端到端验收 + INFO 欠债）见 [milestones/v0.16.1-MILESTONE-AUDIT.md](./milestones/v0.16.1-MILESTONE-AUDIT.md)。

</details>

<details>
<summary>✅ v0.16.0 项目工作区（飞书文档双向同步 + IDE 上下文闭环 + feature list 交付流水线）(Phases 82–89) — SHIPPED 2026-06-26 — 审计 tech_debt</summary>

- [x] Phase 82: 项目工作区实体 + 权限翻转 + 飞书文件夹 + 5 文件 (5/5 plans) — WS-01~04, DOC-01~06 — completed 2026-06-26
- [x] Phase 83: 飞书文档双向同步引擎 (6/6 plans) — SYNC-01~06 — completed 2026-06-26
- [x] Phase 84: 项目工作台前端 2.0 (5/5 plans) — WB-01~05 — completed 2026-06-26
- [x] Phase 85: 项目上下文可读 + 分支绑定 (4/4 plans) — CTX-01/02, BIND-01/02 — completed 2026-06-27
- [x] Phase 86: IDE 上下文闭环（hooks） (5/5 plans) — HOOK-01~04 — completed 2026-06-27
- [x] Phase 87: 看板拆分节点 + 群 + 流式卡片 (4/4 plans) — BOARD-01/02 — completed 2026-06-27
- [x] Phase 88: 智能业务关联仓库 (5/5 plans) — REPO-01/02 — completed 2026-06-27
- [x] Phase 89: 技术方案深化 + 建分支绑项目 (4/4 plans) — PLAN-01~04 — completed 2026-06-27

完整阶段详情见 [milestones/v0.16.0-ROADMAP.md](./milestones/v0.16.0-ROADMAP.md)；里程碑审计 tech_debt（37/37 需求、integration_ok；遗留真机/live-platform 验收 + 既有并发测试欠债）见 [milestones/v0.16.0-MILESTONE-AUDIT.md](./milestones/v0.16.0-MILESTONE-AUDIT.md)。

</details>

<details>
<summary>✅ v0.15.0 项目（交付上下文聚合根）(Phases 76–81) — SHIPPED 2026-06-26 — 审计 passed</summary>

- [x] Phase 76: 命名腾挪（Project→Space 重构前置） (1/1 plans) — RENAME-01/02 — completed 2026-06-25
- [x] Phase 77: 项目聚合根 + 身份映射 + 成员协作 (1/1 plans) — PROJ-01~05, IDENT-01, MEMBER-01~03 — completed 2026-06-25
- [x] Phase 78: 飞书触发建项目 + 看板枚举 + 工作项组合 (1/1 plans) — FSPROJ-01~03, COMPOSE-01/02 — completed 2026-06-25
- [x] Phase 79: 工件/依赖项（可配置类型 + 实例 + RAG）+ 知识关联 (1/1 plans) — ARTIFACT-01~05, KLINK-01/02 — completed 2026-06-26
- [x] Phase 80: 项目记忆 + MR 实体 + 上下文召回接入 Web 会话 (1/1 plans) — MEM-01~04, RECALL-01~03, MR-01/02 — completed 2026-06-26
- [x] Phase 81: Cursor 回流 + 前端项目工作台 (1/1 plans) — CURSOR-01~03, UI-01~03 — completed 2026-06-26

完整阶段详情见 [milestones/v0.15.0-ROADMAP.md](./milestones/v0.15.0-ROADMAP.md)；里程碑审计 passed（38/38 需求、integration_ok）见 [milestones/v0.15.0-MILESTONE-AUDIT.md](./milestones/v0.15.0-MILESTONE-AUDIT.md)。

</details>

<details>
<summary>✅ v0.14.0 可观测性与日志治理 (Phases 71–75) — SHIPPED 2026-06-24 — 审计 passed</summary>

- [x] Phase 71: 可观测性地基（用户上下文贯穿 + 系统日志治理） (5/5 plans) — CTX-01/02, LOG-01~08 — completed 2026-06-24
- [x] Phase 72: 调用数据采集（AI/LLM + 召回 + 请求入口） (4/4 plans) — RATE-01/02, RAG-01/02, SLA-02/03/04 — completed 2026-06-24
- [x] Phase 73: 快照·趋势·查询 API (3/3 plans) — SNAP-01~05, RATE-03, SLA-01, QUERY-01/02 — completed 2026-06-24
- [x] Phase 74: 告警引擎与通知（阈值 + 告警事件 + 邮件） (3/3 plans) — ALERT-01/02/03 — completed 2026-06-24
- [x] Phase 75: 运维大盘前端 + 规范固化 (5/5 plans) — UI-01~04, SPEC-01 — completed 2026-06-24

完整阶段详情见 [milestones/v0.14.0-ROADMAP.md](./milestones/v0.14.0-ROADMAP.md)；里程碑审计 passed（34/34 需求、integration_ok）见 [milestones/v0.14.0-MILESTONE-AUDIT.md](./milestones/v0.14.0-MILESTONE-AUDIT.md)。

</details>

<details>
<summary>✅ v0.13.0 并发治理与索引体验 (Phases 65–70) — SHIPPED 2026-06-23 — 审计 tech_debt</summary>

- [x] Phase 65: AI 对话串流隔离修复 (1/1 plans) — STREAM-01 — completed 2026-06-23
- [x] Phase 66: 默认禁用 LSP（仅 tree-sitter） (1/1 plans) — LSP-01 — completed 2026-06-23
- [x] Phase 67: 并发治理（槽位锁池 / provider 限流 / 容器上限） (3/3 plans) — CONC-01/02/03 — completed 2026-06-23
- [x] Phase 68: 实时进度统一 + 进度条修复 (1/1 plans) — PROG-01/02 — completed 2026-06-23
- [x] Phase 69: 批量加仓 + 全部更新索引（超管） (1/1 plans) — BATCH-01/02 — completed 2026-06-23
- [x] Phase 70: access token / 密钥提供方重构（FK） (1/1 plans) — TOKEN-01/02 — completed 2026-06-23

完整阶段详情见 [milestones/v0.13.0-ROADMAP.md](./milestones/v0.13.0-ROADMAP.md)；里程碑审计 tech_debt（11/11 需求、integration_ok）见 [milestones/v0.13.0-MILESTONE-AUDIT.md](./milestones/v0.13.0-MILESTONE-AUDIT.md)。

</details>

<details>
<summary>✅ v0.12.0 弹性任务底座（durable 任务队列与多副本就绪）(Phases 60–64) — SHIPPED 2026-06-20</summary>

- [x] Phase 60: durable 底座地基 (4/4 plans) — DURABLE-01~04 — completed 2026-06-19
- [x] Phase 61: 迁移 index/graph + 收口 ResumableTask (4/4 plans) — MIGRATE-01/02, IDEMP-01 — completed 2026-06-19
- [x] Phase 62: 爬取+入库 durable 队列 + PageIndex 接入 (3/3 plans) — CRAWL-01/02, PAGEIDX-01 — completed 2026-06-20
- [x] Phase 63: 部署硬化 + 外部副作用 fencing (3/3 plans) — DEPLOY-01~03, IDEMP-02 — completed 2026-06-20
- [x] Phase 64: runner k8s Job executor (2/2 plans) — RUNNER-01/02 — completed 2026-06-20

完整阶段详情见 [milestones/v0.12.0-ROADMAP.md](./milestones/v0.12.0-ROADMAP.md)；里程碑审计 tech_debt（16/16 需求、integration_ok）见 [milestones/v0.12.0-MILESTONE-AUDIT.md](./milestones/v0.12.0-MILESTONE-AUDIT.md)。

</details>

<details>
<summary>✅ v0.11.0 开放与协作 (Phases 56–59) — SHIPPED 2026-06-17 — 审计 PASS</summary>

- [x] Phase 56: compat 内部工具调用 → progress/trace 事件透出 (2/2 plans) — TRACE-01, TRACE-02 — completed 2026-06-17
- [x] Phase 57: Anthropic 兼容端点 `/v1/messages` (2/2 plans) — ANTHROPIC-01, ANTHROPIC-02 — completed 2026-06-17
- [x] Phase 58: 飞书原生流式卡片（CardKit）(2/2 plans) — CARD-01 — completed 2026-06-17
- [x] Phase 59: 工作流自动建群节点 (2/2 plans) — GROUP-01 — completed 2026-06-17

里程碑审计 PASS（6/6 需求、INV-5/INV-6 成立）见 [milestones/v0.11.0-MILESTONE-AUDIT.md](./milestones/v0.11.0-MILESTONE-AUDIT.md)。

</details>

<details>
<summary>✅ v0.10.0 操作审计治理 (Phases 53–55) — SHIPPED 2026-06-17</summary>

完整阶段详情见 [milestones/v0.10.0-ROADMAP.md](./milestones/v0.10.0-ROADMAP.md)。

</details>

<details>
<summary>✅ v0.9.0 SDD / OpenSpec 支持（重型）(Phases 48–52) — SHIPPED 2026-06-17</summary>

完整阶段详情见 [milestones/v0.9.0-ROADMAP.md](./milestones/v0.9.0-ROADMAP.md)。

</details>

<details>
<summary>✅ v0.8.0 多仓串行编码 → 融合 PR (Phases 43–47) — SHIPPED 2026-06-17</summary>

完整阶段详情见 [milestones/v0.8.0-ROADMAP.md](./milestones/v0.8.0-ROADMAP.md)。

</details>

<details>
<summary>✅ v0.7.0 方案编排（需求 → 主方案）(Phases 36–42) — SHIPPED 2026-06-16</summary>

完整阶段详情见 [milestones/v0.7.0-ROADMAP.md](./milestones/v0.7.0-ROADMAP.md)。

</details>

<details>
<summary>✅ v0.6.0 领域脊柱 + 知识图谱补全 (Phases 27–35) — SHIPPED 2026-06-15</summary>

完整阶段详情见 [milestones/v0.6.0-ROADMAP.md](./milestones/v0.6.0-ROADMAP.md)。

</details>

## Progress

里程碑 v0.1.0–v0.16.1（Phases 1–95）均已交付。**🟡 当前立项：v0.16.3 外部依赖接入知识体系（Phases 96–99，4 阶段 / 12 需求 KDEP）** —— 把项目外部依赖（`Artifact`：PRD/埋点评审/UI 文档等）接入知识总览/搜索/知识树，并与关键词/业务能力/代码仓库互相建关联、可视化。规划/调研已就绪（REQUIREMENTS + milestones/v0.16.3-ROADMAP + research 基线），**待 `$gsd-autonomous` 执行整个里程碑**（或 `$gsd-plan-phase 96` 逐阶段）。

> 说明：本里程碑跳过 v0.16.2（未使用）；沿用「续号 Phase」惯例（上一里程碑收官 Phase 95 → 本里程碑 96–99）。

v0.16.1 遗留的真机/真实 provider/画布视觉端到端人工验收（10 项）见 [audit](./milestones/v0.16.1-MILESTONE-AUDIT.md) §4 与各 phase VERIFICATION「Deferred」段。

各历史里程碑详情归档在 `.planning/milestones/`，要点见 `MILESTONES.md`。

---
*Previous milestones archived in .planning/milestones/*
