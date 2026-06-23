# Phase 66: 默认禁用 LSP（仅 tree-sitter） - Context

**Gathered:** 2026-06-23
**Status:** Ready for planning
**Mode:** Smart discuss → Infrastructure phase（配置开关 + 测试 + 文档，无用户可见行为新增）

<domain>
## Phase Boundary

把代码索引/图谱构建默认切到仅 tree-sitter（关闭 Volar/gopls LSP backend），缓解图谱构建慢与 LSP 冷启动等待；后续调好再经环境开关重开。纯环境开关（可逆），不删除 LSP 代码。

**不在范围内**：永久删除 LSP 代码；图谱逐文件串行抽取的异步解耦（GRAPHX-01 留后续）。
</domain>

<decisions>
## Implementation Decisions

### Claude's Discretion（infrastructure phase）
- `VOLAR_BACKEND_ENABLED` / `GOPLS_BACKEND_ENABLED` 两个 `env.bool` kill-switch 默认从 True 改 **False**（`server/friday/settings.py`）；`codegraph/apps.py::ready()` 既有 `if getattr(settings, ...)` 守卫天然跳过 `register_backend`，`BACKEND_REGISTRY` 全保 `TreeSitterBackend` 默认。
- `EXTRACTOR_BACKENDS["go"]` 由声明性 `"gopls"` 回落 `"tree_sitter"`（go gopls 冷启动慢）；`ts/tsx/vue/js/jsx` 仍声明 `"volar"` 作为「重开目标」（该表纯声明性，运行期实际后端由 kill-switch 决定，仅测试断言消费）。
- 运行期实际抽取后端：`unified_extraction.get_extractor` 路径既有 GoExtractor/TSExtractor 等本就 hardcode TreeSitterBackend；`orchestrator.get_backend` 路径经 `BACKEND_REGISTRY`，kill-switch 关闭即全回落 TreeSitterBackend —— 两路径均自动 fallback，无需改抽取器代码。
- 文档：`.env.example`、`docker-compose.yaml`（server environment）、helm `configmap.yaml` + `values.yaml` 注释两开关用途与「调好后重开」。
- 可逆：`env VOLAR_BACKEND_ENABLED=true` / `GOPLS_BACKEND_ENABLED=true` 即恢复 LSP，无需改代码。

</decisions>

<code_context>
## Existing Code Insights

### Reusable Assets
- `server/friday/settings.py`：`EXTRACTOR_BACKENDS`（声明性映射，仅测试消费）、`VOLAR_BACKEND_ENABLED`/`GOPLS_BACKEND_ENABLED`（kill-switch）。
- `server/codegraph/apps.py::CodegraphConfig.ready()`：`if getattr(settings, "VOLAR_BACKEND_ENABLED", ...)` / `GOPLS_BACKEND_ENABLED` 守卫 register；关闭即跳过。
- `server/codegraph/extractors/registry.py`：`BACKEND_REGISTRY` 全默认 `TreeSitterBackend`，apps.ready 仅在 enabled 时 `register_backend` 替换。
- 既有测试 `test_gopls_registry.py` / `test_registry_integration.py` 已**预置**断言目标态（`GOPLS_BACKEND_ENABLED is False`、`EXTRACTOR_BACKENDS["go"]=="tree_sitter"`）—— 本 phase 改动使其转绿。

### Established Patterns
- env.bool kill-switch + apps.ready 守卫注册（运维 toggle 范式）。

### Integration Points
- `codegraph/services/orchestrator.py::get_backend` 图谱抽取路径；`services/unified_extraction.py::get_extractor` 索引抽取路径。

</code_context>

<specifics>
## Specific Ideas
- go endpoint 抽取：tree-sitter go backend 会抽取 gin 路由 endpoint（gopls 路径返空）——禁用 gopls 后 `test_go_extractor` 的 endpoint 断言由「空」改为「抽到 gin 路由」（行为更优，非回归）。
</specifics>

<deferred>
## Deferred Ideas
- 图谱逐文件串行抽取的常驻热池 + 异步解耦（GRAPHX-01）。
- 永久移除 LSP 代码（仅默认关闭可恢复，明确非目标）。
</deferred>
