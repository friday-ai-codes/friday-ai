---
gsd_state_version: 1.0
milestone: v0.20.0
milestone_name: 技术方案蓝图
current_phase: 111
current_phase_name: 蓝图底座
status: ready-to-plan
stopped_at: "里程碑创建完成（REQUIREMENTS 35 条 / ROADMAP Phases 111–116 / 设计输入 technical-blueprint/DESIGN.md）。下一步：$gsd-plan-phase 111。"
last_updated: "2026-07-29T09:30:00.000Z"
last_activity: 2026-07-29
last_activity_desc: Milestone v0.20.0 created (parallel worktree with v0.19.0)
progress:
  total_phases: 6
  completed_phases: 0
  total_plans: 0
  completed_plans: 0
  percent: 0
---

# Project State

## Project Reference

See: .planning/PROJECT.md；本里程碑权威设计输入：**[.planning/technical-blueprint/DESIGN.md](./technical-blueprint/DESIGN.md)**（13 节，§12 八项决策已定夺，plan-phase 必读）。

**Core value（v0.20.0，在建）:** 技术方案成为「人类可读、AI 可依此完备编码」的项目级结构化蓝图——六段骨架每条结论带引用证据，三大编排阶段贯穿仓库确认门与分仓方案，仓库章程补齐净新增落点知识，飞书式划线澄清多轮收敛，全生命周期可管理，知识库可查可引可导出。
**Current focus:** Phase 111 — 蓝图底座（schema + 生命周期 + 线程/章程模型 + golden set）

## Current Position

Phase: 111 (蓝图底座) — NOT STARTED
Plan: —
Status: Milestone created, ready to plan
Last activity: 2026-07-29 — v0.20.0 里程碑规划产物落库（REQUIREMENTS/ROADMAP/STATE）

## Milestone Overview (v0.20.0 — Phases 111–116 — 🟡 PLANNING)

| Phase | Name | Requirements | Status |
|-------|------|--------------|--------|
| 111 | 蓝图底座（schema + 状态机 + 线程/章程模型 + golden set） | SCHEMA-01/06/07, LIFE-01/02/03, CHARTER-01, GATE-02 | Not started |
| 112 | 规格门与双面路由调研（阶段 1 + 确认门 + 章程回灌） | FLOW-01/02/03/04, CHARTER-02/03 | Not started |
| 113 | 分仓方案与融合（阶段 2/3）+ Context Bus | FLOW-05/06, SCHEMA-02/03/04/05, BUS-01/02/03 | Not started |
| 114 | 审查与澄清收敛（AI 审查 + 线程闭环 + 人工编辑） | FLOW-07, CLAR-02/03/04 | Not started |
| 115 | 前端查看器与知识库（查看器/批注/tab/终审 UI） | VIEW-01/02/03/04, CLAR-01, FLOW-08 | Not started |
| 116 | 入口收编与导出（MCP 协议 + 全入口 + 飞书导出 + 图谱物化） | GATE-01, VIEW-05 | Not started |

完整需求见 [REQUIREMENTS.md](./REQUIREMENTS.md)（35 条 + Traceability，35/35 映射；DEPTH-01~05 自 v0.19.0 Phase 108 迁入）；阶段详情见 [ROADMAP.md](./ROADMAP.md)。

**Execution order（依赖链，线性）:** 111 → 112 → 113 → 114 → 115 → 116。111 是数据与质量地基；112 锁规格与仓库集（确认门输出是 113 的输入）；113 产出完整蓝图；114 审查与澄清闭环；115 查看器；116 全入口收编（人审终审为前置）。

## 并行开发（与 v0.19.0 双 worktree，§13 纪律强制）

- **对方线:** `milestone/v0.19.0-plan-trust` worktree（Phases 105–107 + 109 + 110；108 已移交本里程碑，对方分支已确认收录该决策，commit `1fd3e60c`）。
- **同步点 1**（0.19 Phase 107 合并主干）：rebase 对齐澄清送达/提醒设施——影响 112/114 送达通道，未合并前用现有澄清通道兜底。
- **同步点 2**（0.19 Phase 109/110 合并）：execution 投影与事件时间线契约就位——116 的触点升级与默认入口切换在其后执行。
- **边界纪律（每个 plan 都必须遵守，违反=计划不通过）:**
  1. **不改 `codegraph/services/repo_router_v2.py`**——章程/历史落点证据在 `blueprint_route` adapter 层融合。
  2. **冻结既有 `technical_plan` process 六文件**（`decompose_segments.py` / `research_adapter.py` / `architect_merge_adapter.py` / `merged_plan.py` / `clarify_adapter.py` / `render.py` 只读）；蓝图流水线全走 `blueprint_*` 新文件，`builtin_processes.py` 仅新增注册项。
  3. **`ConvergenceSessionEvent` 既有事件类型/字段只消费不修改**，本里程碑仅新增 `blueprint_*` 事件类型。
  4. **前端只新建组件**（BlueprintViewer/blueprints tab/批注层/预览弹层）；TechPlanCard/RoutingDecisionPanel/执行时间线归 0.19，触点升级留到同步点 2 后（116）。
  5. **migration 纪律**：`delivery`/`mcp_tools`/`repositories` 新增 migration 在每次同步点 rebase 时重新生成序号。
  6. **rebase 节奏**：0.19 每个 phase 合并主干后，本分支 rebase 一次，不长期漂移；`.planning/STATE.md` 冲突以本分支为准（ours）。

## 关键约束 / 设计底座（plan-phase 必读）

- **产物 canonical**：蓝图落 `delivery.Artifact(artifact_type=technical_plan)` + `ArtifactVersion.content`（`schema_version="blueprint/v1"`，旧 MergedPlan 为隐式 v0 只读渲染）；markdown 与 execution_plan 都是确定性派生物，禁止双轨创作。
- **上下文纪律**：`stage_state` 只存 id/计数/小摘要（单字段 <2KB）；子代理传 id 清单自取正文；并行容器动态共享走 Context Bus（DESIGN §5.6），不靠 prompt 传递。
- **HITL 语义**：确认门是硬门（`kind=repo_confirmation` 阻塞线程）；澄清超时保持显式 pending + 提醒，不自动作答不判失败；「需要澄清」是叠加态，记 `return_stage`。
- **章程原则**（DESIGN §5.7）：`RepoCharter` 人工确认生效，AI 只可提修订草案；意图分流是权重融合不是硬开关；`charter_match` 进 score breakdown；确认门动作回灌为草案。
- **权限**：项目成员皆可确认/评论/编辑；确认者自动进 `BlueprintReviewer` 名单；不做段级权限。
- **观测规范强制**：新 LLM 调用赋 `call_source`（`blueprint_decompose/spec_gate/repo_research/reroute/repo_plan/merge/ai_review`，LOGGING-SPEC §4.1 先登记）；stage 事件 `blueprint_stage_started/completed/failed` 带 `duration_ms`/`category`/`component`；容器动作绑定 `initiated_by_user_id`；脱敏不可绕过。
- **既有纪律沿用**：INV-6 单一写入入口（新增 `BlueprintLifecycleService` 等 service 收口）；async ORM 走 `sync_to_async`；i18n 默认中文；观测代码 best-effort 绝不反噬业务。
- **Out of Scope 锁定**：改 `repo_router_v2.py`；改旧 technical_plan process 六文件；改 `ConvergenceSessionEvent` 既有契约；TechPlanCard 等 0.19 归属组件（同步点 2 前）；Prompt Center 化；母子蓝图编排拆分；段级权限；审查换模型（档位可配即可）。

## Accumulated Context

### Decisions

- [Milestone v0.20.0, 2026-07-29]: 八项设计决策已定夺（DESIGN.md §12）——①蓝图项目级一项目一份活跃蓝图；②indirect 仓默认轻量调研可人工升级；③项目成员皆可确认、确认者自动进评审人名单；④澄清超时保持显式 pending 不自动作答；⑤AI 审查默认与起草同模型档位；⑥golden set 起步即建（含目标仓命中率，首条 case 高三提分专项）；⑦Context Bus 会话级共享上下文（token→会话→项目绑定 + 两档等待恢复 + 环检测）；⑧RepoCharter 仓库章程补意图面知识、双面路由按意图分流加权。
- [Milestone v0.20.0, 2026-07-29]: Phase 108（DEPTH-01~05）自 v0.19.0 迁入本里程碑，由 blueprint/v1 schema 原生满足；v0.19.0 分支已同步收录（commit `1fd3e60c`），其 109 改以现行 §7 execution_plan 对接执行流。
- [Milestone v0.20.0, 2026-07-29]: 与 v0.19.0 并行开发的四条边界纪律与两个同步点定版（DESIGN.md §13.2/§13.3），本文件「并行开发」节为执行时唯一对照清单。

### Pending Todos

（无）

### Blockers/Concerns

- 同步点 1/2 依赖 v0.19.0 的 107 / 109+110 合并主干节奏；116 的入口切换在同步点 2 前不可执行（可先做 MCP 协议与导出的后端部分）。
- `.planning/` 三文件（ROADMAP/REQUIREMENTS/STATE）与 0.19 分支在里程碑收尾合并时预期机械冲突：v0.19.0 段以对方为准、v0.20.0 段以本分支为准、STATE 以存活里程碑为准。

## Session Continuity

Last session: 2026-07-29 — 设计蓝图收敛（DESIGN.md 13 节）+ 里程碑创建（本次）
Next step: **`$gsd-plan-phase 111`**（蓝图底座；DESIGN.md §3/§4/§5.7/§6 为该相位直接输入）
Resume file: 无（干净起点）
