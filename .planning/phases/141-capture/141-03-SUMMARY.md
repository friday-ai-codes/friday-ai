---
phase: 141-capture
plan: "03"
subsystem: knowledge
tags: [django, capture, access-scope, git-url, idempotency]

requires:
  - phase: 141-capture
    provides: SessionCapture 模型、CaptureService 基础写入与唯一约束
provides:
  - Capture 仓库与项目授权挂钩状态机
  - SSH/HTTPS Git URL 等价匹配与多命中保护
  - IntegrityError 幂等回读的 first-write-wins 验收
affects: [142-capture-mcp, 143-capture-evaluation, 144-capture-recall]

tech-stack:
  added: []
  patterns:
    - 知识 access scope 与 ProjectMember 双重约束 Capture 外键写入
    - 挂钩失败保留 Capture 行并写入闭集 link_reason

key-files:
  created:
    - .planning/phases/141-capture/141-03-SUMMARY.md
  modified:
    - server/initiatives/services/capture_service.py
    - server/knowledge/access_scope.py
    - server/tests/initiatives/test_capture_service.py

key-decisions:
  - "显式 repository_id 优先，缺失时才按 normalize_git_url 生成有限变体查询。"
  - "Capture 外键写入除 knowledge access scope 外仍要求项目成员关系，public_org 只读可见性不放宽写入。"

patterns-established:
  - "挂钩失败不丢账：解析、歧义、未授权与项目不匹配均创建 Capture。"
  - "First-write-wins：唯一键冲突只回读既有行，不覆盖答案或挂钩原因。"

requirements-completed: [STORE-03, STORE-04]

duration: 10min
completed: 2026-08-28
---

# Phase 141 Plan 03: Capture 挂钩与幂等 Summary

**Capture 现可按显式仓库 ID 或 SSH/HTTPS 等价 URL 安全挂钩仓库与项目，失败路径仍持久化，并保持幂等首次写入内容。**

## Performance

- **Duration:** 10 分钟
- **Started:** 2026-08-28T07:39:31Z
- **Completed:** 2026-08-28T07:49:57Z
- **Tasks:** 2
- **Files modified:** 3

## Accomplishments

- 实现仓库优先的完整挂钩状态机，覆盖未解析、多命中、未授权、项目不匹配与 project-only。
- 使用 `resolve_allowed_repository_ids`、`resolve_allowed_project_ids` 和 `ProjectMember` 写权限约束，未授权关系不写 FK。
- 验证唯一约束冲突回读既有 Capture，重复提交不覆盖首次答案与挂钩原因。

## Task Commits

1. **Task 1: 仓库/项目挂钩状态机（STORE-04）** - `728420fc` (feat)
2. **Task 2: 幂等 first-write-wins（STORE-03）** - `4b61c8a6` (test)

## Files Created/Modified

- `server/initiatives/services/capture_service.py` - 仓库/项目解析、授权、关系校验与 FK 写入。
- `server/knowledge/access_scope.py` - 将 ProjectMember 可见项目映射回所属 Space 的仓库。
- `server/tests/initiatives/test_capture_service.py` - 加固首次写入与重复命中结果断言。

## Decisions Made

- `repository_id` 只要提供即禁止回退 `git_url`，非法、软删或不存在统一为 `repo_unresolved`。
- public_org 项目保持只读可见；Capture 关联写入仍要求项目成员身份，避免只读用户建立关系。

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] 修复 ProjectMember 项目无法映射仓库 scope**
- **Found during:** Task 1（仓库/项目挂钩状态机）
- **Issue:** `resolve_allowed_project_ids` 会返回 initiatives.Project UUID，但仓库 scope 只按 Space UUID 查询，项目成员无法访问其项目所属空间的仓库。
- **Fix:** 仓库 scope 同时按 Space id 和 `Space.projects` 映射允许项目，并保留 distinct 与 caller 收窄语义。
- **Files modified:** `server/knowledge/access_scope.py`
- **Verification:** `tests/knowledge/test_access_scope.py` 13 项与 Capture 计划用例全部通过。
- **Committed in:** `728420fc`

---

**Total deviations:** 1 auto-fixed（1 个 Rule 1）
**Impact on plan:** 修复直接保障 STORE-04 的授权挂钩语义，无额外功能扩张。

## Issues Encountered

- pytest 清理 PostgreSQL 测试库时报告仍有一个后台连接的警告；测试结果均通过，未影响断言。

## Known Stubs

None.

## User Setup Required

None - 无外部服务配置。

## Next Phase Readiness

- Phase 142 可直接通过 `CaptureService.persist` 暴露 MCP 写入入口。
- `link_reason` 闭集、授权 FK 与幂等返回标志已可供后续评估和回放使用。

## Self-Check: PASSED

- 已确认 `141-03-SUMMARY.md`、三个修改文件与任务提交 `728420fc`、`4b61c8a6` 存在。
- 计划级回归共 27 项通过；源码无禁止的项目反查、宽权限或延迟写入入口。

---
*Phase: 141-capture*
*Completed: 2026-08-28*
