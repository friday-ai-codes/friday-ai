---
phase: 53-auditevent-emit
plan: 01
subsystem: database
tags: [audit, django, append-only, immutable, migrations, soft-reference]

requires:
  - phase: accounts
    provides: accounts.User（actor_id 标量软引用目标）
provides:
  - audit Django app（零业务依赖横切叶子包，注册 INSTALLED_APPS）
  - AuditEvent append-only 模型（表 audit_event，12 字段 + 双时间戳 + 5 查询索引）
  - AuditEventImmutableError 异常类 + 模型层 save/delete 不可篡改守护
  - 0001_initial 迁移（actor 标量 UUID 非 FK，无跨 app 迁移依赖）
affects: [53-02 AuditService 单一写入入口, Phase 54 emit 覆盖, Phase 55 审计查询/导出]

tech-stack:
  added: []
  patterns:
    - "append-only 模型层守护：save() 在 _state.adding is False 时 raise，delete() 直接 raise"
    - "actor 标量软引用（UUIDField 非 FK）+ actor_repr 快照，删用户不级联触碰审计行"
    - "双时间戳：occurred_at（default=timezone.now 可传入）+ recorded_at（auto_now_add 不可变插入戳）"

key-files:
  created:
    - server/audit/__init__.py
    - server/audit/apps.py
    - server/audit/models/__init__.py
    - server/audit/models/audit_event.py
    - server/audit/migrations/__init__.py
    - server/audit/migrations/0001_initial.py
    - server/tests/audit/__init__.py
    - server/tests/audit/test_audit_model.py
    - server/tests/audit/test_audit_append_only.py
  modified:
    - server/friday/settings.py

key-decisions:
  - "新建轻量 audit app（零业务依赖叶子包）而非塞 delivery/system，可被任意 app 无环 import"
  - "actor 用可空标量 actor_id(UUID) + actor_repr 快照，不建 FK——最纯不可篡改（删用户不触碰审计行）"
  - "append-only 模型层守护为第一道防线；旁路写表（.objects.update/bulk_*）由 Plan 02 INV-6 grep 守护兜底"
  - "occurred_at/recorded_at 双时间戳分离业务事件时间与不可变落库戳"

patterns-established:
  - "AuditEvent 逐项镜像 WorkItemStatusEvent/PlanSessionEvent append-only 模型形状"
  - "Meta 索引覆盖 action / (target_type,target_id) / actor_id / occurred_at / (action,occurred_at) 为 Phase 55 铺底"

requirements-completed: []  # AUDIT-01 仅完成「模型层 + append-only 守护」半；单一写入入口 + INV-6 grep + emit/脱敏归 Plan 02

duration: 7min
completed: 2026-06-17
---

# Phase 53 Plan 01: `AuditEvent` 模型 + emit 地基 Summary

**新建零业务依赖的 audit 横切 Django app，落 AuditEvent append-only 不可篡改模型（actor 标量软引用 + 双时间戳 + 5 查询索引 + 模型层 save/delete 守护）与 0001_initial 迁移**

## Performance

- **Duration:** 7 min
- **Started:** 2026-06-17T07:57:00Z
- **Completed:** 2026-06-17T08:01:00Z
- **Tasks:** 3
- **Files modified:** 10（9 created + 1 modified）

## Accomplishments

- 新建 `audit` Django app（`AuditConfig`，verbose_name=操作审计）——零业务依赖横切叶子包，注册进 INSTALLED_APPS（accounts 之后，低层 sink）
- `AuditEvent` append-only 模型落 `audit_event` 表：AUDIT-01 12 字段（actor_id/actor_repr/action/target_type/target_id/target_repr/before/after/source/occurred_at/recorded_at/metadata）
- actor 用可空标量 `actor_id`（UUID）+ `actor_repr` 快照，**不建 FK**——删用户绝不级联 UPDATE/删除审计行（最纯不可篡改）
- 模型层 append-only 守护：既有行 `save()` / 任意 `delete()` 抛 `AuditEventImmutableError`，首次 create（`_state.adding=True`）放行
- Meta 5 组查询索引（action / (target_type,target_id) / actor_id / occurred_at / (action,occurred_at)）为 Phase 55 查询过滤铺底
- `0001_initial` 迁移自动生成，`makemigrations --check` 干净；8 测全绿

## Task Commits

Each task was committed atomically:

1. **Task 1: 新建 audit app 骨架 + 注册 INSTALLED_APPS** - `052d11ed6` (feat)
2. **Task 2: AuditEvent append-only 模型 + AuditEventImmutableError + 索引** - `341b1b756` (feat)
3. **Task 3: 0001_initial 迁移 + append-only/字段索引/标量-actor 测试** - `d39471c88` (test)

## Files Created/Modified

- `server/audit/__init__.py` - audit app 模块 docstring（横切叶子包说明）
- `server/audit/apps.py` - `AuditConfig`（name=audit, verbose_name=操作审计）
- `server/audit/models/__init__.py` - curated re-export `AuditEvent` / `AuditEventImmutableError`
- `server/audit/models/audit_event.py` - `AuditEvent` 模型 + `AuditEventImmutableError` + save/delete 守护 + `__str__`
- `server/audit/migrations/__init__.py` - 迁移包占位
- `server/audit/migrations/0001_initial.py` - audit_event 表初始迁移（自动生成，仅修正 import 排序）
- `server/tests/audit/__init__.py` - 测试包占位
- `server/tests/audit/test_audit_model.py` - 字段齐备 / 索引维度 / actor 标量非 FK / 双时间戳语义（4 测）
- `server/tests/audit/test_audit_append_only.py` - 首次 create 放行 / save/delete raise / 双层防御边界（4 测）
- `server/friday/settings.py` - INSTALLED_APPS 在 accounts 之后插入 `"audit"`

## Decisions Made

- **新建 audit app 而非复用 delivery/system**：delivery 是高耦合 hub（import feishu/knowledge/projects），audit 需被任意 app 无环 import；新 app = 干净 bounded context（per RESEARCH §1）
- **actor 标量软引用非 FK**：FK + on_delete=SET_NULL 会在删用户时 UPDATE 审计行，与 append-only 冲突；标量引用删用户完全不触碰审计行（per RESEARCH §2.1）
- **append-only 双层防御边界**：模型层 save/delete 守护拦实例级写入；`.objects.update()`/`bulk_*` 旁路由 Plan 02 INV-6 grep 守护兜底（本 plan 不实现，测试 docstring 标注）
- **AUDIT-01 仅完成模型层半**：单一写入入口（AuditService）+ INV-6 grep 守护 + fail-soft emit + 凭证脱敏归 Plan 02，故 requirements-completed 留空，不提前标记 AUDIT-01 完成

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] 自动生成迁移 import 排序违反 ruff I001**

- **Found during:** Task 3（生成 0001_initial 迁移）
- **Issue:** `makemigrations` 生成的 `0001_initial.py` 把 `import django.utils.timezone`（第三方）排在 `import uuid`（stdlib）之前，违反 ruff isort I001；plan verification 含 `ruff check audit` 门禁、pre-commit 钩子亦跑 ruff，不修无法过门/提交
- **Fix:** `ruff check --fix audit/migrations/0001_initial.py` 仅重排 import（uuid 在前），与既有 `delivery/migrations/0001_initial.py` 排序一致；schema 内容逐字未动
- **Files modified:** server/audit/migrations/0001_initial.py
- **Verification:** `ruff check audit tests/audit` All checks passed；`makemigrations --check --dry-run` No changes detected
- **Committed in:** d39471c88 (Task 3 commit)

---

**Total deviations:** 1 auto-fixed (1 lint compliance on generated file)
**Impact on plan:** 仅 import 排序修正以过 lint 门禁/pre-commit 钩子，迁移 schema 内容未改。无 scope creep。

## Issues Encountered

None.

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness

- AuditEvent 存储契约（不可篡改 + 标量 actor + 查询索引）就绪，可供 Plan 02 的 `AuditService` 单一写入入口消费
- Plan 02 待落：`AuditService.emit()`/`aemit()` 单一写入入口 + 强制脱敏（`_redact_audit_payload`）+ fail-soft + action taxonomy 容器 + INV-6 grep 守护测试 + writer-actually-writes 反向测试
- AUDIT-01/AUDIT-02 在 Plan 02 完成后整体闭环

---
*Phase: 53-auditevent-emit*
*Completed: 2026-06-17*
