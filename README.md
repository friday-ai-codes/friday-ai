<p align="center">
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset="web/public/logo-dark.svg">
    <img src="web/public/logo.svg" alt="Friday AI" width="420">
  </picture>
</p>

**Friday AI** is an open-source development automation platform for teams that
want a repeatable path from approved requirements to auditable code changes. It
connects work items, repositories, workflow orchestration, code intelligence,
and AI coding agents in one self-hosted system.

Friday is built for product and engineering teams that already have a process:
requirements are reviewed, implementation plans need to be visible, code should
land through PRs or MRs, and every automated step should leave a trace.

| Capability | What it does |
| --- | --- |
| Requirement-to-code workflows | Trigger work from Feishu project events or manual runs, generate technical plans, wait for review fields, and dispatch coding tasks. |
| AI planning | Turn a work item into structured implementation context that can be reviewed before code is written. |
| Coding agents | Run isolated coding tasks through registered runners and track the resulting branches, commits, and merge requests. |
| Code intelligence | Index repositories with symbol extraction, graph relationships, vector search, and retrieval pipelines for better coding context. |
| Repository integrations | Connect GitHub or GitLab repositories, credentials, branches, PRs, and MRs through a shared project model. |
| Self-hosted operations | Ship the full stack with Docker Compose, persistent local data, Helm manifests, and Argo CD examples. |

## Quick Start

Prerequisites:

- Docker and Docker Compose v2
- Git

Generate local configuration and data directories:

```bash
scripts/setup.sh
```

Start the full stack:

```bash
docker compose up -d
```

The Compose stack starts Web, Server, Runner, PostgreSQL, Redis, and Qdrant.

| Surface | URL |
| --- | --- |
| Web app | <http://localhost:10240> |
| API docs | <http://localhost:10240/docs> |
| Direct API port | <http://localhost:10241> |

Useful operations:

```bash
docker compose logs -f
docker compose down
docker compose -f docker-compose.yaml -f docker-compose.build.yaml up --build -d
```

## Configuration

`scripts/setup.sh` creates `.env`, generates required secrets, and writes
persistent data under `~/.friday-ai` by default. Run
`scripts/setup.sh --help` for non-interactive setup and custom data directory
options.

Key environment variables:

| Variable | Required | Default | Description |
| --- | --- | --- | --- |
| `SECRET_KEY` | yes | generated | Django signing secret. |
| `FRIDAY_ENCRYPTION_KEY` | yes | generated | Encryption key for stored credentials. |
| `RUNNER_REGISTRATION_TOKEN` | yes | generated | Shared registration token for server and runners. |
| `DATABASE_URL` | no | `postgres://friday:${POSTGRES_PASSWORD:-friday}@postgres:5432/friday` | Database URL used by the Compose stack. |
| `FRIDAY_DATA_DIR` | no | `~/.friday-ai` | Host directory for PostgreSQL, Redis, Qdrant, server, and runner data. |
| `FRIDAY_WEB_PORT` | no | `10240` | Web entrypoint and proxied API docs. |
| `FRIDAY_PORT` | no | `10241` | Direct backend API port. |
| `FRIDAY_IMAGE_PREFIX` | no | `ghcr.io/friday-ai-codes/friday-ai` | Container image namespace. |
| `FRIDAY_IMAGE_TAG` | no | `latest` | Container image tag. |

Never commit `.env`, databases, logs, service tokens, or exported customer data.

## Development

Install dependencies:

```bash
make install
```

Run the full local dev loop:

```bash
make dev
```

Or run services separately:

```bash
make dev-server
make dev-web
```

Focused checks:

```bash
cd server && uv run pytest
cd web && pnpm lint && pnpm type-check && pnpm test:unit:coverage
cd web && pnpm test:e2e -- --project=chromium
cd runner && go test ./...
cd task && uv run ruff check . && uv run pytest
```

Before changing deployment behavior, also validate the public setup path:

```bash
bash -n scripts/setup.sh
scripts/setup.sh --non-interactive --force --data-dir /tmp/friday-ai-data
docker compose config
```

## Repository Layout

| Path | Purpose |
| --- | --- |
| `server/` | Django API, orchestration services, repository indexing, integrations, and backend tests. |
| `web/` | Vue 3 frontend, shared UI, Vitest unit tests, and Playwright e2e tests. |
| `runner/` | Go runner service that connects to the server and executes tasks. |
| `task/` | Isolated task execution container and task-side integration tests. |
| `deploy/` | Docker, Helm, and Argo CD deployment assets. |
| `docs/` | VitePress documentation and generated API reference. |
| `scripts/` | Setup, verification, and release helper scripts. |

## Deployment

The default Compose deployment uses prebuilt images from:

```text
ghcr.io/friday-ai-codes/friday-ai
```

Set `FRIDAY_IMAGE_TAG` to pin a release or use
`docker-compose.build.yaml` to build images from the current checkout. Helm and
Argo CD examples live under `deploy/`.

## Documentation

Start with these docs:

| Document | Covers |
| --- | --- |
| [Quick Start](docs/guide/quick-start.md) | Local deployment, first project setup, and workflow testing. |
| [Workflow Guide](docs/guide/workflows.md) | Workflow nodes, triggers, execution records, and debugging. |
| [Admin Guide](docs/guide/admin.md) | Users, permissions, OIDC, runners, and operations. |
| [Friday Codebase Agent](docs/guide/friday-codebase-agent.md) | Codebase-agent behavior and repository context. |
| [API Reference](docs/api/index.md) | REST API documentation. |
| [Chinese README](README.zh-CN.md) | The Chinese version of this README. |

## Status

Friday AI is in its early public release line. APIs, deployment defaults, and
extension points may change between minor versions while the open-source surface
settles.

## Contributing

Read [CONTRIBUTING.md](CONTRIBUTING.md) before opening pull requests. Security
reports should follow [SECURITY.md](SECURITY.md).

## License

Friday AI is released under the [MIT License](LICENSE).
