# Phase 7: 令牌即用户身份（认证地基） - Research

**Researched:** 2026-06-09
**Domain:** DRF 认证类编排（PAT + JWT 共存）、fail-closed 权限收紧、审计链路保持
**Confidence:** HIGH（全部基于本仓库实际源码 + 已安装 DRF/SimpleJWT 源码核验，无外部依赖猜测）

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions

**认证身份语义（IDENT-01 / IDENT-04 / IDENT-05）**
- `AccessTokenAuthentication.authenticate` 由返回 `(None, token)` 改为返回 `(token.created_by, token)`：`request.user` = owner（真实 User），`request.auth` = AccessToken 实例（审计链不断）。
- owner 的 RBAC 经现有 DRF `IsAuthenticated` + 既有权限自然生效；**不引入** scope/项目/allowlist 细分。
- 已吊销/过期 token 一律 `raise AuthenticationFailed`（保留现有 DENIED InteractionRun + error 事件审计、`last_used_at` 节流逻辑，仅改成功分支返回 owner）。
- owner 取 token 关联的 `created_by`，认证类同步上下文用同步 ORM（保持现状），`select_related("created_by")` 一并取出避免额外查询。

**PAT / JWT 共存与认证类顺序（IDENT-02）**
- `AccessTokenAuthentication` 加 `friday_pat_` 前缀闸门：仅当 Bearer token 以 `friday_pat_`（复用 `PAT_PREFIX`）开头才处理；否则 `return None` 让链路交给下一个认证类（不抛错、不吞 JWT）。
- DRF `DEFAULT_AUTHENTICATION_CLASSES` 调整为 `[AccessTokenAuthentication, CookieJWTAuthentication]`——PAT 类在前并靠前缀闸门快速放行/让行；JWT 落到 CookieJWT。
- CookieJWT 既有「cookie 优先 + Authorization Bearer 兜底」语义不变；Web UI cookie 路径不受影响。

**MCP / 工具入口 fail-closed（IDENT-03）**
- `mcp_tools/views.py` 各外部入口 view 的 `permission_classes` 从 `AllowAny` 收紧为 `IsAuthenticated`；`authentication_classes` 显式声明（至少含 `AccessTokenAuthentication`，按需含 `CookieJWTAuthentication` 以支持 Web 调用）。
- 匿名（无 token / 无效 token）请求不可调用，返回 401/403；不泄漏内部结构。
- `begin_interaction_run` 不变：`token_fingerprint` 仍取 `request.auth.token_hash`，审计链保持。

**审计与兼容（IDENT-04）**
- `request.auth` 继续是 AccessToken 实例，`interactions.entry.begin_interaction_run` / ledger 写入无需改动。
- 现有「不存在 token 不建 run、存在但无效建 DENIED run」策略保留。
- 既有以 `(None, token)` 假设的调用方不受影响；新增 `request.user=owner` 是增量能力。

### Claude's Discretion
- 认证类内部是否新增 owner 缓存/`select_related` 细节、settings 注释措辞、各 MCP view 是否统一抽一个 mixin 收紧权限，由实现时按既有风格决定。
- 测试组织（扩展 `test_auth.py` / `test_access_tokens.py` / 新增 `test_pat_identity.py`）由 planner/executor 决定。

### Deferred Ideas (OUT OF SCOPE)
- 细粒度读写 scope / per-tool 权限（v2 PATX-01）。
- 会话/对话 owner 过滤与越权拒绝（Phase 8 ISO-*）。
- 绑定令牌执行、RemoteTool 端点（Phase 10/11 MCPB-*/RTOOL-*）。
</user_constraints>

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| IDENT-01 | 携带有效令牌的请求以令牌所有者身份被认证（`request.user` = owner），施加该用户 RBAC | `authenticate` 成功分支改返回 `(token.created_by, token)`；`created_by` 经 `select_related` 取出（见 §Architecture Patterns / Code Examples）。`IsAuthenticated` + 既有权限对真实 User 自然生效。 |
| IDENT-02 | `friday_pat_` 前缀闸门识别，PAT 与 JWT 互不吞掉，认证类顺序明确 | 已核验 SimpleJWT 在 Bearer 头存在但 token 非法时 `raise InvalidToken`（中断链路），故 PAT 类必须 FIRST 且对非 `friday_pat_` 前缀 `return None`（见 §Pitfall 1 + Code Examples）。 |
| IDENT-03 | MCP/工具入口从 `AllowAny` 收紧为要求认证（fail-closed） | 仅 `mcp_tools/views.py::McpToolView` 基类需改 `permission_classes=[IsAuthenticated]`（17 个子类全部继承）；其余 `AllowAny` 入口非 PAT 体系，明确不在范围（见 §Runtime State Inventory / Don't Hand-Roll）。 |
| IDENT-04 | 审计链路保持不断（`request.auth` 仍为令牌实例，fingerprint 正常记录） | `request.auth` 仍是 AccessToken 实例；`begin_interaction_run` 取 `request.auth.token_hash` 零改动（见 §Architecture Patterns）。 |
| IDENT-05 | 已吊销/已过期令牌一律被拒，不能用于任何身份调用 | 现有 `is_valid` 校验 + DENIED run + `raise AuthenticationFailed` 失败分支完全保留，不受成功分支改动影响（见 §Code Examples）。 |
</phase_requirements>

## Summary

本期是**对既有认证管线的外科手术式改造**，不引入任何新库、新模型或新迁移。核心三处改动全部落在已存在文件：(1) `AccessTokenAuthentication.authenticate` 成功分支由 `(None, token)` 改为 `(token.created_by, token)`，并新增 `friday_pat_` 前缀闸门；(2) DRF `DEFAULT_AUTHENTICATION_CLASSES` 由 `[CookieJWTAuthentication]` 改为 `[AccessTokenAuthentication, CookieJWTAuthentication]`；(3) `mcp_tools/views.py::McpToolView` 基类 `permission_classes` 由 `AllowAny` 收紧为 `IsAuthenticated`。

研究中通过阅读已安装的 `rest_framework_simplejwt/authentication.py` 与 `rest_framework/views.py` 源码，确认了两个**非显而易见且会破坏现有测试**的陷阱：① SimpleJWT 在 `Authorization` 头存在但 token 非 JWT 时会 `raise InvalidToken`（`AuthenticationFailed` 子类）从而中断整个认证链 → 这是必须把 PAT 类排在 JWT 前、且对非己前缀 `return None`（而非 raise）的根本原因；② DRF 的 `get_authenticate_header` 只看 `authenticators[0]`，若首位认证类的 `authenticate_header()` 返回 `None`（`BaseAuthentication` 默认行为），DRF 会把未认证响应**从 401 降级为 403**。由于本期把 `AccessTokenAuthentication`（未实现 `authenticate_header`）提到全局首位，**全站未认证请求会从 401 变 403**，直接打破 `test_auth.py` / `test_auth_e2e.py` 对 401 的断言。

**Primary recommendation:** 三处主改动 + 一处必备配套修复——给 `AccessTokenAuthentication` 实现 `authenticate_header(self, request)` 返回非 None（如 `'Bearer realm="api"'`），以保住全站 401 语义。逐项更新 4 个受影响测试断言（详见 §Regression / Validation Architecture）。

## Architectural Responsibility Map

| Capability | Primary Tier | Secondary Tier | Rationale |
|------------|-------------|----------------|-----------|
| PAT → owner 身份解析 | API / Backend（DRF 认证类） | Database（`AccessToken.created_by` FK） | 认证发生在 DRF 请求管线进入 view 之前，是后端职责；owner 来自 DB FK。 |
| PAT vs JWT 路由（前缀闸门） | API / Backend（认证类编排） | — | 纯请求头判别，必须在认证阶段、view 之前完成。 |
| RBAC 鉴权 | API / Backend（DRF 权限类 `IsAuthenticated` + 既有权限） | Database（ProjectMembership） | 权限层基于 `request.user`；本期不改权限类，只让 owner 成为真实 User。 |
| MCP 入口 fail-closed | API / Backend（`McpToolView.permission_classes`） | — | 外部 HTTP 入口的访问控制是后端边界职责。 |
| 审计链记录 | API / Backend（`interactions.ledger` 同步/异步入口） | Database（InteractionRun/Event） | 既有，零改动；`request.auth` 提供 fingerprint。 |

## Standard Stack

本期**不安装任何新包**。复用既有栈：

### Core
| Library | Version (已锁定) | Purpose | Why Standard |
|---------|------------------|---------|--------------|
| `djangorestframework` | >=3.15（已装） | `BaseAuthentication` / 认证类管线 / 权限类 | 既有认证地基，所有 view 都跑在它上面 |
| `djangorestframework-simplejwt` | >=5.3（已装） | `JWTAuthentication` 基类（被 `CookieJWTAuthentication` 继承） | Web/SDK JWT 既有路径，不动 |
| `adrf` | >=0.1.12（已装） | MCP view 的异步 `APIView` | MCP 入口既有基类 |

### Alternatives Considered
| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| 实现 `authenticate_header` 保 401 | 在 `authentication_classes` 里把 `CookieJWTAuthentication` 排首位 | ❌ 不可行：JWT 类首位会把 `friday_pat_` Bearer 当 JWT 解析并 raise（IDENT-02 的坑），与本期目标冲突 |
| `return None`（非己前缀） | `raise AuthenticationFailed` | ❌ raise 会中断链路，JWT 永远落不到 CookieJWT → 吞掉 JWT |

**Installation:** 无（`uv` 依赖不变，无 `makemigrations`）。

## Package Legitimacy Audit

不适用——本期不安装任何外部包，纯代码改动。所有使用的库（DRF、SimpleJWT、adrf）均已在 `server/pyproject.toml` 锁定并随 Phase 1-6 落地。

## Architecture Patterns

### DRF 认证链路（改造后数据流）

```
HTTP Request
   │
   ▼
DRF APIView.perform_authentication
   │  按 authentication_classes 顺序逐个调用 authenticate(request)
   │  规则：返回 None → 试下一个；返回 (user, auth) → 停止并设置 request.user/request.auth；
   │        raise AuthenticationFailed/InvalidToken → 立即中断，进入 handle_exception
   ▼
[1] AccessTokenAuthentication.authenticate
   │
   ├── 无 "Bearer " 头 ──────────────► return None ──┐
   ├── Bearer 但非 friday_pat_ 前缀 ─► return None ──┤ (让行给 JWT)
   │       (★前缀闸门：IDENT-02 核心)                  │
   ├── friday_pat_ 且 token 不存在 ──► raise AuthenticationFailed (不建 run)
   ├── friday_pat_ 且 is_valid=False ► DENIED run + raise (IDENT-05)
   └── friday_pat_ 且有效 ──────────► return (token.created_by, token)  ★IDENT-01
                                                        │
   ┌────────────────────────────────────────────────────┘
   ▼
[2] CookieJWTAuthentication.authenticate (SimpleJWT)
   │
   ├── 无 cookie 且无 Authorization 头 ► get_header()→None → return None
   ├── cookie/JWT 有效 ──────────────► return (jwt_user, validated_token)
   └── JWT 非法 ─────────────────────► raise InvalidToken → 401
   │
   ▼
权限层 IsAuthenticated：request.user.is_authenticated?
   ├── owner / jwt_user → True  → 放行 view
   └── 无认证成功 → permission_denied → NotAuthenticated
                    → handle_exception：get_authenticate_header(authenticators[0])
                       ├── authenticators[0]=AccessTokenAuth 实现了 authenticate_header → 401 ✅
                       └── 未实现（默认 None）→ 降级 403 ❌（必须修复！见 Pitfall 2）
```

### Pattern 1: 前缀闸门（prefix gate）
**What:** 在认证类入口、取出 Bearer 明文后、做任何 DB 查询前，判断 `plaintext.startswith(PAT_PREFIX)`，非己前缀立即 `return None`。
**When to use:** 多个 Bearer-based 认证类共存、需互不吞掉时的标准编排手法。
**位置（精确）:** `server/access_tokens/authentication.py` 第 53 行 `plaintext = auth_header[7:]` 之后、第 57 行 `fingerprint = hash_token(plaintext)` 之前插入。

### Pattern 2: 成功分支返回真实 owner
**What:** `return (token.created_by, token)` 取代 `return (None, token)`。配合 `AccessToken.objects.select_related("created_by").get(token_hash=...)` 在同一次查询取出 owner，避免访问 `token.created_by` 时多一次 DB 往返。
**审计不变量:** `request.auth` 仍是 `token`，故 `begin_interaction_run` 的 `getattr(request.auth, "token_hash", "")` 完全不受影响（IDENT-04）。

### Pattern 3: fail-closed 收紧（基类一处改，子类全继承）
**What:** `McpToolView` 是 17 个 MCP view 的公共基类（`RouteRepositoriesView`、`SearchRagChunksView`、`GetRepositoryView` … `CreateMergeRequestView`）。在基类把 `permission_classes = [AllowAny]` 改为 `[IsAuthenticated]`、并把 `authentication_classes` 显式声明为 `[AccessTokenAuthentication, CookieJWTAuthentication]`，所有子类一次性收紧。
**注意:** `CreateMergeRequestView(SummarizeBranchView)` 继承自 `SummarizeBranchView` 而非直接继承 `McpToolView`，但 `SummarizeBranchView` 继承 `McpToolView`，仍受基类改动覆盖。

### Anti-Patterns to Avoid
- **把非 `friday_pat_` 前缀的 Bearer 在 PAT 类里 raise**：会中断链路、吞掉 JWT（IDENT-02 反例）。必须 `return None`。
- **把 `CookieJWTAuthentication` 排在 PAT 类之前**：JWT 类会把 `friday_pat_` Bearer 当 JWT 解析失败并 raise → PAT 永远没机会跑（整体 401）。
- **改 `authentication_classes` 顺序却忘了 `authenticate_header`**：全站未认证响应从 401 静默降级为 403（Pitfall 2）。

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| 401 vs 403 状态码判定 | 自己在 view 里写状态码分支 | DRF `get_authenticate_header` + 在认证类实现 `authenticate_header` | DRF 已有标准机制；只需让首位认证类返回非 None |
| JWT 校验 | 手写 JWT 解析 | `CookieJWTAuthentication`（已继承 SimpleJWT） | 既有，安全等价，不动 |
| 收紧其它 `AllowAny` 入口 | 顺手把 runner/feishu/webhook/compat 入口也改 | **不要动** | 它们是独立信任边界（见下） |

**Key insight — 其它 `AllowAny` 入口明确不在本期范围（fail-closed 只针对 MCP/PAT 入口）:**
- `server/runners/views.py:88` `RunnerRegisterView`（`authentication_classes=[]`）：runner 引导/注册，自带 `RunnerTokenAuthentication` 体系。
- `server/subagent/api/callbacks.py:363`：task 容器回调，自有鉴权（Phase 11 RTOOL 范畴）。
- `server/repositories/index_views.py:1558` `RepositoryWebhookView`：git webhook，自带 secret 校验。
- `server/feishu/views.py:184/409/538`：飞书 webhook/card 回调，自带签名校验。
- `server/compat/auth.py`：OpenAI-compat API key 白名单（独立 `OPENAI_COMPAT_API_KEYS` 体系）。

这些都不是 PAT 体系入口，IDENT-03 只要求收紧 MCP/工具入口；改它们会越界并可能破坏 webhook/runner 链路。

## Runtime State Inventory

> 本期是认证语义重构（非字符串 rename），但仍核查"代码改完后还有什么运行时状态会受影响"。

| Category | Items Found | Action Required |
|----------|-------------|------------------|
| Stored data | **None** —— `AccessToken` 表结构不变，无新字段/迁移。owner 早已存在于 `created_by` FK（Phase 6 已建），历史 token 都有 owner。 | 无数据迁移 |
| Live service config | **None** —— 无 UI/DB-only 配置依赖该认证返回值。 | 无 |
| OS-registered state | **None** —— 不涉及定时任务/进程注册。 | 无 |
| Secrets/env vars | **None 新增** —— PAT 明文不落盘契约不变；JWT `SIGNING_KEY`/cookie 设置不变。 | 无 |
| Build artifacts | **None** —— 无包名/二进制变更。 | 无 |
| **运行时调用方语义** | `request.user`：MCP 路径此前为 `AnonymousUser`（`(None, token)`），改后为真实 owner。**已核查 `mcp_tools/` 内无任何代码读取 `request.user`**（仅读 `request.auth`，见 `_begin` 第 158 行 `request.auth is None`）。 | 仅需更新依赖"匿名"假设的测试断言（见 Regression） |

**关键问题——代码改完后还有什么旧语义被缓存/假设？**
- DRF 全局默认认证类顺序变更影响**所有** DRF 视图的未认证响应码（401→403 风险）→ 必须配 `authenticate_header`（Pitfall 2）。
- 唯一读取认证返回 `user` 维度的断言在 `test_access_tokens.py::test_valid_token_passes`（断言 `user is None`）。

## Common Pitfalls

### Pitfall 1: 认证类顺序 + 非己前缀必须 return None（IDENT-02 核心）
**What goes wrong:** 若 `CookieJWTAuthentication` 先于 PAT 类运行，遇到 `Authorization: Bearer friday_pat_xxx`，SimpleJWT `get_validated_token` 对每个 `AUTH_TOKEN_CLASSES` 都解析失败 → `raise InvalidToken`（`AuthenticationFailed` 子类）→ DRF 立即中断，PAT 类永无机会 → 合法 PAT 反被 401。
**Why it happens:** DRF 认证链遇到 `return None` 才继续下一个；遇到 `raise` 立即停止。SimpleJWT 在「头存在但 token 非 JWT」时是 raise 而非 return None（已核验 `rest_framework_simplejwt/authentication.py:49,95-118`）。
**How to avoid:** (1) PAT 类排首位；(2) PAT 类对非 `friday_pat_` 前缀 `return None`（让行），仅对 `friday_pat_` 前缀做 DB 查询与 raise。
**Warning signs:** Web JWT 登录后调用受保护 API 正常，但带 PAT 调用返回 401「Given token not valid for any token type」。

### Pitfall 2: 全站 401→403 降级（最隐蔽、必破测试）
**What goes wrong:** 把 `AccessTokenAuthentication` 提到 `DEFAULT_AUTHENTICATION_CLASSES` 首位后，未认证请求的响应码从 401 静默变成 403，打破 `test_auth.py::test_me_unauthenticated`、`test_change_password_unauthenticated`、`test_auth_e2e.py::test_unauthenticated_access_denied`。
**Why it happens:** DRF `APIView.handle_exception` 对 `NotAuthenticated` 调 `get_authenticate_header`，后者**只取 `authenticators[0].authenticate_header(request)`**（已核验 `rest_framework/views.py:189-196,454-467`）。`BaseAuthentication.authenticate_header` 默认返回 `None`（`rest_framework/authentication.py:44-48`）→ DRF 把 `status_code` 降级为 403。`CookieJWTAuthentication`（SimpleJWT）本来实现了 `authenticate_header` 返回 Bearer realm，所以原来是 401；现在首位变成未实现的 `AccessTokenAuthentication`。
**How to avoid:** 给 `AccessTokenAuthentication` 实现：
```python
def authenticate_header(self, request: Request) -> str:
    return 'Bearer realm="api"'
```
**Warning signs:** 未认证访问任意受保护端点返回 403 而非 401；上述 3 个测试 RED。

### Pitfall 3: MCP 端点错误码契约变化（401 保留，但 error_code 变）
**What goes wrong:** 现状 `McpToolView` 用 `AllowAny` + `_begin()` 内手动判 `request.auth is None` 返回 `error_response("authentication_required", ..., 401)`。改为 `IsAuthenticated` 后，**权限层在进入 `_begin` 之前就拒绝**，走 `McpToolView.handle_exception`（捕获 `NotAuthenticated` → 返回 `error_response("authentication_failed", ..., 401)`）。于是 `test_mcp_auth_errors.py::test_missing_token_returns_error_code` 断言的 `error_code == "authentication_required"` 会失败。
**Why it happens:** DRF 权限检查先于 view body；MCP 自定义 `handle_exception` 硬编码 401（不受 Pitfall 2 的 403 降级影响，因为它在调用 `super()` 前已显式返回 401）。
**How to avoid（二选一，planner 决定）:**
- (A) 更新测试断言为 `"authentication_failed"`（最小改动，符合 CONTEXT「不泄漏内部结构 + 返回 401」）。
- (B) 若要保留 `"authentication_required"` 码，在 `_begin` 保留手动 401 路径并让 MCP view 继续用 `AllowAny`——但这与 CONTEXT「收紧为 IsAuthenticated」相悖，**不推荐**。
**Warning signs:** `test_missing_token_returns_error_code` RED；MCP 无 token 调用返回 `"authentication_failed"`。

### Pitfall 4: 认证类是同步上下文，owner 访问别触发异步陷阱
**What goes wrong:** MCP view 是 adrf 异步 view，但 DRF 认证发生在同步阶段；`AccessTokenAuthentication.authenticate` 是同步方法，内部用同步 ORM（既有约定）。访问 `token.created_by` 若未 `select_related` 会触发同步惰性查询（在认证同步阶段是安全的，但多一次 DB 往返）。
**How to avoid:** `AccessToken.objects.select_related("created_by").get(token_hash=fingerprint)`，owner 随主查询取出。
**Warning signs:** 认证路径 N+1 查询；高频 MCP 调用 DB 压力上升。

## Code Examples

### authenticate 改造（成功分支 + 前缀闸门 + authenticate_header）

```python
# server/access_tokens/authentication.py（改造示意，基于现有 42-74 行）
from .models import PAT_PREFIX, AccessToken  # 复用前缀常量

class AccessTokenAuthentication(BaseAuthentication):
    def authenticate(self, request: Request) -> tuple[object, AccessToken] | None:
        auth_header = request.META.get("HTTP_AUTHORIZATION", "")
        if not auth_header.startswith("Bearer "):
            return None

        plaintext = auth_header[7:]
        if not plaintext:
            return None

        # ★IDENT-02 前缀闸门：非 friday_pat_ 一律让行给下一个认证类（CookieJWT），
        #   绝不 raise，否则会吞掉 JWT。
        if not plaintext.startswith(PAT_PREFIX):
            return None

        fingerprint = hash_token(plaintext)
        try:
            # ★IDENT-01：owner 随主查询取出，避免认证路径 N+1。
            token = AccessToken.objects.select_related("created_by").get(
                token_hash=fingerprint
            )
        except AccessToken.DoesNotExist:
            logger.warning("access_token_denied", reason="not_found")
            raise AuthenticationFailed("无效的 Friday Access Token")

        if not token.is_valid:  # IDENT-05：吊销/过期一律拒（DENIED run 保留）
            self._record_denial(
                request, fingerprint=token.token_hash, reason="revoked_or_expired"
            )
            raise AuthenticationFailed("Token 已吊销或已过期")

        self._touch_last_used(token)
        # ★IDENT-01/04：request.user=owner（真实 User），request.auth=token（审计链不断）
        return (token.created_by, token)

    def authenticate_header(self, request: Request) -> str:
        # ★Pitfall 2 必备：作为全局首位认证类，必须返回非 None 以保全站 401 语义。
        return 'Bearer realm="api"'
```

### settings 认证类顺序

```python
# server/friday/settings.py 第 272-278 行
REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": [
        "access_tokens.authentication.AccessTokenAuthentication",  # ★PAT 类首位
        "common.authentication.CookieJWTAuthentication",
    ],
    "DEFAULT_PERMISSION_CLASSES": [
        "rest_framework.permissions.IsAuthenticated",
    ],
    ...
}
```
> 可复用 `interactions.entry.ACCESS_TOKEN_AUTH = "access_tokens.authentication.AccessTokenAuthentication"` 点路径常量。

### MCP 基类 fail-closed

```python
# server/mcp_tools/views.py 第 141-145 行
from rest_framework.permissions import IsAuthenticated  # 替换 AllowAny
from common.authentication import CookieJWTAuthentication

class McpToolView(APIView):
    authentication_classes = [AccessTokenAuthentication, CookieJWTAuthentication]
    permission_classes = [IsAuthenticated]  # ★IDENT-03：fail-closed
    tool_name = ""
    # _begin() 的 `if request.auth is None:` 可保留作纵深防御（PAT 路径 request.auth=token；
    # Web JWT 路径 request.auth=validated_token，无 token_hash → begin_interaction_run
    # 的 getattr(request.auth, "token_hash", "") 自然降级为空串，不报错）。
```

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| `(None, token)`「有效即全权限匿名放行」 | `(owner, token)`「令牌即用户身份 + RBAC」 | 本期 Phase 7 | 对齐 GitHub/GitLab PAT 默认语义（继承所有者全部权限，不做 scope） |
| MCP 入口 `AllowAny` + view 内手动判空 | `IsAuthenticated` fail-closed | 本期 Phase 7 | 匿名/无效 token 在权限层即被拒，不进 view body |

## Assumptions Log

| # | Claim | Section | Risk if Wrong |
|---|-------|---------|---------------|
| A1 | Web 用户也需经 MCP 端点调用（故 `authentication_classes` 加 `CookieJWTAuthentication`） | Pattern 3 / Code Examples | 若 MCP 仅供外部 PAT/SDK 调用，加 CookieJWT 无害但冗余；CONTEXT 标注「按需」，由 planner 定。低风险。 |
| A2 | `request.auth` 为 JWT validated_token 时 `getattr(..., "token_hash", "")` 降级为空串可接受 | Code Examples | Web 用户走 MCP 时审计 fingerprint 为空——但本期 MCP 主调用方仍是 PAT；ISO/Phase 8 再细化。低风险。 |

**注:** 以上为仅有的两处需 planner 确认的假设，其余结论均经源码核验（HIGH）。

## Open Questions

1. **MCP 错误码契约（Pitfall 3）保 `"authentication_required"` 还是收敛到 `"authentication_failed"`？**
   - What we know: 改 `IsAuthenticated` 后权限层先拒，走 `handle_exception` → `"authentication_failed"`。
   - What's unclear: 是否有外部 MCP 客户端硬依赖 `"authentication_required"` 字面码。
   - Recommendation: 采用方案 (A)——更新测试为 `"authentication_failed"`，符合 CONTEXT「返回 401、不泄漏内部结构」；如需向后兼容再让 planner 决定加自定义权限类回填旧码。

2. **是否给 MCP base 加 `CookieJWTAuthentication`（A1）。** 推荐加（支持 Web 触发 MCP 工具），无副作用。

## Environment Availability

Step 2.6: SKIPPED（纯代码改动，无新增外部工具/服务/运行时依赖；测试用既有 `uv run pytest` + SQLite）。

## Validation Architecture

### Test Framework
| Property | Value |
|----------|-------|
| Framework | `pytest` >=9.0.2 + `pytest-django` >=4.8 + `pytest-asyncio` + `pytest-socket`（网络隔离） |
| Config file | `server/pyproject.toml`（`[tool.pytest.ini_options]`） |
| Quick run command | `cd server && uv run pytest tests/test_access_tokens.py tests/mcp_tools/test_mcp_auth_errors.py -x -q` |
| Full suite command | `cd server && uv run pytest tests/test_auth.py tests/test_auth_e2e.py tests/test_access_tokens.py tests/test_interactions_ledger.py tests/mcp_tools/ -q` |

### Phase Requirements → Test Map
| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| IDENT-01 | 有效 PAT → `authenticate` 返回 `(owner, token)`，`request.user==created_by` | unit | `uv run pytest tests/test_access_tokens.py::test_valid_token_passes -x` | ✅ 存在但断言需改（当前断言 `user is None`） |
| IDENT-02 | `Bearer <jwt>` 落 CookieJWT（PAT 类 return None）；`Bearer friday_pat_*` 落 PAT 类；两者互不吞 | unit/integration | `uv run pytest tests/test_pat_identity.py -k "jwt_falls_through or pat_handled" -x` | ❌ Wave 0（新增） |
| IDENT-02 | 全站未认证请求保持 401（authenticate_header 修复） | integration | `uv run pytest tests/test_auth.py::TestMe::test_me_unauthenticated tests/test_auth_e2e.py -k unauthenticated -x` | ✅ 存在（须保持 GREEN） |
| IDENT-03 | MCP 无 token → 401；有效 PAT → 200/正常业务码 | integration | `uv run pytest tests/mcp_tools/test_mcp_auth_errors.py -x` | ✅ 存在但 `error_code` 断言需改（见 Pitfall 3） |
| IDENT-04 | 有效 PAT 调 MCP → `request.auth.token_hash` 写入 InteractionRun fingerprint | integration | `uv run pytest tests/mcp_tools/test_retrieval_trace.py tests/test_interactions_ledger.py -x` | ✅ 存在（回归） |
| IDENT-05 | 吊销/过期 token → 401 + DENIED run；不可用于任何身份 | unit | `uv run pytest tests/test_access_tokens.py::test_revoked_expired_denied_and_logged -x` | ✅ 存在（须保持 GREEN，不受成功分支改动影响） |

### Sampling Rate
- **Per task commit:** Quick run command（PAT 认证 + MCP auth 错误）。
- **Per wave merge:** Full suite command（含全站 401 回归 + 审计回归）。
- **Phase gate:** Full suite green before `/gsd-verify-work`。

### Wave 0 Gaps
- [ ] `tests/test_pat_identity.py`（或扩展 `test_access_tokens.py`）— 覆盖 IDENT-02 前缀闸门双向：① `Bearer <有效JWT>` 经 `[AccessToken, CookieJWT]` 链路认证为 JWT 用户（PAT 类 return None 让行）；② `Bearer friday_pat_<有效>` 认证为 owner；③ `Bearer friday_pat_<不存在>` → 401 且不落到 JWT。建议用 `APIRequestFactory` 直接驱动 DRF 认证链或经 `APIClient` 打一个受 `IsAuthenticated` 保护的端点。
- [ ] 更新 `tests/test_access_tokens.py::test_valid_token_passes`：`assert user is None` → `assert user == token.created_by`；删去/改写注释「返回 (None, token)」。
- [ ] 更新 `tests/mcp_tools/test_mcp_auth_errors.py::test_missing_token_returns_error_code`：`error_code` 期望由 `"authentication_required"` → `"authentication_failed"`（或按 Open Question 1 决议）。
- [ ] 全站 401 回归保护：确保 `tests/test_auth.py`、`tests/test_auth_e2e.py` 的未认证 401 断言在加了 `authenticate_header` 后保持 GREEN（无需新增，作为 BLOCKING 回归）。
- 框架已就绪，无需安装。

## Security Domain

`security_enforcement: true`，`security_asvs_level: 1`。本期是认证/访问控制核心改动，安全相关度高。

### Applicable ASVS Categories

| ASVS Category | Applies | Standard Control |
|---------------|---------|-----------------|
| V2 Authentication | yes | PAT 经 sha256 fingerprint 比对（`hash_token`，明文绝不落盘，Phase 6 契约）；JWT 经 SimpleJWT 验签。本期不改哈希/验签算法。 |
| V3 Session Management | yes | JWT cookie（HttpOnly/SameSite/Secure）+ refresh 轮转不变；PAT 无 session 概念。 |
| V4 Access Control | yes（核心） | fail-closed：`IsAuthenticated` 默认拒；MCP 入口由 `AllowAny`→`IsAuthenticated`。owner 身份 + 既有 RBAC（ProjectMembership）。 |
| V5 Input Validation | partial | Bearer 头解析既有；前缀闸门为白名单式判别。MCP 入参经既有 serializer 校验（不变）。 |
| V6 Cryptography | yes | 复用 `runners.models.hash_token`（sha256）、Fernet 凭证加密——**禁止重写**。 |
| V7 Error Handling & Logging | yes | DENIED run + structlog；fingerprint 只存 hash，`redact_for_ledger` 脱敏（不变）。错误响应不泄漏内部结构（CONTEXT 要求）。 |

### Known Threat Patterns for {DRF auth refactor}

| Pattern | STRIDE | Standard Mitigation |
|---------|--------|---------------------|
| 认证类顺序错误导致合法 PAT 被 401 / 或 JWT 被吞 | Denial of Service | PAT 类首位 + 非己前缀 return None（Pitfall 1）；新增 IDENT-02 双向测试 |
| 401→403 降级泄漏端点存在性/破坏客户端重试 | Information Disclosure | 首位认证类实现 `authenticate_header`（Pitfall 2） |
| fail-open：MCP 入口仍 `AllowAny` 致匿名调用 | Elevation of Privilege | 基类 `IsAuthenticated`（IDENT-03）；回归测试断言匿名 401 |
| 吊销 token 仍可用 | Spoofing / EoP | 保留 `is_valid` 校验 + raise（IDENT-05）；既有测试守 GREEN |
| owner 提权（PAT 越权他人资源） | Elevation of Privilege | 本期不引入 scope，owner 仅获**自身** RBAC；越权资源隔离留 Phase 8（ISO）——本期不扩大权限面 |
| 审计断链（改返回值后 fingerprint 丢失） | Repudiation | `request.auth` 保持 token 实例；IDENT-04 回归测试守审计写入 |

## Sources

### Primary (HIGH confidence)
- `server/access_tokens/authentication.py`（行 42-110）— 现有 `authenticate` / DENIED / 节流逻辑
- `server/access_tokens/models.py`（行 21-78）— `PAT_PREFIX` / `created_by` / `is_valid`
- `server/common/authentication.py`（行 13-37）— `CookieJWTAuthentication.get_header` cookie 优先 + Bearer 兜底
- `server/friday/settings.py`（行 272-285）— `REST_FRAMEWORK` 认证/权限默认类
- `server/mcp_tools/views.py`（行 141-165 基类 + 17 个子类）— `McpToolView` `AllowAny` + `_begin`
- `server/interactions/entry.py`（行 39-105）— `begin_interaction_run` 取 `request.auth.token_hash`
- `.venv/.../rest_framework_simplejwt/authentication.py`（行 40-118）— JWT 在 token 非法时 `raise InvalidToken`
- `.venv/.../rest_framework/views.py`（行 175-196, 454-478）— `permission_denied` / `get_authenticate_header`（用 authenticators[0]）/ 401→403 降级
- `.venv/.../rest_framework/authentication.py`（行 44-48）— `BaseAuthentication.authenticate_header` 默认 None
- 既有测试：`tests/test_access_tokens.py`、`tests/test_auth.py`、`tests/test_auth_e2e.py`、`tests/mcp_tools/conftest.py`、`tests/mcp_tools/test_mcp_auth_errors.py`、`tests/conftest.py`（`make_access_token` / `access_user` fixtures）

### Secondary (MEDIUM confidence)
- GitLab/GitHub PAT「继承所有者全部权限」默认语义（CONTEXT 既锁定为里程碑决策，作设计对齐参照）

### Tertiary (LOW confidence)
- 无

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH — 无新依赖，全部既有且版本锁定
- Architecture / ordering trap: HIGH — 直接读 SimpleJWT 与 DRF 源码核验 raise/return None 与 401/403 行为
- Pitfalls: HIGH — 每条都映射到具体源码行 + 具体会破的测试
- Regression surface: HIGH — 逐文件定位受影响断言

**Research date:** 2026-06-09
**Valid until:** 2026-07-09（稳定栈，30 天；除非 DRF/SimpleJWT 大版本升级）
