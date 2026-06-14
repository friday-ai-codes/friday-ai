---
phase: 22-fail-closed
plan: GAP
subsystem: repositories
tags: [exclusion, fail-closed, security, rag, rest, EXCL-02, gap-closure]

# Dependency graph
requires:
  - phase: 22-fail-closed
    plan: 01
    provides: "services.exclusion 单一匹配器（build_matcher_for_repo / ExclusionMatcher.is_excluded / log_exclusion_blocked）"
  - phase: 22-fail-closed
    plan: 03
    provides: "search_rag chokepoint fail-closed 过滤模式（per-repo 预取匹配器、收集前剔除、构造/判定异常 fail-closed）——本 gap 镜像该模式到 REST 旁路面"
provides:
  - "CodeSearchView._search REST RAG 读取面 fail-closed：返回前按 build_matcher_for_repo + is_excluded 剔除被排除 file_path（无 content/无 path），total 由过滤后集合重算；matcher 构造失败 → 整仓库不可见；单项判定异常 → 丢弃该项"
  - "CodeSearchView 守护测试（被排除文件不返回 + 构造失败 fail-closed），与 search_rag 守护测试对称"
affects: [23-purge 存量清理对账]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "不经 search_rag chokepoint 的 RAG 旁路直读面，须单独自挂 build_matcher_for_repo + is_excluded（与 22-03 patterns-established 一致）"
    - "fail-closed：matcher 构造异常 → 整仓库结果丢弃 / 单项判定异常 → 丢弃该项；counts/total 一律由过滤后集合重算，不泄漏被排除文件存在性"

key-files:
  created: []
  modified:
    - server/repositories/index_views.py
    - server/tests/test_code_search_branch.py

key-decisions:
  - "在 _search 返回构造结果前先 build_matcher_for_repo（一次/调用），构造失败即 return [] 整仓库 fail-closed；逐项 is_excluded 判定，命中或判定异常即 continue 丢弃 + log surface=code_search"
  - "total 无需特判：post() 已用 len(filtered results) 计算，过滤后自动重算，不暴露被排除文件数量"
  - "file_path 缺失依赖 matcher.is_excluded(None) → normalize 归一失败 → True（fail-closed），无需额外分支"

requirements-completed: [EXCL-02]

# Metrics
duration: ~12min
completed: 2026-06-14
---

# Phase 22 Gap: CodeSearchView REST 读取面 fail-closed 排除 Summary

**闭合 22-VERIFICATION 唯一阻断缺口（EXCL-02）：`CodeSearchView._search`（认证 REST 端点 `POST /api/repositories/<id>/search/`，前端 `searchCode` 在用）原直读 `BranchAwareSearchService.search` 返回 `content`/`file_path` 无任何 `is_excluded` 过滤，被排除文件明文与路径会经该 RAG 旁路直读面泄漏。本 gap 镜像 22-03 `search_rag` chokepoint 模式，给该端点自挂同一 `build_matcher_for_repo` + `matcher.is_excluded` 过滤——被排除文件 fail-closed 不可见，并补对称守护测试。**

## Performance

- **Duration:** ~12 min
- **Tasks:** 1（实现 + 守护测试，原子提交）
- **Files modified:** 2（1 实现 + 1 测试）

## Accomplishments

- `CodeSearchView._search`：在 `BranchAwareSearchService.search`（+ 可选 reranker）取得 `search_results` 后、构造返回 payload 前，按 repo 预取 `build_matcher_for_repo(repository_id)`：
  - matcher **构造失败** → `logger.warning("code_search_matcher_build_failed")` + `log_exclusion_blocked(surface="code_search")` + `return []`（整仓库 fail-closed 不可见）。
  - 逐项 `matcher.is_excluded(file_path)`：命中（含 `file_path` 缺失致归一失败、判定异常）即 `continue` 丢弃 + `log_exclusion_blocked(surface="code_search")`，**绝不**回填 `content`/`file_path`。
  - `post()` 的 `"total"` 由过滤后 `len(results)` 自动重算，不泄漏被排除文件存在性。
- 守护测试 `TestCodeSearchViewExclusion`（`tests/test_code_search_branch.py`），与 `search_rag` 守护测试对称：
  - `test_excluded_file_not_returned`：`config/app.env` 命中 `*.env` → 结果只含 `src/app.py`，被排除路径与明文（`codesearchleak`）均不出现。
  - `test_failclosed_on_matcher_build_error`：`build_matcher_for_repo` 抛异常 → `_search` 返回 `[]`，不向上抛。

## Task Commits

1. **Gap fix + 守护测试（原子）** — `56d230553`（fix: CodeSearchView._search fail-closed + TestCodeSearchViewExclusion）

## Files Created/Modified

- `server/repositories/index_views.py` — `CodeSearchView._search` 返回前挂 `build_matcher_for_repo` + `is_excluded` 过滤，fail-closed（构造失败整仓库丢弃 / 单项判定异常丢弃）+ `log_exclusion_blocked(surface="code_search")`。
- `server/tests/test_code_search_branch.py` — 新增 `TestCodeSearchViewExclusion`（2 例守护）；为既有 `test_search_passes_branch_to_service` 补 patch 一个 no-op `ExclusionMatcher`（其 mock 的 `SystemSetting.objects` 会令真实 matcher 构造 fail-closed 返回空，属本次 fail-closed 行为的直接连带，非缺陷）。

## Decisions Made

- **过滤位置**：在 reranker 之后、构造返回 payload 之前过滤——既覆盖原始 RAG 结果，也覆盖 rerank 重排后的集合。
- **total 不特判**：`post()` 已用过滤后 `len(results)` 计 `total`，无需额外重算逻辑，天然不泄漏被排除文件数量。
- **后缀绕过**：该端点直接返回 qdrant `payload.file_path`（无 browse 那样的 fuzzy 解析），单次 `is_excluded(file_path)`（内部 `normalize_rel_path` 归一越界/绝对路径 fail-closed）即足够，无需二次 resolved-path 复判。

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] 既有 CodeSearchView branch 测试因新 fail-closed 行为失败**
- **Found during:** 运行 `tests/test_code_search_branch.py`
- **Issue:** `test_search_passes_branch_to_service` 未 patch matcher，新增的 `build_matcher_for_repo` 在其 mock 的 `SystemSetting.objects`（MagicMock）下构造失败 → fail-closed `return []` → `len(results)==1` 断言失败。
- **Fix:** 给该测试 patch 一个空规则 `ExclusionMatcher`（no-op，排除零文件），保持其原 branch 传参断言意图。
- **Files modified:** server/tests/test_code_search_branch.py
- **Commit:** 56d230553

**Total deviations:** 1 auto-fixed（测试适配新 fail-closed 行为，无范围蔓延）

## Out of Scope / 未处理（pre-existing，非本 gap 引入）

- `server/repositories/index_views.py` 既有 ruff 告警（`E402` 模块级 import 块 40-56、`F841` line 1343 `repository` 未用）与 `tests/test_code_search_branch.py` 既有 `F841`（`test_search_no_branch_passes_none` 的 `results` 未用）均在 HEAD 即存在，按 scope boundary 不在本 gap 内修复；本 gap 新增代码自身 lint 干净、`ruff format` 已应用。

## Threat Flags

无新增。本 gap 关闭的正是 22-03-SUMMARY 记录的 `information_disclosure` 旁路（`index_views.py` `_vector_search`→现 `CodeSearchView._search`）。

## Self-Check

- Files: `server/repositories/index_views.py` / `server/tests/test_code_search_branch.py` / `.planning/phases/22-fail-closed/22-GAP-SUMMARY.md` — all FOUND.
- Commit: `56d230553` — FOUND.
- Tests: `tests/test_code_search_branch.py` 6 passed / 2 skipped；与 `tests/services/test_retrieval_exclusion.py` 合跑 15 passed / 2 skipped。
- Lint: `ruff format` 已应用；新增代码 `ruff check` 干净（仅余 pre-existing 告警，见上）。

## Self-Check: PASSED

---
*Phase: 22-fail-closed (gap closure)*
*Completed: 2026-06-14*
