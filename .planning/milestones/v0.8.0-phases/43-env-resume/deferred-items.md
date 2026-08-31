# Phase 43 — Deferred / Out-of-Scope Items

## Pre-existing test failure (out of scope for 43-02)
- status: acknowledged


- **Test:** `server/tests/services/test_dependency_cache.py::TestGetVolumeName::test_get_volume_name_format`
- **Discovered during:** 43-02 regression run (`uv run pytest tests/services/`)
- **Why out of scope:** Unrelated to `plan_orchestration` — concerns Docker dependency-cache
  volume name formatting. 43-02 only touches `services/plan_orchestration/resume.py`,
  its barrel `__init__`, and a new unit test. Not caused by this plan's changes.
- **Action:** Logged, not fixed (executor scope boundary). Address separately if needed.
