# Phase 10: MCP 绑定用户令牌 + RemoteTool 执行端点 - Context

**Gathered:** 2026-06-09
**Status:** Ready for planning
**Mode:** Smart discuss（autonomous，推荐项已采纳；用户已授权代为决策）

<domain>
## Phase Boundary

让用户把自己的访问令牌（PAT）持久绑定给 skill/mcp 工具，被绑定的工具以令牌所有者身份与权限执行；用户可查看并解除自己的绑定；同时提供一个经令牌认证、按工具 name 执行的 **RemoteTool 执行端点**，供容器内 agent 回调调用。

覆盖 MCPB-01、MCPB-02、MCPB-03、RTOOL-01。依赖 Phase 7（PAT = 用户身份认证地基）。**不在本期**：task 容器实际消费 remote_tools / 注入令牌（Phase 11）。
</domain>

<decisions>
## Implementation Decisions

### 绑定模型与 API（MCPB-01 / MCPB-03）
- 新增 `tools.ToolTokenBinding` 模型：`user FK(accounts.User)`、`access_token FK(access_tokens.AccessToken)`、`remote_tool FK(tools.RemoteTool)`、`created_at`、`updated_at`。
  - `unique_together = (user, remote_tool)`：每个用户对同一工具最多一条绑定；重复绑定即更新所绑令牌。
  - `on_delete=CASCADE`：令牌或工具删除时绑定自动消失（绑定不应指向失效令牌/工具）。
- 绑定 CRUD API（CookieJWT 认证，按 `user=request.user` 隔离）：list（我的绑定）、create/upsert（把某 PAT 绑给某工具）、delete（解绑）。仅能管理自己的绑定（MCPB-03，复用 access_tokens 的 owner 隔离范式）。
- 可绑定工具范围：`RemoteTool.source ∈ {mcp, skill}`（绑定 UI 仅列 mcp/skill；builtin 内部工具不在绑定范围）。需一个「可绑定工具列表」只读 API 供 UI 选择。

### 执行身份语义（MCPB-02）
- 「被绑定的工具以令牌所有者身份与权限执行」：绑定表记录 tool→token 映射，是 Phase 11 容器回调时选用哪把令牌的持久依据。
- 本期的执行端点（RTOOL-01）直接以**调用方携带的 PAT** 认证 → `request.user = owner`（Phase 7 语义），以 owner 身份执行 `execute_tool`，审计指纹为该令牌。绑定表保证「容器侧知道某工具该用哪把用户令牌」，Phase 11 据此注入。

### RemoteTool 执行端点（RTOOL-01）
- 新增 `POST /api/tools/execute/`（或同级路由），`authentication_classes=[AccessTokenAuthentication]`（PAT）、`permission_classes=[IsAuthenticated]` fail-closed；body `{ "name": <tool_name>, "arguments": {...} }`。
- 处理：经 PAT 认证 → `begin_interaction_run`（审计，fingerprint=token_hash，复用 `interactions.entry`）→ 调 `tools.executor.execute_tool(name, arguments)` → 返回 `{ok, result|error}`（沿用 executor 既有返回契约）。
- 未认证/无效令牌一律拒（401/403）；工具不存在/超时/执行错误沿用 executor 的结构化 error。
- 将 `tools` app 的 urls 挂载进 `server/friday/urls.py`（如 `path("api/tools/", include("tools.urls"))`），当前 `tools` 无 urls/views，需新建。

### 前端（MCPB-01 / MCPB-03）
- 新增「工具令牌绑定」管理界面（沿用 access tokens 设置区/组件范式：列表 + 选择令牌 + 绑定/解绑）。
  - 列出可绑定的 mcp/skill 工具 + 各自当前绑定的令牌（仅显示令牌名称/前后缀，绝不显示明文）。
  - 绑定操作：从「我的有效令牌」下拉选一把绑给某工具；解绑操作；二次确认可选。
- 复用 `web/src/api`、`accessTokens` store/组件风格；新增 `api/toolBindings.ts` + 绑定管理组件/页面。

### Claude's Discretion
- 绑定 API/执行端点放在 `tools` app（建议）还是新建模块；路由前缀 `/api/tools/` vs `/v1/tools/`；绑定 UI 是独立页面还是 access token 设置内的子区。
- 执行端点是否限制只能执行「调用方令牌已绑定的工具」 vs 任意 active 工具（本期推荐：端点按 PAT 认证可执行任意 active 工具；绑定表用于 Phase 11 选令牌，不在执行端点做绑定强校验，避免与回调灵活性冲突——若需强校验可后续加）。
- 测试组织。

</decisions>

<code_context>
## Existing Code Insights

### Reusable Assets
- `server/tools/models.py`（`RemoteTool`：name unique / source builtin·mcp·skill / input_schema / is_active / config）。
- `server/tools/executor.py`（`execute_tool(name, arguments) -> {ok, result|error}`，含 timeout/command-not-allowed/execution-error 结构化处理）。
- `server/tools/registry.py`（`RemoteToolRegistry.aget_tool` / `aget_tools_payload` / active 过滤）。
- `server/tools/sources/{builtin,mcp_source,skill}.py`（三类来源执行实现）。
- 认证：`access_tokens.authentication.AccessTokenAuthentication`（Phase 7：PAT→owner）、`interactions.entry.begin_interaction_run`（审计入口）。
- access_tokens 范式：`AccessToken`、owner 隔离 ViewSet（绑定 CRUD 可仿）。
- 前端：`web/src/api/accessTokens.ts`、`stores/accessTokens.ts`、`components/accessTokens/*`（绑定 UI 范式）。

### Established Patterns
- adrf 异步 view + `sync_to_async`；owner 隔离 `get_queryset(created_by/user=request.user)`。
- MCP 入口审计走 `begin_interaction_run`（Phase 7 已 fail-closed）。
- urls 挂载在 `server/friday/urls.py`（如 `path("mcp/", include("mcp_tools.urls"))`）。

### Integration Points
- `server/friday/urls.py` 新增 `tools` 路由。
- Phase 11 将消费 `ToolTokenBinding` + 调用 `/api/tools/execute/`。
- `tools` 目前无 `urls.py`/`views.py`（views.py 为空），需新建。
</code_context>

<specifics>
## Specific Ideas

- 绑定表是「用户令牌 ↔ skill/mcp」的持久映射，是 Phase 11「容器以用户身份执行工具」的数据地基。
- 执行端点按 PAT 认证 + fail-closed，是 RTOOL-01「容器回调按 name 执行工具」的服务端入口。
- 绝不在任何响应/日志暴露令牌明文（沿用 access_tokens 契约）。
</specifics>

<deferred>
## Deferred Ideas

- task 容器消费 remote_tools / SDK MCP server 加载 / 令牌直传注入 + 脱敏 / 吊销 graceful（Phase 11）。
- 执行端点对「工具必须已绑定」的强校验、per-tool 细粒度 scope（v2）。
</deferred>
