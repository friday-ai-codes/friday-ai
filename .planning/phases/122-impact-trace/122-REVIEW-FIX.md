---
phase: 122-impact-trace
fixed_at: 2026-08-10T02:08:00+08:00
review_path: .planning/phases/122-impact-trace/122-REVIEW.md
iteration: 1
findings_in_scope: 8
fixed: 7
skipped: 1
status: partial
---

# Phase 122: Code Review Fix Report

**Fixed at:** 2026-08-10T02:08:00+08:00  
**Source review:** `.planning/phases/122-impact-trace/122-REVIEW.md`  
**Iteration:** 1  

**Summary:**
- Findings in scope: 8（BL/HI/ME 全部 + 明确安全的 LO-02；INFO 与风险型 LO-01 不在范围）
- Fixed: 7
- Skipped: 1（LO-01）

## Fixed Issues

### BL-01: ORM 解析绕过 exclusion，且 `symbol_not_found` / `symbol_not_in_graph` 区分泄漏被排除符号

**Files modified:** `server/services/code_graph_tools.py`, `server/tests/services/code_graph/test_impact_shell.py`, `server/mcp_tools/views.py`, `server/agents/tools/graph_tools.py`  
**Commit:** `9b755623`  
**Applied fix:** `resolve_symbol_candidates` 用 exclusion matcher 过滤被排除路径（uid / 名字路径均视为不存在）；`run_impact` 将图内落空统一为 `symbol_not_found`；删除可区分预言机出口。

### ME-03: 本仓编排同样在 ACL 闸之前做符号解析

**Files modified:** `server/services/code_graph_tools.py`  
**Commit:** `4ed4abc0`  
**Applied fix:** `run_impact` / `run_trace` 在 ORM 解析前调用 `ensure_repository_readable`（经 importlib 取 access，避免包外直连红线）。

### HI-01: 跨仓 hop 在 `ensure_repository_readable` 之前 ORM 解析对端符号

**Files modified:** `server/services/code_graph_cross_repo.py`  
**Commit:** `23bec676`  
**Applied fix:** 每个 peer 先 `ensure_repository_readable`；denied / not_indexed 不再触碰 peer Symbol ORM。

### HI-02: 对端全部 call site 未解析时仍 `fetch_graph_for_tool(seed_symbol_ids=[])`

**Files modified:** `server/services/code_graph_cross_repo.py`, `server/tests/services/code_graph/test_cross_repo_hop.py`  
**Commit:** `a3cdc54b`  
**Applied fix:** 空 `seed_ids` 跳过取图，返回成功条目并标 `reason=call_sites_unresolved`；补充回归测试并调整 unavailable 用例以匹配新序。

### ME-01: `_merge_impact_payloads` 丢失截断语义与「最浅优先」

**Files modified:** `server/services/code_graph_cross_repo.py`, `server/tests/services/code_graph/test_cross_repo_hop.py`  
**Commit:** `0cb89a97`  
**Applied fix:** 同 `symbol_id` 按 `(depth, -path_confidence)` 保留更优路径；按 `result_limit` 截断并重算 `truncated_by_depth`；`truncated_by_nodes` OR 各种子。

### ME-02: D-21 双面逐字节哨兵未覆盖 `trace_call_path`

**Files modified:** `server/tests/mcp_tools/test_impact_trace_tools.py`  
**Commit:** `0b291088`  
**Applied fix:** 新增 `test_two_surfaces_same_payload_trace`（`found=True` + `ambiguous_symbol`）逐字节比对 MCP / 对话壳。

### LO-02: 对话壳 `ValidationError` 路径 `error=str(exc)` 未脱敏

**Files modified:** `server/agents/tools/graph_tools.py`  
**Commit:** `8205a465`  
**Applied fix:** 四处 `ToolResult` 返回改为 `redact_secrets_in_text(str(exc))[:500]`。

## Skipped Issues

### LO-01: `groups` 键类型在双面消费者上不一致（int vs JSON string）

**File:** `server/services/code_graph/impact.py:548-551`  
**Reason:** API 契约面变更（内核 `dict[int]` vs JSON string keys），风险/范围外；双面哨兵已用 `json.dumps` 归一化绿测，需单独决策后再改。  
**Original issue:** 进程内消费 int 键与 MCP JSON string 键可能静默 miss。

## Test Results

命令前缀：
```
cd server && GALAXY_CACHE_WARM_ON_STARTUP=False GRAPH_BUILD_ORPHAN_RECONCILE_ON_STARTUP=False uv run pytest … --reuse-db
```

Scoped suites（全部通过，30 passed）：
- `tests/services/code_graph/test_impact_shell.py`
- `tests/services/code_graph/test_cross_repo_hop.py`
- `tests/services/code_graph/test_symbol_resolve.py`
- `tests/mcp_tools/test_impact_trace_tools.py`
- `tests/agents/tools/test_graph_tools.py`

## Landing notes

`git merge --ff-only` 曾被并发 WIP（脏 `server/mcp_tools/views.py`）阻断。已用 `update-ref` 推进 `main` 至 `8205a465`，并对其余修复文件做显式 path checkout；`views.py` 仅做 docstring 片段替换，保留并发 WIP（status `MM`）。

逻辑类修复（HI-02 / ME-01）建议人工再确认一次行为语义。

---

_Fixed: 2026-08-10T02:08:00+08:00_  
_Fixer: Claude (gsd-code-fixer)_  
_Iteration: 1_  
