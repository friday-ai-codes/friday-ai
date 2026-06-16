---
phase: 42-chat
fixed_at: 2026-06-16T14:06:00Z
review_path: .planning/phases/42-chat/42-REVIEW.md
iteration: 1
findings_in_scope: 3
fixed: 3
skipped: 0
status: all_fixed
---

# Phase 42: Code Review Fix Report

**Fixed at:** 2026-06-16T14:06:00Z
**Source review:** .planning/phases/42-chat/42-REVIEW.md
**Iteration:** 1

**Summary:**
- Findings in scope: 3
- Fixed: 3
- Skipped: 0

## Fixed Issues

### WR-02: `start_plan_research` 未守护空白 `requirement_text`

**Files modified:** `server/agents/tools/plan_research_tools.py`, `server/tests/agents/test_start_plan_research_tool.py`
**Commit:** e69334422
**Applied fix:** 在工具函数体最前加 fail-closed 守护——空 / 纯空白 `requirement_text` →
`ToolResult(success=False, error="缺少需求文本（requirement_text）")`，不建 session、不驱动
engine（与工作流节点 `_create_session` missing_requirement 对称）。新增参数化测试
`test_start_plan_research_blank_requirement_fail_closed`（`""` / `"   "` / `"\n\t "`），断言
engine 未构建且未新建 `PlanSession`。

### WR-01: chat fire-and-forget 调研挂起无 resume 消费者 + placeholder 过度承诺

**Files modified:** `server/agents/tools/plan_research_tools.py`, `.planning/phases/42-chat/deferred-items.md`
**Commit:** 9350c576e
**Applied fix:** 采用 review 方案 1（最小、与 deferred 一致，**不**实现完整 chat resume 消费者）。
将 researching 在途的 `placeholder` 文案与工具 `description` 如实化——不再声称「调研完成后自动
继续融合」，改为陈述「已发起 + 调研容器在途 + 自动回流后续里程碑接入，当前不会自动继续」（含
session id + status）。在 `deferred-items.md` 显式登记 chat 入口 plan_research 容器完成 → 重新
驱动 engine / resume chat graph 的接线缺口（callbacks 对 plan_research 短路两条 resume 通路；
E2E resume 沿用 Phase 39/40/41 既有 deferred）。同步路径（routing low → 直通 merge → done）的
成功文案未涉及该缺口，保持不变。

### IN-01: `_filter_repos_in_space` 显式仓库全部被过滤时静默回退

**Files modified:** `server/agents/tools/plan_research_tools.py`
**Commit:** 9d9dd6fd1
**Applied fix:** 在 `_filter_repos_in_space` 过滤结果为空（`kept` 为空）且 `include_repos` 非空时
记一条醒目 `warning` 日志 `start_plan_research_include_repos_all_filtered`（含 `requested` /
`kept` 计数），区分「未传 include_repos」与「显式限定全部失效静默回退自动路由」。保持 best-effort
不阻断语义不变。

## Skipped Issues

None — all in-scope findings were fixed.

---

_Fixed: 2026-06-16T14:06:00Z_
_Fixer: Claude (gsd-code-fixer)_
_Iteration: 1_
