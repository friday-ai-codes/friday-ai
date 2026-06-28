# Phase 94: 入口统一 - Context

**Gathered:** 2026-06-27
**Status:** Ready for planning
**Mode:** Smart discuss（autonomous，用户逐 phase 定夺）

<domain>
## Phase Boundary

工作流 / 对话 / MCP 三入口的方案生成全部归一到 `plan_orchestration`，废弃旧 LangChain `ai_plan_generation`，
done 出口用干净结构化 markdown 推送方案到群。

覆盖：UNIFY-01（模板切换）、UNIFY-02（旧节点 deprecated）、UNIFY-03（MCP create_feishu_technical_plan delegate）、
UNIFY-04（create_coding_plan 口径收口）、UNIFY-05（对话澄清双挂起单一来源）、UNIFY-06（done 推群干净渲染）。

</domain>

<decisions>
## Implementation Decisions

### A. 模板切换 + 废弃旧节点
- **UNIFY-01**：内置模板 `technical_plan_generation.json` 的方案节点从 `ai_plan_generation` 切到 `ai_plan_research`；
  既有已实例化工作流不破坏（只改模板定义/新建路径）。
- **UNIFY-02 / 节点库清理（用户要求）**：旧 `ai_plan_generation` **从节点库（NodePalette）移除、不再展示**；
  代码标记 deprecated（仍注册、向后兼容既有实例可运行），**不删代码**；附迁移指引。
  前端 `NodePalette.vue` 硬编码的 `ai_plan_generation` 移除，改暴露 `ai_plan_research`（如尚未暴露）。

### B. MCP 收口
- **UNIFY-03**：`create_feishu_technical_plan` 改为 delegate 到 `plan_orchestration`
  （`start_orchestration` + 续推），产 canonical `MergedPlan`/`PlanVersion`（与工作流/对话同一产物口径）；
  **保留 MCP 响应外形兼容**（response 字段映射自 canonical，调用方不破坏）。旧 `McpWorkItemTechnicalPlan` 落库保留兼容。
- **UNIFY-04**：`create_coding_plan` 产物口径对齐 `plan_orchestration`（并入/映射收口，不再走独立确定性 seam 产分叉结构）；
  保留响应字段兼容、`McpCodingPlan` 落库兼容。

### C. 单一来源 + done 推群
- **UNIFY-05**：对话方案生成的澄清挂起**收敛为单一来源** `delivery.Clarification`（Phase 90/91 模型）；
  消除 `ToolResult` marker vs `PlanSession.Clarification` 双挂起二义——marker 仅作前端渲染信号，
  挂起/续推状态唯一以 delivery.Clarification + PlanSession 为准。
- **UNIFY-06**：`ai_plan_research` 的 `done` 出口接「推送方案到群」（`notify_feishu_im`），
  用**干净结构化 markdown** 渲染（复用本轮渲染修复：markdown 组件 + `•`），**不 dump LLM 原始文本**。

### Claude's Discretion
- MCP 响应字段到 canonical 的精确映射、deprecated 标注方式（docstring/警告日志）、迁移指引文案位置由 plan-phase 定。
- done 推群的 markdown 模板细节复用既有渲染修复。

</decisions>

<code_context>
## Existing Code Insights

### Reusable Assets
- 模板：`server/workflows/templates/technical_plan_generation.json`（现绑 `ai_plan_generation`）；
  已切 `ai_plan_research` 的样板：`code_generation.json`、`feishu_full_pipeline.json`；
  `server/workflows/templates/loader.py`（acreate 前校验）；`test_template_loader.py` 断言。
- 旧节点：`server/workflows/nodes/ai/plan_generation.py`（`ai_plan_generation`，LangChain 单 agent，
  outputs default/need_clarification/error）。
- 编排底座：`server/services/plan_orchestration/`（engine/entrypoint/resume/adapters）；
  `server/agents/tools/plan_research_tools.py::start_plan_research`（chat 入口）。
- MCP：`server/mcp_tools/technical_plan_service.py::build_work_item_technical_plan`（独立 seam）、
  `server/mcp_tools/planning_service.py::build_coding_plan`（独立 seam）、`views.py` 两 View。
- 推群：`server/workflows/nodes/integrations/feishu_im_notify.py`（`notify_feishu_im`）。
- 前端节点库：`web/src/components/workflow/sidebar/NodePalette.vue`（硬编码含 `ai_plan_generation`）。
- 对话澄清双轨：`server/agents/tools/clarification.py::ask_clarification`（marker，ConversationIntentTrace）
  vs `delivery.Clarification`。

### Established Patterns
- 内置模板切换不动既有实例；deprecated 不删（向后兼容不回退，历史里程碑约束）。
- canonical 产物 = `MergedPlan`/`PlanVersion`（`merged_plan.py` schema）。

### Integration Points
- MCP View → delegate `start_orchestration` → `adrive_...` → 取 canonical PlanVersion → 映射 MCP 响应。
- 依赖 Phase 90/91 的单一来源澄清模型（UNIFY-05 收敛点）。

</code_context>

<specifics>
## Specific Ideas

- 用户：废弃节点从节点库去掉不展示；代码标 deprecated 不删。

</specifics>

<deferred>
## Deferred Ideas

- 旧 Mcp* 持久化表的最终下线（本里程碑只收口产物口径，保留落库兼容）。

</deferred>
