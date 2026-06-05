# Codebase Structure

**Analysis Date:** 2026-06-05

Friday AI is a multi-language monorepo. Four deployable components live at the root: `server/` (Django), `web/` (Vue SPA), `runner/` (Go), `task/` (containerized Python agent), plus `docs/` and `deploy/`.

## Directory Layout

```
friday-ai/
├── server/             # Django backend (REST + WS + workflow engine)
│   ├── friday/         # Project config: settings, urls, asgi, wsgi, middleware
│   ├── workflows/      # Workflow engine, nodes, execution models, consumers
│   ├── agents/         # Agent framework: core, sdk, tools, api
│   ├── services/       # Domain logic: RAG, git platform, providers, indexing
│   ├── chat/ codegraph/ repositories/ projects/ ...  # Django apps (bounded contexts)
│   ├── compat/         # OpenAI-compatible API layer (/v1)
│   ├── common/ core/ utils/  # Shared auth, middleware, patches, helpers
│   ├── tests/          # Pytest suite (mirrors app structure)
│   └── pyproject.toml  # Deps, ruff/mypy/pytest/coverage config
├── web/                # Vue 3 SPA (Vite/rolldown, pnpm)
│   └── src/
│       ├── pages/      # File-based routes (unplugin-vue-router)
│       ├── components/ # Reusable UI components
│       ├── stores/     # Pinia stores
│       ├── api/        # Typed REST client modules
│       ├── composables/# Reusable composition functions (incl. WS)
│       ├── layouts/ lib/ utils/ types/ locales/ styles/
│       └── main.ts     # App bootstrap + router guards
├── runner/             # Go host agent (cobra CLI)
│   ├── cmd/friday-runner/main.go   # Binary entrypoint
│   └── internal/       # ws, docker, k8s, scheduler, service, config, crypto, ...
├── task/               # Containerized AI coding agent (Python)
│   ├── friday_task/ core/ cli/ git_ops/ integrations/
│   └── pyproject.toml  # friday-task CLI
├── docs/               # VitePress documentation site
├── deploy/             # Deployment assets (nginx proxy, compose helpers)
├── scripts/            # Repo-level scripts
├── packages/           # Shared workspace packages
├── docker-compose.yaml / docker-compose.build.yaml
├── Makefile            # make dev / install / build-runner / build-task
└── .env.example        # Env var template (infra only)
```

## Directory Purposes

**`server/friday/`:**
- Purpose: Django project configuration
- Contains: `settings.py`, `urls.py`, `asgi.py`, `wsgi.py`, `middleware.py`
- Key files: `server/friday/settings.py`, `server/friday/urls.py`, `server/friday/asgi.py`

**`server/<app>/` (Django apps):**
- Purpose: Bounded contexts (e.g. `workflows`, `chat`, `codegraph`, `repositories`, `projects`, `accounts`, `feishu`, `compat`, `subagent`, `runners`)
- Contains: `models/`, `api/` (views/serializers), `urls.py`, `apps.py`, `migrations/`
- Key files: `server/workflows/api/views.py`, `server/workflows/models/execution.py`

**`server/workflows/`:**
- Purpose: The core differentiator — DAG workflow engine
- Contains: `engine/` (dag, scheduler), `nodes/` (by category), `hooks/`, `conditions/`, `consumers.py`
- Key files: `server/workflows/engine/scheduler.py`, `server/workflows/nodes/registry.py`, `server/workflows/nodes/base.py`

**`server/services/`:**
- Purpose: Reusable, app-agnostic domain logic
- Contains: RAG (`retrieval/`, `qdrant_service.py`), git (`git_platform/`), provider config, indexing, code intel
- Key files: `server/services/provider_config.py`, `server/services/graph_builder.py`

**`web/src/pages/`:**
- Purpose: File-based routes; folder/file path maps to URL
- Contains: `.vue` pages, co-located `__tests__/`, `components/`, `composables/`
- Key files: `web/src/pages/chat.vue`, `web/src/pages/executions/[id].vue`

**`runner/internal/`:**
- Purpose: Runner implementation (not importable outside module)
- Contains: `ws/` (server connection), `docker/` + `k8s/` (executors), `scheduler/`, `service/` (OS service install), `config/`, `crypto/`, `callback/`
- Key files: `runner/internal/scheduler/scheduler.go`, `runner/internal/ws/client.go`

## Key File Locations

**Entry Points:**
- `server/friday/asgi.py`: ASGI app (HTTP + WS)
- `server/manage.py`: Django management CLI
- `web/src/main.ts`: SPA bootstrap
- `runner/cmd/friday-runner/main.go`: Runner binary
- `task/cli/`: `friday-task` CLI

**Configuration:**
- `server/friday/settings.py`: Backend settings
- `server/pyproject.toml`, `task/pyproject.toml`: Python deps + tooling
- `web/package.json`, `web/pnpm-workspace.yaml`, `web/vite.config.ts`: Frontend
- `runner/go.mod`, `runner/Makefile`: Runner
- `.env.example`, `docker-compose*.yaml`: Infra

**Core Logic:**
- `server/workflows/engine/scheduler.py`: Workflow execution
- `server/services/`: Domain services
- `web/src/api/client.ts`: API client + auth refresh

**Testing:**
- `server/tests/`: Backend pytest suite (`server/tests/conftest.py`)
- `web/src/**/__tests__/`, `web/src/**/*.spec.ts`: Frontend unit tests
- `web/src/test/setup.ts`: Vitest setup

## Naming Conventions

**Files:**
- Python: `snake_case.py` (e.g. `provider_config.py`)
- Vue pages: route-driven, kebab/bracket (e.g. `force-change-password.vue`, `[id].vue`)
- Vue components: typically `PascalCase.vue`
- TS modules: `camelCase.ts` (e.g. `accessTokens.ts`)
- Go: `lower_snake` files, package-per-directory (e.g. `executor.go`)
- Tests: backend `test_*.py`; frontend `*.spec.ts` / `*.test.ts`; Go `*_test.go`

**Directories:**
- Backend apps: lowercase singular/plural domain names (`chat`, `workflows`)
- Frontend: lowercase feature folders under `src/`

## Where to Add New Code

**New backend feature (within an app):**
- Models: `server/<app>/models/`
- API: `server/<app>/api/views.py` + `serializers.py`, wired in `server/<app>/urls.py` (and included in `server/friday/urls.py`)
- Domain logic: `server/services/`
- Tests: `server/tests/<app>/test_*.py`

**New workflow node:**
- Implementation: `server/workflows/nodes/<category>/<name>.py` (subclass `BaseNode`); auto-registered by `registry.py`
- UI schema: `web/src/types/workflow/node-definitions/`

**New frontend page:**
- Page: `web/src/pages/<route>.vue` (auto-routed)
- API: `web/src/api/<domain>.ts` (export from `web/src/api/index.ts`)
- State: `web/src/stores/<domain>.ts`
- Tests: co-located `__tests__/` or `*.spec.ts`

**New runner command/executor:**
- Command: `runner/internal/cmd/<name>.go`
- Executor/logic: appropriate `runner/internal/<area>/`

**Utilities:**
- Backend shared helpers: `server/common/`, `server/utils/`
- Frontend helpers: `web/src/utils/`, `web/src/lib/`

## Special Directories

**`server/data/`, `data/`:**
- Purpose: Runtime data (repos, sessions, credentials, SQLite db)
- Generated: Yes
- Committed: No

**`web/src/*.d.ts` (auto-imports, components, typed-router):**
- Purpose: Auto-generated type declarations (unplugin)
- Generated: Yes
- Committed: Yes (kept in sync)

**`server/<app>/migrations/`:**
- Purpose: Django ORM migrations
- Generated: Yes (`makemigrations`)
- Committed: Yes

**`__pycache__/`, `node_modules/`, `.venv/`, `*_cache/`:**
- Purpose: Build/runtime caches and deps
- Generated: Yes
- Committed: No

---

*Structure analysis: 2026-06-05*
