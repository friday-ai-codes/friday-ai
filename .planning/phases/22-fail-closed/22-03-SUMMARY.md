---
phase: 22-fail-closed
plan: 03
subsystem: retrieval
tags: [exclusion, fail-closed, security, rag, hybrid-search, agent-tools, EXCL-02]

# Dependency graph
requires:
  - phase: 22-fail-closed
    plan: 01
    provides: "services.exclusion 单一匹配器（build_matcher_for_repo / ExclusionMatcher.is_excluded / log_exclusion_blocked）"
  - phase: 22-fail-closed
    plan: 02
    provides: "scan_directory 注入式 is_excluded_rel 回调（跨面守护测试复用索引扫描面）"
provides:
  - "search_rag 单一 chokepoint：per-repo 预取匹配器，收集/排序前剔除被排除文件项，命中 log exclusion.blocked surface=rag"
  - "hybrid_search 图谱邻居（hop1/hop2/cross-repo）渲染前 + 返回结果同步剔除被排除 file_path（any-repo-hit，fail-closed）"
  - "browse_file_content 命中排除路径拒读（chunks=[] + error=File is excluded by policy，无任何明文）；fuzzy resolved_path 复判防后缀绕过"
  - "list_space_structure 文件树按 per-repo 匹配器过滤被排除文件"
  - "search_repository_code 兜底再过滤（防御未来不经 search_rag 的旁路回流）"
  - "跨面 fail-closed 守护测试：同一被排除文件在 索引扫描 / browse / RAG 三面均不可见（builtin 默认 + per-repo 规则两情形）"
affects: [23-purge 存量清理对账, RAG 调用方（chat/agent/workflow）]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "search_rag 是 RAG 单一过滤点：过滤一处即覆盖 chat/agent/workflow 所有 RAG 调用方"
    - "读取面 fail-closed：matcher 构造异常→整 repo 丢弃 / 判定异常→单项丢弃；绝不降级泄漏明文"
    - "图谱邻居无 repo 归属 → 对传入 repo_ids 逐一判定，任一命中即剔除（any-hit fail-closed）"
    - "工具拒读返回保持既有契约（success=True + error 文案），不破坏 fuzzy/诊断逻辑"

key-files:
  created:
    - server/tests/services/test_retrieval_exclusion.py
    - server/tests/agents/test_tools_exclusion.py
  modified:
    - server/services/retrieval/rag_search.py
    - server/services/retrieval/hybrid_search.py
    - server/agents/tools/chat_tools.py
    - server/agents/tools/space_tools.py
    - server/tests/codegraph/conftest.py
    - server/tests/services/retrieval/test_hybrid_graph_capable_golden.py

key-decisions:
  - "图谱邻居过滤在 _render_graph_context 之前对邻居列表过滤（而非给渲染器传回调），同时剔除返回的 hop1/hop2/cross-repo 列表，更彻底"
  - "browse_file_content 在入口（拿到 repository_id+file_path 后、scroll 前）即判定拒读；fuzzy 解析出 resolved_path 后复判防 endswith 绕过（T-22-09）"
  - "search_repository_code 兜底过滤为防御层（search_rag 已是 chokepoint），命中 log surface=search_repository_code"
  - "golden byte-eq 环境注入 no-op 匹配器（golden fixtures 路径良性、repo_ids 为合成串无法走真实 DB），保证既有 byte-eq 不漂移"

patterns-established:
  - "新增 RAG 读取面必须经 search_rag（唯一过滤点）；旁路直读面须单独挂 build_matcher_for_repo"
  - "进程内工具读取面命中排除一律 fail-closed 拒读，统一 log_exclusion_blocked(surface=...)"

requirements-completed: [EXCL-02]

# Metrics
duration: ~22min
completed: 2026-06-14
---

# Phase 22 Plan 03: 进程内工具面 + RAG 检索 fail-closed 排除 Summary

**把 Plan 01 的单一匹配器挂接到 RAG 单一 chokepoint（`search_rag` + 图谱邻居 hop1/hop2/cross-repo 渲染）与进程内 chat/agent 工具读取面（`browse_file_content` 拒读、`list_space_structure` 文件树过滤、`search_repository_code` 兜底过滤）——被排除文件在检索 / 工具读取面 fail-closed 不可见，命中即拒读/丢弃，绝不降级泄漏明文；并落地跨面守护测试（索引扫描 + browse + RAG 三面同一文件均不可见）。**

## Performance

- **Duration:** ~22 min
- **Tasks:** 3（Task 1 / Task 2 走 TDD）
- **Files modified:** 8（2 新增测试 + 4 service/tool + 2 golden 测试/conftest 适配）

## Accomplishments
- `search_rag`：按 repo 预取 `build_matcher_for_repo`（每 repo 一次），在收集 `all_results`、去重/排序/截断之前对每项 `payload.file_path` 判定排除，命中即丢弃 + `log_exclusion_blocked(surface="rag")`；matcher 构造异常 → 整 repo 结果丢弃，判定异常 → 单项丢弃（fail-closed，绝不抛出/降级）。
- `hybrid_search`：新增 `_build_is_excluded_path`（对 repo_ids 逐一取匹配器，any-hit + 缺失/异常 fail-closed）与 `_filter_excluded_neighbors`，在 `_render_graph_context` 前剔除 hop1/hop2/cross-repo 被排除邻居，返回的 `hop1_neighbors`/`hop2_neighbors`/`cross_repo_neighbors` 列表与 `graph_context`/`final_context` 同步不含被排除路径。
- `browse_file_content`：入口即 `is_excluded(repository_id, file_path)` 判定，命中 → `chunks=[]` + `error="File is excluded by policy"`（绝不进入 scroll、无任何明文）+ `surface="browse_file_content"` 审计；fuzzy 解析出的 `resolved_path` 复判防后缀绕过（T-22-09）。
- `list_space_structure`：按各自 repo 匹配器过滤被排除文件，不进入文件树。
- `search_repository_code`：组装 `all_results` 后加一道 per-repo 兜底过滤（防御未来不经 `search_rag` 的旁路回流，T-22-10）。
- 跨面守护测试：同一被排除文件在 (a) 索引扫描 `scan_directory`（不进待索引集）(b) `browse_file_content`（拒读）(c) `search_rag`（结果不含）三面一致不可见；内置全局默认（`config/secret.json`）与 per-repo 规则（`*.private.js`）两来源各跑一遍（验证 EXCL-01 两层）。
- 15 个守护测试全绿（retrieval 9 + agent tools 6）；既有 hybrid_search byte-eq golden/skeleton 测试经 no-op 匹配器注入后保持不漂移。

## Task Commits

Each task committed atomically (TDD RED → GREEN where applicable):

1. **Task 1: RAG chokepoint + 图谱邻居过滤** - `a4ea109c0` (test, RED) → `d77d348e1` (feat, GREEN — conftest/golden/测试适配) → `0e9b80a26` (feat — 补 rag_search/hybrid_search 实现文件)
2. **Task 2: browse_file_content 拒读 + list_space_structure 过滤 + search_repository_code 兜底** - `1ca1793ca` (test, RED) → `5b3c2829b` (feat, GREEN)
3. **Task 3: 跨面 fail-closed 守护测试（scan + browse + RAG）** - `481ba91d6` (test)

## Files Created/Modified
- `server/services/retrieval/rag_search.py` - search_rag per-repo 匹配器预取 + 收集前过滤 + fail-closed。
- `server/services/retrieval/hybrid_search.py` - `_build_is_excluded_path` / `_filter_excluded_neighbors`，图谱邻居渲染前 + 返回结果剔除。
- `server/agents/tools/chat_tools.py` - browse_file_content 入口/resolved 双判定拒读 + list_space_structure 文件树过滤 + fail-closed 助手。
- `server/agents/tools/space_tools.py` - search_repository_code 兜底再过滤。
- `server/tests/services/test_retrieval_exclusion.py` - RAG/图谱过滤 + 跨面守护测试（9 例）。
- `server/tests/agents/test_tools_exclusion.py` - 工具读取面拒读/过滤守护测试（6 例）。
- `server/tests/codegraph/conftest.py` - golden 环境注入 no-op 匹配器（byte-eq 不漂移）。
- `server/tests/services/retrieval/test_hybrid_graph_capable_golden.py` - graph_capable golden 注入 no-op 匹配器。

## Decisions Made
- **邻居过滤位置**：在 `_render_graph_context` 之前对邻居列表过滤，并同步剔除返回的 hop1/hop2/cross-repo 列表——比仅给渲染器传 `is_excluded_path` 回调更彻底（返回结构里也不含被排除路径）。
- **any-repo-hit 语义**：邻居 metadata 无 repository_id 归属，对传入 repo_ids 逐一判定，任一命中即剔除；某 repo 匹配器构造失败 → 视为命中（fail-closed，宁可多排不可漏）。
- **golden byte-eq 不漂移**：golden 环境等价「无排除规则」，注入 no-op 匹配器（`is_excluded` 恒 False），既有 byte-eq fixture 不需要改 golden 值。

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] 图谱邻居守护测试 matcher 漏匹配 hop2 文件**
- **Found during:** Task 1（GREEN 验证）
- **Issue:** `test_graph_capable_filters_excluded_neighbors` 的 `_builtin_matcher` 用 `.env` glob（`fnmatch` 全串匹配），无法命中 hop2 的 `secrets.env`，导致 `".env" not in graph_context` 子串断言无法成立（`secrets.env` 含 `.env` 子串）。按测试 docstring 意图（hop1/hop2 被排除邻居均应剔除），改 `_builtin_matcher` 为 `*.env` 让 `secrets.env` 真正命中。
- **Files modified:** server/tests/services/test_retrieval_exclusion.py
- **Verification:** 7/7（后扩至 9/9）retrieval 守护测试通过。
- **Committed in:** d77d348e1（Task 1 GREEN 提交）

**2. [Rule 3 - Blocking] Task 1 实现文件遗漏提交**
- **Found during:** Task 1（resume 复核）
- **Issue:** `d77d348e1` GREEN 提交了 conftest/golden/测试更新，却漏提交实现文件 `rag_search.py` / `hybrid_search.py`（实现仅在工作树），导致 RAG/图谱过滤实现未入库。
- **Fix:** 补提交两实现文件。
- **Files modified:** server/services/retrieval/rag_search.py, server/services/retrieval/hybrid_search.py
- **Verification:** 全量 retrieval 套件 157 passed。
- **Committed in:** 0e9b80a26

**3. [Rule 1 - Bug] e2e callsite 测试 mock 用非法 repo_id 触发兜底 fail-closed**
- **Found during:** Task 2 收尾全量回归
- **Issue:** 既有 `tests/services/retrieval/test_hybrid_e2e_callsites.py` 的 mock L3 item 硬编码 `repository_id="repo-a"`（非 UUID）；Task 2 在 `search_repository_code` 新增的兜底过滤按 item.repository_id 预取匹配器，非法 id → `build_matcher_for_repo` 失败 → fail-closed 丢弃全部结果 → `test_agent_search_repository_code_returns_l3_results` 断言空。
- **Fix:** mock helper `_l3_snapshot_with_items(repo_id)` 改用真实 repo_id（生产路径 search_rag 本就写真实 id，故仅 mock 数据不真实）。
- **Files modified:** server/tests/services/retrieval/test_hybrid_e2e_callsites.py
- **Verification:** e2e 5 passed + retrieval 全量 165 passed。
- **Committed in:** 7229ba3e0

---

**Total deviations:** 3 auto-fixed（2 测试 bug / mock 数据，1 阻塞性提交遗漏）
**Impact on plan:** 均为兑现 plan acceptance / 保持既有契约所必需，无范围蔓延。兜底 fail-closed 语义未削弱（生产路径 repository_id 恒为真实 UUID）。

## Issues Encountered
- 执行期出现 reflog 抖动（连续提交 + 一次 no-op reset）一度被误判为「并发执行器」；经澄清确认全部为本会话自身活动，工作树独占。
- 测试运行器：`uv run pytest`（rootdir=server）正常；个别 byte-eq 测试在工作树中途态下表现为「文件内修改 vs 套件」错位，settle 后全绿。

## Known Stubs / EXCL-02 读取面残余缺口（记入 deferred-items.md，移交收尾/后续 plan）
本 plan 严守 `files_modified` 边界，未扩改以下**不经 `search_rag` 的 RAG 旁路直读面**——它们仍可能漏出被排除文件，是 EXCL-02 的已知缺口：
- `server/repositories/index_views.py` `_vector_search`（仓库搜索 API 直读 RAG，返回 content）。
- `server/codegraph/services/layered_search.py` `LayeredSearchService._l3_hybrid_search`（已 deprecated，但 compat 路径仍可返回 RAG 结果）。
建议收尾/后续 plan 给这两处挂同一 `build_matcher_for_repo` 过滤（或迁移到 `search_rag`）。详见 `deferred-items.md`。

## Threat Flags

| Flag | File | Description |
|------|------|-------------|
| threat_flag: information_disclosure | server/repositories/index_views.py | `_vector_search` 直读 RAG 不经 search_rag，被排除文件可漏出（EXCL-02 缺口，移交后续） |
| threat_flag: information_disclosure | server/codegraph/services/layered_search.py | `_l3_hybrid_search`（deprecated）compat 路径返回 RAG 结果不过滤（EXCL-02 缺口，移交后续） |

## Next Phase Readiness
- EXCL-02 读取面主线（索引扫描 / MCP 工具 / RAG 检索 / 进程内 agent 工具 / 编码容器）已 fail-closed；跨面守护测试兑现 specifics「四面不可见」要求（MCP 面由 22-06 守护，本 plan 守护 server 内三面）。
- 存量被排除文件派生数据（Qdrant 残留 point、镜像 git object）清理仍留 Phase 23（本阶段仅保证读取面不可见，未删历史，per D-04）。
- 上述两处 RAG 旁路直读缺口建议在 Phase 23 收尾或独立 quick task 闭合。

## Self-Check: PASSED

- Files: test_retrieval_exclusion.py / test_tools_exclusion.py / rag_search.py / hybrid_search.py / chat_tools.py / space_tools.py / 22-03-SUMMARY.md — all FOUND.
- Commits: a4ea109c0 / d77d348e1 / 0e9b80a26 / 1ca1793ca / 5b3c2829b / 481ba91d6 — all FOUND.
- Tests: 15 passed（`uv run pytest tests/services/test_retrieval_exclusion.py tests/agents/test_tools_exclusion.py`）；retrieval 全量 + 两守护文件 165 passed / 1 skipped（无 byte-eq 漂移）。
- Lint: `ruff format` 已应用（无改动）；`ruff check` 干净。

---
*Phase: 22-fail-closed*
*Completed: 2026-06-14*
