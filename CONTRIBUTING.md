# Contributing
Thanks for helping improve Friday AI.
## Development Setup
1. Install Docker, Docker Compose v2, `uv`, Node.js, pnpm, Go, and Git.
2. Generate local configuration:
 ```bash
 scripts/setup.sh
 ```
3. Install dependencies:
 ```bash
 make install
 ```
4. Start the app with Docker:
 ```bash
 docker compose up -d
 ```
 Or run services locally with `make dev`.
## Checks
Run the focused checks for the area you changed:
```bash
cd server && uv run pytest tests/test_credential_leak_protection.py tests/test_interactions_ledger.py tests/mcp_tools/test_feishu_work_item_context.py tests/test_httpx_removal_guard.py tests/test_conversation_facade_waiting_clarification.py tests/test_intent_router.py tests/test_langchain_runner_core.py tests/test_langchain_runner_no_stategraph.py tests/test_coding_progress.py --cov=. --cov-report=term-missing
cd web && pnpm lint && pnpm type-check && pnpm test:unit:coverage
cd web && pnpm test:e2e -- --project=chromium
cd runner && go test ./...
cd task && uv run ruff check . && uv run pytest
```
Server ruff and mypy are currently advisory in CI while the legacy backend
baseline is being normalized. Running them locally is still useful before
touching broad backend areas.
Before opening a pull request, also validate the deployment surface:
```bash
bash -n scripts/setup.sh
scripts/setup.sh --non-interactive --force --data-dir /tmp/friday-ai-data
docker compose config
```
## Pull Requests
- Keep changes focused and explain the user-facing impact.
- Include tests or a clear reason why tests are not practical.
- Update documentation when behavior, configuration, or public APIs change.
- Do not commit `.env`, database files, logs, generated reports, or private data.
## Commit Messages
Friday AI uses a strict commit subject format:
```text
feat: add hat wobble
^--^  ^------------^
|     |
|     +-> Summary in present tense.
|
+-------> Type: chore, docs, feat, fix, refactor, style, or test.
```
Allowed types:
- `feat`: a new user-facing feature, not build script work.
- `fix`: a user-facing bug fix, not build script work.
- `docs`: documentation-only changes.
- `style`: formatting changes with no production code change.
- `refactor`: production code refactoring, such as renaming a variable.
- `test`: adding or refactoring tests with no production code change.
- `chore`: maintenance work with no production code change.

Do not use scopes, checkpoint numbers, mixed types, or private workflow IDs in
commit subjects. The CI job runs `scripts/check_commit_messages.sh --all` and
rejects subjects outside this format.

## Security
Do not report vulnerabilities in public issues. Follow [SECURITY.md](SECURITY.md).
