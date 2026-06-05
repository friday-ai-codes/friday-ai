# Coding Conventions

**Analysis Date:** 2026-06-05

Conventions differ by component. Backend/task are Python (ruff + mypy, `structlog`); frontend is TypeScript/Vue 3 (`@antfu/eslint-config`, Composition API); runner is Go (cobra/viper, `zerolog`). Comments and docstrings are frequently written in Chinese (zh-CN) across the backend.

## Naming Patterns

**Files:**
- Python: `snake_case.py` (`provider_config.py`, `graph_builder.py`)
- TS modules: `camelCase.ts` (`accessTokens.ts`, `useExecutionsStore.ts`)
- Vue components: `PascalCase.vue`; pages route-driven (`[id].vue`, `force-change-password.vue`)
- Go: package-per-directory, `lower_snake.go` (`manager_darwin.go`)

**Functions:**
- Python: `snake_case`; private helpers prefixed `_` (`_diagnose_empty_search`, `_run_in_thread`)
- TS: `camelCase` (`subscribeTokenRefresh`, `refreshToken`)
- Go: `PascalCase` exported, `camelCase` unexported

**Variables:**
- Python/TS follow the same case rules as functions
- Module-level singletons/state lowercase with `_` (`_debug_sessions`)

**Types:**
- Python: `PascalCase` classes; `Enum`/`str, Enum` for closed sets (`NodeCategory`, `PortType`); `@dataclass` for value objects (`NodeResult`, `ExecutionContext`); `TypedDict` for dict shapes (`GlobalVariable`)
- TS: `PascalCase` interfaces/types; `zod` schemas for validated shapes
- Go: `PascalCase` structs

## Code Style

**Formatting:**
- Python: `ruff format` — line length 100, target `py314` (`server/pyproject.toml`)
- TS/Vue: ESLint flat config with `@antfu/eslint-config` (`formatters: true`, `vue: true`) — `web/eslint.config.ts`
- Go: standard `gofmt`

**Linting:**
- Python ruff lint selects `E, F, I, W`; ignores `E501` (`[tool.ruff.lint]`)
- mypy with Django/DRF stubs, `python_version = "3.14"` (`[tool.mypy]`)
- ESLint relaxes several antfu defaults (e.g. `@typescript-eslint/no-explicit-any: off`, `no-console: off`, `unused-imports/no-unused-vars: off`)

## Import Organization

**Backend (ruff `I` / isort):**
1. Standard library
2. Third-party (Django, DRF, structlog)
3. First-party app modules (`workflows.*`, `services.*`, `common.*`)
- `# noqa: E402` is used when imports must follow runtime setup (e.g. Django app init in `asgi.py`, adrf patch in `conftest.py`)

**Frontend (antfu):**
- Auto-sorted import groups; `~/` path alias maps to `web/src/`
- Heavy use of unplugin auto-imports (Vue APIs, components, router) — declarations in `web/src/auto-imports.d.ts`, `components.d.ts`

## Error Handling

**Patterns:**
- Workflow nodes return `NodeResult(status="failed", error=...)` rather than raising past the engine (`server/workflows/nodes/base.py`)
- Domain exceptions centralized in `server/agents/core/exceptions.py`
- DRF default exception handling for API; explicit `PermissionDenied` for authz
- Frontend: `ApiError` class (status + detail + optional `body`) in `web/src/api/client.ts`; cookie-JWT refresh retries on 401
- Retries: `tenacity` (task), `go-retryablehttp` (runner)

## Logging

**Framework:** `structlog` (backend + task), `rs/zerolog` (runner). Console `LOGGING` dictConfig in `server/friday/settings.py`.

**Patterns:**
- Structured key-value events: `logger.info("node_definitions_json_loaded", path=path, node_count=len(mapping))`
- Credential-leak protection via `common.logging.configure_structlog`
- Per-library log levels tuned (`httpx`, `httpcore`, `qdrant_client`)

## Comments

**When to Comment:**
- Explain intent/constraints, not mechanics; many comments document "why" (e.g. compatibility patches, threading rationale)
- Comments and docstrings are commonly in Chinese (zh-CN) throughout the backend

**Docstrings:**
- Python modules/classes/functions use triple-quoted docstrings, often Chinese, frequently referencing "implementation contract" / phase IDs
- JSDoc-style comments appear in TS for non-obvious logic (`web/src/api/client.ts`)

## Function Design

**Size:** Small, focused functions; helpers extracted with `_` prefix.

**Parameters:** Keyword-heavy in Python; dataclass/TypedDict for structured inputs.

**Return Values:** Structured value objects (`NodeResult`, diagnostic dicts) over loose tuples; typed responses on the frontend.

## Module Design

**Exports:**
- Backend packages expose a curated API via `__init__.py` (`workflows/engine/__init__.py` re-exports `DAG`, `WorkflowEngine`)
- Frontend `web/src/api/index.ts` is a barrel re-exporting per-domain API modules and default instances

**Barrel Files:** Used on the frontend API layer; backend uses package `__init__.py` selectively.

**Patterns/Registries:**
- Singleton + auto-discovery for node types (`server/workflows/nodes/registry.py`)
- New nodes are registered simply by placing a `BaseNode` subclass in `server/workflows/nodes/<category>/`

---

*Convention analysis: 2026-06-05*
