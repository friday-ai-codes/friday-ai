# Phase 36: 前置修复 + 编排引擎骨架 + PlanSession 状态机 - Context

**Gathered:** 2026-06-16
**Status:** Ready for planning
**Mode:** Smart discuss (autonomous — grey areas resolved at Claude's discretion per design docs)

<domain>
## Phase Boundary

本 phase 交付两类东西，互相独立但同属 v0.7 方案编排地基：

1. **前置修复（PF-01/PF-02，blocking）**：
   - PF-01：`server/workflows/nodes/ai/plan_generation.py` 的 system prompt 与 `get_enabled_tools()` 引用的检索工具名 `search_code` 与注册名 `search_repository_code` 不一致；`agents/tools/langchain_adapter.py:build_langchain_tools` 对不在 `_tool_registry` 的工具名静默 `continue` 跳过 → server 端方案生成的检索工具从未真正生效。修：统一工具名 + 把静默跳过改 fail-loud（记 error/raise）。
   - PF-02：`agents/tools/verify_plan.py` 校验 `title`/`tasks` 字段，但 canonical 方案 schema（`server/workflows/schemas/technical_plan.py`）用 `execution_plan`。修：对齐到 `execution_plan`，使校验真正命中——作为 Phase 40 `PlanValidator` 的基础。

2. **编排引擎骨架 + 状态机（ORCH-01/ORCH-02）**：
   - 立 `PlanSession` 持久化模型（delivery app，DOMAIN §6/§12.7 邻域），状态机按 §14 转移表：`decomposing → routing → recalling → clarifying → researching → merging → done/failed`。
   - 立可复用 `ai_plan_research` 编排 engine 抽象：纯编排状态推进 + 副作用钩子，工作流与 Chat 入口共用底层（本 phase 只立骨架与状态推进，路由/召回/调研/融合的真实实现分别在 Phase 38/39/40 填充）。

**不在本 phase**：真实路由（38）、召回（38）、并行调研子 agent（39）、架构师融合/PlanValidator 完整实现（40）、Clarification 回路/事件 taxonomy/工作流入口（41）、Chat 入口（42）、canonical TechnicalPlan 落库（37，本 phase engine 先留 PlanVersion 写入扩展点不强依赖）。

</domain>

<decisions>
## Implementation Decisions

### PF-01 工具名漂移修复
- 统一到注册名 `search_repository_code`：改 `plan_generation.py` 的 `get_enabled_tools()` 列表项 `search_code`→`search_repository_code`，并改 system prompt 文案中所有 `search_code` 引用为 `search_repository_code`（含第 52/83 行）。不引入工具别名机制（避免维护两套名字）。
- `build_langchain_tools` 未知工具改 **fail-loud**：遇到不在 `_tool_registry` 的工具名 → raise（ValueError，信息含工具名 + 可用工具名集合），不再静默 `continue`。理由：静默跳过正是 PF-01 根因。保留「节点白名单偶有删除工具」的兼容性顾虑 → 由调用方维护正确白名单 + 单测断言 prompt 引用的每个工具名都在注册表，而非靠 adapter 吞错。
- 守护：单测断言 `get_enabled_tools()` 返回的每个名字都在 `_tool_registry`；单测断言 `build_langchain_tools(["__nonexistent__"])` raise。

### PF-02 verify_plan schema 对齐
- `verify_plan` 校验字段从 `tasks` 改 `execution_plan`：必填 `title` + `execution_plan`（非空 list）；逐项校验 `execution_plan[i]` 为对象且含关键字段（`repository_id` + `coding_instruction`，对齐 `technical_plan.py` schema 与 DOMAIN §7 MergedPlan.execution_plan）。
- 工具 description 与 parameters 描述同步更新（不再写"需包含 title 和 tasks"）。
- 保持工具契约形状不变（`{valid, errors, warnings, summary}`，`success=True` 工具自身恒成功，校验结果在 output），避免破坏 `plan_generation.py:484` 读取 `verify_plan` 结果的逻辑。
- 本 phase 只做"对齐 schema"的最小修复；契约一致/依赖成环/回滚完整等扩展校验留 Phase 40 PlanValidator（在此基础上扩展，不在本 phase 堆叠）。

### PlanSession 模型与状态机（ORCH-02）
- 落在既有 `delivery` app（v0.6 已建），与 WorkItem/TechnicalPlan 同 app，符合 DOMAIN §6「操作态聚合」归属。新建 `server/delivery/models/plan_session.py` + curated re-export。
- 字段（DOMAIN §6 PlanSession）：`id UUIDField(pk, uuid4)`、`work_item FK(delivery.WorkItem, null=True, SET_NULL)`（INV-2：chat 自然语言需求允许 null）、`entrypoint CharField(choices: workflow|chat)`、`status CharField(choices: decomposing|routing|recalling|clarifying|researching|merging|done|failed, default=decomposing)`、`current_plan_version FK(null)`（Phase 37 canonical PlanVersion，本 phase 用 nullable FK 占位或 UUID 软引用以避免与 37 形成硬循环——选 nullable FK 到 'delivery.PlanVersion' 字符串引用，37 建表后生效；若 37 未建则该 FK 暂以 null）。
  - **决策**：为避免 36 与 37 的迁移耦合，本 phase `current_plan_version` 用 `models.UUIDField(null=True, blank=True)` 软引用（存 PlanVersion.id），Phase 37 建 canonical 表后由 service 写入/读取，不在 36 建 FK 约束。`work_item` 走真实 FK（WorkItem 已存在）。
  - 附加状态字段：`decomposition JSONField(default=dict)`（拆分结果：前后端/业务线/模块）、`error JSONField(default=dict, blank)`（不可恢复错误结构化落地）、`created_at/updated_at`、`event_time`(null)。
- **状态转移单一入口**：`PlanSessionService.transition(session, event, **payload)`（INV-6 精神：状态只经 service 改），内部校验合法转移（按 §14 转移表的白名单字典 `_ALLOWED: {from_status: {event: to_status}}`），非法转移 raise；合法则更新 status + 落副作用钩子点 + 发 trace 事件占位（事件 taxonomy 真实发射在 Phase 41，本 phase 留 `_emit_event(event_name, payload)` 钩子，先 best-effort no-op/log）。
- **可恢复**：状态全持久化在 DB 行（status + 中间产物 JSON），engine 从任意 status 可 resume（读 session.status → 继续推进），不依赖内存态。不可恢复错误 → `transition(session, "fail", error=...)` 置 `failed` + 落 `error` JSON。

### ai_plan_research 编排 engine 抽象（ORCH-01）
- 落 `server/services/plan_orchestration/`（新 package，service 层，符合 ARCHITECTURE「Services = 可复用域逻辑」）。核心：`PlanOrchestrationEngine`（或 `ai_plan_research` 命名的 engine 入口函数 + 类）。
- 设计为**状态驱动 step 推进器**：`async def advance(session) -> PlanSession`，按当前 status 调对应 stage handler（`_decompose/_route/_recall/_clarify/_research/_merge`），handler 在本 phase 为**骨架**（decompose 可做最小真实实现：把需求文本 + include_repos 拆成 decomposition；其余 stage handler 留 `NotImplementedError` 占位或最小 pass-through + TODO 注释标注 Phase 38/39/40/41 填充）。
- **工作流与 Chat 共用底层**：engine 不耦合 workflow/chat 具体 IO；入口（workflow 节点 / chat）只负责建 session（entrypoint 字段区分）+ 调 engine.advance + 消费产物。本 phase 不接真实入口（41/42），但 engine API 设计为入口无关（接收 session + 注入依赖：router/recall/research/merge 为可注入协议，骨架用 null/默认）。
- 异步约束：engine 全 async，ORM 访问经 `sync_to_async` 或 adrf async ORM（沿用 delivery service 既有范式）。

### Claude's Discretion
- engine 内 stage handler 的依赖注入形态（协议类 / 回调 / 直接 import 后续 service）——planner 按最小可测原则定，倾向「可注入协议 + 骨架默认实现」便于 38-41 逐步替换且单测可 mock。
- `_ALLOWED` 转移表的精确 event 命名（与 §14 转移表语义对齐即可）。
- PlanSession 是否在本 phase 加 `RepoResearchTask`/`Clarification` 等子模型——倾向**不**在 36 建（归属 39/41），36 只建 PlanSession 主表，避免提前建未用的表。

</decisions>

<code_context>
## Existing Code Insights

### Reusable Assets
- `server/agents/tools/verify_plan.py` — 待改的方案校验工具（PF-02）。
- `server/agents/tools/langchain_adapter.py:build_langchain_tools` — 工具桥接，静默跳过未知工具的根因（PF-01）。
- `server/agents/tools/space_tools.py` — `search_repository_code` 注册处（正确工具名来源）。
- `server/workflows/nodes/ai/plan_generation.py` — system prompt + `get_enabled_tools()` 引用 `search_code`（PF-01），`verify_plan` 重试循环 + 结果读取（`:484`）。
- `server/workflows/schemas/technical_plan.py` — canonical 方案 schema（`execution_plan` 真相，PF-02 对齐目标）。
- `server/delivery/` — v0.6 已建 delivery app（models 包按实体拆 + curated re-export + UUIDField(default=uuid4) + service 单一写入入口范式 INV-6）。PlanSession 落此。
- `server/services/` — service 层范式（async + sync_to_async 桥接）。

### Established Patterns
- delivery app：models 包按实体文件拆分 + `__init__.py` curated re-export；id 一律 `UUIDField(primary_key, default=uuid4)`；落库/状态变更只经 service（INV-6）；append-only 事件 + 读时投影。
- 工具注册：`@tool(name=..., parameters=...)` 装饰器入 `_tool_registry`；工具返回 `ToolResult`。
- 测试：后端 pytest + pytest-asyncio + pytest-django；async ORM 守护用 `sync_to_async`。

### Integration Points
- `plan_generation.py` 经 `build_langchain_tools` 装配工具 → 修 PF-01 后该节点检索工具生效。
- PlanSession 经 `delivery` app migration 落表；engine 在 `services/plan_orchestration/` 调 delivery service。
- engine 的真实 stage 实现由后续 phase 接入：38（router/recall）、39（research fan-out）、40（merge + validator）、41（clarify + events + workflow 入口）、42（chat 入口）。

</code_context>

<specifics>
## Specific Ideas

- 严格遵循 DOMAIN-MODEL §6（PlanSession 字段 + 子任务级状态 + 可靠恢复规则）、§14（PlanSession 转移表，逐行对照实现 `_ALLOWED`）、§7（execution_plan 形状，PF-02 校验对齐）。
- PF-01/PF-02 是 should-fix-before-v0.7 的 blocking 项（PREFLIGHT 已 verified），必须在 engine 工作前落地并带回归守护测试。
- engine 抽象的"工作流与 Chat 共用底层"是 vNext 已确认决策（不为两入口造两套编排），本 phase 即把 API 设计成入口无关。

</specifics>

<deferred>
## Deferred Ideas

- canonical `TechnicalPlan`/`PlanVersion` 落库与 `TechnicalPlanService` → Phase 37（本 phase PlanSession.current_plan_version 用 UUID 软引用占位）。
- 真实路由 `RepoRouterV2` + 历史召回接入 → Phase 38。
- 并行调研子 agent `RepoResearchTask`/`PartialPlan` + filter_then_container → Phase 39。
- 架构师融合 + `MergedPlan` + 完整 `PlanValidator`（扩展 verify_plan）+ 跨仓依赖 → Phase 40。
- `Clarification` 回路 + 事件 taxonomy 真实发射 + 工作流入口 → Phase 41。
- Chat 入口薄封装 → Phase 42。
- SDD 扩展点（PlanSession 对 SDD 仓库产 spec draft 字段位）→ 可在 40/41 顺带预留，完整 v0.9。

</deferred>
