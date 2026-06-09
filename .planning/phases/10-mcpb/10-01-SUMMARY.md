---
phase: 10-mcpb
plan: 01
subsystem: testing
tags: [pytest, vitest, pat, owner-isolation, tool-binding, remote-tool, nyquist, red]

# Dependency graph
requires:
  - phase: 07-auth
    provides: AccessTokenAuthentication（PAT→owner）+ make_access_token fixture
  - phase: 10-mcpb (research/validation)
    provides: 绑定/执行端点契约 + Wave 0 测试映射
provides:
  - conftest fixtures make_remote_tool（source/is_active 参数化）+ make_tool_binding（模型缺失优雅 skip）
  - 后端 RED 测试 test_tool_bindings.py（绑定 CRUD owner 隔离 + 不泄漏明文/hash）
  - 后端 RED 测试 test_remote_tool_execute.py（PAT fail-closed + 审计指纹）
  - 前端 RED spec ToolBindingSettings.spec.ts（绑定 UI 行为锁名）
affects: [10-02, 10-03, 10-04]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "RED-first 锁名测试：硬编码 URL 不 import 未落地 views → 端点 404 即 RED 而非 collection error"
    - "前向兼容 fixture：make_tool_binding 用 importorskip + getattr 守卫，模型缺失 pytest.skip"
    - "无明文断言：用 make_access_token 真实 plaintext 子串做 `not in resp.content` + 断言无 token_hash 键"

key-files:
  created:
    - server/tests/test_tool_bindings.py
    - server/tests/test_remote_tool_execute.py
    - web/src/components/toolBindings/__tests__/ToolBindingSettings.spec.ts
  modified:
    - server/tests/conftest.py

key-decisions:
  - "[10-01] 跨用户 owner 隔离用例经 ORM 工厂 make_tool_binding(second_user,...) 播种他人绑定（make_access_token 仅为主用户铸令牌，create 序列化器拒绝跨用户令牌引用）"
  - "[10-01] 前端绑定 API client 不引用 /tools/execute/（PAT-only 容器回调）；浏览器仅 list/bindable/upsert/unbind"
  - "[10-01] 无明文断言用真实 plaintext 子串 + 断言无 token_hash 键（T-10-01）；指纹只验证 token_hash 作 InteractionRun fingerprint"

patterns-established:
  - "Wave 0 RED 脚手架：fixture 前向兼容 skip + 硬编码 URL 避免 collection error + 锁名安全契约用例先行"

requirements-completed: []  # Wave 0 验证脚手架，需求由 10-02/10-03/10-04 实现后转 GREEN 才算交付

# Metrics
duration: 10min
completed: 2026-06-10
---

# Phase 10 Plan 01: Wave 0 RED 验证脚手架 Summary

**为 MCPB-01/02/03 + RTOOL-01 钉死可执行安全契约：conftest 两个工厂 fixture + 后端两份 RED 测试（绑定 owner 隔离/无明文 + PAT 执行 fail-closed/审计）+ 前端绑定 UI 行为 spec，全部初始 RED**

## Performance

- **Duration:** ~10 min
- **Completed:** 2026-06-10
- **Tasks:** 3
- **Files modified:** 4（1 改 + 3 新建）

## Accomplishments
- `make_remote_tool` 工厂 fixture：source/is_active 参数化、唯一 name，直接消费既有 `tools.RemoteTool`。
- `make_tool_binding` 工厂 fixture：`importorskip` + `getattr` 守卫，`ToolTokenBinding`（10-02 落地）缺失时 `pytest.skip` 而非 ImportError。
- `test_tool_bindings.py`（7 用例）：upsert 换令牌、builtin 拒绝、跨用户令牌引用拒绝、owner 隔离 list、unbind 越权 404、无明文/hash 泄漏、bindable 过滤(mcp/skill+active)。
- `test_remote_tool_execute.py`（5 用例）：PAT happy 200、匿名 401、吊销 401、未知工具 ok:false（not_found）、审计 InteractionRun(fingerprint=token_hash)。
- `ToolBindingSettings.spec.ts`（5 用例）：列出 mcp/skill 工具、下拉只列 valid 令牌、bind 调 store.upsert、unbind 调 store.unbind、不渲染明文。

## Task Commits

1. **Task 1: conftest fixtures make_remote_tool + make_tool_binding** — `85cb6564` (test)
2. **Task 2: 后端 RED 测试 test_tool_bindings.py + test_remote_tool_execute.py** — `12fb8d87` (test)
3. **Task 3: 前端 RED spec ToolBindingSettings.spec.ts** — `30f34f11` (test)

## Files Created/Modified
- `server/tests/conftest.py` — 新增 `make_remote_tool` / `make_tool_binding` 工厂 fixtures（仅追加，不改既有语义）。
- `server/tests/test_tool_bindings.py` — 绑定 CRUD owner 隔离 + 不泄漏明文锁名测试（MCPB-01/03）。
- `server/tests/test_remote_tool_execute.py` — PAT 执行端点 fail-closed + 审计锁名测试（RTOOL-01/MCPB-02）。
- `web/src/components/toolBindings/__tests__/ToolBindingSettings.spec.ts` — 绑定管理 UI 行为锁名 spec（mock store）。

## RED Status（预期初始红）

实现代码（10-02 模型 / 10-03 端点 / 10-04 前端）尚未落地，测试 **预期 RED**：

**后端** `uv run pytest tests/test_tool_bindings.py tests/test_remote_tool_execute.py -q` → **9 failed, 1 passed, 2 skipped**，无 collection/import error：
- 9 failed：绑定/执行端点缺失（404 ≠ 期望码）→ RED（intended）。
- 1 passed：`test_bind_others_token_rejected`（404 ≥ 400，越权引用断言成立；`ToolTokenBinding` 缺失故跳过落库计数 → 偶然 PASS，符合 plan 预期）。
- 2 skipped：`test_list_owner_isolation` / `test_unbind_and_cross_user_404`（依赖 `make_tool_binding` 播种，`ToolTokenBinding` 未落地 → 优雅 skip）。

**回归** `uv run pytest tests/test_pat_identity.py -q` → **8 passed**（既有 fixtures 未被破坏）。

**前端** `pnpm vitest run src/components/toolBindings` → **1 test file failed**：`import` 指向 10-04 待建组件（`ToolBindingSettings.vue` / `ToolBindDialog.vue` / `ToolBindingTable.vue`）解析失败即 RED（intended，per plan「import 组件失败即 RED」）。无 JS 语法错误。

10-02/10-03 实现模型与端点后后端转 GREEN；10-04 实现组件/store 后前端转 GREEN。

## Decisions Made
- 跨用户 owner 隔离用例经 ORM 工厂 `make_tool_binding(second_user, ...)` 播种他人绑定（plan-checker 修复）：`make_access_token` 仅为主用户铸令牌，create 序列化器拒绝跨用户令牌引用，故二号用户无法经 API 绑定，必须 ORM 直接播种。
- 二号用户令牌经 test-local `_mint_token(owner)` helper 直接 ORM 铸造（`make_access_token` 不支持任意 owner）。
- 前端绑定 spec 不涉及 `/tools/execute/`（PAT-only 容器回调）；浏览器 store 仅 list/bindable/upsert/unbind（plan-checker 修复）。
- 执行端点 execute_tool 桩用 `monkeypatch.setattr("tools.views.execute_tool", _stub, raising=False)`，10-02 前 `tools.views` 无该符号也不报错。

## Deviations from Plan

None - plan executed exactly as written（含两条 plan-checker 修复已在测试中落实）。

## Known Stubs

无生产代码 stub。本 plan 仅产出测试脚手架，所有「未实现」状态由预期 RED/skip 表达，并在上方 RED Status 明确标注由 10-02/10-03/10-04 转 GREEN。

## Issues Encountered
None.

## Next Phase Readiness
- `make_remote_tool` / `make_tool_binding` 可被 10-02/10-03 直接消费；`make_tool_binding` 在 `ToolTokenBinding` 落地后自动从 skip 转为可播种。
- 后端 12 条 + 前端 5 条锁名用例就位，为 10-02（模型）/10-03（端点）/10-04（前端）提供红→绿可度量目标。
- 无阻塞项。

## Self-Check: PASSED

- Files: test_tool_bindings.py / test_remote_tool_execute.py / ToolBindingSettings.spec.ts / 10-01-SUMMARY.md — all FOUND.
- Commits: 85cb6564 / 12fb8d87 / 30f34f11 — all FOUND.

---
*Phase: 10-mcpb*
*Completed: 2026-06-10*
