---
phase: 122-impact-trace
verified: 2026-08-09T18:11:09Z
status: passed
score: 7/7 must-haves verified
overrides_applied: 0
re_verification: false
deferred:
  - truth: "IMPACT-03 跨仓路径在真实生产 CrossRepoApiCall 样本上复验"
    addressed_in: "Phase 127"
    evidence: "ROADMAP Phase 127「跨相位回访（D-26 / IMPACT-03）」：合成四分支已覆盖；LSP 补齐后必须用真实样本复验"
  - truth: "mcp npm 包 FRIDAY_TOOLS 与 server TOOL_SCHEMA_SNAPSHOT 对齐（漂移 7 项）"
    addressed_in: "另批发版 / ROADMAP D-27 记账"
    evidence: "D-27 明确本相位不碰 mcp submodule；ROADMAP 已记 5→7 漂移白名单"
  - truth: "impact 输出 affected_processes 叙事层回填"
    addressed_in: "Phase 126"
    evidence: "Phase 126 SC-3：detect_changes / impact 输出回填 affected_processes；本相位仅预留空数组字段位"
---

# Phase 122: impact / trace 工具面 Verification Report

**Phase Goal:** 用户/agent 改代码前能回答「影响谁、怎么到达」——impact 深度分组 + 置信度分层 + 跨仓边界，trace 两符号间最短路，经 MCP 与对话双面可用

**Verified:** 2026-08-09T18:11:09Z  
**Status:** passed  
**Re-verification:** No — initial verification  
**Requirements:** IMPACT-01..06 (REQUIREMENTS.md marked Complete)

## Goal Achievement

### Observable Truths

| # | Truth | Status | Evidence |
| --- | --- | --- | --- |
| 1 | 对任一符号执行 impact，返回 d1/d2/d3 深度分组（WILL_BREAK / LIKELY_AFFECTED / MAY_NEED_TESTING），每条边带 confidence + reason，可用 `min_confidence` 过滤 | ✓ VERIFIED | `impact.py` `DEPTH_LABELS` + `analyze_impact` path-min；`test_impact.py` 10 passed |
| 2 | 改后端 Endpoint 时能沿 `CrossRepoApiCall` 列出对端前端调用点，标 `cross_repo: true` + `match_confidence` 原值 | ✓ VERIFIED | `code_graph_cross_repo.py` ORM 直查（D-25）；四分支合成测 `test_cross_repo_hop.py` 6 passed；真实样本按 D-26 记入 Phase 127 |
| 3 | impact 带确定性风险四级（LOW/MEDIUM/HIGH/CRITICAL，含 D-29 bare_name 封顶）与截断 summary 计数 | ✓ VERIFIED | `grade_risk` + `RISK_THRESHOLDS`；summary `total_found`/`returned`/`truncated_by_depth`；ME-01 merge 重算截断已落地 |
| 4 | trace 返回有向最短路，逐跳 file:line + 边类型/置信度；重名返回候选列表，绝不静默取第一个 | ✓ VERIFIED | `trace.py` `subgraph_view`+`shortest_path`+等长声明；`symbol_resolve.py` D-19；`test_trace.py` + `test_symbol_resolve.py` |
| 5 | impact/trace 经 MCP + agents 对话双面可调，输出带 staleness（落后 N commits / as_of 降级） | ✓ VERIFIED | `ImpactAnalysisView`/`TraceCallPathView` + `graph_tools.py`；`chat_runner._INDEXED_TOOL_NAMES`；`staleness_payload`；双面哨兵含 impact+trace |
| 6 | exclusion/ACL：排除路径与「不存在」同出口；仓级 ACL 在 ORM 解析前；跨仓 peer 先 ensure 再解析 | ✓ VERIFIED | BL-01/ME-03/HI-01 修复在 `code_graph_tools.py` / `code_graph_cross_repo.py`；`test_impact_shell` exclusion 用例断言无 `symbol_not_in_graph` |
| 7 | D-21 双面 `data` 段逐字节同源覆盖 impact **与** trace（含 ambiguous） | ✓ VERIFIED | `test_two_surfaces_same_payload` + `test_two_surfaces_same_payload_trace`（ME-02） |

**Score:** 7/7 truths verified

### Deferred Items

| # | Item | Addressed In | Evidence |
|---|------|-------------|----------|
| 1 | IMPACT-03 真实样本复验 | Phase 127 | ROADMAP D-26 跨相位回访 |
| 2 | mcp npm 工具条目 5→7 | 另批发版 | D-27 / ROADMAP 白名单 |
| 3 | `affected_processes` 回填 | Phase 126 | CONTEXT out-of-scope；字段位已预留 `[]` |

### Required Artifacts

| Artifact | Expected | Status | Details |
| -------- | -------- | ------ | ------- |
| `server/services/code_graph/symbol_resolve.py` | D-19 图内解析 | ✓ VERIFIED | 280 lines；exports `resolve_symbol_in_graph` / `SymbolResolution` |
| `server/services/code_graph/impact.py` | 反向 BFS + 风险 + 截断 | ✓ VERIFIED | 627 lines；`analyze_impact` / `grade_risk` |
| `server/services/code_graph/trace.py` | 最短路内核 | ✓ VERIFIED | 384 lines；`subgraph_view` 无 copy |
| `server/services/code_graph_tools.py` | 原语 + `run_impact`/`run_trace` | ✓ VERIFIED | 1190 lines；exclusion 过滤 + ACL-first |
| `server/services/code_graph_cross_repo.py` | 跨仓一跳 | ✓ VERIFIED | 512 lines；HI-01/HI-02/ME-01 修复在位 |
| `server/mcp_tools/views.py` | MCP 薄壳 | ✓ VERIFIED | `ImpactAnalysisView` / `TraceCallPathView` → `run_*` |
| `server/mcp_tools/serializers.py` + `urls.py` | schema + 路由 | ✓ VERIFIED | serializers + `/tools/impact_analysis/` `/tools/trace_call_path/` |
| `server/agents/tools/graph_tools.py` + schemas | 对话壳 | ✓ VERIFIED | 637 lines；owner fail-closed；注册进 `__init__` + chat 白名单 |
| 测试骨架（code_graph + mcp + agents） | 验收覆盖 | ✓ VERIFIED | 见 Behavioral Spot-Checks：45 passed |

### Key Link Verification

| From | To | Via | Status | Details |
| ---- | -- | --- | ------ | ------- |
| MCP views | `run_impact` / `run_trace` | 薄壳调用 | ✓ WIRED | `views.py` 显式 import + await |
| agents `graph_tools` | `run_impact` / `run_trace` | 同编排入口 | ✓ WIRED | D-21；`data` 原样透出 |
| `run_impact` | `analyze_impact` | 唯一内核调用 | ✓ WIRED | `code_graph_tools.py` |
| `run_impact` | `collect_cross_repo_impact` | 跨仓一跳 | ✓ WIRED | lazy import 防循环 |
| `collect_cross_repo_impact` | `CrossRepoApiCall` ORM | `call_site__repository_id` exclude 本仓 | ✓ WIRED | D-25 不改 loader |
| `fetch_graph_for_tool` | `get_graph_service().get_graph` | 必传 `seed_symbol_ids`+`depth` | ✓ WIRED | 无默认值（D-24） |
| `urls.py` | TOOL_SCHEMA_SNAPSHOT | 双向 snapshot | ✓ WIRED | `test_schema_snapshot` 含两工具条目 |
| barrel | impact/trace 不进 `_INTERNAL` | D-28 docstring | ✓ WIRED | 壳直连合法；无 `loader`/`cache` 直 import |

### Data-Flow Trace (Level 4)

| Artifact | Data Variable | Source | Produces Real Data | Status |
| -------- | ------------- | ------ | ------------------ | ------ |
| `run_impact` 成功信封 | `groups` / `summary` / `risk_level` | `analyze_impact(MultiDiGraph)` | 图遍历真实节点/边属性 | ✓ FLOWING |
| `run_impact` `cross_repo` | peer impact / redacted / unavailable | `CrossRepoApiCall` → peer `get_graph` → `analyze_impact` | ORM + 图；空种子跳过取图 | ✓ FLOWING |
| `run_impact`/`run_trace` `staleness` | `behind_commits` / `as_of` | `Repository` 预计算字段 | 库字段，不编造 | ✓ FLOWING |
| `run_*` `graph` | `resolution_rate` + 四标记 | `GraphMeta` via `degradation_payload` | 数值必带（D-23） | ✓ FLOWING |
| MCP/对话壳 `data` | orchestrator dict | `run_*` 原样 / `{**result, run_id}` | 非静态空壳 | ✓ FLOWING |
| `affected_processes` | `[]` | 预留位 | 故意空（Phase 126） | ⚠ deferred（非本相位缺口） |

### Behavioral Spot-Checks

| Behavior | Command | Result | Status |
| -------- | ------- | ------ | ------ |
| Phase 122 作用域回归 | 见下方 pytest 命令 | 45 passed in ~94s | ✓ PASS |

```bash
cd /Users/zaneliu/Projects/open-source/friday-ai/server && \
GALAXY_CACHE_WARM_ON_STARTUP=False GRAPH_BUILD_ORPHAN_RECONCILE_ON_STARTUP=False \
uv run pytest \
  tests/services/code_graph/test_symbol_resolve.py \
  tests/services/code_graph/test_impact.py \
  tests/services/code_graph/test_trace.py \
  tests/services/code_graph/test_cross_repo_hop.py \
  tests/services/code_graph/test_impact_shell.py \
  tests/services/code_graph/test_staleness.py \
  tests/mcp_tools/test_impact_trace_tools.py \
  tests/agents/tools/test_graph_tools.py \
  --reuse-db -q
# → 45 passed
```

### Probe Execution

| Probe | Command | Result | Status |
| ----- | ------- | ------ | ------ |
| — | — | 本相位无 `scripts/*/tests/probe-*.sh` 声明 | SKIP |

### Requirements Coverage

| Requirement | Source Plan | Description | Status | Evidence |
| ----------- | ---------- | ----------- | ------ | -------- |
| IMPACT-01 | 122-03 | 深度分组 d1/d2/d3 | ✓ SATISFIED | `DEPTH_LABELS` + `test_impact.py` |
| IMPACT-02 | 122-03 | confidence + reason + min_confidence | ✓ SATISFIED | path-min + `derive_reason` + 双闸 bare_name |
| IMPACT-03 | 122-06 | 跨仓 CrossRepoApiCall | ✓ SATISFIED* | 合成四分支；*真实样本 deferred → 127 (D-26) |
| IMPACT-04 | 122-03 | 风险四级 + 截断 summary | ✓ SATISFIED | `grade_risk` + D-29 封顶 + summary 计数 |
| IMPACT-05 | 122-04/02 | trace 最短路 + 消歧 | ✓ SATISFIED | `trace_path` + D-19 共享解析器 |
| IMPACT-06 | 122-08/09/10 | 双面暴露 + staleness | ✓ SATISFIED | MCP+agents+双面哨兵；npm 客户端 D-27 除外 |

无 ORPHANED requirements：REQUIREMENTS.md 映射到 Phase 122 的仅 IMPACT-01..06，均被 plan 声明。

### Key Decisions (spot-check)

| Decision | Status | Evidence |
| -------- | ------ | -------- |
| D-19 绝不静默取第一个 | ✓ | 图内 + ORM；跨仓 unresolved 计数不取首条 |
| D-21 双面同源编排 | ✓ | `run_*` 唯一入口；impact+trace 哨兵 |
| D-23 数值 resolution_rate | ✓ | `degradation_payload` 无条件带数值 |
| D-24 种子+深度必传 | ✓ | `fetch_graph_for_tool` 无默认；超预算壳测绿 |
| D-25 跨仓走 ORM 不改 loader | ✓ | `code_graph_cross_repo`；无 loader 改边 |
| D-26 合成验收 + ROADMAP 记账 | ✓ | 声明 + Phase 127 回访段 |
| D-27 不碰 mcp submodule | ✓ | 相位 diff 无 mcp/；ROADMAP 5→7 |

### Review Fix Closure (BL/HI/ME)

| ID | Claimed fix | Code evidence | Test evidence | Status |
| -- | ----------- | ------------- | ------------- | ------ |
| BL-01 | exclusion 合并「不存在」；删 `symbol_not_in_graph` 预言机 | `resolve_symbol_candidates` matcher；图内落空 → `symbol_not_found` | `test_impact_shell` exclusion 用例 | ✓ CLOSED |
| ME-03 | ACL 在 ORM 前 | `run_impact`/`run_trace` 先 `ensure_repository_readable` | shell 套件绿 | ✓ CLOSED |
| HI-01 | peer 先 ensure 再 Symbol ORM | `collect_cross_repo_impact` 循环序 | `test_cross_repo_hop` denied/not_indexed | ✓ CLOSED |
| HI-02 | 空 seed 不 `fetch([])` | `reason=call_sites_unresolved` + continue | 专用用例 assert | ✓ CLOSED |
| ME-01 | merge 最浅优先 + 截断重算 | `_merge_impact_payloads` | cross_repo 套件 | ✓ CLOSED |
| ME-02 | trace 双面哨兵 | `test_two_surfaces_same_payload_trace` | 套件绿 | ✓ CLOSED |
| LO-01 | groups int vs JSON string keys | 未改（刻意 skip） | 哨兵 `json.dumps` 归一化绿 | ℹ INFO（非 blocker） |

### Anti-Patterns Found

| File | Line | Pattern | Severity | Impact |
| ---- | ---- | ------- | -------- | ------ |
| — | — | TBD/FIXME/XXX in phase core modules | none | 扫描 `impact.py`/`trace.py`/`symbol_resolve.py`/`code_graph_tools.py`/`code_graph_cross_repo.py`/`graph_tools.py` 无债务标记 |
| `impact.py` / `code_graph_tools.py` | — | `affected_processes: []` | ℹ Info | 设计预留，Phase 126 回填 |
| REVIEW LO-01 | — | int vs JSON string `groups` keys | ℹ Info | 进程内 int / MCP JSON string；双面哨兵已归一化；需单独契约决策 |

### Human Verification Required

无强制人工项（用户状态枚举为 `passed|gaps_found|blocked`）。可选抽检（不阻塞）：

1. **跨仓合成语义（HI-02 / ME-01）** — 人工读一条 `call_sites_unresolved` 与 merge 后 summary，确认 agent 不会误读为「对端无影响」。
2. **真实仓 MCP 冒烟** — 对已索引仓调 `impact_analysis` / `trace_call_path`，确认 PAT + staleness 文案可读。

### Gaps Summary

无阻断缺口。相位目标在代码与作用域测试下已达成；D-26/D-27/Phase 126 项已记入 deferred，不构成本相位 `gaps_found`。

---

_Verified: 2026-08-09T18:11:09Z_  
_Verifier: Claude (gsd-verifier)_
