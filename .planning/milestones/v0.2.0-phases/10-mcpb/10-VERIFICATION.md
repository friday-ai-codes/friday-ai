---
phase: 10-mcpb
verified: 2026-06-10T01:25:00Z
status: human_needed
score: 4/4 must-haves verified
overrides_applied: 0
human_verification:

  - test: "浏览器端绑定流程：登录 → 个人资料页（profile）→「工具令牌绑定」卡片 → 为某 mcp/skill 工具选一把有效令牌绑定 → 刷新后绑定仍在 → 换绑另一令牌 → 解绑（二次确认）"
    expected: "卡片渲染可绑定 mcp/skill 工具行；绑定下拉仅出现 is_valid 令牌；绑定/换绑/解绑后列表即时更新且持久（刷新不丢）；任何位置都不出现完整 friday_pat_ 明文"
    why_human: "端到端 UI 用户流（需运行 server+web、真实登录与令牌），视觉与持久化只能由人工浏览器验证；自动化仅覆盖到组件 spec（mock store）与后端 API 契约层"
audit_acknowledged:
  milestone: v0.25.0
  at: 2026-08-31
  status: human_needed
---

# Phase 10: MCP 绑定用户令牌 + RemoteTool 执行端点 Verification Report

**Phase Goal:** 用户能把自己的访问令牌持久绑定给 skill/mcp，被绑定的工具以令牌所有者身份与权限执行；提供经令牌认证、按工具 name 执行的 RemoteTool 端点供容器回调
**Verified:** 2026-06-10T01:25:00Z
**Status:** human_needed
**Re-verification:** No — initial verification

## Goal Achievement

### Observable Truths

| # | Truth | Status | Evidence |
| --- | --- | --- | --- |
| 1 | 用户能把某个访问令牌持久绑定给 skill/mcp（绑定关系入库） | ✓ VERIFIED | `ToolTokenBinding` 模型（`server/tools/models.py:37-69`，三 FK CASCADE + `unique_together(user, remote_tool)`）+ 迁移 `0003_tooltokenbinding.py`；`ToolTokenBindingViewSet.acreate` upsert（`views.py:57-89`，`aupdate_or_create` + `IntegrityError` 兜底）；`test_upsert_rebind_updates_token` / `test_upsert_integrity_error_resolves_to_update` PASS |
| 2 | 被绑定的 skill/mcp 调用以令牌所有者身份与权限执行 | ✓ VERIFIED (Phase 11 deferral noted) | 执行端点经 PAT 认证 → `request.user`=owner（`AccessTokenAuthentication`）；审计指纹=`token_hash`（`entry.py:72`，`begin_interaction_run`）；绑定表持久化 tool→token 映射供 Phase 11 容器注入。**已记录范围内 gap**：`execute_tool(name, args)` 本期不接收 user 上下文、执行端点不做绑定强校验（CONTEXT-locked 决策 + RESEARCH Open Q1，REVIEW WR-01 ACKNOWLEDGED）；`test_execute_records_run`（fingerprint=token_hash）PASS |
| 3 | 用户能查看并解除自己的绑定 | ✓ VERIFIED | `get_queryset(user=request.user)` owner 隔离（`views.py:48-55`）；越权 delete → 404；前端 `ToolBindingSettings.vue` + `ToolBindingTable.vue` 解绑（二次确认）；`test_list_owner_isolation` / `test_unbind_and_cross_user_404` PASS |
| 4 | 存在经令牌认证、按 name 执行的 RemoteTool 端点（auth=AccessToken+IsAuthenticated），匿名/无效令牌被拒 | ✓ VERIFIED | `RemoteToolExecuteView`（`views.py:108-158`，`authentication_classes=[AccessTokenAuthentication]` + `IsAuthenticated`，`handle_exception` → 401 不降级）；挂载 `/api/tools/execute/`（`urls.py:20` + `friday/urls.py:58`）；审计 run 收尾（`arecord_tool_call` + COMPLETED/ERROR 终态）；`test_anonymous_401` / `test_revoked_pat_401` / `test_pat_execute_ok` / `test_unknown_tool_ok_false` / `test_execute_finalizes_run` / `test_execute_error_finalizes_run_error` PASS |

**Score:** 4/4 truths verified

### Required Artifacts

| Artifact | Expected | Status | Details |
| --- | --- | --- | --- |
| `server/tools/models.py` | ToolTokenBinding 模型 | ✓ VERIFIED | 三 FK 全 CASCADE + unique(user, remote_tool)，零明文/hash 字段 |
| `server/tools/migrations/0003_tooltokenbinding.py` | CreateModel 迁移 | ✓ VERIFIED | 仅 CreateModel，无 RunPython；`pytest` 迁移应用成功（61 passed） |
| `server/tools/serializers.py` | 5 序列化器 | ✓ VERIFIED | 白名单（id/name/prefix/suffix/is_valid），validate_access_token 归属+有效性，validate_remote_tool source/active |
| `server/tools/views.py` | 3 视图 | ✓ VERIFIED | ViewSet owner 隔离+upsert、BindableToolsView 过滤、ExecuteView fail-closed+审计收尾 |
| `server/tools/urls.py` | 3 路由 | ✓ VERIFIED | bindings/ + bindable/ + execute/ |
| `server/friday/urls.py` | /api/tools/ 挂载 | ✓ VERIFIED | `path("tools/", include("tools.urls"))`（line 58） |
| `web/src/api/toolBindings.ts` | list/bindable/upsert/unbind | ✓ VERIFIED | 相对 `/tools/...`，零 `/tools/execute` 引用 |
| `web/src/stores/toolBindings.ts` | useToolBindingStore | ✓ VERIFIED | 元数据-only 缓存，无明文驻留 |
| `web/src/components/toolBindings/*` | Settings/Table/Dialog | ✓ VERIFIED | 三组件，下拉仅 is_valid 令牌，仅渲染 prefix…suffix 指纹 |
| `web/src/pages/profile.vue` | 绑定卡片 | ✓ VERIFIED | import + `<ToolBindingSettings />`（line 11 / 278） |

### Key Link Verification

| From | To | Via | Status | Details |
| --- | --- | --- | --- | --- |
| RemoteToolExecuteView | tools.executor.execute_tool | `await execute_tool(name, args)` | ✓ WIRED | `views.py:30` 顶层 import + `:137` 调用 |
| ToolTokenBindingViewSet.get_queryset | ToolTokenBinding | `filter(user=request.user)` | ✓ WIRED | `views.py:52` |
| friday/urls.py | tools.urls | `include("tools.urls")` | ✓ WIRED | `friday/urls.py:58` |
| ExecuteView | begin_interaction_run | `token_fingerprint=token_hash` | ✓ WIRED | `entry.py:72` |
| ToolBindDialog | useAccessTokenStore | `tokens.filter(is_valid)` | ✓ WIRED | `ToolBindDialog.vue:43-45` |
| profile.vue | ToolBindingSettings.vue | import + render | ✓ WIRED | `profile.vue:11,278` |

### Behavioral Spot-Checks

| Behavior | Command | Result | Status |
| --- | --- | --- | --- |
| 后端绑定+执行+回归 | `uv run pytest tests/test_tool_bindings.py tests/test_remote_tool_execute.py tests/test_pat_identity.py tests/mcp_tools -q` | 61 passed, 0 failed | ✓ PASS |
| 前端绑定 spec | `pnpm vitest run src/components/toolBindings` | 5 passed | ✓ PASS |
| 前端类型检查 | `pnpm vue-tsc --noEmit` | exit 0, 清白 | ✓ PASS |

### Requirements Coverage

| Requirement | Source Plan | Description | Status | Evidence |
| --- | --- | --- | --- | --- |
| MCPB-01 | 10-02/10-03/10-04 | 把令牌持久绑定给 skill/mcp（入库） | ✓ SATISFIED | 模型+upsert ViewSet+bindable 过滤+前端 UI；锁名用例全绿 |
| MCPB-02 | 10-03 | 被绑定调用以令牌所有者身份执行 | ✓ SATISFIED (scope-bound) | 执行端点 request.user=owner + 审计指纹=token_hash；绑定表记录 tool→token 供 Phase 11；execute_tool 无 user ctx 为已记录 Phase 11 gap |
| MCPB-03 | 10-03/10-04 | 查看并解除自己的绑定 | ✓ SATISFIED | owner 隔离 list/delete + 前端解绑；test_list_owner_isolation / test_unbind_and_cross_user_404 |
| RTOOL-01 | 10-03 | 经令牌认证、按 name 执行的端点 | ✓ SATISFIED | RemoteToolExecuteView PAT fail-closed + 审计收尾；匿名/吊销 401 |

### Anti-Patterns Found

| File | Line | Pattern | Severity | Impact |
| --- | --- | --- | --- | --- |
| — | — | 无明文/hash 泄漏、无未引用 TBD/FIXME 调试标记、无 stub | ℹ️ Info | `BoundTokenSerializer` 白名单零 token_hash；`rg friday_pat_` 仅命中测试 mock。"Phase 11 gap" 注释为有意范围声明（CONTEXT-locked），非未审计债务 |

### Human Verification Required

#### 1. 浏览器端绑定全流程

**Test:** 登录 → 个人资料页 →「工具令牌绑定」卡片 → 为某 mcp/skill 工具从下拉选一把有效令牌绑定 → 刷新页面 → 换绑另一把令牌 → 解绑（二次确认）。
**Expected:** 卡片渲染可绑定 mcp/skill 工具行；下拉仅列 is_valid 令牌；绑定/换绑/解绑即时更新且持久（刷新不丢）；全程不出现完整 `friday_pat_` 明文。
**Why human:** 端到端 UI 用户流需运行 server+web、真实登录与令牌，视觉呈现与持久化只能人工浏览器验证；自动化仅覆盖组件 spec（mock store）与后端 API 契约层。

### Gaps Summary

无阻塞性 gap。全部 4 条 ROADMAP Success Criteria 与 4 条需求（MCPB-01/02/03 + RTOOL-01）在代码与测试层均已落实：后端 61 passed、前端 5 passed、typecheck 清白。

唯一范围内边界：MCPB-02 的「容器内以令牌所有者身份真正执行」在本期通过 (a) 执行端点 PAT→owner 身份 + 审计指纹=token_hash，与 (b) 绑定表持久化 tool→token 映射 两者达成；`execute_tool` 接收 user 上下文与执行端点的绑定强校验是 **CONTEXT-locked 的 Phase 11 deferral**（RESEARCH Open Q1、REVIEW WR-01 ACKNOWLEDGED），不属 Phase 10 缺陷。运营者须知：在已交付状态下，绑定为 advisory 元数据，尚非执行期授权边界（Phase 11 收口）。

唯一待人工项为浏览器端绑定 UI 全流程（见上），因此状态判定为 human_needed。

---

_Verified: 2026-06-10T01:25:00Z_
_Verifier: Claude (gsd-verifier)_
