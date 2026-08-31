---
phase: 145-cursor-claude-code
plan: "02"
subsystem: hooks
tags: [python-stdlib, claude-code, session-capture, fail-soft, pytest]
requires:
  - phase: 145-cursor-claude-code
    plan: "01"
    provides: 双宿主可见问答采集 RED 合同与 HTTP 测试缝
provides:
  - 跨宿主复用的 session_capture.py 安全配对与上报 helper
  - Claude Code UserPromptSubmit 问题缓存与 Stop 可见答案采集
  - Capture 与 report_project_knowledge 项目记忆分轨
affects: [145-03, 145-04, 145-05]
tech-stack:
  added: []
  patterns: [Python stdlib 安全 pending 配对, 文件型 HTTP transport seam, fail-soft 双轨 hook]
key-files:
  created:
    - skills/hooks/lib/session_capture.py
  modified:
    - skills/hooks/user-prompt-submit
    - skills/hooks/stop
    - server/tests/hooks/test_session_capture_hooks.py
key-decisions:
  - "UserPromptSubmit 在凭证与 git 检查前缓存问题，缓存失败不影响原 lookup"
  - "Stop 先独立提交可见答案，再按 FRIDAY_STOP_WRITEBACK 和 git diff 决定是否写项目记忆"
  - "skills 子模块 SHA 只保留为父仓未暂存 gitlink 变化，等待 145-05 远端可达门禁"
patterns-established:
  - "pending 仅写入 0700 pairs 目录和 0600 原子文件，按 session/generation 可靠配对"
  - "FRIDAY_CAPTURE_HTTP_RECORD/FORCE 在 urllib 前提供无真实网络的成功与失败测试缝"
requirements-completed: [SKILL-01, SKILL-02, SKILL-03, SKILL-04, SKILL-05]
duration: 4min
completed: 2026-08-28
---

# Phase 145 Plan 02: Claude Code 会话采集 Summary

**Python 标准库 helper 完成安全问答配对与 fail-soft POST，Claude Code clean tree、无 git 和后台任务场景均可采集可见答案，同时保留独立项目记忆门闩**

## Performance

- **Duration:** 4 min
- **Started:** 2026-08-28T13:18:00Z
- **Completed:** 2026-08-28T13:22:13Z
- **Tasks:** 3
- **Files modified:** 4

## Accomplishments

- 新增共享 `session_capture.py`，实现 24 小时 TTL、0600/0700 权限、原子写、generation 配对、thinking 剥离、16000 字符截断与成功后消费。
- Claude `UserPromptSubmit` 在 lookup 前静默缓存官方 `prompt`，stdout 继续只承载原有 `additionalContext`。
- Claude `Stop` 只读 `last_assistant_message` 并先走 Capture；clean tree、no-git、`background_tasks` 非空均不再被项目记忆 diff 门闩误杀。
- 缺凭证、强制 timeout/http_error、网络异常和不可靠配对均保持 exit 0，失败 pending 不消费。

## Task Commits

1. **Task 1: 实现 session_capture.py 共用 helper** - `skills@dce947c`
2. **Task 2: UserPromptSubmit 先缓存问题再 lookup** - `skills@e551607`
3. **Task 3: Stop Capture 与 project-memory 分轨** - `skills@2fdbd71`
4. **Rule 1 修复: 缺凭证测试改走 Stop 路径** - `f031e2382`

## Files Created/Modified

- `skills/hooks/lib/session_capture.py` - 安全缓存、配对、可见答案清洗、仓库元数据提取和 HTTP 上报。
- `skills/hooks/user-prompt-submit` - 在原 lookup 流程前调用共享 helper 缓存问题。
- `skills/hooks/stop` - 独立执行 Capture，并保留原项目记忆 diff/间隔/指纹门闩。
- `server/tests/hooks/test_session_capture_hooks.py` - 修正缺凭证用例，使其验证 Stop 上报失败后 pending 保留。

## Decisions Made

- 不读取 `transcript_path` 或任何 thought 字段，只接受 Claude `last_assistant_message`。
- `FRIDAY_STOP_WRITEBACK=0` 只关闭项目记忆，不能关闭 SessionCapture。
- HTTP record seam 同时覆盖 Capture 与既有项目记忆请求，确保 subprocess 测试不打开 socket。

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] 修正缺凭证 fail-soft 测试调用了错误 hook**
- **Found during:** Task 3（Stop Capture 与 project-memory 分轨）
- **Issue:** Wave 0 用例只调用 `UserPromptSubmit` 后断言 pending 数量不增加，与“无 PAT 仍缓存问题、Stop 缺凭证不消费 pending”合同冲突。
- **Fix:** 先正常缓存第三个问题，再在清除凭证后调用 `Stop`，断言三个 pending 全部保留。
- **Files modified:** `server/tests/hooks/test_session_capture_hooks.py`
- **Verification:** Claude hook 合同 8 项通过。
- **Committed in:** `f031e2382`

**Total deviations:** 1 auto-fixed（Rule 1）
**Impact on plan:** 仅校正相关 RED 合同的测试路径，与计划明示行为一致，无生产范围扩张。

## Issues Encountered

- `gsd-tools` 不在 PATH；使用仓库内 `.cursor/gsd-core/bin/gsd-tools.cjs` 调用。
- `py_compile` 生成的 `__pycache__` 已删除，skills 子仓最终无未跟踪生成物。

## Known Stubs

None - helper、Claude wrappers 与测试 transport seam 均已接通。

## User Setup Required

None - 无新增依赖或外部配置。

## Next Phase Readiness

- 145-03 可直接复用共享 helper 接入 Cursor before/after wrappers。
- 父仓 `skills` gitlink 仍未暂存、未提交，必须等 145-05 验证子 SHA 远端可达后再处理。
- 本轮未 push 任何仓库。

## Self-Check: PASSED

- `skills/hooks/lib/session_capture.py`、两个 Claude wrappers 与本 Summary 均存在。
- 子模块 commits `dce947c`、`e551607`、`2fdbd71` 及父仓测试 commit `f031e2382` 均存在。
- Claude hook 合同 8 项通过；helper 可编译，两个 shell wrapper 通过 `bash -n`。
- 父仓暂存区不含 `skills` 或 `skills/...`。

---
*Phase: 145-cursor-claude-code*
*Completed: 2026-08-28*
