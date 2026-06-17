---
phase: 55
slug: query-ui
milestone: v0.10.0
requirements: [AUDITUI-01, AUDITUI-02]
ui_hint: yes
mode: smart-discuss (autonomous / auto-accept, unattended)
created: 2026-06-17
---

# Phase 55 — Context（审计查询 API + 前端视图 + 导出）

> 无人值守 smart discuss：基于 Phase 53/54 已落库的 `AuditEvent` 与既有代码模式，自动采纳以下决策。

## Phase Boundary

**Goal**: 审计记录可查、可看 before-after、可导出，访问 fail-closed（仅 superuser）。
**Requirements**: AUDITUI-01（查询 REST API + 只读 + fail-closed）、AUDITUI-02（前端视图 + 导出）。
**Depends on**: Phase 54（已有覆盖的审计数据）。

### In scope
1. 后端审计查询 REST：列表（按 actor / action / target_type / target_id / source / 时间范围过滤 + offset/limit 分页）+ 详情。
2. 只读契约：仅 GET，无任何 create/update/delete 入口（呼应模型 append-only）。
3. fail-closed：`IsSuperUser` 权限，非 superuser 一律拒绝（403）。
4. 导出 CSV / JSON（复用同一过滤条件）。
5. 前端 superuser 审计页：列表 + 过滤表单 + 分页 + 详情（before/after 对比）+ 导出按钮。

### Out of scope（明确不交付）
- 审计行编辑/删除/重放（与 append-only 冲突）。
- 跨实例聚合 / 第三方 SIEM 推送 / 告警规则（后续里程碑）。
- 加密级防篡改链（hash chain）——Phase 53 已记为非目标。
- 项目级（非 superuser）审计自助查询——本期仅 superuser 全局视图。

## Decisions（auto-accepted）

### D1 — 后端形状：`audit/api/` + APIView，复用既有范式
- 在 `server/audit/` 下新建 `api/`（views/serializers/permissions 复用）+ `urls.py`，挂 `friday/urls.py` 于 `/api/audit/`。
- 列表用 **APIView async get + 手动 offset/limit**，返回 `{items, total}`——对齐 `TriggerLogListView` 既有约定（非 DRF PageNumberPagination，保持一致）。
- 复用 `permissions.api_permissions.IsSuperUser`（已被 system/repositories 凭证管理使用），fail-closed 纵深第一道。

### D2 — 过滤维度（对齐模型索引）
- `actor_id`、`action`、`target_type`、`target_id`、`source` 精确过滤；`occurred_from` / `occurred_to`（ISO8601）时间范围。
- 默认排序 `-occurred_at`（模型 Meta 默认）。模型已有 action / target / actor / occurred_at / action+occurred_at 索引，过滤即走索引。
- `q` 自由文本（可选）：对 `actor_repr` / `target_repr` icontains，便于人查。

### D3 — 只读 + 脱敏复用
- 仅注册 GET 路由；序列化器只读，直出已脱敏的 before/after/metadata（Phase 53 入口已强制脱敏，查询面无需二次处理）。
- 详情端点 `GET /api/audit/{id}/` 返回单行全字段（before/after 完整对比）。

### D4 — 导出
- `GET /api/audit/export/?format=csv|json`，复用列表过滤参数；**不分页**（导出全量匹配集），用 `StreamingHttpResponse` 流式避免大结果内存峰值。
- CSV 列：occurred_at, actor_repr, action, target_type, target_id, target_repr, source, before(JSON), after(JSON), metadata(JSON)。
- JSON：`{items: [...]}` 数组，字段与列表一致。
- 导出上限：默认无硬上限但加 `max_rows`（如 50000）防滥用，超限返回 400 提示收紧过滤（fail-safe）。

### D5 — 前端
- 文件路由 `web/src/pages/admin/audit/index.vue`（→ `/admin/audit`），`definePage({ meta: { requiresAdmin: true } })` 守卫（与其它 admin 子页一致）。
- `web/src/api/audit.ts` 客户端模块（list/detail/export），类型与后端序列化器对齐。
- UI：过滤栏（action/source/actor/target/时间范围/q）+ 表格（reka-ui/既有 DataTable 范式）+ 分页 + 行点击抽屉/弹窗看 before/after diff + 导出 CSV/JSON 按钮。
- i18n：接入 `vue-i18n`，默认中文文案。
- 侧边栏：`AppSidebar.vue` admin 区新增「操作审计」入口（superuser 可见）。

### D6 — 测试
- 后端：`tests/audit/test_query_api.py`（过滤/分页/详情/fail-closed 403/只读无写路由）+ `test_export_api.py`（csv/json + 过滤透传 + max_rows）。
- 前端：`web/src/pages/admin/__tests__/audit.spec.ts`（vitest + @vue/test-utils，happy-dom）渲染/过滤/导出按钮基本断言。

## Non-negotiables（CLAUDE.md/AGENTS.md）
- async ORM 走 `sync_to_async`；adrf 异步视图。
- superuser fail-closed：非 superuser 拒绝（与初始化接口同安全基调）。
- 审计只读不可篡改：绝不暴露写入口。
- i18n 默认中文。

## Plan Split（建议）
- **55-01**：后端查询 API（列表+详情+过滤+分页+fail-closed+只读）+ 序列化器/权限/urls + 后端测试。
- **55-02**：后端导出（CSV/JSON 流式+过滤透传+max_rows）+ 导出测试。
- **55-03**：前端 api/audit.ts + admin/audit 页面（过滤/表格/分页/详情 diff/导出按钮）+ 侧栏入口 + i18n + 前端测试。
