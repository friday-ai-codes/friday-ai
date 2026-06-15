# Phase 3: 审计查询 UI + 导出

## Context

Phase 1 (01-auditevent-emit) 定义了 `AuditEvent` 模型和 emit 基础设施。Phase 3 补全可见闭环：管理员可通过前端界面查询、过滤、查看审计事件详情并导出。

## Design Decisions

- **Frontend stack**: Vue 3 + TS + Tailwind 4 + reka-ui (project convention)
- **Page location**: `/admin/audit` — admin-only route, following existing `/admin/` pages pattern
- **API client**: use existing `web/src/api/client.ts` typed fetch wrapper (`get`, `post`)
- **Table**: @tanstack/vue-table via existing `DataTable.vue` component (project convention)
- **i18n**: vue-i18n, default zh-CN, add translations inline or to zh-CN.json
- **Export**: backend CSV/JSON endpoint with streaming download; frontend trigger via download button
- **Permission**: only visible to superuser — backend `IsSuperUser`, frontend `requiresAdmin` meta
- **Existing admin pattern**: follow `conversations.vue`, `users.vue`, `git-credentials/index.vue`
- **Route registration**: unplugin-vue-router file-based routing (pages directory = routes)
- **Testing**: vitest + happy-dom for frontend; pytest for backend

## Patterns to Follow

- Vue SFC: `<script setup lang="ts">`
- Column defs: `ColumnDef<T>[]` with render functions (`h(...)`)
- API module: typed interfaces + `get`/`post` from `./client`
- Admin views: `adrf.views.APIView` + `IsSuperUser` + `sync_to_async`
- Serialization: read serializer (no sensitive fields), separate from write
- Django app: `__init__.py`, `apps.py`, `models.py`, `api/`, `migrations/`
