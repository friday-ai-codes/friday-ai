---
phase: 08-iso
plan: 01
subsystem: testing
tags: [pytest, async, drf, adrf, jwt, idor, access-control, conversation, isolation]

# Dependency graph
requires:
  - phase: 07-ident
    provides: "request.user = 真实 owner（PAT/JWT），owner 隔离可信前提"
provides:
  - "server/tests/test_conversation_isolation.py：25 路径 cross-user-denied(404) + owner-allowed + admin-no-bypass + created_by 落库/回填 + open-mode 回归"
  - "conftest fixtures：second_user / second_user_and_token / second_auth_headers / superuser_and_token / superuser_auth_headers"
  - "frozen_conversation_factory created_by 向后兼容透传探测"
affects: [08-02, 08-03, 08-04]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "RED-first 隔离脚手架：参数化 1:1 映射 RESEARCH 端点编号（#3-#25），任一遗漏=可见缺口"
    - "owner 注入探测 _conversation_has_created_by()：字段落地后 owner-scoped、未落地降级 owner-less（Wave 0 干净 RED）"
    - "回填迁移惰性 import（pkgutil 动态查找 0019）：集合阶段不因迁移缺失而 ImportError"

key-files:
  created:
    - server/tests/test_conversation_isolation.py
  modified:
    - server/tests/conftest.py

key-decisions:
  - "回填排序字段用 created_at（accounts/0005 与 accounts.User 实有字段），非 CONTEXT 草拟的 date_joined（解决 RESEARCH A2）"
  - "accounts/0006 partial unique index 约束「最多一个 superuser」→ 回填 earliest 用例仅建单个 superuser（最早=唯一）"
  - "owner-allowed 正向断言用 != 404（而非 == 200），精确捕捉过度收紧 gate（plan-checker 警告 #2）"
  - "越权对象级断言一律 == 404、list 级 == []，绝不接受 403（ISO-04 不泄漏存在性）"

patterns-established:
  - "隔离测试用 async ORM acreate + JWT Bearer（AsyncClient），跨用户 IDOR 复现"
  - "CROSS_USER_CASES 数据驱动 + _resolve_body 合法请求体填充，确保 owner gate 落地后由 404（非序列化 400）转 GREEN"

requirements-completed: []  # Wave 0 RED 脚手架：ISO-01..04 仅建测试，功能未实现，待 08-02/03/04 转 GREEN 后由对应 plan 标记完成

# Metrics
duration: 15min
completed: 2026-06-09
---

# Phase 8 Plan 01: 对话/会话用户隔离 Wave 0 RED 脚手架 Summary

**对 RESEARCH 全 25 个会话访问路径建立 1:1 映射的 cross-user-denied(404) RED 测试集（含 SSE 流前 404、list-scoping、owner-allowed 正向防误伤、created_by 落库/回填、admin-no-bypass、open-mode 回归），功能未实现故预期 RED。**

## Performance

- **Duration:** ~15 min
- **Completed:** 2026-06-09
- **Tasks:** 3
- **Files modified:** 2（1 created, 1 modified）

## Accomplishments

- 新增 `test_conversation_isolation.py`（37 测试用例），覆盖 ISO-01..04 + open-mode：
  - **ISO-04 全 25 路径**：`CROSS_USER_CASES` 参数化覆盖对象级 #3–#25（id 标注 RESEARCH 编号），逐条断言越权 `== 404`；list-scoping #13/#20 断言 `== []`；SSE #10′ 单列断言流打开前 HTTP 404；`test_404_indistinguishable` 断言越权与不存在响应一致。
  - **ISO-01**：`test_create_sets_owner`（创建落 `created_by`）+ 三个回填用例（earliest superuser / 无 superuser 留 null / 可逆）。
  - **ISO-02/03**：`test_list_only_owner`、`test_admin_no_bypass`（无 superuser bypass）。
  - **owner-allowed 正向**：6 条主路径（detail/runtime/patch/delete/stream/fork）断言 owner `!= 404`（plan-checker 警告 #2）。
  - **open-mode 回归**：未认证仍可访问 owner-less 会话。
- conftest 新增隔离测试 fixtures（second_user/二号 JWT/superuser JWT）+ `frozen_conversation_factory` 的 `created_by` 向后兼容透传探测；既有 `test_conversation_integration.py` 仍全绿（2 passed）。
- 当前 RED 分布符合预期：**27 failed / 10 passed**。

## Task Commits

1. **Task 1: conftest fixtures + created_by 透传** - `18b27753` (test)
2. **Task 2: RED ISO-01/02/03 + open-mode + 回填** - `899e2621` (test)
3. **Task 3: RED ISO-04 全 25 路径 + SSE/list-scoping/owner-allowed** - `beae9007` (test)

## Files Created/Modified

- `server/tests/test_conversation_isolation.py` (created) - 隔离 RED 测试全集：helpers（owner 可注入 async 创建 + 惰性回填迁移 loader）、fixtures（owner_and_token/owner_headers）、ISO-01..04 + open-mode + owner-allowed 用例。
- `server/tests/conftest.py` (modified) - 新增 second_user / second_user_and_token / second_auth_headers / superuser_and_token / superuser_auth_headers；`frozen_conversation_factory` 增加 `created_by` 字段存在性探测透传。

## Current RED/GREEN Status（Wave 0 预期）

**RED（27，功能未实现，Wave 2-4 落地后转 GREEN）：**
- `test_create_sets_owner`（created_by 字段未落地）
- 3× backfill（0019 迁移未落地 → ModuleNotFoundError）
- `test_list_only_owner` / `test_admin_no_bypass`（无 owner 过滤）
- `test_cross_user_denied` 21 参数中的 18 个（#3-#10、#12、#14-#19、#21-#23）+ `test_stream_cross_user_404` + `test_404_indistinguishable` + `test_list_scoping_coding`

**GREEN（10）：**
- `test_open_mode_unaffected`（开放模式回归保护，应始终 GREEN）
- `test_cross_user_denied[#11/#24/#25]`（Wave 0 即返 404：#11 无活跃 run；#24/#25 既有 `has_project_access` 跨用户已 404）
- 6× owner-allowed（owner 主路径 `!= 404`，防误伤保护，应始终 GREEN）

> 这些「已绿」用例并非缺陷：它们断言的安全属性（越权 404 / owner 不被误伤 / 开放模式不变）在 Wave 0 已成立，08-02..04 落地后仍须保持成立——属于回归护栏。

## Decisions Made

- **回填排序字段 = `created_at`**（解决 RESEARCH A2）：`accounts.User` 实有 `created_at`（无 `date_joined`），`accounts/0005` 既有回填即用 `order_by("created_at")`；08-02 的 0019 迁移应沿用 `order_by("created_at","id")`。
- **单 superuser 约束**：`accounts/0006_add_single_superuser_constraint` 以 partial unique index 限制最多一个 superuser，故 `test_backfill_assigns_earliest_superuser` 仅建单个 superuser（系统中「最早」即「唯一」）。
- **越权一律 404 / list 一律 []**：杜绝 403（ISO-04 防存在性枚举）。
- **owner-allowed 断言 `!= 404`**：精确捕捉「过度收紧 gate 把 owner 也 404」，而不锁死各端点具体成功码（stream 200 / delete 204 / fork 201 等）。

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] 回填 earliest 用例不能创建两个 superuser**
- **Found during:** Task 2（运行验证）
- **Issue:** 计划草案以「建两个 superuser 验证 earliest 排序」实现 `test_backfill_assigns_earliest_superuser`，但 `accounts/0006` 的 partial unique index 仅允许一个 superuser → setup 抛 `IntegrityError: UNIQUE constraint failed: users.is_superuser`，使该用例因 setup 崩溃而非「功能未实现」失败。
- **Fix:** 改为创建单个 superuser（系统约束下「最早」即「唯一」），并在 docstring 标注约束来源；用例现以 `ModuleNotFoundError`（0019 迁移缺失）干净 RED。
- **Files modified:** server/tests/test_conversation_isolation.py
- **Verification:** 重跑 `TestOwnerAssignment` → 4 failed，均为 ModuleNotFoundError / created_by 缺失（正确 RED 原因），无 IntegrityError。
- **Committed in:** `899e2621`（Task 2 commit）

---

**Total deviations:** 1 auto-fixed（1 bug）
**Impact on plan:** 修正使 RED 失败原因正确（功能未实现而非测试 setup 崩溃），无范围蔓延。

## Issues Encountered

- Shell cwd 在连续 `cd server` 命令间漂移导致一次 "file not found"；改用显式 `working_directory` 后正常。无代码影响。

## User Setup Required

None - 零新增依赖（pytest 栈已在），无外部服务配置。

## Next Phase Readiness

- 08-02 可据本测试集作为唯一验收：实现 `Conversation.created_by` FK（0018 AddField）+ 0019 RunPython 回填（`order_by("created_at","id")`，无 superuser 留 null，backwards 置 None）+ `ConversationService` owner-scoped 取数，使 ISO-01 用例转 GREEN。
- 08-03/08-04 实现 owner gate（统一 404、SSE 流前 404、去 superuser bypass）后，剩余 cross-user-denied 用例应全数转 GREEN，同时 owner-allowed 与 open-mode 护栏须保持 GREEN。
- **注意**：`test_cross_user_denied[#11 interrupt]` 在无活跃 run 时即 404，无法区分 owner gate 是否真正生效——08-03 实现 interrupt owner gate 时建议补「活跃 run 下越权 404」强用例（本 plan 未覆盖，记录于此）。

## Self-Check: PASSED

- FOUND: `.planning/phases/08-iso/08-01-SUMMARY.md`
- FOUND: `server/tests/test_conversation_isolation.py`
- FOUND commits: `18b27753`, `899e2621`, `beae9007`
- Verify: `uv run pytest tests/test_conversation_isolation.py -q --co` → 37 collected; full run → 27 failed / 10 passed（预期 Wave 0 RED）；`tests/test_conversation_integration.py` → 2 passed（fixture 增量未破坏既有套件）。

---
*Phase: 08-iso*
*Completed: 2026-06-09*
