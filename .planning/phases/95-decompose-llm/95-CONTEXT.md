# Phase 95: 拆分完善 - Context

**Gathered:** 2026-06-27
**Status:** Ready for planning
**Mode:** Smart discuss（autonomous，用户逐 phase 定夺）

<domain>
## Phase Boundary

`decompose` 阶段从「按非空行切分」升级为 LLM 跨仓业务线/模块/前后端拆分，提升路由/调研精度。

覆盖：DECOMP-01。功能相对独立（沿用统一 LLM call_source/观测约定），可收尾推进。

</domain>

<decisions>
## Implementation Decisions

### A. LLM 拆分
- `PlanOrchestrationEngine._decompose` 从 `requirement_text.splitlines()` 按行切分，升级为 LLM 跨仓
  **业务线 / 模块 / 前后端**拆分，产结构化 `segments`（保持下游 routing 消费契约不变）。
- 输入复用现有：`decomposition.requirement_text`（或 `work_item.title`）+ `include_repos`。

### B. 观测
- 新增 `CallSource.PLAN_DECOMPOSE` 枚举值并登记 LOGGING-SPEC §4.1；LLM 调用经 `use_call_source` 标注，
  上报请求/token/TTFT/上游错误码；事件 started/completed/failed + duration_ms（category 合理设定）。

### C. fail-soft 降级
- LLM 失败 / 缺 default_model / 解析异常 → **回退现状「按非空行切分」**（best-effort，绝不阻断编排）。

### Claude's Discretion
- 拆分 prompt 设计、segment 结构细化（是否带 module/repo_hint 字段）、call_source category 取值由 plan-phase 定。

</decisions>

<code_context>
## Existing Code Insights

### Reusable Assets
- `server/services/plan_orchestration/engine.py::_decompose`（现按行切分 stub，唯一 decompose 实现）。
- LLM 惯例：`agents/llm_factory.build_chat_model` + `services/provider_config.ProviderConfigService.aresolve`
  + `agents/call_source.use_call_source`；参考 `clarification_questions.py` 的健壮 JSON 解析 + fail-soft 模式。
- `server/agents/call_source.py::CallSource`（新增 PLAN_DECOMPOSE）。

### Established Patterns
- 状态只经 `PlanSessionService.transition("decomposed", decomposition=...)`；decomposing → routing。
- best-effort 降级、async ORM、观测 best-effort 不反噬业务。

### Integration Points
- `_decompose` 产 `segments` → `_route`（RepoRouterV2Adapter）消费；契约保持。

</code_context>

<specifics>
## Specific Ideas

- 跨仓业务线/模块/前后端拆分，失败回退按行切分。

</specifics>

<deferred>
## Deferred Ideas

None — 范围聚焦 DECOMP-01。

</deferred>
