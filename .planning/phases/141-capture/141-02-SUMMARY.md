---
phase: 141-capture
plan: 02
subsystem: database
tags: [django, capture, inv-6, redaction, structlog]

requires:
  - phase: 141-01
    provides: CaptureService RED 行为、INV-6 与观测契约
provides:
  - 独立 SessionCapture 账本模型与 0015 migration
  - CaptureService.persist 脱敏、unknown 归一、幂等与 project-only 核心写路径
  - normalize_git_url 共享仓库地址规范化入口
affects: [141-03, 141-04, CaptureService, SessionCapture]

tech-stack:
  added: []
  patterns: [INV-6 single writer, nullable SET_NULL ledger links, best-effort caller logging]

key-files:
  created:
    - server/initiatives/models/session_capture.py
    - server/initiatives/migrations/0015_session_capture.py
    - server/initiatives/services/capture_service.py
    - server/services/git_url.py
  modified:
    - server/initiatives/models/__init__.py
    - server/initiatives/services/__init__.py

key-decisions:
  - "Capture 幂等键固定为 initiated_by_user_id、session_id 与脱敏后 NFKC 问题哈希，重复写 first-write-wins。"
  - "141-02 仅解析 unanchored 与 project_only；仓库 URL、授权和 mismatch 状态机留给 141-03。"
  - "持久化 caller 日志只记录关联元数据，不复制 question、answer 或 git_url。"

patterns-established:
  - "SessionCapture 业务写入只允许经过 CaptureService.persist。"
  - "挂钩失败以 link_reason 表达，不能阻止独立账本落库。"

requirements-completed: [STORE-01, STORE-02, STORE-03, STORE-05, OBS-02]

duration: 7 min
completed: 2026-08-28
---

# Phase 141 Plan 02: Capture 持久化地基 Summary

**独立 SessionCapture 账本已支持脱敏、unknown 标量、稳定会话幂等与可空项目/仓库关联，并由 INV-6 CaptureService 单一写入。**

## Performance

- **Duration:** 7 min
- **Started:** 2026-08-28T07:30:38Z
- **Completed:** 2026-08-28T07:37:13Z
- **Tasks:** 2
- **Files modified:** 6

## Accomplishments

- 新增 `initiative_session_captures` 表，项目和仓库 FK 均为 `SET_NULL`，状态默认 `pending_eval`。
- 实现 `CaptureService.persist`：问答入库前脱敏、空标量归一为 `unknown`、缺失会话归一为 `unspecified`，重复提交返回原行且不覆盖答案。
- INV-6 守卫与核心 STORE 测试通过；caller 日志同时满足生命周期、脱敏和 best-effort 契约。
- 提取 `normalize_git_url`，统一 SSH→HTTPS、大小写、末尾斜杠与 `.git` 处理。

## Task Commits

1. **Task 1: SessionCapture 模型 + migration 0015 + 导出** - `49e754b5`（feat）
2. **Task 2: git_url helper + CaptureService 核心 persist + INV-6 变绿** - `35ea6708`（feat）

## Files Created/Modified

- `server/initiatives/models/session_capture.py` - Capture 状态、账本字段、索引与幂等约束。
- `server/initiatives/models/__init__.py` - 导出 `SessionCapture` 与状态枚举。
- `server/initiatives/migrations/0015_session_capture.py` - 创建独立 Capture 表与 `SET_NULL` 外键。
- `server/initiatives/services/capture_service.py` - INV-6 核心持久化、幂等和 caller 日志。
- `server/initiatives/services/__init__.py` - 导出 Capture 服务与结果类型。
- `server/services/git_url.py` - Git URL 共享规范化函数。

## Decisions Made

- 幂等哈希基于脱敏后的问题生成，避免凭证影响审计键并确保库内无原始密钥。
- `session_id` 缺失统一使用 `unspecified`，仍参与唯一约束。
- 本计划按边界只绑定合法成员的 project-only 场景；所有仓库请求先安全降级为 `repo_unresolved`。

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered

- 全仓 `makemigrations --check --dry-run` 检出既有 `codegraph` 索引重命名漂移；与本计划无关，未修改。`initiatives.0015` migration plan、Django system check 与计划文件 ruff 均通过。
- pytest teardown 偶发报告测试数据库仍有一个连接，但目标测试退出码为 0，全部断言通过。

## Known Stubs

- `server/initiatives/services/capture_service.py` 的仓库挂钩分支当前固定返回 `repo_unresolved`；这是计划明确的 141-02 最小状态，完整 URL、授权、歧义与项目仓库 mismatch 状态机由 141-03 落地。
- `server/initiatives/models/session_capture.py` 的 `branch_name` 默认空字符串是允许缺失的审计元数据，不是 UI 或数据源占位。

## TDD Gate Compliance

- RED 契约已由依赖计划 141-01 的 `0bf71276` 与 `793c4e49` 提交建立；本计划两个 GREEN 实现提交均在其后。

## Verification

- `uv run pytest tests/initiatives/test_capture_inv6_guard.py -x -q`：3 passed。
- 核心 `test_capture_service.py` 选择集：5 passed、9 deselected。
- `test_project_only_without_repo`：1 passed。
- `uv run pytest tests/initiatives/test_capture_observability.py -q`：5 passed。
- 六个计划实现文件 `ruff check`：通过。
- `uv run python manage.py check`：0 issues。
- `uv run python manage.py migrate initiatives 0015_session_capture --plan`：仅计划创建 `SessionCapture`。

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness

- 141-03 可在现有 `normalize_git_url` 与可空 FK 基础上补齐仓库解析、授权和 mismatch 状态机。
- 141-04 可登记已实现的 persist caller 事件并完成观测文档收口。

## Self-Check: PASSED

- 四个新增实现文件与 `141-02-SUMMARY.md` 均存在。
- Task commits `49e754b5`、`35ea6708` 均可在 git 历史中定位。
- 用户指定的无关测试、`skills` 状态与 debug 记录未被暂存、提交或修改。

---
*Phase: 141-capture*
*Completed: 2026-08-28*
