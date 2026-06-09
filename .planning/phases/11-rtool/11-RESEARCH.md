# Phase 11: task 容器接通（RemoteTool 链路闭环） - Research

**Researched:** 2026-06-10
**Domain:** 跨组件分发契约（server Django → runner Go → task Python）+ claude-agent-sdk in-process SDK MCP server + PAT 注入/脱敏/吊销 graceful
**Confidence:** HIGH（代码路径全部在仓内验证）/ 但 RTOOL-03「直传 PAT 来源」存在 HIGH 严重度架构 blocker（见 Open Questions）

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions

**令牌注入（RTOOL-03 —— 直传 PAT + 脱敏）**
- 用户令牌以**直传 PAT** 形态注入容器（里程碑锁定，不做短 TTL 派生凭证——那是 v2 PATX-04）。
- 注入通道：沿用既有 dispatch 链 server(`runners/dispatcher.py` + `runners/consumers.py`)→runner(Go `internal/docker/executor.go`，env 注入)→task(`TaskConfig` 新增字段，`FRIDAY_TASK_` 前缀环境变量)。新增形如 `FRIDAY_TASK_USER_TOKEN`（直传 PAT）+ `FRIDAY_TASK_REMOTE_TOOLS`（工具 schema JSON）+ 回调端点 base（复用 callback_url 同源或新增 `FRIDAY_TASK_TOOLS_ENDPOINT`）。
- 脱敏：PAT 绝不进任何日志（task `print`/structlog、runner zerolog、server 审计）。task 侧对令牌做 redact；server 审计沿用 `redact_for_ledger`/`begin_interaction_run` 既有脱敏。runner 日志不打印 env 值。

**remote_tools 消费 + SDK MCP server（RTOOL-02）**
- task 容器从配置读取 `remote_tools`（name/description/input_schema 列表）。
- 用 claude-agent-sdk 的 `create_sdk_mcp_server` + `@tool`（或等价 SDK API）构建进程内 SDK MCP server，把每个 remote_tool 注册为 SDK 工具；通过 `ClaudeAgentOptions(mcp_servers={...}, allowed_tools=[...])` 挂给 `query()`（在 `task/core/executor.py` 的 `_execute_claude` options 装配处）。
- 每个工具的 handler：以 owner 的直传 PAT 调 Phase 10 的 `POST /api/tools/execute/`（`{name, arguments}`，`Authorization: Bearer friday_pat_...`）→ 返回 `{ok, result|error}` 转成 SDK 工具结果。
- 参考 `server/agents/sdk/mcp_adapter.py` 作为 task 侧实现蓝本。
- 无 remote_tools / 无用户令牌时：不挂 MCP server，行为与现状一致（向后兼容）。

**吊销 graceful（RTOOL-04）**
- 不主动 kill 在途任务。令牌吊销后，task 侧后续 tool 回调命中 `/api/tools/execute/` → 认证层对吊销令牌返回 401 → 该 tool 调用 graceful 失败（错误作为工具结果回给 agent，不崩溃容器），任务继续跑完其余工作。

### Claude's Discretion
- env 变量精确命名、remote_tools 注入是整份 active 工具还是按绑定/任务过滤（建议：dispatch 时按发起用户绑定 + active 给集合；成本高可先给 active 全集，绑定过滤留 follow-up）。
- 回调 endpoint base URL 的来源（复用 server 回调地址推导 vs 新 env）。
- task 侧 SDK MCP server 的模块位置（建议 `task/core/` 新增 `remote_tools.py`）。
- runner(Go) 透传字段命名与 executor env 装配点。
- 测试在 task/server/runner 各侧的组织。

### Deferred Ideas (OUT OF SCOPE)
- 短 TTL 派生凭证（broker token）+ tmpfs 注入替代直传 PAT（v2 PATX-04）。
- 吊销即时中断在途任务（本期选 graceful）。
- remote_tools 按绑定/任务精细过滤（若本期先给 active 全集，则细化留 follow-up）。
</user_constraints>

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| RTOOL-02 | task 容器消费 `remote_tools`，claude-agent-sdk 经 SDK MCP server 真正加载并调用（builtin/mcp/skill） | `SdkMcpTool`/`create_sdk_mcp_server` API（§Standard Stack + §Code Examples，验证自 `server/agents/sdk/mcp_adapter.py`）；`remote_tools` 已在 dispatch payload 中（`dispatcher.py:55,77`）；需在 `task/core/executor.py:280` options 装配处挂 `mcp_servers` |
| RTOOL-03 | 用户令牌以直传 PAT 经 server→runner→task 注入容器；日志/审计脱敏 | dispatch→env 注入链完整可复用（§Dispatch Contract Map）；**但 PAT 明文来源缺失**（AccessToken 仅存 sha256，§Open Q1 HIGH blocker） |
| RTOOL-04 | 令牌吊销时在途任务跑完仅阻断新调用（graceful） | 执行端点 `RemoteToolExecuteView.handle_exception` 已对吊销/无效 PAT 返回 401（`views.py:114-126`）；task handler 把非 200 转结构化工具错误即可（§Code Examples） |
</phase_requirements>

## Summary

本阶段是 v0.2.0 里程碑的收尾，跨三组件打通 RemoteTool 闭环。**好消息**：分发链路、SDK MCP server API、执行端点、脱敏基础设施全部已存在且在仓内可验证——`remote_tools` 已经从 `dispatcher.py` 进入 dispatch payload、经 Go runner `buildContainerEnv` 落成 `FRIDAY_REMOTE_TOOLS` 环境变量；server 主 agent 的 `mcp_adapter.py` 提供了「把 schema 列表动态注册为 N 个 SDK 工具」的精确蓝本；执行端点 `RemoteToolExecuteView` 对吊销令牌天然返回 401，使 RTOOL-04 graceful 几乎零成本。

**坏消息（必须在 plan 前消解）**：RTOOL-03 的「直传 PAT」假设 server 能拿到用户 PAT 明文来注入容器，但 `AccessToken` 模型**仅存 `token_hash = sha256(明文)` + prefix/suffix，明文创建时一次性展示后绝不落盘**（PAT-02 里程碑约束，`access_tokens/models.py:39-47`、`views.py:59-73`）。`ToolTokenBinding` 也只引用 `AccessToken` FK，不复制明文（`tools/models.py:38-42` 注释明示 T-10-05）。因此**当前数据模型下，dispatch 时没有任何地方能取出某用户的 PAT 明文**。这与「直传 PAT」决策直接冲突，且修复方案（绑定时加密留存明文）会撞 PAT-02「明文绝不落盘」约束。这是 plan 前必须由用户裁决的 HIGH 严重度 blocker（详见 Open Q1）。

次要 gap：runner 的 `callbackURL` 指向 **runner 本地中转**（`http://host.docker.internal:<port>/callback`，`client.go:141`），而 `/api/tools/execute/` 在 **Friday Server**，二者不同源——不能从 callback_url 推导工具端点，必须新增 `FRIDAY_TASK_TOOLS_ENDPOINT`（server 用 `settings.FRIDAY_BASE_URL` 拼 `/api/tools/execute/` 注入）。

**Primary recommendation:** 先就 Open Q1（PAT 明文来源）取得用户决策，再分三 wave 推进：(W1) task 侧 `remote_tools.py`（SdkMcpTool 动态注册 + httpx 回调 + 脱敏 + 401→结构化错误）+ TaskConfig 新字段，纯单测；(W2) 契约透传：server dispatch metadata 注入 `env_FRIDAY_TASK_*` + Go runner env 落地 + `FRIDAY_TASK_TOOLS_ENDPOINT`；(W3) `executor.py` 装配点挂 `mcp_servers`/`allowed_tools` + 端到端回归。

## Architectural Responsibility Map

| Capability | Primary Tier | Secondary Tier | Rationale |
|------------|-------------|----------------|-----------|
| 解析「该任务归属用户」并取 PAT 明文 | API/Backend (server `dispatcher.py`/`coding.py`) | DB（AccessToken/ToolTokenBinding） | 用户身份与令牌只在 server 侧可知；**但明文不可取**（Open Q1） |
| remote_tools schema 序列化进 payload | API/Backend (server `tools/registry.py`) | — | 已实现（`aget_tools_payload`） |
| dispatch payload → 容器环境变量 | Runner (Go `executor.go buildContainerEnv`) | WS 协议 (`dispatcher.py` payload) | runner 是唯一把任务变成容器的层；env 注入点已存在 |
| 容器内消费 remote_tools + 构建 SDK MCP server | Task (Python `task/core/`) | claude-agent-sdk | SDK 进程内工具必须与 `query()` 同进程 |
| 以用户身份执行工具 | API/Backend (server `RemoteToolExecuteView`) | tools/executor.py | 执行 + RBAC + 审计 + 吊销校验集中在 server 端点（Phase 10 已交付） |
| PAT 脱敏 | 每层各自负责 | — | task（print/structlog）、runner（zerolog 不打 env 值）、server（`redact_for_ledger`） |
| 吊销 graceful 阻断新调用 | API/Backend（端点 401） | Task（401→结构化错误不致命） | 执行端点的认证层是吊销的唯一真源；task 只需不崩 |

## Standard Stack

### Core
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| `claude-agent-sdk` | `==0.1.58`（task）/ `>=0.1.58,<0.2`（server） | 进程内 SDK MCP server + `query()` | 已是项目核心依赖，server `mcp_adapter.py` 已用同 API [VERIFIED: 仓内 `task/pyproject.toml:12` / `server/pyproject.toml:44`] |
| `httpx` | task 既有依赖 | 异步 HTTP 客户端，POST `/api/tools/execute/` | `task/integrations/callback.py` 已用 `httpx.AsyncClient` 同范式 [VERIFIED: 仓内 callback.py:18,142] |
| `pydantic-settings` | task 既有依赖 | `TaskConfig` 经 `FRIDAY_TASK_` 前缀读 env | 既有配置范式 [VERIFIED: 仓内 `task/core/config.py`] |
| `structlog` | task/server 既有 | 结构化日志（脱敏点） | 既有 [VERIFIED] |

### claude-agent-sdk 关键符号（task 侧直接 import）
| 符号 | 签名/用途 | 出处 |
|------|-----------|------|
| `SdkMcpTool` | `SdkMcpTool(name=str, description=str, input_schema=dict, handler=async (dict)->dict)` | [VERIFIED: `server/agents/sdk/mcp_adapter.py:15,74-79`] |
| `create_sdk_mcp_server` | `create_sdk_mcp_server(name=str, tools=list[SdkMcpTool]) -> McpSdkServerConfig` | [VERIFIED: mcp_adapter.py:15,127] |
| `McpSdkServerConfig` | 返回类型（TypedDict），传给 `ClaudeAgentOptions.mcp_servers` 字典的值 | [VERIFIED: mcp_adapter.py:15] |
| `ClaudeAgentOptions(mcp_servers={"name": cfg}, allowed_tools=[...])` | 挂载工具服务器 + 白名单 | [VERIFIED: `server/agents/sdk/runner.py:247-248`] |
| 工具白名单命名 | `mcp__{server_name}__{tool_name}` | [VERIFIED: mcp_adapter.py:163] |

> **注（D-04 决策对齐）：** CONTEXT 提到「`create_sdk_mcp_server` + `@tool`（或等价 SDK API）」。仓内蓝本 **不用 `@tool` 装饰器**，而是直接构造 `SdkMcpTool(...)` 实例并放进 `tools=[...]` 列表——这对「从 remote_tools schema 列表动态注册 N 个工具」是**更优**选择（`@tool` 是静态装饰器，无法按运行时 schema 动态生成）。**推荐：task 侧复刻 `SdkMcpTool` 直接构造法**，不用 `@tool`。`@tool` 装饰器在本仓未使用，其存在性标记 [ASSUMED]。

### Alternatives Considered
| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| `SdkMcpTool` 直接构造 | `@tool` 装饰器 | 装饰器是编译期静态注册，无法按 dispatch 传入的动态 schema 列表生成 N 个工具——**不适用本场景** |
| 新增 `FRIDAY_TASK_TOOLS_ENDPOINT` env | 复用 `callback_url` 推导 | callback_url 指向 runner 本地中转（非 Friday Server），无法推导出 `/api/tools/execute/`——**必须新增 env**（见 Pitfall 1） |

**Installation:** 无需新增依赖（`claude-agent-sdk`/`httpx`/`pydantic-settings`/`structlog` 全部已在 task 依赖中）。

## Package Legitimacy Audit

> 本阶段**不安装任何新外部包**——所有依赖（claude-agent-sdk、httpx、pydantic-settings、structlog）均为 task/server 既有依赖，已在生产 lockfile 中。Package Legitimacy Gate 不适用（无新增 install）。

| Package | Registry | Disposition |
|---------|----------|-------------|
| claude-agent-sdk | PyPI（既有，pinned ==0.1.58） | 既有，无需审计 |
| httpx / pydantic-settings / structlog | PyPI（既有 task 依赖） | 既有，无需审计 |

## Architecture Patterns

### System Architecture Diagram

```
                            ┌─────────────────────────── Friday Server (Django, adrf async) ──────────────────────────┐
 触发（workflow/webhook）→  │  AICodingNode._run_repo_coding (coding.py)                                              │
                            │     ├─ 解析归属用户 ⚠️(triggered_by / AgentSession.user，可能 None — Open Q1)            │
                            │     ├─ 解析用户 PAT 明文 ⚠️(AccessToken 仅存 hash，无明文来源 — Open Q1 BLOCKER)        │
                            │     └─ build DispatchTask(metadata={env_FRIDAY_TASK_USER_TOKEN, env_FRIDAY_TASK_TOOLS_ENDPOINT,...}) │
                            │  TaskDispatcher._try_assign (dispatcher.py)                                             │
                            │     └─ payload += remote_tools = RemoteToolRegistry.aget_tools_payload()  ✅已实现       │
                            └───────────────┬──────────────────────────────────────────────────────────────────────┘
                              channel_layer.send  (TASK_ASSIGN, WebSocket)
                                            ▼
                            ┌─────────────────────────── Runner (Go) ────────────────────────────────────────────────┐
                            │  client.go handleTaskAssign → TaskPayload{Payload: 整个 payload map}                    │
                            │  docker/executor.go buildContainerEnv():                                                │
                            │     ├─ FRIDAY_REMOTE_TOOLS = json(payload["remote_tools"])  ✅已实现                     │
                            │     ├─ metadata 中 env_ 前缀 → TrimPrefix → 容器 env  ✅已实现（API key 同款通道）       │
                            │     └─ (新增) FRIDAY_TASK_REMOTE_TOOLS / FRIDAY_TASK_USER_TOKEN / FRIDAY_TASK_TOOLS_ENDPOINT │
                            └───────────────┬──────────────────────────────────────────────────────────────────────┘
                              docker run (env 注入)
                                            ▼
                            ┌─────────────────────────── Task 容器 (Python) ─────────────────────────────────────────┐
                            │  TaskConfig (config.py) 读 FRIDAY_TASK_* env  → 新增 user_token/remote_tools/tools_endpoint │
                            │  (新) core/remote_tools.py: build_remote_tools_mcp_server(remote_tools, token, endpoint)  │
                            │     └─ 每个 schema → SdkMcpTool(handler=async: httpx POST endpoint Bearer <PAT>)        │
                            │  executor.py _execute_claude(): ClaudeAgentOptions(mcp_servers={...}, allowed_tools=[...])│
                            │     └─ query(prompt, options) ── tool 调用 ──┐                                          │
                            └──────────────────────────────────────────────┼──────────────────────────────────────────┘
                              httpx POST /api/tools/execute/ (Authorization: Bearer friday_pat_...)
                                            ▼
                            ┌─────────────────────────── Friday Server: RemoteToolExecuteView (views.py) ─────────────┐
                            │  AccessTokenAuthentication(PAT-only, fail-closed) → 吊销/过期 → 401 (graceful 真源)      │
                            │  begin_interaction_run(指纹=token_hash) → execute_tool(name, args) → {ok, result|error} │
                            │  arecord_tool_call(redact_for_ledger 脱敏) → 200 {ok,...}                               │
                            └─────────────────────────────────────────────────────────────────────────────────────────┘
```

### Recommended Project Structure（task 侧）
```
task/
├── core/
│   ├── config.py          # 扩展 TaskConfig：user_token / remote_tools / tools_endpoint
│   ├── executor.py        # _execute_claude 装配点挂 mcp_servers / allowed_tools
│   └── remote_tools.py    # 【新增】build_remote_tools_mcp_server + tool handler 工厂 + 脱敏
└── tests/
    ├── test_remote_tools.py        # 【新增】SdkMcpTool 注册 + handler 回调 + 401 graceful + 脱敏
    └── test_claude_sdk_integration.py  # 扩展：options 含 mcp_servers
```

### Pattern 1: 从 schema 列表动态注册 N 个 SdkMcpTool（task 侧蓝本）
**What:** 把 `remote_tools`（`[{name, description, input_schema}]`）逐个转成 `SdkMcpTool`，handler 闭包捕获 PAT + 端点。
**When to use:** RTOOL-02 核心。
（精确实现见 §Code Examples）

### Pattern 2: env 经 metadata `env_` 前缀透传（server→runner）
**What:** server 在 `DispatchTask.metadata` 写 `env_FRIDAY_TASK_XXX` 键，Go runner `buildContainerEnv` 自动 `TrimPrefix("env_")` 注入容器。
**When to use:** RTOOL-03 注入 PAT/端点的**首选通道**——无需改 Go 代码即可加新 env（API key 已走此路）。
**Source:** [VERIFIED: `runner/internal/docker/executor.go:120-131` + `server/workflows/nodes/ai/coding.py:846-870`]
**例外：** `remote_tools` 目前走顶层 payload → `FRIDAY_REMOTE_TOOLS`（非 `FRIDAY_TASK_` 前缀），TaskConfig 读不到。两条路二选一（见 Pitfall 2）。

### Anti-Patterns to Avoid
- **把 PAT 写进 prompt 或 task_description**：会进 SubAgentSession.last_output / ExecutionContext.input_prompt（落库），违反脱敏。PAT 只能进 env + Authorization header。
- **在 task `print(f"[task:tool] {block.name}({tool_input})")` 打印工具入参**（executor.py:327）：若工具参数含敏感值会进 docker logs。注意 PAT 不应出现在工具 arguments 中（它在 handler 内部从 config 取，不在 LLM 可见参数里）——天然隔离，但要确保 handler 不把 token 拼进返回文本。
- **依赖 `callback_url` 推导工具端点**：runner 中转 ≠ Friday Server（Pitfall 1）。

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| 进程内 MCP 工具服务器 | 自己起 stdio/HTTP MCP server 子进程 | `create_sdk_mcp_server` + `SdkMcpTool`（进程内） | SDK 原生支持，零子进程开销，mcp_adapter.py 已验证 |
| schema→工具适配 | 手写 JSON-RPC tool 协议 | `SdkMcpTool(input_schema=...)` | SDK 直接吃 JSON Schema |
| 吊销检测 | task 侧轮询令牌状态 / server 主动 kill 容器 | 执行端点 401（认证层天然校验） | RTOOL-04 决策：graceful，端点是唯一真源 |
| PAT 脱敏（审计侧） | 自己写 redact | `interactions.redact_for_ledger` / `begin_interaction_run` | Phase 10 端点已接入（views.py:132,144） |
| 工具执行分发 | task 侧实现 builtin/mcp/skill | server `execute_tool`（端点背后） | Phase 10 已交付，task 只回调 |

**Key insight:** task 侧只做「薄适配层」——把 SDK 工具调用转成一次 HTTP POST，真正的工具执行/RBAC/审计/吊销全在 server 端点。不要在容器里重新实现工具逻辑。

## Dispatch Contract Map（RTOOL-03 注入点逐跳精确定位）

| 跳 | 文件:行 | 现状 | 本期改动 |
|----|---------|------|----------|
| 1. 构建 DispatchTask | `server/workflows/nodes/ai/coding.py:852-871` | metadata 注入 `env_FRIDAY_TASK_CLAUDE_*`（API key 同款） | **加** `env_FRIDAY_TASK_USER_TOKEN`（PAT 明文⚠️Open Q1）+ `env_FRIDAY_TASK_TOOLS_ENDPOINT`（`{FRIDAY_BASE_URL}/api/tools/execute/`）；按需 `env_FRIDAY_TASK_REMOTE_TOOLS` |
| 2. payload 加 remote_tools | `server/runners/dispatcher.py:53-55,77` | `payload["remote_tools"] = aget_tools_payload()`（active 全集） | 可选：按归属用户绑定过滤（Discretion；成本高则保持 active 全集） |
| 3. WS 发送 TASK_ASSIGN | `dispatcher.py:60-81` (`channel_layer.send`) | payload 含 task_id/prompt/metadata/remote_tools | 无需改（透传） |
| 4. runner 解析 payload | `runner/internal/ws/client.go:311-319` | `TaskPayload{Payload: 整个 map}` | 无需改 |
| 5. env 装配 | `runner/internal/docker/executor.go:90-132` | `FRIDAY_REMOTE_TOOLS`(顶层) + metadata `env_` TrimPrefix | **若走 metadata 路**：零 Go 改动；**若要 `FRIDAY_TASK_REMOTE_TOOLS`**：加一行映射（Pitfall 2） |
| 6. callbackURL/token 来源 | `runner/internal/ws/client.go:140-141` | `http://host.docker.internal:<port>/callback`（**runner 本地中转，非 Friday Server**） | 不可用于工具端点；工具端点走 step1 的 `FRIDAY_TASK_TOOLS_ENDPOINT` |
| 7. TaskConfig 读 env | `task/core/config.py:14-150` | `FRIDAY_TASK_` 前缀字段 | **加** `user_token` / `remote_tools` / `tools_endpoint` 字段 |
| 8. SDK options 装配 | `task/core/executor.py:280-290` | `ClaudeAgentOptions(...)` 无 mcp_servers | **加** `mcp_servers={...}` + `allowed_tools=[...]`（仅当有 remote_tools+token） |
| 9. 工具回调目标 | `server/tools/views.py:108-158` (`RemoteToolExecuteView`) | PAT-only，已审计/吊销校验 | 无需改（Phase 10 已交付） |

**归属用户解析链（server 侧，用于解析 PAT/绑定过滤）：**
- `node_execution_id` → `NodeExecution.workflow_execution.triggered_by`（FK `accounts.User`，`SET_NULL` 可空，`execution.py:111`）
- 或 `SubAgentSession.main_session` → `AgentSession.user`（FK 可空，`agents/models.py:45-51`；`coding.py:893-896` 占位 session 时为 None）
- ⚠️ 两条链都可能为 None（webhook/定时触发无 triggered_by；占位 main_session 无 user）。

## Common Pitfalls

### Pitfall 1: 误用 callback_url 推导工具端点
**What goes wrong:** 容器调 `/api/tools/execute/` 时打到 runner 本地中转端口（host.docker.internal:<callbackPort>/callback），404 或路由错误。
**Why:** runner 的 callbackURL 是**runner 进程的本地回调服务器**（`client.go:141`），与 Friday Server 不同源/不同主机。
**How to avoid:** server 用 `settings.FRIDAY_BASE_URL`（`summary_service.py:204` 已有此用法）拼 `/api/tools/execute/`，经 `env_FRIDAY_TASK_TOOLS_ENDPOINT` 注入。
**Warning signs:** 工具调用全部 404/connection refused。

### Pitfall 2: `FRIDAY_REMOTE_TOOLS` vs `FRIDAY_TASK_REMOTE_TOOLS` 前缀错位
**What goes wrong:** TaskConfig（`env_prefix="FRIDAY_TASK_"`）读不到 Go 现注入的 `FRIDAY_REMOTE_TOOLS`（无 `TASK_`）。
**Why:** `executor.go:104` 写的是 `FRIDAY_REMOTE_TOOLS`（旧顶层协议），pydantic-settings 只认 `FRIDAY_TASK_` 前缀。
**How to avoid:** 二选一——(a) server 在 metadata 写 `env_FRIDAY_TASK_REMOTE_TOOLS`（零 Go 改动，**推荐**）；或 (b) Go `buildContainerEnv` 加 `"FRIDAY_TASK_REMOTE_TOOLS=" + string(remoteTools)`。注意 `remote_tools` 是 JSON 字符串，TaskConfig 字段建议 `str` 后在代码内 `json.loads`，或用 pydantic `Json[list[...]]`。
**Warning signs:** 容器内 remote_tools 永远为空，MCP server 不挂载。

### Pitfall 3: 同步 ORM 在 async dispatch 路径解析 PAT/用户
**What goes wrong:** 在 `_run_repo_coding`（async）里直接 `WorkflowExecution.objects.get(...)` 触发 SynchronousOnlyOperation。
**Why:** adrf 异步上下文需 `async for`/`aget`/`sync_to_async`。
**How to avoid:** 用 `await ...aget()` / `async for`（仓内既有范式，`coding.py:882-890` 已用 `.afirst()`）。
**Warning signs:** SynchronousOnlyOperation 异常。

### Pitfall 4: PAT 泄漏进日志/审计
**What goes wrong:** PAT 出现在 docker logs、runner zerolog、SubAgentSession.last_output、ExecutionContext.environment_vars。
**Why:** runner `ExecutionContext.environment_vars`（`subagent/models.py:582`）若收集容器全部 env 会含 PAT；task `print` 若打印 config 会泄漏。
**How to avoid:**
- task：handler 内 PAT 只进 `Authorization` header，绝不进 `print`/structlog/返回文本；TaskConfig 的 `user_token` 字段加 `repr`/log 脱敏（结构化日志只记 `has_user_token=bool`）。
- runner：zerolog 现状不打印 env 值（`executor.go` 只 `log.Info().Str("task_id",...)`，未打 env）——**保持**，且若 `ExecutionContext.environment_vars` 收集 env，须在 server 侧 redact `FRIDAY_TASK_USER_TOKEN`。
- server：审计走 `redact_for_ledger`（views.py:144 已接）；明文 PAT 只在 Authorization header，不入审计 input/output。
**Warning signs:** grep docker logs / DB 出现 `friday_pat_`。

### Pitfall 5: 401 graceful 误判为容器崩溃
**What goes wrong:** httpx 对 401 调 `raise_for_status()` 抛 `HTTPStatusError`，若未捕获会冒泡终止 query/容器。
**Why:** callback.py 用 `raise_for_status()`（callback.py:149）。
**How to avoid:** 工具 handler **不要** `raise_for_status`；显式判 `response.status_code`，401/403/5xx 一律转成 SDK 工具错误结果 `{"content":[{"type":"text","text":"工具不可用：令牌已失效或无权限"}],"is_error":True}`，**返回而非抛**——agent 收到错误继续跑（RTOOL-04）。
**Warning signs:** 令牌吊销后整个任务失败而非单次工具调用失败。

## Code Examples

### task/core/remote_tools.py（新增——核心实现蓝本）
```python
# Source: 改编自 server/agents/sdk/mcp_adapter.py（VERIFIED 蓝本）
from __future__ import annotations
from typing import Any
import httpx
import structlog
from claude_agent_sdk import McpSdkServerConfig, SdkMcpTool, create_sdk_mcp_server

logger = structlog.get_logger(__name__)
REMOTE_MCP_SERVER_NAME = "friday-remote-tools"

def _make_handler(tool_name: str, tools_endpoint: str, user_token: str):
    async def handler(args: dict[str, Any]) -> dict[str, Any]:
        # PAT 只进 Authorization header，绝不进日志/返回文本（脱敏，RTOOL-03）
        try:
            async with httpx.AsyncClient() as client:
                resp = await client.post(
                    tools_endpoint,
                    json={"name": tool_name, "arguments": args},
                    headers={"Authorization": f"Bearer {user_token}",
                             "Content-Type": "application/json"},
                    timeout=60.0,
                )
        except httpx.HTTPError as e:
            logger.warning("remote_tool_transport_error", tool=tool_name, error=str(e))
            return {"content": [{"type": "text", "text": f"工具传输错误: {e}"}], "is_error": True}

        # 吊销 graceful（RTOOL-04）：401/403 → 结构化工具错误，不抛、不崩容器
        if resp.status_code in (401, 403):
            logger.warning("remote_tool_unauthorized", tool=tool_name, status=resp.status_code)
            return {"content": [{"type": "text", "text": "工具不可用：令牌已失效或无权限"}], "is_error": True}
        if resp.status_code != 200:
            return {"content": [{"type": "text", "text": f"工具执行失败: HTTP {resp.status_code}"}], "is_error": True}

        body = resp.json()  # {"ok": bool, "result"|"error": ...}
        if body.get("ok"):
            return {"content": [{"type": "text", "text": str(body.get("result"))}]}
        return {"content": [{"type": "text", "text": str(body.get("error"))}], "is_error": True}
    return handler

def build_remote_tools_mcp_server(
    remote_tools: list[dict[str, Any]], tools_endpoint: str, user_token: str,
) -> McpSdkServerConfig | None:
    # 向后兼容（CONTEXT 决策）：无工具或无令牌 → 不挂 MCP server
    if not remote_tools or not user_token or not tools_endpoint:
        return None
    sdk_tools: list[SdkMcpTool[dict[str, Any]]] = []
    for t in remote_tools:
        sdk_tools.append(SdkMcpTool(
            name=t["name"],
            description=t.get("description", ""),
            input_schema=t.get("input_schema", {}),
            handler=_make_handler(t["name"], tools_endpoint, user_token),
        ))
    logger.info("remote_mcp_server_created", tool_count=len(sdk_tools),
                tools=[t["name"] for t in remote_tools])  # 不打印 token
    return create_sdk_mcp_server(name=REMOTE_MCP_SERVER_NAME, tools=sdk_tools)

def remote_allowed_tools(remote_tools: list[dict[str, Any]]) -> list[str]:
    return [f"mcp__{REMOTE_MCP_SERVER_NAME}__{t['name']}" for t in remote_tools]
```

### task/core/executor.py 装配点改动（_execute_claude，约 line 280）
```python
# Source: 现有 ClaudeAgentOptions 装配 + runner.py:247-248 模式
from .remote_tools import build_remote_tools_mcp_server, remote_allowed_tools

mcp_server = build_remote_tools_mcp_server(
    self.config.remote_tools, self.config.tools_endpoint, self.config.user_token,
)
options_kwargs = dict(
    system_prompt=self._get_system_prompt(),
    permission_mode=permission_mode,
    cwd=str(self.workspace),
    model=main_model,
    max_turns=max_turns or self.config.claude_max_turns,
    setting_sources=["project"],
    stderr=_stderr_handler,
    env=env_vars,
    extra_args={"debug-to-stderr": None},
)
if mcp_server is not None:
    options_kwargs["mcp_servers"] = {REMOTE_MCP_SERVER_NAME: mcp_server}
    options_kwargs["allowed_tools"] = remote_allowed_tools(self.config.remote_tools)
options = ClaudeAgentOptions(**options_kwargs)
```

### task/core/config.py 新增字段
```python
user_token: str = Field(default="", description="用户直传 PAT（friday_pat_...），仅注入 Authorization，绝不日志")
remote_tools: list[dict] = Field(default_factory=list, description="RemoteTool schema 列表（FRIDAY_TASK_REMOTE_TOOLS JSON）")
tools_endpoint: str = Field(default="", description="Friday Server /api/tools/execute/ 完整 URL")
```
> 注：pydantic-settings 从 env 读 `list[dict]` 需 JSON 解析；`FRIDAY_TASK_REMOTE_TOOLS='[{...}]'` 会被自动 `json.loads`（pydantic v2 对复杂类型默认 JSON 解码 env 值）。若失败则改 `str` + 代码内 `json.loads`。[ASSUMED — plan 时用单测确认 pydantic 自动解码行为]

### server 端 dispatch metadata 注入（coding.py:846 附近，扩展 anthropic_env 模式）
```python
from django.conf import settings
tools_env: dict[str, str] = {}
base = getattr(settings, "FRIDAY_BASE_URL", "")
user_pat = await _resolve_user_pat(...)  # ⚠️ Open Q1：明文来源未定
if base and user_pat:
    tools_env["env_FRIDAY_TASK_TOOLS_ENDPOINT"] = f"{base.rstrip('/')}/api/tools/execute/"
    tools_env["env_FRIDAY_TASK_USER_TOKEN"] = user_pat
    tools_env["env_FRIDAY_TASK_REMOTE_TOOLS"] = json.dumps(remote_tools_payload)
# metadata={**anthropic_env, **tools_env, ...}
```

## Runtime State Inventory

> 本阶段为「新增功能 + 跨组件契约扩展」，非 rename/refactor。但涉及跨进程契约同步，列关键运行态：

| Category | Items Found | Action Required |
|----------|-------------|------------------|
| Stored data | `AccessToken.token_hash`（sha256，**无明文**）；`ToolTokenBinding`（仅 FK 引用，无明文）；`RemoteTool.input_schema`（工具 schema 真源） | RTOOL-03 注入需明文 PAT，但**存储里没有**（Open Q1 blocker） |
| Live service config | Runner 通过 WS 在线注册（channel_name）；`settings.FRIDAY_BASE_URL` 决定工具端点 base | 确认部署环境 `FRIDAY_BASE_URL` 已配置且容器可达（host.docker.internal 路由） |
| OS-registered state | 无 OS 级注册改动 | None — 验证为容器 env 注入，无 launchd/systemd 改动 |
| Secrets/env vars | 新增 env：`FRIDAY_TASK_USER_TOKEN`（PAT 明文，敏感）、`FRIDAY_TASK_TOOLS_ENDPOINT`、`FRIDAY_TASK_REMOTE_TOOLS` | 容器 env 中 PAT 明文必须脱敏出所有日志；`ExecutionContext.environment_vars` 若收集须 redact |
| Build artifacts | task 容器镜像 `friday/claude-code:latest`（`coding.py:856`） | 新增 `remote_tools.py` 需重新构建/发布 task 镜像后才生效 |

**跨进程契约同步点（必须三侧一致）：** dispatch payload 字段名（server）↔ env 键名（runner Go）↔ TaskConfig 字段（task）。命名约定建议统一走 metadata `env_FRIDAY_TASK_*` 前缀（零 Go 改动）。

## State of the Art

| Old Approach | Current Approach | Impact |
|--------------|------------------|--------|
| remote_tools 仅作 schema 传入（不可调用） | SDK MCP server 真正加载并执行（RTOOL-02） | claude-agent-sdk `create_sdk_mcp_server` 进程内工具是当前标准 |
| 短 TTL broker token | 本期直传 PAT（v2 才 PATX-04） | 简化注入链，但需明文来源（Open Q1） |

**Deprecated/outdated:** 无（本仓 claude-agent-sdk 0.1.58 即目标版本，API 已在 mcp_adapter.py 验证）。

## Assumptions Log

| # | Claim | Section | Risk if Wrong |
|---|-------|---------|---------------|
| A1 | `@tool` 装饰器存在于 0.1.58（本仓未用） | Standard Stack | 低——推荐用 `SdkMcpTool` 直接构造（已 VERIFIED），不依赖 `@tool` |
| A2 | pydantic-settings 自动 JSON 解码 `FRIDAY_TASK_REMOTE_TOOLS` env 为 `list[dict]` | Code Examples | 中——失败则用 `str` + 手动 `json.loads`，单测验证 |
| A3 | `settings.FRIDAY_BASE_URL` 在生产/容器场景已配置且容器可达 | Pitfall 1 | 中——未配置则工具端点为空，MCP server 不挂（向后兼容降级），需部署文档强调 |
| A4 | 容器经 `host.docker.internal` 可访问 Friday Server（`ExtraHosts` 已配 `executor.go:69`） | Architecture | 中——k8s 场景需另解（本期 Docker executor 为主，k8s executor 是 stub `k8s/executor.go:20`） |
| A5 | `claude-agent-sdk==0.1.58` task 侧与 server 侧同 API（server `>=0.1.58,<0.2`） | Standard Stack | 低——同 major.minor 区间，API 稳定 |

## Open Questions (RESOLVED)

### Open Q1 ⚠️ HIGH BLOCKER — 直传 PAT 的明文来源不存在
- **What we know:** `AccessToken` 仅存 `token_hash = sha256(明文)` + prefix/suffix；明文创建时一次性返回后**绝不落盘**（PAT-02 里程碑硬约束，`access_tokens/models.py:39-47`、`views.py:59-73`）。`ToolTokenBinding` 只引用 `AccessToken` FK，不复制明文（`tools/models.py:38-42`，T-10-05 注释明示）。
- **What's unclear:** dispatch 时（workflow/webhook 触发，远离原始请求）如何取到某用户的 PAT 明文来注入 `FRIDAY_TASK_USER_TOKEN`？当前**无任何数据源**。
- **额外维度：** 归属用户本身也可能为 None（`triggered_by` SET_NULL 可空；占位 `AgentSession` 无 user）。
- **Recommendation（须用户裁决，HIGH 优先级，plan 前必须定）：**
  1. **Option A（推荐但冲突 PAT-02）：** 绑定时（`ToolTokenBindingViewSet.acreate`）或 PAT 创建时捕获明文，用 Fernet（`cryptography` 既有依赖）加密存一列 `encrypted_plaintext`，仅供容器注入读取。**直接冲突 PAT-02「明文绝不落盘」**——需用户显式批准放宽该约束（或限定「仅绑定到工具的令牌加密留存」的折中）。
  2. **Option B（约束兼容但覆盖窄）：** 仅当任务由**携带 PAT 的认证请求**直接触发时，把 `request.auth` 的明文 PAT 顺着 dispatch 线程下传。覆盖不到 webhook/定时触发，且需改 dispatch 签名贯穿到 `_run_repo_coding`。
  3. **Option C（缩范围）：** 本期 RTOOL-03 只交付**注入机制 + 脱敏 + SDK 消费 + graceful**（用 CLI/手填/测试 PAT 验证全链路），把「自动解析存量用户 PAT」标记为依赖明文来源的 follow-up。
  - **建议默认走 Option C 推进机制，并就 Option A 的 PAT-02 放宽与用户确认**——这样 RTOOL-02/04 可独立完成，RTOOL-03 的「机制」可完成、「自动解析存量 PAT」按裁决落地。
- **Severity:** HIGH — 不解决则 RTOOL-03 的「以真实用户身份自动回调」无法在真实 workflow 触发场景端到端成立。

### Open Q2 — remote_tools 过滤粒度（Discretion）
- active 全集 vs 按归属用户绑定过滤。绑定过滤需先解决 Open Q1 的「归属用户解析」。**Recommendation:** 本期先 active 全集（现状 `aget_tools_payload` 即全集），绑定过滤留 follow-up（CONTEXT 已授权此降级）。

### Open Q3 — k8s executor 透传
- `runner/internal/k8s/executor.go:20` 是 stub。新 env 在 k8s 路径未实现。**Recommendation:** 本期聚焦 Docker executor（生产主路径），k8s env 注入标记 follow-up。

## Environment Availability

| Dependency | Required By | Available | Version | Fallback |
|------------|------------|-----------|---------|----------|
| claude-agent-sdk | task SDK MCP server | ✓（task 依赖） | ==0.1.58 | — |
| httpx | task 工具回调 | ✓（task 依赖） | 既有 | — |
| Docker daemon | runner 起容器 | ✓（runner 运行前提） | — | — |
| `settings.FRIDAY_BASE_URL` | 工具端点 base | ⚠️ 部署相关 | — | 未配 → MCP server 不挂（向后兼容降级） |
| 用户 PAT 明文 | RTOOL-03 注入 | ✗（**无存储来源**） | — | **无 fallback — Open Q1 blocker** |

**Missing dependencies with no fallback:** 用户 PAT 明文来源（Open Q1）——阻塞 RTOOL-03 自动场景。
**Missing dependencies with fallback:** `FRIDAY_BASE_URL` 未配时优雅降级为「不挂 MCP server」（向后兼容）。

## Validation Architecture

### Test Framework
| Property | Value |
|----------|-------|
| Framework (task) | pytest + pytest-asyncio（`task/tests/`，`test_callback.py`/`test_claude_sdk_integration.py` 既有） |
| Framework (server) | pytest + pytest-django + adrf（`server/tests/`，`test_remote_tool_execute.py` 既有） |
| Framework (runner) | Go `testing` + gotest.tools（`runner/internal/docker/executor_test.go` 既有） |
| Quick run (task) | `cd task && uv run pytest tests/test_remote_tools.py -x` |
| Quick run (server) | `cd server && uv run pytest tests/test_coding_*.py tests/test_remote_tool_execute.py -x` |
| Quick run (runner) | `cd runner && go test ./internal/docker/ -run TestBuildContainerEnv` |
| Full suite | task: `uv run pytest`；server: `uv run pytest`；runner: `make test` |

### Phase Requirements → Test Map
| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| RTOOL-02 | schema 列表 → N 个 SdkMcpTool 注册 | unit | `uv run pytest tests/test_remote_tools.py::test_builds_n_tools -x` | ❌ Wave 0（task） |
| RTOOL-02 | 无 remote_tools/token → 不挂 server（向后兼容） | unit | `...::test_no_tools_returns_none -x` | ❌ Wave 0 |
| RTOOL-02 | executor 装配 options 含 mcp_servers/allowed_tools | unit | `tests/test_claude_sdk_integration.py::test_options_include_mcp` | ⚠️ 扩展既有 |
| RTOOL-03 | dispatch metadata 注入 `env_FRIDAY_TASK_USER_TOKEN/TOOLS_ENDPOINT` | unit | `server: tests/test_coding_*.py::test_injects_tools_env` | ⚠️ 扩展（mirror `test_coding_anthropic_base_url_passthrough.py`） |
| RTOOL-03 | runner env 透传新键 | unit | `runner: go test ./internal/docker/ -run TestBuildContainerEnv_RemoteTools` | ⚠️ 扩展 `executor_test.go` |
| RTOOL-03 | 脱敏：token 不进 task 日志/返回文本 | unit | `task: ...test_remote_tools.py::test_token_not_in_logs` | ❌ Wave 0 |
| RTOOL-04 | handler 收 401 → 结构化错误 `is_error`，不抛 | unit | `task: ...::test_401_returns_tool_error_not_raise` | ❌ Wave 0 |
| RTOOL-04 | handler 收 200 ok → 文本结果 | unit | `task: ...::test_success_returns_content` | ❌ Wave 0 |

### Sampling Rate
- **Per task commit:** 对应组件 quick run（task/server/runner 各自）
- **Per wave merge:** 三组件各自 full suite
- **Phase gate:** 三组件全绿 + `makemigrations --check`（若 server 加字段则有迁移）before `/gsd-verify-work`

### Wave 0 Gaps
- [ ] `task/tests/test_remote_tools.py` — 覆盖 RTOOL-02/03/04（用 monkeypatch httpx，mock query，无需 live Claude）
- [ ] `task/tests/conftest.py` — 扩展 `mock_config` 含 `user_token`/`remote_tools`/`tools_endpoint`（既有 `mock_config` fixture 见 `test_callback.py`）
- [ ] server: 扩展 coding dispatch 测试断言新 metadata 键（mirror `test_coding_anthropic_base_url_passthrough.py` 的 dispatch 捕获范式）
- [ ] runner: 扩展 `executor_test.go` 断言新 env 键（`envMap(buildContainerEnv(...))` 既有 helper）

**无 live Claude 的测试法（关键）：** SDK MCP server 的 handler 是普通 async 函数——单测**直接调 handler(args)**，monkeypatch `httpx.AsyncClient.post` 返回伪 200/401，断言返回结构与脱敏；**无需** mock `query()`。`build_remote_tools_mcp_server` 返回 `McpSdkServerConfig`，断言其 tool 数量/名称即可。`executor.py` 装配点用 monkeypatch `query`（既有 `test_claude_sdk_integration.py` 已 mock）断言 options 含 `mcp_servers`。

## Security Domain

### Applicable ASVS Categories
| ASVS Category | Applies | Standard Control |
|---------------|---------|-----------------|
| V2 Authentication | yes | PAT 经 `AccessTokenAuthentication` 前缀闸门 + sha256 指纹（Phase 7 已交付） |
| V3 Session Management | yes | 吊销即时生效靠端点认证层（RTOOL-04 graceful） |
| V4 Access Control | yes | 工具以 PAT owner 的 RBAC 执行（Phase 10 端点 `IsAuthenticated`+owner） |
| V5 Input Validation | yes | `RemoteToolExecuteSerializer` 校验 name/arguments（views.py:129） |
| V6 Cryptography | yes (若选 Open Q1 Option A) | Fernet（`cryptography` 既有）——**绝不**自写加密 |
| V7 Logging（脱敏） | yes | PAT 绝不进 task print/structlog、runner zerolog、server 审计（`redact_for_ledger`） |

### Known Threat Patterns
| Pattern | STRIDE | Standard Mitigation |
|---------|--------|---------------------|
| PAT 泄漏进 docker logs / DB | Information Disclosure | token 只进 Authorization header；env 收集时 redact `FRIDAY_TASK_USER_TOKEN`（Pitfall 4） |
| 吊销后令牌继续被用 | Elevation/Spoofing | 端点认证层每次校验吊销（RTOOL-04，401） |
| 容器内提取 PAT 横向调用 | Elevation | 本期接受（直传 PAT 里程碑取舍）；v2 PATX-04 短 TTL broker 缓解 |
| 任务以错误用户身份调用工具 | Spoofing | 归属用户解析须正确（Open Q1）；解析不到则不注入（fail-closed 降级，不挂 server） |

## Project Constraints (from CLAUDE.md / .cursor/rules)
- 后端 Django 5.1+ adrf 异步：ORM 经 `sync_to_async`/`aget`/`async for`（Pitfall 3）。
- 凭证脱敏强约束：`common.logging` credential-leak 防护；审计 `redact_for_ledger`。
- 注释/docstring 用中文（zh-CN）。
- Go runner：`gofmt`；zerolog 结构化日志。
- Python：`ruff format` 行宽 100，target py314；mypy 严格。
- 向后兼容：无 remote_tools/无 token 时行为与现状一致（不挂 MCP server）。

## Sources

### Primary (HIGH confidence) — 全部仓内代码验证
- `server/agents/sdk/mcp_adapter.py` — SdkMcpTool/create_sdk_mcp_server 精确签名与用法（蓝本）
- `server/agents/sdk/runner.py:241-266` — ClaudeAgentOptions(mcp_servers/allowed_tools) 装配
- `server/runners/dispatcher.py` / `server/runners/consumers.py` — dispatch payload + remote_tools 注入
- `server/workflows/nodes/ai/coding.py:807-913` — DispatchTask 构建 + metadata env_ 注入范式
- `server/tools/views.py` / `models.py` / `registry.py` / `executor.py` — Phase 10 执行端点契约
- `server/access_tokens/{models,views,authentication}.py` — PAT 仅存 hash（Open Q1 依据）
- `runner/internal/docker/executor.go` / `runner/internal/ws/{client,protocol}.go` — env 装配 + payload 解析
- `task/core/{executor,config}.py` / `task/integrations/callback.py` — SDK options 装配点 + httpx 范式
- `task/pyproject.toml` / `server/pyproject.toml` — claude-agent-sdk 版本

### Secondary (MEDIUM)
- `server/repositories/summary_service.py:204-218` — `FRIDAY_BASE_URL` 注入 callback 范式

### Tertiary (LOW)
- `@tool` 装饰器在 0.1.58 的存在性（本仓未用，标 [ASSUMED] A1）

## Metadata

**Confidence breakdown:**
- 分发契约/注入点映射: HIGH — 三组件代码逐跳验证
- SDK MCP server API: HIGH — server `mcp_adapter.py`/`runner.py` 生产代码同 API
- 吊销 graceful: HIGH — 端点 401 已实现，task 只需不抛
- PAT 明文来源 (RTOOL-03 自动场景): LOW/BLOCKED — 数据模型无明文来源（Open Q1）

**Research date:** 2026-06-10
**Valid until:** 2026-07-10（稳定内部代码；SDK 版本锁定）
