---
phase: 49-produce-spec
reviewed: 2026-06-17T02:30:44Z
depth: deep
files_reviewed: 10
files_reviewed_list:
  - server/delivery/models/sdd_spec.py
  - server/delivery/migrations/0018_sddspec.py
  - server/delivery/models/__init__.py
  - server/delivery/services/document_service.py
  - server/delivery/services/sdd_spec_service.py
  - server/delivery/services/__init__.py
  - server/delivery/services/event_taxonomy.py
  - server/services/plan_orchestration/spec_generation.py
  - server/services/plan_orchestration/architect_merge_adapter.py
  - server/services/plan_orchestration/__init__.py
findings:
  critical: 0
  warning: 1
  info: 3
  total: 4
status: issues_found
---

# Phase 49: Code Review Report

**Reviewed:** 2026-06-17T02:30:44Z
**Depth:** deep
**Files Reviewed:** 10
**Status:** issues_found

## Summary

Phase 49（方案产 openspec spec + Document(sdd_spec)）的源码改动整体质量高、契约清晰、测试充分（6 个测试文件 28 用例全绿）。所有重点关切均已正确落实：

- **fail-soft 双保险**：`_handle_pass` 末尾 `spec_generation_hook` 外层 `try/except` + hook 内逐仓 `try/except` + emit best-effort 三层隔离，merge 始终返回 `passed`（`test_hook_total_failure_fail_soft` / `test_spec_synthesis_failure_fail_soft` 覆盖）。
- **非 SDD / 无 SDD 零回归**：`facets["methodology"] != "SDD"` 跳过、无匹配仓 no-op，merge 仍 passed、`current_plan_version` 不受影响（已测）。
- **INV-6**：`SddSpec` 仅经 `SddSpecService`、`Document` 仅经 `DocumentService` 写，grep 守护测试有效（`test_sdd_spec_inv6_guard`）。
- **async ORM 无裸 lazy-FK**：一律 `*_id` 标量 / `afirst` / `.values()`；`repo` / `work_item` 均为 `afirst` 完整实例后再取列属性，无跨 FK 惰性穿透。
- **`external_ref=""` 与条件唯一约束**：`UniqueConstraint(condition=~Q(external_ref=""))` 正确豁免内部 spec 文档；多份内部 spec 并存不撞键（已测）。
- **hash 不翻版本 / select_for_update 原子 / get_or_create 兜底竞态**：版本范式与 `_upsert_locked` 一致。
- **幂等短路不留孤儿**：短路命中直接返回、不调 `create_internal_spec`（`test_recreate_same_key_is_idempotent_no_new_rows` 验证不新增 Document/Version）。

发现 1 个 WARNING（非短路路径的孤儿 Document 泄漏窗口）与 3 个 INFO（健壮性/约束/durability 范式说明）。**无 BLOCKER**，不阻断发布。

## Warnings

### WR-01: `create_draft` 非短路路径在 `_create_locked` 失败时可能泄漏孤儿 Document

**File:** `server/delivery/services/sdd_spec_service.py:60-87`
**Issue:**
`create_draft` 短路未命中时分两个独立事务执行：先 `create_internal_spec`（自身 `@sync_to_async` + `transaction.atomic`，提交 Document + DocumentVersion），再 `_create_locked`（另一个 `transaction.atomic`，`get_or_create` SddSpec）。两者之间无包裹事务，存在两类孤儿窗口：

1. **并发竞态（已在 docstring 中声明为 best-effort 可接受）**：两个调用同时越过短路 → 各自 `create_internal_spec` 落一份 Document → `get_or_create` 仅一方建 SddSpec，另一方拿到既有 spec（指向对方的 document），自己刚建的 Document 成孤儿。
2. **`_create_locked` 异常（未声明）**：若 `get_or_create` 因瞬时 DB 错误/其他 `IntegrityError` 抛出，step 2 已提交的 Document 不会回滚 → 孤儿；异常被 hook 逐仓 `try/except` 吞为 warning，孤儿静默残留。

孤儿 Document 携带一条 DocumentVersion 但无任何 SddSpec 引用，长期累积造成数据卫生问题。重点关切「create_draft 幂等短路不留孤儿」在**短路路径**确实成立，但**非短路失败路径**不成立。

**Fix:**
低概率且属 best-effort 上下文，可不在本 phase 处理；若要收紧，可在 `_create_locked` 内部把「建 SddSpec」与「建 Document」纳入同一事务（需把 `create_internal_spec` 的落库逻辑下沉为可在既有事务内复用的内部 helper），或为孤儿 Document 增补一个后台清理/对账任务。至少建议把 docstring 中「竞态下落单的孤儿 Document 视为 best-effort 可接受」扩展为同时覆盖 `_create_locked` 失败路径，使契约与实现一致：

```python
# 幂等（D-49-3）：短路命中不留孤儿；未命中时 create_internal_spec 与 _create_locked
# 为两个独立事务——竞态或 _create_locked 失败下，先落的 Document 可能成孤儿
# （无 SddSpec 引用），视为 best-effort 可接受（不回滚、不阻断）。
```

## Info

### IN-01: `LLMSddSpecSynthesizer` 未剥离 LLM 输出的 ```` ``` ```` 代码块包裹

**File:** `server/services/plan_orchestration/spec_generation.py:48-65`
**Issue:**
`synthesize` 仅 `_content_to_text(...).strip()` 后判空即落库，未做任何归一化。system prompt 虽要求「不要代码块包裹」，但半可信 LLM 实际常返回 ```` ```markdown ... ``` ```` 包裹体。对比 `architect_merge_adapter._parse_merged_json` 对 JSON 做了「取首 `{` 到末 `}`」的鲁棒抽取，spec 侧无对应防御，包裹符会原样进入 spec 正文，降低产物质量。真实 LLM 路径本 phase 仅 mock 覆盖、E2E deferred，故当前影响低。

**Fix:** 在 `synthesize` 落库前剥离围栏，例如检测首尾 ```` ``` ```` 并去除首行语言标记与尾行围栏；同时保留「strip 后判空抛 `ValueError`」的现有兜底（由 hook 逐仓捕获）。

### IN-02: `unique_together(plan_version, repository)` 在 `plan_version IS NULL` 时不被 DB 强制

**File:** `server/delivery/models/sdd_spec.py:75-101`
**Issue:**
`plan_version` 为 `null=True`（SET_NULL）。SQL 中 `NULL` 互不相等，故 `unique_together(plan_version, repository)` 对 `plan_version=NULL` 的行**不构成唯一约束** —— 同一 repository 下多条 `plan_version=NULL` 的 SddSpec 可共存，幂等键失效。当前编排链路不可达（hook 在 `plan_version_id` 为 None / `PlanVersion` 查无时直接 no-op，`create_draft` 拿不到 None 的 `plan_version_id`），故为潜伏问题而非现网 bug。

**Fix:** 若未来允许 chat 自然语言需求产无 `plan_version` 的 spec，需追加一条针对 `plan_version IS NULL` 的部分唯一约束（如 `UniqueConstraint(fields=["repository"], condition=Q(plan_version__isnull=True), name=...)`），或在 service 层对 None 分支显式串行化。

### IN-03: `SddSpec.repository` 用 `CASCADE`，与脊柱 durability 范式不对称

**File:** `server/delivery/models/sdd_spec.py:61-65`
**Issue:**
`document` / `work_item` / `plan_version` 均用 `SET_NULL` 体现「删 X 不抹脊柱」durability 范式（见模块 docstring D-49-1），但 `repository` 用 `on_delete=CASCADE` —— 删除某 Repository 会级联删掉其全部 SddSpec 脊柱。这与其余 FK 的存续语义不对称。考虑到 `repository` 是非空幂等键（无法 SET_NULL），CASCADE 是合理取舍，此处仅作显式说明，便于后续若引入「软删/归档仓库」时复核该级联是否仍符合预期。

**Fix:** 当前无需改动；若后续 Repository 引入软删，建议复核此 CASCADE 是否应改为 `PROTECT` + 应用层归档，以免误删仓库静默抹除 spec 操作态历史。

---

_Reviewed: 2026-06-17T02:30:44Z_
_Reviewer: Claude (gsd-code-reviewer)_
_Depth: deep_
