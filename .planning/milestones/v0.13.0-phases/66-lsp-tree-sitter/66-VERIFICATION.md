---
phase: 66
slug: lsp-tree-sitter
status: passed
nyquist_compliant: true
wave_0_complete: true
created: 2026-06-23
---

# Phase 66 — Verification（默认禁用 LSP，仅 tree-sitter）

## Goal-Backward Verification

**Phase Goal:** 把代码索引/图谱构建默认切到仅 tree-sitter（关闭 Volar/gopls LSP backend），缓解图谱构建慢与 LSP 冷启动等待，后续调好再经环境开关重开。

## Checks

| # | Success Criterion | Status | Evidence |
|---|-------------------|--------|----------|
| 1 | `VOLAR/GOPLS_BACKEND_ENABLED` 默认 False，`apps.ready` 不注册 Volar/gopls，启动无 LSP 冷启动等待 | ✅ | settings.py 两 kill-switch 默认 `env.bool(..., default=False)`；apps.ready `if getattr(...)` 守卫跳过 register_backend。`test_gopls_registry::test_gopls_backend_not_registered_by_default` 转绿 |
| 2 | 向量抽取路径在 LSP 关闭时回落 TreeSitterBackend，索引与图谱构建成功不报错 | ✅ | `BACKEND_REGISTRY` 全默认 TreeSitterBackend（不 register 即保持）；`get_extractor` 抽取器本就 hardcode tree-sitter；`codegraph/` 608 测全绿（含 registry/extractor 路径） |
| 3 | `.env.example` / compose / helm configmap 注释两开关用途与"调好后重开" | ✅ | `.env.example` 新增 codegraph LSP 段；`docker-compose.yaml` server env 加两开关；helm `configmap.yaml`+`values.yaml` 加 codegraph 段（均注释用途 + 重开方式） |
| 4 | 显式 env 开启后 LSP 行为恢复（开关可逆，无需改代码） | ✅ | `env.bool("VOLAR_BACKEND_ENABLED"/"GOPLS_BACKEND_ENABLED")` 读 env；置 true 即 apps.ready 重新 register_backend，无代码改动。`test_gopls_registry` monkeypatch True 用例验证注册路径 |

## Result

**PASSED** — 4/4 success criteria 满足。预置 acceptance 测试转绿，`codegraph/` 608 passed/10 skipped 零回归（`test_go_extractor` endpoint 断言更新为 tree-sitter 抽取 gin 路由，行为更优非回归）。
