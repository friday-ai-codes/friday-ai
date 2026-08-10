---
phase: 127-semgrep-lsp
reviewed: 2026-08-10T16:55:00Z
depth: standard
files_reviewed: 24
files_reviewed_list:
  - server/services/code_graph/semgrep_scan.py
  - server/services/code_graph/semgrep_enqueue.py
  - server/services/code_graph/semgrep_token.py
  - server/services/code_graph/security_scan_report.py
  - server/services/repo_mirror.py
  - server/codegraph/models.py
  - server/codegraph/migrations/0014_securityfinding.py
  - server/system/models.py
  - server/friday/settings.py
  - server/Dockerfile
  - server/durable/queues.py
  - server/durable/concurrency.py
  - server/durable/tasks.py
  - server/durable/tasks_impl.py
  - server/durable/handlers.py
  - server/workflows/nodes/ai/coding.py
  - server/workflows/services/mr_service.py
  - server/mcp_tools/merge_request_service.py
  - server/codegraph/lsp/orphan_reap.py
  - server/codegraph/lsp/supervisor.py
  - server/codegraph/lsp/volar_pool.py
  - server/codegraph/lsp/__init__.py
  - server/codegraph/management/commands/measure_lsp_baseline.py
  - server/codegraph/management/commands/revisit_impact03_samples.py
findings:
  critical: 2
  major: 3
  minor: 3
  total: 8
status: findings
---

# Phase 127: Code Review Report

**Reviewed:** 2026-08-10T16:55:00Z
**Depth:** standard
**Files Reviewed:** 24
**Status:** findings

## Summary

Phase 127 lands a coherent Semgrep CLI + QUEUE_SCAN + MR `## 安全扫描` surface and LSP orphan/baseline tooling, with solid fail-open and Fernet token patterns. Adversarial review found **two CRITICAL defects** that prevent real scans from hang-points and leave timed-out Semgrep children (with Pro token in env) alive, plus MAJOR gaps around finding uniqueness, Pro honesty for the env escape hatch, and log redaction on hang-point shells.

## Critical Issues

### CR-01: Hang-points enqueue Semgrep with empty `source_sha` / `target_sha`

**File:** `server/workflows/nodes/ai/coding.py:2321-2328`, `server/workflows/nodes/ai/coding.py:2366-2373`
**Also:** `server/mcp_tools/merge_request_service.py:225-231`, `server/workflows/services/mr_service.py:268-274`
**Issue:** All three create-MR hang-points call `enqueue_semgrep_scan` without resolving commit SHAs. Coding and MCP pass `source_sha=""` and `target_sha=""`. `mr_service` passes `source_sha=commit_sha` but still `target_sha=""`. `run_semgrep_scan` immediately fail-opens when either SHA is empty:

```262:264:server/services/code_graph/semgrep_scan.py
        if not source or not target:
            result.error_code = "unavailable"
            return _finish(result, started, actor, repository_id, mr_key, failed=True)
```

Net effect: every production hang-point scan returns `unavailable`, persists nothing, and async patch replaces the pending stub with a permanent failure stub. Diff-aware Semgrep never runs on the intended MR path. Hang-point tests mock enqueue and do not assert SHA presence, so this slipped through.

**Fix:** After MR create (and on dedup reuse), resolve source HEAD SHA for the branch and target SHA for the base/default branch (git platform API or mirror), then pass both into `enqueue_semgrep_scan`. Reject enqueue when either SHA is still empty (log + leave pending stub) rather than enqueueing a guaranteed-fail job.

```python
source_sha = await resolve_branch_sha(client, branch_name)
target_sha = await resolve_branch_sha(client, resolved_target)
if not source_sha or not target_sha:
    logger.warning("enqueue_semgrep_scan_skipped_missing_sha", ...)
else:
    await enqueue_semgrep_scan(..., source_sha=source_sha, target_sha=target_sha, ...)
```

### CR-02: Semgrep subprocess not killed on wall-clock timeout (token-bearing orphan)

**File:** `server/services/code_graph/semgrep_scan.py:116-131`, `server/services/code_graph/semgrep_scan.py:291-311`
**Issue:** `_run_semgrep_cli` uses `asyncio.wait_for(proc.communicate(), timeout=wall_timeout)`. On `TimeoutError`, the child is not `terminate()`/`kill()`’d and remains running. Immediately before spawn, Pro token may be injected:

```291:297:server/services/code_graph/semgrep_scan.py
        env = {**os.environ, "PYTHONUNBUFFERED": "1"}
        ...
        if token:
            env["SEMGREP_APP_TOKEN"] = token
```

Timed-out orphans therefore keep `SEMGREP_APP_TOKEN` in their environment and continue consuming CPU/IO, undermining fail-open timeout and T-127-01 token hygiene. Outer `wait_for` around `_run_semgrep_cli` does not remediate this.

**Fix:** On timeout (and in `finally` if still running), terminate then kill the process, await exit, and clear/never log the token:

```python
proc = await asyncio.create_subprocess_exec(...)
try:
    stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=wall_timeout)
except TimeoutError:
    proc.kill()
    try:
        await proc.wait()
    except Exception:
        pass
    raise
```

## Major Issues

### MJ-01: `SecurityFinding` lacks unique constraint for `update_or_create` lookup

**File:** `server/codegraph/models.py:454-488`, `server/codegraph/migrations/0014_securityfinding.py:64-77`, `server/services/code_graph/semgrep_scan.py:200-214`
**Issue:** Persist path uses `update_or_create(repository=..., fingerprint=..., mr_key=..., defaults=...)`, but the model/migration only add non-unique indexes on `(repository, fingerprint)` / `(repository, mr_key)`. Concurrent scans (or retries) can create duplicate rows; subsequent `update_or_create` then raises `MultipleObjectsReturned`, which is swallowed per-finding — silent persist loss and duplicate ledger rows.

**Fix:** Add `UniqueConstraint(fields=["repository", "fingerprint", "mr_key"], name=...)` (or `unique_together`) in a follow-up migration, then keep `update_or_create` on those fields.

### MJ-02: Pro honesty ignores `SEMGREP_APP_TOKEN` env escape hatch

**File:** `server/services/code_graph/security_scan_report.py:413-418`
**Also contrast:** `server/services/code_graph/semgrep_scan.py:106-113`
**Issue:** Scan injection resolves Pro via SystemSetting **or** `settings.SEMGREP_APP_TOKEN_ENV`, but MR section / patch only checks `get_semgrep_app_token()`:

```python
pro_enabled = bool((await sync_to_async(get_semgrep_app_token)() or "").strip())
```

If operators enable Pro only via the documented env escape hatch, Semgrep runs Pro while the MR section omits the Pro honesty line (D-09 mismatch).

**Fix:** Share one helper (e.g. `_resolve_app_token()` / `is_semgrep_pro_enabled()`) used by both scan and `build_security_scan_section` / `patch_mr_security_scan_section`, still never logging the token value.

### MJ-03: Hang-point failure logs skip secret redaction

**File:** `server/workflows/nodes/ai/coding.py:2275-2280`, `server/workflows/nodes/ai/coding.py:2376-2381`
**Also:** `server/workflows/services/mr_service.py:234-239`, `server/mcp_tools/merge_request_service.py:197-202`
**Issue:** `security_scan_shell_failed` logs `error=str(exc)[:200]` without `redact_secrets_in_text`. Observability spec requires non-bypassable redaction of exception text. Compare with `semgrep_enqueue` / `semgrep_scan`, which redact correctly.

**Fix:**

```python
from common.logging import redact_secrets_in_text
...
error=redact_secrets_in_text(str(exc))[:200],
```

## Minor Issues

### MN-01: `is_security_scan_stub_section` operator-precedence footgun

**File:** `server/services/code_graph/security_scan_report.py:119`
**Issue:**

```python
if "`pending`" in chunk or "pending" in chunk.lower() and "未能生成" in chunk:
```

binds as ``("`pending`" in chunk) or (... and ...)``, so any section containing the literal `` `pending` `` is treated as a replaceable stub even without the Chinese failure phrase. Prefer explicit parentheses / structured markers.

**Fix:** `if ("`pending`" in chunk and "未能生成" in chunk) or (...)`.

### MN-02: Findings load orders severity alphabetically

**File:** `server/services/code_graph/security_scan_report.py:302-309`
**Issue:** `.order_by("severity", ...)` yields ERROR → INFO → WARNING, not the intended ERROR → WARNING → INFO bucket order used by `_render_findings`. Cosmetic but confusing for top-N truncation per severity.

**Fix:** Annotate a severity rank or sort in Python with `_SEVERITY_ORDER` after fetch.

### MN-03: `enqueue_semgrep_scan` missing `*_started` lifecycle event

**File:** `server/services/code_graph/semgrep_enqueue.py:59-68`
**Issue:** Emits `enqueue_semgrep_scan_completed` / `_failed` with `duration_ms`, but no `enqueue_semgrep_scan_started`. Spec prefers started/completed/failed for caller-category lifecycles (scan core already complies).

**Fix:** Log `enqueue_semgrep_scan_started` at entry with the same `category`/`component`/`initiated_by_user_id` fields.

---

## Fix Log

**修复时间：** 2026-08-11T01:00:00Z ｜ **修复者：** Claude (gsd-code-fixer) ｜ **迭代：** 1
**结论：** 8 条全部修复（fixed 8 / skipped 0）。Phase 127 相关套件 33 → 54 passed（新增 21 条用例）。

| ID | 状态 | commit | 说明 |
|----|------|--------|------|
| CR-01 | fixed | `aef17fc8` | 三个建 MR 挂点入队前解析真实两端 sha，解析不出则不入队 |
| CR-02 | fixed | `4118dc37` | 墙钟超时/取消一律 terminate→kill→wait 回收子进程 |
| MJ-01 | fixed | `7a78d580` | 加唯一约束 + 迁移 `0015`（先去重后建约束） |
| MJ-02 | fixed | `795b48ad` | Pro 判定收敛到 `is_semgrep_pro_enabled()` 单一入口 |
| MJ-03 | fixed | `63694b10` | 挂点异常文本全部过 `redact_secrets_in_text` |
| MN-01 | fixed | `5be38c7a` | stub 判定补显式括号 |
| MN-02 | fixed | `5be38c7a` | 按 severity 桶序 annotate 排序 |
| MN-03 | fixed | `17249dc9` | 补 `enqueue_semgrep_scan_started` |

### CR-01（重点：也是 127-VERIFICATION.md 两处缺口的根因）

新增 `server/services/code_graph/semgrep_sha.py` 作为唯一 sha 解析口，优先级 **已知 sha > git 平台 client > 本地 bare mirror**：

- `GitPlatformClient.resolve_branch_sha()` 基类给默认空实现，`GitHubClient`（`repo.get_branch().commit.sha`）与 `GitLabClient`（`project.branches.get().commit["id"]`）分别落地——复用既有 client 抽象，未另造一套。
- `enqueue_semgrep_scan_for_branches()` 作为受保护入口：两端 sha 任一解析不出就**不入队**，只记 `enqueue_semgrep_scan_skipped_missing_sha` 并原样保留 pending stub。
- 三个挂点（`coding.py` / `merge_request_service.py` / `mr_service.py`）与 `attach_security_scan_pending()` 全部切到该入口；`mr_service` 复用现成 `commit_sha` 作 source 端，target 端解析 `resolved_target`。
- 测试补齐了评审指出的漏网点：挂点用例现在**断言入队 payload 的 `source_sha` / `target_sha` 非空**，并覆盖"解析不出 → 跳过入队"与 mirror 兜底路径。

### 附带修复（非评审条目）

`6cfc1f1a`：新模块 `semgrep_sha.py` 事件名补 `code_graph_` 前缀，以满足 `tests/services/code_graph/test_access.py::test_observability_contract` 对**包内**模块的强制契约。

### 遗留观察（本次未处理，建议单独立项）

1. **`test_access.py::test_observability_contract` 在 Phase 127 基线上已是红的**（base `fa2858f0` 即如此）：`semgrep_scan.py` / `semgrep_enqueue.py` / `security_scan_report.py` 发的是无 `code_graph_` 前缀、且 `category="caller"` 的事件，而该契约要求包内模块一律 `code_graph_` 前缀 + `category="sampling"`；`community.py` / `module_summary.py` / `process_trace.py` 等也在违规名单里。属既有系统性欠账，改名会牵动跨 Phase 事件目录，不在本次修复面内。
2. **`tests/mcp_tools/test_mr_impact_report.py::test_mcp_create_mr_failsoft_on_impact_error` 在基线上已失败**：MCP 建 MR 路径无条件追加安全扫描 pending stub，而该用例断言 body 与基线一致。同样是 Phase 127 引入、非本次改动所致。

---

_Reviewed: 2026-08-10T16:55:00Z_
_Reviewer: Claude (gsd-code-reviewer)_
_Depth: standard_
