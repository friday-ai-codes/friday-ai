---
phase: 22-fail-closed
verified: 2026-06-14T10:11:00Z
status: passed
score: 6/6 must-haves verified
overrides_applied: 0
re_verification:
  previous_status: gaps_found
  previous_score: 4/6
  gaps_closed:
    - "被排除文件在 RAG 检索读取面 fail-closed 不可见（CodeSearchView._search，EXCL-02）"
  gaps_remaining: []
  regressions: []
gaps: []
deferred: []
# 非阻断 UAT 备记（autonomous 模式下转入 UAT，不阻断 phase 完成）：
# Plan 05 排除规则编辑面板的浏览器层人工核对（展示/增删/regex 报错/override/安全措辞）。
# 面板已实现 + 类型/构建通过，属对既有功能的视觉确认，非功能缺口，故不阻断。
---

# Phase 22: 排除配置与统一过滤（fail-closed）Verification Report

**Phase Goal:** 建立 per-repo/全局排除配置单一源，并在所有读取面 fail-closed 拦截被排除文件。
**Verified:** 2026-06-14T10:11:00Z（re-verification）
**Status:** passed
**Re-verification:** Yes — after gap closure（commit 56d230553）

## Goal Achievement

### Observable Truths

| # | Truth | Status | Evidence |
|---|-------|--------|----------|
| 1 | 单一匹配器 `is_excluded(repo, rel_path)` 作为唯一判定入口，dir/glob/regex 三类、相对仓库根 POSIX、fail-closed/fail-loud 分明 | ✓ VERIFIED | `server/services/exclusion.py`：`ExclusionMatcher`（110-167）归一越界/运行期异常→True（149,161-167）；非法 regex 构造期抛 `InvalidExclusionRuleError`（138-141）；`BUILTIN_GLOBAL_DEFAULTS`（53-74）含 .env/*.pem/id_rsa/.git//node_modules/；`build_matcher_for_repo`+TTL 缓存（266-276）。单测 `test_exclusion_matcher.py` 覆盖三类+越界+异常+合并 |
| 2 | EXCL-01：可配置 per-repo + 全局默认排除规则（REST API + 前端面板 + regex fail-loud + 缓存失效） | ✓ VERIFIED | `RepoExclusionRule` 模型（models.py:723）+ 迁移 0032；`repositories/views.py` 写操作后 `invalidate_matcher_cache`（1077,1106）；`web/src/api/exclusions.ts` + `ExclusionRulesPanel.vue`；REQUIREMENTS.md EXCL-01 已勾选 |
| 3 | 索引扫描（full+incremental）被排除文件不进入索引 + PF-04 注释修正 | ✓ VERIFIED | `indexer.py` full（840-841）+ incremental（2190-2191）经 `build_matcher_for_repo`→`scan_directory(is_excluded_rel=...)`；`code_parser.scan_directory` 注入回调 + 如实 docstring（642-701）；守护测试 `test_indexer_exclusion.py` |
| 4 | MCP 工具面（get_file/grep/list/find_related）+ 进程内 agent 工具 + 编码容器 clone 后 fail-closed | ✓ VERIFIED | `mcp_tools/views.py` grep（574,577）/list（830）/get_file（901）/find_related（1131）；`chat_tools.py`（41,52）/`space_tools.py`（35,42）；`task/core/exclusion.py:prune_excluded` + `ExclusionPruneError`（持久失败致命）+ `git_ops/operations.py:106` 调用；两派发路径注入 env（coding_session_service.py:204 / coding.py:963） |
| 5 | RAG 检索全部读取面 fail-closed（**所有**读取面，含 REST 检索端点） | ✓ VERIFIED | `search_rag` chokepoint 已过滤（rag_search.py:85-106），hybrid_search 邻居已过滤，GraphSearchView/LayeredSearchService.search 经 HybridSearchService 间接过滤；**CodeSearchView._search 缺口已闭合**（commit 56d230553）：index_views.py:746-789 构造 `build_matcher_for_repo` + 逐项 `matcher.is_excluded` 过滤后再回填 content/file_path，matcher 构造失败 → 整仓库返回空，单项异常/`file_path` 缺失 → 丢弃，命中 `log_exclusion_blocked(surface="code_search")`。守护测试 `TestCodeSearchViewExclusion` 6 passed/2 skipped |
| 6 | 工具层命中即拒读、不降级泄漏明文 | ✓ VERIFIED | 各工具面命中→拒读/丢弃 + `log_exclusion_blocked`；matcher/判定异常一律 fail-closed（rag_search 整 repo 丢弃 / 单项丢弃；mcp/agent 拒读；code_search 同口径）；`exclusion.blocked` 审计埋点齐备 |

**Score:** 6/6 truths verified（唯一 EXCL-02 缺口已闭合并经守护测试覆盖）

### 旁路读取面研判（用户重点关注项 — 复核结果）

| 旁路 | 实际位置 | 可达性 | 是否泄漏 | 判定 |
|------|----------|--------|----------|------|
| `_vector_search`（deferred-items 记名） | 已重命名为 `CodeSearchView._search`（`server/repositories/index_views.py:686`） | **可达**：`POST /api/repositories/<id>/search/`（urls.py:170，IsAuthenticated），前端 `web/src/api/repositories.ts:393 searchCode` 调用 | **已闭合**：返回前经 `build_matcher_for_repo`+`is_excluded` 过滤（746-789），fail-closed | ✓ **已修复（commit 56d230553）** |
| `_l3_hybrid_search`（deprecated） | `server/codegraph/services/layered_search.py:219` | **不可达**（生产）：唯一生产入口 `LayeredSearchService.search` 已 thin-delegate 到 `HybridSearchService.search`（layered_search.py:86），后者经 `search_rag` 过滤；`_l3_hybrid_search` 仅被自身定义 + contract 测试调用 | 否（无生产调用方） | ✓ 死/内部代码，**非 reachable 缺口** |

研判结论：初次验证标注的 `CodeSearchView._search` 真实泄漏面已闭合——现挂同一单一匹配器、fail-closed、有守护测试。`_l3_hybrid_search` 仍为 deprecated thin-wrapper 的内部 helper，所有生产调用都走已过滤的 `search_rag`，非缺口。两处旁路均不再泄漏。

### Required Artifacts

| Artifact | Expected | Status | Details |
|----------|----------|--------|---------|
| `server/services/exclusion.py` | 单一匹配器 + 内置默认 + 合并 + 序列化 + 审计 | ✓ VERIFIED | 301 行，全符号齐备，fail-closed/fail-loud 分明 |
| `server/repositories/models.py` | `RepoExclusionRule` | ✓ VERIFIED | :723 |
| `server/repositories/migrations/0032_repo_exclusion_rule.py` | 建表迁移 | ✓ VERIFIED | 存在 |
| `server/services/indexer.py` / `code_parser.py` | 扫描挂接 + PF-04 修正 | ✓ VERIFIED | full+incremental 挂接；scan_directory 回调 + 如实 docstring |
| `server/services/retrieval/rag_search.py` / `hybrid_search.py` | search_rag chokepoint + 邻居过滤 | ✓ VERIFIED | 85-106 / 173-212,556-564 |
| `server/agents/tools/chat_tools.py` / `space_tools.py` | browse 拒读 / 文件树 / 兜底过滤 | ✓ VERIFIED | 已挂接 |
| `server/mcp_tools/views.py` | grep/get_file/list/find_related fail-closed | ✓ VERIFIED | 574/577/830/901/1131 |
| `task/core/exclusion.py` / `git_ops/operations.py` | 容器 prune + fail-closed | ✓ VERIFIED | prune_excluded + ExclusionPruneError + setup 调用 |
| `server/repositories/views.py` + `web/.../ExclusionRulesPanel.vue` | REST API + 前端面板 | ✓ VERIFIED | CRUD + 缓存失效 + 面板 |
| `server/repositories/index_views.py` | RAG 检索端点 fail-closed | ✓ VERIFIED | `CodeSearchView._search` 挂 build_matcher_for_repo + is_excluded（746-789），fail-closed + 守护测试 |

### Key Link Verification

| From | To | Via | Status |
|------|----|----|--------|
| `rag_search.search_rag` | `services.exclusion.is_excluded` | per-repo 预取 matcher + 收集前过滤 | ✓ WIRED |
| `indexer.run_full_index/run_incremental_index` | `build_matcher_for_repo` | scan_directory(is_excluded_rel) | ✓ WIRED |
| `mcp_tools.views.*` | `build_matcher_for_repo` | 读出后/返回前过滤 | ✓ WIRED |
| `coding_session_service / coding.py` | `serialize_rules_for_repo` | env_FRIDAY_TASK_EXCLUDE_PATTERNS | ✓ WIRED |
| `git_ops.setup` | `task.core.exclusion.prune_excluded` | checkout 后删除 | ✓ WIRED |
| `repositories.views` writes | `invalidate_matcher_cache` | 写后失效 | ✓ WIRED |
| `CodeSearchView._search` | `services.exclusion.build_matcher_for_repo` / `is_excluded` | 返回 content 前过滤 | ✓ WIRED（commit 56d230553） |

### Requirements Coverage

| Requirement | Source Plan | Description | Status | Evidence |
|-------------|-------------|-------------|--------|----------|
| EXCL-01 | 22-01, 22-05 | 可配置 per-repo + 全局默认排除规则 | ✓ SATISFIED | 模型/迁移/内置默认/REST CRUD/regex fail-loud/缓存失效/前端面板；REQUIREMENTS.md 已勾选 |
| EXCL-02 | 22-02/03/04/06 + 收尾 | 被排除文件在 RAG/MCP/agent/容器 fail-closed 不可见 | ✓ SATISFIED | 索引扫描/MCP/进程内工具/容器/`search_rag` 主线 + `CodeSearchView._search` REST 读取面（commit 56d230553）均已 fail-closed 闭合，"所有读取面"达成；各面均有守护测试 |
| PF-04 | 22-02 | scan_directory 注释谎称 .gitignore 修正 | ✓ SATISFIED | code_parser.scan_directory docstring 如实，indexer 注释已改 |

### Anti-Patterns Found

| File | Pattern | Severity | Impact |
|------|---------|----------|--------|
| — | — | — | 无（初次验证的 `CodeSearchView._search` 阻断项已闭合，见下） |

未发现 TBD/FIXME/XXX 等无引用 debt marker（不触发 debt marker gate）。

### 缺口闭合复核（re-verification）

**已闭合：** `CodeSearchView._search`（`server/repositories/index_views.py:746-789`，commit 56d230553）
- 返回 content/file_path 前构造 `build_matcher_for_repo(repository_id)`；构造失败 → 整仓库返回 `[]`（fail-closed，不泄漏存在性）。
- 逐项 `matcher.is_excluded(file_path)`：命中 / `file_path` 缺失 / 判定异常 → 丢弃该项（fail-closed）+ `log_exclusion_blocked(surface="code_search")`。
- `post` 的 `total` 由过滤后 `results` 重算（index_views.py:682）。
- 守护测试 `TestCodeSearchViewExclusion`（`server/tests/test_code_search_branch.py:130`）：`test_excluded_file_not_returned` + `test_failclosed_on_matcher_build_error`；既有 branch 测试已 patch `services.exclusion.build_matcher_for_repo` 保持绿。
- 实跑：`uv run pytest tests/test_code_search_branch.py -q` → **6 passed, 2 skipped**。

其余读取面（索引扫描、MCP、进程内 agent 工具、`search_rag` chokepoint、hybrid 邻居、GraphSearchView、容器 prune）本次未改动，保持初次验证的 VERIFIED 状态，无回归。

### 非阻断 UAT 备记（不影响 status）

Plan 05 排除规则编辑面板的浏览器层人工核对（展示内置默认 / 增删 / 非法 regex 报错 / override / 安全措辞）在 autonomous 模式下转入 UAT，单独记录。面板已实现且类型/构建通过（`ExclusionRulesPanel.vue` + `exclusions.ts`），此项为对既有功能的视觉确认，非功能缺口，**不阻断 phase 完成**。

### Gaps Summary

无阻断缺口。Phase 22 的排除地基（单一匹配器、单一源、合并语义、fail-closed/fail-loud、审计埋点）实现扎实；EXCL-01 配置闭环（模型+API+前端+缓存失效）达成；EXCL-02 在**全部读取面**——索引扫描 full/incremental、MCP get_file/grep/list/find_related、进程内 agent 工具、`search_rag` 统一 chokepoint（chat/agent/workflow）、hybrid 图谱邻居、GraphSearchView、编码容器 clone 后 prune，以及本次闭合的 `CodeSearchView._search` REST 检索端点——均已 fail-closed 闭合，并各有守护测试覆盖。`_l3_hybrid_search` 经复核为 deprecated 死代码（生产入口均走已过滤的 `search_rag`），非缺口。phase goal「在所有读取面 fail-closed 拦截被排除文件」达成。

---

_Verified: 2026-06-14T10:11:00Z（re-verification after commit 56d230553）_
_Verifier: Claude (gsd-verifier)_
