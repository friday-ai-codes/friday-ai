---
phase: 145-cursor-claude-code
plan: "04"
subsystem: skills
tags: [session-capture, project-memory, http-fallback, privacy]
requires:
  - phase: 145-cursor-claude-code
    provides: Plan 01 的 skills snapshot 职责分离守卫
  - phase: 145-cursor-claude-code
    provides: Plan 02 的 Claude Code SessionCapture 与 ProjectMemory 分轨实现
provides:
  - friday、friday-dev 与 friday-memory 的双工具职责分流说明
  - report_session_knowledge HTTP fallback 十二字段契约与隐私边界
affects: [145-05, skills-distribution, cursor-hooks, claude-code-hooks]
tech-stack:
  added: []
  patterns:
    - SessionCapture 原始问答与 ProjectMemory 交付总结分轨
    - clean tree 仍采集用户可见问答
key-files:
  created: []
  modified:
    - skills/skills/friday/SKILL.md
    - skills/skills/friday-dev/SKILL.md
    - skills/skills/friday-dev/references/http-fallback.md
    - skills/skills/friday-memory/SKILL.md
    - skills/skills/friday-memory/references/http-fallback.md
key-decisions:
  - "会话问答始终走 report_session_knowledge，项目交付总结仅在有 git 变更时走 report_project_knowledge。"
  - "HTTP fallback 展示服务端十二字段开放契约，但明确禁止客户端猜测或拼装 project_id。"
patterns-established:
  - "技能文档必须同时声明 clean tree Capture、可见 final 边界和 transcript/CoT/凭证禁传规则。"
requirements-completed: [SKILL-04]
duration: 5min
completed: 2026-08-28
---

# Phase 145 Plan 04: Skills 会话采集契约 Summary

**可分发技能文档现已明确分离 SessionCapture 原始问答与 ProjectMemory 交付总结，并对齐 HTTP fallback 十二字段及隐私边界。**

## Performance

- **Duration:** 5 min
- **Started:** 2026-08-28T13:24:04Z
- **Completed:** 2026-08-28T13:26:17Z
- **Tasks:** 2
- **Files modified:** 5

## Accomplishments

- friday 与 friday-dev 收工环路显式并列 `report_session_knowledge` 和 `report_project_knowledge`，保留开工分支召回路径。
- friday-memory 增加 SessionCapture 原始问答与 ProjectMemory 交付总结职责分层。
- 两份 HTTP fallback 对齐十二字段请求契约，明确只取用户可见最终答案，禁止 transcript、隐藏思维链与凭证。
- snapshot、npm 对齐和 schema 注册联合门禁 14 项全部通过。

## Task Commits

Each task was committed atomically in the `skills` child repository:

1. **Task 1: friday 与 friday-dev 主文/HTTP fallback** - `67970e7`
2. **Task 2: friday-memory 主文与 HTTP fallback** - `e4abc90`

父仓 `skills` gitlink 按计划保持未暂存，未执行 push。

## Files Created/Modified

- `skills/skills/friday/SKILL.md` - 在分支环路中增加双工具职责分流。
- `skills/skills/friday-dev/SKILL.md` - 明确 clean tree Capture 与项目交付总结门闩。
- `skills/skills/friday-dev/references/http-fallback.md` - 补充会话报告十二字段 HTTP 契约。
- `skills/skills/friday-memory/SKILL.md` - 增加 SessionCapture 与 ProjectMemory 分层。
- `skills/skills/friday-memory/references/http-fallback.md` - 对齐会话与项目记忆 HTTP 职责。

## Decisions Made

- 不把两种写入合并为“记忆写回”：原始问答与项目交付总结保持独立生命周期。
- 文档保留完整十二字段服务端契约，同时要求常规客户端不根据默认分支推断 `project_id`。

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered

- Task 1 的 snapshot 守卫按计划仅因 friday-memory 尚未更新而失败；Task 2 完成后联合门禁 14 项全部通过。
- `state.update-progress` 在 free-form ROADMAP 兼容模式下未刷新 STATE frontmatter 百分比，已按 23/25 计划手动校正为 92%。

## Known Stubs

None.

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness

- Plan 05 可在确认 child commits 远端可达后更新父仓 gitlink。
- 当前未 push，父仓 gitlink 继续保持未暂存。

## Self-Check: PASSED

- 五份技能文档与 Summary 均存在。
- child commits `67970e7`、`e4abc90` 均可从 skills 仓历史读取。

---
*Phase: 145-cursor-claude-code*
*Completed: 2026-08-28*
