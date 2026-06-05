# Friday AI

Friday AI is an open-source development automation platform. It connects project
requirements, repositories, workflow orchestration, and AI coding agents so teams
can move from an approved requirement to an auditable code change.
## Status
Friday AI is starting its public release line at `0.0.1`. The repository history
has been rewritten and scanned for public release readiness. Treat the project as
early-stage open source: APIs, deployment defaults, and extension points may still
change between minor versions.
## Quick Start
Prerequisites:
- Docker and Docker Compose v2
- Git
Generate a local `.env` file and persistent data directories:
```bash
scripts/setup.sh
```
Start the full stack:
```bash
docker compose up -d
```
Friday starts Web, Server, Runner, PostgreSQL, Redis, and Qdrant.
- Web app: <http://localhost:10240>
- API docs: <http://localhost:10240/docs>
- Direct API port: <http://localhost:10241>
Useful commands:
```bash
docker compose logs -f
docker compose down
docker compose -f docker-compose.yaml -f docker-compose.build.yaml up --build -d
```
## Configuration
`scripts/setup.sh` creates `.env`, generates required secrets, and writes data
under `~/.friday-ai` by default. Run `scripts/setup.sh --help` for non-interactive
and custom data directory options.
Key environment variables:
| Variable | Required | Default | Description |
| --- | --- | --- | --- |
| `SECRET_KEY` | yes | generated | Django signing secret |
| `FRIDAY_ENCRYPTION_KEY` | yes | generated | Encryption key for stored credentials |
| `RUNNER_REGISTRATION_TOKEN` | yes | generated | Shared registration token for runners |
| `DATABASE_URL` | no | `postgres://friday:${POSTGRES_PASSWORD:-friday}@postgres:5432/friday` | Database URL used by the Compose stack |
| `FRIDAY_DATA_DIR` | no | `~/.friday-ai` | Host directory for persistent data |
| `FRIDAY_WEB_PORT` | no | `10240` | Web entrypoint |
| `FRIDAY_PORT` | no | `10241` | Direct backend API port |
| `FRIDAY_IMAGE_PREFIX` | no | `ghcr.io/friday-ai-codes/friday-ai` | Container image namespace |
| `FRIDAY_IMAGE_TAG` | no | `latest` | Container image tag |
Never commit `.env`, databases, logs, or exported customer data.
## Development
Install dependencies:
```bash
make install
```
Run the backend:
```bash
cd server
uv run uvicorn friday.asgi:application --reload --host 0.0.0.0 --port 10241
```
Run the frontend:
```bash
cd web
pnpm dev
```
Run focused checks:
```bash
cd server && uv run pytest tests/test_credential_leak_protection.py tests/test_interactions_ledger.py tests/mcp_tools/test_feishu_work_item_context.py tests/test_httpx_removal_guard.py tests/test_conversation_facade_waiting_clarification.py tests/test_intent_router.py tests/test_langchain_runner_core.py tests/test_langchain_runner_no_stategraph.py tests/test_coding_progress.py --cov=. --cov-report=term-missing
cd web && pnpm test:unit:coverage
cd web && pnpm test:e2e -- --project=chromium
cd runner && go test ./...
```
## Repository Layout
| Path | Purpose |
| --- | --- |
| `server/` | Django API, orchestration, integrations, and backend tests |
| `web/` | Vue 3 frontend, Vitest unit tests, Playwright e2e tests |
| `runner/` | Go runner service |
| `task/` | Isolated task execution container |
| `deploy/` | Docker, Helm, and Argo CD deployment assets |
| `docs/` | User and developer documentation |
| `scripts/` | Setup and verification scripts |
## CI/CD
The GitHub Actions CI workflow runs blocking web/task/runner checks, server
smoke tests with coverage, Playwright smoke e2e, Docker Compose config
validation, and secret scanning. Server ruff and mypy currently run as advisory
checks while the legacy backend static-analysis baseline is being normalized.
The release workflow builds multi-architecture container images and creates
GitHub releases from version tags.
## Contributing
Please read [CONTRIBUTING.md](CONTRIBUTING.md) before opening pull requests.
Security reports should follow [SECURITY.md](SECURITY.md).
## License
Friday AI is released under the [MIT License](LICENSE).
