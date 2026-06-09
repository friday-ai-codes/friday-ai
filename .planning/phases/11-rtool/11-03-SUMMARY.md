---
phase: 11-rtool
plan: 03
subsystem: infra
tags: [rtool, runner, golang, docker-executor, env-passthrough, pat-injection]

# Dependency graph
requires:
  - phase: 11-01
    provides: "runner RED 用例 TestBuildContainerEnv_RemoteTools（FRIDAY_TASK_REMOTE_TOOLS 前缀契约）"
provides:
  - "runner buildContainerEnv 注入 FRIDAY_TASK_REMOTE_TOOLS（前缀修复，TaskConfig 可读）"
  - "USER_TOKEN/TOOLS_ENDPOINT 经既有 metadata env_ TrimPrefix 通道透传（零新增 Go 解析）"
affects:
  - "11-04 server dispatch（注入 env_FRIDAY_TASK_USER_TOKEN/TOOLS_ENDPOINT metadata 落地后全链路打通）"

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "单源 payload remote_tools → 同值双键（FRIDAY_REMOTE_TOOLS + FRIDAY_TASK_REMOTE_TOOLS），仅前缀差异"
    - "metadata env_ TrimPrefix 透传敏感值，runner 不解析/不记录"

key-files:
  created: []
  modified:
    - runner/internal/docker/executor.go

key-decisions:
  - "FRIDAY_TASK_REMOTE_TOOLS 复用函数顶部既有 remoteTools JSON，与旧 FRIDAY_REMOTE_TOOLS 同源同值，仅前缀不同"
  - "USER_TOKEN/TOOLS_ENDPOINT 零新增 Go 代码——server 经 metadata env_ 注入，既有 TrimPrefix + s != \"\" 守卫自动透传"
  - "保留旧 FRIDAY_REMOTE_TOOLS 行（兼容既有读者，不删）"

patterns-established:
  - "Pitfall 2 前缀错位修复：TaskConfig 只认 FRIDAY_TASK_ 前缀，旧顶层键并存不冲突"

requirements-completed: [RTOOL-03]

# Metrics
duration: 4min
completed: 2026-06-10
---

# Phase 11 Plan 03: runner env 透传修复 Summary

**runner buildContainerEnv 新增 FRIDAY_TASK_REMOTE_TOOLS（前缀修复），使 task TaskConfig 可读 remote_tools；PAT/工具端点经既有 metadata env_ 通道透传，runner 日志零 env 值泄漏。**

## Performance

- **Duration:** 4 min
- **Started:** 2026-06-10T02:18:00Z
- **Completed:** 2026-06-10T02:22:00Z
- **Tasks:** 1
- **Files modified:** 1

## Accomplishments
- `buildContainerEnv` 在 `FRIDAY_TASK_` 块新增 `FRIDAY_TASK_REMOTE_TOOLS`，与旧 `FRIDAY_REMOTE_TOOLS` 同源同值（Pitfall 2 前缀错位修复），TaskConfig 的 `FRIDAY_TASK_` 前缀现可读到 remote_tools。
- `FRIDAY_TASK_USER_TOKEN` / `FRIDAY_TASK_TOOLS_ENDPOINT` 经既有 `metadata env_` TrimPrefix 循环（含 `s != ""` 空值守卫）自动透传，零新增 Go 解析逻辑。
- 11-01 runner RED 用例 `TestBuildContainerEnv_RemoteTools` 转 GREEN；既有 `TestBuildContainerEnvSeparatesTaskModeAndTaskType` 与 `..._NoPATNoEmptyKey` 仍 PASS。
- runner zerolog 不打印任何 env 值（仅 task_id/container_id/answer_endpoint，PAT 不进 Go 日志，T-11-08）。

## Task Commits

Each task was committed atomically:

1. **Task 1: executor.go — buildContainerEnv 新增 FRIDAY_TASK_REMOTE_TOOLS（前缀修复）** - `218e83fa` (fix)

## Files Created/Modified
- `runner/internal/docker/executor.go` - `buildContainerEnv` 新增一行 `"FRIDAY_TASK_REMOTE_TOOLS=" + string(remoteTools)`（复用函数顶部既有 `remoteTools` JSON）

## Decisions Made
- 单源双键：`FRIDAY_TASK_REMOTE_TOOLS` 与旧 `FRIDAY_REMOTE_TOOLS` 复用同一 `json.Marshal(task.Payload["remote_tools"])` 结果，仅前缀不同；旧键保留兼容既有读者。
- USER_TOKEN/TOOLS_ENDPOINT 不新增 Go 代码，复用既有 `env_` TrimPrefix 透传通道（含空值守卫，向后兼容）。

## Deviations from Plan

None - plan executed exactly as written.

## Verification

| 命令 | 结果 |
|------|------|
| `cd runner && go test ./internal/docker/...` | ok (PASS，含新 + 既有用例) |
| `cd runner && gofmt -l internal/docker/` | 无输出（格式合规） |
| `cd runner && go build ./...` | 编译通过 |
| `rg "Str\(" runner/internal/docker/executor.go` | 仅 task_id/container_id/answer_endpoint，无 env 值打印 |

## Issues Encountered
None.

## User Setup Required
None - no external service configuration required.

## Threat Flags

无新增安全面。本 plan 落实 threat register：
- T-11-08（zerolog 打印 env 值）→ mitigate：未新增任何打印 env 值的 log，现状仅 log task_id/container_id（保持）。
- T-11-09（前缀错位致 remote_tools 永远空）→ mitigate：新增 FRIDAY_TASK_REMOTE_TOOLS 同源映射，test 守卫。
- T-11-10（注入空 FRIDAY_TASK_USER_TOKEN）→ mitigate：复用既有 `s != ""` 守卫，空值不注入。

## Next Phase Readiness
- runner 这一跳打通。全链路闭环待 11-04（server dispatch 注入 `env_FRIDAY_TASK_USER_TOKEN` / `env_FRIDAY_TASK_TOOLS_ENDPOINT` metadata + `_resolve_user_pat`）落地。

## Self-Check: PASSED

- 修改文件存在：`runner/internal/docker/executor.go`（含 `FRIDAY_TASK_REMOTE_TOOLS`）。
- 提交存在：`218e83fa`（runner fix）。

---
*Phase: 11-rtool*
*Completed: 2026-06-10*
