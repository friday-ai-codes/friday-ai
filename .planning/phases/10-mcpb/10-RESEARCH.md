# Phase 10: MCP 绑定用户令牌 + RemoteTool 执行端点 - Research

**Researched:** 2026-06-10
**Domain:** Django/adrf 异步 REST（owner 隔离 CRUD + PAT 认证执行端点）+ Vue3/TS 绑定管理 UI
**Confidence:** HIGH（全部基于本仓库实证代码，无外部新依赖）

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions

**绑定模型与 API（MCPB-01 / MCPB-03）**
- 新增 `tools.ToolTokenBinding` 模型：`user FK(accounts.User)`、`access_token FK(access_tokens.AccessToken)`、`remote_tool FK(tools.RemoteTool)`、`created_at`、`updated_at`。
  - `unique_together = (user, remote_tool)`：每个用户对同一工具最多一条绑定；重复绑定即更新所绑令牌。
  - `on_delete=CASCADE`：令牌或工具删除时绑定自动消失。
- 绑定 CRUD API（CookieJWT 认证，按 `user=request.user` 隔离）：list（我的绑定）、create/upsert、delete（解绑）。仅能管理自己的绑定（MCPB-03，复用 access_tokens 的 owner 隔离范式）。
- 可绑定工具范围：`RemoteTool.source ∈ {mcp, skill}`（builtin 不在绑定范围）。需一个「可绑定工具列表」只读 API 供 UI 选择。

**执行身份语义（MCPB-02）**
- 绑定表记录 tool→token 映射，是 Phase 11 容器回调时选用哪把令牌的持久依据。
- 本期执行端点（RTOOL-01）直接以调用方携带的 PAT 认证 → `request.user = owner`（Phase 7 语义），以 owner 身份执行 `execute_tool`，审计指纹为该令牌。

**RemoteTool 执行端点（RTOOL-01）**
- 新增 `POST /api/tools/execute/`，`authentication_classes=[AccessTokenAuthentication]`（PAT）、`permission_classes=[IsAuthenticated]` fail-closed；body `{ "name": <tool_name>, "arguments": {...} }`。
- 处理：PAT 认证 → `begin_interaction_run`（审计，复用 `interactions.entry`）→ 调 `tools.executor.execute_tool(name, arguments)` → 返回 `{ok, result|error}`（沿用 executor 契约）。
- 未认证/无效令牌一律拒（401/403）；工具不存在/超时/执行错误沿用 executor 结构化 error。
- 将 `tools` app 的 urls 挂载进 `server/friday/urls.py`（如 `path("api/tools/", include("tools.urls"))`），当前 `tools` 无 urls/views，需新建。

**前端（MCPB-01 / MCPB-03）**
- 新增「工具令牌绑定」管理界面（沿用 access tokens 设置区/组件范式：列表 + 选择令牌 + 绑定/解绑）。
  - 列出可绑定的 mcp/skill 工具 + 各自当前绑定的令牌（仅显示令牌名称/前后缀，绝不显示明文）。
  - 绑定：从「我的有效令牌」下拉选一把绑给某工具；解绑；二次确认可选。
- 复用 `web/src/api`、`accessTokens` store/组件风格；新增 `api/toolBindings.ts` + 绑定管理组件/页面。

### Claude's Discretion
- 绑定 API/执行端点放 `tools` app（建议）还是新建模块；路由前缀 `/api/tools/` vs `/v1/tools/`；绑定 UI 独立页面还是 access token 设置内的子区。
- 执行端点是否限制「只能执行调用方令牌已绑定的工具」 vs 任意 active 工具（本期推荐：按 PAT 认证可执行任意 active 工具；绑定表用于 Phase 11 选令牌，不在执行端点做绑定强校验）。
- 测试组织。

### Deferred Ideas (OUT OF SCOPE)
- task 容器消费 remote_tools / SDK MCP server 加载 / 令牌直传注入 + 脱敏 / 吊销 graceful（Phase 11）。
- 执行端点对「工具必须已绑定」的强校验、per-tool 细粒度 scope（v2）。
</user_constraints>

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| MCPB-01 | 用户可把自己的某个访问令牌持久绑定给 skill/mcp（绑定入库） | `ToolTokenBinding` 模型 + upsert CRUD（§Standard Stack / §Architecture Patterns / §Code Examples）|
| MCPB-02 | 被绑定的 skill/mcp 调用以该令牌所有者身份与权限执行 | 执行端点 PAT 认证 → `request.user=owner`；绑定表为 Phase 11 注入地基。execute_tool 当前无 user 上下文 → 见 §Open Questions Q4 与 Phase 11 gap |
| MCPB-03 | 用户可查看并解除自己的绑定 | owner 隔离 ViewSet（`get_queryset(user=request.user)`），mirror `AccessTokenViewSet`（§Code Examples）|
| RTOOL-01 | 经令牌认证的 RemoteTool 执行端点（按 name 执行），供容器回调 | `POST /api/tools/execute/` adrf APIView，`[AccessTokenAuthentication]` + `IsAuthenticated`，`begin_interaction_run` 审计 → `execute_tool`（§Code Examples）|
</phase_requirements>

## Summary

本期是纯后端 + 前端的「数据建模 + 端点装配」工作，**零新外部依赖**：全部复用仓库既有的 Django 5.1+/adrf 异步栈、`AccessTokenAuthentication`（Phase 7 PAT→owner）、`interactions.entry.begin_interaction_run`（审计入口）、`tools.executor.execute_tool`（已是 async-safe 协程）、以及 `AccessTokenViewSet` 的 owner 隔离范式。`tools` app 目前 `views.py` 为空、无 `urls.py`，需从零新建 ViewSet/APIView/serializers/urls 并挂进 `friday/urls.py`。

两条主线：(1) **绑定 CRUD**——新增 `ToolTokenBinding` 模型（三 FK + CASCADE + `unique_together(user, remote_tool)`），mirror `AccessTokenViewSet` 的 `get_queryset(user=request.user)` 实现 owner 隔离；序列化器仅吐令牌 `name/token_prefix/token_suffix`（**绝不含明文与 token_hash**）。(2) **执行端点**——adrf `APIView`，`authentication_classes=[AccessTokenAuthentication]` + `IsAuthenticated` fail-closed，`begin_interaction_run(source="tool")` 审计后直接 `await execute_tool(name, arguments)` 返回其 `{ok,...}` 契约。

关键洞察：`execute_tool(name, arguments)` **不接收 user 上下文**，三类源执行器（builtin/mcp/skill）也都不消费 owner 身份。本期「以 owner 身份执行」只在**认证边界**成立（`request.user=owner`、审计指纹为该令牌）；真正把绑定令牌注入容器、让 agent 以用户身份回调，是 Phase 11（RTOOL-02/03）。**本期不需要改 `execute_tool` 签名**，绑定表是 Phase 11 的数据地基。

**Primary recommendation:** 在 `tools` app 内新建 `models.ToolTokenBinding` + `serializers.py` + `views.py`（`ToolTokenBindingViewSet` 走 CookieJWT/owner 隔离 + `RemoteToolExecuteView` 走 PAT/fail-closed）+ `urls.py`，挂载 `path("api/tools/", include("tools.urls"))`；前端在 `profile.vue` Access Tokens 区下方新增「工具令牌绑定」卡片（新 `api/toolBindings.ts` + `stores/toolBindings.ts` + `components/toolBindings/*`），令牌下拉复用 `useAccessTokenStore` 仅取 `is_valid` 元数据。

## Architectural Responsibility Map

| Capability | Primary Tier | Secondary Tier | Rationale |
|------------|-------------|----------------|-----------|
| 绑定关系持久化（user↔token↔tool） | Database / Storage | API | 新 `ToolTokenBinding` 模型 + migration；为 Phase 11 提供查询地基 |
| 绑定 CRUD（list/upsert/delete） | API / Backend | — | owner 隔离 + 不泄漏明文是后端安全责任，不能下放浏览器 |
| 可绑定工具列表（mcp/skill filter） | API / Backend | — | 过滤逻辑（source/is_active）在服务端，UI 只渲染 |
| RemoteTool 执行（按 name） | API / Backend | — | PAT 认证 + 审计 + executor 调度全在服务端；容器是消费方（Phase 11）|
| 令牌身份认证（PAT→owner） | API / Backend | — | 复用 Phase 7 `AccessTokenAuthentication`，认证边界唯一关卡 |
| 绑定管理界面 + 令牌下拉 | Browser / Client | API | 纯展示与交互；明文绝不进浏览器（沿用 access tokens 契约）|

## Standard Stack

### Core（全部已在仓库，无新增安装）
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| `django` | >=5.1（仓库锁 6.0.1 migration 头） | ORM 模型 + migration | 全后端基座 |
| `adrf` | >=0.1.12 | 异步 ViewSet / APIView | 仓库既有异步 DRF 范式（`AccessTokenViewSet`、`McpToolView`）|
| `djangorestframework` | >=3.15 | serializer / permission / router | DRF 标准 |
| `access_tokens.authentication.AccessTokenAuthentication` | 仓库内（Phase 7） | PAT→owner 认证 | RTOOL-01 执行端点认证类（locked decision）|
| `interactions.entry.begin_interaction_run` | 仓库内 | 顶层 InteractionRun 审计 | 执行端点审计（locked decision），自动脱敏 |
| `tools.executor.execute_tool` | 仓库内 | 按 name 执行工具，返回 `{ok,...}` | RTOOL-01 调度目标，已是 async 协程 |
| `vue` / `pinia` / `@tanstack/vue-query`（按现状） | ^3.5 / — | 前端 store + 组件 | 复用 `useAccessTokenStore` 范式 |

### Supporting
| Component | Purpose | When to Use |
|-----------|---------|-------------|
| `adrf.viewsets.ModelViewSet` | 绑定 CRUD | mirror `AccessTokenViewSet`（`acreate` 覆写为 upsert）|
| `adrf.routers.DefaultRouter` | 绑定路由注册 | mirror `access_tokens/urls.py` |
| `adrf.views.APIView` | 执行端点 + 可绑定工具列表端点 | mirror `mcp_tools.views.McpToolView` |
| `rest_framework.permissions.IsAuthenticated` | fail-closed 权限 | 两类端点都用 |
| `common.authentication.CookieJWTAuthentication` | 浏览器 JWT 认证 | 绑定 CRUD（默认认证链已含）|

### Alternatives Considered
| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| `tools` app 内新建 | 独立新 app（如 `tool_bindings`） | 新 app 需注册 INSTALLED_APPS + 额外 migration 链；`tools` app 已有 `RemoteTool`，同 app 更内聚（**推荐 tools app**）|
| `unique_together` | `Meta.constraints=[UniqueConstraint(...)]` | UniqueConstraint 是 Django 新写法且可命名；CONTEXT 锁定 `unique_together` 语义，两者等价，**遵循 CONTEXT 用 `unique_together` 或等价 UniqueConstraint 均可** |
| 执行端点 PAT-only | PAT + CookieJWT 双认证 | CONTEXT 锁定 `[AccessTokenAuthentication]`（容器回调场景），**保持 PAT-only** |

**Installation:** 无需安装任何包（纯仓库内组装）。

## Architecture Patterns

### System Architecture Diagram

```text
浏览器（绑定管理）                          容器内 agent（Phase 11 消费）
      │ CookieJWT                                  │ Bearer friday_pat_…（owner 的 PAT）
      ▼                                            ▼
┌──────────────────────────────┐        ┌──────────────────────────────────┐
│ POST/GET/DELETE               │        │ POST /api/tools/execute/         │
│ /api/tools/bindings/          │        │  authentication=[AccessToken]    │
│  ModelViewSet (CookieJWT)     │        │  permission=[IsAuthenticated]    │
│  get_queryset(user=req.user)  │        │  (fail-closed: 匿名→401)         │
│  ─ list   我的绑定            │        └──────────────┬───────────────────┘
│  ─ upsert update_or_create    │                       │ request.user = owner
│  ─ delete 解绑                │                       ▼
│ GET /api/tools/bindable/      │        ┌──────────────────────────────────┐
│  APIView 只读 mcp/skill+active│        │ begin_interaction_run(source=     │
└──────────────┬───────────────┘        │   "tool")  → InteractionRun 审计  │
               │ 校验 access_token.       │   token_fingerprint=token_hash   │
               │ created_by==req.user     └──────────────┬───────────────────┘
               ▼                                          ▼
┌──────────────────────────────┐        ┌──────────────────────────────────┐
│ ToolTokenBinding (DB)         │◀──读── │ await execute_tool(name, args)   │
│  user FK / access_token FK /  │ Phase  │   ─ aget_tool(name, is_active)   │
│  remote_tool FK  CASCADE      │  11    │   ─ _dispatch → builtin/mcp/skill│
│  unique(user, remote_tool)    │        │   ─ 返回 {ok, result|error}      │
└──────────────────────────────┘        └──────────────┬───────────────────┘
                                                        ▼
                                         Response(result, 200)  // ok 字段判定成功
```

> 注：本期执行端点**不读绑定表**（discretion：不做绑定强校验）。绑定表是 Phase 11「容器侧据 tool→token 映射选令牌注入」的数据地基；图中虚线表示 Phase 11 才接通的读取关系。

### Recommended Project Structure
```
server/tools/
├── models.py            # + ToolTokenBinding（既有 RemoteTool 之后）
├── serializers.py       # 新建：ToolTokenBindingSerializer(read) / *CreateSerializer / RemoteToolExecuteSerializer / BindableToolSerializer
├── views.py             # 新建：ToolTokenBindingViewSet / BindableToolsView / RemoteToolExecuteView
├── urls.py              # 新建：router 注册 bindings/ + path bindable/ + execute/
├── executor.py          # 不改（已 async-safe）
├── registry.py          # 不改
└── migrations/0003_tooltokenbinding.py  # 新建：CreateModel，无数据迁移

web/src/
├── api/toolBindings.ts          # 新建
├── stores/toolBindings.ts       # 新建
├── types/toolBinding.ts         # 新建
├── components/toolBindings/     # 新建：ToolBindingSettings.vue / ToolBindingTable.vue / ToolBindDialog.vue
└── pages/profile.vue            # 改：Access Tokens 卡片下方新增「工具令牌绑定」卡片
```

### Pattern 1: owner 隔离 ModelViewSet（mirror AccessTokenViewSet）
**What:** `get_queryset` 强制 `user=request.user`，天然防越权读/删他人绑定。
**When to use:** 绑定 CRUD（MCPB-03）。
**Example:** 见 §Code Examples「绑定 ViewSet」。

### Pattern 2: PAT-only fail-closed 执行端点（mirror McpToolView）
**What:** `authentication_classes=[AccessTokenAuthentication]` + `permission_classes=[IsAuthenticated]`，匿名/无效令牌在权限层即拒；`handle_exception` 把 `AuthenticationFailed/NotAuthenticated` 收敛为 401。
**When to use:** RTOOL-01。
**Example:** 见 §Code Examples「执行端点」。

### Pattern 3: upsert 通过 update_or_create
**What:** `unique_together(user, remote_tool)` 下，重复 POST 同一 tool 应「更新所绑令牌」而非 IntegrityError。覆写 `acreate` 用 `update_or_create(user=…, remote_tool=…, defaults={"access_token": …})`。
**Why:** CONTEXT 明确「重复绑定即更新所绑令牌」。

### Anti-Patterns to Avoid
- **序列化器吐 token_hash/明文：** 绑定序列化器只能嵌套令牌的 `id/name/token_prefix/token_suffix`，**严禁** `token_hash`、明文（沿用 `AccessTokenSerializer` 的 `read_only_fields` 白名单）。
- **执行端点对 executor 异常码再翻译走样：** 直接透传 `execute_tool` 的 `{ok:false, error:{code,message}}`，不要自造新错误结构。
- **在 async view 里同步 ORM：** 绑定校验若在 async 上下文取 `access_token.created_by`，需 `select_related` 或用 `aget`/`sync_to_async`（adrf ModelViewSet 的 `acreate` 是 async）。
- **执行端点放开认证：** 绝不可用 `AllowAny`（IDENT-03 fail-closed 已确立全站基线）。

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| PAT→owner 认证 | 自写 token 解析 | `AccessTokenAuthentication`（locked） | 已含前缀闸门/吊销/过期/owner 停用/审计/节流 |
| 审计 run | 手拼 InteractionRun | `begin_interaction_run(source="tool")` | 自动脱敏 + 复用 X-Friday-Run-ID 串联 |
| 工具调度 | 自写 dispatch | `execute_tool(name, arguments)` | 已含 timeout/command_not_allowed/execution_error |
| owner 隔离 | 手写权限判断 | `get_queryset(user=request.user)` | mirror `AccessTokenViewSet`，越权天然为空集 |
| 明文脱敏 | 自定义 redact | `interactions.ledger` 内置 redact + serializer 白名单 | 契约已锁 |

**Key insight:** 本期几乎不写"新逻辑"，而是把既有 4 块（PAT 认证 / 审计入口 / executor / owner ViewSet 范式）按 CONTEXT 装配起来；自造任何一块都会偏离已锁安全契约。

## Common Pitfalls

### Pitfall 1: 绑定他人令牌（owner 隔离漏在 access_token 维度）
**What goes wrong:** `get_queryset` 只隔离了「读自己的绑定」，但 create 时若不校验 `access_token.created_by == request.user`，用户可把别人的 token id 绑给工具（即使看不到明文，也是越权引用）。
**How to avoid:** create/upsert serializer 的 `validate_access_token` 里断言 `access_token.created_by_id == request.user.id`，否则 400/404（不泄漏存在性）。同理校验 `remote_tool.source in {mcp, skill}` 且 `is_active`。
**Warning signs:** 测试「用 B 的 token id 绑 A 的工具」未返回 4xx。

### Pitfall 2: 执行端点 401 被降级为 403
**What goes wrong:** 若自定义 `handle_exception` 漏处理或认证类 `authenticate_header` 返回 None，DRF 会把未认证响应降级为 403。
**How to avoid:** `AccessTokenAuthentication.authenticate_header` 已返回 `'Bearer realm="api"'`（站点级 401 已保住）；执行端点 mirror `McpToolView.handle_exception` 把 `AuthenticationFailed/NotAuthenticated`→401。
**Warning signs:** 匿名请求返回 403 而非 401。

### Pitfall 3: upsert 撞 unique_together 抛 500
**What goes wrong:** 直接 `objects.acreate` 第二次绑同一工具 → IntegrityError → 500。
**How to avoid:** 覆写 `acreate` 用 `update_or_create`（Pattern 3）。
**Warning signs:** 重复绑定测试返回 500。

### Pitfall 4: async view 里同步 ORM 触发 SynchronousOnlyOperation
**What goes wrong:** adrf `acreate` 是 async；在其中访问 `access_token.created_by`（未预取）或同步查询会抛错。
**How to avoid:** 用 `await AccessToken.objects.filter(id=…, created_by=request.user).aexists()` 做归属校验，或 `aget` + `select_related`。序列化器同步校验需 `sync_to_async(serializer.is_valid)`（mirror `McpToolView._validate`）。
**Warning signs:** 测试报 `SynchronousOnlyOperation`。

### Pitfall 5: 绑定到已吊销/过期令牌
**What goes wrong:** 后端允许绑任意自己的 token，UI 却该只列 valid 的。若 UI 不过滤，用户会绑到废令牌，Phase 11 注入时才发现失效。
**How to avoid:** UI 下拉用 `useAccessTokenStore` 过滤 `is_valid===true`；后端是否拒绝绑无效令牌为 discretion（推荐后端只校验 ownership，valid 由 UI 把关 + Phase 11 graceful 处理）。
**Warning signs:** 下拉里出现 revoked 令牌。

## Code Examples

### 模型（server/tools/models.py 追加）
```python
class ToolTokenBinding(models.Model):
    """用户令牌 ↔ skill/mcp 工具的持久绑定（Phase 11 容器注入令牌的依据）。"""

    user = models.ForeignKey(
        "accounts.User", on_delete=models.CASCADE, related_name="tool_token_bindings",
    )
    access_token = models.ForeignKey(
        "access_tokens.AccessToken", on_delete=models.CASCADE, related_name="tool_bindings",
    )
    remote_tool = models.ForeignKey(
        RemoteTool, on_delete=models.CASCADE, related_name="token_bindings",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "tool_token_bindings"
        unique_together = (("user", "remote_tool"),)  # 每用户对同一工具最多一条
        ordering = ["-created_at"]
```

### 绑定序列化器（不泄漏明文/hash）
```python
class BoundTokenSerializer(serializers.ModelSerializer):
    class Meta:
        model = AccessToken
        fields = ["id", "name", "token_prefix", "token_suffix", "is_valid"]  # 绝不含 token_hash/明文

class ToolTokenBindingSerializer(serializers.ModelSerializer):
    access_token = BoundTokenSerializer(read_only=True)
    remote_tool_name = serializers.CharField(source="remote_tool.name", read_only=True)
    remote_tool_source = serializers.CharField(source="remote_tool.source", read_only=True)
    class Meta:
        model = ToolTokenBinding
        fields = ["id", "remote_tool", "remote_tool_name", "remote_tool_source",
                  "access_token", "created_at", "updated_at"]
        read_only_fields = fields

class ToolTokenBindingCreateSerializer(serializers.Serializer):
    remote_tool = serializers.PrimaryKeyRelatedField(queryset=RemoteTool.objects.all())
    access_token = serializers.PrimaryKeyRelatedField(queryset=AccessToken.objects.all())
    # validate_* 中校验 remote_tool.source in {mcp,skill} & is_active；access_token.created_by==request.user
```

### 绑定 ViewSet（mirror AccessTokenViewSet，owner 隔离 + upsert）
```python
class ToolTokenBindingViewSet(ModelViewSet):
    serializer_class = ToolTokenBindingSerializer
    permission_classes = [IsAuthenticated]
    http_method_names = ["get", "post", "delete", "head", "options"]

    def get_queryset(self):
        return ToolTokenBinding.objects.filter(user=self.request.user).select_related(
            "access_token", "remote_tool",
        ).order_by("-created_at")

    async def acreate(self, request, *args, **kwargs):
        ser = ToolTokenBindingCreateSerializer(data=request.data, context={"request": request})
        await sync_to_async(ser.is_valid)(raise_exception=True)
        # 归属/范围校验后 upsert：重复绑定即更新所绑令牌
        binding, _ = await ToolTokenBinding.objects.aupdate_or_create(
            user=request.user,
            remote_tool=ser.validated_data["remote_tool"],
            defaults={"access_token": ser.validated_data["access_token"]},
        )
        return Response(ToolTokenBindingSerializer(binding).data, status=status.HTTP_201_CREATED)
```

### 可绑定工具列表端点（只读 mcp/skill + active）
```python
class BindableToolsView(APIView):
    permission_classes = [IsAuthenticated]
    async def get(self, request):
        tools = [
            {"id": t.id, "name": t.name, "description": t.description, "source": t.source}
            async for t in RemoteTool.objects.filter(
                source__in=[RemoteTool.Source.MCP, RemoteTool.Source.SKILL], is_active=True,
            ).order_by("name")
        ]
        return Response(tools)
```

### 执行端点（RTOOL-01，PAT fail-closed + 审计 + executor）
```python
class RemoteToolExecuteView(APIView):
    authentication_classes = [AccessTokenAuthentication]   # PAT only（locked）
    permission_classes = [IsAuthenticated]                 # fail-closed

    def handle_exception(self, exc):  # mirror McpToolView：401 不降级为 403
        if isinstance(exc, (AuthenticationFailed, NotAuthenticated)):
            return Response({"ok": False, "error": {"code": "authentication_failed",
                             "message": str(getattr(exc, "detail", exc))}},
                            status=status.HTTP_401_UNAUTHORIZED)
        return super().handle_exception(exc)

    async def post(self, request):
        ser = RemoteToolExecuteSerializer(data=request.data)  # name: str, arguments: dict=default {}
        await sync_to_async(ser.is_valid)(raise_exception=True)
        await begin_interaction_run(request, source="tool")   # 审计；指纹=token_hash
        result = await execute_tool(ser.validated_data["name"],
                                    ser.validated_data.get("arguments") or {})
        return Response(result, status=status.HTTP_200_OK)  # 沿用 executor {ok,...} 契约
```

> `execute_tool` 是纯 async 协程（`aget_tool` + async `_dispatch`），从 async view 直接 `await` 是 async-safe 的，**无需** `sync_to_async`。

### urls（server/tools/urls.py 新建）+ 挂载
```python
# server/tools/urls.py
router = DefaultRouter()
router.register("bindings", ToolTokenBindingViewSet, basename="tool-binding")
urlpatterns = [
    path("", include(router.urls)),
    path("bindable/", BindableToolsView.as_view(), name="bindable-tools"),
    path("execute/", RemoteToolExecuteView.as_view(), name="tool-execute"),
]
# server/friday/urls.py api_patterns 追加：
path("tools/", include("tools.urls")),   # → /api/tools/bindings/ /api/tools/bindable/ /api/tools/execute/
```

### 前端 API（web/src/api/toolBindings.ts，复用 client.ts 自动 /api 前缀 + 末尾 /）
```typescript
export const toolBindingsApi = {
  list: () => get<ToolBindingDto[]>('/tools/bindings/'),          // 我的绑定
  bindable: () => get<BindableToolDto[]>('/tools/bindable/'),      // 可绑定 mcp/skill
  upsert: (p: { remote_tool: number, access_token: string }) =>
    post<ToolBindingDto>('/tools/bindings/', p),                  // 绑定/换令牌
  unbind: (id: number) => del(`/tools/bindings/${id}/`),          // 解绑
}
```

## Runtime State Inventory

> 本期为新增功能（new model + endpoints），非 rename/refactor/migration。

| Category | Items Found | Action Required |
|----------|-------------|------------------|
| Stored data | None — 新建 `tool_token_bindings` 表，无历史数据迁移 | migration 仅 CreateModel |
| Live service config | None — 不改既有服务配置 | — |
| OS-registered state | None | — |
| Secrets/env vars | None — 复用既有 PAT 体系，无新密钥 | — |
| Build artifacts | None | — |

**结论：** 仅一个 `0003_tooltokenbinding.py` CreateModel migration，无 RunPython 数据回填。

## Validation Architecture

### Test Framework
| Property | Value |
|----------|-------|
| Framework | 后端 `pytest` + `pytest-django` + `pytest-asyncio`（仓库实证）；前端 `vitest` + `@vue/test-utils` |
| Config file | `server/pyproject.toml`（pytest 配置）；`web/vitest.config.*` |
| Quick run command | `cd server && uv run pytest tests/test_tool_token_bindings.py tests/test_remote_tool_execute.py -x` |
| Full suite command | `cd server && uv run pytest`；`cd web && pnpm test` |

### Phase Requirements → Test Map
| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| MCPB-01 | upsert 绑定入库；重复绑定换令牌（update_or_create） | integration | `pytest tests/test_tool_token_bindings.py::test_upsert_rebind_updates_token -x` | ❌ Wave 0 |
| MCPB-01 | 绑非 mcp/skill（builtin）工具被拒 | integration | `pytest tests/test_tool_token_bindings.py::test_bind_builtin_rejected -x` | ❌ Wave 0 |
| MCPB-01 | 绑他人令牌 id 被拒（owner 隔离 access_token 维度） | integration | `pytest tests/test_tool_token_bindings.py::test_bind_others_token_rejected -x` | ❌ Wave 0 |
| MCPB-03 | list 仅返回自己的绑定（跨用户隔离） | integration | `pytest tests/test_tool_token_bindings.py::test_list_owner_isolation -x` | ❌ Wave 0 |
| MCPB-03 | delete 解绑；不能删他人绑定（404） | integration | `pytest tests/test_tool_token_bindings.py::test_unbind_and_cross_user_404 -x` | ❌ Wave 0 |
| MCPB-01/03 | 序列化器不泄漏 token_hash/明文 | unit | `pytest tests/test_tool_token_bindings.py::test_serializer_no_plaintext_no_hash -x` | ❌ Wave 0 |
| MCPB-01 | 可绑定列表只含 mcp/skill 且 is_active | integration | `pytest tests/test_tool_token_bindings.py::test_bindable_filters_mcp_skill_active -x` | ❌ Wave 0 |
| RTOOL-01 | 有效 PAT → 200 + executor `{ok,...}` | integration | `pytest tests/test_remote_tool_execute.py::test_pat_execute_ok -x` | ❌ Wave 0 |
| RTOOL-01 | 匿名请求 → 401（fail-closed） | integration | `pytest tests/test_remote_tool_execute.py::test_anonymous_401 -x` | ❌ Wave 0 |
| RTOOL-01 | 吊销/无效 PAT → 401 | integration | `pytest tests/test_remote_tool_execute.py::test_revoked_pat_401 -x` | ❌ Wave 0 |
| RTOOL-01 | 不存在 tool → `{ok:false, error.code=not_found}` | integration | `pytest tests/test_remote_tool_execute.py::test_unknown_tool_ok_false -x` | ❌ Wave 0 |
| RTOOL-01 | 审计 InteractionRun 创建（fingerprint=token_hash，无明文） | integration | `pytest tests/test_remote_tool_execute.py::test_execute_records_run -x` | ❌ Wave 0 |

### Sampling Rate
- **Per task commit:** `uv run pytest tests/test_tool_token_bindings.py tests/test_remote_tool_execute.py -x`
- **Per wave merge:** 后端 `uv run pytest` + 前端 `pnpm test`
- **Phase gate:** 全套绿 + `pnpm -C web typecheck` 清白，再 `/gsd-verify-work`

### Wave 0 Gaps
- [ ] `server/tests/test_tool_token_bindings.py` — 覆盖 MCPB-01/03（owner 隔离、upsert、bindable filter、不泄漏）
- [ ] `server/tests/test_remote_tool_execute.py` — 覆盖 RTOOL-01（PAT happy/fail-closed/审计/executor 透传）
- [ ] conftest 新增 fixtures：`make_remote_tool`（source/is_active 参数化）+ `make_tool_binding`（user/token/tool）。`make_access_token` / `access_user` / `user` / `second_user` 已存在可复用（`server/tests/conftest.py`）
- [ ] 前端：`web/src/**/toolBindings*.spec.ts` — store 拉取/绑定/解绑 + 组件渲染 + 下拉只列 valid 令牌（mirror `accessTokens` 现有测试）
- [ ] executor mock：执行端点测试应 monkeypatch `tools.executor.execute_tool` 返回桩 `{ok:true,...}`，避免真起 mcp 子进程（mirror `test_mcp_whitelist.py` 风格）

## Security Domain

### Applicable ASVS Categories (Level 1)
| ASVS Category | Applies | Standard Control |
|---------------|---------|-----------------|
| V2 Authentication | yes | 执行端点 `AccessTokenAuthentication`（PAT，复用 Phase 7）；绑定 CRUD CookieJWT |
| V3 Session Management | no | 无新会话语义 |
| V4 Access Control | **yes（核心）** | 绑定 `get_queryset(user=request.user)` owner 隔离；create 校验 `access_token.created_by==request.user`；执行端点 `IsAuthenticated` fail-closed |
| V5 Input Validation | yes | DRF serializer 校验 name/arguments/FK；`remote_tool.source` 白名单 |
| V6 Cryptography | no（复用） | 不新增加密；令牌 hash 复用 `runners.models.hash_token` |
| V7 Logging | yes | 审计走 `begin_interaction_run`，明文经 ledger redact；序列化器白名单杜绝 token_hash/明文外泄 |

### Known Threat Patterns
| Pattern | STRIDE | Standard Mitigation |
|---------|--------|---------------------|
| 绑定/解绑他人资源（IDOR） | Elevation / Tampering | owner 隔离 queryset + access_token 归属校验，越权→404/400 |
| 匿名调用执行端点 | Spoofing | `[AccessTokenAuthentication]`+`IsAuthenticated`，匿名→401 |
| 废令牌/过期令牌调用 | Spoofing | `AccessTokenAuthentication` 已拒 revoked/expired/owner-inactive |
| 令牌明文/hash 经响应或日志外泄 | Information Disclosure | 序列化器白名单 + ledger redact（沿用既有契约）|
| 任意命令经 mcp source 执行 | Tampering | executor 既有 `MCP_ALLOWED_COMMANDS` 白名单（不在本期改动）|

## Environment Availability

> 本期为代码/配置变更，执行端点本身仅装配既有 executor。

| Dependency | Required By | Available | Version | Fallback |
|------------|------------|-----------|---------|----------|
| 既有 Python/Django/adrf 栈 | 全部 | ✓ | 仓库锁 | — |
| MCP 子进程（stdio） | execute_tool 的 mcp source 真实执行 | 运行时按需 | — | 测试 monkeypatch `execute_tool`，不真起子进程 |

**结论：** 无新外部依赖；测试用 mock 隔离 mcp 子进程。

## State of the Art

| Old Approach | Current Approach | Impact |
|--------------|------------------|--------|
| `unique_together` | `Meta.constraints=[UniqueConstraint(...)]`（Django 4.1+ 可命名约束） | 两者等价；CONTEXT 锁 `unique_together` 语义，沿用即可，无需引入新写法 |
| 同步 DRF view | adrf 异步 `acreate`/`async post` | 本仓库已全面采用，绑定/执行端点必须沿用异步 + `sync_to_async` 桥接 |

## Assumptions Log

| # | Claim | Section | Risk if Wrong |
|---|-------|---------|---------------|
| A1 | 执行端点对 tool not_found/timeout 返回 HTTP 200 + `{ok:false}`（沿用 executor 契约），而非映射到 404/4xx | Code Examples / Validation | 低——CONTEXT 明确「沿用 executor 既有返回契约」；若 Phase 11 容器侧偏好 HTTP 码区分，可后续加映射 |
| A2 | 后端绑定时只校验令牌 ownership，不拒绝绑「已吊销/过期」令牌（valid 由 UI 把关 + Phase 11 graceful） | Pitfalls / Open Questions | 低——属 discretion；若需后端硬拒无效令牌，加一条 `is_valid` 校验即可 |
| A3 | `tools` app 内新建（非独立新 app）；路由前缀 `/api/tools/` | Project Structure | 低——CONTEXT 推荐 tools app + `/api/tools/`；改前缀仅影响前端 URL 常量 |
| A4 | 执行端点 `source="tool"` 作为 `begin_interaction_run` 的 source 标识 | Code Examples | 极低——source 仅审计标签，自由命名（mcp_tools 用 "mcp"）|

## Open Questions

1. **execute_tool 是否需要 owner 上下文以满足 MCPB-02？（核心研究问题 Q4）**
   - **What we know:** `execute_tool(name, arguments)` 与三类 source 执行器（builtin 动态 import 调函数、mcp 起 stdio 子进程、skill 递归 execute_tool）**均不接收/不消费 user 身份**。本期「以 owner 身份执行」在认证边界成立：执行端点 PAT 认证使 `request.user=owner`，审计指纹为该令牌。
   - **What's unclear:** 真正的「以用户身份在容器内执行」需要把绑定的 PAT 注入容器、让 agent 以该令牌回调 `/api/tools/execute/`——这是 **Phase 11（RTOOL-02/03）**，会读 `ToolTokenBinding` 选令牌 + server→runner→task 直传注入 + 日志脱敏。
   - **Recommendation:** **本期不改 `execute_tool` 签名**。绑定表是 Phase 11 的数据地基；执行端点本期只需认证 + 审计 + 透传。Phase 11 gap 已在 §Deferred 记录。

2. **执行端点是否做「工具必须已绑定」强校验？**
   - **What we know:** CONTEXT discretion 推荐「不做绑定强校验，可执行任意 active 工具」，绑定表用于 Phase 11 选令牌。
   - **Recommendation:** 本期**不做**强校验（保持容器回调灵活性）；若 v2 需要，可在执行端点查 `ToolTokenBinding.filter(user=request.user, remote_tool__name=name)` 后再放行。

3. **绑定序列化器 `remote_tool` FK 用 PK（int）还是 name（unique）？**
   - **What we know:** `RemoteTool.name` 是 unique，`id` 是 BigAutoField。前端 bindable 列表两者都能给。
   - **Recommendation:** CRUD 用 `id`（PrimaryKeyRelatedField，DRF 默认）；执行端点用 `name`（RTOOL-01 明确「按 name 执行」，且容器侧只知 name）。

## Sources

### Primary (HIGH confidence) — 全部本仓库实证
- `server/tools/models.py` / `executor.py` / `registry.py` / `sources/{builtin,mcp_source,skill}.py` / `migrations/0001,0002` — RemoteTool + execute_tool 契约（async-safe 确认）
- `server/access_tokens/{models,views,serializers,authentication,urls}.py` — owner 隔离 ViewSet + PAT→owner + 不泄漏明文范式
- `server/mcp_tools/views.py`（`McpToolView`）— PAT fail-closed + handle_exception 401 + begin_interaction_run 审计范式
- `server/interactions/entry.py` — `begin_interaction_run(source=...)` 签名与脱敏
- `server/friday/urls.py` + `settings.py` — url 挂载点 + INSTALLED_APPS（`tools` 已注册）+ 默认认证链顺序（PAT 首位）
- `server/tests/conftest.py`（`make_access_token`/`access_user`/`user`/`second_user`）+ `test_pat_identity.py` + `test_access_tokens.py`（`test_cross_user_isolation`）— 测试 fixtures 与 owner 隔离用例范式
- `web/src/{api,stores,types}/accessTokens*.ts` + `components/accessTokens/*` + `pages/profile.vue` — 前端绑定 UI 范式与放置点
- `.planning/config.json` — nyquist_validation: true / security_enforcement: true (ASVS L1)

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH — 零新依赖，全部仓库内既有组件实证
- Architecture: HIGH — 直接 mirror `AccessTokenViewSet` + `McpToolView` 两个实证范式
- Pitfalls: HIGH — 从既有代码安全契约（Pitfall 1-2 注释、authenticate_header、redact）反推

**Research date:** 2026-06-10
**Valid until:** 2026-07-10（仓库内代码稳定；除非 access_tokens/tools/interactions 契约变更）
