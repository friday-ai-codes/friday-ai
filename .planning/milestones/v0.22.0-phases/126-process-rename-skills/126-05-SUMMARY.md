---
phase: 126-process-rename-skills
plan: 05
subsystem: skills
tags: [skills, friday-impact, friday-refactoring, hash-sync, SKILL-01]

requires:
  - phase: 126-04
    provides: rename_preview dual-face + knowledge whitelist (checklist consumer)
provides:
  - friday-impact / friday-refactoring skill sources in @friday-ai-codes/skills
  - SKILL_NAMES extended + task/assets sync mirror + sha256 guards green
  - install surface 7→9 (README / installer / plugin / friday hub)
affects:
  - phase-126 verification
  - coding-container skill injection
  - npm @friday-ai-codes/skills publish (Deferred D-15)

tech-stack:
  added: []
  patterns:
    - "Submodule single source of truth + sync_skills mirror + TestSkillsHashConsistency"
    - "Coding-period skills in SKILL_NAMES; IDE-only (friday-routing) excluded"

key-files:
  created:
    - skills/skills/friday-impact/SKILL.md
    - skills/skills/friday-impact/references/tool-order.md
    - skills/skills/friday-refactoring/SKILL.md
    - skills/skills/friday-refactoring/references/tool-order.md
    - task/assets/skills/friday-impact/SKILL.md
    - task/assets/skills/friday-impact/references/tool-order.md
    - task/assets/skills/friday-refactoring/SKILL.md
    - task/assets/skills/friday-refactoring/references/tool-order.md
  modified:
    - skills/README.md
    - skills/lib/installer.mjs
    - skills/.claude-plugin/plugin.json
    - skills/skills/friday/SKILL.md
    - task/scripts/sync_skills.py
    - task/tests/test_skills_injection.py
    - skills (submodule pointer)

key-decisions:
  - "D-13: skill names friday-impact / friday-refactoring; zh-CN checklist only"
  - "D-14: SKILL_NAMES=(friday-code,friday-memory,friday-impact,friday-refactoring); no routing"
  - "D-15: npm publish Deferred — acceptance = source + hash + injection tests"
  - "D-16: frozen repo_router_v2.py and mcp/ untouched; explicit-path commits only"

patterns-established:
  - "Pattern: new coding-period skill → edit skills/skills/<name>/ → submodule commit → sync_skills → main pointer+assets"
  - "Pattern: installer bundledSkills() dynamic scan; README/bootstrap/plugin counts updated by hand 7→9"

requirements-completed: [SKILL-01]

duration: 2min
completed: 2026-08-09
---

# Phase 126 Plan 05: friday-impact / friday-refactoring Skills Summary

**Two coding-period workflow skills (`friday-impact`, `friday-refactoring`) land in the skills submodule with install-surface 7→9, sync into `task/assets/skills/`, and sha256 injection guards green — closes SKILL-01 without npm publish.**

## Performance

- **Duration:** ~2 min
- **Started:** 2026-08-09T21:31:43Z
- **Completed:** 2026-08-09T21:33:30Z
- **Tasks:** 2/2
- **Files modified:** 14+ (submodule + main)

## Accomplishments

- Added `friday-impact` (impact-analysis checklist: staleness → detect_changes/impact/list_processes → `affected_processes`) and `friday-refactoring` (rename_preview read-only then local edit; fail-soft)
- Updated skills README / installer bootstrap / plugin.json / friday hub routing 7→9
- Extended container `SKILL_NAMES` and ran `sync_skills.py`; `TestSkillsHashConsistency` + injection tests 8/8 green
- npm `@friday-ai-codes/skills` publish left Deferred (D-15)

## Task Commits

Each task was committed atomically:

1. **Task 1: 子模块新增两 skill 正文 + 安装面文案（D-13）**
   - skills submodule `54f15aa` — `feat(skills): 新增 friday-impact / friday-refactoring 并同步接入面 7→9`
   - main `a8c1f6c6` — `feat(126-05): 更新 skills 子模块指针（friday-impact / friday-refactoring）`
2. **Task 2: SKILL_NAMES 扩展 + sync + sha256 守卫（D-14/D-15）** — RED `74f6756b` (test) → GREEN `60ce8e7c` (feat)

**Plan metadata:** `51ed2a65` (docs: complete plan SUMMARY)

## Files Created/Modified

- `skills/skills/friday-impact/**` — impact-analysis workflow skill + tool-order reference
- `skills/skills/friday-refactoring/**` — refactoring/rename_preview workflow skill + tool-order reference
- `skills/README.md` / `lib/installer.mjs` / `.claude-plugin/plugin.json` / `skills/friday/SKILL.md` — 7→9 surface
- `task/scripts/sync_skills.py` — SKILL_NAMES += impact/refactoring
- `task/tests/test_skills_injection.py` — parametrize four skills
- `task/assets/skills/friday-{impact,refactoring}/**` — sync mirror only
- `skills` gitlink — pointer `54f15aa`

## Decisions Made

- Coding-period skills enter container `SKILL_NAMES`; `friday-routing` remains IDE-only (not synced).
- Skill bodies are zh-CN checklists; optional `references/tool-order.md` short cheat sheets; no tool implementation copied.
- Acceptance does not wait on npm bump (D-15).

## Deviations from Plan

None - plan executed exactly as written.

## TDD Gate Compliance

- RED: `74f6756b` — `test(126-05): 扩展 SKILL_NAMES…` (hash tests failed on missing assets)
- GREEN: `60ce8e7c` — `feat(126-05): 扩展 sync_skills…` (`8 passed`)

## Deferred Ideas

- npm publish `@friday-ai-codes/skills` (D-15) — ops follow-up
- Push skills submodule branch `feat/friday-impact-refactoring-skills` to remote (local commit SHA `54f15aa` already pointed from main)

## Threat Flags

None beyond plan register (T-126-05 mitigated via preview-readonly wording; T-126-06 frozen surfaces clean).

## Known Stubs

None.

## Verification

```bash
cd task && uv run pytest tests/test_skills_injection.py -q   # 8 passed
python task/scripts/sync_skills.py                          # four skills synced
node skills/bin/friday-ai-skills.mjs list                   # 打包技能（9 个）
```

Frozen confirmation: commits `a8c1f6c6`..`60ce8e7c` do not touch `server/codegraph/services/repo_router_v2.py` or `mcp/` submodule.

## Self-Check: PASSED

- FOUND: `skills/skills/friday-impact/SKILL.md`
- FOUND: `skills/skills/friday-refactoring/SKILL.md`
- FOUND: `task/assets/skills/friday-impact/SKILL.md`
- FOUND: `task/assets/skills/friday-refactoring/SKILL.md`
- FOUND: commit `54f15aa` via `git -C skills log` (skills submodule)
- FOUND: commits `a8c1f6c6`, `74f6756b`, `60ce8e7c`, `51ed2a65` (main)
