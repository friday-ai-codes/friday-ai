---
phase: 11-rtool
reviewed: 2026-06-10T02:40:00Z
depth: deep
files_reviewed: 7
files_reviewed_list:
  - task/core/remote_tools.py
  - task/core/config.py
  - task/core/executor.py
  - runner/internal/docker/executor.go
  - server/workflows/nodes/ai/coding.py
  - task/tests/test_remote_tools.py
  - server/tests/test_remote_tool_dispatch.py
findings:
  critical: 0
  warning: 4
  info: 4
  total: 8
resolved:
  warning: 4
  info_acknowledged: 4
status: clean
fix_summary: "WR-01..04 resolved (atomic commits); IN-01..04 acknowledged. No actionable findings remain."
---

# Phase 11: Code Review Report (task 容器接通 / RemoteTool 链路闭环)

**Reviewed:** 2026-06-10T02:40:00Z
**Depth:** deep (cross-component: task / runner / server)
**Files Reviewed:** 7
**Status:** clean (all 4 warnings resolved; 4 info items acknowledged)

## Resolution

All actionable warnings (WR-01..04) were fixed with one atomic commit each and
covered by tests; `cd task && uv run pytest tests/test_remote_tools.py
tests/test_callback.py tests/test_claude_sdk_integration.py -q` → **46 passed,
3 skipped** (3 skipped are live-API integration tests gated by
`FRIDAY_RUN_INTEGRATION_TESTS`). Info findings IN-01..04 are acknowledged below;
none require a code change in this phase.

| ID | Status | Commit | Note |
|----|--------|--------|------|
| WR-01 | ✅ Resolved | `ded4ed07` | 200-path `resp.json()` (and non-dict body) wrapped → structured `is_error`, never raises. Test: 200 + non-JSON body returns tool error. |
| WR-02 | ✅ Resolved | `7259c926` | Mounting remote tools no longer disables builtins; `allowed_tools` now = builtin coding tools + remote tools. Test: execute-mode keeps Bash/Edit/Write/Read. |
| WR-03 | ✅ Resolved | `a5a5fd93`, `492a822e` | `tools_endpoint` validated (scheme ∈ {http,https} + host, non-str fails closed) before building the PAT-bearing MCP server. |
| WR-04 | ✅ Resolved | `6ea77f61` | `t.get("name")` + skip nameless entries in both `build_remote_tools_mcp_server` and `remote_allowed_tools`; one bad schema entry no longer crashes the task. |
| IN-01 | ☑️ Acknowledged | — | Dormant loop is the intended CONTEXT Open-Q1 Option-C decision (see note below). |
| IN-02 | ☑️ Acknowledged | — | Ignored `json.Marshal` error; safe back-compat empty value. No change this phase. |
| IN-03 | ☑️ Acknowledged | — | Per-call httpx client + magic 60s timeout; maintainability only, out of v1 scope. |
| IN-04 | ☑️ Acknowledged | — | PAT in container env is the accepted design, consistent with existing precedent. |

## Summary

Phase 11 wires a process-in-container SDK MCP server in the task executor that
calls back to the Friday server's `/api/tools/execute/` endpoint with the user's
PAT, plus the runner env passthrough and server-side dispatch metadata.

**Security verdict on the focus items — all clean, NO BLOCKER/HIGH:**

1. **PAT persistence / DB read (PAT-02): CLEAN.** `_resolve_user_pat`
   (`coding.py:812`) is a hard-coded `return ""` and never touches
   `AccessToken` / `ToolTokenBinding` / any DB table. PAT is injected only when
   a truthy `user_pat` is present, and the empty key is omitted on all three
   layers (`coding.py:890` `if user_pat:`, Go `executor.go:128` `s != ""`
   guard). The dedicated negative tests assert AccessToken is never queried and
   no `friday_pat_` lands in metadata.
2. **PAT logging: CLEAN.** task/runner/server only ever log booleans
   (`has_user_token`, `has_tools_endpoint`, `remote_tool_count`) or tool names.
   The PAT travels solely in the `Authorization: Bearer` header and the env
   injection. No `print`/structlog/zerolog statement emits the token value.
3. **RTOOL-04 graceful: MOSTLY clean.** 401/403/non-200/`httpx.HTTPError` all
   return structured `is_error` results and never raise. One residual gap:
   `resp.json()` on a 200 response is not wrapped (see WR-01).
4. **SSRF / endpoint trust: CLEAN under current design.** `tools_endpoint` is
   derived exclusively from `settings.FRIDAY_BASE_URL` (server-controlled,
   `coding.py:886`), never from `callback_url` or any untrusted source. Residual
   defense-in-depth note in WR-03.
5. **Cross-component contract: CONSISTENT.** `FRIDAY_TASK_USER_TOKEN` /
   `FRIDAY_TASK_REMOTE_TOOLS` / `FRIDAY_TASK_TOOLS_ENDPOINT` match across
   task config, runner env assembly, and server metadata; back-compat preserved
   (all fields default empty → no MCP server; legacy `FRIDAY_REMOTE_TOOLS` kept).
   Endpoint path `{base}/api/tools/execute/` matches the mounted route
   (`api/` + `tools/` + `execute/`) and the request/response shape
   (`{name, arguments}` → `{ok, result|error}`).
6. **SDK MCP correctness: CORRECT.** Naming `mcp__friday-remote-tools__{name}`,
   per-tool handler closure binds `tool_name` via function parameter (no
   late-binding loop bug), async httpx used correctly. One latent concern about
   `allowed_tools` scoping (WR-02).
7. **Go env assembly: CORRECT.** `go test ./internal/docker/` passes; no value
   logging.

Net: the secret-handling invariants that matter most are satisfied. Remaining
findings are robustness/quality and one notable functional-latency caveat
(the feature is effectively dormant end-to-end — IN-01).

## Warnings

### WR-01: `resp.json()` on a 200 response is unguarded — can raise out of the tool handler (RTOOL-04 edge)

**Status:** ✅ Resolved (`ded4ed07`). The 200-path `resp.json()` is wrapped in
`try/except ValueError` (also rejecting non-dict bodies), returning a structured
`is_error` tool result instead of raising. Test added
(`test_handler_200_non_json_returns_tool_error`).

**File:** `task/core/remote_tools.py:84`
**Issue:** The `try/except httpx.HTTPError` only wraps the `client.post` call
(lines 45–55). After a 200, `body = resp.json()` (line 84) is outside any
guard. `httpx.Response.json()` raises `json.JSONDecodeError` (a `ValueError`,
**not** an `httpx.HTTPError`) when the body is not valid JSON — e.g. a reverse
proxy / gateway / auth portal returning `200 text/html`. That exception
propagates out of the handler, violating the RTOOL-04 "handler must never raise,
always return a structured tool error" contract. The explicitly-listed cases
(401/403/non-200/transport) are handled; this is the one un-handled path.
**Fix:**
```python
if resp.status_code != 200:
    ...
try:
    body = resp.json()
except ValueError:
    logger.warning("remote_tool_bad_json", tool=tool_name, status=resp.status_code)
    return {
        "content": [{"type": "text", "text": "工具响应解析失败：非 JSON 响应"}],
        "is_error": True,
    }
```

### WR-02: `allowed_tools` set to ONLY remote tools may suppress built-in coding tools

**Status:** ✅ Resolved (`7259c926`). When the remote-tools MCP server is mounted,
`allowed_tools` is now `[*_BUILTIN_CODING_TOOLS, *remote_allowed_tools(...)]`
(builtin names mirror `server/agents/sdk/runner.py`), so builtin
Bash/Edit/Write/Read remain available. Test added
(`test_execute_mode_keeps_builtin_tools_with_remote_tools`) and the existing
integration test now asserts builtins are present.

**File:** `task/core/executor.py:305-309`
**Issue:** When the MCP server is mounted, `allowed_tools` is overwritten with
*only* the remote tool names (`remote_allowed_tools(...)` →
`["mcp__friday-remote-tools__a", ...]`). The coding agent relies on built-in
`Bash`/`Edit`/`Write`/`Read`. Depending on claude-agent-sdk allowlist
semantics, an exclusive `allowed_tools` list can restrict the agent to *only*
those tools (or de-prioritize built-ins), which would break execute-mode
coding. The integration test only asserts the list contents in `plan` mode and
does not exercise execute-mode tool availability. Under `bypassPermissions`
built-ins may still run, but this is SDK-version-dependent and unverified here.
**Fix:** Confirm SDK semantics; if `allowed_tools` is an exclusive allowlist,
append the built-in tool names the coding agent needs, e.g.:
```python
options_kwargs["allowed_tools"] = [
    "Bash", "Edit", "Write", "Read", "Glob", "Grep",
    *remote_allowed_tools(self.config.remote_tools),
]
```
Or omit `allowed_tools` and rely on `bypassPermissions` if the SDK treats an
unset list as "all tools".

### WR-03: No task-side validation of `tools_endpoint` before sending the PAT (defense-in-depth)

**Status:** ✅ Resolved (`a5a5fd93`, `492a822e`). Added `_is_valid_tools_endpoint`
(scheme ∈ {http, https} + non-empty host, non-str fails closed) mirroring
`_validate_anthropic_base_url`; `build_remote_tools_mcp_server` returns `None`
(no MCP server, no PAT injection) on an invalid endpoint. Parametrized tests
cover rejected schemes (`javascript:`/`file://`/`ftp://`/no-host) and accepted
http/https values.

**File:** `task/core/remote_tools.py:43-55`, `task/core/config.py:90-93`
**Issue:** The handler sends `Authorization: Bearer <PAT>` to whatever
`tools_endpoint` resolves to, with no scheme/host check. Today the value is
server-derived from `FRIDAY_BASE_URL`, so there is **no live SSRF/exfil path**.
However, unlike `anthropic_base_url` (which is validated via
`_validate_anthropic_base_url` in `coding.py:60`), the PAT-bearing endpoint has
no equivalent guard. If `FRIDAY_TASK_TOOLS_ENDPOINT` is ever populated from a
less-trusted channel (env override, future feature), the PAT could be sent to
an attacker-controlled host. Mirror the existing anthropic validation for the
secret-bearing endpoint.
**Fix:** Validate scheme ∈ {http, https} + non-empty host, and consider
requiring `https` for the PAT callback (reject `http` except localhost) before
building the MCP server.

### WR-04: `t["name"]` raises `KeyError` on a malformed schema, failing the entire task

**Status:** ✅ Resolved (`6ea77f61`). Both `build_remote_tools_mcp_server` and
`remote_allowed_tools` now use `t.get("name")` and skip entries without a usable
name (logging `remote_tool_missing_name`), consistent with the `.get` used for
`description`/`input_schema`. Tests added
(`test_malformed_schema_without_name_skipped`,
`test_remote_allowed_tools_skips_missing_name`).

**File:** `task/core/remote_tools.py:120, 123, 138`
**Issue:** `build_remote_tools_mcp_server` and `remote_allowed_tools` index
`t["name"]` directly. A schema entry missing `name` raises `KeyError`. This
propagates into `_execute_claude`'s outer `except Exception` (`executor.py:500`)
and fails the whole task with `success=False` rather than skipping the bad tool.
`description`/`input_schema` already use `.get(...)` with defaults — `name` is
the inconsistent one. The payload is server-controlled (`RemoteToolRegistry`),
so likelihood is low, but the asymmetry is a latent crash.
**Fix:** Skip entries without a usable name:
```python
for t in remote_tools:
    name = t.get("name")
    if not name:
        logger.warning("remote_tool_missing_name", schema=t)
        continue
    sdk_tools.append(SdkMcpTool(name=name, ...))
```
and guard `remote_allowed_tools` the same way.

## Info

### IN-01: RemoteTool chain is inert end-to-end until a realtime PAT channel exists

**Status:** ☑️ Acknowledged — no code change this phase. The RemoteTool loop is
currently dormant because `_resolve_user_pat` returns `""`, so no
`FRIDAY_TASK_USER_TOKEN` is injected and `build_remote_tools_mcp_server` always
returns `None`. This is the intended **CONTEXT Open-Q1 Option-C** decision
("mechanism complete, does not violate PAT-02"): automatic PAT resolution via a
realtime contextvar channel is a documented follow-up (`TODO(RTOOL follow-up)`),
tracked separately. Downstream consumers must not assume remote tools are live
until that follow-up lands.

**File:** `server/workflows/nodes/ai/coding.py:812-829`
**Issue:** `_resolve_user_pat` always returns `""`, so
`env_FRIDAY_TASK_USER_TOKEN` is never injected, so `user_token` is empty in the
container, so `build_remote_tools_mcp_server` always returns `None`. The
remote-tool MCP server is therefore **never actually mounted** in any current
dispatch path, even though `remote_tools` and `tools_endpoint` flow correctly.
This is intentional per the CONTEXT Open-Q1 ruling ("mechanism complete, does
not violate PAT-02"), but it means the feature is dormant — downstream consumers
should not assume remote tools are live. The `TODO(RTOOL follow-up)` documents
the missing contextvar channel.
**Fix:** None required for this phase; ensure the follow-up to plumb a realtime
PAT contextvar is tracked so the chain is exercised before it is relied upon.

### IN-02: Ignored `json.Marshal` error in runner env assembly

**Status:** ☑️ Acknowledged — no code change this phase (safe back-compat empty
value on failure; logging the marshal error is a low-priority follow-up).

**File:** `runner/internal/docker/executor.go:91`
**Issue:** `remoteTools, _ := json.Marshal(task.Payload["remote_tools"])` drops
the error. On failure `remoteTools` is `nil` → `string(nil)` == `""`, which is
the safe back-compat value, so behavior is acceptable, but a silent marshal
failure would be invisible.
**Fix:** Log on error: `if err != nil { log.Warn().Err(err).Msg("remote_tools_marshal_failed") }`.

### IN-03: Per-call httpx client + hardcoded 60s timeout

**Status:** ☑️ Acknowledged — no code change this phase (maintainability only,
out of v1 perf scope).

**File:** `task/core/remote_tools.py:46, 54`
**Issue:** A fresh `httpx.AsyncClient()` is created on every tool invocation and
`timeout=60.0` is a magic number. Functionally correct (out-of-v1-scope for
perf); flagged only for maintainability — consider a module constant for the
timeout.
**Fix:** Extract `_TOOL_CALL_TIMEOUT = 60.0`; optionally reuse a shared client.

### IN-04: PAT exposed as a container env var (accepted design, consistent precedent)

**Status:** ☑️ Acknowledged — no code change this phase (accepted design,
consistent with existing env-injection precedent; mounted-secret hardening is a
future option).

**File:** `runner/internal/docker/executor.go:124-133`, `task/core/config.py:86`
**Issue:** When injected, the PAT lands in the container environment
(`FRIDAY_TASK_USER_TOKEN`), visible via `docker inspect` and
`/proc/<pid>/environ`. This matches the existing pattern for
`FRIDAY_TASK_CLAUDE_API_KEY`, `FRIDAY_CALLBACK_TOKEN`, and git tokens, and the
phase brief explicitly accepts "env injection" as a transport. Noted as residual
exposure, not a regression.
**Fix:** None for this phase; a future hardening could prefer a mounted secret
file or a short-lived scoped token over a long-lived PAT in env.

---

_Reviewed: 2026-06-10T02:40:00Z_
_Reviewer: Claude (gsd-code-reviewer)_
_Depth: deep_
