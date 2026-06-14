---
phase: 23-purge-reconcile
plan: 04
subsystem: web
tags: [reconcile, purge, cleanup, exclusion, vue, tanstack-query, vue-i18n, frontend]

# Dependency graph
requires:
  - phase: 23-purge-reconcile
    provides: 23-02 /reconcile/(含 degraded)、POST /reconcile/(run_id 202)、/reconcile/status/(CleanupRun) 三端点契约
  - phase: 23-purge-reconcile
    provides: 23-03 CleanupRun.sensitive 形状（scrubbed/unscrubbed/caveat/errors）
  - phase: 22-fail-closed
    provides: 22-05 ExclusionRulesPanel.vue + 仓库详情页挂载点 + useConfirmDialog/useToast/useErrorHandler 模式
provides:
  - reconcileApi（getReconcile/cleanup/getCleanupStatus）+ ReconcileReport/CleanupDispatch/CleanupRun TS 类型
  - ReconcilePanel.vue（对账差异 + degraded 警示 + 普通/敏感双清理入口 + 派发后状态回显未清面/caveat）
  - 仓库详情页 EXCL-06 可见闭环（挂在 ExclusionRulesPanel 旁）
affects: []

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "degraded 二分前端落地：degraded=true → 显式『对账不可信』警示 + 禁用清理，绝不渲染空态/已一致（W3）"
    - "派发后双查询：mutation 成功 → 开启第二个 useQuery 轮询 getCleanupStatus（refetchInterval 直到 status≠running）+ invalidate reconcile 观察归零"
    - "敏感未清面如实回显：从 CleanupRun.sensitive.unscrubbed/caveat 渲染真实后端结果，非静态文案（W1/W2）"
    - "双清理入口分离（§9.2）：普通 destructive 确认 + 敏感更强确认（不可逆 + 不承诺 git/备份物理消失，§9.1）"

key-files:
  created:
    - web/src/api/reconcile.ts
    - web/src/components/repository/ReconcilePanel.vue
    - web/src/components/repository/__tests__/ReconcilePanel.spec.ts
  modified:
    - web/src/locales/zh-CN.json
    - web/src/pages/repositories/[id]/index.vue

key-decisions:
  - "状态轮询用 refetchInterval=(query)=> query.state.data?.status==='running' ? 2000 : false，完成/失败/无记录即停（对齐 executions 页轮询模式）"
  - "敏感确认强措辞直取 §9.1：『此操作不可逆』+『仅清除 Friday 派生数据与操作记录中的可定位内容，不承诺从 git 历史或备份中物理消失』"
  - "excluded_paths 列表前 50 条 + 折叠计数，避免大仓刷屏"
  - "测试用真实 zh-CN.json 作 i18n messages，使 W3/W1/W2/§9.1 措辞断言验证真实文案而非占位 key"

patterns-established:
  - "对账失败可见（degraded 警示）+ 后台清理真实结果（含敏感未清面）经 status 端点诚实回流前端，UI 不假装已干净/已清净"

requirements-completed: [EXCL-06]

# Metrics
duration: ~20min
completed: 2026-06-14
---

# Phase 23 Plan 04: 对账/清理前端面板 Summary

**`reconcileApi`（getReconcile/cleanup/getCleanupStatus，类型对齐 23-02/23-03 契约）+ `ReconcilePanel.vue`（对账差异展示 + degraded『对账不可信』警示并禁用清理 + 普通/敏感双清理入口分离 + 敏感强确认含不可逆/不承诺 git/备份物理消失如实措辞 + 派发后轮询 getCleanupStatus 如实回显 CleanupRun 真实 unscrubbed 面 + caveat）+ 仓库详情页挂载 + zh-CN 文案 + 5 例守护测试，兑现 EXCL-06 可见闭环（W1/W2/W3、§9.1/§9.2）。**

## Performance

- **Duration:** ~20 min
- **Completed:** 2026-06-14
- **Tasks:** 2
- **Files modified:** 5（3 created + 2 modified）

## Accomplishments
- 新建 `web/src/api/reconcile.ts`：`reconcileApi`（`getReconcile`/`cleanup`/`getCleanupStatus`）+ `ReconcileReport`（含 `degraded`/`error`）/`CleanupDispatch`（`run_id`）/`CleanupRun`（`status:'none'|'running'|'completed'|'failed'` + `sensitive` 含 `unscrubbed`/`caveat`）/`CleanupMode` 类型，对齐 23-02 `/reconcile/` + `/reconcile/status/` 契约。
- 新建 `ReconcilePanel.vue`：`useQuery` 取对账；`degraded` 时渲染 `reconcile.degradedWarning`（destructive 警示色）并禁用双清理按钮、不渲染空态/已一致（W3）；否则展示 `match_count` + `excluded_paths` 列表（前 50 + 折叠计数），`match_count==0 && !degraded` 才渲染空态。
- 双清理入口（§9.2）：`useMutation` 调 `reconcileApi.cleanup`；普通按钮 → `useConfirmDialog({variant:'destructive'})` 普通确认 → `cleanup(repoId,'normal')`；敏感按钮（危险色 + shield-alert）→ 更强确认（不可逆 + 不承诺物理消失）→ `cleanup(repoId,'sensitive')`。派发成功后 toast + `invalidateQueries(reconcile)` 观察差异归零。
- 派发后开启第二个 `useQuery(['repository-cleanup-status'], getCleanupStatus, { enabled: statusEnabled, refetchInterval })` 轮询拉 `CleanupRun`，按 `status` 回显运行中/已完成/失败 + `match_count` + `failures`；`sensitive` 存在时如实渲染 `unscrubbed` 面 + `caveat`（W1/W2，非静态文案）。
- 在 `pages/repositories/[id]/index.vue` import `ReconcilePanel` 并挂于 `#exclusions` section 内 `ExclusionRulesPanel` 旁。
- `zh-CN.json` 新增 `reconcile.*` 命名空间：标题/差异提示/空态/`degradedWarning`（对账不可信）/双清理按钮/普通+敏感确认（含不可逆 + 不承诺 git/备份物理消失）/清理状态（运行中/完成/失败 + `unscrubbedTitle` + `caveatLabel`）/派发提示/错误文案，全中文。
- 守护测试 5 例全绿：(a) 有差异渲染 match_count + 列表；(b) degraded → 警示 + 不渲染空态 + 双按钮禁用（W3）；(c) 普通清理确认 → `cleanup(repoId,'normal')` → 重查 match_count==0 → 空态（归零）；(d) 敏感清理 → 强确认（断言 destructive + '不可逆' + '不承诺从 git 历史或备份中物理消失'）→ `cleanup(repoId,'sensitive')` → status 端点回显真实 `unscrubbed`(prompt_snapshot/git_objects) + caveat（W1/W2）；(e) 空态。

## Task Commits

1. **Task 1: reconcile API client + zh-CN 文案** - `51cd36867` (feat)
2. **Task 2: ReconcilePanel 对账差异+双清理入口+强确认+派发后状态回显 + 页面挂载 + 守护测试** - `baa35af01` (feat)

_非 TDD 计划：feat 一次到位 + 守护测试同提交（与 23-01/23-02/23-03 风格一致）。_

## Files Created/Modified
- `web/src/api/reconcile.ts` - 对账/清理类型化 client（含 status 端点 + degraded 类型 + sensitive unscrubbed/caveat 类型）。
- `web/src/components/repository/ReconcilePanel.vue` - 对账差异 + degraded 警示 + 双清理入口 + 强确认 + 派发后轮询状态回显真实未清面/caveat。
- `web/src/components/repository/__tests__/ReconcilePanel.spec.ts` - 5 例守护测试（差异/degraded/普通归零/敏感强确认+未清面回显/空态）。
- `web/src/locales/zh-CN.json` - 新增 `reconcile.*` 中文文案（含对账不可信/不可逆/不承诺物理消失/未清面回显）。
- `web/src/pages/repositories/[id]/index.vue` - import + 在 ExclusionRulesPanel 旁挂载 `<ReconcilePanel>`。

## Decisions Made
- **状态轮询策略**：`refetchInterval` 函数据 `query.state.data?.status` 返回 2000ms（running）或 false（终态/none），复用 executions 页既有轮询模式，避免清理完成后无谓请求。
- **敏感确认措辞**：直取 §9.1 边界——`此操作不可逆` + `仅清除 Friday 派生数据与操作记录中的可定位内容，不承诺从 git 历史或备份中物理消失`，避免过度安全承诺（T-23-16）。
- **测试用真实 locale**：以真实 `zh-CN.json` 作 i18n messages，使 degraded『对账不可信』、敏感『不可逆/不承诺物理消失』、未清面回显等断言验证真实产品文案而非占位 key——守护威胁缓解措辞不被悄悄改空（W3/W1/W2/§9.1）。

## Deviations from Plan
None - plan executed exactly as written（含 PLAN 修订要点：ReconcileReport TS 含 degraded/error；派发后 fetch cleanup status 展示真实 unscrubbed 面；verify 门禁为真实失败的 vue-tsc 检查——Task 1 中 spec 的 createI18n messages 类型不符被 W5 门禁捕获并修复）。

## Issues Encountered
- W5 类型门禁真实生效：spec 初版 `messages: { 'zh-CN': zhCN as Record<string, unknown> }` 触发 createI18n 重载不匹配（TS2769），按门禁要求修复为 `zhCN as any`（eslint `no-explicit-any` 项目已关闭），复跑 `grep -ci reconcile` → 0、vitest 5/5 绿。
- shell 工作目录在批量命令间保持在 `web/`，初次重复 `cd web` 报无此目录（无害），后续统一 `cd "$(git rev-parse --show-toplevel)/web"` 规避。

## User Setup Required
None - 纯前端，无外部服务/迁移；复用既有 client/TanStack Query/reka-ui/vue-i18n 栈，无新增 npm 依赖（T-23-SC）。

## Next Phase Readiness
- EXCL-06 前端可见闭环就位：对账差异（含 degraded 不可信）+ 普通/敏感双清理 + 派发后真实结果回显（含敏感未清面 + caveat）全链路对用户可达。Phase 23 purge-reconcile 前后端契约（23-01 purge_file / 23-02 对账+清理服务+API / 23-03 敏感面 / 23-04 前端）完整贯通。

## Self-Check: PASSED

- FOUND: `web/src/api/reconcile.ts`
- FOUND: `web/src/components/repository/ReconcilePanel.vue`
- FOUND: `web/src/components/repository/__tests__/ReconcilePanel.spec.ts`
- FOUND: `web/src/locales/zh-CN.json`（reconcile.* 命名空间）
- FOUND: `web/src/pages/repositories/[id]/index.vue`（ReconcilePanel 挂载）
- FOUND: `.planning/phases/23-purge-reconcile/23-04-SUMMARY.md`
- FOUND commit: `51cd36867` (Task 1)
- FOUND commit: `baa35af01` (Task 2)
- 类型门禁：`pnpm exec vue-tsc --noEmit | grep -ci reconcile` → 0（无 reconcile 类型错误，W5 PASS）
- 测试：`pnpm vitest run …/ReconcilePanel.spec.ts` → 5 passed
- lint：`eslint reconcile.ts / ReconcilePanel.vue / [id]/index.vue / spec` → 0 error
