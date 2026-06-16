# Roadmap: Friday AI

## Milestones

- 🚧 **v0.8.0 多仓串行编码 → 融合 PR** — Phases 43–47 (in progress)
- ✅ **v0.7.0 方案编排（需求 → 主方案）** — Phases 36–42 (shipped 2026-06-16) — [archive](./milestones/v0.7.0-ROADMAP.md)
- ✅ **v0.6.0 领域脊柱 + 知识图谱补全** — Phases 27–35 (shipped 2026-06-15) — [archive](./milestones/v0.6.0-ROADMAP.md)
- ✅ **v0.5.0 索引检索地基与排除文件** — Phases 22–26 (shipped 2026-06-15) — [archive](./milestones/v0.5.0-ROADMAP.md)
- ✅ **v0.4.0 工作流系统契约重构** — Phases 17–21 (shipped 2026-06-13) — [archive](./milestones/v0.4.0-ROADMAP.md)
- ✅ **v0.3.0 交付知识图谱** — Phases 12–16 (shipped 2026-06-12) — [archive](./milestones/v0.3.0-ROADMAP.md)
- ✅ **v0.2.0 用户身份令牌与 Agent 工具打通** — Phases 6–11 (shipped 2026-06-10) — [archive](./milestones/v0.2.0-ROADMAP.md)
- ✅ **v0.1.0 首启初始化向导** — Phases 1–5 (shipped 2026-06-09) — [archive](./milestones/v0.1.0-ROADMAP.md)

> 跨里程碑前瞻路线（v0.8–v0.11）与设计底座见 `ROADMAP-vNext.md`、`DOMAIN-MODEL.md`、`PREFLIGHT.md`。

## Phases

<details>
<summary>✅ v0.6.0 领域脊柱 + 知识图谱补全 (Phases 27–35) — SHIPPED 2026-06-15</summary>

完整阶段详情见 [milestones/v0.6.0-ROADMAP.md](./milestones/v0.6.0-ROADMAP.md)。

</details>

<details>
<summary>✅ v0.7.0 方案编排（需求 → 主方案）(Phases 36–42) — SHIPPED 2026-06-16</summary>

- [x] Phase 36: 前置修复 + 编排引擎骨架 + PlanSession 状态机 (3/3 plans) — PF-01, PF-02, ORCH-01, ORCH-02 — completed 2026-06-16
- [x] Phase 37: canonical TechnicalPlan + TechnicalPlanService + 旧路径软链/迁移 (3/3 plans) — PLAN-01..03 — completed 2026-06-16
- [x] Phase 38: 路由 + 召回接入 (3/3 plans) — ROUTE-01, RECALL-01 — completed 2026-06-16
- [x] Phase 39: 并行调研子 agent (4/4 plans) — RESEARCH-01..03 — completed 2026-06-16
- [x] Phase 40: 架构师融合 + MergedPlan + PlanValidator + 跨仓依赖 (2/2 plans) — MERGE-01..03 — completed 2026-06-16
- [x] Phase 41: HITL 澄清 + 事件 taxonomy + 工作流入口 (3/3 plans) — CLARIFY-01, ENTRY-01, EVENT-01 — completed 2026-06-16
- [x] Phase 42: Chat 入口薄封装 (1/1 plans) — ENTRY-02 — completed 2026-06-16

完整阶段详情见 [milestones/v0.7.0-ROADMAP.md](./milestones/v0.7.0-ROADMAP.md)。里程碑审计 passed（19/19 需求、INV-2/5/6 成立）见 [v0.7.0-MILESTONE-AUDIT.md](./milestones/v0.7.0-MILESTONE-AUDIT.md)。

> **v0.8 开工首项 tech-debt（v0.7 audit D-2）**：chat deep-research 自动回流接线缺口——主入口「工作流先行」端到端已闭环，chat fire-and-forget 编排进 researching、容器在途完成后无消费者驱动续跑。已纳入本里程碑 Phase 43（RESUME-01 通用 resume 回流通路）。

</details>

### 🚧 v0.8.0 多仓串行编码 → 融合 PR (In Progress)

**Milestone Goal:** 把 v0.7 产的主方案（`MergedPlan.execution_plan` + 跨仓依赖 DAG）落成多仓代码：按跨仓依赖分层 wave 执行、上游产物注入下游、关联多仓融合 PR、编码遇阻抛 question 给人。**显式非目标：不做编码中全自动回溯重规划。** 详细数据模型见 `DOMAIN-MODEL.md` §6（`RepoCodingTask`：wave/`depends_on` DAG/`produced_artifacts` + 可靠恢复规则 + SDD 扩展点），前置修复台账见 `PREFLIGHT.md`（PF-06/07）。

**依赖链（严格顺序）：** 编码 env 对齐 + 通用 resume 回流地基(43) → RepoCodingTask + DAG 拓扑分层 + wave 调度(44) → 上游产物提取/注入下游(45) → 多仓融合 PR + 跨仓关联(46) → 编码遇阻 question 抛人(47)。PF-06（编码 env）+ RESUME-01（resume 通路）是 callback 驱动多 wave 的前置地基；44 立 RepoCodingTask 与 wave 调度；45 在 wave 之间传产物；46 把 wave 结果落 PR；47 补遇阻 HITL 回路（复用 43 的 resume 通路）。

- [x] **Phase 43: 编码 env 对齐 + 通用 resume 回流地基** - 修 PF-06（workflow 编码路径 branch strategy / git token env 对齐 chat）+ 立通用 `coding`/`plan_session` → 工作流/会话 resume 回流通路（消化 v0.7 audit D-2），为 callback 驱动多 wave 铺底 (completed 2026-06-16)
- [x] **Phase 44: RepoCodingTask + execution_plan DAG 拓扑分层 + wave 调度** - 立 `RepoCodingTask`（wave/`depends_on` DAG/`produced_artifacts`/`follow_openspec` 预留）+ 按 `execution_plan[].dependencies` 拓扑分层（消化 PF-07，不再全并行）+ wave N 全 done 才触发 wave N+1 (completed 2026-06-16)
- [ ] **Phase 45: 上游产物提取 + 注入下游 wave** - 上游 wave `produced_artifacts`（API 契约/OpenAPI/diff）提取 + 注入下游 wave prompt/global_context
- [ ] **Phase 46: 多仓融合 PR + 跨仓 PR 关联** - 各仓产出关联 PR/MR（diff base 用各仓正确 `target_branch` 非假设 master）+ 跨仓 PR cross-ref 关联
- [ ] **Phase 47: 编码遇阻 → question 抛人（HITL，非全自动 replan）** - task 侧发起 question（复用已有 question 协议 + orchestrator resume）抛给用户/orchestrator，非全自动回溯重规划

## Phase Details

### Phase 43: 编码 env 对齐 + 通用 resume 回流地基

**Goal**: 先把多仓 wave 编码的两块地基补齐——修 PF-06（workflow 编码路径 `AICodingNode` 未注入 branch strategy / git token env，对齐 chat `coding_session_service` 已有的 env 注入）+ 立一个通用的 `coding`/`plan_session` → 工作流/会话 resume 回流通路（消化 v0.7 audit D-2：chat fire-and-forget 编排进 researching、容器在途完成后无消费者驱动续跑），为后续 callback 驱动的多 wave 调度提供统一回流通路。
**Depends on**: Nothing（本里程碑首个 phase；PF-06 为 should-fix-before-v0.8、resume 通路是 wave 调度前置地基）
**Requirements**: PF-06, RESUME-01
**Success Criteria** (what must be TRUE):

  1. workflow 编码路径 `AICodingNode` 注入 branch strategy / git token env（对齐 chat `coding_session_service`），私有仓 clone 成功且用正确目标分支（不再落默认 `friday/task-{id}`）（PF-06）
  2. 立通用 resume 回流通路：`coding`/`plan_session` 容器在途完成后，callback 能驱动对应工作流节点 / 会话续跑——消化 v0.7 audit D-2（chat deep-research 自动回流缺口），happy-path 与 deep-research 路径均可闭环
  3. resume 通路对工作流入口与 chat 入口一致可用、不重复造两套（复用既有 `waiting_event` + callback resume 范式）

**Plans:** 4/4 plans complete

- [x] 43-01-PLAN.md — PF-06：`_run_repo_coding` 注入对称 git token env + branch env + SSH→HTTPS 改写（wave 1）
- [x] 43-02-PLAN.md — RESUME-01：抽入口无关共享续驱 helper `adrive_plan_session_to_pause_or_terminal` + 单测（wave 1）
- [x] 43-03-PLAN.md — RESUME-01：新增 `_schedule_chat_plan_resume` + 接线 plan_research 分支 + 闭环集成测试（wave 2）
- [x] 43-04-PLAN.md — RESUME-01：节点/工具 advance 循环复用共享 helper + 工具文案如实更新（wave 3）

### Phase 44: RepoCodingTask + execution_plan DAG 拓扑分层 + wave 调度

**Goal**: 立 `RepoCodingTask` 操作态模型（wave / `depends_on` DAG / `produced_artifacts` / `follow_openspec` 预留 SDD 扩展点），把 `MergedPlan.execution_plan` 的 `dependencies` 真正消费——按跨仓依赖拓扑分层成 wave（消化 PF-07：`dependencies` 不再仅 schema 声明、下游不再无条件全并行），wave N 全部 done 才触发 wave N+1。
**Depends on**: Phase 43（resume 回流通路 + 编码 env 对齐是 callback 驱动多 wave 的前置）
**Requirements**: WAVE-01, WAVE-02
**Success Criteria** (what must be TRUE):

  1. `RepoCodingTask` 模型落库（plan_version FK / repository FK / wave int / `depends_on` M2M self DAG / status / `produced_artifacts` JSON / `follow_openspec` 预留），经单一写入入口（INV-6 精神，禁旁路写表）
  2. 按 `execution_plan[].dependencies` 拓扑分层成 wave，下游不再无条件全并行（消化 PF-07：`AICodingNode` 真正读 dependencies）
  3. wave N 全部 done 才触发 wave N+1，依赖未满足的仓不提前 dispatch（§14 RepoCodingTask 拓扑推进 + 可靠恢复）
  4. wave 失败 / 部分回滚语义明确：单 wave 内单仓失败的隔离边界与整体回滚语义有定义且有测试

**Plans:** 5/5 plans complete
Plans:
**Wave 1**

- [x] 44-01-PLAN.md — RepoCodingTask 模型 + barrel + 迁移 0017 + 模型测试（wave 1）
- [x] 44-02-PLAN.md — wave_layering 拓扑分层纯函数（task-id DAG→仓级 wave）+ 测试（wave 1）

**Wave 2** *(blocked on Wave 1 completion)*

- [x] 44-03-PLAN.md — RepoCodingTaskService 单一写入入口 + INV-6 守护 + 测试（wave 2）

**Wave 3** *(blocked on Wave 2 completion)*

- [x] 44-04-PLAN.md — wave_progression 入口无关推进 helper（gate/失败隔离/传递闭包下游阻断/幂等）+ 测试（wave 3）

**Wave 4** *(blocked on Wave 3 completion)*

- [x] 44-05-PLAN.md — AICodingNode wave 分批 dispatch + callback 驱动推进 + 集成测试（wave 4）

### Phase 45: 上游产物提取 + 注入下游 wave

**Goal**: 把上游 wave 的产物（API 契约 / OpenAPI / diff）提取落 `RepoCodingTask.produced_artifacts`，并注入下游 wave 的 prompt / `global_context`，使下游仓编码能消费上游契约（如 wave1 后端 → 提取 API 契约 → 注入 wave2 前端 `global_context`）。
**Depends on**: Phase 44（wave 调度 + `RepoCodingTask.produced_artifacts` 字段）
**Requirements**: ARTIFACT-01, ARTIFACT-02
**Success Criteria** (what must be TRUE):

  1. 上游 wave 完成后提取 `produced_artifacts`（API 契约 / OpenAPI / diff）落 `RepoCodingTask.produced_artifacts`
  2. 下游 wave dispatch 时把上游 `produced_artifacts` 注入容器 prompt / `global_context`
  3. 端到端：构造跨仓依赖方案，断言 wave2 容器 prompt / 上下文含 wave1 产出的契约（产物传递正确）

**Plans:** 3 plans
**Wave 1**

- [ ] 45-01-PLAN.md — ARTIFACT-01：artifact_extraction.py 纯函数 + record_produced_artifacts 单一写入 + wave_progression 提取钩子 + INV-6 字段级守护（wave 1）

**Wave 2** *(blocked on Wave 1 completion)*

- [ ] 45-02-PLAN.md — ARTIFACT-02：artifact_injection.py 收集/渲染 + coding.py dispatch 链 defaulted 透传注入 + 零回归断言（wave 2）

**Wave 3** *(blocked on Wave 2 completion)*

- [ ] 45-03-PLAN.md — ARTIFACT-01+02：端到端产物传递集成（wave1 done→提取→wave2 prompt 含契约）+ 幂等/fail-soft + phase gate（wave 3）

### Phase 46: 多仓融合 PR + 跨仓 PR 关联

**Goal**: 把多仓 wave 编码结果产出关联的 PR/MR——各仓 diff base 用各仓正确的 `target_branch`（非假设 master，对齐 v0.6 坐实的 MR target_branch 锚定），并做跨仓 PR 关联（cross-ref），可追溯到同一 `TechnicalPlan`/`WorkItem`。
**Depends on**: Phase 44（wave 编码产出）、Phase 45（上游产物传递）
**Requirements**: PR-01, PR-02
**Success Criteria** (what must be TRUE):

  1. 多仓产出关联的 PR/MR，各仓 diff base 用各仓正确的 `target_branch`（非假设 master）
  2. 跨仓 PR 互相引用（cross-ref），可追溯到同一 `TechnicalPlan`/`WorkItem`
  3. PR 创建复用既有 git 平台 client + `aresolve_git_token`（per-repo 优先 → host 实例池 fallback），缺凭证行为不回退

**UI hint**: maybe（多仓 PR 关联结果展示可能复用既有执行/方案视图，reuse-first）

### Phase 47: 编码遇阻 → question 抛人（HITL，非全自动 replan）

**Goal**: 补编码遇阻的 HITL 回路——task 侧发起 question（复用已有 question 协议契约，补 task 侧发起 + orchestrator resume），抛给用户 / orchestrator 等回答后续跑。**显式非目标：不做编码中全自动回溯重规划。**
**Depends on**: Phase 43（resume 回流通路）、Phase 44（wave 编码 task）
**Requirements**: HITL-01
**Success Criteria** (what must be TRUE):

  1. 编码容器遇阻时 task 侧能发起 question（复用已有 question 协议契约），不再走「Server 端不再重试」死路
  2. question 抛给用户 / orchestrator，回答后经 Phase 43 resume 通路驱动对应 wave/task 续跑
  3. 显式非目标守护：编码遇阻只抛人、不触发全自动 replan / 重调研改方案（全自动回溯留 backlog）

**UI hint**: yes（question 抛人复用既有 `ask_user_question` 澄清卡片，reuse-first，无新 Vue 组件）

## Progress

**Execution Order:** 43 → 44 → 45 → 46 → 47（严格顺序；每个 phase 都建立在前序编码骨架之上）

| Phase | Milestone | Plans Complete | Status | Completed |
|-------|-----------|----------------|--------|-----------|
| 43. 编码 env 对齐 + 通用 resume 回流地基 | v0.8.0 | 4/4 | Complete   | 2026-06-16 |
| 44. RepoCodingTask + execution_plan DAG 拓扑分层 + wave 调度 | v0.8.0 | 5/5 | Complete   | 2026-06-16 |
| 45. 上游产物提取 + 注入下游 wave | v0.8.0 | 0/? | Not started | — |
| 46. 多仓融合 PR + 跨仓 PR 关联 | v0.8.0 | 0/? | Not started | — |
| 47. 编码遇阻 → question 抛人（HITL） | v0.8.0 | 0/? | Not started | — |

---
*Previous milestones archived in .planning/milestones/*
