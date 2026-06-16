---
phase: 37-canonical-technicalplan-technicalplanservice
reviewed: 2026-06-16T00:42:00Z
depth: standard
files_reviewed: 10
files_reviewed_list:
  - server/delivery/models/technical_plan.py
  - server/delivery/models/__init__.py
  - server/delivery/services/technical_plan_service.py
  - server/delivery/services/__init__.py
  - server/delivery/migrations/0010_technicalplan_planversion_planexternalref.py
  - server/chat/models.py
  - server/chat/migrations/0022_codingplan_canonical_plan_id.py
  - server/mcp_tools/models.py
  - server/mcp_tools/migrations/0008_mcpworkitemtechnicalplan_canonical_plan_id.py
  - server/agents/tools/coding_tools.py
findings:
  critical: 0
  warning: 2
  info: 3
  total: 5
status: issues_fixed
fixed_at: 2026-06-16T00:57:00Z
fixed: [WR-01, WR-02, IN-01, IN-03]
deferred: [IN-02]
---

# Phase 37: Code Review Report

**Reviewed:** 2026-06-16T00:42:00Z
**Depth:** standard
**Files Reviewed:** 10
**Status:** issues_fixed

> **修复状态（2026-06-16）**：WR-01 / WR-02 / IN-01 / IN-03 已修复并各自原子提交，配套测试齐全；
> `tests/delivery` 全绿（263 passed），`makemigrations --check` 无变更。IN-02（canonical 被删
> 后悬空软链回退重建）按计划 deferred —— 非平凡（需清空 canonical_plan_id + 重建分支），留后续。
> 其余 chat 路由 trace 用例的 2 处失败为 pre-existing（与本 phase 改动无关，修复前后一致）。

## Summary

审查 Phase 37（canonical `TechnicalPlan` + `TechnicalPlanService` + 旧路径软链/迁移，PLAN-01/02/03）变更源文件。

总体质量良好，核心契约**正确落地**：
- **INV-2**：`TechnicalPlan.work_item` 为 `null=True, SET_NULL`，`origin=chat` + `work_item=None` 合法且不级联抹方案 —— 正确。
- **INV-3**：`_content_hash` 为本地 `sha256(canonical JSON sort_keys)`，全文件无 `knowledge` import —— 正确。
- **INV-6**：grep 全 `server/` 确认 canonical `TechnicalPlan`/`PlanVersion` 的 `.objects.create` / 实例化写入**仅**出现在 `technical_plan_service.py`；其余命中均为同名 mcp 模型（`McpWorkItemTechnicalPlan` / `McpCodingPlanVersion`）或 `workflows.schemas` 的 dataclass —— 无旁路写。
- **循环 FK migration**：`0010` 单 migration 先建 `PlanVersion`（含 `supersedes` self FK）→ 建 `TechnicalPlan`（`current_version`/`work_item` nullable FK）→ `AddField planversion.plan`，无 `RunPython`，正/反向均干净。
- **跨 app 软引用**：chat/mcp 的 `canonical_plan_id` 为 `UUIDField`（非 FK），无硬 FK 链；workflow 经 `PlanExternalRef` —— 正确。
- **archive 不级联**：`_archive_sync` 仅 `save(update_fields=["status","updated_at"])`，不触碰旧表/不删版本 —— 符合 DOMAIN §5.4 规则 5。
- **hash 相等不翻版本**：`_add_version_sync` 命中 `current.content_hash == new_hash` 返回 current —— 符合铁律。

发现 0 Critical、2 Warning、3 Info。最显著的是**用户特别关注的 lazy migration 并发竞态**（WR-01）确实存在：并发 `resolve()` 同一未迁移旧记录会创建重复 canonical。eager 投影的 best-effort 隔离（WR 无）实现正确，不会阻断 chat 创建。

---

## Warnings

### WR-01: lazy migration 竞态 + create/link 非原子 → 重复/孤儿 canonical  ✅ RESOLVED (bce5dc8eb)

**File:** `server/delivery/services/technical_plan_service.py:219-233`（chat，mcp `235-249` 同构）
**Issue:**
`_resolve_chat` 的 lazy 建分支无并发保护、且 `create_from` 与 `link` 处于**两个独立事务**：

```python
old = await CodingPlan.objects.aget(id=ref.source_key)
if old.canonical_plan_id:                       # ① check
    return await self._aget_plan(...)
content = chat_codingplan_to_content(old)
canonical = await self.create_from(...)         # ② create（独立事务，已 commit）
await self.link(old, canonical)                 # ③ backfill（另一独立事务）
```

两类问题：
1. **并发竞态**（用户特别关注项 —— 答案：是，会建 2 个 canonical）：两个并发 `resolve()` 命中同一 `canonical_plan_id=None` 的旧记录，都通过 ① 检查、都执行 ② 创建出独立 `TechnicalPlan`+`PlanVersion`、都执行 ③ 回填 —— 后写者覆盖 `canonical_plan_id`，前者成为**永久孤儿** canonical（无任何引用，但记录长存）。`canonical_plan_id` 只有 `db_index`、**无 unique 约束**，DB 层不拦截。违反 §5.4 规则 1 的幂等意图（一旧记录 → 单一 canonical）。
2. **非原子**：即使无并发，若 ② 成功但 ③ `link` 失败（如 `asave` 异常），旧记录 `canonical_plan_id` 仍为空 → 下次 `resolve` 再次走 lazy 建分支 → 又一个孤儿 canonical。

**Fix:** 把「取旧记录 + 重查软链 + 建 canonical + 回填」收进单一 `transaction.atomic` 并对旧记录加行锁，锁内复检软链：

```python
@sync_to_async
def _resolve_chat_lazy_sync(self, source_key, ref):
    from chat.models import CodingPlan
    with transaction.atomic():
        try:
            old = CodingPlan.objects.select_for_update().get(id=source_key)
        except CodingPlan.DoesNotExist:
            raise PlanNotFound(ref) from None
        if old.canonical_plan_id:               # 锁内复检：竞态后来者直接读
            return TechnicalPlan.objects.get(id=old.canonical_plan_id)
        content = chat_codingplan_to_content(old)
        # create + link 同一事务内同步执行
        ...
        old.canonical_plan_id = canonical.id
        old.save(update_fields=["canonical_plan_id", "updated_at"])
        return canonical
```

> 注：当前实现读路径仍返回**有效** canonical（不崩溃、不丢源数据），故定为 Warning；但在高并发 resolve 同一新 chat plan 场景下属真实数据漂移，建议修复后再进入 Phase 40 编排接入。

---

### WR-02: `mcp_plan_to_content` 丢弃 `plan_body.execution_plan` 的 coding_instruction / files / dependencies  ✅ RESOLVED (e2cccf1e8)

**File:** `server/delivery/services/technical_plan_service.py:338-379`（`_normalize_exec_task`）
**Issue:**
37-03 PLAN 要求 mcp 取材「优先用 `plan_body`（若其本身已是 §7/execution_plan 形态则**直接复用并补全必填**）」。但 `_normalize_exec_task` 只保留 5 个必填键，**无条件丢弃** `coding_instruction`、`files`、`dependencies` 等已存在字段：

```python
def _normalize_exec_task(raw, idx, default_name):
    return {
        "id": ...,
        "name": ...,
        "repository_id": ...,
        "repository_name": ...,
        "branch_strategy": ...,
        # coding_instruction / files / dependencies 全丢
    }
```

当 mcp `plan_body.execution_plan` 已含完整任务（coding_instruction、files）时，投影出的 canonical 丢失这些内容，与「忠实映射」的 must-have（`server/delivery/services/...` 37-03 truths #2）不符。对比 chat 的 `chat_codingplan_to_content` 正确保留了 `coding_instruction` 与 `files`。源 mcp 记录未被改写（原数据仍在），故非数据丢失，但 canonical 投影保真度低于计划契约。

**Fix:** 复用 `raw` 中已有的可选字段（仅在缺失时补默认），例如：

```python
task = {
    "id": str(raw.get("id") or f"mcp-{idx}"),
    "name": str(raw.get("name") or raw.get("repository_name") or default_name),
    "repository_id": str(raw.get("repository_id") or ""),
    "repository_name": str(raw.get("repository_name") or ""),
    "branch_strategy": _normalize_branch_strategy(raw.get("branch_strategy")),
}
if raw.get("coding_instruction"):
    task["coding_instruction"] = str(raw["coding_instruction"])
if isinstance(raw.get("files"), list):
    task["files"] = [
        {"path": str(f.get("path") or f.get("file_path", "")),
         "action": _normalize_action(f.get("action") or f.get("change_type"))}
        for f in raw["files"] if isinstance(f, dict)
    ]
return task
```

---

## Info

### IN-01: 非 UUID `source_key` 抛 ValueError 而非 PlanNotFound（resolve 契约缺口）  ✅ RESOLVED (736fdaf05)

**File:** `server/delivery/services/technical_plan_service.py:223,239`
**Issue:**
`CodingPlan.objects.aget(id=ref.source_key)` / `McpWorkItemTechnicalPlan.objects.aget(id=ref.source_key)` 中 `source_key` 为任意字符串。当 caller 传入非合法 UUID 时，Django 抛 `ValueError`/`ValidationError`，**不**被 `except DoesNotExist` 捕获 → 绕过「找不到旧记录 → `raise PlanNotFound`」契约（§5.4 规则 3），向上抛出未归类异常。
**Fix:** 在 `_resolve_chat`/`_resolve_mcp` 入口预校验 `uuid.UUID(ref.source_key)`，非法时 `raise PlanNotFound(ref) from None`；或将 `aget` 的 `except` 扩为 `(DoesNotExist, ValidationError, ValueError)`。

### IN-02: canonical 被删后 resolve 抛 PlanNotFound，旧记录 canonical_plan_id 悬空  ⏸ DEFERRED（非平凡，留后续）

**File:** `server/delivery/services/technical_plan_service.py:226-227,263-267`
**Issue:**
软链命中分支若 `canonical_plan_id` 指向的 `TechnicalPlan` 已被硬删除，`_aget_plan` 抛 `PlanNotFound`，即使旧记录本身完整、本可重新 lazy 迁移。DOMAIN §5.4 规则 5 设想 canonical 归档/删除时旧记录保留为历史输入；此时 resolve 应能从悬空软链回退到重建（或先清空 `canonical_plan_id` 再 lazy 建）。当前直接失败。
**Fix:** `_aget_plan` 捕获 `DoesNotExist` 时，对 chat/mcp 路径清空旧记录 `canonical_plan_id` 后走 lazy 重建分支（workflow 路径维持 `PlanNotFound`）。

### IN-03: eager 投影失败日志可能记录 content 片段  ✅ RESOLVED (35151d59a)

**File:** `server/agents/tools/coding_tools.py:282-287`
**Issue:**
best-effort 兜底 `logger.warning("chat_eager_plan_projection_failed", error=str(exc))`。当失败源于 `PlanContentInvalid`（`f"content 校验失败：{err}"`，`err` 为 jsonschema 错误消息）时，`str(exc)` 可能内嵌被校验 content 的字段值片段。chat `tech_plan` 通常非密钥，风险低；但若未来 content 含敏感串，会进入日志。
**Fix:** 仅记录异常类型与稳定摘要（如 `error_type=type(exc).__name__`），避免回写完整校验消息；或对 `PlanContentInvalid` 单独降噪。

---

_Reviewed: 2026-06-16T00:42:00Z_
_Reviewer: Claude (gsd-code-reviewer)_
_Depth: standard_
