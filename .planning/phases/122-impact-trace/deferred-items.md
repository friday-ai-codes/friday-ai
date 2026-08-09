# Phase 122 — Deferred Items（out-of-scope 发现，本相位不修）

## 122-01

### 既有 ruff error（两处，本 plan 从未触碰的文件）

`uv run ruff check tests/mcp_tools` 在 HEAD 上已报两条 error，与 122-01 的改动无关：

| 文件 | 规则 | 内容 |
|---|---|---|
| `server/tests/mcp_tools/test_delivery_knowledge_tools.py:9` | F401 | `asgiref.sync.sync_to_async` imported but unused |
| `server/tests/mcp_tools/test_find_related_chunks.py:1` | I001 | Import block is un-sorted or un-formatted |

两个文件的最后一次改动是 `062f686f`（Phase 76，「测试引用对齐 Space 重命名」），
`git status` 显示未被本会话或任何并发会话修改，即两条 error 在 122-01 之前就存在。
两条都是 `--fix` 可自动修的，但按 scope boundary（只修当前 task 改动**直接**引发的问题）
未动。122-01 新增/修改的 9 个文件 `ruff check` 与 `ruff format --check` 全部通过。

### 既有 ruff format 漂移（`tests/services/code_graph/` 下 6 个文件）

`uv run ruff format --check tests/services/code_graph` 报 6 个既有文件 would reformat
（`test_access.py` / `test_cache.py` / `test_loader.py` / `test_model.py` /
`test_perf_diagnostics.py` / `test_signature.py`），均为 Phase 121 交付物，本 plan 未触碰。
122-01 交付的 4 个文件（`conftest.py` / `test_impact.py` / `test_trace.py` /
`test_symbol_resolve.py`）与 Task 3 的 5 个文件均为 already formatted。
