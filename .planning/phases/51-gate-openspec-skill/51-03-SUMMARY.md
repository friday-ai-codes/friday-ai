---
phase: 51-gate-openspec-skill
plan: 03
subsystem: task
tags: [openspec, sdd, task-config, system-prompt, pydantic-settings, follow_openspec]

requires:
  - phase: 51-02
    provides: env_FRIDAY_TASK_FOLLOW_OPENSPEC dispatch 注入（approved SDD 仓）
provides:
  - TaskConfig.follow_openspec 字段（读 FRIDAY_TASK_FOLLOW_OPENSPEC env）
  - _get_system_prompt 条件追加 openspec 指引段（独立 _openspec_guidance helper）
affects: []

tech-stack:
  added: []
  patterns:
    - "pydantic-settings env_prefix 自动映射布尔 env（默认 False 零回归）"
    - "system_prompt 静态文本独立 helper，无外部输入拼接（无注入面）"

key-files:
  created:
    - task/tests/test_openspec_prompt.py
  modified:
    - task/core/config.py
    - task/core/executor.py
    - task/tests/test_config.py
    - task/tests/test_callback.py

key-decisions:
  - "openspec 指引段抽独立 _openspec_guidance helper 便于测试，不内联"
  - "既有 MagicMock-config 用例显式 follow_openspec=False 防真值 Mock 误触追加"
  - "setting_sources=[project] 既有原生加载 .claude/skills 不改，仅加 prompt 注入点"

patterns-established:
  - "follow_openspec=False/缺省 → system_prompt 逐字等现状（零回归守护）"

requirements-completed: [GATE-02]

duration: ~10min
completed: 2026-06-17
---

# Phase 51 Plan 03: task openspec system_prompt Summary

**TaskConfig 加 follow_openspec 字段（经 env_prefix 映射 FRIDAY_TASK_FOLLOW_OPENSPEC，默认 False），_get_system_prompt 在 follow_openspec 为真时追加独立 _openspec_guidance helper 文本（指示 agent 遵循 openspec/ 下已批准 spec、优先查仓库内 openspec skill 按 delta 实现），缺省路径逐字等现状**

## Performance

- **Duration:** ~10 min
- **Tasks:** 2 (TDD)
- **Files modified:** 5

## Accomplishments
- `TaskConfig.follow_openspec: bool=False`，env `"true"` / 参数 `True` 均生效
- `_openspec_guidance()` 独立 helper（中文 openspec 指引段）；`_get_system_prompt` 条件 `base + "\n\n" + guidance`
- follow_openspec=False/缺省 → 返回 base 逐字等现状（零回归断言）
- 修正 `test_callback.py` 两处 MagicMock-config 用例显式 `follow_openspec=False`，防真值 Mock 误触 openspec 追加（T-51-MOCK）

## Task Commits

1. **Task 1: TaskConfig.follow_openspec 字段** - `4ba41acdb` (feat, TDD)
2. **Task 2: _get_system_prompt openspec 段 + MagicMock 修正** - `af96b0129` (feat, TDD)

## Files Created/Modified
- `task/core/config.py` - follow_openspec 字段
- `task/core/executor.py` - _openspec_guidance helper + _get_system_prompt 条件追加
- `task/tests/test_config.py` - follow_openspec 默认/参数/env 三态
- `task/tests/test_openspec_prompt.py` - true 含 openspec 段 / false 逐字等现状守护
- `task/tests/test_callback.py` - MagicMock-config 显式 follow_openspec=False 零回归修正

## Decisions Made
None - followed plan as specified.

## Deviations from Plan
None - plan executed exactly as written.

## Issues Encountered
None.

## Next Phase Readiness
- 容器侧 openspec 信号消费完成；`.claude/skills` 由既有 `setting_sources=["project"]` 原生加载。
- 真实模型遵循 openspec 流程属真实环境人工验收（deferred）。

---
*Phase: 51-gate-openspec-skill*
*Completed: 2026-06-17*
