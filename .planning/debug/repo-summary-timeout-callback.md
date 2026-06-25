---
status: resolved
trigger: "Remote Friday AI repo_summary tasks keep timing out; task completion callbacks are rejected as terminal while pending work remains."
created: 2026-06-25
updated: 2026-06-25
---

# Debug Session: repo-summary-timeout-callback

## Symptoms

- Expected behavior: repo_summary queue drains until pending tasks are completed, cancelled, or failed with useful errors.
- Actual behavior: runner keeps accepting repo_summary tasks, but many sessions are marked timeout before the task callback completes; callbacks log `completed_session_not_found_or_terminal` or `failed_session_not_found_or_terminal`.
- Error messages: server logs show `completed_session_not_found_or_terminal` and `failed_session_not_found_or_terminal` for recently accepted `reposummary-*` task ids.
- Timeline: observed after scaling extra workers and restoring queue progress on 2026-06-25.
- Reproduction: run the remote queue, watch `subagent_subagentsession`, `runner_task_assignments`, runner logs, and task containers.

## Current Focus

- hypothesis: running repo_summary sessions are timed out based on stale or missing heartbeat/update fields before the runner completion callback arrives; terminal session handling also leaves assignment rows running/assigned.
- test: inspect recovery/timeout logic and runner callback handlers, then verify with live DB/log evidence.
- expecting: timeout thresholds or stale-session filters include active runner-assigned tasks with no heartbeat; callback path refuses terminal sessions without closing assignments.
- next_action: inspect server-side repo_summary recovery, timeout, and runner callback code.
- reasoning_checkpoint:
- tdd_checkpoint:

## Evidence

- timestamp: 2026-06-25T09:40:34+08:00
  observation: Procrastinate has 5 live workers, no todo/doing jobs, and index queue has only succeeded/aborted jobs.
- timestamp: 2026-06-25T09:40:34+08:00
  observation: repo_summary session counts include pending=112, running=18, timeout=4375; runner_task_assignments include assigned=200 and running=268.
- timestamp: 2026-06-25T09:40:34+08:00
  observation: runner/server logs repeatedly show completion/failure callbacks rejected because the session is already terminal timeout.
- timestamp: 2026-06-25T09:50:12+08:00
  observation: capacity-limited manual recovery dispatched 6 sessions; concurrent periodic recovery also dispatched 6, exposing that runner DB concurrent was higher than actual runner config.
- timestamp: 2026-06-25T09:55:11+08:00
  observation: after runner cleanup and hotpatch, periodic recovery created 8 active assignments and real runner containers began processing them.
- timestamp: 2026-06-25T09:58:00+08:00
  observation: a new repo_summary completed successfully and wrote summary/tree; runner stayed online with current_tasks=2 and no index queue backlog.

## Eliminated

- hypothesis: index queue is blocking all work
  reason: Procrastinate jobs have no todo/doing rows and index queue has no active job.

## Resolution

- root_cause: recover_stranded_summaries treated RUNNING sessions with stale updated_at as stranded, so it timed out live repo_summary tasks before their runner callbacks completed. It also timed out all active sessions for a repo when any older stranded session existed, and recovery dispatched more sessions than the runner could immediately run, leaving work in process-local dispatcher queues.
- fix: RUNNING sessions now use hard started_at timeout only; older stranded sessions no longer kill newer active sessions; timeout cleanup closes active runner assignments; recovery dispatch is capped by real available runner capacity including DB active assignments. Remote runner DB concurrent was aligned to its actual config value of 2.
- verification: uv run ruff check repositories/summary_service.py tests/test_repo_summary_recovery.py; uv run pytest tests/test_repo_summary_recovery.py; remote Procrastinate queue had no todo/doing index jobs; repo_summary completed successfully after hotpatch.
- files_changed: server/repositories/summary_service.py; server/tests/test_repo_summary_recovery.py
