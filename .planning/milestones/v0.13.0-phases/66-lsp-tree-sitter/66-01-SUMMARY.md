---
phase: 66-lsp-tree-sitter
plan: 01
subsystem: codegraph-config
tags: [lsp, tree-sitter, volar, gopls, settings, kill-switch]

requires: []
provides:
  - "默认禁用 LSP（VOLAR/GOPLS_BACKEND_ENABLED 默认 False）"
  - "EXTRACTOR_BACKENDS['go'] 回落 tree_sitter"
  - ".env.example / compose / helm 两开关文档"
affects: [codegraph 抽取后端, 索引/图谱构建]

tech-stack:
  added: []
  patterns:
    - "env.bool kill-switch 默认 False + apps.ready 守卫跳过 register_backend → BACKEND_REGISTRY 全回落 TreeSitterBackend"

key-files:
  created: []
  modified:
    - server/friday/settings.py
    - server/codegraph/tests/test_go_extractor.py
    - .env.example
    - docker-compose.yaml
    - deploy/helm/friday/templates/configmap.yaml
    - deploy/helm/friday/values.yaml

status: complete
---

# Phase 66 Plan 01 Summary — 默认禁用 LSP（仅 tree-sitter）

## 做了什么

- **`settings.py`**：`VOLAR_BACKEND_ENABLED` / `GOPLS_BACKEND_ENABLED` 两个 `env.bool` kill-switch 默认 `True → False`；`EXTRACTOR_BACKENDS["go"]` 由声明性 `"gopls"` 回落 `"tree_sitter"`（ts/tsx/vue/js/jsx 仍声明 `volar` 作为重开目标，该表纯声明性仅测试消费）。更新三处注释说明「默认仅 tree-sitter + env 可逆重开」。
- `codegraph/apps.py::ready()` 既有 `if getattr(settings, ...)` 守卫天然跳过 `register_backend` —— `BACKEND_REGISTRY` 全保 `TreeSitterBackend` 默认，图谱（`orchestrator.get_backend`）与索引（`unified_extraction.get_extractor`，抽取器本就 hardcode tree-sitter）两路径均自动回落，无需改抽取器代码。
- **`test_go_extractor.py`**：`test_endpoints_empty_for_go` → `test_endpoints_extracted_for_go_treesitter`。旧断言（endpoints==[]）建立在 gopls backend 上；禁用 gopls 后 go 走 tree-sitter，gin `r.GET/r.POST` 路由被抽取为 EndpointData（GET /users/:id + POST /users）—— 行为更优，非回归。
- **文档**：`.env.example` 新增「代码图谱 / 索引 LSP backend 开关」段；`docker-compose.yaml` server `environment` 加 `VOLAR/GOPLS_BACKEND_ENABLED`（默认 false）；helm `configmap.yaml` 注入两 env + `values.yaml` 新增 `codegraph.{volarBackendEnabled,goplsBackendEnabled}: false`。

## 验收

- `cd server && uv run pytest codegraph/ -q` → **608 passed, 10 skipped, 24 deselected**。
- 预置 acceptance 测试转绿：`test_gopls_registry::test_gopls_backend_not_registered_by_default`（`GOPLS_BACKEND_ENABLED is False`）、`test_registry_integration::test_settings_extractor_backends_5_languages_are_volar`（`EXTRACTOR_BACKENDS["go"]=="tree_sitter"`）。
- `test_gopls_real_extract`（@integration + gopls binary skipif）正常 skip，不受影响。

## 决策

- `EXTRACTOR_BACKENDS` 为声明性映射（仅测试消费），运行期实际后端由 kill-switch + apps.ready 决定；保留 ts/vue volar 声明作为「重开目标」。
- 可逆：`env VOLAR_BACKEND_ENABLED=true` / `GOPLS_BACKEND_ENABLED=true` 即恢复 LSP，无需改代码。
