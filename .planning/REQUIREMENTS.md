# Requirements: Friday AI — v0.7.0 方案编排（需求 → 主方案）

**Defined:** 2026-06-16
**Core Value:** 让团队"开箱即用、安全地"把需求自动变成代码；v0.7.0 把"需求 → 一份高质量多仓主技术方案"做成可复用的 map-reduce 多 agent 编排引擎（拆分 → 路由 → 召回 → 澄清 → 并行调研 → 架构师融合），并立 canonical `TechnicalPlan` 脊柱、编排状态机与事件 taxonomy——作为 v0.8 多仓编码、v0.9 SDD 的方案底座。

> 设计底座：`.planning/ROADMAP-vNext.md` §v0.7（流水线 6 段/概念/现状坐标/已确认决策）、`.planning/DOMAIN-MODEL.md` §5（canonical TechnicalPlan + service + 迁移规则）/§6（编排状态机 + 子任务级状态 + 可靠恢复规则 + SDD 扩展点）/§7（PartialPlan/MergedPlan/PlanValidator schema）/§14（PlanSession 转移表）/§15（事件 payload 规格）、`.planning/PREFLIGHT.md`（PF-01/02 必修）。
> 不变量：INV-2（所有技术方案最终可追溯到 WorkItem，chat 自然语言例外可 null 但显式标记）、INV-5（对外暴露 progress/trace 事件非模型私有 CoT）、INV-6（技术方案解析/创建只经 TechnicalPlanService，禁旁路写表）。

## v1 Requirements

本里程碑提交范围。每条映射到 roadmap 某个 phase。

### 前置修复（PF）

> should-fix-before-v0.7：方案质量与 PlanValidator 的地基（PF-01/02 已 verified，见 PREFLIGHT）。

- [ ] **PF-01**: 修 `ai_plan_generation` 工具名漂移（`search_code` → 注册名 `search_repository_code`），并把 `build_langchain_tools` 对未知工具的静默 `continue` 改为 fail-loud（记 error），使 server 端方案生成的检索工具真正生效
- [ ] **PF-02**: 修 `verify_plan` 校验字段从 `tasks` 对齐到 schema 实际的 `execution_plan`，使方案校验不再形同虚设（作为 v0.7 `PlanValidator` 的基础）

### 编排引擎与状态机（ORCH）

- [ ] **ORCH-01**: 立一个可复用的 `ai_plan_research` 编排 engine（工作流与 Chat 共用底层 orchestration 抽象），驱动"拆分 → 路由 → 召回 → 澄清 → 并行调研 → 融合"流水线
- [ ] **ORCH-02**: `PlanSession` 编排状态机可持久化、可恢复（decomposing → routing → recalling → clarifying → researching → merging → done/failed），按 §14 转移表推进并落结构化错误

### canonical 方案脊柱（PLAN）

- [x] **PLAN-01**: 立 canonical `TechnicalPlan`/`PlanVersion` 模型（origin/status 状态 + version + supersedes 版本链 + `content` 存 MergedPlan schema），方案最终可追溯到 `WorkItem`（INV-2，chat 自然语言允许 null）
- [x] **PLAN-02**: `TechnicalPlanService` 作为方案解析/创建/关联的唯一写入入口（`resolve`/`create_from`/`link`，INV-6），新编排经它 eager 创建 canonical
- [x] **PLAN-03**: 存量 3 路径（chat/mcp/workflow）经 service 挂软链 + eager 投影 + read-time lazy 迁移（不全量双写）；旧表迁移期只读、冲突以 canonical 为准、canonical 归档不级联删旧表

### 路由与召回（ROUTE / RECALL）

- [ ] **ROUTE-01**: 编排接入 `RepoRouterV2`（能力树 + LLM），从需求路由出候选仓库 + confidence，写入 `PlanSession`
- [ ] **RECALL-01**: 编排接入历史召回（`DeliveryKnowledgeSearchService`：相似需求/缺陷/复盘/技术方案），把召回上下文注入后续调研

### 并行调研子 agent（RESEARCH）

- [ ] **RESEARCH-01**: 筛选后只对"需深入"的仓 fan-out 并行调研子 agent（filter_then_container：每仓独立 claude code 容器上下文隔离），产出结构化 `PartialPlan`（research_summary/proposed_changes/candidate_files/api_contracts_exposed/dependencies_on_other_repos）
- [ ] **RESEARCH-02**: 单仓 `RepoResearchTask` 失败可单独重试，不重跑整个 `PlanSession`
- [ ] **RESEARCH-03**: 仓库被重新索引（commit 变化）使关联 `PartialPlan.valid=False` 置 `stale`，融合前需重跑

### 架构师融合（MERGE）

- [ ] **MERGE-01**: 起"架构师"融合子 agent，收齐 partial 产出结构化 `MergedPlan`（跨仓契约汇总 / 依赖 DAG / 数据迁移 / 兼容风险 / 发布顺序 / 回滚策略 / execution_plan），落 `PlanVersion`
- [ ] **MERGE-02**: `PlanValidator` 能拦截契约不一致（暴露↔依赖不匹配）/ 依赖成环 / 迁移顺序不合理 / 发布顺序与依赖不一致 / 缺回滚的方案，失败落 `ArchitectMerge.validation_status=failed` + 报告
- [ ] **MERGE-03**: 跨仓依赖在 `MergedPlan` 中显式建模（dependency_dag + execution_plan[].dependencies），为 v0.8 wave 编码提供拓扑

### 澄清与入口（CLARIFY / ENTRY）

- [ ] **CLARIFY-01**: HITL 澄清回路：编排在不清晰时发 `Clarification` 挂起等用户，回答后仅 `affected_partials` 内的 `RepoResearchTask` 重跑，其余 partial 复用
- [ ] **ENTRY-01**: 工作流入口端到端跑通编排——一个需求经"拆分→路由→召回→澄清→并行调研→融合"产出一份带跨仓依赖的 `MergedPlan`（工作流先行）
- [ ] **ENTRY-02**: Chat 入口薄封装复用同一底层 orchestration engine（不并行造两套编排）

### 事件 taxonomy（EVENT）

- [ ] **EVENT-01**: 编排全程产出 §15 trace 事件（统一信封 `{event, session_id, work_item_id?, ts, payload}`，taxonomy：work_item.syncing / knowledge.recalling / repo.routing / repo.research.* / clarification.* / plan.merge.* / plan.validation.failed），为 v0.11 对外 adapter 沉淀稳定词表（INV-5，progress/trace 非 CoT）

## v2 Requirements

延后到后续里程碑，已记录但不在本 roadmap。

### 多仓编码（CODE）— v0.8

- **CODE-01**: `RepoCodingTask` 多仓 wave 编码（DAG 拓扑分层）+ 上游 `produced_artifacts` 注入下游 + 融合 PR（接 v0.7 `MergedPlan.execution_plan`）
- **CODE-02**: 编码遇阻走 question 抛人（HITL 回路，非全自动 replan）

### SDD / OpenSpec（SDD）— v0.9

- **SDD-01**: `PlanSession` 对 SDD 仓库产 spec draft（v0.7 仅预留扩展点字段位，完整状态机/gate/评审在 v0.9）

### 对外开放（OPEN）— v0.11

- **OPEN-01**: 事件 taxonomy 经 adapter 对外透出为 OpenAI/Anthropic 兼容 progress/trace（复用 v0.7 EVENT-01 词表）

## Out of Scope

明确排除，附理由，避免反复回炉。

| Feature | Reason |
|---------|--------|
| 多仓 wave 编码 → 融合 PR | v0.8 主题；v0.7 只产方案（含 execution_plan 拓扑），不落代码 |
| 编码中全自动 replan/回溯 | 最高阶能力，v0.8 用"抛 question 给人"过渡，全自动留 backlog |
| SDD spec 完整状态机 / gate / 评审 / 验收 | v0.9 主题；v0.7 仅在 `PlanSession`/产物预留 SDD 扩展点字段位 |
| 事件 taxonomy 对外 API adapter（OpenAI/Anthropic 透出） | v0.11 主题；v0.7 只产出内部 trace 事件，对外暴露是不同 adapter |
| 标准双向 tool_calls 协议（客户端自带工具） | 等"客户端自带工具"诉求再做；v0.7 内部工具是服务端闭环 |
| 全量双写新旧方案表 | 明确选 service 投影（eager + lazy migration），旧表为历史输入非并行事实源 |
| 图片向量库 / 视觉精确定位 | 与 v0.7 无关，沿用 v0.6 决策留 backlog |

## Traceability

哪个 phase 覆盖哪些需求。roadmap 创建时确认/调整（建议映射，v0.6 结束于 Phase 35，本里程碑从 Phase 36 续号）。

| Requirement | Phase | Status |
|-------------|-------|--------|
| PF-01 | Phase 36 | Pending |
| PF-02 | Phase 36 | Pending |
| ORCH-01 | Phase 36 | Pending |
| ORCH-02 | Phase 36 | Pending |
| PLAN-01 | Phase 37 | Complete |
| PLAN-02 | Phase 37 | Complete |
| PLAN-03 | Phase 37 | Complete |
| ROUTE-01 | Phase 38 | Pending |
| RECALL-01 | Phase 38 | Pending |
| RESEARCH-01 | Phase 39 | Pending |
| RESEARCH-02 | Phase 39 | Pending |
| RESEARCH-03 | Phase 39 | Pending |
| MERGE-01 | Phase 40 | Pending |
| MERGE-02 | Phase 40 | Pending |
| MERGE-03 | Phase 40 | Pending |
| CLARIFY-01 | Phase 41 | Pending |
| ENTRY-01 | Phase 41 | Pending |
| EVENT-01 | Phase 41 | Pending |
| ENTRY-02 | Phase 42 | Pending |

**Coverage:**

- v1 requirements: 19 total
- Mapped to phases: 19/19 ✓
- Unmapped: 0

---
*Requirements defined: 2026-06-16*
*Last updated: 2026-06-16 — traceability confirmed against ROADMAP.md (Phases 36–42, 19/19 mapped)*
