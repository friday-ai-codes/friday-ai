---
phase: 38-routing-recall
reviewed: 2026-06-16T09:24:00Z
depth: standard
files_reviewed: 7
files_reviewed_list:
  - server/services/plan_orchestration/repo_router_adapter.py
  - server/services/plan_orchestration/recall_adapter.py
  - server/services/plan_orchestration/engine.py
  - server/services/plan_orchestration/__init__.py
  - server/delivery/models/plan_session.py
  - server/delivery/services/plan_session_service.py
  - server/delivery/migrations/0011_plansession_routing_recall_created_by.py
findings:
  critical: 1
  warning: 2
  info: 2
  total: 5
status: resolved
resolution:
  fixed: [CR-01, WR-01, IN-01]
  accepted: [WR-02, IN-02]
  fixed_at: 2026-06-16T09:31:00Z
  fix_report: 38-REVIEW-FIX.md
---

# Phase 38: Code Review Report

**Reviewed:** 2026-06-16T09:24:00Z
**Depth:** standard
**Files Reviewed:** 7
**Status:** resolved（CR-01/WR-01/IN-01 已修；WR-02/IN-02 经评审接受，见 38-REVIEW-FIX.md）

## Summary

Phase 38 把编排 `routing`/`recalling` 两段骨架替换为复用 `RepoRouterV2` + `DeliveryKnowledgeSearchService` 的真实 adapter，并扩展 `PlanSession`（routing/recall_context/created_by）+ 0011 迁移 + `PlanSessionService` 单一写入入口。

整体接线质量高，且关键安全/契约点经核验**正确**：

- **DOMAIN §14 转移正确**：`_ALLOWED` 中 `routing→recalling`（routed）、`recalling→clarifying`（recalled）逐字对齐 §14。
- **DOMAIN §15 事件 payload 正确**：`repo.routing` = `{candidates:[{repo_id, confidence}]}`（不含 reasoning，INV-5 守）；`knowledge.recalling` = `{query, kinds, hits 计数}`（不外泄命中明细）。
- **INV-6 守住**：routing/recall_context/status 仅经 `transition` 落库；engine 无 `.status=` 直写（purity 守护仍有效）。
- **召回权限 scoping 不越权**：`repository_ids`（路由候选仓）经 `resolve_allowed_repository_ids` 与用户可见仓 **求交**，非子集 → `[]`，**绝不放宽**到用户授权范围之外；项目维 `resolve_allowed_project_ids(None)` 仅返回用户成员项目，候选仓收窄不绕过用户 scoping。
- **created_by=None 真 fail-closed**：adapter 直接透传 `user=None`（不伪造 actor），`search_similar` 因 `allowed_projects==[]` 提前返回 `[]` → 空召回，不泄漏。
- **DTO 字段映射正确**：`_map_hit` 使用 `entity_kind`（EntityMetadata 实际属性），非误用 `kind`，无静默空值 bug。
- **RepoRouterV2.route 为 classmethod**，候选字段 `repo_id/repo_name/confidence` + `router_version/auto_selected` 与 adapter 映射一致。

但发现 **1 个 BLOCKER**（召回 actor 的 async ORM 懒加载会崩溃认证路径）、2 个 WARNING、2 个 INFO。

## Critical Issues

### CR-01: 召回 adapter 在 async 上下文懒加载 `session.created_by` FK，认证路径会触发 `SynchronousOnlyOperation` 且不被 best-effort 捕获

**Status:** ✅ FIXED（commit 56f5e11d6）—— 新增 `@sync_to_async _resolve_actor(session)` 解析 actor，调用置于 best-effort try/except 内；补 `test_created_by_real_user_loads_actor_without_sync_error`（真实 created_by 用户 + 不预取 aget 走 FK 加载路径）。`created_by=None` 仍 fail-closed 空召回。

**File:** `server/services/plan_orchestration/recall_adapter.py:58`
**Issue:**
`recall()` 是 async 方法，第 58 行 `user = session.created_by` 直接访问**前向 FK 对象**。当 `created_by_id` 非空且关联 User 未被 `select_related` 预取时，Django 会触发同步 ORM 懒加载，在 async 事件循环中抛 `django.core.exceptions.SynchronousOnlyOperation`。

两点放大危害：

1. 该访问在 `try/except Exception`（第 60 行起）**之外** —— 异常不被 best-effort 捕获，会冒泡到 `engine.advance` 的通用 `except`，把会话推到 `failed`。这**直接违背 RECALL-01 的「召回失败返回空、不阻断编排」契约**，也使「created_by 为权限 actor」的正常认证路径反而比 `None` 路径更脆弱。
2. 现有测试**未覆盖**：`test_created_by_none_graceful_empty` 只测 `created_by is None`（Django 对 `_id is None` 短路返回 None、不查库，安全）；没有任何用例构造「带真实 `created_by` 用户、从 DB aget 的 session」，故该崩溃在 286 passed 中被完全掩盖。

注意 `RepoRouterV2Adapter` 在同类场景下做对了——它用 `session.work_item_id`（本地列，不查库）并把 ORM 包进 `@sync_to_async _project_repository_ids`。recall adapter 偏离了这个已验证的范式。本 phase adapter 仅在测试与 `__init__` 被引用（Phase 41/42 才注入真实编排入口），故为**潜伏 BLOCKER**：一旦 41 从 DB 加载 session 注入真实 adapter，认证召回路径即崩。

**Fix:**
用 `created_by_id` + `sync_to_async` 安全解析 actor（避免 async 懒加载），或至少把访问移入 try 块。推荐前者：

```python
@staticmethod
@sync_to_async
def _resolve_actor(session: PlanSession):
    # created_by_id 为空直接返回 None（不查库）；非空经同步 ORM 取 User
    return session.created_by

# recall() 内：
user = await self._resolve_actor(session)
```

并补一个用例：构造带真实 `created_by` 用户、`await PlanSession.objects.select_related(...).aget(...)` **不预取** created_by 的 session，断言 `recall()` 不抛 `SynchronousOnlyOperation` 且 `user` 正确透传。

## Warnings

### WR-01: `recall_context` 模型字段 `default=dict` 但实际持久化为 `list` —— 空值与有值形状不一致，下游消费易踩坑

**Status:** ✅ FIXED（commit 13834431e）—— `recall_context` 改 `default=list`，生成迁移 `0012_alter_plansession_recall_context`（AlterField）；`makemigrations --check` clean。`routing` 仍 dict 不动。无代码/测试依赖原 dict 默认。

**File:** `server/delivery/models/plan_session.py:77`（配套 `migrations/0011_...py:24`）
**Issue:**
`recall_context = models.JSONField(default=dict, blank=True)`，但 engine `_recall` 落库的是 `hits`（list），即未召回时为 `{}`（dict）、有召回时为 `[{...}]`（list）。同一字段在空/非空两态返回不同顶层类型。Phase 39 并行调研消费 `recall_context` 时，任何 `recall_context.get(...)` 或下标 `recall_context[0]` 都会因类型漂移而行为不一致（`{}` 上下标抛 `KeyError`/`IndexError`，list 上 `.get` 抛 `AttributeError`）。模型注释已承认此设计，但「文档化的脚枪仍是脚枪」。

**Fix:**
改 `default=list` 并新增迁移使空态与有值态一致为 list：

```python
recall_context = models.JSONField(default=list, blank=True)
```

（`routing` 仍是 dict 不动。）若不改 schema，则需在 Phase 39 消费端强制 `recall_context if isinstance(recall_context, list) else []` 归一。

### WR-02: 路由候选仓收窄召回在「候选仓非用户可见仓子集」时静默失效，召回被悄悄放宽到用户全部可见项目

**Status:** ⏭️ ACCEPTED（非越权泄漏，仅精度问题）—— 项目维 scoping 仍由 `allowed_projects` 严格守住，仅在用户已授权范围内放宽；下游 `recall_similar_chunks`/`resolve_allowed_repository_ids` 属 Phase 15 既有逻辑（本 phase 未改）。留待 Phase 39 消费端结合 routing 候选仓二次过滤命中。

**File:** `server/services/plan_orchestration/recall_adapter.py:54-57`
**Issue:**
adapter 把 `routing.candidates[].repo_id` 作为 `repository_ids` 传给 `search_similar` 以收窄召回。但下游 `resolve_allowed_repository_ids`：当 caller `repository_ids` **不是**用户可见仓子集时返回 `[]`；而 `recall_similar_chunks` 对 `allowed_repository_ids==[]` 的 demand 分路（work_item/tech_plan）走 `require_repository=False` 且不加仓库过滤 —— 结果是**仓库收窄被静默丢弃**，召回退化为「用户全部可见项目」范围。

**这不是越权泄漏**（项目维 scoping 仍由 `allowed_projects` 严格守住，只在用户已授权范围内放宽），但当路由候选仓是陈旧/外部/拼写漂移的 repo_id 时，预期的「聚焦候选仓」精度被无声破坏，注入 Phase 39 的召回上下文相关性下降且不可观测。

**Fix:**
adapter 侧对「收窄意图丢失」可观测化或显式收口。例如：当 `repository_ids` 解析非空但召回未按其收窄时记 warning；或在确有候选仓时不接受「静默全项目召回」，必要时由 39 消费端结合 routing 候选仓二次过滤命中。注意下游 `recall_similar_chunks`/`resolve_allowed_repository_ids` 属 Phase 15 既有逻辑（本 phase 未改），此为 Phase 38 依赖该收窄语义而引入的契约风险，建议至少在 38 文档/注释标注此边界。

## Info

### IN-01: `engine._route` 缺少 `_recall` 已有的 `isinstance(result, dict)` 防御，非 dict 路由返回会在转移已落库后崩为 failed

**Status:** ✅ FIXED（commit fd2c430bb）—— `_route` 加 `candidates = (result.get("candidates") or []) if isinstance(result, dict) else []`，与 `_recall` 防御对称。`test_engine_does_not_write_status_directly` 守护仍 green。

**File:** `server/services/plan_orchestration/engine.py:125-133`
**Issue:**
`_recall` 用 `result.get(...) if isinstance(result, dict) else ...` 防御注入返回形状，但 `_route` 直接 `result.get("candidates")`。若注入/未来 router 返回非 dict，会在 `transition(session, "routed", routing=result)` **已成功落库并转移 routing→recalling 之后**于构造 trace 时抛 `AttributeError`，经 `advance` 通用 except 推到 `failed`——产生「routing 已持久化但会话 failed」的不一致态。真实 `RepoRouterV2Adapter` 恒返回 dict，故仅防御性问题；但与 `_recall` 的防御不对称。

**Fix:**
对齐 `_recall` 的防御范式：

```python
candidates = result.get("candidates") or [] if isinstance(result, dict) else []
trace = {"candidates": [{"repo_id": c.get("repo_id"), "confidence": c.get("confidence")} for c in candidates]}
```

### IN-02: engine 跨类调用 `self.session_service._emit_event(...)` 私有方法（封装气味）

**Status:** ⏭️ ACCEPTED（Phase 36 既定钩子，计划明确如此）—— 留待 Phase 41 接真实 sink 时统一暴露公开 `emit_event` API。

**File:** `server/services/plan_orchestration/engine.py:133, 154`
**Issue:**
engine 直接调用 `PlanSessionService._emit_event`（下划线私有）。虽为 Phase 36 既定钩子（计划明确如此），但跨类访问私有成员使 §15 事件产出契约隐式化，Phase 41 接真实 sink 时易漏改/破坏。

**Fix:**
为 `PlanSessionService` 暴露公开发事件 API（如 `emit_event`），engine 改调公开方法；保持 §15 事件为显式公共契约的一部分。

---

_Reviewed: 2026-06-16T09:24:00Z_
_Reviewer: Claude (gsd-code-reviewer)_
_Depth: standard_
