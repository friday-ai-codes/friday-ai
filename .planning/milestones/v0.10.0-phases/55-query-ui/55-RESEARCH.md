---
phase: 55
slug: query-ui
status: inline (subagents blocked)
created: 2026-06-17
---

# Phase 55 — Research（查询 API + 前端 + 导出）

## Endpoint Map（后端，挂 /api/audit/）

| Method | Path | View | 说明 |
|--------|------|------|------|
| GET | `/api/audit/events/` | `AuditEventListView(APIView)` | 列表 + 过滤 + offset/limit，返回 `{items, total}` |
| GET | `/api/audit/events/{id}/` | `AuditEventDetailView(APIView)` | 单行详情（before/after 全量） |
| GET | `/api/audit/events/export/` | `AuditEventExportView(APIView)` | CSV/JSON 流式导出，复用过滤 |

- 全部 `permission_classes = [IsSuperUser]`（`permissions.api_permissions.IsSuperUser`）——fail-closed。
- 仅 GET 路由注册（只读，无 create/update/delete）。
- async ORM：`await qs.acount()` + `[x async for x in qs[offset:offset+limit]]`（对齐 `TriggerLogListView`）。

## 过滤参数（query_params）

`actor_id`, `action`, `target_type`, `target_id`, `source`, `occurred_from`(ISO), `occurred_to`(ISO), `q`(actor_repr/target_repr icontains)。分页：`limit`(默认 50, 上限 200), `offset`(默认 0)。

模型索引已覆盖 action / target_type+target_id / actor_id / occurred_at / action+occurred_at → 过滤走索引。

## Serializer

`AuditEventSerializer`（DRF ModelSerializer，全字段只读）：id, actor_id, actor_repr, action, target_type, target_id, target_repr, before, after, source, occurred_at, recorded_at, metadata。before/after/metadata 已在写入端脱敏，查询面直出。

## 导出

- `?format=csv|json`（默认 csv）。`StreamingHttpResponse`，`Content-Disposition: attachment`。
- 复用列表过滤构造 queryset（不分页）；`max_rows`（默认 50000）超限 400。
- CSV header：occurred_at, actor_repr, action, target_type, target_id, target_repr, source, before, after, metadata（JSON 字段 json.dumps）。
- 流式生成器需在 sync 上下文迭代 ORM（StreamingHttpResponse 同步迭代）→ 用同步 APIView `get` + 同步 queryset 迭代（导出端用同步视图，避免 async 流式 ORM 复杂度）。

## 前端

- 文件路由：`web/src/pages/admin/audit/index.vue` → `/admin/audit`，`definePage({ meta: { requiresAdmin: true } })`。
- API 模块：`web/src/api/audit.ts`（list/detail/exportUrl）。导出走浏览器直接 `window.open` 带 query 的 URL（cookie-JWT 自动携带）或 fetch blob 下载。
- 组件范式：`PageContainer` + card + 过滤栏（Input/select）+ table + 分页按钮 + 详情弹窗（before/after 并排 JSON）。复用 `~/components/ui/{button,input,badge,label}`、`@tanstack/vue-query`、`useToast`/`useErrorHandler`。
- i18n：`web/src/locales/zh-CN.json` 增 `audit.*` 命名空间。
- 侧栏：`AppSidebar.vue` `adminNavItems` 增 `{ to: '/admin/audit', label: '操作审计', icon: 'lucide--shield-check' }`。

## Risks
- 导出流式 + async ORM 冲突 → 导出视图用同步 APIView（DRF 同步 get + StreamingHttpResponse 同步迭代 queryset），权限仍 IsSuperUser。
- before/after 可能较大 → 列表表格只显示摘要，详情弹窗看全量。
