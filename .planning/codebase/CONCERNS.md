# Codebase Concerns

**Analysis Date:** 2026-06-05

> Scope: full repo. Polyglot project — Django/DRF backend (`server/`), Python task runtime (`task/`), Go runner/orchestrator (`runner/`), Vue 3 + TS frontend (`web/`).

## Tech Debt

**Oversized modules (single-responsibility erosion):**
- Issue: Several modules far exceed maintainable size, mixing routing, business logic, and serialization in one file. Hard to test, review, and modify safely.
- Files:
  - `server/services/indexer.py` (3562 lines)
  - `server/chat/views.py` (2435 lines)
  - `server/workflows/api/views.py` (1902 lines)
  - `server/mcp_tools/views.py` (1809 lines)
  - `server/workflows/engine/scheduler.py` (1734 lines)
  - `server/chat/conversation_service.py` (1707 lines)
  - `web/src/stores/chat.ts` (2376 lines)
  - `web/src/components/chat/ChatMessageBubble.vue` (1959 lines)
  - `web/src/components/chat/ChatInput.vue` (1175 lines)
- Impact: High cognitive load, merge conflicts, slow review, easy to introduce regressions; large Vue SFCs hurt frontend build/HMR performance.
- Fix approach: Extract cohesive concerns into submodules/composables. For Django views, split into ViewSet + service-layer modules per resource; for `chat.ts`, split runtime/parts/clarification slices (test files already hint at this seam: `chat.runtime.spec.ts`, `chat.parts.spec.ts`, `chat.clarification.spec.ts`).

**Compat adapter carries explicit migration debt:**
- Issue: `server/compat/request_handler.py` keeps a `LayeredSearchService` alias purely as a test-patch entry point while real calls delegate to `HybridSearchService`. Module docstring (lines 1-12) flags this as temporary until the provider test matrix migrates.
- Files: `server/compat/request_handler.py`
- Impact: Indirection that exists only to keep legacy tests green; confusing for new contributors.
- Fix approach: Migrate `patch()` targets in `server/tests/compat/test_adapter.py` to `HybridSearchService`, then delete the alias.

**Broad exception swallowing:**
- Issue: ~431 `except Exception` blocks across `server/` and `task/`. Many log-and-continue paths (e.g. `request_handler.py:136-138` silently degrades RAG retrieval failures to plain LLM calls).
- Files: widespread; `server/compat/request_handler.py:136`, plus 430 others.
- Impact: Real errors masked, harder debugging, silent degradation of features without surfacing to operators.
- Fix approach: Narrow exception types where the failure mode is known; ensure broad catches re-raise or emit metrics/alerts, not just `logger.warning`.

**Type-checker suppressions despite mypy in the stack:**
- Issue: ~419 `# noqa` / `# type: ignore` occurrences in `server/` and `task/` even though `mypy`, `django-stubs`, and `djangorestframework-stubs` are project dependencies.
- Files: widespread across `server/`, `task/`.
- Impact: Erodes the value of static typing; suppressions accumulate and hide genuine type errors.
- Fix approach: Audit suppressions, add specific error codes (`# type: ignore[code]`), and burn down untyped boundaries incrementally.

**Stray `print()` in production code paths:**
- Issue: ~40 `print(` calls in `server/`/`task/` outside tests, scripts, and management commands, despite `structlog` being the standard.
- Files: scattered in `server/`, `task/`.
- Impact: Unstructured output bypasses logging config, log levels, and aggregation.
- Fix approach: Replace with `structlog` logger calls.

## Known Bugs

No confirmed runtime bugs were reproduced during this static pass. The codebase has only a handful of inline `TODO`/`FIXME` markers (~10 actionable, the rest are placeholder strings like `doxcnXXXX` in docstrings). Notable open items:
- `web/src/components/workflow/validation/IssuesPanel.vue:24` — warning-click handler not wired to graph centering (TODO).
- `web/src/components/prompts/PromptEditor.vue:195` — `change_note` input deferred; `useConfirmDialog` lacks input-slot support (TODO).
- `server/workflows/engine/scheduler.py:1414` — callback-path method flagged with a TODO note for the Docker/container node path.

## Security Considerations

**Container sandbox has no resource limits or hardening (highest priority):**
- Risk: The Go runner launches task containers (which run LLM/agent-generated code) with **no** `Memory`, `NanoCPUs`, `PidsLimit`, `security_opt`, `cap_drop`, `ReadonlyRootfs`, or `Privileged` constraints in `HostConfig` (verified: those keys are absent). Additionally `ExtraHosts: host.docker.internal:host-gateway` lets task containers reach host services, and `GIT_SSL_NO_VERIFY=true` disables TLS verification for git operations.
- Files: `runner/internal/docker/executor.go:53-88` (container create), `:67-70` (HostConfig), `:117` (`GIT_SSL_NO_VERIFY=true`)
- Current mitigation: Container lifecycle timeout via `WaitContainer` (`executor.go:144-161`); a `git-wrapper.sh` intercepts git writes via `FRIDAY_TASK_MODE`.
- Recommendations: Add memory/CPU/PID limits, `--cap-drop=ALL` + minimal adds, `--security-opt=no-new-privileges`, read-only rootfs with explicit writable mounts, restrict/segment network egress, and remove `host.docker.internal` access unless required. Fix git TLS verification rather than disabling it.

**Secrets injected as plaintext container env vars:**
- Risk: Provider API keys are passed into task containers as env vars (e.g. `env_FRIDAY_TASK_CLAUDE_API_KEY=sk-...`) via `task.Payload["metadata"]`. Env vars are visible to any process in the container and via `docker inspect`.
- Files: `runner/internal/docker/executor.go:120-131`, `:90-119`
- Current mitigation: Containers are per-task and short-lived.
- Recommendations: Prefer mounted secret files (tmpfs) or a short-lived broker token over long-lived provider keys in env; scope/rotate keys.

**IDOR in the OpenAI-compat retrieval path:**
- Risk: `prepare_messages` passes caller-supplied `repository_ids` straight into `LayeredSearchService.search` without verifying the caller may access each repository (no `PermissionService.has_repository_access` check). An attacker could read arbitrary repository code snippets.
- Files: `server/compat/request_handler.py:120-127` (explicit `TODO(security mitigation)` at line 120)
- Current mitigation: None in the retrieval call itself.
- Recommendations: Filter `repository_ids` through a per-caller permission check before search; gate behind authenticated access.

**OpenAI-compat endpoints default to AllowAny:**
- Risk: `OptionalBearerTokenAuth` returns `True` (open access) whenever `OPENAI_COMPAT_API_KEYS` is empty — the default. Combined with the IDOR above, an unconfigured deployment exposes code-context retrieval to anyone who can reach the endpoint.
- Files: `server/compat/auth.py:26-30`, applied in `server/compat/views.py:55,172`
- Current mitigation: When configured, token comparison correctly uses `hmac.compare_digest` (timing-safe).
- Recommendations: Fail closed (deny when whitelist unset) or require explicit opt-in; document the security implication prominently.

**Encryption key derivation falls back to `SECRET_KEY`; failures silently return plaintext:**
- Risk: `_derive_fernet_key()` derives the Fernet key from `FRIDAY_ENCRYPTION_KEY` or, if unset, `SECRET_KEY`. Rotating `SECRET_KEY` would render all stored encrypted credentials undecryptable. Worse, `decrypt_value` catches `InvalidToken`/`ValueError` and **returns the input unchanged** ("plaintext fallback"), so a key mismatch or corrupted ciphertext silently yields garbage instead of erroring.
- Files: `server/common/encryption.py:22-40` (derivation), `:54-` (decrypt fallback)
- Current mitigation: Intentional backward-compat path for pre-v21 plaintext rows.
- Recommendations: Require a dedicated `FRIDAY_ENCRYPTION_KEY` decoupled from `SECRET_KEY`; add a version/prefix marker so true ciphertext that fails to decrypt raises loudly rather than returning plaintext.

**Production config guards are present (positive note):**
- `server/friday/settings.py:69-74` raises `ImproperlyConfigured` if production runs with `DEBUG=True`, default `SECRET_KEY`, or wildcard `ALLOWED_HOSTS`. CI includes secret scanning and `.env` is gitignored. Maintain these.

## Performance Bottlenecks

**Monolithic indexer / synchronous-to-async bridging:**
- Problem: `server/services/indexer.py` (3562 lines) drives repository indexing with heavy `sync_to_async` wrapping over Django ORM and external services (Qdrant, tree-sitter, git). Large single-module orchestration makes hot paths hard to profile and parallelize.
- Files: `server/services/indexer.py`
- Cause: ORM calls bridged into async context; per-file hashing/parsing/embedding in long sequential flows.
- Improvement path: Batch ORM operations, profile embedding/Qdrant upserts, and consider bounded concurrency for file parsing.

**Very large frontend bundles for chat:**
- Problem: `web/src/stores/chat.ts` (2376) and `ChatMessageBubble.vue` (1959) are large reactive surfaces re-rendered on streaming updates.
- Files: `web/src/stores/chat.ts`, `web/src/components/chat/ChatMessageBubble.vue`
- Cause: Monolithic store + bubble component handling all message part types.
- Improvement path: Split store slices, memoize/virtualize message lists, lazy-load heavy bubble subcomponents.

## Fragile Areas

**Go runner orchestration is nearly untested:**
- Files: `runner/internal/docker/executor.go`, `runner/internal/ws/client.go` (492 lines), `runner/internal/scheduler/scheduler.go`, `runner/internal/callback/server.go`
- Why fragile: The runner handles container lifecycle, WebSocket dispatch, and host-facing callbacks — security- and reliability-critical — but only **1** `*_test.go` file exists in the entire `runner/` tree.
- Safe modification: Add table-driven tests around `buildContainerEnv`, container create/wait/kill, and WS reconnection before changing behavior; test with a fake Docker client implementing the `client.APIClient` interface.
- Test coverage: Effectively absent for orchestration logic.

**Compat layer's test-patch coupling:**
- Files: `server/compat/request_handler.py`, `server/tests/compat/test_adapter.py`
- Why fragile: Tests patch a compatibility alias rather than the real service; refactors that touch the alias break tests for non-obvious reasons.
- Safe modification: Migrate patch targets first (see Tech Debt), then refactor.

**Encryption backward-compat fallback:**
- Files: `server/common/encryption.py`
- Why fragile: Silent plaintext fallback (see Security) means encryption regressions can pass tests and run in prod undetected.
- Safe modification: Add explicit ciphertext markers and round-trip tests covering key-rotation and corrupted-token cases.

## Scaling Limits

**Single-host Docker execution model:**
- Current capacity: Tasks run as local Docker containers on the runner host; concurrency bounded by host CPU/RAM (and, since there are no per-container limits, by noisy-neighbor effects).
- Limit: No Kubernetes/cluster scheduling yet (the `Executor` interface in `executor.go:25-33` is documented as "为 K8s 预留" / reserved for K8s but not implemented).
- Scaling path: Implement a K8s-backed `Executor` and enforce per-task resource requests/limits.

## Dependencies at Risk

**Bleeding-edge Python runtime requirement:**
- Risk: `server/pyproject.toml` requires `requires-python = ">=3.14"`; the resolved `.venv` uses Python 3.14. This is a very new runtime with a narrower ecosystem/wheel availability surface.
- Impact: Some third-party packages may lack 3.14 wheels; contributor onboarding friction.
- Migration plan: Confirm all deps publish 3.14 wheels; consider supporting 3.12/3.13 to widen the contributor base, or document the hard 3.14 requirement clearly.

**Fast-moving LLM/agent SDKs:**
- Risk: `claude-agent-sdk>=0.1.58,<0.2`, `anthropic>=0.40.0`, `google-genai`, `llama-index>=0.10.0` evolve rapidly with breaking changes.
- Impact: Pre-1.0 SDKs (claude-agent-sdk) can break on minor bumps.
- Migration plan: Pin tighter ranges, add contract tests around the agent/runner boundary, watch upstream changelogs.

## Missing Critical Features

**Authentication-by-default on compat endpoints:**
- Problem: OpenAI-compat surface is open unless an env var is configured (see Security).
- Blocks: Safe default deployment of the OpenAI-compatible API.

**Network egress control for task containers:**
- Problem: No network policy/egress restriction on agent-run containers.
- Blocks: Safe execution of untrusted/generated code without data-exfiltration risk.

## Test Coverage Gaps

**Go runner (orchestration & sandbox):**
- What's not tested: Container create/wait/kill/cleanup, env construction, WS client reconnection, callback server.
- Files: `runner/internal/docker/executor.go`, `runner/internal/ws/client.go`, `runner/internal/callback/server.go`
- Risk: Regressions in security-critical container handling go unnoticed.
- Priority: High

**Security-path coverage (auth/IDOR/encryption):**
- What's not tested: Permission filtering on `repository_ids` in the compat path; encryption key-rotation / corrupted-token behavior.
- Files: `server/compat/request_handler.py`, `server/common/encryption.py`
- Risk: Silent data exposure or silent plaintext fallback.
- Priority: High

**Note on Python/Frontend coverage (positive):**
- The backend has ~509 `test_*.py` files (including e2e under `server/tests/e2e/`) and the frontend ~127 `*.spec.ts`/`*.test.ts` files. Backend and frontend coverage is broad; the gap is concentrated in the Go runner and specific security paths above.

---

*Concerns audit: 2026-06-05*
