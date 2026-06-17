---
phase: 55
slug: query-ui
status: inline
created: 2026-06-17
---

# Phase 55 — Validation Strategy

## Test Infra
- 后端：pytest（`cd server && uv run pytest tests/audit/ -q`）。
- 前端：vitest（`cd web && pnpm test`，happy-dom + @vue/test-utils）。

## SC → Test Map

| SC | Behavior | Test | Command |
|----|----------|------|---------|
| SC-1 查询+过滤+分页+fail-closed | 列表按 actor/action/target/source/时间过滤、offset/limit；非 superuser 403 | `tests/audit/test_query_api.py` | `uv run pytest tests/audit/test_query_api.py -q` |
| SC-2 只读 | 无 POST/PUT/PATCH/DELETE 路由（405/404）；模型 append-only 已守护 | `test_query_api.py::test_readonly_no_write` | 同上 |
| SC-3 前端列表+过滤+详情 | 渲染列表、过滤交互、详情 before/after | `web .../audit.spec.ts` | `pnpm test audit` |
| SC-4 导出 | CSV/JSON 导出 + 过滤透传 + max_rows 400 | `tests/audit/test_export_api.py` | `uv run pytest tests/audit/test_export_api.py -q` |

## Sampling
- 每 task commit 后跑对应测试文件；阶段末跑 `tests/audit/` 全量 + `makemigrations --check`（应 No changes，纯查询无模型变更）+ 前端 `vue-tsc`/eslint。
