---
phase: 28-workitem-spine
plan: 01
subsystem: database
tags: [django, delivery, work-item, models, migration, uuid, unique-together, pytest-django]

# Dependency graph
requires:
  - phase: 27-feishu-prefix-fixes
    provides: 修对的飞书回源接口（work_item_type 取数 / 完整 fields[] / 关系字段派生），为 upsert 提供可靠数据
provides:
  - 新建 Django delivery app（注册进 INSTALLED_APPS）
  - canonical WorkItem 模型（飞书三元组身份，DB unique_together 强制 INV-1）
  - WorkItemSyncState（按 facet 来源完整度，unique(work_item, facet)）
  - WorkItemRelation（派生关系 + target_external_id 占位）
  - WorkItemStatusEvent（append-only 状态事件）
  - delivery 0001_initial migration（已 migrate，建出四张表）
affects: [28-02 WorkItemService.upsert, 28-03 webhook 接线, 29 评论事件流, 30 Document/REFERENCES, 31 Release 账本, 32 一键摄取, 34 反查]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "delivery app = bounded context：models/ 包按实体拆分 + curated re-export __init__"
    - "操作态聚合身份 = 飞书三元组自然键，DB unique_together 强制 INV-1"
    - "source-of-truth 三分类（mirror / friday_enhanced / writeback）在模型 docstring 标注"
    - "枚举值用 TextChoices；bitable_import / mr_reverse 先就位枚举占位"

key-files:
  created:
    - server/delivery/apps.py
    - server/delivery/models/work_item.py
    - server/delivery/models/sync_state.py
    - server/delivery/models/relation.py
    - server/delivery/models/status_event.py
    - server/delivery/models/__init__.py
    - server/delivery/migrations/0001_initial.py
    - server/tests/delivery/test_models.py
  modified:
    - server/friday/settings.py

key-decisions:
  - "INV-1 由 WorkItem.Meta.unique_together(feishu_project_key, work_item_type, work_item_id) 在 DB 层强制，测试以 pytest.raises(IntegrityError) 守护"
  - "id 一律 UUIDField(primary_key, default=uuid.uuid4, editable=False)；feishu_fields=JSONField(default=list)、field_provenance=JSONField(default=dict)"
  - "本 plan 只建表，无 create/save 业务逻辑（落库逻辑归 28-02 service，守 INV-6）；bitable_import/mr_reverse 仅枚举占位（真实调用方 Phase 31/32）"

patterns-established:
  - "delivery models 包拆分 + models/__init__.py curated re-export（__all__）"
  - "WorkItem FK 用字符串引用 projects.Project 避循环 import；同 app FK 直接类引用"

requirements-completed: [WIT-01, WIT-02, WIT-03, WIT-04, WIT-05]

# Metrics
duration: ~12min
completed: 2026-06-15
---

# Phase 28 Plan 01: WorkItem 脊柱数据层 Summary

**新建 delivery Django app 与四个操作态脊柱模型（canonical WorkItem + SyncState + Relation + StatusEvent），DB unique_together 强制 INV-1 三元组唯一，初始 migration 已应用建出四张表，7 个模型单测全绿。**

## Performance

- **Duration:** ~12 min
- **Completed:** 2026-06-15
- **Tasks:** 3
- **Files modified:** 12

## Accomplishments
- 新建 `server/delivery/` app 并注册进 `INSTALLED_APPS`（feishu 之后），Django 可加载、`makemigrations` 无报错。
- 四个模型逐字段对齐 DOMAIN §12.1–§12.4：`WorkItem`（mirror/friday_enhanced/writeback/元数据四组 + 三元组自然键 + 索引）、`WorkItemSyncState`（per-facet 完整度）、`WorkItemRelation`（派生关系 + `target_external_id` 占位）、`WorkItemStatusEvent`（append-only）。
- `0001_initial` 迁移生成并 `migrate`，DB 实际建出 `delivery_work_item` / `_sync_state` / `_relation` / `_status_event` 四张表；`makemigrations --check` 干净。
- 模型单测覆盖：字段读回、INV-1 三元组重复抛 `IntegrityError`、`(work_item, facet)` 唯一、relation external-id 占位、append-only status event——7 passed，无真实网络。

## Task Commits

1. **Task 1: delivery app 脚手架 + 注册 INSTALLED_APPS** - `244d7838` (feat)
2. **Task 2: 四模型 + choices + 包 re-export** - `ca3722ef` (feat)
3. **Task 3 [BLOCKING]: 生成并应用 migration + 模型层单测** - `95515672` (feat)

## Files Created/Modified
- `server/delivery/apps.py` - `DeliveryConfig`（name=delivery, verbose_name=交付脊柱）
- `server/delivery/models/work_item.py` - `WorkItem` + `WorkItemOrigin`（含 bitable_import/mr_reverse 占位）
- `server/delivery/models/sync_state.py` - `WorkItemSyncState` + `SyncFacet` + `SyncStatus`
- `server/delivery/models/relation.py` - `WorkItemRelation` + `RelationType` + `RelationOrigin`
- `server/delivery/models/status_event.py` - `WorkItemStatusEvent`
- `server/delivery/models/__init__.py` - curated re-export + `__all__`
- `server/delivery/migrations/0001_initial.py` - 四表初始迁移（unique_together + 索引）
- `server/tests/delivery/test_models.py` - 7 个模型单测
- `server/friday/settings.py` - `INSTALLED_APPS` 追加 `"delivery"`

## Decisions Made
- INV-1 用 DB `unique_together` 强制，而非应用层校验——重复三元组创建在 DB 层抛 `IntegrityError`，测试覆盖。
- `id` 统一 `UUIDField`；JSONField 默认值用 `list`/`dict` 工厂；本 plan 不写任何落库业务逻辑（归 28-02 service，守 INV-6）。
- `bitable_import`/`mr_reverse` 仅作 `WorkItemOrigin` 枚举占位，真实调用方在 Phase 31/32。

## Deviations from Plan
None - plan executed exactly as written.

（注：自动生成的 `0001_initial.py` import 块未排序触发 ruff I001，已用 `ruff check --fix` 规范化——属生成产物格式收尾，非计划偏离。）

## Issues Encountered
None.

## Verification Results
- `makemigrations delivery --check --dry-run` → No changes detected（迁移已就绪、干净）。
- `migrate delivery` → `Applying delivery.0001_initial... OK`；DB introspection 确认四张表存在。
- `pytest tests/delivery/test_models.py -x -q` → **7 passed**。
- `ruff format --check delivery/ tests/delivery/` + `ruff check delivery/ tests/delivery/` → all clean。

## User Setup Required
None - no external service configuration required.

## Next Phase Readiness
- 表结构就位，28-02 可在其上实现 `WorkItemService.upsert`（DOMAIN §13.1）作为唯一写入入口（INV-6）。
- 下游 phase（29 CommentEvent / 30 Document / 31 Release / 34 反查）可 FK 关联 `delivery.WorkItem`。

---
*Phase: 28-workitem-spine*
*Completed: 2026-06-15*
