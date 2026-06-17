---
phase: 55-query-ui
plan: 02
subsystem: api
tags: [audit, export, csv, json, streaming, fail-closed]
requirements-completed: [AUDITUI-02]
key-files:
  created:
    - server/tests/audit/test_export_api.py
  modified:
    - server/audit/api/views.py
    - server/audit/urls.py
key-decisions:
  - "导出用同步 APIView + StreamingHttpResponse 同步迭代 ORM（避免 async 流式 ORM 复杂度）"
  - "导出格式参数用 fmt 而非 format —— format 是 DRF 保留的内容协商 query 参数，传 csv 会触发协商劫持路由(404)"
  - "max_rows=50000 上限：超限 400 要求收紧过滤（防内存峰值/滥用）"
completed: 2026-06-17
---

# Phase 55 Plan 02 — 审计导出 Summary

**CSV / JSON 流式导出（IsSuperUser、复用列表过滤、max_rows 上限），`GET /api/audit/events/export/?fmt=csv|json`。**

## Accomplishments
- `AuditEventExportView`（同步 APIView，IsSuperUser）：复用 `apply_audit_filters`（与列表完全一致），不分页。
- CSV：`StreamingHttpResponse` + `csv.writer(_Echo())` 流式生成器，列含 before/after/metadata（json.dumps）；`Content-Disposition: attachment`。
- JSON：流式 `{"items":[...]}`。
- `max_rows=50000` 超限返回 400「请收紧过滤」。
- `test_export_api.py`：csv/json 内容 + 过滤透传 + max_rows 400 + fail-closed 403 全绿。

## Deviations
- **[Bug auto-fix]** 导出参数从 `format` 改 `fmt`：`format` 被 DRF 内容协商劫持，`?format=csv` 路由 404。改 `fmt` 后 csv/json 均 200。

## Acceptance
- CSV/JSON 正确表头/字段、复用过滤、超限 400、非 superuser 403。`tests/audit/` 84 passed。
