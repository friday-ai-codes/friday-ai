---
phase: 43
slug: env-resume
status: planned
nyquist_compliant: true
wave_0_complete: true
created: 2026-06-16
---

# Phase 43 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution. Derived from 43-RESEARCH.md `## Validation Architecture`.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest 9.x + pytest-asyncio (`asyncio_mode=auto`) + pytest-django (`DJANGO_SETTINGS_MODULE=friday.settings`) |
| **Config file** | `server/pyproject.toml` `[tool.pytest.ini_options]` (`testpaths=["tests"]`, `--disable-socket --allow-unix-socket`) |
| **Quick run command** | `cd server && uv run pytest tests/test_coding_node.py tests/services/test_research_completion_callback.py -x` |
| **Full suite command** | `cd server && uv run pytest` |
| **Estimated runtime** | ~60-120 seconds (quick) / full suite minutes |

DB marker: `@pytest.mark.django_db(transaction=True)` (async + multi-coroutine callbacks). Network isolation enforced via `pytest-socket`; container/runner/LLM fully mocked at IO boundary.

---

## Sampling Rate

- **After every task commit:** Run `cd server && uv run pytest tests/test_coding_node.py tests/services/test_research_completion_callback.py -x`
- **After every plan wave:** Run `cd server && uv run pytest tests/test_coding_node.py tests/services/ tests/workflows/test_plan_research_node.py tests/agents/test_start_plan_research_tool.py tests/services/test_orchestration_entry_consistency.py`
- **Before `$gsd-verify-work`:** Full suite (`cd server && uv run pytest`) must be green
- **Max feedback latency:** ~120 seconds

---

## Per-Task Verification Map

| Task ID | Plan | Wave | Requirement | Threat Ref | Secure Behavior | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|------------|-----------------|-----------|-------------------|-------------|--------|
| 43-01-* | 01 | 1 | PF-06 | T-43-INFO (token leak) | token 仅进 dispatch payload，日志只 `has_*` 布尔 | unit | `cd server && uv run pytest tests/test_coding_node.py -k "git_env or branch_strategy or ssh_https or no_token_leak" -x` | ❌ W0 | ⬜ pending |
| 43-02-* | 02 | 2 | RESUME-01 | T-43-TAMPER (entrypoint 守门) | chat 续驱须 `PlanSession.entrypoint==chat` 守门 + task 归属校验 | integration | `cd server && uv run pytest tests/services/test_research_completion_callback.py -x` | ❌ W0 | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

---

## Wave 0 Requirements

> **No separate Wave 0 plan.** Test infrastructure is embedded via TDD inside the implementing plans — 43-01 Task 1 writes RED PF-06 assertions before Task 2 implements; 43-02 Task 2 unit-tests the shared helper; 43-03 Task 2 adds the closed-loop integration tests. The framework (pytest + asyncio + django + socket isolation) is already present, so the "Wave 0" coverage below is satisfied within Waves 1–2 rather than a dedicated wave.

- [x] `tests/test_coding_node.py` — extend with PF-06 dispatch metadata env assertions (git token env + branch strategy + target branch + SSH→HTTPS + no-token degrade + no-leak). Existing file with dispatch mock patterns (see `tests/chat/test_coding_exclusion_env.py` env-key style, `tests/test_coding_anthropic_base_url_passthrough.py`). → **43-01 Task 1 (RED-first)**.
- [x] `tests/services/test_research_completion_callback.py` — extend with chat-entry resume + barrier reflow closed-loop tests (existing `_setup` chat-entry fixture + `_PATCHES` mock patterns; mock merge adapter to drive merging→done). → **43-03 Task 2**.
- [x] `tests/services/test_plan_resume_driver.py` (new, helper lands in `services/plan_orchestration/resume.py`) — unit tests for advance loop (terminal returns / researching-pending short-circuit / clarifying-pending short-circuit / step-limit fail). → **43-02 Task 2**.

*Framework already present — no install needed.*

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| 真实 runner + Docker 容器端到端 resume（私有仓 clone + 正确分支 + 调研容器在途完成驱动 chat/workflow 续跑） | PF-06, RESUME-01 | 需真实 runner + Docker + 任务容器 + 真实编码/调研 agent（本地无法闭环，沿用 STATE.md Deferred Items） | 真实环境派发编码/调研容器，观察私有仓 clone 成功 + 落正确目标分支 + 容器完成后会话/工作流自动续跑到 done |

---

## Validation Sign-Off

- [x] All tasks have `<automated>` verify or Wave 0 dependencies (every task across 43-01..43-04 carries an `<automated>` command)
- [x] Sampling continuity: no 3 consecutive tasks without automated verify
- [x] Wave 0 covers all MISSING references (test infra embedded via TDD in implementing plans — no separate Wave 0 plan)
- [x] No watch-mode flags
- [x] Feedback latency < 120s (quick run ~60-120s)
- [x] `nyquist_compliant: true` set in frontmatter

**Note:** Test infrastructure is embedded via TDD inside the implementing plans (43-01 Task 1 is RED-first; 43-02/43-03 add helper unit + callback integration tests). No standalone Wave 0 plan is required; sampling continuity is satisfied because each implementing task has an `<automated>` verify.

**Approval:** approved
