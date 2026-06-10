# Phase 11: task 容器接通（RemoteTool 链路闭环） - Context

**Gathered:** 2026-06-09
**Status:** Ready for planning
**Mode:** Smart discuss（autonomous，推荐项已采纳；用户已授权代为决策）

<domain>
## Phase Boundary

打通 RemoteTool 全链路闭环：task 容器消费 `remote_tools`，claude-agent-sdk 通过 SDK MCP server 真正加载并调用这些工具（builtin/mcp/skill）；用户令牌以**直传 PAT** 形态经 server→runner→task 安全注入容器，agent 以用户身份回调 Phase 10 的执行端点；日志/审计对令牌脱敏；任务运行中令牌被吊销时，在途任务 graceful 跑完，仅阻断后续新调用。

覆盖 RTOOL-02、RTOOL-03、RTOOL-04。依赖 Phase 10（可调用的 `/api/tools/execute/` 端点 + 绑定令牌）。这是里程碑链式依赖最重的收尾阶段，跨 server / runner(Go) / task(Python) 三组件。
</domain>

<decisions>
## Implementation Decisions

### 令牌注入（RTOOL-03 —— 直传 PAT + 脱敏）
- 用户令牌以**直传 PAT** 形态注入容器（里程碑锁定，不做短 TTL 派生凭证——那是 v2 PATX-04）。
- 注入通道：沿用既有 dispatch 链 server(`runners/dispatcher.py` + `runners/consumers.py`)→runner(Go `internal/docker/executor.go`，env 注入)→task(`TaskConfig` 新增字段，`FRIDAY_TASK_` 前缀环境变量)。新增形如 `FRIDAY_TASK_USER_TOKEN`（直传 PAT）+ `FRIDAY_TASK_REMOTE_TOOLS`（工具 schema JSON）+ 回调端点 base（复用 callback_url 同源或新增 `FRIDAY_TASK_TOOLS_ENDPOINT`）。
- 脱敏：PAT 绝不进任何日志（task `print`/structlog、runner zerolog、server 审计）。task 侧对令牌做 redact；server 审计沿用 `redact_for_ledger`/`begin_interaction_run` 既有脱敏。runner 日志不打印 env 值。

### remote_tools 消费 + SDK MCP server（RTOOL-02）
- task 容器从配置读取 `remote_tools`（name/description/input_schema 列表）。
- 用 claude-agent-sdk 的 `create_sdk_mcp_server` + `@tool`（或等价 SDK API）构建一个进程内 SDK MCP server，把每个 remote_tool 注册为 SDK 工具；通过 `ClaudeAgentOptions(mcp_servers={...}, allowed_tools=[...])` 挂给 `query()`（在 `task/core/executor.py` 的 `_execute_claude` options 装配处）。
- 每个工具的 handler：以 owner 的直传 PAT 调 Phase 10 的 `POST /api/tools/execute/`（`{name, arguments}`，`Authorization: Bearer friday_pat_...`）→ 返回 `{ok, result|error}` 转成 SDK 工具结果。
- 参考 server 既有 `server/agents/sdk/mcp_adapter.py`（主 agent 的 SDK MCP 适配范式）作为 task 侧实现蓝本。
- 无 remote_tools / 无用户令牌时：不挂 MCP server，行为与现状一致（向后兼容）。

### 吊销 graceful（RTOOL-04）
- 不主动 kill 在途任务。令牌吊销后，task 侧后续 tool 回调命中 `/api/tools/execute/` → Phase 7/10 认证层对吊销令牌返回 401 → 该 tool 调用 graceful 失败（把错误作为工具结果回给 agent，不崩溃容器），任务继续跑完其余工作。
- 即「在途跑完、仅阻断新调用」靠执行端点的吊销校验天然实现，task 侧只需把 401/执行失败转成结构化工具错误、不致命。

### Claude's Discretion
- env 变量精确命名、remote_tools 注入是整份 active 工具还是按绑定/任务过滤（建议：dispatch 时按「该任务发起用户的绑定 + active」给集合；若实现成本高可先给 active 全集，绑定过滤留 follow-up）。
- 回调 endpoint base URL 的来源（复用 server 回调地址推导 vs 新 env）。
- task 侧 SDK MCP server 的模块位置（建议 `task/core/` 新增 `remote_tools.py`）。
- runner(Go) 透传字段命名与 executor env 装配点。
- 测试在 task/server/runner 各侧的组织。

</decisions>

<code_context>
## Existing Code Insights

### Reusable Assets
- task：`task/core/executor.py`（`ClaudeRunner._execute_claude` 装配 `ClaudeAgentOptions`——MCP server 挂载点）、`task/core/config.py`（`TaskConfig`，`FRIDAY_TASK_` env 前缀，已有 callback_url/callback_token）、`task/integrations/callback.py`（回调 HTTP 范式）。
- server：`server/tools/views.py`（Phase 10 `/api/tools/execute/` PAT 执行端点）、`server/tools/models.py`（`RemoteTool` + `ToolTokenBinding`）、`server/agents/sdk/mcp_adapter.py`（主 agent SDK MCP 适配蓝本）、`server/runners/dispatcher.py` + `server/runners/consumers.py`（任务 dispatch 链路）。
- runner：`runner/internal/docker/executor.go`（容器 env 注入点）。

### Established Patterns
- task 配置经 `FRIDAY_TASK_` 前缀环境变量注入（pydantic-settings）。
- server↔runner WebSocket dispatch + 回调；契约需跨 `server/runners/`、`runner/internal/`、`task/` 同步。
- claude-agent-sdk `query()` + `ClaudeAgentOptions`；SDK MCP server 用 `create_sdk_mcp_server`。
- 令牌脱敏：`interactions` 的 `redact_for_ledger` / `begin_interaction_run`（server 侧），credential-leak 防护 `common.logging`。

### Integration Points
- 三组件契约同步：dispatch payload（server）→ env 注入（runner Go）→ TaskConfig（task）。
- task → server `/api/tools/execute/` 回调（PAT 认证）。
- 既有测试：`task/tests/test_claude_sdk_integration.py`、`task/tests/test_callback.py`、`server/tests/test_remote_tool_execute.py`、`runner/internal/docker/executor_test.go`。
</code_context>

<specifics>
## Specific Ideas

- 「直传 PAT + 脱敏」是里程碑锁定取舍（v2 才换短 TTL 派生凭证）。
- 「吊销 graceful」靠执行端点吊销校验天然实现，task 侧把失败转结构化工具错误即可，避免中断/回滚复杂度。
- SDK MCP server 让 claude-agent-sdk 真正「加载并调用」远程工具，而非仅传 schema。
</specifics>

<resolution>
## Open Q1 裁决（直传 PAT vs PAT-02 冲突）—— 已定

用户跳过选择，由编排者裁决：**Option C + 机会性 B**（PAT-02「明文绝不落盘」是 CLAUDE.md 锁定的不可违背约束，排除 Option A 的加密留存）。

- 本期**完整交付机制**：task 侧 SDK MCP server 加载 `remote_tools` 并真正调用（RTOOL-02）；以直传 PAT 调 `/api/tools/execute/` 的回调链；吊销 graceful（RTOOL-04）；全链路注入管道（`FRIDAY_TASK_USER_TOKEN` + `FRIDAY_TASK_REMOTE_TOOLS` + 新增 `FRIDAY_TASK_TOOLS_ENDPOINT`，server→runner→task）；令牌脱敏。
- **PAT 明文来源（机会性 B）**：仅在「带 PAT 的实时请求线程」内可拿到明文时下传注入（绝不落盘）；无明文来源的后台/飞书触发任务，机制就绪但自动注入留 follow-up（不违反 PAT-02）。
- RTOOL-02 / RTOOL-04 本期完整达成；RTOOL-03 的注入机制 + 脱敏 + graceful 达成，"对所有 dispatch 场景自动解析 PAT 明文"作为已知 follow-up（不阻塞里程碑）。
</resolution>

<deferred>
## Deferred Ideas

- 短 TTL 派生凭证（broker token）+ tmpfs 注入替代直传 PAT（v2 PATX-04）。
- 吊销即时中断在途任务（本期选 graceful）。
- remote_tools 按绑定/任务精细过滤（若本期先给 active 全集，则细化留 follow-up）。
</deferred>
