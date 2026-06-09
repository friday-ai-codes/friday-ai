# Phase 7: 令牌即用户身份（认证地基） - Context

**Gathered:** 2026-06-09
**Status:** Ready for planning
**Mode:** Smart discuss（autonomous，推荐项已采纳；用户已授权代为决策）

<domain>
## Phase Boundary

把 Friday Access Token 从「有效即全权限的匿名放行」升级为「令牌即用户身份」的认证地基：携带有效 PAT 的请求以令牌所有者身份（`request.user = owner`）被认证，并施加该用户既有 RBAC 权限（暂不做读写 scope 细分）；PAT 与 JWT 同用 Bearer 但互不吞掉；MCP/工具入口从 `AllowAny` 收紧为 fail-closed；令牌鉴权后审计链路（`request.auth` 仍为令牌实例、InteractionRun fingerprint）保持不断；已吊销/已过期令牌一律拒。

覆盖 IDENT-01..05。**不在本期**：scope 细分、对话/会话隔离（Phase 8）、绑定执行/RemoteTool（Phase 10/11）。
</domain>

<decisions>
## Implementation Decisions

### 认证身份语义（IDENT-01 / IDENT-04 / IDENT-05）
- `AccessTokenAuthentication.authenticate` 由返回 `(None, token)` 改为返回 `(token.created_by, token)`：`request.user` = owner（真实 User），`request.auth` = AccessToken 实例（审计链不断）。
- owner 的 RBAC 经现有 DRF `IsAuthenticated` + 既有权限自然生效；**不引入** scope/项目/allowlist 细分（与里程碑决策一致）。
- 已吊销/过期 token 一律 `raise AuthenticationFailed`（保留现有 DENIED InteractionRun + error 事件审计、`last_used_at` 节流逻辑，仅改成功分支返回 owner）。
- owner 取 token 关联的 `created_by`，认证类同步上下文用同步 ORM（保持现状），`select_related("created_by")` 一并取出避免额外查询。

### PAT / JWT 共存与认证类顺序（IDENT-02）
- `AccessTokenAuthentication` 加 `friday_pat_` 前缀闸门：仅当 Bearer token 以 `friday_pat_`（复用 `PAT_PREFIX`）开头才处理；否则 `return None` 让链路交给下一个认证类（不抛错、不吞 JWT）。
- DRF `DEFAULT_AUTHENTICATION_CLASSES` 调整为 `[AccessTokenAuthentication, CookieJWTAuthentication]`——PAT 类在前并靠前缀闸门快速放行/让行；JWT（非 `friday_pat_` 前缀）落到 CookieJWT。避免「CookieJWT 先跑把 friday_pat_ 当 JWT 解析失败而整体 401」的坑。
- CookieJWT 既有「cookie 优先 + Authorization Bearer 兜底」语义不变；Web UI cookie 路径不受影响。

### MCP / 工具入口 fail-closed（IDENT-03）
- `mcp_tools/views.py` 各外部入口 view 的 `permission_classes` 从 `AllowAny` 收紧为 `IsAuthenticated`；`authentication_classes` 显式声明（至少含 `AccessTokenAuthentication`，按需含 `CookieJWTAuthentication` 以支持 Web 调用）。
- 匿名（无 token / 无效 token）请求不可调用，返回 401/403；不泄漏内部结构。
- `begin_interaction_run` 不变：`token_fingerprint` 仍取 `request.auth.token_hash`，审计链保持。

### 审计与兼容（IDENT-04）
- `request.auth` 继续是 AccessToken 实例，`interactions.entry.begin_interaction_run` / ledger 写入无需改动。
- 现有「不存在 token 不建 run、存在但无效建 DENIED run」策略保留。
- 既有以 `(None, token)` 假设的调用方（如 work-item/skill view 取 `request.auth`）不受影响；新增 `request.user=owner` 是增量能力。

### Claude's Discretion
- 认证类内部是否新增 owner 缓存/`select_related` 细节、settings 注释措辞、各 MCP view 是否统一抽一个 mixin 收紧权限，由实现时按既有风格决定。
- 测试组织（扩展 `test_auth.py` / `test_access_tokens.py` / 新增 `test_pat_identity.py`）由 planner/executor 决定。
</decisions>

<code_context>
## Existing Code Insights

### Reusable Assets
- `server/access_tokens/authentication.py`（`AccessTokenAuthentication`，当前返回 `(None, token)`，含前缀缺失检测、denial 审计、`last_used_at` 节流）。
- `server/access_tokens/models.py`（`PAT_PREFIX="friday_pat_"`、`AccessToken.created_by` FK、`is_valid`）。
- `server/common/authentication.py`（`CookieJWTAuthentication`：cookie 优先 + Authorization Bearer 兜底）。
- `server/interactions/entry.py`（`AccessTokenAuthentication` re-export、`begin_interaction_run`、`ACCESS_TOKEN_AUTH` 点路径常量）。
- `server/friday/settings.py`（`REST_FRAMEWORK.DEFAULT_AUTHENTICATION_CLASSES = [CookieJWTAuthentication]`、`DEFAULT_PERMISSION_CLASSES = [IsAuthenticated]`）。
- `server/mcp_tools/views.py`（adrf `APIView`，当前 `permission_classes = [AllowAny]` + `AccessTokenAuthentication`）。

### Established Patterns
- 认证类同步 `authenticate` + 同步 ORM（与 RunnerTokenAuthentication 一致）。
- 审计走 `interactions.ledger`，fingerprint 只存 hash，写库前 `redact_for_ledger` 脱敏。
- adrf 异步 view + `sync_to_async` 桥接 ORM。

### Integration Points
- DRF settings 认证类顺序（全局影响，需回归 Web JWT + 既有测试）。
- 既有测试：`server/tests/test_auth.py`、`test_auth_e2e.py`、`test_access_tokens.py`、`test_interactions_ledger.py`、`server/tests/mcp_tools/*`。
</code_context>

<specifics>
## Specific Ideas

- 对齐 GitLab「PAT 继承所有者全部权限」的默认语义（里程碑已锁定，不做 scope）。
- 前缀闸门是 PAT/JWT 共存的关键：用 `friday_pat_` 区分两类 Bearer，认证类顺序必须保证 PAT 类先于 JWT 类、且对非己前缀 `return None`。
</specifics>

<deferred>
## Deferred Ideas

- 细粒度读写 scope / per-tool 权限（v2 PATX-01）。
- 会话/对话 owner 过滤与越权拒绝（Phase 8）。
- 绑定令牌执行、RemoteTool 端点（Phase 10/11）。
</deferred>
