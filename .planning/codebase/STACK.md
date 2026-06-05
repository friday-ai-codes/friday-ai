# Technology Stack

**Analysis Date:** 2026-06-05

Friday AI is a **multi-language monorepo** for an AI-powered development automation system. It has four primary components, each with its own toolchain:

| Component | Path | Language | Role |
|-----------|------|----------|------|
| Backend / API | `server/` | Python 3.14 (Django) | REST + WebSocket API, workflow engine, code intelligence (codegraph/RAG) |
| Frontend | `web/` | TypeScript (Vue 3) | SPA dashboard, flow editor, chat UI |
| Task executor | `task/` | Python 3.14 | Containerized AI coding agent run inside Docker by the runner |
| Runner | `runner/` | Go 1.25 | Host agent that schedules and runs task containers (Docker / k8s) |
| Docs | `docs/` (root `package.json`) | VitePress / Vue | Documentation site |

## Languages

**Primary:**
- Python 3.14 (`>=3.14`) — backend (`server/`) and task executor (`task/`); pinned via `server/.python-version`
- TypeScript ~5.9.3 — frontend (`web/`), Vue 3 SFCs
- Go 1.25.0 — runner (`runner/go.mod`)

**Secondary:**
- Vue 3 templates (`web/src/**/*.vue`)
- Shell scripts (`scripts/`, `runner/entrypoint.sh`)
- SQL via Django ORM migrations

## Runtime

**Backend (`server/`):**
- Python `>=3.14`
- ASGI server: `uvicorn[standard]>=0.30` (dev, see `Makefile`), `daphne>=4.2.1` + `gunicorn>=23.0.0` (prod)
- ASGI app: `friday.asgi:application`; WSGI app: `friday.wsgi:application`

**Frontend (`web/`):**
- Node (version pinned in `web/.nvmrc`)
- Dev/build tool: Vite — note it is aliased to `rolldown-vite` via pnpm overrides in `web/pnpm-workspace.yaml`

**Runner (`runner/`):**
- Go 1.25.0 compiled binary (`runner/cmd/friday-runner/main.go` → `friday-runner`)

**Package Managers:**
- Python: `uv` (lockfiles `server/uv.lock`, `task/uv.lock`); build backend `hatchling`
- JS: `pnpm@10.28.0` (frontend, `web/pnpm-lock.yaml`); root docs use `pnpm@10.30.3`
- Go: Go modules (`runner/go.mod`)
- Lockfiles: present for all three ecosystems

## Frameworks

**Backend Core:**
- `django>=5.1` — web framework
- `djangorestframework>=3.15` — REST API
- `adrf>=0.1.12` — async DRF views
- `djangorestframework-simplejwt>=5.3` — JWT auth (with token blacklist)
- `drf-spectacular>=0.27` — OpenAPI/Swagger schema
- `channels[daphne]>=4.3.2` + `daphne>=4.2.1` — WebSocket / ASGI
- `django-apscheduler>=0.7.0` — scheduled jobs (repo sync polling)
- `django-environ>=0.11` — env-based settings

**AI / LLM frameworks (backend):**
- `claude-agent-sdk>=0.1.58,<0.2` — Anthropic Claude agent SDK
- `anthropic>=0.40.0`, `openai>=2.16.0`, `google-genai>=1.0.0` — provider SDKs
- `langgraph>=1.1.6` + `langgraph-checkpoint-sqlite>=3.0.3` — agent orchestration graph
- `langchain>=1.2.15` with `langchain-anthropic`, `langchain-openai`, `langchain-google-genai`, `langchain-ollama`
- `llama-index>=0.10.0` + `llama-index-vector-stores-qdrant>=0.2.0` — RAG indexing
- `fastembed>=0.4.0` — local embeddings
- `qdrant-client>=1.9.0` — vector DB client

**Code intelligence (backend):**
- `tree-sitter>=0.21.0` + grammars: go, javascript, typescript, python, css, html, json
- `pygls>=2.0` — Language Server Protocol client; integrates external `vue-language-server` (volar) and `gopls` (configured in `server/friday/settings.py` `LSP_SERVERS` / `EXTRACTOR_BACKENDS`)

**Frontend Core:**
- `vue@^3.5.26` — UI framework (Composition API, `<script setup>`)
- `vue-router` (file-based via `unplugin-vue-router`), `pinia` — state
- `@tanstack/vue-query` — server state; `@tanstack/vue-table` — tables
- `@vue-flow/*` — node/flow editor; `3d-force-graph` + `three` — graph viz
- `@tiptap/*` — rich text editor; `codemirror` / `@codemirror/*` — code editor
- `tailwindcss@^4.1.18` + `reka-ui` + `class-variance-authority` — styling/components
- `vee-validate` + `zod` — form validation; `vue-i18n` — i18n; `echarts`/`vue-echarts` — charts

**Runner (Go):**
- `spf13/cobra` + `spf13/viper` — CLI & config
- `docker/docker` (v28) + `docker/go-connections` — Docker SDK
- `coder/websocket` — WebSocket client to server
- `charmbracelet/huh` + `lipgloss` + `bubbletea` — interactive TUI
- `hashicorp/go-retryablehttp` — resilient HTTP; `rs/zerolog` — logging
- `shirou/gopsutil/v4` — system metrics

**Task executor (Python):**
- `claude-agent-sdk==0.1.58` (pinned) — runs the coding agent
- `pydantic>=2.6` + `pydantic-settings>=2.2` — config/models
- `click>=8.0` — CLI (`friday-task = "cli:main"`)
- `gitpython`, `httpx`, `structlog`, `tenacity`, `jinja2`

**Testing:**
- Backend: `pytest>=9.0.2`, `pytest-asyncio`, `pytest-django>=4.8`, `pytest-cov`, `factory-boy`, `respx` (httpx mocking), `pytest-socket` (network isolation)
- Frontend: `vitest@^4`, `@vue/test-utils`, `happy-dom`, `@vitest/coverage-v8`, `@playwright/test` (E2E)
- Go: standard `testing` + `gotest.tools/v3`

**Build/Dev:**
- Backend: `uv`, `hatchling`, `mypy>=1.14` (+ django/drf stubs), `ruff>=0.14`
- Frontend: `vite` (rolldown), `vue-tsc`, `eslint` (`@antfu/eslint-config`), `tsx`, unplugin auto-import/components/i18n/router, `vue-macros`
- Go: `runner/Makefile`

## Key Dependencies

**Critical:**
- `claude-agent-sdk` — core of the AI coding agent (both `server/` and `task/`)
- `langgraph` / `langchain` — LLM orchestration in workflow nodes
- `qdrant-client` + `fastembed` + `llama-index` — RAG / semantic code search
- `tree-sitter` + `pygls` — AST extraction and LSP-backed code intelligence
- `channels` / `daphne` — real-time WebSocket updates (workflow status, chat streaming)

**Infrastructure:**
- `psycopg[binary]>=3.3` (PostgreSQL), `mysqlclient>=2.2` (MySQL/MariaDB) — DB drivers
- `docker>=7.1.0` (Python SDK, server side) — container orchestration
- `gitpython` + `python-gitlab>=4.0` + `PyGithub>=2.0` — Git platform integration
- `cryptography>=42.0` + `passlib[argon2]` — encryption & password hashing
- `whitenoise>=6.7` — static file serving
- `pywebpush>=2.3.0` — browser push notifications
- `lark-oapi>=1.5.2` — Feishu (Lark) integration
- `paramiko>=4.0.0` — SSH

## Configuration

**Environment:**
- Backend settings: `server/friday/settings.py`, loaded via `django-environ`
- `.env` resolution order: `server/.env` first, then project root `.env` (`env.read_env(...)`)
- Template: `.env.example` at repo root (documents all vars)
- `FRIDAY_ENV` / `FRIDAY_PRODUCTION` toggle production hardening (forces `DEBUG=False`, non-default `SECRET_KEY`, explicit `ALLOWED_HOSTS`)
- Frontend config via Vite env: `VITE_API_URL`, `VITE_USE_POLLING` (see `Makefile`, `API_DETECTOR_CONFIG` in settings)
- Runner config: TOML file (`config.toml` under config dir) + `FRIDAY_RUNNER_*` env vars bound by viper (`runner/internal/config/config.go`)

**Build:**
- `server/pyproject.toml` — backend deps, pytest/mypy/ruff/coverage config
- `task/pyproject.toml` — task executor deps & CLI entrypoint
- `web/package.json` + `web/pnpm-workspace.yaml` (pnpm catalog pins all versions) + `web/vite.config.ts` + `web/tsconfig.json`
- `runner/go.mod` + `runner/Makefile`
- Per-component `Dockerfile` (`server/`, `web/`, `task/`, `runner/`)
- `docker-compose.yaml` (prebuilt images) + `docker-compose.build.yaml` (source build)
- Root `Makefile` — `make dev` (tmux split server+web), `make install`, `make build-runner`, `make build-task`

## Platform Requirements

**Development:**
- Python 3.14 + `uv`; Node + `pnpm`; Go 1.25
- Docker daemon (runner spawns task containers via `/var/run/docker.sock`)
- Optional: PostgreSQL, Redis, Qdrant (or use SQLite + in-memory channel layer for local dev)

**Production:**
- Docker Compose stack: `server`, `web` (Nginx proxy), `runner`, `postgres:17-alpine`, `redis:7-alpine`, `qdrant/qdrant`
- Default ports: web `10240`, API `10241`, Qdrant `6333/6334`, Redis `6379`
- Prebuilt images: `ghcr.io/friday-ai-codes/friday-ai/{server,web,runner}`
- CI/CD: GitHub Actions (`.github/workflows/ci.yaml`, `.github/workflows/release.yaml`)

---

*Stack analysis: 2026-06-05*
