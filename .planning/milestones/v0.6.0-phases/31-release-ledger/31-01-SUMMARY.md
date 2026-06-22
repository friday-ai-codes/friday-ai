---
phase: 31-release-ledger
plan: 01
subsystem: delivery
tags: [release-ledger, tolerant-model, raw_row, bitable, natural-key, REL-01]
requires:
  - "delivery.WorkItem (Phase 28)"
  - "delivery migration 0005 (Document uniq)"
provides:
  - "ReleaseBatch / ReleaseRecord / ReleaseArtifact 宽容模型 + raw_row 无损存储"
  - "build_bitable_record_key natural-key helper（31-03 adapter 复用）"
  - "delivery_release_* 三表（migration 0006）"
affects:
  - "31-02 ReleaseService（落库入口）"
  - "31-03 Bitable adapter（幂等 upsert 经 bitable_record_key）"
tech-stack:
  added: []
  patterns:
    - "占位 external_id 范式（work_item FK null + work_item_external_id）"
    - "条件 UniqueConstraint condition=~Q(field='')（镜像 Document uniq）"
    - "raw_row JSONField(default=dict) 保留原始行（REL-01 宽容模型）"
key-files:
  created:
    - server/delivery/models/release.py
    - server/delivery/migrations/0006_releasebatch_releaserecord_releaseartifact.py
    - server/tests/delivery/test_release_models.py
  modified:
    - server/delivery/models/__init__.py
decisions:
  - "natural key 落独立字段 bitable_record_key（不复用 external_ref），便于 31-03 幂等 upsert"
  - "本 plan 只建表 + 单测，无落库业务逻辑（守 INV-6 精神，落库归 31-02）"
metrics:
  duration: ~5m
  completed: 2026-06-15
  tasks: 3
  files: 4
---

# Phase 31 Plan 01: Release 账本宽容模型 Summary

Release 账本三张宽容模型（ReleaseBatch/ReleaseRecord/ReleaseArtifact）落地，每个
row-bearing 模型带 `raw_row` JSONField 无损保留 Bitable 原始行（REL-01），natural
key `{app_token}:{table_id}:{record_id}` 经 `bitable_record_key` + 条件唯一约束就位，
migration 0006 已应用，9 个守护单测全绿。

## What Was Built

- **`server/delivery/models/release.py`**（Task 1）：
  - `ReleaseSource`（bitable|manual）、`ReleaseArtifactType`（mr|branch|commit|diff|release_note|doc）枚举。
  - `ReleaseBatch`：UUID PK + name/released_at/source/external_ref + `raw_row JSONField(default=dict)`。
  - `ReleaseRecord`：UUID PK + batch FK(CASCADE) + `work_item FK(null, SET_NULL)` + `work_item_external_id BigInt(null)` 占位 + status/note + `bitable_record_key` + `raw_row` + work_item/work_item_external_id 反查 indexes + 条件 UniqueConstraint `uniq_release_record_bitable_key`（非空键 DB 级唯一）。
  - `ReleaseArtifact`：UUID PK + release_record FK(CASCADE) + artifact_type 枚举 + ref(1000) + payload JSON。
  - `build_bitable_record_key(app_token, table_id, record_id)` helper（任一段空返回 ""）。
  - 无 create/save 业务逻辑；`__all__` 全导出；models/__init__.py curated re-export。
- **migration 0006**（Task 2 [BLOCKING]）：Django 生成（非手写），依赖 0005，建三表 + 两 index + 条件唯一约束；`migrate delivery` → OK；`makemigrations --check` → No changes detected。
- **`server/tests/delivery/test_release_models.py`**（Task 3）：9 用例，纯 ORM 无网络。

## Verification Results

- `migrate delivery`：`Applying delivery.0006... OK`；三表 `delivery_release_batch/record/artifact` 实测存在。
- `makemigrations delivery --check --dry-run`：`No changes detected`（模型与迁移一致）。
- `pytest tests/delivery/test_release_models.py`：**9 passed**（raw_row 无损 round-trip × 2、natural key 占位、非空键唯一抛 IntegrityError、空键共存、batch/artifact FK 反查、artifact_type 枚举读回、work_item 连 FK 反查、helper 拼接/空段豁免）。
- `ruff check` / `ruff format --check`（仅本 plan 变更文件）：All checks passed / already formatted。

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] migration 文件名重命名**
- **Found during:** Task 2
- **Issue:** Django 默认生成 `0006_releasebatch_releaserecord_releaseartifact_and_more.py`，非 plan 指定文件名。
- **Fix:** 重命名为 `0006_releasebatch_releaserecord_releaseartifact.py`（dependencies 不变，仍指向 0005）。
- **Commit:** 08f6e5b1

**2. [Rule 3 - Blocking] migration import 排序**
- **Found during:** Task 2
- **Issue:** 生成产物触发 ruff I001（import 未排序）。
- **Fix:** `ruff check --fix delivery/migrations/0006_*.py`（格式收尾，非逻辑改动）。
- **Commit:** 08f6e5b1

> 说明：Task 1（release.py + __init__.py re-export）在执行开始前已存在于工作树（未跟踪），内容逐字段对齐 DOMAIN §4/§12.6 与 plan，直接验证并提交。

## Known Stubs

None — 本 plan 范围即"只建表 + 单测"，无 UI/数据源接线缺口。落库业务逻辑（ReleaseService）按设计归 31-02，非本 plan 的 stub。

## Self-Check: PASSED

- FOUND: server/delivery/models/release.py
- FOUND: server/delivery/migrations/0006_releasebatch_releaserecord_releaseartifact.py
- FOUND: server/tests/delivery/test_release_models.py
- FOUND commit 59ee7128 (Task 1), 08f6e5b1 (Task 2), 89100753 (Task 3)
