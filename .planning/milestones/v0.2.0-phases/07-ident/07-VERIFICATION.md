---
phase: 07-ident
verified: 2026-06-09T21:34:00Z
status: human_needed
score: 5/5 must-haves verified
overrides_applied: 0
human_verification:

  - test: "在浏览器中以 Web UI 走 cookie-JWT 登录（access_token HttpOnly cookie 主路径），然后访问受保护页面/接口（如 /me、对话、工作流）"
    expected: "登录成功，受保护资源正常返回 200；DEFAULT_AUTHENTICATION_CLASSES 改为 PAT-first 后，cookie 优先的 access_token 仍被 CookieJWTAuthentication 正常接住，端到端不回退"
    why_human: "认证类全局重排属高 blast-radius 改动；自动化测试覆盖了 Bearer-header JWT、refresh cookie、logout 与站点级 401，但 access_token cookie-first 路径经重排链路的真实浏览器端到端登录未在本次验证中实跑"
audit_acknowledged:
  milestone: v0.25.0
  at: 2026-08-31
  status: human_needed
---

# Phase 7: 令牌即用户身份（认证地基） Verification Report

**Phase Goal:** 携带有效 PAT 的请求以令牌所有者身份 + 其 RBAC 权限被鉴权（替代「有效即全权限」），MCP 入口 fail-closed，PAT 与 JWT 互不干扰，认证类顺序明确，审计链路不断。
**Verified:** 2026-06-09T21:34:00Z
**Status:** human_needed
**Re-verification:** No — initial verification

## Goal Achievement

### Observable Truths

| # | Truth (IDENT) | Status | Evidence |
|---|---------------|--------|----------|
| 1 | IDENT-01: 有效 PAT 认证为 owner（`request.user = created_by`）+ owner RBAC；停用 owner 被拒 | ✓ VERIFIED | `authentication.py:94-103` 成功分支返回 `(token.created_by, token)`，`select_related("created_by")`；`:94-98` CR-01 修复——`is_active=False` 写 `owner_inactive` DENIED run 后 `raise`。测试 `test_valid_pat_authenticates_as_owner`、`test_pat_authenticates_protected_endpoint_as_owner`（/me→200 + username==owner）、`test_inactive_owner_pat_is_rejected`、`test_inactive_owner_pat_rejected_through_chain`（→401）全 GREEN |
| 2 | IDENT-02: `friday_pat_` 前缀闸门；非 PAT 让行 JWT；坏 PAT 不下传；DEFAULT_AUTHENTICATION_CLASSES PAT-first；`authenticate_header` 防 401→403 | ✓ VERIFIED | `authentication.py:71-72` 前缀闸门 `return None`；`:105-107` `authenticate_header` 返回 `'Bearer realm="api"'`；`settings.py:277-280` PAT 类排首位。测试 `test_non_pat_bearer_falls_through`（→None）、`test_unknown_pat_is_rejected_not_passed_through`（→raise）、`test_jwt_bearer_still_authenticates_with_pat_class_first`（→200）、`test_auth.py`/`test_auth_e2e.py` 401 回归全 GREEN |
| 3 | IDENT-03: McpToolView 基类 `IsAuthenticated`（fail-closed），无 `AllowAny` 残留，匿名→401 | ✓ VERIFIED | `mcp_tools/views.py:145-146` 基类 `authentication_classes=[AccessToken, CookieJWT]` + `permission_classes=[IsAuthenticated]`；grep 确认文件内 `AllowAny` 计数为 0；`handle_exception` 硬编码 401。测试 `test_missing_token_returns_error_code`（→401 + `authentication_failed`）GREEN |
| 4 | IDENT-04: `request.auth` 仍为 token；InteractionRun fingerprint 记录（含 JWT 路径 user 兜底） | ✓ VERIFIED | 成功分支保留 `request.auth=AccessToken`；`entry.py:72-76` `token_hash` 取值 + JWT 路径退化 `user:<id>`（WR-01 修复）。`test_interactions_ledger` 全 GREEN |
| 5 | IDENT-05: 已吊销/已过期 token 一律被拒 | ✓ VERIFIED | `authentication.py:83-88` `is_valid` 检查→DENIED run + `raise`。测试 `test_revoked_pat_rejected_through_chain`（→401）、`test_revoked_expired_denied_and_logged` GREEN |

**Score:** 5/5 truths verified

### Required Artifacts

| Artifact | Expected | Status | Details |
|----------|----------|--------|---------|
| `server/access_tokens/authentication.py` | owner 返回 + 前缀闸门 + authenticate_header + is_active 闸门 | ✓ VERIFIED | 全部存在，含 CR-01 修复（owner_inactive） |
| `server/friday/settings.py` | PAT-first DEFAULT_AUTHENTICATION_CLASSES | ✓ VERIFIED | `:277-280` PAT 类首位，附中文注释说明 Pitfall 1/2 |
| `server/mcp_tools/views.py` | fail-closed McpToolView 基类 | ✓ VERIFIED | `IsAuthenticated` + 显式 auth 类；无 `AllowAny` 残留 |
| `server/interactions/entry.py` | token_hash fingerprint + JWT 兜底 | ✓ VERIFIED | `:72-76` user:<id> 兜底（WR-01） |

### Key Link Verification

| From | To | Via | Status |
|------|----|-----|--------|
| `authentication.py` | `AccessToken.created_by` | `select_related('created_by')` + `return (created_by, token)` | ✓ WIRED |
| `settings.py` | `AccessTokenAuthentication` | DEFAULT_AUTHENTICATION_CLASSES first entry | ✓ WIRED |
| `mcp_tools/views.py` | `IsAuthenticated` / `CookieJWTAuthentication` | McpToolView base class | ✓ WIRED |
| `entry.py` | `request.auth.token_hash` / `user:<id>` | `begin_interaction_run` fingerprint | ✓ WIRED |

### Behavioral Spot-Checks (Test Suite)

| Behavior | Command | Result | Status |
|----------|---------|--------|--------|
| 全相位认证/身份/审计套件 | `uv run pytest tests/test_pat_identity.py tests/test_access_tokens.py tests/test_auth.py tests/test_auth_e2e.py tests/test_interactions_ledger.py tests/mcp_tools -q` | **88 passed, 75 warnings in 12.91s** | ✓ PASS |

### Requirements Coverage

| Requirement | Source Plan | Status | Evidence |
|-------------|-------------|--------|----------|
| IDENT-01 | 07-01/07-02 | ✓ SATISFIED | owner 身份返回 + RBAC + is_active 闸门，单元+集成测试 |
| IDENT-02 | 07-01/07-02 | ✓ SATISFIED | 前缀闸门 + PAT-first + authenticate_header，共存测试 |
| IDENT-03 | 07-01/07-03 | ✓ SATISFIED | McpToolView fail-closed，匿名→401 测试 |
| IDENT-04 | 07-02/07-03 | ✓ SATISFIED | request.auth=token + fingerprint（含 JWT 兜底） |
| IDENT-05 | 07-01/07-02 | ✓ SATISFIED | 吊销/过期→DENIED run + 401，端到端测试 |

无孤儿需求（REQUIREMENTS.md 仅 IDENT-01..05 映射 Phase 7，全部被 plan 声明覆盖）。

### Anti-Patterns Found

无 BLOCKER 级反模式。无未引用的 `TBD`/`FIXME`/`XXX` 债务标记于本相位改动文件。`entry.py` docstring 示例中的 `permission_classes = [AllowAny]` 为文档示例字符串（非 MCP 入口实际配置），MCP 入口已 fail-closed。

### Human Verification Required

#### 1. Web UI cookie-JWT 端到端登录（认证类重排后）

**Test:** 在真实浏览器中以 Web UI 走 cookie-JWT 登录（`access_token` HttpOnly cookie 主路径），然后访问受保护页面/接口。
**Expected:** 登录成功、受保护资源 200；PAT-first 重排后 cookie 优先的 access_token 仍被 `CookieJWTAuthentication` 正常接住，无回退。
**Why human:** 认证类全局重排为高 blast-radius 改动。自动化已覆盖 Bearer-header JWT、refresh cookie、logout 与站点级 401，但 `access_token` cookie-first 路径经重排链路的真实浏览器端到端登录未在本次验证中实跑。（风险评估：低——cookie 路径仅改变 token 读取来源，与认证类顺序正交，`get_header` 仍归一为同一 JWT 管线。）

### Gaps Summary

无功能性 gap。5/5 可观测真值在代码中验证落地，88 项测试全绿，CR-01（停用 owner 仍可认证）BLOCKER 已修复并加回归测试，WR-01/WR-02 已解。状态置为 `human_needed` 仅因一项浏览器级 Web UI cookie-JWT 登录建议人工确认（用户显式要求记录）。

---

_Verified: 2026-06-09T21:34:00Z_
_Verifier: Claude (gsd-verifier)_
