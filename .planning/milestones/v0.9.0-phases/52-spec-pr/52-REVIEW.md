---
phase: 52-spec-pr
reviewed: 2026-06-17T13:35:00Z
depth: standard
files_reviewed: 9
files_reviewed_list:
  - server/delivery/models/sdd_spec.py
  - server/delivery/migrations/0020_sddspec_implementation_prs.py
  - server/delivery/services/sdd_spec_service.py
  - server/workflows/nodes/ai/coding.py
  - server/delivery/api/serializers.py
  - web/src/api/specs.ts
  - web/src/components/spec/SpecDeliveryPanel.vue
  - web/src/pages/specs/[id].vue
  - web/src/locales/zh-CN.json
findings:
  critical: 0
  warning: 0
  info: 3
  total: 3
status: issues_found
---

# Phase 52: Code Review Report

**Reviewed:** 2026-06-17T13:35:00Z
**Depth:** standard（含跨文件链路追踪：service ↔ coding 节点 ↔ serializer ↔ view ↔ model ↔ 前端类型）
**Files Reviewed:** 9（外加 3 个测试文件作上下文）
**Status:** issues_found（仅 Info 级建议，无 BLOCKER / WARNING）

## Summary

审查 Phase 52「spec↔需求/PR 关联 + 交付验收视图」全部源码改动。重点关注的高风险路径
（`link_implementation_pr` 幂等/状态流转、`_finalize_and_notify` fail-soft 回填、INV-6 写入收口、
async ORM 安全、serializer 字段泄漏、前端外链安全 / i18n）均**未发现 bug、安全漏洞或质量阻断项**。
实现严谨、测试覆盖到位（去重幂等、非 approved 宽容、no-op 零回归、fail-soft 不阻断通知均有断言）。

逐条核对结果：

- **`link_implementation_pr` 幂等 + 状态流转**：✅ 正确。按 `pr_url` 去重（`already_linked`），
  仅 `approved → implemented` 强转、非 approved 仅记 ref 不强转（`test_link_non_approved_*` 参数化覆盖
  draft/in_review/implemented/archived），无 spec → no-op（`select_for_update().first()` 命中 None 直接 return）。
  append + 状态流转在单一 `transaction.atomic` 内，行锁 `select_for_update` 防 TOCTOU。`from/to_status`
  复用 `_LEGAL_TRANSITIONS["mark_implemented"]` 单一真相，未重复硬编码。
- **`_finalize_and_notify` fail-soft**：✅ 整段 `try/except Exception → warning`，镜像上方 cross-ref 范式；
  `plan_version_id` 缺失 / `successful_mrs` 为空时跳过；异常绝不上抛，不阻断 PR 创建/通知/节点完成
  （`test_link_failure_does_not_block_notification` 断言 `completed` + 通知被调用）。非 SDD 仓走 service no-op，零回归。
- **INV-6 写入收口**：✅ `implementation_prs` 与状态流转写入只经 `SddSpecService`；节点用 `from delivery.services
  import SddSpecService` lazy import 防循环；service 内 `.filter().update()` / `.save(update_fields=...)` 属合法收口写入。
- **async ORM**：✅ 节点侧仅传 `repository_id` / `pr_url` 标量；service 同步逻辑全在 `@sync_to_async` 包裹的
  `_link_implementation_pr` 内；detail serializer 的 `work_item.prd_url` / `plan_version.version` 等 FK 访问由
  `_detail_queryset()` 的 `select_related` 预取，且 `.data` 经 `sync_to_async` 包裹，无裸 lazy-FK。
- **serializer 字段泄漏 / read_only**：✅ `implementation_prs = JSONField(read_only=True)` 且在 `read_only_fields`，
  不可写；暴露字段无敏感项（pr_url / repository_id / linked_at）；`work_item.url` 取 `prd_url or ""`，无则空串、
  不臆造 URL（对齐 pr_cross_reference 范式）。
- **前端外链安全 / fail-soft / i18n**：✅ 外链一律 `:href` 绑定（非 v-html）+ `rel="noopener noreferrer"` +
  `target="_blank"`；缺数据经可选链 + 默认值降级占位（`workItem && workItemUrl` 三态、`prs.length` 空态）；
  zh-CN.json 合法、`specs.delivery` 仅一处、无重复键，组件用到的 7 个 key 均已定义。

## Info

### IN-01: i18n 死键 `planVersionUnlinked` 未被任何组件引用

**File:** `web/src/locales/zh-CN.json:195`
**Issue:** 新增的 `specs.delivery.planVersionUnlinked`（"未关联方案"）在全仓 `web/src` 内仅出现于本 locale 文件，
`SpecDeliveryPanel.vue` 仅渲染需求 / 规格 / 实现 PR 三段，从未渲染「方案未关联」占位，故此键为死代码。
非功能缺陷，但属冗余键，易在后续维护中误导。
**Fix:** 若交付面板不计划展示 plan_version 段，删除该键：

```json
"workItemUnlinked": "未关联需求",
"prsEmpty": "暂无实现 PR",
"linkedAt": "已关联于 {time}"
```

（移除 `"planVersionUnlinked": "未关联方案",` 行。）若后续要补 plan_version 段则保留并在组件中接入。

### IN-02: 实现 PR 的 `linked_at` 直接展示原始 ISO8601 字符串

**File:** `web/src/components/spec/SpecDeliveryPanel.vue:90`
**Issue:** `t('specs.delivery.linkedAt', { time: pr.linked_at })` 直接把后端 `timezone.now().isoformat()`
原文（形如 `2026-06-17T04:33:21.123456+00:00`）插入文案，对用户不友好（含微秒与时区偏移）。非 bug，
属展示质量项。仓内其它时间展示（如评审历史）通常经本地化格式化。
**Fix:** 复用项目既有时间格式化工具（如 `useDateFormat` / dayjs 封装）格式化后再传入：

```ts
const linkedAtText = (iso: string) => formatDateTime(iso) // 项目既有封装
```

或在模板中 `{{ t('specs.delivery.linkedAt', { time: formatDateTime(pr.linked_at) }) }}`。

### IN-03: 外链 `:href` 无客户端 scheme 白名单（纵深防御建议）

**File:** `web/src/components/spec/SpecDeliveryPanel.vue:34,82`（`workItemUrl` 与 `pr.pr_url` 绑定 `:href`）
**Issue:** Vue 模板 `:href` 绑定**不会**拦截 `javascript:` 等危险 scheme。当前两个来源均可信
（`pr_url` 由平台 MR 创建生成；`work_item.url` 取自 Django `URLField` `prd_url`，落库时经 URLValidator 校验，
默认不接受 `javascript:`），故实际 XSS 风险极低、非当前缺陷。仅作纵深防御提示：若未来该字段来源放宽
（如允许手填外链），缺少前端 scheme 校验会成为注入面。
**Fix:** 可加一个轻量 http(s) 守卫供外链统一过滤：

```ts
const safeHref = (u?: string) => (u && /^https?:\/\//i.test(u) ? u : '')
// 模板：:href="safeHref(pr.pr_url)"
```

---

_Reviewed: 2026-06-17T13:35:00Z_
_Reviewer: Claude (gsd-code-reviewer)_
_Depth: standard_
