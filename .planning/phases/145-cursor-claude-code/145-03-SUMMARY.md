---
phase: 145-cursor-claude-code
plan: "03"
subsystem: hooks
tags: [cursor, node-stdlib, session-capture, hooks-json, fail-soft]
requires:
  - phase: 145-cursor-claude-code
    plan: "01"
    provides: Cursor hooks merge RED 合同与双宿主行为测试
  - phase: 145-cursor-claude-code
    plan: "02"
    provides: session_capture.py 安全配对与上报 helper
provides:
  - Cursor beforeSubmitPrompt 问题缓存与 afterAgentResponse.text 可见答案配对
  - hooks.json v1 非破坏 merge、basename 去重与非法 JSON 保留
  - 项目级和全局 Cursor hooks 安装接线
affects: [145-05, cursor-hooks, skills-installer]
tech-stack:
  added: []
  patterns: [Node 标准库原子 JSON 合并, Cursor 官方事件配对, fail-soft shell wrapper]
key-files:
  created:
    - skills/hooks/cursor/hooks.json
    - skills/hooks/cursor/before-submit-prompt
    - skills/hooks/cursor/after-agent-response
  modified:
    - skills/lib/installer.mjs
    - skills/bin/friday-ai-skills.mjs
key-decisions:
  - "Cursor Capture 只使用 beforeSubmitPrompt.prompt 与 afterAgentResponse.text，不注册 stop 或 thought 事件"
  - "hooks.json 只按 Friday command basename 替换去重，用户顶级键、其他事件和 stop hooks 原样保留"
  - "skills 子模块 SHA 继续只作为父仓未暂存 gitlink 变化，等待 145-05 远端可达门禁"
patterns-established:
  - "安装器先复制 0755 wrappers，再以同目录临时文件和 rename 原子合并 hooks.json"
  - "非法 hooks.json 返回中文可操作 warning，绝不覆盖原 bytes"
requirements-completed: [SKILL-01, SKILL-03, SKILL-05]
duration: 3min
completed: 2026-08-28
---

# Phase 145 Plan 03: Cursor 官方问答采集与 hooks 安装 Summary

**Cursor 通过 beforeSubmitPrompt/afterAgentResponse 官方事件安全配对可见问答，安装器以 hooks.json v1 结构化 merge 保留用户配置并幂等升级 Friday hooks**

## Performance

- **Duration:** 3 min
- **Started:** 2026-08-28T13:27:15Z
- **Completed:** 2026-08-28T13:29:54Z
- **Tasks:** 3
- **Files modified:** 5

## Accomplishments

- 新增 Cursor before/after wrappers；before 仅缓存 `prompt` 并最多输出 `{"continue":true}`，after 仅提交 `text`，两者全部 fail-soft。
- 新增 Cursor hooks v1 模板，只注册 `beforeSubmitPrompt` 与 `afterAgentResponse`，不引入 `stop`、`afterAgentThought` 或 `failClosed`。
- `mergeCursorHooksConfig` 保留未知顶级键、用户 hooks 和其他事件，按 Friday command basename 替换重复或旧路径。
- `writeMergedCursorHooksFile` 对合法配置执行同目录原子替换；非法 JSON 保留原始 bytes 并返回可操作 warning。
- Cursor 项目级与全局安装均复制可执行 wrappers、选择正确 command 路径并在 bootstrap 开关之外合并 hooks。

## Task Commits

1. **Task 1: Cursor before/after wrappers 与模板** - `skills@fe2e305`
2. **Task 2: mergeCursorHooksConfig 纯函数** - `skills@1b9fb2a`
3. **Task 3: performInstall 复制 Cursor hooks 并 merge** - `skills@dc0a69c`

## Files Created/Modified

- `skills/hooks/cursor/hooks.json` - Cursor hooks v1 可分发模板。
- `skills/hooks/cursor/before-submit-prompt` - 静默缓存 Cursor 用户问题。
- `skills/hooks/cursor/after-agent-response` - 只用 Cursor `text` 提交可见答案。
- `skills/lib/installer.mjs` - 提供安全 merge、原子写与 Cursor hooks 安装 API。
- `skills/bin/friday-ai-skills.mjs` - Cursor 安装流程接入 wrappers 复制和 hooks 配置合并。

## Decisions Made

- 保持 Capture 与 Cursor 既有或用户自定义 `stop` 完全分离；安装器不删除也不登记 `stop` 为答案来源。
- basename 是 Friday hook 的稳定身份，允许项目级与全局路径互相升级而不产生重复条目。
- `--no-bootstrap` 只影响上下文引导，不关闭 Cursor hooks 安装。

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] 修正 state.update-progress 写入的错误百分比**
- **Found during:** 计划状态收口
- **Issue:** SDK 返回 `completed=24/total=25/percent=96`，但将 STATE frontmatter 的 `percent` 写为 80。
- **Fix:** 按同一 SDK 返回的计划计数将百分比校正为 96。
- **Files modified:** `.planning/STATE.md`
- **Verification:** `completed_plans: 24`、`total_plans: 25` 与 `percent: 96` 一致。
- **Committed in:** 计划元数据提交

**Total deviations:** 1 auto-fixed（Rule 1）
**Impact on plan:** 仅修正 GSD 状态算术不一致，不扩展生产实现范围。

## Issues Encountered

- `gsd-tools` 不在 PATH；继续使用仓库内 `.cursor/gsd-core/bin/gsd-tools.cjs`。
- 当前父仓 `main` 的 Friday 项目绑定与 Phase 145 无直接业务关系，因此未向该错误业务项目写入本计划交付记忆。

## Known Stubs

None - wrappers、merge、原子写和安装调用链均已接通。

## User Setup Required

None - 无新增依赖或外部配置。

## Next Phase Readiness

- 145-05 可验证子模块 commits 的远端可达性后再处理父仓 `skills` gitlink。
- 本计划未暂存或提交父仓 `skills` gitlink，也未执行 push。

## Self-Check: PASSED

- 5 个计划文件均存在，skills 子模块 commits `fe2e305`、`1b9fb2a`、`dc0a69c` 均可解析。
- Node merge 测试 4 项与双宿主 hook 行为测试 10 项通过，两个 shell wrapper 通过 `bash -n`。
- skills 子仓工作树干净；父仓暂存区不含 `skills` 或 `skills/...`。

---
*Phase: 145-cursor-claude-code*
*Completed: 2026-08-28*
