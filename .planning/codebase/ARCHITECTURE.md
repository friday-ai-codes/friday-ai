<!-- refreshed: 2026-06-05 -->
# Architecture

**Analysis Date:** 2026-06-05

Friday AI is a distributed, multi-process system. A Django backend (`server/`) orchestrates AI-driven coding workflows as DAGs, persists state, and streams updates over WebSockets. A Vue 3 SPA (`web/`) is the control plane. A Go runner (`runner/`) registers with the server over WebSocket and launches containerized task executors (`task/`) that run the actual AI coding agent in isolation.

## System Overview

```text
┌─────────────────────────────────────────────────────────────┐
│                     Frontend (SPA)                           │
│   Vue 3 dashboard / flow editor / chat — `web/src/`          │
│   REST (`web/src/api/`) + WebSocket (`web/src/composables/`) │
└────────┬───────────────────────────────────┬────────────────┘
         │ HTTP /api, /v1                      │ WS (workflow/chat status)
         ▼                                     ▼
┌─────────────────────────────────────────────────────────────┐
│                  Backend — Django ASGI                       │
│  HTTP: DRF views  `server/<app>/api/` `server/<app>/urls.py` │
│  WS:   channels consumers  `server/workflows/consumers.py`   │
│  Workflow engine (DAG) `server/workflows/engine/`            │
│  Nodes  `server/workflows/nodes/`  Services `server/services/`│
└──────┬──────────────────────┬──────────────────┬────────────┘
        │ ORM                  │ WS dispatch       │ vector/RAG
        ▼                      ▼                   ▼
┌──────────────┐   ┌────────────────────┐   ┌─────────────────┐
│ DB (PG/      │   │ Go Runner          │   │ Qdrant + Redis  │
│ MySQL/SQLite)│   │ `runner/internal/` │   │ (RAG + channels)│
└──────────────┘   └─────────┬──────────┘   └─────────────────┘
                              │ Docker / k8s exec
                              ▼
                   ┌────────────────────────┐
                   │ Task container `task/`  │
                   │ claude-agent-sdk agent  │
                   └────────────────────────┘
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

**Overall:** Service-oriented Django backend with a node-based workflow engine (DAG executor), decoupled from a SPA control plane and an out-of-process containerized agent runtime.

**Key Characteristics:**
- Django apps are bounded contexts; each app owns `models/`, `api/` (DRF views/serializers), and `urls.py`
- Workflows are DAGs of pluggable, auto-registered nodes (`workflows/nodes/<category>/`)
- Async-first: `adrf` async DRF views, `channels` consumers, `asgiref.sync_to_async` bridges to the ORM
- Credentials and provider config resolved at runtime from the DB (encrypted), not env
- Real-time state delivered over WebSockets; REST for CRUD/commands

## Layers

**Presentation (frontend):**
- Purpose: User-facing dashboard, flow editor, chat
- Location: `web/src/pages/`, `web/src/components/`
- Depends on: API client (`web/src/api/`), stores (`web/src/stores/`)
- Used by: Browser

**API layer (backend):**
- Purpose: HTTP request handling, auth, serialization
- Location: `server/<app>/api/views.py`, `server/<app>/api/serializers.py`, `server/<app>/urls.py`
- Depends on: services, models
- Used by: SPA, OpenAI-compatible clients (`server/compat/`)

**Domain/service layer:**
- Purpose: Business logic, RAG, git platform, provider resolution
- Location: `server/services/`
- Depends on: models, external SDKs
- Used by: API views, workflow nodes

**Workflow engine:**
- Purpose: Execute workflow DAGs node-by-node with scheduling, retries, debug
- Location: `server/workflows/engine/`, `server/workflows/nodes/`
- Depends on: node registry, execution models, hooks
- Used by: workflow API + WS consumers

**Persistence:**
- Purpose: ORM models + migrations
- Location: `server/<app>/models/`, `server/<app>/migrations/`
- Depends on: Django ORM
- Used by: all backend layers

**Execution runtime (out-of-process):**
- Purpose: Schedule + run isolated agent containers
- Location: `runner/internal/`, `task/`
- Depends on: Docker/k8s, claude-agent-sdk
- Used by: server (via WebSocket dispatch + HTTP callbacks)

## Data Flow

### Primary Path — Workflow Execution

1. Client triggers execution via REST (`server/workflows/api/views.py`)
2. `WorkflowEngine` loads the DAG (`server/workflows/engine/dag.py`) and walks ready nodes (`server/workflows/engine/scheduler.py`)
3. Each node resolves its class from `NodeRegistry` and runs with an `ExecutionContext` (`server/workflows/nodes/base.py`)
4. AI coding nodes (`server/workflows/nodes/ai/coding.py`) dispatch a job to the Go runner over WebSocket (`server/runners/`)
5. Runner launches a `friday-task` container (`runner/internal/docker/executor.go` / `k8s/executor.go`); the agent runs (`task/friday_task/`)
6. Task posts progress/results back via HTTP callbacks (`server/subagent/api/callbacks.py`, runner callback `runner/internal/callback/server.go`)
7. Node results persist (`NodeExecution`) and status is pushed to clients via channels consumers (`server/workflows/consumers.py`)

### Secondary Flow — Chat / RAG

1. Client opens chat (`web/src/pages/chat.vue`) → REST/WS to `server/chat/`
2. Provider resolved (`server/services/provider_config.py`) and credentials decrypted
3. RAG retrieval via Qdrant (`server/services/qdrant_service.py`, `server/services/retrieval/`)
4. Streamed tokens pushed back over WebSocket

**State Management:**
- Backend: persisted in DB (`WorkflowExecution`, `NodeExecution`); transient debug/pause state in module-level `_debug_sessions` in `server/workflows/engine/scheduler.py`
- Frontend: Pinia stores (`web/src/stores/`) + TanStack Query for server cache

## Key Abstractions

**BaseNode:**
- Purpose: Unit of workflow execution
- Examples: `server/workflows/nodes/ai/`, `server/workflows/nodes/control/`, `server/workflows/nodes/git/`
- Pattern: Subclass `BaseNode`, declare ports (`NodePort`), implement execution returning `NodeResult`

**NodeRegistry (singleton):**
- Purpose: Auto-discovery of node types via package walk; merges UI schema from `web/.../node-definitions.json`
- Examples: `server/workflows/nodes/registry.py`
- Pattern: Module-import side-effect registration

**ExecutionContext / NodeResult:**
- Purpose: Pass inputs/upstream outputs into a node and standardize outputs + branch handle
- Examples: `server/workflows/nodes/base.py`

**Service modules:**
- Purpose: Stateless domain operations callable from views and nodes
- Examples: `server/services/graph_builder.py`, `server/services/provider_config.py`

## Entry Points

**Backend ASGI:**
- Location: `server/friday/asgi.py` (`application`)
- Triggers: uvicorn/daphne
- Responsibilities: HTTP→Django, WS→channels routing

**Backend WSGI:**
- Location: `server/friday/wsgi.py`
- Triggers: gunicorn (prod, HTTP only)

**Frontend:**
- Location: `web/src/main.ts`
- Triggers: Vite build/serve; mounts `App.vue`, installs router/Pinia/Query/i18n

**Runner CLI:**
- Location: `runner/cmd/friday-runner/main.go` → `runner/internal/cmd/` (cobra commands: `run`, `register`, `service`, …)

**Task CLI:**
- Location: `task/cli/` (`friday-task` entrypoint)

## Architectural Constraints

- **Threading:** ASGI async event loop; the workflow engine spawns background threads with their own event loops (`_run_in_thread` in `server/workflows/engine/scheduler.py`). ORM access from async contexts goes through `sync_to_async`.
- **Global state:** Module-level `_debug_sessions` dict and `NodeRegistry` singleton (`server/workflows/nodes/registry.py`). Background indexing uses a daemon-thread runner (`server/services/background_runner.py`).
- **Cross-process coupling:** Server↔runner over WebSocket + HTTP callbacks; contracts must stay in sync across `server/runners/`, `runner/internal/ws/`, and `server/subagent/api/`.
- **adrf compatibility:** A monkeypatch (`core.patches.patch_asyncio_iscoroutinefunction`) must run before Django loads (applied in `server/tests/conftest.py`).

## Anti-Patterns

### ORM access from raw async without bridge

**What happens:** Calling synchronous ORM methods directly inside an async node/consumer.
**Why it's wrong:** Raises `SynchronousOnlyOperation` and can break the event loop.
**Do this instead:** Wrap with `asgiref.sync.sync_to_async` as done across `server/workflows/engine/scheduler.py`.

### Reading provider/Git credentials from env

**What happens:** Expecting `ANTHROPIC_API_KEY`-style env vars for LLM/Git access.
**Why it's wrong:** Credentials are stored encrypted in the DB and resolved per scope.
**Do this instead:** Resolve via `server/services/provider_config.py` (`ProviderConfigService`); env is for infra only.

## Error Handling

**Strategy:** DRF exception handling for HTTP; structured `NodeResult(status="failed", error=...)` for nodes; explicit exceptions in `server/agents/core/exceptions.py`.

**Patterns:**
- Node failures captured as result status, not raised past the engine, enabling retries/error-handling fields on `NodeExecution`
- `tenacity` retries in task executor; `hashicorp/go-retryablehttp` in runner

## Cross-Cutting Concerns

**Logging:** `structlog` (backend + task), `zerolog` (runner); credential-leak protection in `common.logging.configure_structlog`
**Validation:** `jsonschema` for node port schemas; `zod`/`vee-validate` on frontend; DRF serializers for API
**Authentication:** Cookie-based JWT (`common.authentication.CookieJWTAuthentication`); WS auth via `AuthMiddlewareStack` + `WSSEnforcementMiddleware`

---

*Architecture analysis: 2026-06-05*
