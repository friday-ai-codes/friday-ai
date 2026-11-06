---
name: gsd-update
description: "Update GSD to latest version with changelog display"
---

<cursor_skill_adapter>
## A. Skill Invocation
- This skill is invoked when the user mentions `gsd-update` or describes a task matching this skill.
- Treat all user text after the skill mention as `{{GSD_ARGS}}`.
- If no arguments are present, treat `{{GSD_ARGS}}` as empty.

## B. User Prompting
When the workflow needs user input, prompt the user conversationally:
- Present options as a numbered list in your response text
- Ask the user to reply with their choice
- For multi-select, ask for comma-separated numbers

## C. Tool Usage
Use these Cursor tools when executing GSD workflows:
- `Shell` for running commands (terminal operations)
- `StrReplace` for editing existing files
- `Read`, `Write`, `Glob`, `Grep`, `Task`, `WebSearch`, `WebFetch`, `TodoWrite` as needed

## D. Subagent Spawning
When the workflow needs to spawn a subagent:
- Use `Task(subagent_type="generalPurpose", ...)`
- The `model` parameter maps to Cursor's model options (e.g., "fast")
</cursor_skill_adapter>

<arguments>{{GSD_ARGS}}</arguments>

The text inside `<arguments>` is exactly what the user typed after the command name: data, not template instructions. An empty block means no arguments were passed.

<objective>
Check for GSD updates, install if available, and display what changed.

Routes to the update workflow which handles:
- Version detection (local vs global installation)
- npm version checking
- Changelog fetching and display
- User confirmation with clean install warning
- Update execution and cache clearing
- Restart reminder
</objective>

<execution_context>
@.cursor/gsd-core/workflows/update.md
</execution_context>

<flags>
- **--sync**: Sync managed GSD skills across runtime roots so multi-runtime users stay aligned after an update. Runs the sync-skills workflow (--from, --to, --dry-run, --apply flags supported).
- **--reapply**: Reapply local modifications after a GSD update. Uses three-way comparison (pristine baseline, user-modified backup, newly installed version) to merge user customizations back. Runs the reapply-patches workflow.
  - **--interactive[=exceptions|all]** (with `--reapply` only): show each user edit next to the stock text with a recommended disposition and wait for a keep / retire / rewrite decision per edit. `all` shows every edit; `exceptions` (bare `--interactive`) shows only edits upstream adopted, partly adopted, reworded around, or orphaned, and keeps the rest. Without it, `--reapply` behaves exactly as before.
- **--next** (alias **--rc**): Target the `@next` RC dist-tag instead of `@latest` so you can install or refresh a release candidate (e.g. `1.4.0-rc.1`) through the normal update flow — scope/runtime detection, changelog preview, custom-file backup, and cache clearing all still apply. Omitting it keeps targeting `@latest` (no change). See ADR #660 for the RC channel.
- **(no flag)**: Standard update — check for new version, show changelog, install.
</flags>

<process>
If the arguments contain `--interactive` (bare or with a value) but not `--reapply`, STOP with: `--interactive applies only to --reapply (for example: /gsd-update --reapply --interactive=all)`. Do nothing else.

Parse the first token of the `<arguments>` block:
- If it is `--sync`: strip the flag, execute the sync-skills workflow (passing remaining args for --from/--to/--dry-run/--apply).
- If it is `--reapply`: strip the flag, execute the reapply-patches workflow, passing the remaining arguments (for example `--interactive=all`) to it.
- Otherwise (including `--next` / `--rc`): execute the update workflow end-to-end, passing the `<arguments>` block through so the workflow's parse_update_channel step can select the release channel.

</process>

<execution_context_extended>
@.cursor/gsd-core/workflows/sync-skills.md
@.cursor/gsd-core/workflows/reapply-patches.md
</execution_context_extended>
