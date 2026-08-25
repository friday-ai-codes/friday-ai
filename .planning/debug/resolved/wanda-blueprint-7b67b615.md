---
status: resolved
trigger: "Wanda blueprint artifact 7b67b615-8830-4980-bf0f-3572fded41fa displays inconsistent stage results, durations, citations, and unknown repository metadata"
created: 2026-08-21
updated: 2026-08-21T18:23:00+08:00
symptoms_prefilled: true
---

# Debug Session: Wanda Blueprint 7b67b615

## Symptoms

expected: |
  Blueprint viewer shows coherent stage durations, accurate repo-plan success/failure
  denominators, citation-backed AI review conclusions, structured merge/gate fields with
  human labels, and confirm-gate threads bound to named repositories with repository_id.
actual: |
  各仓方案大量失败，UI 显示耗时 1621m。
  AI 审查连续三轮报告关键结论缺少 citations，跨日后仍出现第 3 轮与等待 1 天。
  合并状态卡与仓库集确认门的大量结构化字段被渲染成“其他信息”。
  确认门事件存在 `thread_id`，但 UI 显示未知仓库且 `repository_id` 为空。
  仓库调研显示完成 9/23、54m6s，真实完成、失败、排除与待处理口径不明。
  需要核查旧 artifact 是否缺少当前代码已有的 citation backfill/review/retry 修复。
errors: |
  UI: 1621m duration; “其他信息” for structured fields; 未知仓库; empty repository_id;
  citation-missing review blockers; 9/23 research progress ambiguity.
reproduction: |
  Open Wanda blueprint artifact 7b67b615-8830-4980-bf0f-3572fded41fa
  (session 4d6984c4-cbab-4ae3-ba5f-d49f5dfd5eb6) in the blueprint viewer.
started: observed on live Wanda artifact during/after prior repo-plan recovery work

## Current Focus

reasoning_checkpoint:
  hypothesis: |
    Coupled UI+data defects: (1) stage duration used wall-clock first→last including overnight
    waits → 1621m; (2) research/repo_plan facts counted raw events not unique repos → 9/23;
    (3) missing i18n for stage_state keys → 其他信息; (4) repoNames only from current
    associations + confirm action emitted empty repository_id → 未知仓库; (5) historical
    confirm-gate emptied fitness.citations before pool-build fix → citation_missing ×8.
  confirming_evidence:
    - "events_by_stage.repo_plan.span_minutes = 1621.3 (2026-08-19 07:22 → 2026-08-20 10:23)"
    - "repo_research.started events=23 but unique repos started/completed=9/9"
    - "merge/confirm stage_state keys (gaps/degraded_sections/repos/confirmed) absent from zh-CN payload map"
    - "confirmation.action payload repository_id='' ; confirmation stage_state repos=[] after lock; unsuitable backend-config UUID only in events"
    - "v11 associations all empty fitness/rationale citations; PartialPlans still had raw cites; after backfill v12 fit/rat populated and citation_missing=0"
  falsification_test: |
    If duration still shows ~1621m after FE active-duration change, or research still 9/23
    with unique-count facts, or citation_missing returns after backfill — hypothesis wrong.
  fix_rationale: |
    FE: unique-repo denominators, active duration excluding >30m pauses, i18n labels,
    repoNames from event accumulator, confirmation field aliases. BE: emit taxonomy keys,
    omit empty repository_id on gate actions. Data: justified backfill+merge rewind restored
    citations; remaining blockers are acceptance_uncovered (separate).
  blind_spots: |
    Wanda container still runs pre-FE-fix code until redeploy; acceptance_uncovered (30)
    still exhausts review; full confirm_gate pytest hung in this environment (source guards verified).

hypothesis: confirmed multi-cause; fixes deployed and verified on Wanda
test: completed — source hash match, targeted service rebuild, health/API checks, production bundle labels, and live-event UI derivation
expecting: satisfied — v12 citations intact; research 9/9; repo-plan 8/8; no 1621m wall-clock duration; readable labels deployed
next_action: archive resolved session; no commit per user instruction

## Eliminated

- hypothesis: repo-plan still mostly failed on final barrier
  evidence: stage_state repo_plan all 8 ready; unique completed=8/8; failures are historical retry events (17 repo_failed)
  timestamp: 2026-08-21T17:27:00+08:00

- hypothesis: waitingDays calendar math is wrong
  evidence: open threads from prior day correctly show floor(now-created)/86400000 ≥ 1; symptom is long-lived unresolved findings, not off-by-one day math
  timestamp: 2026-08-21T17:30:00+08:00

## Evidence

- timestamp: 2026-08-21T17:20:00+08:00
  checked: knowledge-base.md
  found: |
    Matches repo-plan-poisoned-resume (same artifact 7b67b615) and support_repository_id
    alias false positives. Citation backfill script documents confirm-gate emptied
    fitness.citations because whitelist used empty content.citations before merge pool.
  implication: treat prior resume/alias fixes as context; focus remaining UI/data symptoms

- timestamp: 2026-08-21T17:27:00+08:00
  checked: Wanda DB via SSH (artifact/session/events/threads/research/subagent)
  found: |
    Session done @ ai_review; versions 1–11 then later 12 after repair.
    repo_plan event span 1621.3m; research started events 23 / completed 9;
    confirmation.action repository_id empty; stage_state confirmation.repos=[];
    v11 assoc citations empty despite pool=140; PartialPlans retain raw fitness cites;
    review rounds 1–3 then resumed round 3 on Aug 20; unresolved citation_missing×8.
  implication: UI metrics mis-derived from events; historical citation data poisoned; empty id + missing names cause 未知仓库

- timestamp: 2026-08-21T17:46:00+08:00
  checked: backfill_fitness_citations.py applied on Wanda
  found: |
    dry-run then apply: filled 8/8 fitness cites on v11; rewind merge; resume produced v12;
    merge completed (api_contracts degraded); review exhausted on acceptance_uncovered×30;
    citation_missing=0; all 8 assocs now fit/rat citations >0; old citation threads resolved.
  implication: citation symptom fixed in live data; remaining review blockers are acceptance coverage

- timestamp: 2026-08-21T17:47:00+08:00
  checked: FE vitest blueprintActivity + stageStepper
  found: 48 passed including unique-count, active-duration, confirmation aliases
  implication: FE regressions covered for fixed metrics

- timestamp: 2026-08-21T18:23:00+08:00
  checked: Wanda deployment, health, authenticated APIs, production bundle, and live-event UI derivation
  found: |
    Compared local/Wanda dirty trees before copying: only six intended source files differed.
    Synced those files; rebuilt server/worker/scheduler/web. One first-build failure was caused
    by an accidentally escaped route filename from scp; removed only that duplicate, restored
    the canonical [id].vue, then rebuilt successfully. All affected containers are healthy.
    Authenticated document/events/stages/threads APIs all returned 200. Document is current v12,
    citation pool=169, all 8 associations have fitness+rationale citations, and stages reports
    citation_missing=0 (remaining acceptance_uncovered=30). Live endpoint/UI derivation reports
    research 9/9, repo-plan 8/8, terminal failures 0, repo-plan active duration 9,966,602ms
    instead of 1621m wall-clock. Production assets contain the new Chinese field labels.
    Vitest 49 passed; pnpm build passed; backend py_compile + ruff passed.
  implication: original reported data/UI defects are deployed and verified; acceptance coverage and runner WebSocket ping timeouts are separate pre-existing concerns

## Resolution

- root_cause: |
  Five coupled causes: (1) panorama duration = wall-clock first→last event including overnight
  clarification pauses (1621m); (2) research/repo_plan progress counted event occurrences not
  unique repository_id (9/23, inflated failures); (3) stage_state keys lacked i18n →「其他信息」;
  (4) repoNames only from current associations + gate confirm emitted empty repository_id →
  「未知仓库」; (5) historical confirm-gate emptied fitness.citations before pool-build fix,
  so AI review citation_missing persisted across rounds despite later code fix.
- fix: |
  FE unique-repo facts + active duration (pause>30m excluded) + hour formatting + i18n payload
  keys + repoNames from event accumulator + confirmation field aliases; BE emit taxonomy
  repository_count/locked_repository_count (+legacy aliases) and omit empty repository_id on
  gate actions; Wanda data repaired via citation backfill + merge rewind (v12, citation_missing=0).
- verification: |
  Complete: Vitest 49 passed; local production web build passed; backend py_compile + ruff passed.
  Wanda server/worker/scheduler/web rebuilt and healthy; authenticated blueprint APIs all 200.
  Artifact v12 has 169 citations, all 8 associations cited, citation_missing=0. Live UI derivation
  shows research 9/9, repo-plan 8/8, terminal failures 0, and active duration instead of 1621m.
  Production bundle contains the added labels. No commit was created.
- files_changed:
  - web/src/utils/blueprintActivity.ts
  - web/src/utils/__tests__/blueprintActivity.spec.ts
  - web/src/components/blueprint/BlueprintStageStepper.vue
  - web/src/pages/knowledge/blueprints/[id].vue
  - web/src/locales/zh-CN.json
  - server/services/process_runtime/blueprint_confirm_gate.py
  - server/delivery/services/blueprint_lifecycle_service.py
