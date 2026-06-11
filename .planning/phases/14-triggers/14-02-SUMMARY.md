---
phase: 14-triggers
plan: 02
subsystem: services
tags: [kmod-05, ingest-02, git-platform, branch-diff, skip-pr]
requires:
  - GitPlatformClient 既有 get_merge_request_diff / compare_branches 契约（MRDiffResult 复用）
provides:
  - GitPlatformClient.get_branch_diff 抽象方法（OQ-1 定案，漏实现即实例化 TypeError）
  - GitLab 实现：repository_compare(from_=target, to=source) 包装，diffs[].diff 自带文本
  - GitHub 实现：repo.compare + file.patch 包装，patch 缺失 → truncated 响亮降级（A1）
  - base.truncate_diff_lines 共用截断 helper（双客户端共享，避免截断逻辑三份复制）
affects:
  - 14-03 DiffArchiver（skip-PR 路径统一消费 MRDiffResult，不区分 MR diff 与分支 diff）
tech-stack:
  added: []
  patterns:
    - 分支全量 diff 与 MR diff 统一出口 MRDiffResult（不新增 DTO）
    - 平台异常 → MRDiffResult(success=False, error=...) 不上抛（与 get_merge_request_diff 同语义）
key-files:
  created:
    - server/tests/test_branch_diff.py
  modified:
    - server/services/git_platform/base.py
    - server/services/git_platform/gitlab_client.py
    - server/services/git_platform/github_client.py
decisions:
  - 截断 helper truncate_diff_lines 放 base.py 模块级（plan 允许"共用模块"，双客户端 import 共享）；既有 get_merge_request_diff 内联截断不动（零回归）
  - base.py 抽象化分两步：Task 1 先以 NotImplementedError 占位，Task 2 双实现齐备后转 @abstractmethod——避免抽象化瞬间令 GitHubClient 不可实例化打破 test_compare_branches
  - GitHub patch 缺失（None/空串）一律降级空 diff + truncated=True，不本地 git 兜底（范围克制）
metrics:
  duration: ~8min
  tasks: 2
  files: 4
completed: 2026-06-12
---

# Phase 14 Plan 02: GitPlatformClient.get_branch_diff 双平台实现 Summary

GitLab（repository_compare）与 GitHub（compare + file.patch）双客户端落地 `get_branch_diff(source, target) -> MRDiffResult` 抽象方法，skip-PR 路径全量 diff 统一兜底来源成立，14-03 DiffArchiver 可不区分来源消费 MRDiffResult。

## Tasks Completed

| Task | Name | Commits | Key Files |
|------|------|---------|-----------|
| 1 | base 抽象方法 + GitLab 实现（TDD） | fa305303 (RED) / a51a5004 (GREEN) | base.py, gitlab_client.py, test_branch_diff.py |
| 2 | GitHub 实现（compare + file.patch，patch 缺失降级）（TDD） | 4dc8382a (RED) / 4ac85b86 (GREEN) | github_client.py, base.py（转 abstract）, test_branch_diff.py |

## 交付物对照（must_haves）

- ✅ 双客户端均实现 `get_branch_diff(source, target) -> MRDiffResult`，返回含 per-file unified diff 文本的文件列表（test_success 双侧断言 diff 文本逐字一致）
- ✅ max_files/max_diff_lines 超限或 GitHub patch 缺失 → truncated=True 响亮标记，不静默丢失（双侧截断用例 + patch 缺失用例钉死；截断尾部追加 "[diff truncated]"，与 get_merge_request_diff 同款语义）
- ✅ 平台 API 异常 → MRDiffResult(success=False, error 非空) 不上抛（GitlabError / GithubException 双侧用例）
- ✅ base.py 抽象方法强制双子类实现（最终态 @abstractmethod，漏实现即实例化 TypeError）
- ✅ 既有 get_merge_request_diff / compare_branches 行为零变更（test_compare_branches 13 用例 + test_batch_pr 全绿）

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] base.py 抽象化分两步落地**
- **Found during:** Task 1
- **Issue:** Task 1 直接加 @abstractmethod 会令尚未实现的 GitHubClient 实例化即 TypeError，打破 Task 1 验收项 "test_compare_branches.py 零回归"（该文件 TestGitHubCompare 实例化 GitHubClient）
- **Fix:** Task 1 GREEN 以 NotImplementedError 占位声明；Task 2 GREEN（双实现齐备）转 @abstractmethod。最终态与 must_haves 完全一致；Task 2 因此追加修改 base.py（不在该任务 files 列表）
- **Commits:** a51a5004 / 4ac85b86

**2. [Rule 1 - Format] ruff format 顺带规范 gitlab_client.py 既有 3 处多行表达式**
- **Found during:** Task 1
- **Issue:** gitlab_client.py 既有代码不完全符合 ruff format（多行 lambda/集合推导可收单行）
- **Fix:** 项目以 ruff format 为准，纯格式零行为变化，随 Task 1 提交
- **Commit:** a51a5004

其余按计划逐字执行。

## Known Stubs

无。

## Verification

- `uv run pytest tests/test_branch_diff.py tests/test_compare_branches.py tests/test_batch_pr.py` → 35 passed（新增 9 用例 + 相邻宿主零回归）
- `uv run pytest tests/knowledge/` → 136 passed（采样回归零失败；合计 171 passed）
- `uv run ruff check services/git_platform/ tests/test_branch_diff.py` + `ruff format --check` → 全部通过
- 验收锚点：`rg -c "get_branch_diff" base.py` == 1；`rg -c "def get_branch_diff"` gitlab/github 各 == 1；github_client.py 新增代码 `FRIDAY_|os.environ` 零命中（凭证仍由构造注入）

## Self-Check: PASSED

- FOUND: server/tests/test_branch_diff.py
- FOUND: commit fa305303 / a51a5004 / 4dc8382a / 4ac85b86
- tests green（171 passed）/ ruff check + format clean
