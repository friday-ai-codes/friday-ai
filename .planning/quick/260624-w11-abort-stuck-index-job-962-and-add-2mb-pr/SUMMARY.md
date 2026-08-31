---
audit_acknowledged:
  milestone: v0.25.0
  at: 2026-08-31
  status: unknown
---

# Summary

- Aborted production Procrastinate job `962` via `finish_job_by_id_async(..., ABORTED)` after killing/restarting `friday-worker` to stop the stuck parser process.
- Verified the worker registered as `worker_id=13` and resumed consuming index jobs.
- Copied the patched `indexer.py` into the running remote `friday-worker`, `friday-server`, and `friday-scheduler` containers as a temporary hotpatch; the worker process still needs a restart after the current job if immediate runtime activation is required.
- Added a 2MB pre-parse guard in `server/services/indexer.py`; skipped files are recorded as enabled per-repo `RepoExclusionRule` entries using exact regex patterns with source `ai_suggested`.
- Applied the guard to full, git-diff, incremental, and branch overlay parse paths, and kept graph indexing from re-parsing skipped large files.
- Added regression coverage for full indexing so a `huge.json` over 2MB never reaches `parse_file_dual`, never enters `FileIndex`, and creates the exclusion rule.

# Verification

- `uv run ruff check services/indexer.py tests/services/test_indexer_exclusion.py`
- `uv run pytest tests/services/test_indexer_exclusion.py`
