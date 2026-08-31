# Phase 142: MCP 会话回写契约 - Context

**Gathered:** 2026-08-28
**Status:** Ready for planning

<domain>
## Phase Boundary

新增并冻结 `report_session_knowledge` MCP 写入契约，使已认证的 Cursor / Claude Code 客户端把结构化问答同步提交给 Phase 141 的 `CaptureService`；任何仓库或项目挂钩失败都不得影响 Capture 持久化。本阶段只交付服务端 serializer/view/url、服务端 schema snapshot、npm MCP 工具定义及契约回归，不实现价值评估、入图、召回、回放或宿主 hooks。

</domain>

<decisions>
## Implementation Decisions

### 工具请求与响应契约
- 新工具名固定为 `report_session_knowledge`；必填字段只有非空 `question` 与 `answer`，其中 `answer` 是客户端可见答案精华，不是 transcript 或隐藏思维链。
- 可选元数据完整覆盖 `repository_id`、`git_url`、`branch_name`、`project_id`、`session_id`、`response_model`、`provider`、`input_tokens`、`output_tokens` 与 `client`；不可得字段由既有 `CaptureService` 归一为 `unknown`/`unspecified`，服务端不猜测。
- 成功响应固定包含 `accepted=true`、`capture_id`、`reason`、解析后的可空 `repository_id`/`project_id`、`idempotent_hit` 与 `run_id`；`accepted=true` 的唯一含义是 Capture 已持久化，不承诺已挂钩或已入 RAG。
- 缺少认证或必填问答继续按既有 MCP 基类/DRF 返回 401/400；仓库未解析、项目未解析/未授权/不匹配等业务挂钩结果返回 200，且必须先有 Capture 行。

### 挂钩、持久化与幂等语义
- View 只做 `_begin`、serializer 校验、调用 `CaptureService.persist`、`_record` 和响应映射；不得直接写 `SessionCapture`，也不得调用 `_resolve_report_project_id` 作为接受门闩。
- 透传 `request.user` 与 `initiated_by_user_id=request.user.id`，并把客户端仓库、项目、会话、模型元数据原样交给 Phase 141 的仓库优先挂钩状态机。
- `repo_unresolved`、`repo_ambiguous`、`project_unresolved`、`project_unauthorized`、`project_repo_mismatch`、`unanchored` 等 `reason` 只描述挂钩结果；不得复用 `branch_unresolved` 表示未收。
- 重试继续复用 Phase 141 的 `(initiated_by_user_id, session_id, question_hash)` first-write-wins 幂等键；命中既有 Capture 时仍返回 `accepted=true` 与原 `capture_id`，不覆盖首次答案或挂钩原因。

### 三面对齐与可发现性
- `ReportSessionKnowledgeRequestSerializer`、`TOOL_SCHEMA_SNAPSHOT["report_session_knowledge"]` 与 `mcp/src/tools.ts` 必须使用同一请求键集；snapshot 同时锁定完整响应键集。
- npm 工具注解按非破坏、可幂等的 Friday 内部写操作登记，不能标为只读；工具描述明确“已收 Capture”与“已入知识库”是两回事。
- 扩展现有 `test_schema_snapshot.py`、`test_mcp_package_alignment.py` 与针对新 view 的契约测试，使服务端、snapshot 或 npm 任一面漏字段/漏工具都直接失败。
- 本阶段不借机修整 `report_project_knowledge` 已存在的 snapshot 漂移；新工具从第一天完整对齐，旧工具兼容面原样保留。

### 旧工具隔离与安全观测
- `report_project_knowledge` 继续服务“已定位项目的 MEMORY/RESEARCH 沉淀”，保留项目门闩、质量门、draft/active 与 git-diff 路径；不得扩成 Capture 入口。
- 新工具继续复用 `McpToolView` 的 PAT/JWT 用户身份、`InteractionRun`、RequestMetric 与脱敏 Ledger 记录，但 Ledger 只作调用审计，不作为 Capture 或 RAG 正文。
- 日志与工具留痕不得复制未脱敏问答、git URL、凭证或 token；正文持久化脱敏仍以 `CaptureService` 为唯一安全边界。
- 为旧 `report_project_knowledge` 保留并运行零回归测试，显式断言新工具不会新增 `ProjectMemory`、调用 `MemoryService.append` 或改变 `branch_unresolved` 旧语义。

### the agent's Discretion
- serializer 的具体长度上限、`client` 是否用闭集 ChoiceField、类/测试文件内部拆分由实现者按现有 DRF 与 MCP 约定决定，但不得缩减已锁定的可选元数据。
- response serializer 是否独立成类可由实现者决定；snapshot 与实际响应键必须一致。

</decisions>

<code_context>
## Existing Code Insights

### Reusable Assets
- `server/initiatives/services/capture_service.py::CaptureService.persist` 已完成脱敏、unknown/unspecified 归一、仓库优先挂钩、授权校验和 first-write-wins，并返回 `CapturePersistResult`。
- `server/mcp_tools/views.py::McpToolView` 提供 `_begin`、`_validate`、`_record`、PAT/JWT 鉴权、RequestMetric、ToolCallRecord 与 RetrievalTrace 统一外壳。
- `server/mcp_tools/serializers.py::ReportProjectKnowledgeRequestSerializer`、`server/mcp_tools/views.py::ReportProjectKnowledgeView` 与 `server/mcp_tools/urls.py` 提供相邻 MCP 写工具的 serializer/view/url 组织模式。

### Established Patterns
- `server/tests/mcp_tools/test_mcp_package_alignment.py` 从 `mcp/src/tools.ts` 提取 `FRIDAY_TOOLS` 名集并与 `TOOL_SCHEMA_SNAPSHOT` 做双向相等校验。
- `server/tests/mcp_tools/test_schema_snapshot.py` 锁定服务端 schema 面；`test_skills_snapshot_guard.py` 把 skills 中反引号工具名与 snapshot 的工具/字段白名单对齐。
- `server/tests/initiatives/test_capture_inv6_guard.py` 已锁定 `SessionCapture` 只有 `capture_service.py` 可写，且 Phase 141 writer 不接 deferred sink、Memory 或分支项目门闩。

### Integration Points
- 在 `server/mcp_tools/serializers.py` 新增请求 serializer 和 snapshot 条目，在 `server/mcp_tools/views.py` 新增 view，在 `server/mcp_tools/urls.py` 注册 `/api/mcp/tools/report_session_knowledge/`。
- 在 `mcp/src/tools.ts` 的 `FRIDAY_TOOLS` 与 `TOOL_ANNOTATIONS` 同步新增工具；文件头工具计数也要随真实数量更新。
- 新 view 的唯一业务写调用点连接 `CaptureService.persist`；`server/tests/mcp_tools/test_report_project_knowledge.py` 是 MCP-04 零回归锚点。

</code_context>

<specifics>
## Specific Ideas

- `accepted=true` 必须可由数据库中的 Capture 行证明；它不等于仓库解析成功、项目绑定成功、价值评估成功或 RAG 入图成功。
- 新工具应允许只提交问答而无仓库/项目元数据；这种 `unanchored` Capture 仍是有效评测与后续补标资产。
- 服务端 schema、npm snapshot 与测试须在同一个 Phase 完成，禁止重现“Django 有工具但 Cursor MCP 白名单不可达”。

</specifics>

<deferred>
## Deferred Ideas

- high/medium/low 评估、durable 状态机与 `session_capture` 入图延后到 Phase 143。
- 仓库/项目召回、Capture 原文回放、默认分支第三源修复和 RetrievalTrace 收口延后到 Phase 144。
- skills 文案、HTTP fallback 与 Cursor / Claude Code hooks 接线延后到 Phase 145。
- 既有 `report_project_knowledge` snapshot 历史漂移不在本阶段顺手修复。

</deferred>
