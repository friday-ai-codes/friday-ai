---
status: resolved
trigger: "帮我完全排查、修复好"
created: 2026-08-19
updated: 2026-08-19T18:36:00+08:00
---

# Debug Session: repo-plan-poisoned-resume

## Symptoms

- Expected behavior: blueprint `repo_plan` agents submit schema-valid RepoPlan through MCP; transient provider/socket failures retry from safe context; every failed/stale branch either redispatches within bounds or advances with an explicit unresolved item; merge then accepts `support_repository_id` when it uniquely maps to a locked association (UUID, full `repository_name`, or unique basename). Only truly absent repos block.
- Actual behavior (wave 1): blueprint `7b67b615-8830-4980-bf0f-3572fded41fa` reaches `repo_plan`, but `frontend/onion-learning` and `backend/study-course` repeatedly explore successfully then fail at the final RepoPlan submission. Tasks become stale/failed, barrier can deadlock, and the whole convergence session ends `failed` with 7/9 plans.
- Actual behavior (wave 2): after prior fixes, live session safely advanced from `repo_plan` to `merge` and paused at `waiting_clarification`. Merge opened a blocking clarification with four missing support references. `support_repository_id=onion-learning` is a false positive because locked repo `frontend/onion-learning` (UUID `050e49b2-...`) exists. `course-business` and `backend/course-business` identify the same actually absent repo; `onion-auth` is absent.
- Error messages: `API Error: The socket connection was closed unexpectedly`; later `Missing required field in assistant message: 'thinking'`; `repo_plan_invalid_retrying`; `container_failed`; `process.session.failed`; later `missing_support_repos` / `support_repo_missing` for resolvable aliases; `advance_step_limit`.
- Timeline: first failures around 2026-08-19 15:27–15:31; redispatches through 17:03; 8/8 plans then self-spin to `advance_step_limit`; merge alias false positives after advancing to merge.
- Reproduction: session `4d6984c4-cbab-4ae3-ba5f-d49f5dfd5eb6` / artifact `7b67b615-8830-4980-bf0f-3572fded41fa`. Do not mutate the live session from this debug close.

## Current Focus

- hypothesis: confirmed — eight coupled contracts across resume/retry, event-specific pause, and UUID-only support-repo closure.
- test: non-live 145-test alias/merge/reconcile/review verification accepted; earlier resume/state-machine suites also passed.
- expecting: post-deploy operator recovery removes/replaces stale alias false-positive threads and reruns merge; true missing-repo questions stay for humans.
- next_action: none — session resolved; live session 4d6984c4 must not be mutated until operator recovery is explicitly authorized after deploy.

## Evidence

- timestamp: 2026-08-19T17:12:00+08:00
  observation: Current session is `repo_plan/failed`: 7 tasks done, `frontend/onion-learning` and `backend/study-course` failed.
- timestamp: 2026-08-19T18:02:00+08:00
  observation: New live evidence shows all 8/8 RepoPlans present and task DONE, followed by exactly 20 needs_clarification events and process.session.failed reason=advance_step_limit.
- timestamp: 2026-08-19T18:10:00+08:00
  observation: StageDef wait_status forced repo_plan needs_clarification into WAITING_EVENT; indirect degraded synthesis opened a blocking thread.
- timestamp: 2026-08-19T18:22:00+08:00
  observation: After pause fix, live session at merge/waiting_clarification with four missing_support_repos; onion-learning is a locked-repo alias false positive.
- timestamp: 2026-08-19T18:30:00+08:00
  observation: Shared `blueprint_repo_alias` resolver + merge canonicalization; focused 38 + adjacent 107 = 145 tests passed; ruff check/format passed; no live mutation; no commit.
- timestamp: 2026-08-19T18:36:00+08:00
  observation: Human accepted 145-test non-live verification; deferred stale-clarification cleanup and merge rerun as guarded post-deploy operator recovery; forbade auto-answering true missing-repository business questions.

## Eliminated

- hypothesis: repeated failures are solely caused by low runner concurrency or duplicate runner services
  reason: those issues were fixed and subsequent containers ran normally, but the two heavy repos still failed at the same final SDK/provider step.
- hypothesis: onion-learning false positive is a missing association
  reason: locked repo frontend/onion-learning exists; failure is UUID-only closure, not membership.

## Resolution

- root_cause: |
    Eight coupled contracts:

    1–6. Unsafe cross-mode/malformed SDK resume; late SDK ID capture; retry callbacks without wakeup; naked failed accepted by the barrier; unbounded structured submit and generic repo-plan limits.
    7. repo_plan has two self-loop events with different pause semantics, but StageDef exposed only one wait_status, forcing needs_clarification into WAITING_EVENT (advance_step_limit). Indirect degraded synthesis also opened a blocking thread unlike the direct callback path.
    8. reconcile_cross_repo_apis and blueprint_review.check_api_closure compared support_repository_id only to association UUIDs. Merge persisted raw RepoPlan aliases (full/short names) without canonicalizing unique matches, so locked `frontend/onion-learning` was reported missing as `onion-learning`.
- fix: |
    Resume is mode/source + mcp_submit_ok + JSONL/thinking validated; stable SDK UUIDs; bounded redispatch then schema-valid degraded RepoPlans; barrier requires an actual repo_plan section; MCP schema closed/bounded; repo-plan 100 max_turns / 45min timeout. StageDef event_wait_statuses: needs_clarification → WAITING_CLARIFICATION, plan_dispatched → WAITING_EVENT. Indirect degraded clarifications are nonblocking.

    New pure `blueprint_repo_alias.resolve_repository_alias`: exact UUID, exact repository_name, unique basename; ambiguous basename unresolved; strip-only whitespace; case-sensitive. Merge calls canonicalize_contract_support_repository_ids before reconcile; _apply_needs_support canonicalizes hints. Reconcile and review share is_resolvable_repository_alias.
- verification: |
    Wave 1: focused 55 server + 32 task (3 skipped); adjacent 59 + 83 process-graph/callback tests. Wave 2: focused 38 alias/reconcile/review/merge tests + adjacent 107 merge/reconcile/review = 145 passed; ruff check + ruff format --check passed. Human accepted the 145-test non-live verification. Live session 4d6984c4 / artifact 7b67b615 was not mutated. No git commit.
- files_changed:
    - server/chat/sdk_resume.py
    - server/delivery/services/convergence_session_service.py
    - server/services/process_runtime/registry.py
    - server/services/process_runtime/builtin_processes.py
    - server/services/process_runtime/blueprint_research_adapter.py
    - server/services/process_runtime/blueprint_repo_plan.py
    - server/services/process_runtime/blueprint_repo_alias.py
    - server/services/process_runtime/blueprint_reconcile.py
    - server/services/process_runtime/blueprint_review.py
    - server/services/process_runtime/blueprint_merge.py
    - server/subagent/api/callbacks.py
    - server/tests/test_sdk_resume.py
    - server/tests/delivery/test_blueprint_repo_resume.py
    - server/tests/services/process_runtime/test_blueprint_process_graph.py
    - server/tests/services/process_runtime/test_blueprint_repo_plan_stage.py
    - server/tests/services/process_runtime/test_blueprint_repo_alias.py
    - server/tests/services/process_runtime/test_blueprint_reconcile.py
    - server/tests/services/process_runtime/test_blueprint_review_rules.py
    - server/tests/services/process_runtime/test_blueprint_merge_stage.py
    - server/tests/subagent/test_blueprint_repo_plan_callback.py
    - task/core/agent_submit_mcp.py
    - task/core/executor.py
    - task/tests/test_agent_submit_mcp.py
    - task/tests/test_explore_structured_submit.py
    - task/tests/test_claude_sdk_integration.py
- recovery_procedure: |
    Post-deploy only. Do not run before alias-closure + prior resume/pause fixes are deployed. Do not mutate the live session from this debug close. Do NOT auto-answer true missing-repository business questions (whether to add onion-auth / course-business to locked associations, or rewrite contracts).

    IDs:
    - ConvergenceSession: 4d6984c4-cbab-4ae3-ba5f-d49f5dfd5eb6
    - Artifact: 7b67b615-8830-4980-bf0f-3572fded41fa
    - Expected healthy set: 8 DONE tasks with valid PartialPlan.content.repo_plan
    - Alias classification on the stale merge clarification:
      - FALSE POSITIVE (remove/replace, not a business answer): onion-learning → locked frontend/onion-learning UUID 050e49b2-...
      - SAME absent repo (keep as one human question after rerun): course-business and backend/course-business
      - TRULY ABSENT (keep for human): onion-auth

    1. Deploy server+task with this fix; confirm a single runner (ai.friday.runner.dev).
    2. Dry-run inspect (read-only):
       uv run python manage.py shell
       Load session 4d6984c4. Print status, current_stage (expect merge / waiting_clarification), current_artifact_version (must remain 7b67b615). Confirm 8/8 DONE tasks still have valid repo_plan sections.
    3. Abort if any DONE task lacks a valid repo_plan, plan count is not 8/8, or the artifact id drifted. Do not mark_stale. Do not redispatch repo_plan.
    4. List open+blocking BlueprintThread rows on the artifact with return_stage=merge (kind=ai_clarification). Identify the stale missing_support_repos thread that lists onion-learning alongside true absences.
    5. Operator cleanup of the STALE thread only (this is not answering the business question):
       a. BlueprintLifecycleService().resolve_thread(thread, resolution="operator: stale alias false-positive after canonicalize; rerun merge", initiated_by_user_id=<operator>, dismissed=True)
          Dismiss rather than resolve-as-accepted so it is not treated as a human decision to drop onion-auth / course-business.
       b. Do not call record_answer with invented repository UUIDs. Do not silently add onion-auth or course-business to repo_associations.
    6. Apply exactly once after the stale blocking thread is dismissed:
       a. ConvergenceSessionService().arewind_to_stage(session, stage="merge", reason="operator: rerun merge after alias canonicalize; preserve 8/8 repo plans")
       b. If applied is False, stop (concurrent driver already moved the row).
       c. Build the deployed blueprint engine and call adrive_blueprint_session_to_pause_or_terminal(engine, fresh_session) once. Do not mark tasks stale and do not dispatch containers.
    7. Success:
       - onion-learning is not re-flagged (canonicalizes to locked frontend/onion-learning).
       - If onion-auth and/or course-business remain unresolved, merge re-opens a blocking clarification listing only those true absences, session pauses at merge/waiting_clarification, and a human decides whether to add associations or rewrite contracts.
       - If no true absences remain, merge proceeds without a missing_support_repos thread.
    8. Optional later: a fresh isolated blueprint (not this session) to operator-verify resume/degraded/alias paths end-to-end.
