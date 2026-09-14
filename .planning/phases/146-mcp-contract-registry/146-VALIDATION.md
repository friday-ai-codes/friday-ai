---
phase: 146
slug: mcp-contract-registry
status: draft
nyquist_compliant: false
wave_0_complete: false
created: 2026-09-14
---

# Phase 146 — Validation Strategy

> 契约注册表、生成目录、55-tool stdio、structuredContent、doctor 与发布门禁的 Nyquist 合同。当前为规划态；只有 Wave 0 测试文件存在且全部计划门禁通过后才改为 `validated` / `nyquist_compliant: true`。

## Test Infrastructure

| Property | Value |
|---|---|
| **Backend** | pytest 9.0.2 + pytest-django 4.11.1；`jsonschema` 4.26.0 Draft 2020-12 |
| **npm** | Vitest 4.1.8 + TypeScript 5.9.3 + tsdown 0.22.2；package scripts 均为一次性命令 |
| **Backend config** | `server/pyproject.toml` |
| **npm config** | `mcp/package.json`、`mcp/tsconfig.json`、`mcp/pnpm-lock.yaml` |
| **Quick backend** | `cd server && uv run pytest tests/mcp_tools/test_contract_registry.py tests/mcp_tools/test_contract_generation.py tests/mcp_tools/test_contract_compatibility.py -q` |
| **Quick npm** | `cd mcp && pnpm test -- --run tests/server.test.ts tests/cli.test.ts && pnpm typecheck` |
| **Generation gate** | `cd server && uv run python manage.py generate_mcp_contracts --check` |
| **Phase gate** | backend targeted suite + generator check + `cd mcp && pnpm install --frozen-lockfile && pnpm typecheck && pnpm test && pnpm build` |

禁止 watch：不使用 `pytest-watch`、`--looponfail`、`vitest --watch`、`tsdown --watch`。所有测试不得访问真实 Friday、npm registry 业务 API 或外部 Agent；HTTP/doctor 用 mock fetch，manifest API 用 Django test client。

## Dependency Waves

| Wave | Plan | Deliverable |
|---|---|---|
| 0 | validation fixtures | 创建 contract/output/compat/generation/manifest/doctor tests |
| 1 | 146-01 | registry、actual-200 response schemas、manifest model、compat baseline |
| 2 | 146-02 | generator、canonical bytes、snapshot、唯一 TS catalog、`--check` |
| 3 | 146-03 | URL cutover、snapshot re-export、npm 55 tools 与 handoff preservation |
| 4 | 146-04 | structuredContent、stable errors、schema additive-only guard |
| 5 | 146-05 | manifest API、package version、doctor |
| 6 | 146-06 | root CI、publish guards、version-pinned docs |

每一波只依赖前一波已提交接口；共享文件导致计划必须顺序执行，不允许同波并行覆盖 `views.py`、`server.ts` 或 generated artifacts。

## Sampling Rate

- **After every task:** 运行下表对应的单次 `<automated>` 命令。
- **After schema/generated changes:** 额外运行 generator `--check` 与 compatibility test。
- **After mcp child changes:** 运行 `pnpm test -- --run ...`、`pnpm typecheck`；不使用 watch。
- **After each plan:** 运行该 PLAN `<verification>` 中的 targeted suite。
- **Before Phase verification:** 运行完整 Phase Gate；确认 compatibility baseline 未被 generator 修改，且 unrelated dirty worktree 未被暂存。
- **Feedback target:** 单任务窄跑优先控制在 60 秒内；install/build/full targeted suite 仅用于 plan/phase gate。

## Per-Task Verification Map

| Task ID | Wave | Requirements | Secure / Observable Behavior | Automated Command | Test File |
|---|---:|---|---|---|---|
| 146-01-01 | 1 | PUB-01 | 55 URL tuple、DRF mapper、actual 200 fixtures、保守 required | `cd server && uv run pytest tests/mcp_tools/test_contract_registry.py tests/mcp_tools/test_output_contracts.py -q` | W0 |
| 146-01-02 | 1 | PUB-01 | registry/response serializer/canonical bytes/exact SHA-256 | `cd server && uv run pytest tests/mcp_tools/test_contract_registry.py tests/mcp_tools/test_output_contracts.py tests/mcp_tools/test_schema_snapshot.py -q` | W0 + existing |
| 146-01-03 | 1 | PUB-04 | breaking/additive classifier；baseline 无写回 | `cd server && uv run pytest tests/mcp_tools/test_contract_compatibility.py -q` | W0 |
| 146-02-01 | 2 | PUB-01 | deterministic JSON omits self hash/runtime versions | `cd server && uv run pytest tests/mcp_tools/test_contract_generation.py -q` | W0 |
| 146-02-02 | 2 | PUB-01 | snapshot 与唯一 `generated/toolCatalog.ts` 同源 | `cd server && uv run pytest tests/mcp_tools/test_contract_registry.py tests/mcp_tools/test_contract_generation.py -q` | W0 |
| 146-02-03 | 2 | PUB-03 | `--check` 只读；missing/dirty/submodule absent hard fail；安全日志 | `cd server && uv run pytest tests/mcp_tools/test_contract_generation.py -q && uv run python manage.py generate_mcp_contracts --check` | W0 |
| 146-03-01 | 3 | PUB-01 | URL/view/request serializer/snapshot 同源且旧 URL 不变 | `cd server && uv run pytest tests/mcp_tools/test_contract_registry.py tests/mcp_tools/test_schema_snapshot.py -q` | W0 + existing |
| 146-03-02 | 3 | PUB-01, PUB-02 | 55 tools 与 12 缺口 list/call；handoff 安全行为保留 | `cd server && uv run pytest tests/mcp_tools/test_contract_registry.py tests/mcp_tools/test_mcp_package_alignment.py -q && cd ../mcp && pnpm test -- --run tests/server.test.ts && pnpm typecheck` | W0 + existing |
| 146-04-01 | 4 | PUB-01, PUB-06 | schema exact/additive-only；必要修正全量 regenerate；baseline 只读 | `cd server && uv run pytest tests/mcp_tools/test_contract_registry.py tests/mcp_tools/test_output_contracts.py tests/mcp_tools/test_contract_compatibility.py -q && uv run python manage.py generate_mcp_contracts --check` | W0 |
| 146-04-02 | 4 | PUB-06 | HTTP/stdio stable codes；PAT/raw body/exception 不回显 | `cd server && uv run pytest tests/mcp_tools/test_mcp_auth_errors.py -q && cd ../mcp && pnpm test -- --run tests/server.test.ts` | existing |
| 146-04-03 | 4 | PUB-01, PUB-06 | structuredContent schema-valid；TextContent 同源；handoff 仅摘要 | `cd mcp && pnpm test -- --run tests/server.test.ts && pnpm typecheck && pnpm build` | existing |
| 146-05-01 | 5 | PUB-01, PUB-05 | authenticated manifest、package metadata、exact-bytes hash、caller logs | `cd server && uv run pytest tests/mcp_tools/test_manifest_api.py -q` | W0 |
| 146-05-02 | 5 | PUB-01, PUB-05 | SERVER_VERSION===package.json.version | `cd mcp && pnpm test -- --run tests/server.test.ts && pnpm typecheck` | existing |
| 146-05-03 | 5 | PUB-01, PUB-05 | doctor exact/additive/breaking/401/404/network + redaction | `cd mcp && pnpm test -- --run tests/cli.test.ts && pnpm typecheck && pnpm build` | W0 |
| 146-06-01 | 6 | PUB-01, PUB-03 | recursive submodule、五面对齐、无 skip、全 blocking gates | `cd server && uv run python manage.py generate_mcp_contracts --check && uv run pytest tests/mcp_tools/test_contract_registry.py tests/mcp_tools/test_contract_generation.py tests/mcp_tools/test_contract_compatibility.py tests/mcp_tools/test_manifest_api.py tests/mcp_tools/test_mcp_package_alignment.py tests/mcp_tools/test_output_contracts.py tests/mcp_tools/test_mcp_auth_errors.py -q` | W0 + existing |
| 146-06-02 | 6 | PUB-05 | parent gitlink==child SHA、publish guards、version-pinned docs | `cd mcp && pnpm install --frozen-lockfile && pnpm typecheck && pnpm test && pnpm build` | existing |

`W0` 表示计划执行前不存在、由对应 TDD 任务先创建 RED fixture；`existing` 表示文件已存在但需要扩展。每个 task 都有自动化命令，无连续验证空洞。

## Wave 0 Requirements

- [ ] `server/tests/mcp_tools/test_contract_registry.py` — 55-tool URL/view/request/response/annotation characterization、DRF mapper 与 import-cycle guards。
- [ ] `server/tests/mcp_tools/test_output_contracts.py` — 每工具实际 HTTP 200 分支 fixtures、Draft 2020-12 校验、保守 required 交集。
- [ ] `server/tests/mcp_tools/test_contract_compatibility.py` — 删除工具/字段、新增 required、收窄 enum，以及类型/nullable/边界/annotation 风险与 additive 正例。
- [ ] `server/tests/mcp_tools/test_contract_generation.py` — canonical bytes、exact SHA-256、确定性、唯一 TS 路径、`--check` 只读、missing/dirty/submodule absent。
- [ ] `server/tests/mcp_tools/test_manifest_api.py` — auth、package/build version、exact bytes/hash、caller logs、redaction、best-effort observability。
- [ ] `mcp/tests/cli.test.ts` — doctor exact/additive/incompatible/401/404/network/invalid JSON/version/redaction。
- [ ] 扩展 `server/tests/mcp_tools/test_mcp_package_alignment.py` — 缺 mcp hard fail、五面全字段一致；删除 skip。
- [ ] 扩展 `mcp/tests/server.test.ts` — 55 list/call、outputSchema、structuredContent、machine errors、handoff 权限/摘要。
- [ ] Framework install: 无；全部复用现有 pytest/jsonschema/Vitest/TypeScript/Node built-ins。

## Phase Gate

```bash
cd server
uv run python manage.py generate_mcp_contracts --check
uv run pytest \
  tests/mcp_tools/test_contract_registry.py \
  tests/mcp_tools/test_contract_generation.py \
  tests/mcp_tools/test_contract_compatibility.py \
  tests/mcp_tools/test_manifest_api.py \
  tests/mcp_tools/test_mcp_package_alignment.py \
  tests/mcp_tools/test_output_contracts.py \
  tests/mcp_tools/test_mcp_auth_errors.py -q
cd ../mcp
pnpm install --frozen-lockfile
pnpm typecheck
pnpm test
pnpm build
```

## Manual-Only Verifications

无。真实已发布 npm 与生产 server canary 属 Phase 152；本阶段 publish workflow、doctor 和 stdio 均用自动化 synthetic fixtures 验证，不冒充 live evidence。

## Validation Sign-Off

- [ ] All 16 tasks have an automated command.
- [ ] Wave 0 creates every referenced missing test file.
- [ ] No watch-mode command appears.
- [ ] Plan 01 freezes actual-200 response schemas before generated/structured consumers.
- [ ] Any later schema correction is additive-only, regenerates all artifacts, and leaves compatibility baseline unchanged.
- [ ] Manifest hash is exact on-disk canonical JSON bytes everywhere.
- [ ] `mcp/src/generated/toolCatalog.ts` is the sole generated TS catalog; `mcp/src/tools.ts` is barrel-only.
- [ ] Missing/uninitialized mcp submodule fails rather than skips.
- [ ] `nyquist_compliant: true` only after all rows are green.

**Approval:** pending
