---
phase: 128-initiative-profile-team-gate
plan: 01
subsystem: process_runtime
tags: [initiative-profile, call_source, structlog, llm]

requires:
  - phase: v0.23.0-DECISIONS
    provides: PROF-01/02/03 画像语料与 fail-soft 约束
provides:
  - InitiativeProfile dataclass + build_profile 三态结果
  - select_profile_corpus 剔除 acceptance
  - CallSource.INITIATIVE_PROFILE + LOGGING-SPEC 登记
affects:
  - 128-03 漏斗三入口接线

tech-stack:
  added: []
  patterns:
    - "画像 LLM fail-soft → degraded，不抛垮调用方"
    - "日志仅 corpus_char_len/reason，禁止需求原文"

key-files:
  created:
    - server/services/process_runtime/initiative_profile.py
    - server/tests/services/process_runtime/test_initiative_profile.py
  modified:
    - server/agents/call_source.py
    - .planning/observability/LOGGING-SPEC.md

key-decisions:
  - "call_source 新增 initiative_profile（非复用 aux_repo_router）"
  - "语料不足不调 LLM，直接 clarify(insufficient_profile_corpus)"

patterns-established:
  - "ProfileResult 统一 ok|clarify|degraded + profile dict"

requirements-completed: [PROF-01, PROF-02, PROF-03]

duration: 25min
completed: 2026-08-14
---

# Phase 128 Plan 01: 专项画像模块 Summary

**可单测的 `build_profile` 交付机读画像：语料剔除验收项，不足 clarify，LLM 失败 degraded。**

## Performance

- **Duration:** ~25min
- **Started:** 2026-08-14T04:43:37Z
- **Completed:** 2026-08-14T04:50:00Z
- **Tasks:** 2/2
- **Files modified:** 4

## Accomplishments

- `InitiativeProfile` 可 JSON 序列化进 stage 观测
- `select_profile_corpus` 默认剔除 acceptance/测试正文
- fail-soft 观测：`initiative_profile_started/completed/failed` + `CallSource.INITIATIVE_PROFILE`

## Task Commits

1. **Task 1 RED:** `8ba77242` — test(128-01): 添加专项画像模块失败用例
2. **Task 1–2 GREEN:** `89d4d9a9` — feat(128-01): 实现专项画像抽取与 CallSource 登记

## Files Created/Modified

- `server/services/process_runtime/initiative_profile.py` — 画像契约 + corpus + LLM 抽取
- `server/tests/services/process_runtime/test_initiative_profile.py` — PROF-01~03 单测
- `server/agents/call_source.py` — `INITIATIVE_PROFILE`
- `.planning/observability/LOGGING-SPEC.md` — §4.1 登记

## Decisions Made

- 新增独立 `initiative_profile` call_source，便于 QPS/错误维度拆分
- 非法 JSON / 上游异常一律 `degraded`，不向上抛

## Deviations from Plan

None - plan executed exactly as written.

## Verification

```text
cd server && uv run pytest tests/services/process_runtime/test_initiative_profile.py -q
# 7 passed
```

## Self-Check: PASSED

- FOUND: `server/services/process_runtime/initiative_profile.py`
- FOUND: `8ba77242`, `89d4d9a9`
