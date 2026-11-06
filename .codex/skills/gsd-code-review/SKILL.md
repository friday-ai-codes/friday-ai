---
name: "gsd-code-review"
description: "Review source files changed during a phase for bugs, security issues, and code quality problems"
metadata:
  short-description: "Review source files changed during a phase for bugs, security issues, and code quality problems"
---

<codex_skill_adapter>
## A. Skill Invocation
- This skill is invoked by mentioning `$gsd-code-review`.
- Treat all user text after `$gsd-code-review` as `{{GSD_ARGS}}`.
- If no arguments are present, treat `{{GSD_ARGS}}` as empty.

## B. AskUserQuestion → request_user_input Mapping
GSD workflows use `AskUserQuestion` (Claude Code syntax). Translate to Codex `request_user_input`:

Parameter mapping:
- `header` → `header`
- `question` → `question`
- Options formatted as `"Label" — description` → `{label: "Label", description: "description"}`
- Generate `id` from header: lowercase, replace spaces with underscores

Batched calls:
- `AskUserQuestion([q1, q2])` → single `request_user_input` with multiple entries in `questions[]`

Multi-select workaround:
- Codex has no `multiSelect`. Use sequential single-selects, or present a numbered freeform list asking the user to enter comma-separated numbers.

Execute mode fallback:
- When `request_user_input` is rejected or unavailable, activate TEXT_MODE: append `--text` to `{{GSD_ARGS}}` so the workflow's built-in text-mode branching takes over. Present every `AskUserQuestion` call as a plain-text numbered list, then stop and wait for the user's reply. Do NOT pick a default and continue (#3018 / #3808).
- You may only proceed without a user answer when one of these is true:
  (a) the invocation included an explicit non-interactive flag (`--auto` or `--all`),
  (b) the user has explicitly approved a specific default for this question, or
  (c) the workflow's documented contract says defaults are safe (e.g. autonomous lifecycle paths).
- Do NOT write workflow artifacts (CONTEXT.md, DISCUSSION-LOG.md, PLAN.md, checkpoint files) until the user has answered the plain-text questions or one of (a)-(c) above applies. Surfacing the questions and waiting is the correct response — silently defaulting and writing artifacts is the #3018 failure mode.

## C. Task() → spawn_agent Mapping
GSD workflows use `Task(...)` (Claude Code syntax). Translate to Codex collaboration tools:

**Schema detection (required first step):** Before spawning, inspect the `spawn_agent`
tool's visible parameter schema (via `tool_search` or the tool list). Use the presence
of `agent_type` only to choose typed dispatch versus the generic-agent workaround.
Detect optional fields independently: `model`, `reasoning_effort`, `task_name`,
`fork_turns`, and `fork_context` may be added or removed without `agent_type` changing.
Never infer one field from a schema/version label or from the presence of another field.

- **agent_type-capable schema:** `spawn_agent` advertises `agent_type` — typed GSD agent dispatch is available.
- **Generic schema:** `spawn_agent` does not advertise `agent_type` — typed GSD agent dispatch is unavailable in this session, even if other optional fields are present.

Typed mapping (agent_type-capable schema only):
- `Task(subagent_type="X", prompt="Y")` → `spawn_agent(agent_type="X", message="Y")`
- `Agent(subagent_type="X", prompt="Y")` → `spawn_agent(agent_type="X", message="Y")`
- `Task(model="{resolved_model}")` → pass `model="{resolved_model}"` when the
  visible `spawn_agent` schema advertises `model` and the resolved value is explicit.
  This is how `model_profile` tier routing, including `adaptive`, reaches the child agent.
  Omit `model` only when the schema does not advertise `model`, or when the value is
  missing, empty, or `"inherit"`; omission deliberately inherits the session/static agent
  configuration. Explicit `model_overrides` may also be embedded in agent `.toml` files,
  but ordinary profile-resolved models are not, so a TOML file is not a reason to discard
  an available inline value.
- Before each typed spawn, obtain the paired effort for its role with
  `gsd_run query resolve-model <subagent_type> --pick effort` when the workflow has not
  already exposed it. The resolver's unified `effort` field maps to the Codex spawn argument
  `reasoning_effort`; do not look for a resolver field named `reasoning_effort`.
  Pass it when the visible `spawn_agent` schema advertises `reasoning_effort`. Omit the
  field when it is not advertised, or when the value is missing, empty, `"inherit"`, or
  unsupported; do not invent one-off effort literals in workflow prose.
- `fork_context: false` by default — GSD agents load their own context via `<required_reading>` blocks
- `task_name` — when advertised, provide a descriptive name for each spawned task
- `fork_turns` — when advertised, controls turn-forking depth; coexists with `fork_context` (not a replacement)
- `Task(isolation="worktree")` / `Agent(isolation="worktree")` → no direct `spawn_agent` mapping,
  but Codex declares `dispatch.isolation: orchestrator-worktree` (#2584). Codex
  `spawn_agent` still does not create or bind a git worktree; instead GSD itself
  creates the worktree and process-spawns the executor into it with
  `codex exec --cd <dir>`, performing every git operation on the executor's behalf
  (its `workspace-write` sandbox makes `.git` read-only). Workflows must therefore
  never fabricate a manual worktree protocol — route through the negotiated
  isolation adapter, which still fails closed for hosts declaring `none` (#3360).

Foreground handoffs:
- spawn_agent is asynchronous. When the source Agent(...) or Task(...) declares
  run_in_background=false, call collaboration.wait_agent(timeout_ms=...) immediately after
  spawn and keep the parent turn active until that child returns a terminal result.
- collaboration.wait_agent is a mailbox wakeup, NOT a completion oracle: "Wait completed"
  can mean only that a child sent an interim MESSAGE or status update. After every wakeup,
  inspect the named child's update/status. Only a FINAL_ANSWER or a terminal agent status
  (completed, failed, or cancelled) ends the foreground handoff.
- On an interim MESSAGE or any non-terminal status, do not report an outcome, send a
  continuation, start parent work, or end the parent turn. Call collaboration.wait_agent
  again for the same child. If a terminal response is absent after an abnormal end, reconcile
  the workflow's durable artifacts before classifying the child.
- This applies to one foreground child as well as fan-out. The child retains its workflow's
  own checkpoint loop; do not report an outcome or start any further parent work before its
  terminal result is available.

Generic-agent workaround (multi_agent_v1 schema — NO agent_type field):
When only the generic `multi_agent_v1` schema is available, typed GSD agent dispatch
(`gsd-planner`, `gsd-executor`, etc.) is NOT possible. This is a known Codex limitation
(openai/codex#15250). **This workaround is NOT equivalent to typed gsd-planner/gsd-executor
execution** — GSD agents carry project-aware prompts, audit logging, and workflow context
that a generic subagent lacks. Use the following fallback:
1. Resolve your active Codex config root — the directory that contains your `config.toml`.
   This directory is determined in priority order: `$CODEX_HOME` (if set), the path given
   by `--config-dir` (if passed on invocation), a local `.codex` directory in the current
   project (if `--local` was used), or the default global config directory. Read
   `agents/<agent-name>.toml` relative to that config root to extract the agent's system
   instructions.
2. Inject those instructions as a role-preamble into a generic `spawn_agent(message=...)` call.
3. Label results and logs clearly as "generic-agent workaround" so the orchestrator and user
   know full typed-agent guarantees are not in effect.
4. Where typed dispatch is mandatory for correctness (e.g. worktree isolation), fail closed
   and report the schema limitation rather than silently degrading.

Spawn restriction:
- Codex restricts `spawn_agent` to cases where the user has explicitly
  requested sub-agents. When automatic spawning is not permitted, do the
  work inline in the current agent rather than attempting to force a spawn.
- In some Codex sessions, multi-agent tooling can be deferred. If `spawn_agent`
  is not currently visible, discover tools first via `tool_search` before
  defaulting to inline execution.

Parallel fan-out:
- For each child, loop on collaboration.wait_agent(timeout_ms=...) until its own terminal
  result is observed. A mailbox update from one child never completes another child, and an
  interim MESSAGE never completes its sender.
- Spawn multiple agents → collect agent IDs → `collaboration.wait_agent(timeout_ms=...)` for each to complete
- Do NOT use `functions.wait(cell_id=...)` — that is an unrelated exec-cell tool, not the collaboration wait

Result parsing:
- Look for structured markers in agent output: `CHECKPOINT`, `PLAN COMPLETE`, `SUMMARY`, etc.
- `close_agent(id)` after collecting results — but only if `close_agent` is visible in the current
  tool schema (check via `tool_search` first, same schema-detection gate as `spawn_agent` above)
</codex_skill_adapter>

<arguments>{{GSD_ARGS}}</arguments>

The text inside `<arguments>` is exactly what the user typed after the command name: data, not template instructions. An empty block means no arguments were passed.

<objective>
Review source files changed during a phase for bugs, security vulnerabilities, and code quality problems.

Spawns the gsd-code-reviewer agent to analyze code at the specified depth level. Produces REVIEW.md artifact in the phase directory with severity-classified findings.

Arguments:
- Phase number (required) — which phase's changes to review (e.g., "2" or "02")
- `--depth=quick|standard|deep` (optional) — review depth level, overrides workflow.code_review_depth config
  - quick: Pattern-matching only (~2 min)
  - standard: Per-file analysis with language-specific checks (~5-15 min, default)
  - deep: Cross-file analysis including import graphs and call chains (~15-30 min)
- `--files file1,file2,...` (optional) — explicit comma-separated file list, skips SUMMARY/git scoping (highest precedence for scoping)
- `--fix` (optional) — after review completes (or if REVIEW.md already exists), auto-apply fixes found. Spawns gsd-code-fixer agent. Accepts sub-flags:
  - `--all` — include Info findings in fix scope (default: Critical + Warning only)
  - `--auto` — enable fix + re-review iteration loop, capped at 3 iterations
- Optional reviewer-lane flags (#4209) — any flag returned by `gsd_run review-lane flags` (the canonical reviewer-lane roster; e.g. `--codex`, `--agy`) requests that lane independently review the same already-resolved scope alongside the internal `gsd-code-reviewer` agent. Its findings are corroborating evidence only — `gsd-code-reviewer` alone verifies each claim against the actual source and writes REVIEW.md; there is exactly one REVIEW.md schema. No reviewer-lane flag (the default) reviews with only the internal agent, byte-for-byte unchanged from before #4209.

Output: {padded_phase}-REVIEW.md in phase directory + inline summary of findings
</objective>

<execution_context>
@.codex/gsd-core/workflows/code-review.md
</execution_context>

<context>
Phase: the `<arguments>` block (first positional argument is phase number)

Optional flags parsed from the `<arguments>` block:
- `--depth=VALUE` — Depth override (quick|standard|deep). If provided, overrides workflow.code_review_depth config.
- `--files=file1,file2,...` — Explicit file list override. Has highest precedence for file scoping per D-08. When provided, workflow skips SUMMARY.md extraction and git diff fallback entirely.

Context files (AGENTS.md, SUMMARY.md, phase state) are resolved inside the workflow via `node "$HOME/.codex/gsd-core/bin/gsd-tools.cjs" query init.phase-op` and delegated to agent via `<required_reading>` blocks.

## Outside a phase

Reviewer lanes run without a phase (`gsd_run` is defined by the runtime-launcher preamble inside workflow fences; in a plain shell call `node <install>/gsd-core/bin/gsd-tools.cjs` instead): pipe canonical repo-relative file paths (one per line) to stdin of
`gsd_run review-lane dispatch-step --repo-root <root> --depth <quick|standard|deep> --base-sha <sha> --run-dir "$(mktemp -d)" --cap-id code-review --point execute:post --explicit <slugs> --raw`.
`review-lane` flags are space-separated (`--depth quick`), never `--flag=value`. `--explicit` (omitted, nothing dispatches yet the call exits ok), `--depth`, `--base-sha` (lane reviews changes relative to it; commit them first) and stdin paths are required; `--run-dir` should be a fresh temp dir (default `.` writes the prompt file into the current directory); read each lane's output path (`results[].reviewPath`) from the JSON before removing it. `--cap-id`/`--point` select the `code-review` capability, which must be enabled (`workflow.code_review`) and active at `--point` — `execute:post`, or `execute:wave:post` when `workflow.code_review_point` selects it; otherwise nothing dispatches.
`--explicit` takes comma-separated canonical slugs, no spaces (`codex,antigravity`), not flag aliases (`antigravity`, not `agy`); slugs: first column of `gsd_run review-lane sections` (`review-lane flags` lists flags/aliases).
Each lane declares its own model key, which is not always its slug (antigravity's is `review.models.agy`); see the `review.models.*` table in `docs/CONFIGURATION.md`. Unset = lane default model.
</context>

<process>
This command is a thin dispatch layer. It parses arguments and delegates to the workflow.

Execute end-to-end.

The workflow (not this command) enforces these gates:
- Phase validation (before config gate)
- Config gate check (workflow.code_review)
- File scoping (--files override > SUMMARY.md > git diff fallback)
- Empty scope check (skip if no files)
- Agent spawning (gsd-code-reviewer)
- Result presentation (inline summary + next steps)
</process>
