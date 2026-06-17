---
phase: 55
slug: query-ui
type: ui-design-contract
status: inline
created: 2026-06-17
---

# Phase 55 — UI Design Contract（操作审计页）

## Route & Guard
- `/admin/audit`（`web/src/pages/admin/audit/index.vue`），`definePage({ meta: { requiresAdmin: true } })`。
- 侧栏 admin 区入口「操作审计」（`lucide--shield-check`）。

## Layout（复用既有 admin 页范式）
`PageContainer show-background` → `.card`：
1. **页头**：图标(lucide--shield-check) + 标题「操作审计」+ 副标题；右侧导出按钮组（CSV / JSON）。
2. **过滤栏**（grid，可折叠）：action(下拉，来自 taxonomy 常量集)、source(下拉 web/api/feishu_webhook/purge/system/invitation)、actor(文本)、target_type(文本)、target_id(文本)、occurred_from/to(datetime-local)、q(自由文本)。「查询」「重置」按钮。
3. **表格**：列 = 时间(occurred_at) / 操作者(actor_repr) / 动作(action, Badge) / 目标(target_type:target_repr) / 来源(source, Badge)。行可点击 → 详情。
4. **分页**：上一页/下一页 + 「第 X–Y / 共 N 条」，limit 选择(20/50/100)。
5. **详情弹窗/抽屉**：全字段 + before/after 并排 JSON（`<pre>` 格式化）+ metadata。只读。

## States
- loading：spinner + 文案。
- error：destructive 文案。
- empty：「暂无审计记录」居中。
- 403：由全局守卫 + 后端 IsSuperUser 双重兜底（非 superuser 不可达）。

## Data Contract（对齐后端 AuditEventSerializer）
```ts
interface AuditEvent {
  id: string; actor_id: string | null; actor_repr: string
  action: string; target_type: string; target_id: string; target_repr: string
  before: Record<string, unknown>; after: Record<string, unknown>
  source: string; occurred_at: string; recorded_at: string
  metadata: Record<string, unknown>
}
interface AuditListResp { items: AuditEvent[]; total: number }
```

## Pillars
- **只读**：无任何编辑/删除按钮（呼应 append-only）。
- **i18n**：全文案走 `audit.*`，默认中文。
- **脱敏**：before/after 后端已脱敏，前端原样展示（不二次处理）。
- **可达性**：表格语义化、按钮有 aria/label、过滤项有 Label。
