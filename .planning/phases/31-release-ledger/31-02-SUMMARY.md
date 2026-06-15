---
phase: 31-release-ledger
plan: 02
subsystem: delivery
tags: [release-ledger, single-write, INV-6, raw_row, idempotent-upsert, work-item-backfill, REL-01]
requires:
  - "31-01 Release 宽容模型（ReleaseBatch/ReleaseRecord/ReleaseArtifact + bitable_record_key + raw_row）"
  - "delivery.WorkItem (Phase 28)"
provides:
  - "ReleaseService — Release 账本唯一写入入口（INV-6）：ingest_batch / upsert_record / add_artifact"
  - "bitable_record_key 幂等 upsert（消费预组装成品 key，自然键契约）"
  - "work_item_external_id 反查回填（命中连 FK / 未命中占位不抛）"
  - "Release 三模型旁路写表 INV-6 grep 守护"
affects:
  - "31-03 Bitable adapter（经 ReleaseService.ingest_batch 落库而非旁路写表；emit 预组装 bitable_record_key）"
tech-stack:
  added: []
  patterns:
    - "单一写入收口 + @sync_to_async 包同步 transaction.atomic（镜像 DocumentService/WorkItemService）"
    - "select_for_update().get_or_create 幂等 upsert + 条件唯一约束防并发重复"
    - "逐行 best-effort try/except 降级（单行畸形不回滚整批，§1.4）"
    - "占位 external_id 反查回填（对齐 WorkItemRelation / Document.work_item）"
    - "Release 三模型 INV-6 精确锚定 grep 守护"
key-files:
  created:
    - server/delivery/services/release_service.py
    - server/tests/delivery/test_release_inv6_guard.py
    - server/tests/delivery/test_release_service.py
  modified:
    - server/delivery/services/__init__.py
decisions:
  - "自然键契约：ReleaseService 消费传入行预组装的 bitable_record_key（record_key 入参 / raw_row['bitable_record_key']），不在服务内重拼接 app_token/table_id/record_id（拼接归 31-03 adapter，避免漂移）"
  - "work_item 占位反查按 work_item_id（非三元组）取首条 + warning，真实粒度留 REL-03（T-31-05 accept）"
  - "add_artifact 同样经 service 收口（不旁路），ReleaseArtifact 写表入口就位"
metrics:
  duration: ~7m
  completed: 2026-06-15
  tasks: 3
  files: 4
---

# Phase 31 Plan 02: ReleaseService 账本单一写入收口 Summary

`ReleaseService` 落地为 Release 账本（ReleaseBatch/ReleaseRecord/ReleaseArtifact）
**唯一写入入口**（INV-6），`ingest_batch` 把一批 Bitable 原始行收口成 1 个 ReleaseBatch
+ N 条 ReleaseRecord（raw_row 原样无损保留），按预组装 `bitable_record_key` 幂等 upsert；
`work_item` 经 `work_item_external_id` 反查（命中连 FK / 未命中留占位不抛）；配套 Release
三模型旁路写表 grep 守护与行为守护，9 个守护测试全绿。

## What Was Built

- **`server/delivery/services/release_service.py`**（Task 1）：`ReleaseService` 镜像
  DocumentService/WorkItemService 单一写入范式——async 公共方法 + `@sync_to_async` 包同步
  `transaction.atomic`；structlog 结构化日志（`release_batch_ingested` /
  `release_record_workitem_linked` / `_placeholder` / `_multimatch` /
  `release_record_ingest_failed`）。
  - `ingest_batch(*, raw_rows, source, batch_meta=None)`：建一个 ReleaseBatch（batch_meta
    原始内容落 `raw_row` 保留），逐行 best-effort `upsert_record`（单行异常不回滚整批，§1.4 /
    T-31-04 降级）。
  - `upsert_record(*, batch, raw_row, source, record_key=None)`：单行 async 公共入口（供
    31-03 adapter / 手动录入复用），委托 `_upsert_record`。
  - `_upsert_record`（`@sync_to_async` + `transaction.atomic`）：非空 key →
    `select_for_update().get_or_create` 收敛同行（31-01 条件唯一约束防并发重复），已存在则
    `raw_row` 始终覆盖为最新原始行 + 刷新占位映射（status/note/work_item）；空 key →
    直接 create（豁免唯一，多行共存）。
  - `_resolve_work_item`：经 `work_item_external_id` 反查 `WorkItem.work_item_id`，命中连
    FK（多条取首条 + warning）、未命中留占位 + `work_item=None`、**不抛**。
  - `add_artifact`：ReleaseArtifact 写入同样经 service 收口（不旁路）。
  - 占位列映射处标 `TODO(REL-03)`（批次字段 / status/note / work_item 反查 / 真实 Bitable 列映射待开放平台凭证）。
- **`server/delivery/services/__init__.py`**（Task 1 修改）：re-export `ReleaseService` + `__all__`。
- **`server/tests/delivery/test_release_inv6_guard.py`**（Task 2）：纯本地源码扫描（无 DB/网络），
  对 ReleaseBatch/ReleaseRecord/ReleaseArtifact 各建三类精确正则（`.objects.<write>` /
  `\s*\(` 实例化 / 链式 `.save(`），排除 writer 自身 / tests / migrations / models，跳过
  `class Release...` 定义行；命中即 fail；writer 有效性断言 release_service.py 含 ReleaseRecord 写表。
- **`server/tests/delivery/test_release_service.py`**（Task 3）：`django_db(transaction=True)`，
  7 用例覆盖 ingest 建批 + N 记录 + raw_row 无损、batch_meta raw_row 保留、幂等 upsert、空 key
  多行共存、work_item 命中连 FK / 未命中占位不抛、畸形行降级不回滚整批。

## Verification Results

- `pytest tests/delivery/test_release_service.py tests/delivery/test_release_inv6_guard.py`：
  **9 passed**（行为 7 + INV-6 守护 2）。
- `python -c "from delivery.services import ReleaseService"`（django.setup）：`ok`。
- `ruff check`（仅本 plan 变更文件 release_service.py / __init__.py / 两测试）：All checks passed。
- INV-6 grep 守护：除 ReleaseService 外无旁路 Release 三模型写表。

## Deviations from Plan

### Auto-fixed / Contract-driven Issues

**1. [Contract resolution] 自然键消费方式改为消费预组装 key（非重拼接）**
- **Found during:** Task 1
- **Issue:** plan Task 1 正文描述 ReleaseService 经 `build_bitable_record_key(...)` 从 raw_row
  顶层 app_token/table_id/record_id 现拼 natural key；但 plan-checker WARNING 指出拼接逻辑
  应单一来源（归 31-03 adapter），ReleaseService 重拼会导致漂移。
- **Fix:** 按本次执行明确的自然键契约实现——ReleaseService 把传入行**预先组装好的**
  `bitable_record_key`（`record_key` 入参优先，缺省读 `raw_row["bitable_record_key"]`）作为
  natural key 唯一来源，**不在服务内重拼接**；契约写入 ReleaseService docstring。`build_bitable_record_key`
  拼接收口留给 31-03 adapter（emit 预组装 key）。
- **Files modified:** server/delivery/services/release_service.py
- **Commit:** 418a0260

> 说明：plan Task 1 acceptance 提到 `add_artifact` 占位方法"可留可不留"——本实现选择实现，
> 使 ReleaseArtifact 写入也经 service 收口（INV-6 完整覆盖三模型）。

## Known Stubs

占位列映射（非完成态，已标 `TODO(REL-03)`，属本 phase 设计内骨架，非缺口）：

- status/note/work_item_external_id 取 raw_row 顶层同名键（真实 Bitable 业务列 → 字段映射
  待开放平台凭证 + 列样例，REL-03 v2）。
- work_item 反查按 `work_item_id`（非三元组自然键）取首条，真实粒度定型留 REL-03。

以上为 CONTEXT 明确的"骨架 + 宽容模型"范围（真实列映射 = v2 REL-03），非阻断本 plan 目标的 stub。

## Threat Flags

无新增计划外安全面——三模型写表收口由 INV-6 grep 守护锁定，无新网络端点 / 鉴权路径 / schema 变更。

## Self-Check: PASSED

- FOUND: server/delivery/services/release_service.py
- FOUND: server/tests/delivery/test_release_inv6_guard.py
- FOUND: server/tests/delivery/test_release_service.py
- FOUND: server/delivery/services/__init__.py（ReleaseService re-export）
- FOUND commit 418a0260 (Task 1), 8f733249 (Task 2), 9dc1de35 (Task 3)
