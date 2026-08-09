---
phase: 122-impact-trace
plan: 05
subsystem: code-graph
tags: [orm-boundary, graph-fetch, staleness, degradation, symbol-disambiguation, observability-guard]

# Dependency graph
requires:
  - phase: 121-graph-base
    provides: "get_graph_service barrel、GraphError 四子类、GraphMeta 15 字段、ensure_repository_readable 每次都跑、超预算无种子抛 GraphError"
  - plan: 122-02
    provides: "SymbolCandidate / SymbolResolution / CANDIDATE_LIMIT、resolved 非空 ⇒ candidates 为空的不变式"
provides:
  - "fetch_graph_for_tool：种子与深度必传的取图原语（D-24），不 catch GraphError"
  - "GRAPH_ERROR_MESSAGES / graph_error_to_tool_error：五个异常类 → (error_code, 中文文案)，details 不出墙"
  - "staleness_payload：三态 + behind_commits 有值报数字 / None 降级 as_of（D-22，请求路径零 git）"
  - "degradation_payload：数值 resolution_rate + 四个降级标记 + 人话 declarations（D-23）"
  - "resolve_symbol_candidates / resolution_to_payload：取图前 ORM 解析 + signature 截断 200 字符（D-19）"
  - "_SIBLING_GUARDED_MODULES：AST 观测契约扫描面扩到包外兄弟模块（补 D-04 缺口）"
affects: [122-06, 122-07, 122-08, 122-09, 122-10]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "包外兄弟模块 + 显式清单守护：ORM 边界把文件留在包外，观测契约用 _SIBLING_GUARDED_MODULES 显式收回扫描面"
    - "必填关键字参数无默认值：seed_symbol_ids / depth 在签名层就拦下『忘了传』，而不是等生产报错"

key-files:
  created:
    - server/services/code_graph_tools.py
  modified:
    - server/tests/services/code_graph/test_access.py
    - server/tests/services/code_graph/test_staleness.py
    - server/tests/services/code_graph/test_impact_shell.py
    - server/tests/services/code_graph/test_symbol_resolve.py

key-decisions:
  - "模块必须放 services/code_graph_tools.py：唯一理由是 ORM 边界（D-01），不是『要发 caller 事件』——本模块每个事件都是 sampling"
  - "graph_error_to_tool_error 在映射表文案与 exc.message 不同时拼成『表文案（message）』，⛔ 不用 str(exc)"
  - "behind_commits==0 单独措辞『索引与远端一致』，与『落后 N』和『未知』三档区分"
  - "观测契约只放宽 category 到 {sampling,caller} 对兄弟文件；包内仍只许 sampling；其余四条判据逐字不变"
  - "⛔ 不预登记 code_graph_cross_repo.py：122-06 才存在，提前加会让存在性断言在两个 wave 之间一直红"

requirements-completed: []  # IMPACT-05 需壳层 122-07/08/09 齐活；本 plan 只交付编排原语，⛔ 不得勾选

# Metrics
duration: 21min
completed: 2026-08-09
---

# Phase 122 Plan 05: 壳层共用编排原语（取图 / 异常翻译 / staleness / 降级 / 候选 signature）Summary

**一个 594 行、因 ORM 边界必须待在包外的兄弟模块：把「种子必传取图 → GraphError 逐类翻译 → staleness / 降级声明 → 重名候选带 signature」收成两个壳共用的原语，并用显式清单把 AST 观测契约的扫描面缺口补上——变异测试实测证明守护不是摆设**

## Performance

- **Duration:** ~21 min
- **Started:** 2026-08-09T16:20:00Z
- **Completed:** 2026-08-09T16:41:00Z
- **Tasks:** 4
- **Files modified:** 5（1 新建 594 行 + 4 填实）

## Accomplishments

- **`fetch_graph_for_tool` 把 D-24 写成签名**。`seed_symbol_ids` 与 `depth` 都是必填关键字参数、无默认值——忘传在写代码时报错，而不是等超预算大仓在生产上抛 `GraphError`。用例两条断言并列：同一条件下带种子返回 `degraded` 以 `on_demand_subgraph` 开头的子图、不带种子 `pytest.raises(GraphError)`，并 spy 证明 `depth=3` / `seed_symbol_ids=[sid]` 真的传到了 `get_graph`。⛔ 本函数不 catch 任何 `GraphError`。
- **`graph_error_to_tool_error` 按 `__mro__` 取最具体项**，五个异常类各自对应不同 `error_code`。文案只取映射表常量与 `exc.message`——用例用带 `{"estimated_bytes": 999}` 的 `GraphError` 钉死 `"999"` / `"estimated_bytes"` 都不出现在返回文案里（`str(exc)` 会把它们拼上去）。
- **`staleness_payload` 三档声明写全**：`behind_commits=7` ⇒ 含 `"7"`；`behind_commits is None` ⇒ 含 as_of 前 12 位且「落后」必配「未知」；`remote_head_checked_at=None` ⇒ `freshness == "unknown"`。⛔ 请求路径零 git 子进程，三态一律走 `compute_freshness_status`。
- **`degradation_payload` 始终带数值 `resolution_rate`**。即便 `low_resolution=False`（生产常态就是 0.17），`declarations` 里仍有「约 83% 未解析」那条——布尔量在这个常态下没有信息量。`on_demand_subgraph` 与 `on_demand_subgraph_truncated` 的措辞刻意不同。
- **`resolve_symbol_candidates` 是取图前的 ORM 半边**。uid 优先（非法 UUID 视作落空，不退化按名搜）；名字路径 `acount()` + 前 20 条封顶，`signature` 同一次 `values_list` 取出并截到 200 字符；⛔ 任何路径都不取第一条，AST 断言守着不重蹈 `_resolve_source_chunk` 的覆辙。补 `file_path` 可一次收敛。
- **观测契约扫描面扩到包外兄弟模块**。`_SIBLING_GUARDED_MODULES = ("code_graph_tools.py",)` 显式清单 + 存在性断言；只放宽 `category` 到 `{sampling, caller}` 对兄弟文件，包内仍只许 `sampling`。变异测试：临时追加 `logger.info("bad_event_name", …)` ⇒ 用例失败且违规信息含 `code_graph_tools.py`；删除后全绿。

## Task Commits

1. **Task 1: 取图原语（D-24 种子透传）与 GraphError 翻译表（D-03）** - `933f2133` (feat)
2. **Task 2: staleness 声明（D-22）与降级标记透出（D-23）** - `52c07113` (feat)
3. **Task 3: 重名候选的 ORM 解析与 signature 补取（D-19）** - `4bf50348` (feat)
4. **Task 4: AST 观测契约扩展到包外兄弟模块（补 D-04 缺口）** - `f73ff656` (test)

## Files Created/Modified

- `server/services/code_graph_tools.py`（新建，594 行）— 三段式中文 docstring（第一段写明为什么不在包内）；`GRAPH_ERROR_MESSAGES` 五表项；事件名 `_EVENT_GRAPH_FETCHED` / `_EVENT_CANDIDATES_RESOLVED`；公开六个函数 + `CANDIDATE_SIGNATURE_MAX_CHARS`；私有 `_log_*` / `_truncate_signature`。图相关一律经包根 barrel；ORM 模型函数体内 lazy import。
- `server/tests/services/code_graph/test_impact_shell.py` — 摘掉 2 个 skip 并填实（超预算种子透传 / GraphError 不吞）；新增 `test_degradation_payload_declares_resolution_rate_numerically`；`test_ambiguous_symbol_short_circuits_before_graph_fetch` 仍挂 skip 待 122-07。
- `server/tests/services/code_graph/test_staleness.py` — 两条 D-22 用例落地，零 skip。
- `server/tests/services/code_graph/test_symbol_resolve.py` — `test_ambiguous_returns_candidates` 落地（ORM + signature 截断 + file_path 一次收敛），本文件现已零 skip。
- `server/tests/services/code_graph/test_access.py` — 新增 `_SIBLING_GUARDED_MODULES`；`test_observability_contract` 扫描面 = 包内 glob + 兄弟清单；`category` 按 `source_path.parent == package_dir` 分流。⛔ 未改 barrel / upper_layer 两组用例。

## Decisions Made

- **模块位置的唯一理由是 ORM 边界**，不是「要发 caller 事件」。本模块与 122-06 声明的每一个事件都是 `category="sampling"`；`caller` 要到 122-08 / 122-09 的壳层才出现。契约扩展时把 `category` 放宽到 `{sampling, caller}` 只是给将来留位。
- **翻译在映射表文案与 `exc.message` 不同时拼成「表文案（message）」**。表文案是给 agent 的下一步指引，`exc.message` 是本仓 raise 点写死的短句（不含内部量）；两者都有信息，且都不含 `details`。
- **`behind_commits == 0` 单独措辞「索引与远端一致」**，与「落后 N」和「未知」三档区分——「落后 0 commits」在中文里听起来像在绕弯子。
- **⛔ 不预登记 `code_graph_cross_repo.py`**。存在性断言会在 122-05 完成到 122-06 落地之间一直红；谁新建谁登记。
- **`ruff format` 不作为本包门禁**（沿用 122-02 起的裁决）。本文件对齐包内 88 列风格。plan `<verification>` 要求的 `ruff check` 对本 plan 文件全绿。

## Deviations from Plan

None - plan executed exactly as written。四个 task 的 acceptance criteria 全部逐条实测通过，未触发任何 Rule 1–4 的自动修复。

## Verification Results

| 判据 | 结果 |
|---|---|
| `pytest tests/services/code_graph -q --reuse-db` | **117 passed / 6 skipped**（基线 111/11，+6 passed / −5 skipped，零新增失败）。`test_staleness.py` / `test_symbol_resolve.py` 零 skip；`test_impact_shell.py` 剩 1 skip（归 122-07） |
| `test_access.py` 全绿 | **19 passed**（扩展后本模块两个埋点已满足全部判据） |
| 变异测试（缺 `code_graph_` 前缀） | **必须失败**：`code_graph_tools.py:598:bad_event_name 事件名缺少 code_graph_ 前缀`；删除后复跑全绿 |
| AST import 守护（无 loader/cache/signature/access 直连） | 退出码 0 |
| AST 无 `.afirst()` / `.first()` | 退出码 0，实际调用面含 `acount` / `aexists` / `values_list` / `filter` / `order_by` |
| `degradation_payload` 源码含全部必透字段 | 退出码 0 |
| `_SIBLING_GUARDED_MODULES == ("code_graph_tools.py",)` 且用例引用该常量 | 退出码 0 |
| `ruff check` 对本 plan 5 个文件 | All checks passed |
| `mypy services/code_graph/ services/code_graph_tools.py` | **本 plan 文件零错误**（报出的 9 条全在包外既有 / 并发会话编辑面） |
| `makemigrations --check --dry-run` | `No changes detected`，退出码 0 |
| `git diff --name-only HEAD~4 HEAD` | 恰 5 个文件，**不含** `repo_router_v2.py` 与 `mcp/` |

## Issues Encountered

- `uv run ruff check services/`（plan `<verification>` 首次把 gate 扩到整个 `services/`）报出两条**先于本 plan 存在**的 error：`branch_search.py:109`（F841）与 `project_context_packer.py:415`（I001）。两个文件均未被本会话或并发会话修改，按 scope boundary 未修，已记入 `deferred-items.md`。本 plan 5 个文件 `ruff check` 全绿。
- 第一次跑 `test_symbol_resolve.py` 时 `test_uid_takes_precedence` 偶发 ERROR（疑似 Django 应用加载竞态），立即复跑 4 passed；与本 plan 改动无关，未计入失败。

## Mutation Test Report（Task 4 必报）

临时在 `services/code_graph_tools.py` 末尾追加：

```python
def _mutation_probe() -> None:
    logger.info("bad_event_name", component="code_graph", category="sampling")
```

`pytest tests/services/code_graph/test_access.py -k observability` **失败**，违规信息：

```text
code_graph_tools.py:598:bad_event_name 事件名缺少 code_graph_ 前缀
```

随后完整删除追加代码并复跑至 **19 passed**。证明扩展后的扫描面真的覆盖到了兄弟文件，四条核心判据（事件名前缀 / 静态可解析 / `component` / `error=` 脱敏）未被放宽。

## Known Stubs

| 桩 | 归属 |
|---|---|
| `test_ambiguous_symbol_short_circuits_before_graph_fetch`（`test_impact_shell.py`） | **122-07**（`run_impact` 短路） |
| `test_impact.py::test_graph_cross_repo_edges_are_intra_repo` | **122-06** |
| 跨仓 / MCP / 对话壳其余 skip 桩 | 122-06 / 08 / 09 / 10 |

本 plan 交付的生产代码里没有任何占位字段、没有恒空返回、没有 TODO。

## Threat Flags

无新增威胁面。plan `<threat_model>` 的 `mitigate` 落地情况：

| Threat ID | 落地方式 | 判据 |
|---|---|---|
| T-122-绕闸 | 图相关只经包根 barrel；AST 断言禁止内部子模块直连 | `test_access.py -k upper_layer` + 就地 AST 断言退出码 0 |
| T-122-错误细节泄漏 | 翻译只用表常量 + `exc.message`，⛔ 不用 `str(exc)` | `test_graph_error_translated_not_swallowed` 断言 `999` / `estimated_bytes` 不在文案里 |
| T-122-空图误导 | `fetch_graph_for_tool` 不 catch `GraphError` | 未索引仓 `pytest.raises(GraphNotIndexed)` |
| T-122-半新图误导 | 四个标记 + 数值 `resolution_rate` 全透出；degraded 两档区分 | `test_degradation_payload_…` |
| T-122-遍历 DoS | `acount()` + `[:CANDIDATE_LIMIT]`；signature 截断 200 | AST 无 `afirst`/`first`；截断断言 `len <= 201` |
| T-122-日志放大 | 三个 `_log_*` 全 DEBUG + `sampling`；每原语至多一条 | 观测契约 19 passed |
| T-122-观测缺口 | 扫描面扩到 `code_graph_tools.py`；变异测试实跑 | 见上方 Mutation Test Report |
| T-122-穿仓 | 每次取图都经 `ensure_repository_readable` | `get_graph` 契约；跨仓复核归 122-06 |
| T-122-SC | `accept` —— **零新增依赖** | Package Legitimacy Audit 表为空 |

## 如实记账（供 122-10 汇总）

- **本 plan 不交付任何用户可达的工具面**。`run_impact` / `run_trace` 归 122-07，MCP / 对话壳归 122-08 / 09。⛔ 不得据本 plan 勾选 IMPACT-05 / IMPACT-06。
- **本 plan 全程未碰并发会话的编辑面**：四个 task commit 恰触及 5 个文件，`git diff --name-only HEAD~4 HEAD` 中无 `mcp/`、无 `server/repositories/`、无 `server/durable/`、无 `server/codegraph/`、无 `web/`。并发会话的 ~59 条未提交改动保持原样。
- **`mcp` submodule 与 `repo_router_v2.py` 全程未碰**。

## User Setup Required

None - 零新增依赖、零迁移、零模型变更、无外部服务配置。

## Next Phase Readiness

- **122-06** 可直接复用 `fetch_graph_for_tool` / `graph_error_to_tool_error` 做跨仓一跳，并把自己的 `code_graph_cross_repo.py` 加进 `_SIBLING_GUARDED_MODULES`。
- **122-07** 可直接把 `resolve_symbol_candidates` → `fetch_graph_for_tool` → 内核 → `staleness_payload` / `degradation_payload` 串成 `run_impact` / `run_trace`；重名短路用例的桩已在 `test_impact_shell.py` 就位。
- **IMPACT-05 未标记完成**：本 plan 只交付编排原语，工具面还差 122-07/08/09。⛔ 不得据本 plan 勾选 REQUIREMENTS。
- **无 blocker。**

## Self-Check: PASSED

- 交付文件均存在于磁盘：`server/services/code_graph_tools.py`（594 行）、四个测试文件均已更新。
- 四个 task commit（`933f2133` / `52c07113` / `4bf50348` / `f73ff656`）均可在 `git log` 中查到。

---
*Phase: 122-impact-trace*
*Completed: 2026-08-09*
