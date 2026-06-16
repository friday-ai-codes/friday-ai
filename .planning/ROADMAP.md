# Roadmap: Friday AI

## Milestones

- 🚧 **v0.7.0 方案编排（需求 → 主方案）** — Phases 36–42 (in progress)
- ✅ **v0.6.0 领域脊柱 + 知识图谱补全** — Phases 27–35 (shipped 2026-06-15) — [archive](./milestones/v0.6.0-ROADMAP.md)
- ✅ **v0.5.0 索引检索地基与排除文件** — Phases 22–26 (shipped 2026-06-15) — [archive](./milestones/v0.5.0-ROADMAP.md)
- ✅ **v0.4.0 工作流系统契约重构** — Phases 17–21 (shipped 2026-06-13) — [archive](./milestones/v0.4.0-ROADMAP.md)
- ✅ **v0.3.0 交付知识图谱** — Phases 12–16 (shipped 2026-06-12) — [archive](./milestones/v0.3.0-ROADMAP.md)
- ✅ **v0.2.0 用户身份令牌与 Agent 工具打通** — Phases 6–11 (shipped 2026-06-10) — [archive](./milestones/v0.2.0-ROADMAP.md)
- ✅ **v0.1.0 首启初始化向导** — Phases 1–5 (shipped 2026-06-09) — [archive](./milestones/v0.1.0-ROADMAP.md)

> 跨里程碑前瞻路线（v0.7–v0.11）与设计底座见 `ROADMAP-vNext.md`、`DOMAIN-MODEL.md`、`PREFLIGHT.md`。

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

<details>
<summary>✅ v0.6.0 领域脊柱 + 知识图谱补全 (Phases 27–35) — SHIPPED 2026-06-15</summary>

- [x] Phase 27: 飞书接口前置修复 (3/3 plans) — FIX-01..04 (+PF-09/10/11/12) — completed 2026-06-15
- [x] Phase 28: WorkItem 脊柱 + 单一 upsert 入口 (3/3 plans) — WIT-01..05 — completed 2026-06-15
- [x] Phase 29: 评论事件流 (3/3 plans) — CMT-01..02 — completed 2026-06-15
- [x] Phase 30: Document + REFERENCES 边 (4/4 plans) — DOC-01..02 — completed 2026-06-15
- [x] Phase 31: Release 账本 + Bitable adapter 骨架 (3/3 plans) — REL-01..02 — completed 2026-06-15
- [x] Phase 32: 一键摄取编排 (3/3 plans) — ING-01 — completed 2026-06-15
- [x] Phase 33: 历史 diff 冻结 + bi-temporal 失效 (2/2 plans) — HDIFF-01..02 (+PF-08) — completed 2026-06-15
- [x] Phase 34: 评论入图 + 片段→需求反查 (2/2 plans) — RREF-01..02 — completed 2026-06-15
- [x] Phase 35: 截图识别需求 (2/2 plans) — VIS-01 — completed 2026-06-15

完整阶段详情见 [milestones/v0.6.0-ROADMAP.md](./milestones/v0.6.0-ROADMAP.md)。

</details>

### 🚧 v0.7.0 方案编排（需求 → 主方案）(In Progress)

**Milestone Goal:** 把「需求 → 一份高质量多仓主技术方案」做成可复用的 map-reduce 多 agent 编排引擎：拆分 → 路由 → 召回 → 澄清 → 并行调研（子 agent 容器隔离）→ 架构师融合主方案（结构化 `MergedPlan` + `PlanValidator`）。同时立 canonical `TechnicalPlan` 脊柱、编排状态机 `PlanSession`、事件 taxonomy——作为 v0.8 多仓编码、v0.9 SDD 的方案底座。详细数据模型见 `DOMAIN-MODEL.md` §5/§6/§7/§14/§15，前置修复台账见 `PREFLIGHT.md`（PF-01/02），不变量 INV-2/INV-5/INV-6。

**依赖链（严格顺序）：** 前置修复+引擎骨架(36) → canonical 方案脊柱(37) → 路由+召回(38) → 并行调研(39) → 架构师融合(40) → 澄清+事件+工作流入口(41) → Chat 入口(42)。PF-01/02 为开工 blocking 必修；37 canonical 方案是 40 融合产物的落库底座；38 路由/召回喂给 39 调研；39 partial 喂给 40 融合；41 把入口+事件端到端串起。

- [x] **Phase 36: 前置修复 + 编排引擎骨架 + PlanSession 状态机** - 修 PF-01/02（检索工具名漂移 / verify_plan schema 漂移）+ 立可复用 `ai_plan_research` 编排 engine + 可持久化可恢复的 `PlanSession` 状态机（§14） (completed 2026-06-16)
- [x] **Phase 37: canonical TechnicalPlan + TechnicalPlanService + 旧路径软链/迁移** - 立 canonical `TechnicalPlan`/`PlanVersion` + `TechnicalPlanService` 唯一写入入口（INV-6）+ 旧 3 路径 eager 投影软链 + read-time lazy 迁移 (completed 2026-06-16)
- [x] **Phase 38: 路由 + 召回接入** - 编排接入 `RepoRouterV2`（能力树+LLM 路由候选仓）+ 历史召回（`DeliveryKnowledgeSearchService` 相似需求/缺陷/复盘/方案） (completed 2026-06-16)
- [x] **Phase 39: 并行调研子 agent** - filter_then_container 只对需深入仓 fan-out 隔离容器调研，产结构化 `PartialPlan` + 单仓失败重试 + 重索引使过期 partial 置 stale 重跑 (completed 2026-06-16)
- [x] **Phase 40: 架构师融合 + MergedPlan + PlanValidator + 跨仓依赖** - 架构师子 agent 收齐 partial 产结构化 `MergedPlan`（契约/依赖 DAG/迁移/风险/发布顺序/回滚/execution_plan）+ `PlanValidator` 拦截 + 跨仓依赖显式建模 (completed 2026-06-16)
- [ ] **Phase 41: HITL 澄清 + 事件 taxonomy + 工作流入口** - `Clarification` 挂起回路（仅 affected_partials 重跑）+ §15 trace 事件全程产出 + 工作流入口端到端跑通编排
- [ ] **Phase 42: Chat 入口薄封装** - Chat 入口薄封装复用同一底层 orchestration engine（工作流先行，不并行造两套编排）

## Phase Details

### Phase 36: 前置修复 + 编排引擎骨架 + PlanSession 状态机

**Goal**: 先修两个 blocking 前置漂移（`search_code` 工具名 / `verify_plan` schema），把方案质量与 PlanValidator 的地基补齐；再立一个可复用的 `ai_plan_research` 编排 engine（工作流与 Chat 共用底层）+ 可持久化、可恢复的 `PlanSession` 状态机，按 §14 转移表驱动「拆分→路由→召回→澄清→并行调研→融合」流水线。
**Depends on**: Nothing（本里程碑首个 phase；PF-01/02 为开工 blocking 必修，先于一切编排工作）
**Requirements**: PF-01, PF-02, ORCH-01, ORCH-02
**Success Criteria** (what must be TRUE):

  1. server 端方案生成的检索工具真正生效——prompt 引用的工具名与注册名一致（`search_code` → `search_repository_code`），`build_langchain_tools` 对未知工具改 fail-loud 记 error，不再静默 `continue` 吞掉（PF-01）
  2. `verify_plan` 校验字段对齐到 schema 实际的 `execution_plan`（不再校验不存在的 `tasks`），方案校验真正命中关键字段——作为 v0.7 `PlanValidator` 的基础（PF-02）
  3. `PlanSession` 状态机可持久化、可从中断恢复，按 §14 转移表推进（decomposing → routing → recalling → clarifying → researching → merging → done/failed），不可恢复错误落结构化 `failed`
  4. 可复用 `ai_plan_research` 编排 engine 抽象就位，驱动流水线推进，工作流与 Chat 可共用同一底层（不为两入口造两套编排）

**Plans**: 3 plans

Plans:
- [x] 36-01-PLAN.md — 前置修复 PF-01（工具名漂移 + fail-loud）/ PF-02（verify_plan 对齐 execution_plan）+ 守护测试
- [x] 36-02-PLAN.md — PlanSession 模型（delivery app）+ migration + PlanSessionService 状态机单一入口（§14 _ALLOWED）+ INV-6 守护
- [x] 36-03-PLAN.md — ai_plan_research 编排 engine 骨架（入口无关 + 可注入协议）+ advance/resume/不旁路 status 测试

### Phase 37: canonical TechnicalPlan + TechnicalPlanService + 旧路径软链/迁移

**Goal**: 立 canonical `TechnicalPlan`/`PlanVersion` 方案脊柱 + `TechnicalPlanService` 唯一写入入口（INV-6），把存量 3 条 plan 路径（chat/mcp/workflow）经 service 渐进收敛——eager 投影挂软链 + read-time lazy 迁移，不全量双写，不爆改。这是后续架构师融合产物（§7 `MergedPlan`）的落库底座。
**Depends on**: Phase 36（编排 engine + `PlanSession`：新编排经 service eager 创建 canonical）
**Requirements**: PLAN-01, PLAN-02, PLAN-03
**Success Criteria** (what must be TRUE):

  1. canonical `TechnicalPlan`/`PlanVersion` 落库（origin/status 状态 + version + supersedes 版本链 + `content` 存 §7 MergedPlan schema），方案最终可追溯到 `WorkItem`（INV-2，chat 自然语言允许 null 但显式标记）
  2. 所有方案解析/创建/关联只经 `TechnicalPlanService`（`resolve`/`create_from`/`link`，INV-6），无旁路写表；新编排经它 eager 创建 canonical
  3. 存量 3 路径经 service eager 投影挂软链（`canonical_plan_id` / `external_ref`）+ 首次读到无 canonical 的旧记录走 read-time lazy 迁移建 canonical 并回填链（不全量双写）
  4. 迁移期旧表只读历史、冲突以 canonical 为准、canonical 归档/删除不级联删旧表

**Plans**: 3 plans

Plans:
- [x] 37-01-PLAN.md — canonical TechnicalPlan/PlanVersion + PlanExternalRef + chat/mcp canonical_plan_id 软链字段 + migration（schema-first）+ 模型守护测试
- [x] 37-02-PLAN.md — TechnicalPlanService 唯一写入入口（create_from/resolve/link/add_version/archive）+ PlanRef + INV-6 grep 守护
- [x] 37-03-PLAN.md — read-time lazy 迁移三路径忠实取材 + chat 创建入口 eager 投影示范 + 幂等/冲突/归档不级联守护

### Phase 38: 路由 + 召回接入

**Goal**: 把编排的「路由」与「召回」两段接上既有底座——`RepoRouterV2`（能力树 + LLM 快筛涉及哪些仓）路由出候选仓 + confidence 写入 `PlanSession`；`DeliveryKnowledgeSearchService` 召回相似需求/缺陷/复盘/技术方案，注入后续并行调研上下文。
**Depends on**: Phase 37（canonical 脊柱 + 编排 engine 推进到 routing/recalling 阶段）
**Requirements**: ROUTE-01, RECALL-01
**Success Criteria** (what must be TRUE):

  1. 编排在 `routing` 阶段接入 `RepoRouterV2`，从需求路由出候选仓库 + confidence，并写入 `PlanSession`（按 §14 routing → recalling 转移）
  2. 编排在 `recalling` 阶段接入历史召回（`DeliveryKnowledgeSearchService`：相似需求/缺陷/复盘/技术方案），把召回上下文注入后续调研
  3. 编排在该两段产出 `repo.routing` / `knowledge.recalling` trace 事件（§15 统一信封）

**Plans**: 3 plans

Plans:
- [x] 38-01-PLAN.md — PlanSession 字段扩展（routing/recall_context JSON + created_by FK）+ migration 0011 + PlanSessionService 持久化接线（INV-6）
- [x] 38-02-PLAN.md — 路由 adapter（ROUTE-01）RepoRouterV2Adapter + engine._route 接线 + repo.routing §15 事件
- [x] 38-03-PLAN.md — 召回 adapter（RECALL-01）DeliveryKnowledgeRecallAdapter（fail-closed）+ engine._recall 接线 + knowledge.recalling §15 事件

### Phase 39: 并行调研子 agent

**Goal**: 实现 map 段——先 server 端 RAG/路由快筛，只对「需深入」的仓 fan-out 并行调研子 agent（filter_then_container：每仓独立 claude code 容器、上下文隔离），产出结构化 `PartialPlan`；并落可靠恢复规则：单仓失败可单独重试、仓库重索引使过期 partial 置 stale 重跑。
**Depends on**: Phase 38（路由/召回输出筛选候选仓 + 注入调研上下文）
**Requirements**: RESEARCH-01, RESEARCH-02, RESEARCH-03
**Success Criteria** (what must be TRUE):

  1. 筛选后只对「需深入」的仓起独立 claude code 容器并行调研（filter_then_container，上下文隔离防串味/防超长），每仓产出结构化 `PartialPlan`（research_summary / proposed_changes / candidate_files / api_contracts_exposed / dependencies_on_other_repos，§7）
  2. 单仓 `RepoResearchTask` 失败可单独重试，不重跑整个 `PlanSession`（§6/§14 子任务级状态 pending→running→done/failed）
  3. 仓库被重新索引（commit 变化）使关联 `PartialPlan.valid=False` 置 `stale`，融合前需重跑
  4. 调研全程产出 `repo.research.started` / `repo.research.completed` / `repo.research.failed` trace 事件（§15）

**Plans**: 4 plans

Plans:
- [x] 39-01-PLAN.md — RepoResearchTask + PartialPlan 模型（delivery app §6/§7）+ migration 0013 + curated re-export + 模型守护
- [x] 39-02-PLAN.md — ResearchService 唯一写入入口（状态/单仓重试隔离 RESEARCH-02/重索引 stale RESEARCH-03）+ INV-6 grep 守护
- [x] 39-03-PLAN.md — ResearchDispatchAdapter filter_then_container fan-out（high/medium 起隔离容器、low 走轻量 partial，RESEARCH-01）+ fan-out 建 task/回填 running + started 事件（mock dispatch 单测）
- [x] 39-04-PLAN.md — barrier 聚合 research_complete + 容器回调结果解析为 PartialPlan（结构化+降级）+ completed/failed 事件 + 重索引 stale best-effort 钩子 + engine._research 接线（mock callback 单测；真实容器 E2E deferred）

### Phase 40: 架构师融合 + MergedPlan + PlanValidator + 跨仓依赖

**Goal**: 实现 reduce 段——起一个「架构师」融合子 agent，收齐所有 partial 产出结构化 `MergedPlan`（跨仓契约汇总 / 依赖 DAG / 数据迁移 / 兼容风险 / 发布顺序 / 回滚策略 / execution_plan）落 `PlanVersion`；并以 `PlanValidator` 拦截低质量方案，让架构师 agent「不只是更贵的总结器」。跨仓依赖在 `MergedPlan` 中显式建模，为 v0.8 wave 编码提供拓扑。
**Depends on**: Phase 39（收齐各仓 `PartialPlan` 作融合输入）、Phase 37（canonical `TechnicalPlan`/`PlanVersion` 作融合产物落库底座）
**Requirements**: MERGE-01, MERGE-02, MERGE-03
**Success Criteria** (what must be TRUE):

  1. 架构师融合子 agent 收齐 partial 产出结构化 `MergedPlan`（跨仓契约 / 依赖 DAG / 数据迁移 / 兼容风险 / 发布顺序 / 回滚 / execution_plan），落 `PlanVersion`（经 `TechnicalPlanService`，INV-6）
  2. `PlanValidator` 能拦截契约不一致（暴露↔依赖不匹配）/ 依赖成环 / 迁移顺序不合理 / 发布顺序与依赖不一致 / 缺回滚的方案，失败落 `ArchitectMerge.validation_status=failed` + 报告，按 §14 回退重融合或澄清
  3. 跨仓依赖在 `MergedPlan` 中显式建模（`dependency_dag` + `execution_plan[].dependencies`），为 v0.8 wave 编码提供拓扑
  4. 融合段产出 `plan.merge.started` / `plan.merge.completed` / `plan.validation.failed` trace 事件（§15）

**Plans**: 2 plans

Plans:
- [x] 40-01-PLAN.md — ArchitectMerge 模型 + migration 0014 + MergedPlan §7 schema 校验（复用 technical_plan）+ PlanValidator 5 项跨仓校验纯函数 + 模型/校验守护测试（MERGE-02/03 建模侧）
- [x] 40-02-PLAN.md — ArchitectMergeAdapter(MergeProtocol) 收齐 partial + 可注入 LLM 合成器产 MergedPlan + 经 TechnicalPlanService 落 canonical + engine._merge 接线（pass→done / 限次回退 clarifying·researching / 超限 failed）+ §15 事件 + INV-6 守护（MERGE-01/02/03）

### Phase 41: HITL 澄清 + 事件 taxonomy + 工作流入口

**Goal**: 补上 HITL 澄清回路（不清晰时挂起问用户，回答后仅重跑受影响 partial），把事件 taxonomy 全程产出沉淀为稳定词表（v0.11 对外只是 adapter），并以工作流入口把整条编排端到端跑通——一个需求经「拆分→路由→召回→澄清→并行调研→融合」产出一份带跨仓依赖的 `MergedPlan`。工作流先行。
**Depends on**: Phase 40（融合产物 `MergedPlan` 是端到端跑通的终点；澄清回路插在 researching/merging 之间）
**Requirements**: CLARIFY-01, ENTRY-01, EVENT-01
**Success Criteria** (what must be TRUE):

  1. 编排在不清晰时发 `Clarification` 挂起等用户，回答后仅 `affected_partials` 内的 `RepoResearchTask` 重跑、其余 partial 复用（§14 clarifying 挂起/重跑规则）
  2. 工作流入口端到端跑通编排——一个需求经「拆分→路由→召回→澄清→并行调研→融合」产出一份带跨仓依赖的 `MergedPlan`（工作流先行）
  3. 编排全程产出 §15 统一信封 trace 事件（`{event, session_id, work_item_id?, ts, payload}`，覆盖 work_item.syncing / knowledge.recalling / repo.routing / repo.research.* / clarification.* / plan.merge.* / plan.validation.failed），为 v0.11 对外 adapter 沉淀稳定词表（INV-5，progress/trace 非 CoT）

**Plans**: TBD
**UI hint**: yes

### Phase 42: Chat 入口薄封装

**Goal**: 在工作流入口跑通后，给 Chat 加一层薄封装入口，复用同一底层 orchestration engine 发起方案编排——不并行造两套编排。对话自然语言需求允许无 `WorkItem`，但需显式标记（INV-2）。
**Depends on**: Phase 41（工作流入口端到端验证通过后，Chat 复用同一 engine 薄封装）
**Requirements**: ENTRY-02
**Success Criteria** (what must be TRUE):

  1. Chat 入口薄封装复用同一底层 orchestration engine（不并行造两套编排），从对话即可发起方案编排
  2. Chat 发起的编排与工作流入口产出一致的 `MergedPlan` 与 §15 trace 事件（同一 engine、同一状态机）
  3. Chat 自然语言需求允许 `TechnicalPlan.work_item` 为 null 但显式标记（INV-2）

**Plans**: TBD
**UI hint**: yes

### 📋 Next milestone

v0.8.0 多仓串行编码 → 融合 PR（按 v0.7 `MergedPlan.execution_plan` 跨仓依赖 DAG 分层 wave 执行 + 上游产物注入下游 + 多仓融合 PR）见 `ROADMAP-vNext.md` §v0.8。

## Progress

**Execution Order:** 36 → 37 → 38 → 39 → 40 → 41 → 42（严格顺序；每个 phase 都建立在前序编排骨架之上）

| Phase | Milestone | Plans Complete | Status | Completed |
|-------|-----------|----------------|--------|-----------|
| 36. 前置修复 + 编排引擎骨架 + PlanSession 状态机 | v0.7.0 | 3/3 | Complete | 2026-06-16 |
| 37. canonical TechnicalPlan + TechnicalPlanService + 旧路径软链/迁移 | v0.7.0 | 3/3 | Complete | 2026-06-16 |
| 38. 路由 + 召回接入 | v0.7.0 | 3/3 | Complete | 2026-06-16 |
| 39. 并行调研子 agent | v0.7.0 | 4/4 | Complete | 2026-06-16 |
| 40. 架构师融合 + MergedPlan + PlanValidator + 跨仓依赖 | v0.7.0 | 2/2 | Complete | 2026-06-16 |
| 41. HITL 澄清 + 事件 taxonomy + 工作流入口 | v0.7.0 | 0/0 | Not started | - |
| 42. Chat 入口薄封装 | v0.7.0 | 0/0 | Not started | - |

---
*Previous milestones archived in .planning/milestones/*
