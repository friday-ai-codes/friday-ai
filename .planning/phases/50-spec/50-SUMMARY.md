---
phase: 50-spec
subsystem: delivery / spec governance
tags: [spec, state-machine, review, rest, vue, i18n]
requirements: [SPECST-01, SPECST-02, SPECST-03]
dependency_graph:
  requires: [Phase 49 SddSpec / SddSpecService.create_draft]
  provides:
    - "SddSpecReview append-only 评审模型 + ReviewDecision"
    - "SddSpecService 状态机流转（submit_for_review/approve/reject/mark_implemented/archive）+ SddSpecTransitionError"
    - "/api/specs/ REST（list/detail/transition）"
    - "前端 spec 治理界面（/specs 列表 + 详情 + 流转操作 + 评审时间线 + 侧边栏入口）"
  affects: [Phase 51 编码前置 gate（消费 approved）, Phase 52 spec↔PR 关联]
tech_stack:
  added: []
  patterns:
    - "条件 .filter(status=from).update(status=to) + 影响行数判定（幂等 fail-loud，复用 RepoCodingTaskService）"
    - "approve/reject 单一 transaction.atomic 建评审 + 驱动状态（更新 0 行回滚）"
    - "adrf APIView + sync_to_async 包裹 .data；view 内 action 级 superuser 分流"
    - "前端 TanStack useMutation onSuccess invalidate(['specs'] / ['spec', id]) + toast/errorHandler"
key_files:
  created:
    - server/delivery/models/sdd_spec_review.py
    - server/delivery/migrations/0019_sddspecreview.py
    - server/delivery/api/spec_views.py
    - server/delivery/spec_urls.py
    - server/tests/delivery/test_sdd_spec_review_model.py
    - server/tests/delivery/test_sdd_spec_transitions.py
    - server/tests/delivery/test_spec_api.py
    - web/src/api/specs.ts
    - web/src/components/spec/SddSpecStatusBadge.vue
    - web/src/components/spec/SpecReviewTimeline.vue
    - web/src/components/spec/SpecReviewDialog.vue
    - web/src/components/spec/SpecTransitionActions.vue
    - web/src/pages/specs/index.vue
    - web/src/pages/specs/[id].vue
    - web/src/components/spec/__tests__/SddSpecStatusBadge.test.ts
    - web/src/components/spec/__tests__/SpecReviewTimeline.test.ts
    - web/src/components/spec/__tests__/SpecTransitionActions.test.ts
    - web/src/pages/specs/__tests__/specs-index.test.ts
  modified:
    - server/delivery/models/__init__.py
    - server/delivery/services/sdd_spec_service.py
    - server/delivery/services/__init__.py
    - server/delivery/api/serializers.py
    - server/friday/urls.py
    - server/tests/delivery/test_sdd_spec_inv6_guard.py
    - web/src/api/index.ts
    - web/src/locales/zh-CN.json
    - web/src/components/layout/AppSidebar.vue
    - web/src/components.d.ts
    - web/src/typed-router.d.ts
metrics:
  plans: 5
  task_commits: 13
  backend_tests_added: 3 files (model/transitions/api) + INV-6 extension
  frontend_tests_added: 4 files
  completed: 2026-06-17
---

# Phase 50 — spec 状态机 + 变更记录 + 评审状态 + 前端展示 Summary

让 Phase 49 落的 `SddSpec` 具备完整可治理生命周期：不可篡改评审记录（append-only）、单一 service 入口的状态机流转（评审驱动状态、条件更新防双推进）、fail-closed 的 REST 治理端点，以及 reuse-first 的 Vue 3 spec 治理界面（列表/详情/流转/评审时间线）。

## Plan-by-Plan

### 50-01 — SddSpecReview append-only 模型 + migration（wave 1）

- 新建 `SddSpecReview`（`spec` FK CASCADE related_name=`reviews`、`reviewer` FK→`AUTH_USER_MODEL` SET_NULL null、`decision` approve/reject、`comment`、`created_at`）+ `ReviewDecision` 枚举；模型层零业务写方法（append-only，INV-6）。
- curated re-export（`models/__init__.py`）；`makemigrations` 生成 `0019_sddspecreview`（依赖 0018），`makemigrations --check` 无漂移。
- 守护测试：字段/on_delete/ordering/append-only 内省 + CASCADE/SET_NULL/倒序 ORM 语义（7 用例）。

### 50-02 — SddSpecService 状态机 + INV-6 守护扩展（wave 2）

- `SddSpecService` 新增 5 个 async 流转方法 + `SddSpecTransitionError`（导出到 `__all__` 与 services 包）。
  - 合法表：submit_for_review(draft→in_review)、approve(in_review→approved)、reject(in_review→draft)、mark_implemented(approved→implemented)、archive(任意非 archived→archived)。
  - 条件 `.filter(id,status=from).update(status=to)` + 影响行数 0 → `SddSpecTransitionError`（幂等/防双推进 fail-loud，消息含 action+当前状态）。
  - approve/reject 单一 `transaction.atomic` 内先建 `SddSpecReview` 再条件更新；更新 0 行 raise → 回滚评审（无孤儿，T-50-04）。`SddSpecService` 是 `SddSpecReview` 唯一写入点。
- `test_sdd_spec_inv6_guard` 扩展三组正则覆盖 `SddSpecReview` 旁路写 + 正向有效性用例（writer 含 `SddSpecReview.objects.create`）。
- 测试：10 流转/幂等/原子/回滚用例 + 3 INV-6 用例；`-k sdd_spec` 24 用例零回归。

### 50-03 — /api/specs/ REST（wave 3）

- 序列化器（全 read_only）：`SddSpecReviewSerializer`（reviewer username 或 null）、`SddSpecListSerializer`、`SddSpecDetailSerializer`（body=`document.current_version.content`、reviews 倒序、relations repository/work_item/plan_version 摘要，缺失项不输出）。
- `spec_views.py`（adrf）：`SpecListView`（IsAuthenticated，?status/?repository_id 过滤，非法值 400）、`SpecDetailView`（404 中性消息）、`SpecTransitionView`（action 级 superuser 分流 D-50-3——approve/reject/archive/mark_implemented 须 superuser，否则 403；reviewer=request.user；reject comment 必填；非法流转 400；不存在 404）。
- 挂载 `/api/specs/`（`friday/urls.py` include `delivery.spec_urls`）。
- 测试：17 API 用例（list 过滤/400、detail body+relations+reviews/404、transition 提交/403/superuser approve 建评审/reject 必填/非法流转 400/403-vs-404）。

### 50-04 — 前端基础设施（wave 1）

- `api/specs.ts`：`specsApi`（list/detail/transition）+ 完整 TS 类型（与 50-03 契约对齐）+ barrel 导出。
- `SddSpecStatusBadge`（5 态色彩映射 + i18n label + archived 图标）、`SpecReviewTimeline`（reviewer/decision/comment/time，approve 绿 reject 红，空态文案）。
- `zh-CN.json` 注入 `specs` 命名空间（严格照搬 UI-SPEC i18n 草案）。
- 测试：徽标 5 态真实 zh-CN 文案+色彩、时间线顺序/null reviewer/空态（10 用例）。

### 50-05 — 前端交互层（wave 2）

- `SpecReviewDialog`（reka-ui Dialog + textarea，reject comment 必填禁用确认）、`SpecTransitionActions`（state×权限矩阵显隐：非 superuser in_review 仅见 awaitingReview 提示；approve/reject 走对话框，archive/mark_implemented 走 useConfirmDialog；流转中 disabled+spinner；onSuccess invalidate ['specs']/['spec',id] + toast，onError errorHandler）。
- `pages/specs/index.vue`（PageContainer/PageHeader + 状态/仓库 Select 过滤 + LoadingState/EmptyState + 行点击进详情）、`pages/specs/[id].vue`（状态徽标 + 关联链接区 + MarkdownRenderer 正文 + 评审时间线 + 操作区）。
- `AppSidebar` 新增 `{ to: '/specs', label: 'spec 治理', icon: 'lucide--file-check-2' }`。
- 测试：操作按钮 state×权限显隐 + transition→invalidate + 列表渲染/空态真实 zh-CN 文案（6 用例）。

## Verification

- 后端：`pytest` 41 用例（model 7 + transitions 10 + inv6 3 + api 17 + service 49-既有 4）全绿；`makemigrations --check` 无漂移；源码 `ruff` 干净。
- 前端：`vitest` spec 套件 16 用例全绿；`vue-tsc --noEmit` 0 错误；`eslint` 干净；`zh-CN.json` 合法 JSON。
- 零回归：`pytest tests/delivery/ -k sdd_spec` 不破坏 Phase 49 create_draft 链路。

## Deviations from Plan

- **[Rule 3 - 阻断修复] `[id].vue` typed-router 类型**：`route.params.id` 在 unplugin-vue-router 联合类型下报 TS2339；按既有 `[id].vue` 范式改为 `useRoute('/specs/[id]')`（typed route），vue-tsc 转绿。
- 其余按 plan + CONTEXT D-50-1..7 + UI-SPEC 实现，无架构偏差。

## Deferred / Out-of-Scope（详见 deferred-items.md）

1. **Pre-existing 测试失败**：`test_plan_session_event.py::test_all_events_equals_v07_orchestration_set` 因 Phase 49 加入 `spec.drafted` 事件后未更新该 v0.7 集合断言而失败——本 phase 未触碰 `event_taxonomy.py`，属 Phase 49 测试债，未修。
2. **Migrations ruff I001**：`delivery/migrations/0008..0019` import 排序均不满足 ruff（Django 自动生成），团队既有约定不对自动生成 migration 跑 `--fix`；`0019` 与 9 个 siblings 同形态，plan 明确禁止手改 migration 内容，故未改。建议在 ruff 配置加 `*/migrations/*` per-file-ignore。

## Known Stubs

无。所有组件均接真实数据源（specsApi / 后端 detail），无占位数据。

## Notes

- `mcp` / `skills` 子模块指针为既有 dirty 状态，全程未 stage/commit；所有提交均按文件路径精确提交。
- 前端新增组件触发的 `web/src/components.d.ts` 与 `web/src/typed-router.d.ts` 自动重生成已一并提交（diff 仅含 spec 相关条目）。
- 环境无 `gsd-tools` 二进制，STATE.md / ROADMAP.md / REQUIREMENTS.md 的 SDK 自动更新未执行；需在具备 gsd-tools 的环境补跑 state.advance / roadmap.update / requirements.mark-complete。

## Self-Check: PASSED

- 13 个任务提交均存在（git log）。
- 关键产物文件均落盘（模型/migration/views/urls/serializers/前端组件/页面/测试）。
- 后端 41 + 前端 16 测试全绿；vue-tsc/eslint/ruff(源码)/makemigrations --check 全部通过。
