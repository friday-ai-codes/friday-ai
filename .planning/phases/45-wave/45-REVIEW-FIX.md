---
phase: 45-wave
fixed_at: 2026-06-16T23:10:00Z
review_path: .planning/phases/45-wave/45-REVIEW.md
iteration: 1
findings_in_scope: 5
fixed: 5
skipped: 0
status: all_fixed
---

# Phase 45: Code Review Fix Report — 上游产物提取 + 注入下游 wave

**Fixed at:** 2026-06-16T23:10:00Z
**Source review:** .planning/phases/45-wave/45-REVIEW.md
**Iteration:** 1

**Summary:**
- Findings in scope: 5（2 medium + 3 low；无 critical/high）
- Fixed: 5
- Skipped: 0

> 说明：本轮修复在隔离 worktree 中执行；一次中断的前序运行已落下 4 个修复 commit + 一个测试 commit，
> 本轮校验其正确性（全部命中 5 项发现、零回归与不变量完好）、跑通验证门、并 fast-forward 合入 `main`。

## Fixed Issues

### MD-01 + MD-02: 注入渲染未转义半可信路径 / 文档声称的注入端截断不存在

**Files modified:** `server/services/plan_orchestration/artifact_injection.py`
**Commit:** 4b0337ac
**Applied fix:**
- 新增 `_safe_inline(value, max_len=200)`：把半可信值的反引号替换为视觉近似安全字符 `ʼ`、
  换行（`\n`/`\r`）压成空格、并截断到 `_MAX_INLINE_LEN=200`，确定性无副作用，确保渲染为惰性
  **数据**而非指令（MD-01，T-45-05/06/07）。
- `render_upstream_artifacts_section` 中仓名 / 分支 / MR / 每条契约文件路径全部过 `_safe_inline`。
- 新增 `_MAX_FILES_PER_BUCKET=50` 每桶上限，超出折叠为 `… (+M more)` 省略行，兑现
  `artifact_extraction.py` docstring「无界展开由注入端截断」承诺（MD-02，T-45-02）；同步更新
  render docstring 使其与实际行为一致。
- **零回归保持**：消毒 / 截断逻辑全部位于 `for a in artifacts` 循环体内，`render([])` 仍返回 `""`，
  空段守卫 `if upstream_section:` 路径字节级不变。

### LW-02: `available` 缺省值过宽松——改为 fail-closed

**Files modified:** `server/services/plan_orchestration/artifact_injection.py`
**Commit:** 6bb4dbe0
**Applied fix:** `acollect_upstream_artifacts` 中 `artifacts.get("available", True)` →
`artifacts.get("available", False)`，缺失 / 未知 `available` 即视为不可用（与提取端占位
`{"available": False}` 保守语义对齐）；同步更新 docstring。

### LW-01: 注入收集 try/except 粒度过粗——收进循环逐仓 fail-soft

**Files modified:** `server/workflows/nodes/ai/coding.py`
**Commit:** 3e3220b4
**Applied fix:** `_dispatch_next_wave` 中把整段 `try/except` 收进 `for repo_id, task` 循环体内，
单仓 `acollect_upstream_artifacts` 失败仅 `upstream_by_repo[repo_id] = []` 并记 `repo_id` + error，
不再清空全 wave 已收集产物；保持 fail-soft（warning，绝不 raise），import 上移出循环。

### LW-03: `TaskResult` 选取无 ordering——加确定性排序

**Files modified:** `server/services/plan_orchestration/wave_progression.py`
**Commit:** 37f01d5d
**Applied fix:** `_backfill_running_terminal` 中
`TaskResult.objects.filter(session=sess).afirst()` →
`...filter(session=sess).order_by("-created_at").afirst()`，多 TaskResult 时选取最新优先、确定。

### 测试覆盖（MD-01 / MD-02 新行为）

**Files modified:** `server/tests/services/plan_orchestration/test_artifact_injection.py`
**Commit:** 2d6b1821
**Applied fix:** 新增 5 个测试：
- `test_malicious_path_sanitized_no_backtick_or_newline_breakout`（反引号/换行越权防护）
- `test_malicious_repo_name_and_branch_sanitized`（仓名/分支消毒）
- `test_long_path_truncated_to_max_inline_len`（单条长度截断到 200）
- `test_bucket_truncated_with_more_elision`（每桶 50 上限 + `… (+10 more)`）
- `test_bucket_at_limit_no_elision`（恰好等于上限边界，无省略行）

## Skipped Issues

None — 全部 5 项发现均已修复。

## Verification Results

- `cd server && uv run pytest tests/services/plan_orchestration tests/delivery tests/test_coding_wave.py tests/test_coding_node.py -x` → **365 passed, 1 xfailed**（xfail 为既存、与本修复无关）。
- `cd server && uv run ruff check`（4 个改动文件）→ **All checks passed!**
- 零回归不变量（INV-6 单写 / fail-soft / async ORM / 空段字节级一致）经核对全部完好；现有
  `test_coding_node.py::TestBuildCodingPromptUpstreamInjection` 的 `==` 字节级断言仍通过。

---

_Fixed: 2026-06-16T23:10:00Z_
_Fixer: Claude (gsd-code-fixer)_
_Iteration: 1_
