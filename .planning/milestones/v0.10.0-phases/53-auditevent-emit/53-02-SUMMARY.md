---
phase: 53-auditevent-emit
plan: 02
subsystem: api
tags: [audit, service, redaction, taxonomy, fail-soft, inv6, async, sync_to_async]

requires:
  - phase: 53-auditevent-emit (plan 01)
    provides: AuditEvent append-only 模型 + audit app + AuditEventImmutableError
provides:
  - AuditService 单一写入入口（emit sync / aemit async via sync_to_async）——AuditEvent 唯一 writer（INV-6）
  - _redact_audit_payload 递归脱敏入口（key-name + 值级密钥/高熵）+ REDACTION_PLACEHOLDER
  - action taxonomy 稳定常量容器（15 种子 Final[str] + ALL_ACTIONS + RESERVED_ACTIONS frozenset）
  - INV-6 grep 守护测试（无旁路写 AuditEvent）+ writer-actually-writes 反向断言
affects: [Phase 54 敏感操作全量覆盖 emit, Phase 55 审计查询/导出]

tech-stack:
  added: []
  patterns:
    - "单一写入入口 service（emit sync + aemit via sync_to_async）收口于唯一 AuditEvent.objects.create（INV-6）"
    - "入口内强制脱敏：before/after/metadata 经 _redact_audit_payload 兜底，调用方无法绕过明文落库"
    - "fail-soft emit：整段 try/except 吞异常 + audit.emit_failed warning，绝不冒泡阻断主操作"
    - "INV-3 不跨层 import：redaction.py 复刻 sensitive_detect/work_item_service 正则常量而非 import"
    - "INV-6 grep 源码守护（镜像 test_sdd_spec_inv6_guard.py）作 append-only 无旁路写表第二道防线"

key-files:
  created:
    - server/audit/services/__init__.py
    - server/audit/services/taxonomy.py
    - server/audit/services/redaction.py
    - server/audit/services/audit_service.py
    - server/tests/audit/test_audit_taxonomy.py
    - server/tests/audit/test_audit_redaction.py
    - server/tests/audit/test_audit_service.py
    - server/tests/audit/test_audit_failsoft.py
    - server/tests/audit/test_audit_inv6_guard.py
  modified: []

key-decisions:
  - "taxonomy 独立 taxonomy.py（对齐 event_taxonomy.py），本 phase 仅定义稳定容器 + 15 种子 + purge.* RESERVED 预留，具体 action 值由 Phase 54 各埋点补充"
  - "redaction.py 复刻（非 import）sensitive_detect 密钥正则/Shannon + work_item_service 键名集，守 INV-3 audit app 零业务跨层硬依赖"
  - "emit 入口强制脱敏 before/after/metadata（key-name 命中整体抹值 + 值级密钥/高熵只抹叶子），纵深防御兜底——调用方传明文也绝不落明文"
  - "emit 整段 fail-soft（吞异常 + audit.emit_failed warning，仅记 action/target_type 不记敏感载荷）；aemit 委托 sync_to_async(emit)，actor 字段访问全在 sync 块内（async 安全）"
  - "emit docstring 注明应在主操作成功后调用（transaction.on_commit），事务边界由 Phase 54 各调用方按场景处理"

patterns-established:
  - "AuditService.emit/aemit 双面均收口唯一 AuditEvent.objects.create，INV-6 grep 守护断言除此模块外无旁路写"
  - "脱敏占位符统一为 [已脱敏]；_redact_audit_payload 递归只抹命中叶子保留非敏感字段（参考 sensitive_purge._redact_value）"

requirements-completed: [AUDIT-01, AUDIT-02]

duration: 9min
completed: 2026-06-17
---

# Phase 53 Plan 02: `AuditEvent` 模型 + emit 地基 Summary

**AuditService 单一写入入口（emit/aemit）落地：唯一 AuditEvent writer（INV-6）+ 入口强制脱敏（key-name/值级密钥/高熵）+ fail-soft 吞异常不阻断主操作 + 稳定 action taxonomy 容器，配 INV-6 grep 守护**

## Performance

- **Duration:** 9 min
- **Started:** 2026-06-17T08:03:00Z
- **Completed:** 2026-06-17T08:11:00Z
- **Tasks:** 4
- **Files modified:** 9（9 created）

## Accomplishments

- **`AuditService.emit`/`aemit` 单一写入入口（INV-6，AUDIT-01）**：所有 AuditEvent 落库收口于唯一 `AuditEvent.objects.create`；sync `emit` + async `aemit`（`sync_to_async(emit)` 桥接 ORM）双面字段一致
- **入口强制脱敏（AUDIT-02，SC-4）**：`before`/`after`/`metadata` 经 `_redact_audit_payload` 兜底——key-name 命中整体抹值 + 值级密钥正则/高熵 Shannon 只抹命中叶子，调用方传明文也绝不落明文（DB 无明文测试断言）
- **fail-soft emit（AUDIT-02，SC-3）**：整段 try/except 吞异常 + `audit.emit_failed` warning（仅记 action/target_type 不记敏感载荷），绝不冒泡阻断主操作
- **action taxonomy 稳定容器（AUDIT-02）**：15 个 `Final[str]` 种子常量（object.verb 命名）+ `ALL_ACTIONS` / `RESERVED_ACTIONS`（purge.* 预留不计入本 phase 词表）frozenset
- **INV-6 grep 守护（AUDIT-01，SC-1/SC-2）**：扫 server 源码断言除 `AuditService` 外无旁路 `AuditEvent.objects.<write>`/实例化/`.save()`（负向前瞻排除 `AuditEventImmutableError`）+ writer-actually-writes 反向断言
- `audit/` 全套件 **28 测全绿**（含 Plan 01 的 8 model/append-only 测）；`makemigrations --check` 干净（仅 service/helper，无模型字段变更）；ruff format/check 通过

## Task Commits

Each task was committed atomically:

1. **Task 1: action taxonomy 稳定常量容器（taxonomy.py）** - `941e3a8f4` (feat)
2. **Task 2: 脱敏入口 _redact_audit_payload（redaction.py）** - `5ec064467` (feat)
3. **Task 3: AuditService 单一写入入口 emit/aemit + fail-soft + 强制脱敏** - `883d98401` (feat)
4. **Task 4: INV-6 grep 守护测试（无旁路写 AuditEvent）** - `2013739e0` (test)

## Files Created/Modified

- `server/audit/services/__init__.py` - audit service 层模块 docstring（curated 不强制 re-export）
- `server/audit/services/taxonomy.py` - 15 种子 `ACTION_*` Final[str] + `ALL_ACTIONS` / `RESERVED_ACTIONS` frozenset
- `server/audit/services/redaction.py` - `_redact_audit_payload` 递归脱敏 + `REDACTION_PLACEHOLDER` + 复刻密钥正则/Shannon/键名集（INV-3 不 import）
- `server/audit/services/audit_service.py` - `AuditService.emit`/`aemit` + `_actor_id`/`_actor_repr` + 强制脱敏 + fail-soft
- `server/tests/audit/test_audit_taxonomy.py` - 命名规范 + 种子覆盖 + reserved 不相交（3 测）
- `server/tests/audit/test_audit_redaction.py` - key-name/值级密钥/高熵/嵌套只抹叶子/标量保留（6 测）
- `server/tests/audit/test_audit_service.py` - 全字段持久化 + actor=None/superuser + async aemit + 默认 occurred_at（5 测）
- `server/tests/audit/test_audit_failsoft.py` - 吞异常不冒泡 + warning + 主操作不受影响 + async fail-soft + 入口强制脱敏 DB 无明文（4 测）
- `server/tests/audit/test_audit_inv6_guard.py` - 无旁路写 + writer-actually-writes 反向断言（2 测）

## Decisions Made

- **taxonomy 独立模块**：对齐 `delivery/services/event_taxonomy.py` 范式拆 `taxonomy.py`；本 phase 只定稳定容器 + 种子/预留，具体值由 Phase 54 各埋点补充消费
- **redaction 复刻非 import**：守 INV-3——audit app 零业务跨层硬依赖，`_SECRET_VALUE_PATTERNS`/`_shannon_entropy`/敏感键名集复刻到 `redaction.py`，语义对齐 `sensitive_detect`/`work_item_service`
- **脱敏在 emit 入口内强制**：调用方无法绕过服务端兜底（CONTEXT「禁止调用方各自手工脱敏后传入而无服务端兜底」）
- **fail-soft + async 安全**：emit 整段吞异常仅 warning；`aemit` 委托 `sync_to_async(emit)`，actor 字段（`actor.id`/`actor.username`/`is_superuser`）访问全在 sync 块内发生，规避 async 裸访问 lazy-FK
- **事务边界顺延**：emit docstring 注明应在主操作成功后调用（如 `transaction.on_commit`），具体由 Phase 54 各调用方按场景处理

## Deviations from Plan

None - plan executed exactly as written.

**Total deviations:** 0
**Impact on plan:** 无偏离；4 任务逐项按 plan action/acceptance 执行，全部 acceptance criteria 与 plan-level verification 通过。

## Issues Encountered

None.

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness

- **AUDIT-01 / AUDIT-02 整体闭环**（Plan 01 模型层 + append-only + Plan 02 单一写入入口 + INV-6 grep + fail-soft emit + 凭证脱敏 + taxonomy 容器）
- emit 地基就绪：Phase 54 可对任意敏感操作经 `AuditService.emit`/`aemit` 安全埋点——绝不落明文、绝不阻断主流程、写入唯一收口
- Phase 54 待落：身份/权限类 + 凭证/数据治理类敏感操作埋点 + v0.5 既有 `purge.started`/`purge.completed`（已预留 RESERVED_ACTIONS）/`TriggerLog`/`ActionLog` 收口；taxonomy 种子常量供各埋点引用

## Self-Check: PASSED

- 9 key files verified on disk (`[ -f ]`) — all present
- `git log --grep="53-02"` → 6 commits (4 task + 2 metadata)
- All task `<acceptance_criteria>` re-run: taxonomy (ALL_ACTIONS/RESERVED_ACTIONS + 种子值 + reserved 不相交), redaction (`_redact_audit_payload`/`REDACTION_PLACEHOLDER` + INV-3 无 import), audit_service (class/emit/aemit/create/_redact/audit.emit_failed + except 无 raise), inv6 guard (`_ALLOWED_WRITER` + 两测 + 负向前瞻)
- Plan-level `<verification>` re-run:
  - `ruff format --check audit tests/audit`: OK
  - `ruff check audit tests/audit`: All checks passed
  - `pytest tests/audit/ -q`: **28 passed**
  - `makemigrations --check --dry-run`: No changes detected

---
*Phase: 53-auditevent-emit*
*Completed: 2026-06-17*
