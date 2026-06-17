# Roadmap: Friday AI

## Milestones

- 🚧 **v0.9.0 SDD / OpenSpec 支持（重型）** — Phases 48–52 (planning)
- ✅ **v0.8.0 多仓串行编码 → 融合 PR** — Phases 43–47 (shipped 2026-06-17) — [archive](./milestones/v0.8.0-ROADMAP.md)
- ✅ **v0.7.0 方案编排（需求 → 主方案）** — Phases 36–42 (shipped 2026-06-16) — [archive](./milestones/v0.7.0-ROADMAP.md)
- ✅ **v0.6.0 领域脊柱 + 知识图谱补全** — Phases 27–35 (shipped 2026-06-15) — [archive](./milestones/v0.6.0-ROADMAP.md)
- ✅ **v0.5.0 索引检索地基与排除文件** — Phases 22–26 (shipped 2026-06-15) — [archive](./milestones/v0.5.0-ROADMAP.md)
- ✅ **v0.4.0 工作流系统契约重构** — Phases 17–21 (shipped 2026-06-13) — [archive](./milestones/v0.4.0-ROADMAP.md)
- ✅ **v0.3.0 交付知识图谱** — Phases 12–16 (shipped 2026-06-12) — [archive](./milestones/v0.3.0-ROADMAP.md)
- ✅ **v0.2.0 用户身份令牌与 Agent 工具打通** — Phases 6–11 (shipped 2026-06-10) — [archive](./milestones/v0.2.0-ROADMAP.md)
- ✅ **v0.1.0 首启初始化向导** — Phases 1–5 (shipped 2026-06-09) — [archive](./milestones/v0.1.0-ROADMAP.md)

> 跨里程碑前瞻路线（v0.9–v0.11）与设计底座见 `ROADMAP-vNext.md`、`DOMAIN-MODEL.md`、`PREFLIGHT.md`。

## Phases

### 🚧 v0.9.0 SDD / OpenSpec 支持（重型）(Planning)

**Milestone Goal:** 让 spec-driven development 成为可治理的过程资产——仓库打标（检测 `openspec/`）→ 方案产 openspec spec → spec 状态机 + 编码前置 gate + 评审状态 → spec↔需求/PR 关联 → 交付验收。复用 v0.7/v0.8 预留扩展点（`Document.SDD_SPEC` 枚举、`RepoCodingTask.follow_openspec` 字段、`Repository.facets` JSON、task `setting_sources=["project"]`），做完整 spec 生命周期与治理。

- [x] **Phase 48: SDD 仓库检测 + facets 打标 + 前端标签** - 索引后检测 `openspec/` → `facets["methodology"]="SDD"` + 列表/详情方法论标签 — completed 2026-06-17
- [x] **Phase 49: 方案产 openspec spec + Document(sdd_spec)** - SDD 仓库方案编排融合阶段额外产 spec draft，落 `Document(sdd_spec)` 并关联来源 — completed 2026-06-17
- [x] **Phase 50: spec 状态机 + 变更记录 + 评审状态 + 前端展示** - 完整 spec 生命周期状态机 + 不可篡改评审记录 + spec 列表/详情/状态流转 UI — completed 2026-06-17
- [x] **Phase 51: 编码前置 gate + openspec skill 编码策略** - SDD 仓库编码前校验 spec 已 approved（gate）+ 容器注入 openspec 指引 — completed 2026-06-17
- [x] **Phase 52: spec↔需求/PR 关联 + 交付验收视图** - spec 挂 `WorkItem` + 关联实现 PR + 沿链路可追溯的交付验收视图

## Phase Details

### Phase 48: SDD 仓库检测 + facets 打标 + 前端标签

**Goal**: 索引完成后自动识别 spec-driven 仓库并打标，用户在前端可识别 SDD 仓库
**Depends on**: Nothing (本里程碑首个 phase；复用既有 `Repository.facets` JSON 与索引完成钩子)
**Requirements**: SDD-01, SDD-02
**Success Criteria** (what must be TRUE):

  1. 索引完成后，仓库根含 `openspec/` 目录的仓库被自动写入 `facets["methodology"]="SDD"`；检测/打标失败为 best-effort，不阻断索引 success 终态
  2. 不含 `openspec/` 的仓库不被误标；重复索引幂等，标记不重复或漂移
  3. 用户在仓库列表与详情页可见 "SDD" 方法论标签，据此识别 spec-driven 仓库

**Plans**: 2 plans

- [x] 48-01-PLAN.md — 后端 SDD 检测器 sdd_detect.py + 索引 FINALIZING best-effort 挂接（SDD-01）
- [x] 48-02-PLAN.md — 前端 SDD 方法论徽标 + i18n + 守护测试，接入知识树卡片/详情（SDD-02）

**UI hint**: yes

### Phase 49: 方案产 openspec spec + Document(sdd_spec)

**Goal**: SDD 仓库的方案编排额外产出可追溯的 openspec spec draft 并持久化为内部生成文档
**Depends on**: Phase 48 (需先有 SDD 仓库打标才能在融合阶段判定是否产 spec)
**Requirements**: SPEC-01, SPEC-02
**Success Criteria** (what must be TRUE):

  1. SDD 仓库经方案编排（`PlanSession` 融合阶段，接 v0.7 扩展点）额外产出 openspec 格式 spec draft（change proposal / spec delta）
  2. spec draft 落 `Document(document_type=sdd_spec, source_kind=internal_generated)`，且经 `DocumentService` 单一入口写入（INV-6，禁旁路写表）
  3. 非 SDD 仓库的方案编排不产 spec（零回归）
  4. 产出的 spec draft 关联到来源 `WorkItem` 与 `PlanVersion`，可追溯其生成上下文

**Plans**: 4 plans

- [x] 49-01-PLAN.md — SddSpec 脊柱模型 + status/change_kind 枚举 + 建表 migration + DocumentService.create_internal_spec（数据底座，SPEC-01/SPEC-02）
- [x] 49-02-PLAN.md — SddSpecService.create_draft（幂等单一写入入口）+ SddSpec INV-6 grep 守护（SPEC-01/SPEC-02）
- [x] 49-03-PLAN.md — spec_generation（SddSpecSynthesizer + agenerate_specs_for_plan）+ EVENT_SPEC_DRAFTED + 对齐守护（SPEC-01/SPEC-02）
- [x] 49-04-PLAN.md — ArchitectMergeAdapter._handle_pass best-effort 挂接 + 端到端/零回归/fail-soft/幂等测试（SPEC-01/SPEC-02）

### Phase 50: spec 状态机 + 变更记录 + 评审状态 + 前端展示

**Goal**: spec 具备完整可治理生命周期，评审留痕、用户可见可操作
**Depends on**: Phase 49 (需先有 spec draft 实体才能挂状态机与评审)
**Requirements**: SPECST-01, SPECST-02, SPECST-03
**Success Criteria** (what must be TRUE):

  1. spec 经单一 service 入口完成 `draft → in_review → approved → implemented → archived` 状态流转，非法流转被拒
  2. spec 评审产生不可篡改记录（reviewer / decision approve|reject / comment / time），审批驱动状态流转
  3. 用户在前端可见 spec 列表 / 详情 / 当前状态与评审记录
  4. 用户可在前端发起状态流转（提交评审 / 批准 / 驳回）并看到结果

**Plans**: 5 plans

- [x] 50-01-PLAN.md — SddSpecReview append-only 模型 + ReviewDecision 枚举 + re-export + migration（SPECST-02）
- [x] 50-02-PLAN.md — SddSpecService 状态机流转 + SddSpecTransitionError + 单一事务评审驱动 + INV-6 守护扩展（SPECST-01/02）
- [x] 50-03-PLAN.md — /api/specs/ REST（list/detail/transition）+ 权限分流 + read_only 序列化器（SPECST-01/02/03）
- [x] 50-04-PLAN.md — 前端基础：api/specs.ts + 类型 + SddSpecStatusBadge + SpecReviewTimeline + specs i18n（SPECST-03）
- [x] 50-05-PLAN.md — 前端页面：列表/详情 + SpecTransitionActions/SpecReviewDialog + 侧边栏入口（SPECST-03）

**UI hint**: yes

### Phase 51: 编码前置 gate + openspec skill 编码策略

**Goal**: SDD 仓库编码前强制 spec 已批准，且编码容器遵循 openspec 流程
**Depends on**: Phase 50 (gate 依赖 spec 已具备 `approved` 状态判定)
**Requirements**: GATE-01, GATE-02
**Success Criteria** (what must be TRUE):

  1. SDD 仓库（`RepoCodingTask.follow_openspec=True`）编码派发前校验关联 spec 已 `approved`，未批准则拦截编码（gate）并如实标注阻断原因，不静默放行
  2. spec 已 `approved` 的 SDD 仓库编码正常放行派发
  3. SDD 仓库编码容器注入 openspec 指引（task `system_prompt` 按仓库类型注入点 + 复用 `setting_sources=["project"]` 原生加载仓库内 `.claude/skills`），编码遵循 openspec 流程
  4. 非 SDD 仓库编码不受 gate 与注入影响（零回归）

**Plans**: 3 plans

- [x] 51-01-PLAN.md — RepoCodingTaskService follow_openspec 置位 + mark_gate_blocked 单一写入入口（GATE-01）
- [x] 51-02-PLAN.md — AICodingNode._dispatch_wave 前置 gate（fail-closed + 单仓隔离 + 下游阻断）+ env_FRIDAY_TASK_FOLLOW_OPENSPEC 注入（GATE-01/GATE-02）
- [x] 51-03-PLAN.md — task TaskConfig.follow_openspec + _get_system_prompt openspec 指引段（复用 setting_sources 原生加载 .claude/skills）（GATE-02）

### Phase 52: spec↔需求/PR 关联 + 交付验收视图

**Goal**: 沿 spec → 需求 → 实现 PR 的完整链路可追溯一次 spec-driven 交付状态
**Depends on**: Phase 51 (实现 PR 由 gate 放行后的编码产出回填)
**Requirements**: LINK-01, LINK-02
**Success Criteria** (what must be TRUE):

  1. spec 挂接到对应 `WorkItem`，并关联其实现 PR/MR（编码产出回填）
  2. 用户可见交付验收视图，沿 spec → `WorkItem` → 实现 PR 链路追溯一次需求的 spec-driven 交付状态
  3. 关联回填全程 fail-soft，链断 / 缺数据时降级展示而非报错

**Plans**: 3 plans

- [x] 52-01-PLAN.md — 后端 SddSpec.implementation_prs 字段 + migration + SddSpecService.link_implementation_pr + _finalize_and_notify fail-soft 回填挂接（LINK-01）
- [x] 52-02-PLAN.md — 后端 SddSpecDetailSerializer 扩 implementation_prs + work_item url/title + plan_version 追溯摘要（LINK-01/LINK-02）
- [x] 52-03-PLAN.md — 前端 spec 详情页「交付验收」追溯面板（WorkItem→spec→PR）+ i18n + fail-soft 降级 + vitest（LINK-02）

**UI hint**: yes

<details>
<summary>✅ v0.8.0 多仓串行编码 → 融合 PR (Phases 43–47) — SHIPPED 2026-06-17</summary>

- [x] Phase 43: 编码 env 对齐 + 通用 resume 回流地基 (4/4 plans) — PF-06, RESUME-01 — completed 2026-06-16
- [x] Phase 44: RepoCodingTask + execution_plan DAG 拓扑分层 + wave 调度 (5/5 plans) — WAVE-01, WAVE-02 — completed 2026-06-16
- [x] Phase 45: 上游产物提取 + 注入下游 wave (3/3 plans) — ARTIFACT-01, ARTIFACT-02 — completed 2026-06-16
- [x] Phase 46: 多仓融合 PR + 跨仓 PR 关联 (2/2 plans) — PR-01, PR-02 — completed 2026-06-16
- [x] Phase 47: 编码遇阻 → question 抛人（HITL，非全自动 replan）(2/2 plans) — HITL-01 — completed 2026-06-17

完整阶段详情见 [milestones/v0.8.0-ROADMAP.md](./milestones/v0.8.0-ROADMAP.md)。里程碑审计 passed（9/9 需求、integration_ok、Nyquist 5/5）见 [v0.8.0-MILESTONE-AUDIT.md](./milestones/v0.8.0-MILESTONE-AUDIT.md)。

</details>

<details>
<summary>✅ v0.7.0 方案编排（需求 → 主方案）(Phases 36–42) — SHIPPED 2026-06-16</summary>

完整阶段详情见 [milestones/v0.7.0-ROADMAP.md](./milestones/v0.7.0-ROADMAP.md)。里程碑审计 passed（19/19 需求、INV-2/5/6 成立）见 [v0.7.0-MILESTONE-AUDIT.md](./milestones/v0.7.0-MILESTONE-AUDIT.md)。

</details>

<details>
<summary>✅ v0.6.0 领域脊柱 + 知识图谱补全 (Phases 27–35) — SHIPPED 2026-06-15</summary>

完整阶段详情见 [milestones/v0.6.0-ROADMAP.md](./milestones/v0.6.0-ROADMAP.md)。

</details>

## Progress

**Execution Order:** Phases 48–52 严格顺序执行：48 → 49 → 50 → 51 → 52。依赖链 = 打标(48) → 产 spec(49) → spec 状态机/评审(50) → 编码 gate(51) → 关联/验收(52)。

| Phase | Milestone | Plans Complete | Status | Completed |
|-------|-----------|----------------|--------|-----------|
| 48. SDD 仓库检测 + facets 打标 + 前端标签 | v0.9.0 | 2/2 | ✅ Complete (verify human_needed) | 2026-06-17 |
| 49. 方案产 openspec spec + Document(sdd_spec) | v0.9.0 | 4/4 | ✅ Complete | 2026-06-17 |
| 50. spec 状态机 + 变更记录 + 评审状态 + 前端展示 | v0.9.0 | 5/5 | ✅ Complete (verify human_needed) | 2026-06-17 |
| 51. 编码前置 gate + openspec skill 编码策略 | v0.9.0 | 3/3 | ✅ Complete (verify human_needed) | 2026-06-17 |
| 52. spec↔需求/PR 关联 + 交付验收视图 | v0.9.0 | 3/3 | Complete | - |

所有先前里程碑（v0.1.0–v0.8.0，Phases 1–47）均已交付归档。

---
*Previous milestones archived in .planning/milestones/*
