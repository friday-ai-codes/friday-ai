# Architecture Research

**Domain:** Brownfield 集成 — v0.2.0「用户身份令牌与 Agent 工具打通」接入既有 Friday AI 架构
**Researched:** 2026-06-09
**Confidence:** HIGH（结论几乎全部基于现有代码；唯 claude-agent-sdk `mcp_servers` 具体签名为 MEDIUM，依据 milestone 上下文 + SDK 训练知识）

> 本文回答「这三条新能力如何接入既有架构」，**不重研已存在基线**。所有集成点具体到文件 / 类 / 函数，标注 **NEW（新增）** vs **MOD（修改）**，并给出考虑依赖的 build order 与跨进程（server/runner/task）契约同步点。

---

## Standard Architecture

### 当前相关组件全景（已存在基线）

```
┌──────────────────────────────────────────────────────────────────────┐
│ 入口认证层                                                              │
│  AccessTokenAuthentication  → 现返回 (None, token)  ← 改造点①           │
│   re-export: interactions.entry.AccessTokenAuthentication              │
│  OptionalJWTAuthentication + ChatKeyAuthentication（chat 专用）         │
├──────────────────────────────────────────────────────────────────────┤
│ API 视图层                                                              │
│  mcp_tools/views.McpToolView   auth=[AccessToken] perm=[AllowAny] ← ②  │
│  chat/views.*                  auth=[OptionalJWT,ChatKey] perm=[Chat]  │
│  tools/                        （无 urls / 无 view）           ← ③ NEW  │
├──────────────────────────────────────────────────────────────────────┤
│ 领域 / 服务层                                                          │
│  permissions.PermissionService.has_project_access(user,project,role)   │
│  chat.ConversationService.{list,create,delete,get}_conversation        │
│  tools.executor.execute_tool(name,args) ← 仅内部可达，无 HTTP 入口      │
│  tools.RemoteToolRegistry.aget_tools_payload()                         │
├──────────────────────────────────────────────────────────────────────┤
│ 持久层                                                                  │
│  AccessToken(created_by FK, token_hash, expires_at, revoked_at)        │
│  Conversation(project FK, 无 user FK) ← 改造点②                         │
│  RemoteTool(name, source, input_schema, config, is_active)             │
│  ProjectMembership(user, project, role)                                │
└────────────┬─────────────────────────────────────────────────────────┘
             │ WS TASK_ASSIGN(payload.remote_tools) + env_ metadata 透传
             ▼
┌──────────────────────┐   buildContainerEnv()    ┌──────────────────────┐
│ Go Runner            │ ───────────────────────► │ Task 容器 task/       │
│ dispatcher → ws      │  FRIDAY_REMOTE_TOOLS=...  │ ClaudeRunner          │
│ executor.go          │  env_* 前缀 → 容器 env    │  ⚠ 不读 remote_tools  │
│                      │                          │  ⚠ 无 mcp_servers     │
└──────────────────────┘                          └──────────────────────┘
       ▲  HTTP 回调 /api/containers/callback/ (Bearer callback_token)
       └────────────────────────────────────────────────── 改造点③ 反向新增 execute 端点
```

### Component Responsibilities（受影响组件）

| Component | 现责任 | v0.2.0 后责任 | 文件 |
|-----------|--------|---------------|------|
| AccessTokenAuthentication | 有效 token → `(None, token)`，全权限 | 有效 token → `(token.created_by, token)`，落地用户身份 | `server/access_tokens/authentication.py` |
| McpToolView | `AllowAny`，token-only | `IsAuthenticated` + 既有权限链 | `server/mcp_tools/views.py:141` |
| Conversation | 仅 project FK | 增 `created_by` FK + 用户隔离 | `server/chat/models.py:21` |
| ConversationService | 不按用户过滤 | list/detail/delete/create 按 user 过滤 | `server/chat/conversation_service.py` |
| tools app | 无对外 HTTP | NEW：按 name 执行 RemoteTool 的认证端点 | `server/tools/`（NEW urls/views） |
| dispatcher | 注入 active remote_tools | 额外注入用户 PAT（env_ 前缀） | `server/runners/dispatcher.py` |
| task ClaudeRunner | 无 mcp_servers | 读 remote_tools + 用 PAT 装配 SDK MCP proxy | `task/core/executor.py`, `task/core/config.py` |

---

## Architectural Patterns（接入既有惯例，不发明新模式）

### Pattern 1：同步认证类 + 返回 user，配合 select_related 规避 async ORM 陷阱
**What:** DRF `BaseAuthentication.authenticate()` 是**同步**方法；adrf 在 async view 中自动 `sync_to_async` 包装。改为返回 `(user, token)` 后，下游 async view（mcp_tools / chat 均为 `adrf.views.APIView`）会访问 `request.user.<attr>`。
**When:** 改造点① 必须遵守。
**Trade-offs:** 若 authenticate 里只 `AccessToken.objects.get(token_hash=...)`，则 `token.created_by` 是惰性 FK，**在 async view 上下文首次访问会抛 `SynchronousOnlyOperation`**（ARCHITECTURE 反模式「ORM access from raw async without bridge」）。
**Example（MOD `authentication.py:59,74`）:**
```python
# 当前
token = AccessToken.objects.get(token_hash=fingerprint)
...
return (None, token)
# 改造：认证仍是同步上下文，可直接 select_related 预取 user，
# 让 async view 访问 request.user.id / is_superuser 不再触发同步 ORM
token = AccessToken.objects.select_related("created_by").get(token_hash=fingerprint)
...
return (token.created_by, token)
```
> `interactions.entry` 第 39 行 re-export 同一个类 → 改一处，所有外部入口（mcp_tools 经此 re-export 引用）同步生效。`begin_interaction_run` 读的是 `request.auth.token_hash`（第 69 行），不受影响。

### Pattern 2：权限收紧走既有 PermissionService，而非新建权限体系
**What:** 用户身份就位后，复用 `IsAuthenticated` + `PermissionService.has_project_access(user, project, min_role)`（superuser 自动短路放行，`services.py:52`）。
**When:** 改造点①②③ 的授权判定。
**Trade-offs:** chat 既有端点已是该模式（`ConversationMessagesDeleteView` / `ConversationPreflightView` / `RoutingTraceManualOverrideView` 都 `sync_to_async(PermissionService.has_project_access)`）——保持一致即可，无学习成本。
**Example（既有惯例，照抄）:**
```python
if getattr(user, "is_authenticated", False) and not getattr(user, "is_superuser", False):
    ok = await sync_to_async(PermissionService.has_project_access)(user, conv.project, "member")
    if not ok:
        return Response({"detail": "无权访问"}, status=403)
```

### Pattern 3：跨进程密钥注入复用 `env_` 前缀 metadata 透传（关键复用点）
**What:** Server 把 `env_FRIDAY_TASK_*` 键塞进 `DispatchTask.metadata`；runner `buildContainerEnv` 第 122-131 行**已通用地**把任何 `env_` 前缀字段剥前缀后注入容器环境变量。
**When:** 改造点③「把用户 PAT 安全传到容器」。
**Trade-offs:** **runner 侧零改动**即可传任意新密钥 —— 这是注入用户 PAT 的最干净通道；已被 `CLAUDE_API_KEY` / `GIT_ACCESS_TOKEN` 验证（`chat/coding_session_service.py:158,176`）。
**Example（既有惯例）:**
```python
env_metadata["env_FRIDAY_TASK_CLAUDE_API_KEY"] = api_key   # 既有
env_metadata["env_FRIDAY_TASK_USER_TOKEN"] = minted_plaintext_pat  # NEW：同机制
```

### Pattern 4：claude-agent-sdk 进程内 MCP proxy（task 侧接通）
**What:** 用 `create_sdk_mcp_server` + `@tool` 把每个 RemoteTool 包成进程内 SDK MCP server，工具体 HTTP 回调 Friday Server 的 RemoteTool execute 端点（携 `Authorization: Bearer <user PAT>`），再传 `mcp_servers=` 给 `ClaudeAgentOptions`。
**When:** 改造点③ task 侧。
**Trade-offs:** 执行始终落在 server（用户身份 + interactions 审计 + 既有 `execute_tool` 派发 builtin/mcp/skill 三源），容器只做代理 → 不在容器内塞 MCP 凭证，安全面最小；代价是每次 tool call 一跳 HTTP（容器→host.docker.internal→server，`executor.go:69` 已配 ExtraHosts）。
**Example（MOD `task/core/executor.py` `_execute_claude` 的 options 装配）:**
```python
from claude_agent_sdk import create_sdk_mcp_server, tool
def _build_remote_tool_servers(cfg):
    tools = json.loads(cfg.remote_tools or "[]")
    fns = []
    for spec in tools:
        @tool(spec["name"], spec["description"], spec["input_schema"])
        async def _call(args, _name=spec["name"]):
            async with httpx.AsyncClient() as c:
                r = await c.post(f"{cfg.friday_api_url}/api/tools/execute/",
                    json={"name": _name, "arguments": args},
                    headers={"Authorization": f"Bearer {cfg.user_token}"})
            return {"content": [{"type": "text", "text": r.text}]}
        fns.append(_call)
    return create_sdk_mcp_server("friday-remote-tools", tools=fns)
# options = ClaudeAgentOptions(..., mcp_servers={"friday": _build_remote_tool_servers(cfg)})
```

---

## Data Flow

### Flow A — Token 即用户身份（改造点①）
```
请求 Authorization: Bearer friday_pat_xxx
  → AccessTokenAuthentication.authenticate()  [同步]
      AccessToken.objects.select_related("created_by").get(token_hash=sha256)
      is_valid? → (token.created_by, token)            # request.user=owner, request.auth=token
  → McpToolView  perm=[IsAuthenticated]  ← 收紧（原 AllowAny）
  → 既有 PermissionService 权限链按 owner 生效
```
契约：`begin_interaction_run`（审计）仍用 `request.auth`；denial 路径不变。

### Flow B — 对话用户隔离（改造点②）
```
GET /api/chat/conversations/
  → ConversationListView.get(request)
      ConversationService.list_conversations(user=request.user)
        superuser → 全部
        else → filter(Q(created_by=user) | Q(project__memberships__user=user)).distinct()
POST 创建 → create_conversation(..., created_by=request.user)
GET/DELETE/stream/runtime/preflight/{id} → 取 conv → ownership 校验（created_by==user 或 has_project_access 或 superuser）
```
迁移：`Conversation.created_by` `null=True` 新列 + data migration 回填（见下「迁移与回填」）。

### Flow C — 用户令牌注入工具链（改造点③，三端）
```
[server 派发]  dispatcher / mcp_tools.execution_service.dispatch_execution
   1) 为 owner mint 短时 AccessToken（明文仅此刻可得）
   2) metadata["env_FRIDAY_TASK_USER_TOKEN"] = 明文
      metadata["env_FRIDAY_TASK_FRIDAY_API_URL"] = server 根
      payload["remote_tools"] = RemoteToolRegistry.aget_tools_payload()   # 既有
   3) DispatchTask → TASK_ASSIGN（WS）
[runner]  buildContainerEnv()  ← env_ 前缀自动透传（零/极小改动）
   FRIDAY_TASK_USER_TOKEN / FRIDAY_TASK_FRIDAY_API_URL / (FRIDAY_TASK_REMOTE_TOOLS)
[task]   TaskConfig 读取 → ClaudeRunner 装配 create_sdk_mcp_server(@tool proxy)
   agent 调工具 → HTTP POST {server}/api/tools/execute/  Bearer=USER_TOKEN
[server 反向] tools.views.ExecuteRemoteToolView  auth=[AccessToken] perm=[IsAuthenticated]
   → tools.executor.execute_tool(name, arguments)  # builtin/mcp/skill 三源既有派发
   → 任务结束后 server revoke 短时 token
```

### Key Data Flows
1. **身份落地：** `(None,token)`→`(owner,token)` 是全链路前置；mcp_tools 收紧后由 `IsAuthenticated` 兜底。
2. **隔离过滤：** 统一收敛到 `ConversationService` 一处过滤 + 各 view 一处 ownership 校验，避免散落。
3. **令牌闭环：** mint→inject(env_)→proxy 回调→revoke；明文永不落盘（沿用 AccessToken 「仅创建时返回明文」契约）。

---

## Integration Points

### 改造点①：Token 认证 = owner 身份；mcp_tools 收紧
| 项 | 内容 |
|----|------|
| MOD | `server/access_tokens/authentication.py:59` 加 `select_related("created_by")`；`:74` 返回 `(token.created_by, token)` |
| MOD | `server/mcp_tools/views.py:145` `permission_classes = [AllowAny]` → `[IsAuthenticated]`（`handle_exception` 已映射 401，第 148-155 行） |
| 不变 | `interactions/entry.py` re-export 自动生效；`begin_interaction_run` 用 `request.auth`，`_begin` 判 `request.auth is None`（views.py:158）仍成立 |
| 约束 | authenticate 同步、`_touch_last_used` 同步 save 不变；**必须** select_related 预取 user 防 async `SynchronousOnlyOperation` |
| 回归风险 | chat 端点目前**不挂** AccessTokenAuthentication → PAT 当前无法认证 chat。要让「PAT=身份」覆盖 chat，需把 `AccessTokenAuthentication` **加入** chat view 的 `authentication_classes`（与 OptionalJWT/ChatKey 并列）——属②的前置 |

### 改造点②：对话用户隔离
| 项 | 内容 |
|----|------|
| MOD | `server/chat/models.py` `Conversation` 增 `created_by = ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=SET_NULL, related_name="conversations")` |
| NEW | migration：schema（加列+index）+ data（回填，见下） |
| MOD | `conversation_service.py:1310 list_conversations(user)`、`:697 create_conversation(..., created_by)`、`get_conversation_with_messages` 可选带 user 校验 |
| MOD | `chat/views.py`：`ConversationListView`(get 传 user / post 设 created_by)、`ConversationDetailView`(get/delete **当前无任何校验** → 加 ownership)、`ChatStreamView.post`(:1138 加校验)、`ConversationRuntimeView` |
| 复用 | `ConversationPreflightView`/`MessagesDeleteView`/`ForkView` 已有 project-access 校验，补 `created_by` 维度即可 |
| 决策 | superuser 可见全部（与 `PermissionService` superuser 短路一致）|
| 约束 | 写 FK 用 `created_by_id`；async 读 FK 前 `select_related("project")`；`Anonymous`（ChatAuth 开关关闭）无身份 → 隔离需真实用户，建议对话端点改 `IsAuthenticated` 或对 Anonymous 显式降级（roadmap 决策） |

### 改造点③：RemoteTool execute 端点 + 令牌注入
| 项 | 内容 |
|----|------|
| NEW | `server/tools/views.py` `ExecuteRemoteToolView`：`auth=[AccessTokenAuthentication] perm=[IsAuthenticated]`，body `{name, arguments}` → `await execute_tool(...)`（executor.py 已返回 `{ok,result|error}`） |
| NEW | `server/tools/urls.py` + `friday/urls.py` 注册 `path("tools/", include("tools.urls"))`（紧邻 `mcp/`、`agents/`，第 54-56 行） |
| NEW | 用户「绑定令牌给 skill/mcp」的模型/接口：最简可按 owner 在 dispatch 时即时 mint 短时 token（无需新表）；若要持久绑定则 NEW 表（user↔token↔tool 作用域） |
| MOD | 派发处注入：`runners/dispatcher.py` 或 `mcp_tools/execution_service.py:196 extra_metadata` 加 `env_FRIDAY_TASK_USER_TOKEN` / `env_FRIDAY_TASK_FRIDAY_API_URL` |
| MOD(小) | `runner/internal/docker/executor.go:104`：当前写 `FRIDAY_REMOTE_TOOLS`（无 `FRIDAY_TASK_` 前缀，pydantic 读不到）→ 改写 `FRIDAY_TASK_REMOTE_TOOLS` 或 task 端显式映射 env |
| MOD | `task/core/config.py`：增 `remote_tools: str`、`user_token: str`、`friday_api_url: str`（FRIDAY_TASK_ 前缀） |
| MOD | `task/core/executor.py` `_execute_claude`：装配 `create_sdk_mcp_server` + `@tool` proxy，`ClaudeAgentOptions(mcp_servers=...)`（第 280 行 options 处） |

### 跨进程契约同步点（必须三端同改）
| 契约 | 生产者 | 消费者 | 状态 |
|------|--------|--------|------|
| TASK_ASSIGN `payload.remote_tools` | `dispatcher.py:77` | `ws/client.go:318` → `executor.go:91` | 已存在 |
| `env_*` metadata 透传 | server metadata | `executor.go:122-131` | 已存在（复用） |
| 容器 env `FRIDAY_TASK_REMOTE_TOOLS` | `executor.go`(改名) | `task/core/config.py`(NEW) | **需新增/对齐** |
| 容器 env `FRIDAY_TASK_USER_TOKEN` / `..._FRIDAY_API_URL` | server env_ 注入 | `task/core/config.py`(NEW) | **NEW** |
| `POST /api/tools/execute/` `{name,arguments}`→`{ok,...}` | task `@tool` proxy | `tools/views.py`(NEW) | **NEW** |

---

## 迁移与回填（Conversation.created_by）

- **schema migration**：`AddField(created_by, null=True)` + `AddIndex(["created_by","-updated_at"])`（沿用既有 index 习惯）。
- **data migration（回填策略，需 roadmap 拍板）**：
  - Project **无 owner 字段**（已核对 `projects/models.py`）→ 无法按项目所有者回填。
  - 推荐：回填 `created_by = 最早的 superuser`（setup 向导建的管理员），确定性强；其余保持 `null`。
  - 备选：全部留 `null`，运行期视 `null` 为「legacy/共享」，仅 superuser 可见 → 升级零风险但普通用户看不到历史会话。
- **兼容性约束（PROJECT）**：`null=True` 确保已有部署升级不报错、不回退；`on_delete=SET_NULL` 避免删用户级联删会话。

---

## Build Order（含依赖）

```
Phase A  Token=owner 身份（地基）
  A1 MOD authentication.py 返回 (user,token) + select_related      ← 无依赖
  A2 MOD mcp_tools McpToolView AllowAny→IsAuthenticated           ← 依赖 A1
  （A 完成后：外部 PAT 调用即带用户身份，权限链生效）

Phase B  对话用户隔离（依赖 A：需可靠用户身份）
  B0 MOD chat views 挂 AccessTokenAuthentication（让 PAT 能认证 chat）← 依赖 A1
  B1 MOD models 加 created_by + NEW migration(schema) + 回填        ← 无强依赖，可与 A 并行
  B2 MOD ConversationService 过滤 + create 设 created_by           ← 依赖 B1
  B3 MOD chat/views 各入口 ownership 校验（含 detail/delete/stream）← 依赖 B0,B2

Phase C  RemoteTool 反向执行端点（依赖 A：端点靠 PAT 认证用户）
  C1 NEW tools/views ExecuteRemoteToolView + urls + 注册          ← 依赖 A1

Phase D  令牌注入（依赖 C：有可调用端点才有意义）
  D1 NEW 短时 token mint + revoke（owner）                         ← 依赖 A（AccessToken 既有）
  D2 MOD dispatch 处注入 env_FRIDAY_TASK_USER_TOKEN/API_URL        ← 依赖 D1
  D3 MOD(小) runner executor.go remote_tools env 改名/对齐          ← 与 E1 配对

Phase E  task 侧接通（依赖 C 端点 + D 令牌）
  E1 MOD task/core/config.py 读 remote_tools/user_token/api_url    ← 依赖 D3
  E2 MOD task/core/executor.py 装配 mcp_servers proxy             ← 依赖 C1,D2,E1
```

**关键路径：** A1 → (A2 / B0 / C1) → D → E。A1 是单点地基；C1+D+E 是「工具打通」主链；B 可在 A1 后与 C/D/E 并行推进。

---

## Anti-Patterns（本次须规避）

### AP1：authenticate 返回 user 但不预取 created_by
**做错：** `AccessToken.objects.get(...)` 后直接 `return (token.created_by, token)`。
**后果：** async mcp/chat view 首次访问 `request.user.id` 抛 `SynchronousOnlyOperation`。
**改为：** `select_related("created_by")`（authenticate 同步上下文中预取）。

### AP2：在每个 view 各写一套对话过滤逻辑
**做错：** list/detail/stream 各自拼 `filter(created_by=...)`。
**后果：** 规则漂移、superuser/membership 分支不一致、易漏 detail/delete 这类「当前零校验」入口。
**改为：** 过滤收敛到 `ConversationService`，ownership 校验复用 `PermissionService.has_project_access` 统一断言。

### AP3：把用户 PAT 明文存库再注入
**做错：** 为了能注入容器而新存一份明文/可逆 token。
**后果：** 违反「明文仅展示一次、仅存 hash」契约，扩大泄露面。
**改为：** dispatch 时即时 mint 短时 AccessToken（明文仅此刻可得）→ env_ 注入 → 任务结束 revoke。

### AP4：在容器内直接持有 MCP/Git 业务凭证执行工具
**做错：** 把各 RemoteTool 的真实凭证下发到容器本地执行。
**后果：** 凭证扩散到隔离度最低处，且绕过 server 审计（interactions ledger）。
**改为：** 容器只持短时 PAT，经 `/api/tools/execute/` 回调，执行与凭证解析留在 server（`execute_tool` 既有三源派发）。

---

## Integration Points 汇总（速查）

| Boundary | 通信 | NEW/MOD | 说明 |
|----------|------|---------|------|
| 外部 ↔ mcp_tools | HTTP Bearer PAT | MOD | AllowAny→IsAuthenticated；身份=owner |
| 外部/web ↔ chat | HTTP（PAT/JWT/ChatKey） | MOD | 加 AccessTokenAuth + 用户隔离 |
| task ↔ server tools | HTTP Bearer 短时 PAT | NEW | `/api/tools/execute/` |
| server ↔ runner | WS TASK_ASSIGN + env_ | MOD(小) | remote_tools env 名对齐 + token 注入 |
| runner ↔ task | 容器 env | MOD | 新增 USER_TOKEN/API_URL/REMOTE_TOOLS |
| task agent ↔ SDK | 进程内 MCP | MOD | `create_sdk_mcp_server` + `mcp_servers=` |

---

## Sources

- `server/access_tokens/{authentication,models}.py`、`server/interactions/entry.py`（认证/审计契约）— HIGH
- `server/mcp_tools/views.py`、`server/chat/{views,models,permissions,authentication,conversation_service}.py`、`server/permissions/{models,services}.py`（权限/隔离）— HIGH
- `server/tools/{executor,registry,models,views}.py` + `server/friday/urls.py`（确认 tools 无对外端点）— HIGH
- `server/runners/dispatcher.py`、`server/chat/coding_session_service.py`、`server/mcp_tools/execution_service.py`（env_ 注入惯例）— HIGH
- `runner/internal/docker/executor.go`、`runner/internal/ws/client.go`、`task/core/{config,executor,runner}.py`、`task/integrations/callback.py`（跨进程链路 / task 未读 remote_tools / 无 mcp_servers）— HIGH
- `.planning/codebase/ARCHITECTURE.md`、`.planning/PROJECT.md`（架构约束 / 里程碑目标）— HIGH
- claude-agent-sdk 0.1.58 `create_sdk_mcp_server` / `@tool` / `mcp_servers`（milestone 上下文 + SDK 知识）— MEDIUM

---
*Architecture research for: Friday AI v0.2.0 用户身份令牌与 Agent 工具打通（brownfield 集成）*
*Researched: 2026-06-09*
