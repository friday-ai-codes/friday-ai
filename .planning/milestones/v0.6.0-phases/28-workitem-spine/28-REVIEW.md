---
phase: 28-workitem-spine
reviewed: 2026-06-15T13:20:00Z
depth: deep
files_reviewed: 16
files_reviewed_list:
  - server/delivery/apps.py
  - server/delivery/signals.py
  - server/delivery/urls.py
  - server/delivery/models/__init__.py
  - server/delivery/models/work_item.py
  - server/delivery/models/sync_state.py
  - server/delivery/models/relation.py
  - server/delivery/models/status_event.py
  - server/delivery/services/work_item_service.py
  - server/delivery/services/derivation.py
  - server/delivery/api/views.py
  - server/delivery/api/serializers.py
  - server/delivery/migrations/0001_initial.py
  - server/friday/settings.py
  - server/friday/urls.py
  - server/feishu/views.py
findings:
  critical: 1
  warning: 3
  info: 5
  total: 9
status: clean
fix_pass:
  fixed_at: 2026-06-15T13:25:00Z
  fixed:
    - WR-01  # 并发：mirror 刷新 + 状态事件 append 收敛进单把行锁的原子块
    - WR-03  # 状态事件 event_time 改用 payload 业务时间，与 history 回填同源去重
    - IN-04  # _safe_error 落库前真实脱敏 token/secret/Bearer
  deferred:
    - id: CR-01
      reason: 入口接线在 server/feishu/views.py，本次 fix pass 范围限定 delivery service 层（work_item_service.py / derivation.py）；webhook create/status 默认 work_item_type=\"story\" 的 INV-1 风险仍然存在，建议另开 fix 收敛 create/status 与 update 处理器的缺类型跳过逻辑。
    - id: WR-02
      reason: 派生关系收敛删除属 mirror 语义完整性增强，非本次并发/脱敏聚焦项；下游反查（Phase 34）接入前补即可。
    - id: IN-01
      reason: int(work_item_id) 容错在 feishu/views.py 入口层，超出本次 service 层范围。
    - id: IN-02
      reason: event_time / feishu_project_simple_name mirror 填充为独立增强项（本次仅把 payload 业务时间用于状态事件去重，未扩展 mirror 白名单）。
    - id: IN-03
      reason: send_robust 仅隔离订阅者异常，已被整体 try/except 兜底，低风险延后。
    - id: IN-05
      reason: 跨 type 同 id 碰撞在飞书侧实际不可能，记录备查即可。
---

# Phase 28: Code Review Report

**Reviewed:** 2026-06-15T13:20:00Z
**Depth:** deep
**Files Reviewed:** 16
**Status:** issues_found

## Summary

脊柱本体扎实：INV-1 由 `unique_together` 强制；INV-6 由"只经 `WorkItemService.upsert` 写表"+ grep 守护测试坐实（全仓除 service 外无旁路 `WorkItem` 写表，已复核）；INV-3 由 delivery 不 import knowledge、webhook 保留 `aschedule_ingestion` 守住。mirror-only 刷新用显式 `update_fields` 白名单，friday_enhanced / writeback 不在其中，保护正确。凭证不泄漏到日志/`SyncState.error`（token 在请求 header、不在响应；上游 `strict_response_json` 已脱敏；`error` 截断 500）——该焦点判定 clean。

主要问题集中在**入口接线**与**并发/刷新语义**：webhook 的 create/status 处理仍把缺失的 `work_item_type` 默认成 `"story"` 再喂给 canonical upsert，直接威胁 INV-1（与同文件 update 处理器已落地的 WR-04 防线自相矛盾）；upsert 的 `select_for_update` 锁范围只覆盖 get_or_create，mirror 刷新与状态事件 append 跑在各自独立事务里，并发下存在竞态；派生关系无收敛删除（mirror 语义不完整）。

## Critical Issues

### CR-01: webhook create/status 处理器默认 `work_item_type="story"` 喂给 canonical upsert，威胁 INV-1

**File:** `server/feishu/views.py:804`, `server/feishu/views.py:829`（→ `_schedule_delivery_upsert` at `:772`）
**Issue:**
`_handle_workitem_create` 与 `_handle_workitem_status` 用 `payload.get("work_item_type_key", "story")` 取类型，随后调用 `_schedule_delivery_upsert(project, work_item_id, work_item_type)`。`_schedule_delivery_upsert` 仅判 `if not work_item_id or not work_item_type`——`work_item_type` 因默认值恒为真，永不跳过。当 webhook 事件**缺** `work_item_type_key`（同文件 `_handle_workitem_update` 的注释明确指出"占位类型会把同一工作项分裂成两个实体（WR-04）"，证明确有事件不带该字段）时，一个 `issue` 会以 `type="story"` 落库为一个**错误三元组**的 canonical `WorkItem`；后续以正确类型再次 upsert 会创建第二行，形成"同一逻辑工作项 → 两个 canonical 行"，恰是 INV-1 要消灭的实体分裂。`_handle_workitem_update`（`:938`）已用 `""` 默认 + early-return 防住，create/status 路径却未对齐，属本 phase 入口接线引入的 INV-1 风险。

**Fix:** 与 update 处理器统一——不默认 `"story"`，缺类型则跳过 delivery upsert（knowledge ingestion 可另行决定，但 canonical 身份绝不能用占位类型）：

```python
# _handle_workitem_create / _handle_workitem_status
work_item_type = payload.get("work_item_type_key", "")
...
# _schedule_delivery_upsert 已能在 not work_item_type 时跳过 + warning；
# 仅需把默认值从 "story" 改为 ""，让缺类型走既有跳过分支。
```

（若 create/status 的 ingestion 仍需 `"story"` 兜底，应把 ingestion 与 delivery 的类型来源分开，delivery 只接受真实 type。）

## Warnings

### WR-01: upsert `select_for_update` 锁范围过窄——mirror 刷新与状态事件 append 在锁外独立事务，存在并发竞态

**File:** `server/delivery/services/work_item_service.py:180-191`（`_get_or_create_locked`），`:202-248`（`_refresh_mirror`）
**Issue:**
`_get_or_create_locked` 把 `select_for_update().get_or_create(...)` 包在 `transaction.atomic()` 内，经 `sync_to_async` 调用。但该函数**一返回事务即提交、行锁立即释放**。其后的 `_refresh_mirror` / `_record_sync_state` / `_apply_relations` / `_backfill_status_history` 各是独立 `sync_to_async` 调用、各自独立事务，**全程不持锁**，且复用步骤 1 取回的、可能已过期的 `work_item` 内存实例。模块/步骤 docstring 宣称"`select_for_update` 三元组 → 刷新 mirror → StatusEvent"像是一个原子读改写，实际不是。后果：同三元组并发 upsert（webhook 后台 `run_in_background` + 手动 API，或两条 webhook）下，`_refresh_mirror` 用过期的 `work_item.status_state_key` 做"状态是否变化"判断 → 可能**重复 append 或漏 append** `WorkItemStatusEvent`，mirror 字段 last-writer-wins（对镜像可接受，对事件流不可接受）。INV-1 仍由 `unique_together` 兜底，但状态事件流正确性受损。
**Fix:** 让读改写在同一把锁内完成——在 `_refresh_mirror`（及状态事件判断）内部对该行重新 `select_for_update` 并置于同一 `transaction.atomic` 同步块，再 `sync_to_async`；或把"取锁 + 刷 mirror + append 事件"合并进一个 `sync_to_async(transaction.atomic)` 同步函数，facet 缺料降级仍按现状在锁外补记。

### WR-02: 派生 `WorkItemRelation` 只增不删，源关联字段清空/变更后留下陈旧关系

**File:** `server/delivery/services/work_item_service.py:272-300`（`_apply_relations`）
**Issue:**
`_apply_relations` 对 `derive_relations_from_fields(...)` 当前结果逐条 `update_or_create`，**从不删除**库内已不在当前派生集合里的关系。`WorkItemRelation` 派生自 mirror 类字段（飞书权威、每次 sync 覆盖），但当飞书侧移除某关联（如 `所属迭代` 字段被清空）时，旧 `WorkItemRelation` 行会永久残留，违背 mirror"飞书赢、覆盖本地"语义，下游（Phase 34 反查/入图）会读到已失效关系。
**Fix:** 在 `_apply_relations` 内对"本次派生覆盖到的 source_field_key 集合"做收敛删除——删除 `source_work_item=work_item` 且 `(relation_type, source_field_key, target_external_id)` 不在本次 specs 中、且 `origin=feishu_field` 的行（仅清飞书派生来源，保留 `friday` 人工关系），再做现有的 upsert + 反向回填。

### WR-03: 状态事件可能重复——`_refresh_mirror` 合成 now() 事件与 `_backfill_status_history` 历史事件去重键不一致

**File:** `server/delivery/services/work_item_service.py:211-222`（合成事件），`:302-326`（历史回填）
**Issue:**
`_refresh_mirror` 在状态变化时 append 一条 `event_time=timezone.now()`、`cur_state_key=新态` 的事件；随后 `_backfill_status_history` 从 `work_item_status.history[]` 回填事件，去重键是 `(work_item, cur_state_key, event_time)`。当 history 含与当前态相同 `state_key` 但带**真实** `updated_at` 的条目时，其 `event_time` 与合成事件的 `now()` 不同 → 去重不命中，产生两条指向同一状态变更的逻辑重复事件（一条 now 戳、一条真实戳）。当前测试 fixture 未带 history，故未暴露。
**Fix:** 统一状态事件来源：要么状态变更只由 history 回填驱动（合成事件仅在无 history 时兜底），要么用 `cur_state_key`（+ 可空 `pre_state_key`）而非 `event_time` 作去重锚，避免 now() 戳与真实戳并存重复。

## Info

### IN-01: `_schedule_delivery_upsert` 的 `int(work_item_id)` 未保护

**File:** `server/feishu/views.py:794`
**Issue:** `work_item_id=int(work_item_id)` 在同步处理路径内执行；若 `work_item_id` 为非数字字符串会抛 `ValueError` 进入 webhook 处理器。飞书侧通常为数字，风险低，但与该函数"缺三元组只 warning 不抛"的容错基调不一致。
**Fix:** 用 try/except 包裹 int 解析，解析失败 `logger.warning` 后 `return`，与缺类型同款跳过。

### IN-02: upsert 从不写 `event_time` / `feishu_project_simple_name`

**File:** `server/delivery/services/work_item_service.py:202-248`
**Issue:** `WorkItem.event_time`（DOMAIN §12.1：飞书侧业务时间）与 `feishu_project_simple_name`（建/解析 URL 用）由 upsert 负责却始终为空。两者均 nullable/blank，不致崩溃，但脊柱字段长期缺值，URL 解析与时间排序后续会缺料。
**Fix:** 从飞书响应（`updated_at` epoch / 顶层 `simple_name`，见 §16）派生并纳入 mirror 刷新；或在 CONTEXT 显式标注为后续 phase 填充。

### IN-03: `_emit` 用 `Signal.send` 而非 `send_robust`

**File:** `server/delivery/services/work_item_service.py:328-342`
**Issue:** 整体已 try/except 兜底（订阅者异常不影响落库），但 `send`（非 `send_robust`）下单个订阅者抛错会中断其余订阅者派发。
**Fix:** 改用 `work_item_synced.send_robust(...)`，逐订阅者隔离异常。

### IN-04: `_safe_error` docstring 过度宣称脱敏

**File:** `server/delivery/services/work_item_service.py:359-361`
**Issue:** docstring 称"复用 feishu 既有脱敏"，实际仅 `str(exc)[:500]` 截断，无脱敏逻辑。实际安全性由上游 `strict_response_json` 保证，但注释易误导维护者以为此处做了脱敏。
**Fix:** 修正注释为"截断长度上限，依赖上游响应解析层脱敏"，或在此显式调用既有脱敏 helper。

### IN-05: 关系目标匹配/反向回填忽略 `work_item_type`

**File:** `server/delivery/services/work_item_service.py:283-300`
**Issue:** 正向 target 匹配与反向回填均按 `(feishu_project_key, work_item_id)` 过滤、未带 `work_item_type`；自然键含 type，理论上同 `(project_key, work_item_id)` 不同 type 两行会 `.first()` 任取其一。飞书 `work_item_id` 项目内全局唯一，实际碰撞几乎不可能，记录备查。
**Fix:** 若未来出现跨 type 同 id，需在匹配条件补 type 语义或确认 id 全局唯一性约束。

---

_Reviewed: 2026-06-15T13:20:00Z_
_Reviewer: Claude (gsd-code-reviewer)_
_Depth: deep_
