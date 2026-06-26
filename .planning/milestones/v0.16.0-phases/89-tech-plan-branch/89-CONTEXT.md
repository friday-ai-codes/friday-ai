# Phase 89: 技术方案深化 + 建分支绑项目 - Context

**Gathered:** 2026-06-26
**Status:** Ready for planning
**Mode:** Smart discuss (autonomous) — 用户逐 Wave 选定

<domain>
## Phase Boundary

产出 per-repo + overall 技术方案，支持修订回路与容器挂起，方案确认后建分支并绑项目：每仓负责事项/预改动/影响模块/e2e·单测/风险/feature 冲突 + 修订回路「调研问题发现」卡片 + 容器 5min 挂起/resume + 按方案建分支推送并绑项目。

交付需求：PLAN-01~04。
</domain>

<decisions>
## Implementation Decisions

### 技术方案产出载体
- **复用 v0.7 TechnicalPlan/PlanVersion + 镜像进项目 RESEARCH 文件**：方案 canonical 落 v0.7 编排实体（TechnicalPlan/PlanVersion），同时镜像一份进项目 RESEARCH（经 Phase 83 同步引擎双向镜像飞书）。
- per-repo（负责事项/代码预改动/影响业务模块/预计 e2e·单测+覆盖项/风险/feature list 不清处/与现功能冲突）+ overall 整体方案，含跨仓上下文。

### 分支命名来源（用户指定格式）
- **固定格式 + AI 生成 + 用户卡片确认**：分支名由 AI 方案生成、用户卡片确认，遵循以下规则：
  - 格式：`{type}/{yymmdd}.m-{项目跟踪id}.{项目名}[-{版本号}]`
  - `type`：conventional commits 类型（feat/fix/chore 等），按变更性质取。
  - `{yymmdd}`：日期（如 260610）。
  - `m-{项目跟踪id}`：项目跟踪 id（飞书项目跟踪 work_item id）。
  - `{项目名}`：与项目跟踪看板名称保持一致。
  - `{版本号}`：项目名/描述里有版本号则填（如 v1.0），没有则省略。
  - 示例：`feat/260610.m-123456770019.高三提分专项-v1.0`
- 每仓按方案建分支并推送 + 绑定 仓库↔分支↔项目（写 `ProjectBranch`，Phase 85），回接 IDE 闭环。

### 方案修订回路（PLAN-02）
- 执行中发现要改/增/删仓库 → 「调研问题发现」卡片 → 更新方案/创建补充修订 + 同步改仓库关联（多轮，优雅处理）。

### 容器挂起/resume（PLAN-03）
- 单仓任务遇阻等待用户时，5 分钟无回复挂起/暂存容器；用户卡片回复后 resume（session 持久化，复用 Phase 86 SessionStore→Redis + v0.8 callback resume + v0.12 durable）继续到终态。
- session 找不到 → 用应用态（方案+用户回复）重灌新 session（官方推荐兜底）。

</decisions>

<code_context>
## Existing Code Insights

### Reusable Assets
- `server/workflows/services/plan_orchestration/`（v0.7 PlanOrchestration / TechnicalPlan / PlanVersion / MergedPlan）：方案产出 canonical 实体复用增强。
- `server/services/git_platform/` + v0.8 git/branch dispatch：按方案建分支推送。
- `server/initiatives/models`（Phase 85 ProjectBranch）：仓库↔分支↔项目绑定。
- `server/services/feishu_im.py` + bot_cards：修订回路「调研问题发现」卡片 + 多轮校验澄清。
- `task/` + `server/resumable/`(durable) + Phase 86 SessionStore→Redis：容器 5min 挂起/resume。
- 项目 RESEARCH 文件（Phase 82/83）：方案镜像目标。

### Established Patterns
- 入口无关续驱 helper（adrive_plan_session_to_pause_or_terminal）+ 单一 engine 工厂（不造两套，v0.7/v0.8）。
- 容器挂起：finish turn → 停容器 → 回复后 SessionStore resume（callback resume + durable）。
- wave 编码 + cross-ref PR（v0.8）。

### Integration Points
- 消费 Phase 88 仓库关联确认结果。
- 写 ProjectBranch(Phase 85) + 镜像 RESEARCH(Phase 83) + 回接 Phase 86 IDE 闭环。

</code_context>

<specifics>
## Specific Ideas

- 分支命名格式由用户精确指定：`{type}/{yymmdd}.m-{项目跟踪id}.{项目名}[-{版本号}]`，type 走 conventional commits，项目名与项目跟踪看板名一致，版本号有则填。示例 `feat/260610.m-123456770019.高三提分专项-v1.0`。
- 方案载体复用 v0.7 TechnicalPlan（非另起），并镜像进 RESEARCH。

</specifics>

<deferred>
## Deferred Ideas

- None — 讨论保持在 phase scope 内。

</deferred>

<canonical_refs>
## Canonical References

- `.planning/project-workspace/MILESTONE-PROPOSAL.md` — §8 交付流水线（4 技术方案深化 / 5 建分支绑项目）、§10 调研结论（容器 resume）
- `.planning/REQUIREMENTS.md` — PLAN-01~04
- `.planning/ROADMAP.md` — Phase 89 Success Criteria
- `.cursor/rules/observability-logging.mdc` — call_source/initiated_by_user_id/脱敏强制项

</canonical_refs>
