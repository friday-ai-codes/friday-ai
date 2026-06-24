<!-- GSD:project-start source:PROJECT.md -->

## Project

**Friday AI**

Friday AI 是一个 AI 驱动的敏捷开发自动化系统：它把飞书（Lark）项目管理中的需求自动转化为代码合并请求（MR/PR），从需求触发、AI 技术方案生成、到容器化 AI 编码代理执行、再到自动建分支提交 PR，全链路可编排、可观测。面向需要把"需求→代码"流程自动化的研发团队与平台工程师，自托管部署（Docker Compose / k8s）。

系统由四个组件构成：Django 后端（`server/`，REST + WebSocket + 工作流引擎 + 代码智能/RAG）、Vue 3 前端（`web/`，控制台/流程编辑器/对话）、Go 运行器（`runner/`，调度并在 Docker/k8s 中运行任务容器）、Python 任务执行器（`task/`，容器内运行 claude-agent-sdk 编码代理）。

**Core Value:** 让团队"开箱即用、安全地"把需求自动变成代码：用户能顺利完成首次部署与登录、配好必备的 AI 供应商，然后让工作流把飞书需求自动跑成 PR。如果第一步进不去（登录/配置），后面一切都无从谈起。

### Constraints

- **Tech stack**: 后端 Django 5.1+/Python 3.14（adrf 异步 DRF + channels），前端 Vue 3 + TS + Tailwind 4 + reka-ui，凭证用 `cryptography` Fernet 加密 — 必须沿用既有栈与异步约束（async ORM 走 `sync_to_async`）。
- **Security**: 初始化接口必须 fail-closed —— 仅当"无 superuser"时可用，存在 superuser 即拒绝；防止被用于重置/接管现有实例。
- **Compatibility**: 已有部署（已存在 superuser、或用 env/命令建过号）升级后行为不得回退；`init_superuser` / `reset_superuser_password` 命令保留。
- **Convention**: 新增凭证/设置必须复用 `ProviderCredential` / `SystemSetting` / `SettingKeys` 与现有 service 层，不绕过加密与权限。
- **i18n**: 向导文案接入既有 `vue-i18n`，默认中文。

<!-- GSD:project-end -->

<!-- GSD:stack-start source:codebase/STACK.md -->

## Technology Stack

| Component | Path | Language | Role |
|-----------|------|----------|------|
| Backend / API | `server/` | Python 3.14 (Django) | REST + WebSocket API, workflow engine, code intelligence (codegraph/RAG) |
| Frontend | `web/` | TypeScript (Vue 3) | SPA dashboard, flow editor, chat UI |
| Task executor | `task/` | Python 3.14 | Containerized AI coding agent run inside Docker by the runner |
| Runner | `runner/` | Go 1.25 | Host agent that schedules and runs task containers (Docker / k8s) |
| Docs | `docs/` (root `package.json`) | VitePress / Vue | Documentation site |

## Languages

- Python 3.14 (`>=3.14`) — backend (`server/`) and task executor (`task/`); pinned via `server/.python-version`
- TypeScript ~5.9.3 — frontend (`web/`), Vue 3 SFCs
- Go 1.25.0 — runner (`runner/go.mod`)
- Vue 3 templates (`web/src/**/*.vue`)
- Shell scripts (`scripts/`, `runner/entrypoint.sh`)
- SQL via Django ORM migrations

## Runtime

- Python `>=3.14`
- ASGI server: `uvicorn[standard]>=0.30` (dev, see `Makefile`), `daphne>=4.2.1` + `gunicorn>=23.0.0` (prod)
- ASGI app: `friday.asgi:application`; WSGI app: `friday.wsgi:application`
- Node (version pinned in `web/.nvmrc`)
- Dev/build tool: Vite — note it is aliased to `rolldown-vite` via pnpm overrides in `web/pnpm-workspace.yaml`
- Go 1.25.0 compiled binary (`runner/cmd/friday-runner/main.go` → `friday-runner`)
- Python: `uv` (lockfiles `server/uv.lock`, `task/uv.lock`); build backend `hatchling`
- JS: `pnpm@10.28.0` (frontend, `web/pnpm-lock.yaml`); root docs use `pnpm@10.30.3`
- Go: Go modules (`runner/go.mod`)
- Lockfiles: present for all three ecosystems

## Frameworks

- `django>=5.1` — web framework
- `djangorestframework>=3.15` — REST API
- `adrf>=0.1.12` — async DRF views
- `djangorestframework-simplejwt>=5.3` — JWT auth (with token blacklist)
- `drf-spectacular>=0.27` — OpenAPI/Swagger schema
- `channels[daphne]>=4.3.2` + `daphne>=4.2.1` — WebSocket / ASGI
- `django-apscheduler>=0.7.0` — scheduled jobs (repo sync polling)
- `django-environ>=0.11` — env-based settings
- `claude-agent-sdk>=0.1.58,<0.2` — Anthropic Claude agent SDK
- `anthropic>=0.40.0`, `openai>=2.16.0`, `google-genai>=1.0.0` — provider SDKs
- `langgraph>=1.1.6` + `langgraph-checkpoint-sqlite>=3.0.3` — agent orchestration graph
- `langchain>=1.2.15` with `langchain-anthropic`, `langchain-openai`, `langchain-google-genai`, `langchain-ollama`
- `llama-index>=0.10.0` + `llama-index-vector-stores-qdrant>=0.2.0` — RAG indexing
- `fastembed>=0.4.0` — local embeddings
- `qdrant-client>=1.9.0` — vector DB client
- `tree-sitter>=0.21.0` + grammars: go, javascript, typescript, python, css, html, json
- `pygls>=2.0` — Language Server Protocol client; integrates external `vue-language-server` (volar) and `gopls` (configured in `server/friday/settings.py` `LSP_SERVERS` / `EXTRACTOR_BACKENDS`)
- `vue@^3.5.26` — UI framework (Composition API, `<script setup>`)
- `vue-router` (file-based via `unplugin-vue-router`), `pinia` — state
- `@tanstack/vue-query` — server state; `@tanstack/vue-table` — tables
- `@vue-flow/*` — node/flow editor; `3d-force-graph` + `three` — graph viz
- `@tiptap/*` — rich text editor; `codemirror` / `@codemirror/*` — code editor
- `tailwindcss@^4.1.18` + `reka-ui` + `class-variance-authority` — styling/components
- `vee-validate` + `zod` — form validation; `vue-i18n` — i18n; `echarts`/`vue-echarts` — charts
- `spf13/cobra` + `spf13/viper` — CLI & config
- `docker/docker` (v28) + `docker/go-connections` — Docker SDK
- `coder/websocket` — WebSocket client to server
- `charmbracelet/huh` + `lipgloss` + `bubbletea` — interactive TUI
- `hashicorp/go-retryablehttp` — resilient HTTP; `rs/zerolog` — logging
- `shirou/gopsutil/v4` — system metrics
- `claude-agent-sdk==0.1.58` (pinned) — runs the coding agent
- `pydantic>=2.6` + `pydantic-settings>=2.2` — config/models
- `click>=8.0` — CLI (`friday-task = "cli:main"`)
- `gitpython`, `httpx`, `structlog`, `tenacity`, `jinja2`
- Backend: `pytest>=9.0.2`, `pytest-asyncio`, `pytest-django>=4.8`, `pytest-cov`, `factory-boy`, `respx` (httpx mocking), `pytest-socket` (network isolation)
- Frontend: `vitest@^4`, `@vue/test-utils`, `happy-dom`, `@vitest/coverage-v8`, `@playwright/test` (E2E)
- Go: standard `testing` + `gotest.tools/v3`
- Backend: `uv`, `hatchling`, `mypy>=1.14` (+ django/drf stubs), `ruff>=0.14`
- Frontend: `vite` (rolldown), `vue-tsc`, `eslint` (`@antfu/eslint-config`), `tsx`, unplugin auto-import/components/i18n/router, `vue-macros`
- Go: `runner/Makefile`

## Key Dependencies

- `claude-agent-sdk` — core of the AI coding agent (both `server/` and `task/`)
- `langgraph` / `langchain` — LLM orchestration in workflow nodes
- `qdrant-client` + `fastembed` + `llama-index` — RAG / semantic code search
- `tree-sitter` + `pygls` — AST extraction and LSP-backed code intelligence
- `channels` / `daphne` — real-time WebSocket updates (workflow status, chat streaming)
- `psycopg[binary]>=3.3` (PostgreSQL), `mysqlclient>=2.2` (MySQL/MariaDB) — DB drivers
- `docker>=7.1.0` (Python SDK, server side) — container orchestration
- `gitpython` + `python-gitlab>=4.0` + `PyGithub>=2.0` — Git platform integration
- `cryptography>=42.0` + `passlib[argon2]` — encryption & password hashing
- `whitenoise>=6.7` — static file serving
- `pywebpush>=2.3.0` — browser push notifications
- `lark-oapi>=1.5.2` — Feishu (Lark) integration
- `paramiko>=4.0.0` — SSH

## Configuration

- Backend settings: `server/friday/settings.py`, loaded via `django-environ`
- `.env` resolution order: `server/.env` first, then project root `.env` (`env.read_env(...)`)
- Template: `.env.example` at repo root (documents all vars)
- `FRIDAY_ENV` / `FRIDAY_PRODUCTION` toggle production hardening (forces `DEBUG=False`, non-default `SECRET_KEY`, explicit `ALLOWED_HOSTS`)
- Frontend config via Vite env: `VITE_API_URL`, `VITE_USE_POLLING` (see `Makefile`, `API_DETECTOR_CONFIG` in settings)
- Runner config: TOML file (`config.toml` under config dir) + `FRIDAY_RUNNER_*` env vars bound by viper (`runner/internal/config/config.go`)
- `server/pyproject.toml` — backend deps, pytest/mypy/ruff/coverage config
- `task/pyproject.toml` — task executor deps & CLI entrypoint
- `web/package.json` + `web/pnpm-workspace.yaml` (pnpm catalog pins all versions) + `web/vite.config.ts` + `web/tsconfig.json`
- `runner/go.mod` + `runner/Makefile`
- Per-component `Dockerfile` (`server/`, `web/`, `task/`, `runner/`)
- `docker-compose.yaml` (prebuilt images) + `docker-compose.build.yaml` (source build)
- Root `Makefile` — `make dev` (tmux split server+web), `make install`, `make build-runner`, `make build-task`

## Platform Requirements

- Python 3.14 + `uv`; Node + `pnpm`; Go 1.25
- Docker daemon (runner spawns task containers via `/var/run/docker.sock`)
- Optional: PostgreSQL, Redis, Qdrant (or use SQLite + in-memory channel layer for local dev)
- Docker Compose stack: `server`, `web` (Nginx proxy), `runner`, `postgres:17-alpine`, `redis:7-alpine`, `qdrant/qdrant`
- Default ports: web `10240`, API `10241`, Qdrant `6333/6334`, Redis `6379`
- Prebuilt images: `ghcr.io/friday-ai-codes/friday-ai/{server,web,runner}`
- CI/CD: GitHub Actions (`.github/workflows/ci.yaml`, `.github/workflows/release.yaml`)

<!-- GSD:stack-end -->

<!-- GSD:conventions-start source:CONVENTIONS.md -->

## Conventions

## Naming Patterns

- Python: `snake_case.py` (`provider_config.py`, `graph_builder.py`)
- TS modules: `camelCase.ts` (`accessTokens.ts`, `useExecutionsStore.ts`)
- Vue components: `PascalCase.vue`; pages route-driven (`[id].vue`, `force-change-password.vue`)
- Go: package-per-directory, `lower_snake.go` (`manager_darwin.go`)
- Python: `snake_case`; private helpers prefixed `_` (`_diagnose_empty_search`, `_run_in_thread`)
- TS: `camelCase` (`subscribeTokenRefresh`, `refreshToken`)
- Go: `PascalCase` exported, `camelCase` unexported
- Python/TS follow the same case rules as functions
- Module-level singletons/state lowercase with `_` (`_debug_sessions`)
- Python: `PascalCase` classes; `Enum`/`str, Enum` for closed sets (`NodeCategory`, `PortType`); `@dataclass` for value objects (`NodeResult`, `ExecutionContext`); `TypedDict` for dict shapes (`GlobalVariable`)
- TS: `PascalCase` interfaces/types; `zod` schemas for validated shapes
- Go: `PascalCase` structs

## Code Style

- Python: `ruff format` — line length 100, target `py314` (`server/pyproject.toml`)
- TS/Vue: ESLint flat config with `@antfu/eslint-config` (`formatters: true`, `vue: true`) — `web/eslint.config.ts`
- Go: standard `gofmt`
- Python ruff lint selects `E, F, I, W`; ignores `E501` (`[tool.ruff.lint]`)
- mypy with Django/DRF stubs, `python_version = "3.14"` (`[tool.mypy]`)
- ESLint relaxes several antfu defaults (e.g. `@typescript-eslint/no-explicit-any: off`, `no-console: off`, `unused-imports/no-unused-vars: off`)

## Import Organization

- `# noqa: E402` is used when imports must follow runtime setup (e.g. Django app init in `asgi.py`, adrf patch in `conftest.py`)
- Auto-sorted import groups; `~/` path alias maps to `web/src/`
- Heavy use of unplugin auto-imports (Vue APIs, components, router) — declarations in `web/src/auto-imports.d.ts`, `components.d.ts`

## Error Handling

- Workflow nodes return `NodeResult(status="failed", error=...)` rather than raising past the engine (`server/workflows/nodes/base.py`)
- Domain exceptions centralized in `server/agents/core/exceptions.py`
- DRF default exception handling for API; explicit `PermissionDenied` for authz
- Frontend: `ApiError` class (status + detail + optional `body`) in `web/src/api/client.ts`; cookie-JWT refresh retries on 401
- Retries: `tenacity` (task), `go-retryablehttp` (runner)

## Logging

- Structured key-value events: `logger.info("node_definitions_json_loaded", path=path, node_count=len(mapping))`
- Credential-leak protection via `common.logging.configure_structlog`
- Per-library log levels tuned (`httpx`, `httpcore`, `qdrant_client`)

## Comments

- Explain intent/constraints, not mechanics; many comments document "why" (e.g. compatibility patches, threading rationale)
- Comments and docstrings are commonly in Chinese (zh-CN) throughout the backend
- Python modules/classes/functions use triple-quoted docstrings, often Chinese, frequently referencing "implementation contract" / phase IDs
- JSDoc-style comments appear in TS for non-obvious logic (`web/src/api/client.ts`)

## Function Design

## Module Design

- Backend packages expose a curated API via `__init__.py` (`workflows/engine/__init__.py` re-exports `DAG`, `WorkflowEngine`)
- Frontend `web/src/api/index.ts` is a barrel re-exporting per-domain API modules and default instances
- Singleton + auto-discovery for node types (`server/workflows/nodes/registry.py`)
- New nodes are registered simply by placing a `BaseNode` subclass in `server/workflows/nodes/<category>/`

<!-- GSD:conventions-end -->

<!-- GSD:architecture-start source:ARCHITECTURE.md -->

## Architecture

## System Overview

```text

```

## Component Responsibilities

| Component | Responsibility | File |
|-----------|----------------|------|
| ASGI entrypoint | Routes HTTP → Django, WS → channels | `server/friday/asgi.py` |
| URL router | Maps `/api/*`, `/v1/*` to app urlconfs | `server/friday/urls.py` |
| Workflow engine | Executes workflow DAGs, manages node scheduling, debug/pause | `server/workflows/engine/scheduler.py` |
| DAG model | Topological structure of nodes/edges | `server/workflows/engine/dag.py` |
| Node registry | Auto-discovers and registers node types | `server/workflows/nodes/registry.py` |
| Node base | Contract for all executable nodes | `server/workflows/nodes/base.py` |
| WS consumers | Push workflow/runner status to clients | `server/workflows/consumers.py`, `server/runners/routing.py` |
| Services | Reusable domain logic (RAG, git, providers) | `server/services/` |
| Agent core | Agent state, events, results, exceptions | `server/agents/core/` |
| Go runner | Schedules + runs task containers | `runner/internal/scheduler/scheduler.go` |
| Task executor | Runs the AI coding agent in a container | `task/friday_task/`, `task/cli/` |
| SPA bootstrap | App, router guards, plugins | `web/src/main.ts` |
| API client | Typed fetch wrapper, cookie-JWT refresh | `web/src/api/client.ts` |

## Pattern Overview

- Django apps are bounded contexts; each app owns `models/`, `api/` (DRF views/serializers), and `urls.py`
- Workflows are DAGs of pluggable, auto-registered nodes (`workflows/nodes/<category>/`)
- Async-first: `adrf` async DRF views, `channels` consumers, `asgiref.sync_to_async` bridges to the ORM
- Credentials and provider config resolved at runtime from the DB (encrypted), not env
- Real-time state delivered over WebSockets; REST for CRUD/commands

## Layers

- Purpose: User-facing dashboard, flow editor, chat
- Location: `web/src/pages/`, `web/src/components/`
- Depends on: API client (`web/src/api/`), stores (`web/src/stores/`)
- Used by: Browser
- Purpose: HTTP request handling, auth, serialization
- Location: `server/<app>/api/views.py`, `server/<app>/api/serializers.py`, `server/<app>/urls.py`
- Depends on: services, models
- Used by: SPA, OpenAI-compatible clients (`server/compat/`)
- Purpose: Business logic, RAG, git platform, provider resolution
- Location: `server/services/`
- Depends on: models, external SDKs
- Used by: API views, workflow nodes
- Purpose: Execute workflow DAGs node-by-node with scheduling, retries, debug
- Location: `server/workflows/engine/`, `server/workflows/nodes/`
- Depends on: node registry, execution models, hooks
- Used by: workflow API + WS consumers
- Purpose: ORM models + migrations
- Location: `server/<app>/models/`, `server/<app>/migrations/`
- Depends on: Django ORM
- Used by: all backend layers
- Purpose: Schedule + run isolated agent containers
- Location: `runner/internal/`, `task/`
- Depends on: Docker/k8s, claude-agent-sdk
- Used by: server (via WebSocket dispatch + HTTP callbacks)

## Data Flow

### Primary Path — Workflow Execution

### Secondary Flow — Chat / RAG

- Backend: persisted in DB (`WorkflowExecution`, `NodeExecution`); transient debug/pause state in module-level `_debug_sessions` in `server/workflows/engine/scheduler.py`
- Frontend: Pinia stores (`web/src/stores/`) + TanStack Query for server cache

## Key Abstractions

- Purpose: Unit of workflow execution
- Examples: `server/workflows/nodes/ai/`, `server/workflows/nodes/control/`, `server/workflows/nodes/git/`
- Pattern: Subclass `BaseNode`, declare ports (`NodePort`), implement execution returning `NodeResult`
- Purpose: Auto-discovery of node types via package walk; merges UI schema from `web/.../node-definitions.json`
- Examples: `server/workflows/nodes/registry.py`
- Pattern: Module-import side-effect registration
- Purpose: Pass inputs/upstream outputs into a node and standardize outputs + branch handle
- Examples: `server/workflows/nodes/base.py`
- Purpose: Stateless domain operations callable from views and nodes
- Examples: `server/services/graph_builder.py`, `server/services/provider_config.py`

## Entry Points

- Location: `server/friday/asgi.py` (`application`)
- Triggers: uvicorn/daphne
- Responsibilities: HTTP→Django, WS→channels routing
- Location: `server/friday/wsgi.py`
- Triggers: gunicorn (prod, HTTP only)
- Location: `web/src/main.ts`
- Triggers: Vite build/serve; mounts `App.vue`, installs router/Pinia/Query/i18n
- Location: `runner/cmd/friday-runner/main.go` → `runner/internal/cmd/` (cobra commands: `run`, `register`, `service`, …)
- Location: `task/cli/` (`friday-task` entrypoint)

## Architectural Constraints

- **Threading:** ASGI async event loop; the workflow engine spawns background threads with their own event loops (`_run_in_thread` in `server/workflows/engine/scheduler.py`). ORM access from async contexts goes through `sync_to_async`.
- **Global state:** Module-level `_debug_sessions` dict and `NodeRegistry` singleton (`server/workflows/nodes/registry.py`). Background indexing uses a daemon-thread runner (`server/services/background_runner.py`).
- **Cross-process coupling:** Server↔runner over WebSocket + HTTP callbacks; contracts must stay in sync across `server/runners/`, `runner/internal/ws/`, and `server/subagent/api/`.
- **adrf compatibility:** A monkeypatch (`core.patches.patch_asyncio_iscoroutinefunction`) must run before Django loads (applied in `server/tests/conftest.py`).

## Anti-Patterns

### ORM access from raw async without bridge

### Reading provider/Git credentials from env

## Error Handling

- Node failures captured as result status, not raised past the engine, enabling retries/error-handling fields on `NodeExecution`
- `tenacity` retries in task executor; `hashicorp/go-retryablehttp` in runner

## Cross-Cutting Concerns

<!-- GSD:architecture-end -->

<!-- GSD:skills-start source:skills/ -->

## Project Skills

No project skills found. Add skills to any of: `.claude/skills/`, `.agents/skills/`, `.cursor/skills/`, `.github/skills/`, or `.codex/skills/` with a `SKILL.md` index file.
<!-- GSD:skills-end -->

<!-- GSD:workflow-start source:GSD defaults -->

## GSD Workflow Enforcement

Before using Edit, Write, or other file-changing tools, start work through a GSD command so planning artifacts and execution context stay in sync.

Use these entry points:

- `/gsd-quick` for small fixes, doc updates, and ad-hoc tasks
- `/gsd-debug` for investigation and bug fixing
- `/gsd-execute-phase` for planned phase work

Do not make direct repo edits outside a GSD workflow unless the user explicitly asks to bypass it.
<!-- GSD:workflow-end -->

<!-- GSD:profile-start -->

## Developer Profile

> Profile not yet configured. Run `/gsd-profile-user` to generate your developer profile.
> This section is managed by `generate-claude-profile` -- do not edit manually.
<!-- GSD:profile-end -->

## 可观测性与日志规范（强制）

新增或修改任何功能（API / 工作流节点 / 服务 / 任务 / webhook / 工具 / LLM 调用 / 召回）时，必须按规范补齐日志与指标埋点。完整规范见 `.planning/observability/LOGGING-SPEC.md`，里程碑方案见 `.planning/observability/MILESTONE-PROPOSAL.md`，强制规则见 `.cursor/rules/observability-logging.mdc`。

核心要求：

- 用 `structlog.get_logger(__name__)`，事件名 snake_case（started/completed/failed），字段用 kv；关键生命周期带 `duration_ms`。
- 每个事件设 `category`（`caller` 调用类 / `sampling` 采样类）与 `component`。
- 绑定触发用户：入口走统一中间件自动注入 `user_id/source/request_id/trace_id`；后台任务（durable/background_runner/workflow/scheduler/飞书·webhook）显式带 `initiated_by_user_id`；系统行为标 `system`。
- 脱敏不可绕过：凭证/token/上游响应体/异常文本走 `redact_credentials` / `redact_secrets_in_text`；入库留痕走 `redact_for_ledger`。
- 指标与留痕分离：指标走精简事件表（`RequestMetric` / 扩展的 `ModelUsageRecord` 等，SQL 聚合）；调用详情/召回内容/会话原始数据走 Interaction Ledger（`server/interactions/`）；排障日志走系统日志（采样）。三者用 `request_id/run_id/conversation_id` 关联。
- 新增 LLM 调用赋 `call_source`（枚举见 LOGGING-SPEC §4.1）并上报请求数/token/TTFT/上游错误码；新增请求入口纳入 QPS/错误率/时长；新增召回上报条数/分层耗时/score 并写 `RetrievalTrace`（MCP + AI 对话两条链）。
- 观测代码 best-effort，绝不反噬业务；高频循环禁止 INFO 刷屏。
