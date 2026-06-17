---
phase: 55-query-ui
plan: 01
subsystem: api
tags: [audit, query, rest, fail-closed, readonly]
requirements-completed: [AUDITUI-01]
key-files:
  created:
    - server/audit/api/__init__.py
    - server/audit/api/serializers.py
    - server/audit/api/filters.py
    - server/audit/api/views.py
    - server/audit/urls.py
    - server/tests/audit/test_query_api.py
  modified:
    - server/friday/urls.py
completed: 2026-06-17
---

# Phase 55 Plan 01 — 审计查询 REST API Summary

**审计查询列表 + 详情 REST（IsSuperUser fail-closed、只读、过滤 + offset/limit 分页），挂 `/api/audit/`。**

## Accomplishments
- `AuditEventListView`（adrf async）：过滤 actor_id/action/target_type/target_id/source/occurred_from/occurred_to/q + offset/limit（默认 50/上限 200），返回 `{items,total,limit,offset}`，复用 `apply_audit_filters`。
- `AuditEventDetailView`（adrf async）：单行全字段（before/after 对比），404 容错。
- `AuditEventSerializer`：全字段只读直出（before/after/metadata 写入端已脱敏）。
- 仅 GET 路由（list/detail/export），无任何写入口 —— 呼应 append-only 只读契约。
- `test_query_api.py`：过滤/分页/详情/fail-closed(403 非 superuser、401/403 匿名)/只读(无写路由) 全绿。

## Acceptance
- superuser 可查/过滤/分页/详情；非 superuser 403；写方法不可用。`manage.py check` 0 issues；`makemigrations --check` No changes。
