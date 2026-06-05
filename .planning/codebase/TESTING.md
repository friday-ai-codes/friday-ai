# Testing Patterns

**Analysis Date:** 2026-06-05

The backend has the most mature test suite — 430+ `test_*.py` files under `server/tests/`, mirroring app structure, run with pytest + pytest-django and **network isolation enforced** (`pytest-socket`). The frontend uses Vitest (happy-dom) for units and Playwright for E2E. The runner uses Go's standard `testing` with `gotest.tools/v3`.

## Test Framework

**Runner:**
- Backend: `pytest>=9.0.2` + `pytest-django>=4.8` + `pytest-asyncio>=1.3.0` — config in `server/pyproject.toml` `[tool.pytest.ini_options]`
- Frontend: `vitest@^4` — config `web/vitest.config.ts` (merges `vite.config.ts`)
- Runner: Go `testing` + `gotest.tools/v3`
- E2E: `@playwright/test`

**Assertion Library:**
- Backend: plain `assert` (pytest rewrite)
- Frontend: Vitest `expect` + `@vue/test-utils`

**Run Commands:**
```bash
# Backend (from server/)
uv run pytest                               # Run all (CI markers excluded)
uv run pytest -m perf                       # Perf benchmarks (skipped by default)
uv run pytest -m integration                # Integration tests (need external binaries)
uv run pytest --cov --cov-report=html       # Coverage

# Frontend (from web/)
pnpm test                                   # Vitest
pnpm test --coverage                        # Coverage (v8)

# Runner (from runner/)
go test ./...
```

## Test File Organization

**Location:**
- Backend: separate `server/tests/` tree mirroring apps (`tests/agents/`, `tests/chat/`, `tests/services/`, `tests/e2e/`)
- Frontend: co-located `__tests__/` folders and `*.spec.ts` next to source (`web/src/pages/__tests__/`, `web/src/stores/__tests__/`)

**Naming:**
- Backend: `test_*.py` (enforced via `python_files = ["test_*.py"]`)
- Frontend: `*.spec.ts` / `*.test.ts` (`include: ['src/**/*.{test,spec}.{js,ts}']`)
- Go: `*_test.go`

**Structure:**
```
server/tests/
├── conftest.py            # Fixtures: APIClient, users, memberships, cache reset
├── fixtures/ helpers/     # Shared factories + helpers
├── e2e/fixtures/mock_services.py   # Registered as pytest_plugins (root conftest.py)
├── agents/ chat/ services/ codegraph/ ...  # Per-domain test modules
└── test_*.py              # Top-level cross-cutting tests
```

## Test Structure

**Suite Organization:**
```python
# server/tests/test_search_diagnostics.py (representative)
from agents.tools.space_tools import _diagnose_empty_search

def test_diagnose_multi_keyword_query() -> None:
    """用户实际 case：9 个空格分隔关键词混搜 → 应建议拆 query。"""
    diag = _diagnose_empty_search(query="...", min_score=0.5, l3_top_score=None, ...)
    assert diag["query_analysis"]["keyword_count"] == 9
```

**Patterns:**
- Plain pytest functions (not xunit classes) with type-annotated signatures
- `asyncio_mode = "auto"` — `async def` tests run without explicit markers
- `addopts`: `-v --tb=short --disable-socket --allow-unix-socket -m 'not perf and not integration and not slow'`
- Custom markers: `perf`, `integration`, `slow`, plus targeted opt-out markers (`real_history_load`, `no_workdir_stub`) to disable specific autouse fixtures

## Mocking

**Framework:** `respx` (httpx mocking), `unittest.mock`, `factory-boy` (model factories); `pytest-socket` blocks real network.

**Patterns:**
```python
# Provider health checks mock httpx via respx; external HTTP forbidden by --disable-socket
# Autouse fixtures stub side-effecting subsystems (background runner, repo workdir prep)
@pytest.fixture(autouse=True)
def _reset_background_runner():
    # drains in-flight background indexing tasks and tears down worker threads
    ...
```

**What to Mock:**
- All outbound HTTP (LLM providers, Git platforms) — network is disabled by default
- Heavy subsystems: background indexing runner, repo clone/workdir prep, LSP binaries
- E2E external services via `tests/e2e/fixtures/mock_services.py`

**What NOT to Mock:**
- The unit under test and pure in-process logic (e.g. diagnostics, DAG topology)
- The DB — use pytest-django test DB + `factory-boy` factories instead

## Fixtures and Factories

**Test Data:**
```python
# server/tests/conftest.py provides shared fixtures:
#   APIClient, User (custom accounts.User), Project, Repository, ProjectMembership/Role
# factory-boy factories under server/tests/fixtures/ build model instances
```

**Location:**
- Shared fixtures: `server/tests/conftest.py` (+ root `conftest.py` for plugin registration)
- Factories/helpers: `server/tests/fixtures/`, `server/tests/helpers/`
- Frontend setup: `web/src/test/setup.ts`

## Coverage

**Requirements:** No hard threshold enforced. Backend coverage scoped to `friday` source, omitting migrations/tests (`[tool.coverage.run]`).

**View Coverage:**
```bash
uv run pytest --cov --cov-report=html   # backend
pnpm test --coverage                    # frontend (v8 → text/json/html)
```

## Test Types

**Unit Tests:**
- Backend: dominant — per-app logic, nodes, services, tools (`server/tests/**`)
- Frontend: stores, composables, components, page logic (`web/src/**/__tests__`)

**Integration Tests:**
- Marked `integration` (require external binaries like `vue-language-server`); skipped in CI by default

**E2E Tests:**
- Backend e2e under `server/tests/e2e/` with mocked services
- Frontend `@playwright/test` (excluded from Vitest run via `exclude: [...,'tests/e2e/**']`)

## Common Patterns

**Async Testing:**
```python
# asyncio_mode = "auto" → just write async tests
async def test_node_executes() -> None:
    result = await node.run(context)
    assert result.status == "completed"
```

**Error Testing:**
```python
import pytest
with pytest.raises(PermissionDenied):
    service.do_protected_action(unauthorized_user)
```

**Network Isolation:**
```python
# Forgetting to mock outbound HTTP fails fast under --disable-socket;
# use respx to register expected calls, or mark the test integration.
```

---

*Testing analysis: 2026-06-05*
