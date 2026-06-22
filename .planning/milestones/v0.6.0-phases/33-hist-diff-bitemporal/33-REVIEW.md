---
phase: 33-hist-diff-bitemporal
reviewed: 2026-06-15T13:23:50Z
depth: deep
files_reviewed: 8
files_reviewed_list:
  - server/services/git_platform/base.py
  - server/services/git_platform/models.py
  - server/services/git_platform/gitlab_client.py
  - server/services/git_platform/github_client.py
  - server/knowledge/diff_archive.py
  - server/knowledge/modifies_chunk.py
  - server/knowledge/graph_store.py
  - server/services/indexer.py
  - server/delivery/services/ingest_orchestrator.py
  - server/tests/knowledge/test_modifies_chunk_reconcile.py
findings:
  critical: 1
  warning: 2
  info: 1
  total: 4
status: clean
resolved: 2026-06-15T13:23:50Z
resolution: |
  全部 4 项已修复（fix(33): CR-01 / WR-01 / WR-02 三笔原子提交）：
  - CR-01：两 git client 改用 datetime.timezone.utc 归一 naive merged_at；
    新增 tests/services/test_git_platform_metadata.py 覆盖真实归一化路径。
  - WR-01：aresolve_mr_commit_anchor 追加 merged_at is not None 判据，
    未合并 open PR 的瞬态 test-merge sha 不再被当历史锚。
  - WR-02：bitemporal_as_of_q 增 business_only 开关 + chunk_in_edges 透传，
    amodifies_chunk_edges as-of 走纯业务时间线，回填历史边当年可见。
  - IN-01：GitHub client docstring 已更新（PyGithub >=2.0 返回 aware）。
---

# Phase 33: Code Review Report

**Reviewed:** 2026-06-15T13:23:50Z
**Depth:** deep
**Files Reviewed:** 8 source + tests
**Status:** issues_found

## Summary

Phase 33 commit-anchoring + bi-temporal invalidation 总体实现扎实，核心不变量基本守住：
失效唯一经 `graph_store.invalidate_edge` 收口（置位不删、仅 `invalid_at IS NULL` 写一次、
不覆盖原值），对账逐边 `try/except` best-effort 且 indexer 钩子整段吞异常不阻断索引终态，
钩子正确 gated 在 base-only 路径（`if not branch`），双信号过期判定（chunk 不存在 ∪
content_hash 漂移）+ 缺指纹保守，as-of 当前视图正确排除已失效边，新 metadata 抓取无明显
token 泄漏（仅记 mr_id/repository_id）。WR-02 修复正确——无合成 commit_sha，anchor 不可用
时如实 `skipped`。

但发现 **1 个 BLOCKER**（已确认运行时触发）：新增的 merged_at naive→aware 归一化用了
Django 5.0 起已删除的 `django.utils.timezone.utc`，在本仓库实际运行的 Django 6.0.1 下必抛
`AttributeError`，使 HDIFF-01 commit 锚定在 naive 时间戳路径上静默失效。另有 2 个 WARNING
（未合并 PR 的 test-merge SHA 可被当作锚；as-of 历史查询混入系统时间线 `created_at` 谓词，
回填历史边在其"当年"不可见）。

## Critical Issues

### CR-01: `dj_timezone.utc` 已被 Django 移除 — merged_at 归一化路径必抛 AttributeError

**File:** `server/services/git_platform/github_client.py:282`，`server/services/git_platform/gitlab_client.py:286`
**Issue:**
两处新增代码用 `dj_timezone.make_aware(merged_at, dj_timezone.utc)` 把 naive `merged_at`
归一为 aware。但 `django.utils.timezone.utc` 自 Django 5.0 起已删除（4.0 起 deprecated），
本仓库实际运行 Django **6.0.1**（已验证 `hasattr(django.utils.timezone, "utc") == False`，
且 `make_aware(dt, dj_timezone.utc)` 实测抛 `AttributeError: module 'django.utils.timezone'
has no attribute 'utc'`）。

后果：任何返回 **naive** `merged_at` 的 MR/PR 都会命中 `is_naive` 分支 →
`AttributeError` → 被外层 `except Exception` 兜住 → `get_merge_request_metadata` 返回
`success=False` → `aresolve_mr_commit_anchor` 返回 None → 一键摄取该 MR 直接 `skipped`。
即 HDIFF-01 commit 锚定在 naive 时间戳路径上 **永远无法成功**，而作者恰恰是为 GitHub naive
datetime 专门写的这段（docstring 明示「PyGithub 返回 naive UTC datetime」）。归一化代码非但不
归一，反而保证失败。当前环境 PyGithub 2.8.1 / GitLab ISO8601 多返回 aware（分支多不命中）
故未在真实场景暴露，但这是引用已删除 API 的确定性缺陷，且测试用 fake client 绕过了真实客户端
（`test_diff_archive.py` 的 anchor 测试不覆盖此路径）。

**Fix:**
```python
from datetime import timezone as dt_timezone
# ...
if merged_at is not None and dj_timezone.is_naive(merged_at):
    merged_at = dj_timezone.make_aware(merged_at, dt_timezone.utc)
```
（两个客户端同改；或直接 `merged_at.replace(tzinfo=dt_timezone.utc)`。）

## Warnings

### WR-01: anchor 未校验"已合并"——未合并 GitHub PR 的 test-merge SHA 会被当历史锚

**File:** `server/knowledge/diff_archive.py:573`（`aresolve_mr_commit_anchor`）
**Issue:**
降级判定仅 `if not result.success or not result.merge_commit_sha`，未检查 `merged_at`。
GitHub 对**未合并但可合并**的 open PR 会返回一个 *test-merge* `merge_commit_sha`（非空、瞬态、
base 演进即变），且 `merged_at=None`。此时 anchor 返回成功 → `ingest_orchestrator` 取
`event_time = anchor.merged_at or timezone.now()` = `now()` → 以瞬态 test-merge SHA + 
`valid_at=now()` 冻结一份"伪历史快照"，正是 WR-02 / T-33-03 明令避免的（"绝不静默沿用合成
commit_sha"、"避免伪历史快照污染对账"）。GitLab 未合并 MR `merge_commit_sha` 为空故不受影响，
此缺口为 GitHub + open-PR 专属。
**Fix:** anchor helper 在 `not result.merge_commit_sha` 之外追加 `or result.merged_at is None`
判定（或令 client 仅在真正 merged 时回填 `merge_commit_sha`），未合并即 `return None` →
如实 `skipped`。

### WR-02: as-of 历史查询混入系统时间线 `created_at`——回填历史边在其"当年"不可见

**File:** `server/knowledge/modifies_chunk.py:66` + `server/knowledge/graph_store.py:94`
**Issue:**
`amodifies_chunk_edges(as_of=...)` 复用 `bitemporal_as_of_q`，其谓词除业务时间线
（`valid_at<=as_of<invalid_at`）外还叠加系统时间线 `created_at<=as_of`。但一键摄取把
`valid_at=merged_at`（可能很久以前）而 `created_at=auto_now_add`（=摄取的当下）。于是对一个
"两年前合并、今天才摄取"的 MR，用其**合并那年**的 `as_of` 查询会因 `created_at(今天) > as_of`
被过滤掉——返回空，与 CONTEXT 成功标准3「历史 as_of 见当年成立的边」相悖。该谓词与
neighbors/traverse 一致（有意复用），但 CONTEXT 定义的 as-of 仅业务时间线
（`valid_at<=as_of<invalid_at`），二者语义不一致；现有 reconcile 测试 `as_of` 均 >= `created_at`
故未覆盖此缺口。
**Fix:** 若 as-of 语义应为纯业务时间线，`amodifies_chunk_edges` 走独立谓词
（`valid_at<=as_of AND (invalid_at IS NULL OR as_of<invalid_at)`，去掉 `created_at` 约束）；
若有意保留系统时间线交集，应在 helper docstring/CONTEXT 显式记录回填边的可见性边界，并补一条
`as_of < created_at` 的测试以固化预期。

## Info

### IN-01: GitHub client docstring 关于 merged_at 时区的描述已过时

**File:** `server/services/git_platform/github_client.py:267`
**Issue:** docstring 称「PyGithub 返回 naive UTC datetime」，但实际依赖的 PyGithub 2.8.1 自
2.0 起返回 timezone-aware datetime；`is_naive` 短路使其无害，但描述误导后续维护者。
**Fix:** 更新为「PyGithub ≥2.0 返回 aware datetime；保留 naive→aware 归一作为防线」。

---

_Reviewed: 2026-06-15T13:23:50Z_
_Reviewer: Claude (gsd-code-reviewer)_
_Depth: deep_
