# Requirements: Friday AI — v0.8.0 多仓串行编码 → 融合 PR

**Defined:** 2026-06-16
**Core Value:** 让团队"开箱即用、安全地"把需求自动变成代码；v0.8.0 把 v0.7 产的主方案（`MergedPlan.execution_plan` + 跨仓依赖 DAG）落成多仓代码——按跨仓依赖分层 wave 执行、上游产物注入下游、关联多仓融合 PR、编码遇阻抛 question 给人。

> 设计底座：`.planning/ROADMAP-vNext.md` §v0.8（Target features/现状坐标/已确认决策/候选 phases）、`.planning/DOMAIN-MODEL.md` §6（`RepoCodingTask`：wave/`depends_on` DAG/`produced_artifacts` + 可靠恢复规则 + SDD 扩展点）、`.planning/PREFLIGHT.md`（PF-06 should-fix-before-v0.8、PF-07 can-fix-in-milestone）。
> 复用底座（v0.7 已交付）：canonical `TechnicalPlan`/`MergedPlan`（含 `execution_plan` 跨仓依赖拓扑）+ `PlanSession` 编排状态机 + §15 事件 taxonomy；既有 `DispatchTask` 协议、RemoteTool MCP、callback 驱动 workflow resume、`waiting_event`、`AICodingNode` 并行派发、chat `coding_session_service`。
> 关键约束：scope=`plan_to_pr`；**显式非目标——不做编码中全自动回溯重规划**（编码遇阻走已有 question 协议抛人，全自动 replan 留 backlog）。diff base 用各仓正确 `target_branch`（非假设 master）。

## v1 Requirements

本里程碑提交范围。每条映射到 roadmap 某个 phase。

### 前置修复与 resume 地基（PF / RESUME）

> PF-06 should-fix-before-v0.8（多仓 wave 编码依赖私有仓 clone + 正确分支）；RESUME-01 消化 v0.7 audit D-2，是 callback 驱动多 wave 的通用回流通路。

- [ ] **PF-06**: 修 workflow 编码路径 `AICodingNode` 未注入 branch strategy / git token env（chat 路径已有）——对齐 chat 路径的 env 注入，使私有仓 clone 成功且用正确目标分支（不再落默认 `friday/task-{id}`）
- [x] **RESUME-01**: 立通用 `coding`/`plan_session` → 工作流/会话的 resume 回流通路——消化 v0.7 audit D-2（chat fire-and-forget 编排进 researching、容器在途完成后无消费者驱动 engine 续跑的缺口），为 callback 驱动的多 wave 调度提供统一回流通路

### 多仓 wave 编码（WAVE）

- [ ] **WAVE-01**: 立 `RepoCodingTask` 模型（plan_version FK / repository FK / wave int / `depends_on` M2M self DAG / status / `produced_artifacts` JSON / `follow_openspec` 预留 SDD 扩展点）+ 按 `execution_plan[].dependencies` 做拓扑分层（消化 PF-07：`dependencies` 不再仅 schema 声明、下游不再全并行）
- [ ] **WAVE-02**: wave 式执行——wave N 全部 done 才触发 wave N+1（按 `depends_on` 拓扑顺序推进），并明确 wave 失败/部分回滚语义（单 wave 内单仓失败的隔离与整体回滚边界）

### 上游产物传递（ARTIFACT）

- [x] **ARTIFACT-01**: 上游 wave 完成后提取 `produced_artifacts`（API 契约 / OpenAPI / diff）落 `RepoCodingTask.produced_artifacts`
- [x] **ARTIFACT-02**: 把上游 `produced_artifacts` 注入下游 wave 的 prompt / `global_context`，使下游仓编码能消费上游契约（如 wave1 后端 → wave2 前端）

### 多仓融合 PR（PR）

- [ ] **PR-01**: 多仓产出关联的 PR/MR，各仓 diff base 用各仓正确的 `target_branch`（非假设 master，对齐 v0.6 坐实的 MR target_branch 锚定）
- [ ] **PR-02**: 跨仓 PR 关联（cross-ref）——同一方案的多仓 PR 互相引用，可追溯到同一 `TechnicalPlan`/`WorkItem`

### 编码遇阻 HITL（HITL）

- [ ] **HITL-01**: 编码遇阻走 question 抛人——task 侧发起 question（复用已有 question 协议，补 task 侧发起 + orchestrator resume），抛给用户/orchestrator 等回答后续跑；**非全自动回溯重规划**

## v2 Requirements

延后到后续里程碑，已记录但不在本 roadmap。

### SDD / OpenSpec（SDD）— v0.9

- **SDD-01**: SDD 仓库编码前置 gate + `RepoCodingTask.follow_openspec` → 编码容器注入 openspec 指引（v0.8 仅预留扩展点字段位，完整状态机/gate/评审/关联在 v0.9）

### 编码全自动重规划（REPLAN）— backlog

- **REPLAN-01**: 编码中全自动 replan/回溯（前端卡住自动唤起后端重调研改方案）——最高阶能力，v0.8 用 HITL-01「抛 question 给人」过渡，全自动留 backlog

### 对外开放（OPEN）— v0.11

- **OPEN-01**: `coding.wave.started`/`coding.wave.completed` 事件经 adapter 对外透出（复用 v0.7 EVENT 词表，v0.8 仅产出内部 trace）

## Out of Scope

明确排除，附理由，避免反复回炉。

| Feature | Reason |
|---------|--------|
| 编码中全自动 replan/回溯 | 最高阶能力，v0.8 用 HITL-01「抛 question 给人」过渡，全自动留 backlog（避免范围爆炸，DOMAIN/ROADMAP-vNext 显式非目标） |
| SDD spec 完整状态机 / gate / 评审 / 验收 | v0.9 主题；v0.8 仅在 `RepoCodingTask.follow_openspec` 预留扩展点字段位 |
| `coding.wave.*` 事件对外 API adapter（OpenAI/Anthropic 透出） | v0.11 主题；v0.8 只产出内部 trace 事件 |
| 重做方案编排 / 路由 / 召回 / 融合 | v0.7 已交付；v0.8 只消费 `MergedPlan.execution_plan`，不改编排上游 |
| 多分支策略 / 复杂 merge 冲突自动消解 | v0.8 聚焦「按 wave 落代码 + 关联 PR」；冲突走既有冲突预检 + 抛人，自动消解留后续 |

## Traceability

哪个 phase 覆盖哪些需求。roadmap 创建时确认/调整（v0.7 结束于 Phase 42，本里程碑从 Phase 43 续号）。

| Requirement | Phase | Status |
|-------------|-------|--------|
| PF-06 | Phase 43 | Pending |
| RESUME-01 | Phase 43 | Complete |
| WAVE-01 | Phase 44 | Pending |
| WAVE-02 | Phase 44 | Pending |
| ARTIFACT-01 | Phase 45 | Complete |
| ARTIFACT-02 | Phase 45 | Complete |
| PR-01 | Phase 46 | Pending |
| PR-02 | Phase 46 | Pending |
| HITL-01 | Phase 47 | Pending |

**Coverage:**

- v1 requirements: 9 total
- Mapped to phases: 9/9 ✓
- Unmapped: 0

---
*Requirements defined: 2026-06-16*
*Last updated: 2026-06-16 — traceability mapped against ROADMAP.md (Phases 43–47, 9/9 mapped)*
