# Roadmap: Friday AI

## Milestones

- 🚧 **v0.10.0 操作审计治理** — Phases 53–55 (planning)
- ✅ **v0.9.0 SDD / OpenSpec 支持（重型）** — Phases 48–52 (shipped 2026-06-17) — [archive](./milestones/v0.9.0-ROADMAP.md)
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

### 🚧 v0.10.0 操作审计治理 (Planning)

**Milestone Goal:** 立起统一 `AuditEvent` 横切审计模型，对成员/凭证/飞书同步/仓库权限/排除规则/清理任务/API key 等敏感操作做不可篡改留痕，并提供查询/导出——可查、可追溯、可审计。系统管理员 = 现有 `is_superuser`（不新建角色）；v0.5 既有分散埋点（`purge.started/completed`、`TriggerLog`/`ActionLog`）收口到统一表。设计底座：`ROADMAP-vNext.md §v0.10`、`DOMAIN-MODEL.md §11`。

- [x] **Phase 53: `AuditEvent` 模型 + emit 地基** (2/2 plans) - 统一审计模型（actor/action/target/before-after/source/时间）+ 单一写入入口 + append-only 不可篡改 + fail-soft emit 机制 + 凭证脱敏 — AUDIT-01, AUDIT-02 — completed 2026-06-17
- [x] **Phase 54: 敏感操作全量覆盖 emit** (2/2 plans) - 身份与权限类 + 凭证与数据治理类敏感操作经统一入口 emit 审计；v0.5 排除/清理埋点收口统一表 — AUDITCOV-01, AUDITCOV-02 — completed 2026-06-17
- [x] **Phase 55: 审计查询 API + 前端视图 + 导出** (3/3 plans) - 审计查询 REST（过滤+分页，superuser fail-closed）+ 前端列表/过滤/before-after 详情 + CSV/JSON 导出 — AUDITUI-01, AUDITUI-02 — completed 2026-06-17

## Phase Details

### Phase 53: `AuditEvent` 模型 + emit 地基

**Goal**: 立起统一不可篡改审计模型与 fail-soft emit 地基，供后续所有敏感操作复用
**Depends on**: Nothing (本里程碑首个 phase；复用既有 Django app 与信号/service 机制)
**Requirements**: AUDIT-01, AUDIT-02
**Success Criteria** (what must be TRUE):

  1. `AuditEvent` 表落库（actor / action / target_type / target_id / target_repr / before / after / source / occurred_at / metadata），写入经单一 service 入口（INV-6 精神）
  2. append-only 不可篡改——无 update/delete 业务路径，模型层 + grep 守护无旁路写表
  3. emit helper / 信号可被任意敏感操作调用，emit 失败 best-effort 不阻断主操作（fail-soft）
  4. 凭证 / 密钥 / 明文 token 字段在审计 before/after 中脱敏，绝不落明文

**UI hint**: no

### Phase 54: 敏感操作全量覆盖 emit

**Goal**: 各敏感/管理操作经统一入口产出审计记录，含 v0.5 既有埋点收口
**Depends on**: Phase 53 (需先有 `AuditEvent` 模型 + emit 地基)
**Requirements**: AUDITCOV-01, AUDITCOV-02
**Success Criteria** (what must be TRUE):

  1. 成员/用户增删改、用户启停、角色/权限变更、空间配置变更、仓库权限变更产生审计记录（actor + 目标 + 前后值）
  2. Provider / Git 实例 / 飞书凭证增删改、Agent API key / PAT 操作、飞书同步操作产生审计记录（凭证字段脱敏）
  3. 排除规则变更与清理任务（v0.5 既有 `purge` 埋点）收口到统一 `AuditEvent`，可查
  4. 读操作 / 普通业务操作不产生审计噪音（仅敏感/管理操作 emit）

**UI hint**: no

### Phase 55: 审计查询 API + 前端视图 + 导出

**Goal**: 审计记录可查、可看 before-after、可导出，访问 fail-closed
**Depends on**: Phase 54 (需先有覆盖的审计数据)
**Requirements**: AUDITUI-01, AUDITUI-02
**Success Criteria** (what must be TRUE):

  1. 审计查询 REST API 支持按 actor / action / target / 时间范围过滤 + 分页，superuser fail-closed（非 superuser 拒绝）
  2. 审计记录对外只读——无任何创建/编辑/删除入口
  3. 前端审计视图可见列表 + 过滤 + 详情（before-after 对比）
  4. 支持导出（CSV / JSON）

**UI hint**: yes

<details>
<summary>✅ v0.9.0 SDD / OpenSpec 支持（重型）(Phases 48–52) — SHIPPED 2026-06-17</summary>

- [x] Phase 48: SDD 仓库检测 + facets 打标 + 前端标签 (2/2 plans) — SDD-01, SDD-02 — completed 2026-06-17
- [x] Phase 49: 方案产 openspec spec + Document(sdd_spec) (4/4 plans) — SPEC-01, SPEC-02 — completed 2026-06-17
- [x] Phase 50: spec 状态机 + 变更记录 + 评审状态 + 前端展示 (5/5 plans) — SPECST-01, SPECST-02, SPECST-03 — completed 2026-06-17
- [x] Phase 51: 编码前置 gate + openspec skill 编码策略 (3/3 plans) — GATE-01, GATE-02 — completed 2026-06-17
- [x] Phase 52: spec↔需求/PR 关联 + 交付验收视图 (3/3 plans) — LINK-01, LINK-02 — completed 2026-06-17

完整阶段详情见 [milestones/v0.9.0-ROADMAP.md](./milestones/v0.9.0-ROADMAP.md)。里程碑审计 passed（11/11 需求、integration_ok、INV-6/INV-2 成立）见 [milestones/v0.9.0-MILESTONE-AUDIT.md](./milestones/v0.9.0-MILESTONE-AUDIT.md)。

</details>

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

里程碑 v0.1.0–v0.9.0（Phases 1–52）均已交付归档。**当前里程碑 v0.10.0 操作审计治理（Phases 53–55）规划完成，待执行**——`/gsd-plan-phase 53` 起步，或 autonomous 跑完整个里程碑。后续候选见 `ROADMAP-vNext.md`（v0.11 开放与协作）。

---
*Previous milestones archived in .planning/milestones/*
