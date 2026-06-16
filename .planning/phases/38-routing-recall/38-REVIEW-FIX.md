---
phase: 38-routing-recall
fixed_at: 2026-06-16T09:31:00Z
review_path: .planning/phases/38-routing-recall/38-REVIEW.md
iteration: 1
findings_in_scope: 3
fixed: 3
skipped: 0
accepted: 2
status: all_fixed
---

# Phase 38: Code Review Fix Report

**Fixed at:** 2026-06-16T09:31:00Z
**Source review:** .planning/phases/38-routing-recall/38-REVIEW.md
**Iteration:** 1

**Summary:**
- Findings in scope: 3（CR-01, WR-01, IN-01）
- Fixed: 3
- Skipped: 0
- Accepted (intentionally not fixed): 2（WR-02, IN-02）

## Fixed Issues

### CR-01: 召回 adapter 在 async 上下文懒加载 `session.created_by` FK（BLOCKER）

**Files modified:** `server/services/plan_orchestration/recall_adapter.py`, `server/tests/services/test_recall_adapter.py`
**Commit:** 56f5e11d6
**Applied fix:**
- 新增 `@sync_to_async _resolve_actor(self, session)` 实例方法（镜像 `RepoRouterV2Adapter._project_repository_ids` 的 async ORM 范式）：`created_by_id` 为空时 Django 短路返回 None（不查库、不伪造 actor），非空则同步 ORM 取 User，避免 async 事件循环内懒加载 FK 触发 `SynchronousOnlyOperation`。
- `user = await self._resolve_actor(session)` 移入 best-effort `try/except` 内 —— actor 解析任何失败均降级为空召回（守 RECALL-01：召回失败返回空、绝不冒泡破坏编排）。
- 补测 `test_created_by_real_user_loads_actor_without_sync_error`：构造真实 `created_by` 用户、经 `aget`（**不** `select_related`）重载强制走 FK 加载路径，断言不抛 `SynchronousOnlyOperation` 且 actor 按 pk 正确透传。原 `created_by=None` fail-closed 用例保留并仍通过。

### WR-01: `recall_context` 字段 `default=dict` 与实际持久化 `list` 类型漂移

**Files modified:** `server/delivery/models/plan_session.py`, `server/delivery/migrations/0012_alter_plansession_recall_context.py`
**Commit:** 13834431e
**Applied fix:**
- `recall_context` 改 `models.JSONField(default=list, blank=True)`，空态与有值态顶层统一为 `list`，消除下游消费类型漂移。
- 生成 delivery 迁移 `0012_alter_plansession_recall_context`（`AlterField`，依赖 0011）。
- `routing` 仍为 `default=dict`（确为 dict，不动）。无代码/测试依赖原 dict 默认（已全仓核验）。
- `makemigrations --check --dry-run` → `No changes detected`（clean）。

### IN-01: `engine._route` 缺 `isinstance(result, dict)` 防御（与 `_recall` 不对称）

**Files modified:** `server/services/plan_orchestration/engine.py`
**Commit:** fd2c430bb
**Applied fix:**
- `_route` 改为 `candidates = (result.get("candidates") or []) if isinstance(result, dict) else []`，再据此构造 §15 trace —— 与 `_recall` 防御范式对称，杜绝「routing 已落库转移后构造 trace 崩 → 会话不一致 failed」。
- 更新 docstring 说明该防御与 `_recall` 对称。
- 源码守护 `test_engine_does_not_write_status_directly` 仍 green（未引入 `.status=` 直写）。

## Accepted Issues（经评审接受，不修）

### WR-02: 路由候选仓收窄召回静默放宽（精度问题，非越权）

**File:** `server/services/plan_orchestration/recall_adapter.py:54-57`
**Reason:** 非越权泄漏 —— 项目维 scoping 仍由 `allowed_projects` 严格守住，仅在用户已授权范围内放宽精度。下游 `recall_similar_chunks`/`resolve_allowed_repository_ids` 属 Phase 15 既有逻辑（本 phase 未改）。留待 Phase 39 消费端结合 routing 候选仓二次过滤命中。

### IN-02: engine 调 `self.session_service._emit_event(...)` 私有方法（封装气味）

**File:** `server/services/plan_orchestration/engine.py:133, 154`
**Reason:** Phase 36 既定钩子（计划明确如此）。留待 Phase 41 接真实事件 sink 时统一暴露公开 `emit_event` API。

## Verification

- 受影响测试：`tests/delivery` + `tests/services/{test_recall_adapter,test_repo_router_adapter,test_plan_orchestration_engine}.py` → **287 passed**（新增 1 用例，原 286 → 287，无回归）。
- 纯净度守护：`test_engine_does_not_write_status_directly`、`test_inv6_no_bypass_plan_session_write` 均 green。
- 迁移：`makemigrations --check --dry-run` clean（0012 AlterField 后无残余漂移）。
- Lint：`ruff check` 三个改动源文件全过（line 100，zh-CN docstrings）。

---

_Fixed: 2026-06-16T09:31:00Z_
_Fixer: Claude (gsd-code-fixer)_
_Iteration: 1_
