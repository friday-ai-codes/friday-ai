---
phase: 260817-0z5-append-only-p11-validate
verified: 2026-08-16T17:35:00Z
status: passed
score: 6/6 must-haves verified
overrides_applied: 0
re_verification: false
gaps: []
deferred: []
---

# Phase 260817-0z5: Append-only charter + P11 validate — Verification Report

**Phase Goal:** Runner directly reads repository and creates first fixed charter baseline; later refreshes are fingerprint-gated; automated updates only append structured appendices or create destructive proposals, never mutate formal fields/draft_content; human approval is the only formal mutation; existing data is not rewritten.

**Verified:** 2026-08-16T17:35:00Z
**Status:** passed
**Re-verification:** No — initial verification

## Goal Achievement

### Observable Truths

| # | Truth | Status | Evidence |
| --- | --- | --- | --- |
| 1 | 首次仓库阅读（repo_summary Runner）可直接产出章程基线，不再依赖对 ai_summary 的二次 LLM 蒸馏作为主路径 | ✓ VERIFIED | `task/core/executor.py` optional `charter` in `_REPO_SUMMARY_INPUT_SCHEMA`; prompt seed `0012_seed_repo_summary_charter.py`; callback branch applies `aapply_charter_from_runner` when `payload.charter` present — no unconditional overwrite enqueue |
| 2 | 基线一旦生成后，自动化路径不得写入正式字段或 draft_content | ✓ VERIFIED | `apply_automation_to_existing_charter` only mutates `appendices`/`change_proposals`/`baseline_*`; `adraft_charter` / writeback `_persist` call that helper; formal `setattr` only in `aconfirm_charter` / `_apply_proposal_to_formal`; tests assert formal + `draft_content` unchanged |
| 3 | 每次成功门禁处理持久化 observed fingerprint（含空 delta）；首次触碰可写 locked_at；相同 fingerprint 不新增 appendices/proposals | ✓ VERIFIED | `_persist_fingerprint_and_lock` on skip and classify paths; `test_empty_delta_still_persists_fingerprint`, `test_fingerprint_repeat_*`, `test_legacy_*_locked_at`; `resolve_fingerprint_for_repository` preserves non-empty stored when evidence unreadable |
| 4 | 实质变化：新 list key/citation-only → appendices；标量/删除/同 key 语义 → change_proposals；正式字段仅人工 confirm/批准提案 | ✓ VERIFIED | `classify_charter_delta` implements full table; `test_classify_new_key_to_appendices_scalar_to_proposals`; `test_aconfirm_approve_and_reject_proposals`; API confirm wires `approve_proposal_ids`/`reject_proposal_ids` |
| 5 | callback 决策树：equal skip；changed+charter apply；无行+无 charter bootstrap；有行+无 charter supplement | ✓ VERIFIED | `callbacks._update_repository_on_summary_complete` four-branch tree (lines ~1618–1711); tests cover bootstrap / apply / equal-skip / supplement; enqueue only in bootstrap|supplement branches |
| 6 | P11 与确认门回灌改为 formal-unchanged + side-channel；migration 不回写生产章程正文 | ✓ VERIFIED | API/writeback/service tests assert formal-unchanged; MJ-07 docstring updated to appendices/proposals; migration `0042` is AddField-only (no RunPython) |

**Score:** 6/6 truths verified

### Required Artifacts

| Artifact | Expected | Status | Details |
| -------- | -------- | ------ | ------- |
| `server/repositories/models.py` | baseline_fingerprint/locked_at/appendices/change_proposals | ✓ VERIFIED | Fields present; docstring documents freeze + side-channels |
| `server/repositories/migrations/0042_repo_charter_append_only.py` | additive-only schema | ✓ VERIFIED | Four `AddField` ops; depends on `0041_merge_20260802_0303`; no data rewrite |
| `server/repositories/services/charter_service.py` | apply/classify/fingerprint | ✓ VERIFIED | Exports `aapply_charter_from_runner`, `compute_charter_fingerprint`, `classify_charter_delta`; observability events present |
| `task/core/executor.py` | submit_summary charter field | ✓ VERIFIED | Optional `charter` object schema; not in `required` |
| `server/subagent/api/callbacks.py` | deterministic gate | ✓ VERIFIED | Four-branch tree wired to apply/enqueue |
| `server/tests/repositories/test_charter_service.py` | freeze/append/proposal/fingerprint/P11 coverage | ✓ VERIFIED | Substantive tests; INV-6 scan present |
| `server/tests/services/process_runtime/test_blueprint_confirm_gate.py` | confirm-gate alignment | ✓ VERIFIED | MJ-07 asserts automation side-channel semantics + no note pollution |

### Key Link Verification

| From | To | Via | Status | Details |
| ---- | --- | --- | ------ | ------- |
| `executor._REPO_SUMMARY_INPUT_SCHEMA` | `callbacks._update_repository_on_summary_complete` | `submit_summary.charter` | ✓ WIRED | Schema has `charter`; callback reads `payload_obj.get("charter")` |
| `callbacks` | `aapply_charter_from_runner` \| `enqueue_charter_draft(mode=…)` | fingerprint decision tree | ✓ WIRED | equal→apply(skip growth); charter→apply; no-row→bootstrap; row→supplement |
| `classify_charter_delta` | `RepoCharter.appendices\|change_proposals` | classify destinations | ✓ WIRED | `_append_side_channels` only; no formal/draft writes |
| automated writers | `baseline_fingerprint` | persist after gated handling | ✓ WIRED | apply/skip/adraft/writeback all call `_persist_fingerprint_and_lock` |
| `POST …/charter/confirm/` | `aconfirm_charter` edits\|approve | sole formal mutation | ✓ WIRED | `charter_views` passes `approve_proposal_ids`/`reject_proposal_ids` |

### Data-Flow Trace (Level 4)

| Artifact | Data Variable | Source | Produces Real Data | Status |
| -------- | ------------- | ------ | ------------------ | ------ |
| `aapply_charter_from_runner` | formal / appendices / fingerprint | Runner `charter` JSON + evidence fingerprint | Yes — normalize + create/classify + ORM save | ✓ FLOWING |
| callback gate | `observed_fingerprint` | overview/tree/facets from summary payload or repo | Yes — `compute_charter_fingerprint` | ✓ FLOWING |
| GET charter serializer | appendices/proposals/fingerprint | `RepoCharter` ORM fields | Yes — ModelSerializer read_only | ✓ FLOWING |
| confirm approve | formal fields | pending `change_proposals[].after` | Yes — `_apply_proposal_to_formal` | ✓ FLOWING |

### Behavioral Spot-Checks

| Behavior | Command | Result | Status |
| -------- | ------- | ------ | ------ |
| Service + writeback + callback + durable | `uv run pytest tests/repositories/test_charter_service.py tests/repositories/test_charter_draft_writeback.py tests/subagent/test_summary_callback_charter_enqueue.py tests/durable/test_charter_draft_task.py -q --reuse-db` | **60 passed** in ~166s | ✓ PASS |
| API + confirm-gate | `uv run pytest tests/repositories/test_charter_api.py tests/services/process_runtime/test_blueprint_confirm_gate.py -q --reuse-db` | **47 passed** in ~201s | ✓ PASS |
| Runner schema charter | `uv run pytest tests/test_216_02_repo_summary.py -k charter -q` (task/) | **1 passed** | ✓ PASS |

### Probe Execution

| Probe | Command | Result | Status |
| ----- | ------- | ------ | ------ |
| — | — | No phase-declared probes | SKIPPED |

### Requirements Coverage

| Requirement | Source Plan | Description | Status | Evidence |
| ----------- | ---------- | ----------- | ------ | -------- |
| CHARTER-RUNNER-01 | 01 | Runner 一等产出 charter | ✓ SATISFIED | Schema + prompt 0012 + callback apply branch |
| CHARTER-BASELINE-01 | 01 | 基线固定 | ✓ SATISFIED | Existing-row automation freeze + tests |
| CHARTER-GATE-01 | 01 | material fingerprint gate | ✓ SATISFIED | Equal skip + persist + repeat regression |
| CHARTER-APPEND-01 | 01 | appendices-only automation | ✓ SATISFIED | classify → appendices for new key / citation-only |
| CHARTER-PROPOSAL-01 | 01 | proposals + human approve | ✓ SATISFIED | change_proposals + confirm approve/reject |
| CHARTER-COMPAT-01 | 01 | 不改写生产数据 | ✓ SATISFIED | Migration AddField-only; legacy locked_at first-touch without body rewrite |

### Anti-Patterns Found

| File | Line | Pattern | Severity | Impact |
| ---- | ---- | ------- | -------- | ------ |
| `server/services/process_runtime/blueprint_confirm_gate.py` | ~14–16 | Module docstring still says human_confirmed automation writes `draft_content` | ℹ️ Info | Behavior fixed via writeback; docstring drift only |
| `server/services/process_runtime/blueprint_confirm_gate.py` | ~983–984 | Comment still claims ai_draft in-place formal merge | ℹ️ Info | Guard path for empty domain remains; comment outdated |
| `server/tests/repositories/test_charter_service.py` | ~518–549 | `test_manual_draft_without_fingerprint_preserves_stored` middle branch `del second` without assert | ℹ️ Info | Production `resolve_fingerprint_for_repository` still preserves stored; weak middle assertion only |

No `TBD`/`FIXME`/`XXX` blockers in modified charter paths.

### Human Verification Required

None. Goal is backend contract + migration safety + API/callback trees covered by automated tests. Live Runner→summary E2E against a real repo is optional operational smoke outside this phase’s must-haves.

### Gaps Summary

No blocking gaps. All six must-have truths are implemented and covered by focused tests (108 passed across the suites above). Minor docstring/comment drift in `blueprint_confirm_gate.py` does not affect runtime behavior.

---

_Verified: 2026-08-16T17:35:00Z_
_Verifier: Claude (gsd-verifier)_
