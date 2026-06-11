# Stack Research

**Domain:** Brownfield 增量 — 用户身份令牌（PAT-as-identity）+ 会话用户隔离 + MCP/RemoteTool 用户令牌注入到 claude-agent-sdk 容器（Django 5.1 / Python 3.14 异步栈）
**Researched:** 2026-06-09
**Confidence:** HIGH（核心结论是"复用现有栈、几乎零新增依赖"；claude-agent-sdk MCP 配置 API 已用 Context7 官方文档核对）

---

## TL;DR（给需求/Roadmap 的硬结论）

- **三项新能力全部可在现有依赖内实现，无需新增任何后端 PyPI 包。** 关键词：DRF `BaseAuthentication`、`secrets`/`hashlib`（已用）、`cryptography` Fernet（已用，仅第三方外部 secret 才需要）、`asgiref.sync_to_async`（已用）。
- **令牌即身份**：把 `AccessTokenAuthentication.authenticate()` 的返回从 `(None, token)` 改为 `(token.created_by, token)`，并在查询时 `select_related("created_by")`。**这是唯一核心改动**，权限随之由 DRF 既有 `IsAuthenticated` + 项目 `PermissionService` 自然生效。
- **会话隔离**：给 `chat.Conversation` 增 `created_by` FK（迁移），list/detail/stream 按 `request.user` 过滤；复用既有 `PermissionService.has_project_access` 模式（views.py 已大量使用）。**不引入新授权库。**
- **MCP/工具注入容器**：claude-agent-sdk `0.1.58`（已装）**自带** `mcp_servers` 配置 + `@tool` / `create_sdk_mcp_server`。在 `task/core/executor.py` 的 `ClaudeAgentOptions` 上挂一个**进程内 SDK MCP server**，把 `remote_tools` 包装成工具，handler 用容器内已装的 `httpx` 回调 Friday Server REST（携带用户 PAT 作 `Authorization: Bearer`）。**task/ 不新增依赖。**
- **不要新增**：`PyJWT`/第三方 token 库、`django-guardian`/`django-rest-framework-api-key`、容器内重装 `mcp`/`anthropic`、把 claude-agent-sdk 升到 0.2.x（见 "What NOT to Use"）。

---

## Recommended Stack

### Core Technologies（全部为"复用既有"）

| Technology | Version | Purpose | Why Recommended |
|------------|---------|---------|-----------------|
| `djangorestframework` `BaseAuthentication` | 3.15+（已装） | 令牌即身份：`authenticate()` 返回 `(user, auth)` | DRF 的契约就是返回 `(request.user, request.auth)`；现状返回 `(None, token)` 是刻意"全权限"。改成返回 owner 后，`IsAuthenticated`、`request.user.has_perm`、`PermissionService` 全部自动接管，**无需任何新机制**。 |
| `secrets` + `hashlib` (sha256) | stdlib（已用） | PAT 生成/校验 | `generate_pat()` 已用 `secrets.token_urlsafe(32)`；`runners.models.hash_token` 已是 sha256。令牌增强（名称/备注/有效期/前后缀展示）纯属模型字段，零新依赖。 |
| `asgiref.sync_to_async` | 随 Django（已用） | 认证类同步 ORM ↔ adrf 异步 view 桥接 | `AccessTokenAuthentication.authenticate` 是同步方法（DRF 要求），改读 `created_by` 必须用 `select_related` 避免 async 上下文的 `SynchronousOnlyOperation`。这是**现有约束**，不是新技术。 |
| `claude-agent-sdk` | **0.1.58（已装，保持不变）** | 容器内把 `remote_tools` 暴露给 agent | 已用 `ClaudeAgentOptions` / `query`；同包**已含** `mcp_servers` 参数 + `tool` / `create_sdk_mcp_server`（官方 README + API 文档确认，见 Sources）。挂进程内 SDK MCP server 即可，**无新依赖**。 |
| `httpx` | 0.27+（task 已装） | 容器内工具 handler 回调 Server 执行真实工具 | `task/integrations/callback.py` 已用 httpx 做回调，复用同一客户端把 `Authorization: Bearer <用户PAT>` 注入即可。 |
| `cryptography` Fernet | 42.0+（已装） | **仅**第三方/外部 MCP secret 落库时加密 | 复用 `common.encryption` / `ProviderCredential` 既有加密路径。Friday 自签 PAT **不落明文**（见架构决策），故大多数场景**用不到** Fernet。 |

### Supporting Libraries（按需，均已在栈内）

| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| `permissions.services.PermissionService` | 内部模块（已存在） | 项目级 RBAC（viewer/member/owner） | 会话隔离的越权判定。`chat/views.py` 的 cleanup/fork/preflight 已是范例：非 superuser → `has_project_access(user, project, role)` → 否则 403/404。**直接照抄到 list/detail/stream。** |
| `mcp`（Python MCP SDK） | 随 server 已装 / claude-agent-sdk 内置 | 外部 stdio MCP server 调用 | server 侧 `tools/sources/mcp_source.py` 已用 `from mcp import ClientSession, stdio_client`。容器内**不需要**单独装：`create_sdk_mcp_server` 由 claude-agent-sdk 提供。 |
| `structlog` | 已装 | 认证/注入审计事件 | 复用 `interactions.ledger` 既有脱敏入口（`redact_for_ledger`），token 只记 fingerprint。 |

### Development Tools

| Tool | Purpose | Notes |
|------|---------|-------|
| `pytest` + `pytest-django` + `pytest-asyncio` | 认证/隔离回归 | 已有 ~509 后端测试；新增越权用例可复用 `factory-boy` + `respx`（mock httpx 回调）。 |
| `respx` | mock task→server 回调 | 验证 PAT 头注入与 401/403 分支，不打真实网络（配合 `pytest-socket`）。 |
| `mypy` (django/drf stubs) | 认证返回类型 | `authenticate()` 返回签名由 `tuple[None, AccessToken]` 改为 `tuple[User, AccessToken]`，同步更新类型注解。 |

## Installation

```bash
# 后端（server/）: 无新增依赖。仅 Django 迁移：
#   - AccessToken 增 name 备注/前后缀字段（多为已存在，按缺口补）
#   - chat.Conversation 增 created_by FK（+ 数据回填/允许 null）
uv run python manage.py makemigrations access_tokens chat
uv run python manage.py migrate

# task/: 无新增依赖（claude-agent-sdk==0.1.58 已含 mcp_servers/@tool/create_sdk_mcp_server）
# runner/: 无新增 Go 依赖（已有 buildContainerEnv 写 FRIDAY_REMOTE_TOOLS，仅再加一个 user-token env）
```

> 唯一可能"看起来像新增"的是 chat 的 `created_by` 迁移与 AccessToken 的元数据字段——这是 schema 演进，不是依赖增加。

## Alternatives Considered

| Recommended | Alternative | When to Use Alternative |
|-------------|-------------|-------------------------|
| 复用 DRF `BaseAuthentication`（返回 owner） | `djangorestframework-api-key` | 永远不要——它另起一套 key 模型/权限，与既有 `AccessToken` + sha256 + 软吊销契约冲突，纯重复。 |
| 进程内 SDK MCP server（`create_sdk_mcp_server`）回调 Server 执行 | 在容器内直接配 `mcp_servers={"x":{"type":"http",...}}` 指向 Friday REST | 仅当 Friday 真的暴露 **MCP Streamable-HTTP 传输**端点时才行。现状 `/api/mcp/tools/*` 是普通 DRF REST，**不是** MCP 传输协议，SDK 的 `http` 类型连不上。故选进程内 server 包一层 httpx 回调。 |
| 工具执行留在 Server 侧 | 把外部 MCP server 的 `command/args/secret` 下发到容器、容器内直接 stdio 起子进程 | 仅当某工具必须在仓库工作区本地执行时。默认不推荐：会把白名单（`MCP_ALLOWED_COMMANDS`）与第三方 secret 泄进容器，扩大攻击面。 |
| Friday PAT = dispatch 时即时铸造、明文仅进 env | 把用户长期 PAT 明文存库再注入 | 永不——违反 "明文绝不落盘" 契约。需长期绑定时存 sha256 + 在 dispatch 时另铸短时令牌或要求用户配置。 |
| `cryptography` Fernet 存第三方 secret | base64/明文存外部 token | 永不——外部 MCP 的第三方 API key 必须走既有 Fernet 加密路径。 |

## What NOT to Use（明确"不要新增"——本里程碑重点）

| Avoid | Why | Use Instead |
|-------|-----|-------------|
| `PyJWT` / 任何新 JWT 库 | PAT 是不透明随机串 + sha256 比对，不是 JWT；项目 JWT 已由 `djangorestframework-simplejwt` 管 cookie 会话 | 现有 `AccessToken` 模型 + `secrets`/`hashlib` |
| `djangorestframework-api-key` | 与既有 AccessToken 契约（前缀/前后缀/软吊销/last_used 节流/ledger 审计）正面冲突，且不给"令牌即 owner 身份"语义 | 改 `AccessTokenAuthentication` 返回 `(created_by, token)` |
| `django-guardian` / 新对象级权限库 | 会话隔离用项目 RBAC 即可；引第二套权限系统会与 `permissions.PermissionService` 双源失真 | 复用 `PermissionService.has_project_access` + `Conversation.created_by` 过滤 |
| 在 task/ 容器内新增 `mcp` / `anthropic` / 任何 SDK 包 | `create_sdk_mcp_server` / `@tool` / `mcp_servers` 全由已装的 `claude-agent-sdk==0.1.58` 提供 | 直接 `from claude_agent_sdk import tool, create_sdk_mcp_server` |
| 升级 `claude-agent-sdk` 到 0.2.x（最新 0.2.94） | 跨 minor 有 breaking（`ClaudeCodeOptions`→`ClaudeAgentOptions` 等已迁移，但 0.1→0.2 仍属次版本跃迁，且 server `pyproject` 显式钉 `<0.2`）；本里程碑用到的 MCP/工具 API 在 0.1.58 已具备 | 保持 0.1.58；MCP 接通验证通过后再单独立项评估升级 |
| 在认证类里写 `async def authenticate` 或裸 `await` ORM | DRF `BaseAuthentication.authenticate` 是同步契约；adrf 会 `sync_to_async` 包装，async 上下文裸访问 FK 触发 `SynchronousOnlyOperation` | 同步方法 + `AccessToken.objects.select_related("created_by").get(...)` |
| 自建对话级 ACL 表 | 过度设计；会话归属 = `created_by` + 项目权限两层足够 | `created_by` FK + 既有项目 RBAC |

## Stack Patterns by Variant

**令牌即身份（最小改动路径）：**
- `AccessTokenAuthentication.authenticate()`：`AccessToken.objects.select_related("created_by").get(token_hash=fp)` → `return (token.created_by, token)`。
- 因为它被 `interactions.entry` re-export 给 `mcp_tools` 等所有外部入口，**一处改动全局生效**；`mcp_tools/views.py` 的 `permission_classes=[AllowAny]` 应收紧为 `[IsAuthenticated]`（现在 `request.user` 已是真实 owner）。
- 注意：`begin_interaction_run` 仍读 `request.auth.token_hash`，向后兼容不受影响。

**会话用户隔离：**
- `Conversation` 加 `created_by = FK(User, null=True)`（迁移允许 null 以兼容历史数据，按需回填/或视 null 为"仅 superuser 可见"）。
- `ConversationListView.get`：`ConversationService.list_conversations(user=request.user)` 内按 `created_by=user`（或 `PermissionService` 可见项目）过滤。
- detail/stream/delete：在现有 `Conversation.objects.aget(...)` 后补 ownership 校验，复用 `chat/views.py` 已有的 `has_project_access` 范式（preflight/cleanup 已示范，含 async-safe `sync_to_async`）。

**MCP/RemoteTool 注入容器（claude-agent-sdk 落地）：**
- runner `buildContainerEnv` 已写 `FRIDAY_REMOTE_TOOLS`；再加 `FRIDAY_TASK_USER_ACCESS_TOKEN`（dispatcher 从触发用户解析/铸造，payload 下发）。
- `TaskConfig` 增 `remote_tools`（解析 `FRIDAY_REMOTE_TOOLS` JSON）+ `user_access_token` 字段。
- `task/core/executor.py`：用 `@tool(name, desc, input_schema)` 为每个 remote_tool 生成 handler（handler = httpx POST → Friday Server 执行端点，头带用户 PAT），`create_sdk_mcp_server(name="friday", tools=[...])`，挂到 `ClaudeAgentOptions(mcp_servers={"friday": server}, allowed_tools=["mcp__friday__<tool>", ...])`。
- 工具真实执行仍在 Server 侧 `tools.executor.execute_tool`（白名单/skill 编排/secret 集中），认证改造后以用户身份运行。
  - ⚠️ 集成缺口（flag 给 plan）：当前 `server/tools/` **没有** `urls.py`/通用 execute 端点；`tools.executor.execute_tool` 仅内部可达。本里程碑需新增一个"按 name 执行 RemoteTool"的认证端点（`AccessTokenAuthentication` + `IsAuthenticated`），或复用/扩展 `/api/mcp/tools/*`。这是必做的接线项，不是依赖项。

## Version Compatibility

| Package A | Compatible With | Notes |
|-----------|-----------------|-------|
| `claude-agent-sdk==0.1.58` | Python 3.14 | 官方声明 `>=3.10`（Augment 指南列 3.10–3.13；项目已在 3.14 跑通现状）。0.1.58 已是 `ClaudeAgentOptions` 命名（与现有代码一致）。 |
| `claude-agent-sdk` `mcp_servers` | `allowed_tools` 形如 `mcp__<server>__<tool>` | 进程内 SDK server + 外部 stdio/sse/http 可在同一 `mcp_servers` dict 混用；工具名前缀规则官方确认。 |
| DRF `BaseAuthentication` 返回 `(user, auth)` | `IsAuthenticated` / `PermissionService` | 改返回 owner 后，`request.user.is_authenticated=True`，既有权限链全部生效；无需改 DRF 配置。 |
| `adrf` async view | 同步 `authenticate()` + `select_related` | adrf 自动 `sync_to_async` 包装认证类；只要不在同步认证里触发未预取的惰性 FK 即安全。 |

## Sources

- `/anthropics/claude-agent-sdk-python`（Context7，597 snippets，High）— `ClaudeAgentOptions.mcp_servers`（stdio/sse/http/sdk 四类型）、`@tool` 装饰器签名、`create_sdk_mcp_server(name, version, tools)` 签名、`allowed_tools` 的 `mcp__server__tool` 规则、SDK+外部 server 混用示例 — **HIGH**
- PyPI `claude-agent-sdk`（https://pypi.org/project/claude-agent-sdk/）— 最新 0.2.94（2026-06-06），项目钉 0.1.58 — **HIGH**
- Augment Code 指南（augmentcode.com/guides/claude-agent-sdk-python）— `claude-code-sdk`→`claude-agent-sdk`、`ClaudeCodeOptions`→`ClaudeAgentOptions` 重命名、Python 版本支持 — **MEDIUM**（二手，但与官方一致）
- 代码现状核对（仓库内）：`server/access_tokens/{models,authentication}.py`、`server/interactions/entry.py`（re-export）、`server/mcp_tools/views.py`（`AllowAny`）、`server/chat/{models,views,authentication}.py`（无 user FK、`PermissionService` 范式）、`server/tools/{executor,registry,models,sources/*}.py`、`server/runners/dispatcher.py`、`runner/internal/docker/executor.go`（`FRIDAY_REMOTE_TOOLS`）、`task/core/{executor,config}.py`、`task/pyproject.toml` — **HIGH**

---
*Stack research for: v0.2.0 用户身份令牌与 Agent 工具打通（brownfield）*
*Researched: 2026-06-09*
