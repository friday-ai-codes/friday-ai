---
phase: 127-semgrep-lsp
fixed_at: 2026-08-11T01:00:00Z
review_path: .planning/phases/127-semgrep-lsp/127-REVIEW.md
iteration: 1
findings_in_scope: 8
fixed: 8
skipped: 0
status: all_fixed
---

# Phase 127: Code Review Fix Report

**Fixed at:** 2026-08-11T01:00:00Z
**Source review:** `.planning/phases/127-semgrep-lsp/127-REVIEW.md`
**Iteration:** 1

**Summary:**

- Findings in scope: 8（CR-01、CR-02、MJ-01、MJ-02、MJ-03、MN-01、MN-02、MN-03）
- Fixed: 8
- Skipped: 0

**测试结果：** Phase 127 声明套件 + 新增用例 **54 passed**（原 33 条全绿，新增 21 条）。

```
cd server && GALAXY_CACHE_WARM_ON_STARTUP=False GRAPH_BUILD_ORPHAN_RECONCILE_ON_STARTUP=False \
  uv run pytest tests/services/code_graph/test_dockerfile_semgrep_lsp_layers.py \
  tests/codegraph/test_security_finding_model.py tests/services/code_graph/test_semgrep_app_token.py \
  tests/codegraph/test_lsp_defaults_unchanged.py tests/services/code_graph/test_semgrep_scan.py \
  tests/services/code_graph/test_semgrep_enqueue.py tests/services/code_graph/test_security_scan_report.py \
  tests/workflows/test_coding_security_scan.py tests/mcp_tools/test_mr_security_scan.py \
  tests/services/code_graph/test_semgrep_sha.py codegraph/lsp/tests/test_orphan_reap.py \
  tests/codegraph/test_revisit_impact03.py tests/services/code_graph/test_frozen_surface_127.py -q --reuse-db
# => 54 passed
```

冻结面守护 `tests/services/code_graph/test_frozen_surface_127.py` 保持绿色。

## Fixed Issues

### CR-01: Hang-points enqueue Semgrep with empty `source_sha` / `target_sha`

**Files modified:** `server/services/code_graph/semgrep_sha.py`（新增）、`server/services/code_graph/semgrep_enqueue.py`、`server/services/git_platform/base.py`、`server/services/git_platform/github_client.py`、`server/services/git_platform/gitlab_client.py`、`server/workflows/nodes/ai/coding.py`、`server/mcp_tools/merge_request_service.py`、`server/workflows/services/mr_service.py`、`server/services/code_graph/security_scan_report.py`、`server/tests/services/code_graph/test_semgrep_sha.py`（新增）、`server/tests/services/code_graph/test_semgrep_enqueue.py`、`server/tests/workflows/test_coding_security_scan.py`、`server/tests/mcp_tools/test_mr_security_scan.py`
**Commit:** `aef17fc8`（附带 `6cfc1f1a` 补事件名前缀）
**Applied fix:**

1. 新增 `semgrep_sha.py` 作为唯一 sha 解析口，优先级 **已知 sha > git 平台 client > 本地 bare mirror**，两级失败都只记结构化日志、不抛。
2. `GitPlatformClient.resolve_branch_sha()` 基类默认返回空串；`GitHubClient` 用 `repo.get_branch(...).commit.sha`，`GitLabClient` 用 `project.branches.get(...).commit["id"]`——复用既有 client 抽象，未另起一套。
3. 新增受保护入口 `enqueue_semgrep_scan_for_branches()`：解析两端 sha，任一为空即**放弃入队**，记 `enqueue_semgrep_scan_skipped_missing_sha`，pending stub 原样留在 MR 描述里。
4. 三个挂点与 `attach_security_scan_pending()` 全部改走该入口；`mr_service` 复用现成 `commit_sha` 作 source 端。
5. 测试补上评审点出的漏网判据：挂点用例现在断言入队 payload 两端 sha 非空，另覆盖"解析不出 → 跳过"与 mirror 兜底。

**结论：** 建 MR 路径现在带真实 sha 入队，`run_semgrep_scan` 不再在入口早退 `unavailable`。

### CR-02: Semgrep subprocess not killed on wall-clock timeout

**Files modified:** `server/services/code_graph/semgrep_scan.py`、`server/tests/services/code_graph/test_semgrep_scan.py`
**Commit:** `4118dc37`
**Applied fix:** `_run_semgrep_cli` 收成单一 `wait_for` owner，`finally` 里统一 `_terminate_process()`（terminate → 等 → kill → `wait()` 收尸），超时/取消/任意异常都走同一路径；去掉外层冗余 `wait_for`。新增用例 spawn `sleep` 并超时，断言进程确实被回收而非留下带 `SEMGREP_APP_TOKEN` 的孤儿。

### MJ-01: `SecurityFinding` lacks unique constraint for `update_or_create` lookup

**Files modified:** `server/codegraph/models.py`、`server/codegraph/migrations/0015_securityfinding_unique_fingerprint.py`（新增）、`server/tests/codegraph/test_security_finding_model.py`
**Commit:** `7a78d580`
**Applied fix:** 模型 Meta 加 `UniqueConstraint(["repository", "fingerprint", "mr_key"])`。迁移 `0015` 先按该三元组去重（保留 `updated_at` 最新一行）再建约束——直接建约束会在已有重复数据的库上炸掉；同时剔掉 `makemigrations` 顺带生成的无关索引改名。

### MJ-02: Pro honesty ignores `SEMGREP_APP_TOKEN` env escape hatch

**Files modified:** `server/services/code_graph/semgrep_token.py`、`server/services/code_graph/semgrep_scan.py`、`server/services/code_graph/security_scan_report.py`、`server/tests/services/code_graph/test_semgrep_app_token.py`
**Commit:** `795b48ad`
**Applied fix:** `semgrep_token.py` 提供 `resolve_semgrep_app_token()` / `is_semgrep_pro_enabled()` 作单一事实源（SystemSetting 优先，其次 `settings.SEMGREP_APP_TOKEN_ENV`）；扫描注入与 MR 段落生成都改调它，token 值仍不落日志。

### MJ-03: Hang-point failure logs skip secret redaction

**Files modified:** `server/workflows/nodes/ai/coding.py`、`server/workflows/services/mr_service.py`、`server/mcp_tools/merge_request_service.py`、`server/tests/workflows/test_coding_security_scan.py`
**Commit:** `63694b10`
**Applied fix:** 三处挂点的 `security_scan_shell_failed` / `impact_report_shell_failed` 全部改为 `error=redact_secrets_in_text(str(exc))[:200]`。新增静态守护用例：断言这些模块里不再出现未脱敏的 `str(exc)` 直接入日志。

### MN-01: `is_security_scan_stub_section` operator-precedence footgun

**Files modified:** `server/services/code_graph/security_scan_report.py`、`server/tests/services/code_graph/test_security_scan_report.py`
**Commit:** `5be38c7a`
**Applied fix:** 补显式括号，`pending` 标记必须与"未能生成"同现才判定为可替换 stub。新增用例：正文里恰好提到 `pending` 的**已完成**段落不再被误判覆盖。

### MN-02: Findings load orders severity alphabetically

**Files modified:** `server/services/code_graph/security_scan_report.py`、`server/tests/services/code_graph/test_security_scan_report.py`
**Commit:** `5be38c7a`
**Applied fix:** `_load_findings_for_mr` 用 `Case/When` annotate 出 `severity_rank` 再排序，得到 ERROR → WARNING → INFO 桶序，与 `_render_findings` 的截断预期一致。

> MN-01 与 MN-02 同文件同函数族、且都由同一批用例覆盖，合并为一个 commit。

### MN-03: `enqueue_semgrep_scan` missing `*_started` lifecycle event

**Files modified:** `server/services/code_graph/semgrep_enqueue.py`、`server/tests/services/code_graph/test_semgrep_enqueue.py`
**Commit:** `17249dc9`
**Applied fix:** 入口补 `enqueue_semgrep_scan_started`，`category` / `component` / `initiated_by_user_id` 与同族 completed/failed 一致；新增用例断言 started/completed 成对出现。

## Skipped Issues

无。

## 遗留观察（基线既有问题，非本次改动引入）

1. `tests/services/code_graph/test_access.py::test_observability_contract` 在 base `fa2858f0` 上已失败：Phase 127 的包内模块发的是无 `code_graph_` 前缀、`category="caller"` 的事件，与该契约冲突；`community.py` / `module_summary.py` / `process_trace.py` 等也在违规名单内。本次只保证**新增**模块 `semgrep_sha.py` 合规，未连带改名既有事件（会牵动跨 Phase 事件目录）。
2. `tests/mcp_tools/test_mr_impact_report.py::test_mcp_create_mr_failsoft_on_impact_error` 在基线上已失败：MCP 建 MR 路径无条件追加安全扫描 pending stub，与该用例的 body 断言冲突。
3. `tests/workflows/test_work_item_execution.py`、`tests/mcp_tools/test_schema_snapshot.py`、`test_skills_snapshot_guard.py`、`test_repo_router_v2_degraded.py` 的失败均在本次未触碰的模块，属既有问题。

---

_Fixed: 2026-08-11T01:00:00Z_
_Fixer: Claude (gsd-code-fixer)_
_Iteration: 1_
