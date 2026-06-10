---
phase: 10-mcpb
plan: 02
subsystem: storage
tags: [django, model, migration, tool-binding, access-token, cascade, unique-together]

# Dependency graph
requires:
  - phase: 10-mcpb (10-01)
    provides: make_tool_binding fixture（ToolTokenBinding 缺失时 skip）+ RED 锁名测试
  - phase: 07-auth
    provides: access_tokens.AccessToken（绑定 FK 目标）
provides:
  - tools.ToolTokenBinding 模型（user↔access_token↔remote_tool 持久绑定）
  - tools/migrations/0003_tooltokenbinding.py（CreateModel）
affects: [10-03, 11-inject]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "三 FK on_delete=CASCADE：令牌/工具/用户删除即级联清理绑定（无悬挂指向）"
    - "unique_together(user, remote_tool)：DB 层每用户每工具唯一，重复绑定靠 10-03 upsert 收敛"
    - "绑定表只引用 access_token FK，绝不复制 token_hash/明文（无泄漏面）"

key-files:
  created:
    - server/tools/migrations/0003_tooltokenbinding.py
  modified:
    - server/tools/models.py

key-decisions:
  - "[10-02] related_name 三件套与 conftest/测试契约对齐：user→tool_token_bindings、access_token→tool_bindings、remote_tool→token_bindings"
  - "[10-02] 迁移仅 CreateModel 无 RunPython（RESEARCH：无历史数据，零回填）"

patterns-established:
  - "存储地基纯 schema：模型 + CreateModel 迁移，正反向可逆，无数据迁移耦合"

requirements-completed: [MCPB-01, MCPB-03]  # 按 plan frontmatter 标记；存储地基已就位，功能性 GREEN（端点/UI）由 10-03/10-04 收口

# Metrics
duration: 6min
completed: 2026-06-10
---

# Phase 10 Plan 02: ToolTokenBinding 模型 + 迁移 Summary

**在 tools app 新增 `ToolTokenBinding`（user/access_token/remote_tool 三 FK 全 CASCADE + unique(user, remote_tool)）并生成 CreateModel 迁移 0003，为 MCPB-01 绑定入库唯一性与 MCPB-03 owner 管理建立存储地基；make_tool_binding fixture 自此停止 skip**

## Performance

- **Duration:** ~6 min
- **Completed:** 2026-06-10
- **Tasks:** 2
- **Files modified:** 2（1 改 + 1 新建）

## Accomplishments

- `ToolTokenBinding` 模型追加于 `server/tools/models.py`：三 FK（`accounts.User` / `access_tokens.AccessToken` / `tools.RemoteTool`）全部 `on_delete=CASCADE`，`created_at`(auto_now_add)/`updated_at`(auto_now)，`Meta` 含 `db_table="tool_token_bindings"`、`unique_together=(("user","remote_tool"),)`、`ordering=["-created_at"]`。
- 模型不含任何明文/hash 字段，绑定仅经 `access_token` FK 引用令牌（T-10-05 缓解）。
- `0003_tooltokenbinding.py` 仅 `CreateModel`，无 RunPython 回填；dependencies 自动包含 `tools.0002` + `access_tokens.0002` + `AUTH_USER_MODEL`（满足三 FK）。

## Task Commits

1. **Task 1: ToolTokenBinding 模型（tools/models.py 追加）** — `a8fad182` (feat)
2. **Task 2: 迁移 0003_tooltokenbinding（CreateModel）** — `d40b5b00` (feat)

## Files Created/Modified

- `server/tools/models.py` — 末尾追加 `class ToolTokenBinding`（仅新增，未改 RemoteTool 语义）。
- `server/tools/migrations/0003_tooltokenbinding.py` — CreateModel 迁移，正反向可用。

## Verification Results

- **模型自检**（Task 1 verify）→ `ok`：五字段齐备、`unique_together==(("user","remote_tool"),)`、三 FK CASCADE。
- **`migrate tools`** → `Applying tools.0003_tooltokenbinding... OK`（正向成功；CreateModel 默认可逆，可 `migrate tools 0002` 回滚）。
- **`makemigrations --check --dry-run tools`** → `No changes detected in app 'tools'`（模型/迁移一致，无 schema 漂移）。
- **`pytest tests/test_tool_bindings.py -q`** → **6 failed, 1 passed**（10-01 时为 9 failed / 1 passed / 2 skipped）。关键进展：原依赖 `make_tool_binding` 播种的 2 条用例（`test_list_owner_isolation` / `test_unbind_and_cross_user_404`）**不再 skip**——fixture 因模型落地开始真实播种，现因绑定端点未实现而 404 RED。所有剩余 failure 均为 10-03 待建端点（404≠期望码），属预期 RED。

## RED → 进展说明

本 plan 是 Storage 层，不提供端点，故 `test_tool_bindings.py` 仍整体 RED——但 RED 性质从「模型缺失（skip/collection）」推进到「端点缺失（404）」，证明存储地基已就位：
- 2 条 owner-隔离/越权用例从 **skipped → 运行**（make_tool_binding 停止 skip）。
- 端点行为类用例（upsert/builtin 拒绝/bindable/无明文）待 10-03 端点落地后转 GREEN。
- `test_bind_others_token_rejected` 维持 1 passed（越权引用断言 ≥400 成立）。

## Decisions Made

- `related_name` 三件套严格对齐 10-01 conftest 与测试契约：`user→tool_token_bindings`、`access_token→tool_bindings`、`remote_tool→token_bindings`，避免反查名冲突。
- 迁移仅 `CreateModel`，遵循 RESEARCH「无历史数据零回填」locked decision，不手写任何 RunPython。

## Deviations from Plan

None - plan executed exactly as written.

## Known Stubs

无。本 plan 为纯 schema 落地；端点（10-03）/前端（10-04）的「未实现」由 test_tool_bindings.py 预期 RED 表达，已在上方说明各用例转 GREEN 归属。

## Threat Mitigations Applied

- **T-10-04**（重复绑定歧义）→ `unique_together(user, remote_tool)` DB 约束就位。
- **T-10-05**（绑定表落明文/hash）→ 模型零明文/hash 字段，仅 access_token FK。
- **T-10-06**（悬挂指向）→ 三 FK 全 `on_delete=CASCADE`。

## Issues Encountered

None.

## Next Phase Readiness

- 10-03 可直接基于 `ToolTokenBinding` 构建 list/bindable/upsert/unbind 端点与序列化器，转 test_tool_bindings.py 为 GREEN。
- Phase 11 容器注入可据 (user, remote_tool)→access_token 映射选令牌。
- 无阻塞项。

## Self-Check: PASSED

- Files: server/tools/models.py（含 `class ToolTokenBinding`）/ server/tools/migrations/0003_tooltokenbinding.py — all FOUND.
- Commits: a8fad182 / d40b5b00 — all FOUND.

---
*Phase: 10-mcpb*
*Completed: 2026-06-10*
