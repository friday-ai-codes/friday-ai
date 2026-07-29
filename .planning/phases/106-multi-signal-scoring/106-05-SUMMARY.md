---
phase: 106-multi-signal-scoring
plan: 05
subsystem: ui
tags: [vue, repo-router, weight-config, settings-ui, routing-panel, reka-ui, vitest]

# Dependency graph
requires:
  - phase: 106-multi-signal-scoring/106-02
    provides: RepoRouterWeightConfigView GET/PUT 契约（GET 全量配置 + is_default；PUT 400 逐条 errors）、WEIGHT_GRID 网格与 INV-R2/常数校验口径
provides:
  - getRepoRouterWeightConfig / putRepoRouterWeightConfig API 函数 + RepoRouterWeightConfig TS 类型（web/src/api/settings.ts，专用端点，不走通用 per-key API）
  - RepoRouterWeightSettings.vue 设置区（五权重网格下拉 + 十关键常数 + t2_disabled_facets + 版本号编辑 + 前端预校验 + 400 errors 逐条渲染），挂载于 admin RAG tab
  - RoutingDecisionPanel SIGNAL_LABELS 新键 domain/stack/team（业务域匹配/技术栈匹配/团队归属），未知 key 英文回退保留
affects: [106-06, 106-07, phase-107]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "专用校验端点的设置区模式：强校验配置不走通用 per-key updateSetting，组件保存后重新 GET 回读以后端规范化结果为准"
    - "UI 只编辑关键字段子集时，非编辑字段随 GET 回读原样带回 PUT payload——防止后端 merge 语义把未编辑常数重置为默认"

key-files:
  created:
    - web/src/components/settings/RepoRouterWeightSettings.vue
  modified:
    - web/src/api/settings.ts
    - web/src/pages/admin/index.vue
    - web/src/components/chat/RoutingDecisionPanel.vue
    - web/src/components/chat/__tests__/RoutingDecisionPanel.test.ts

key-decisions:
  - "PUT payload 剥离 is_default：后端 validate_weight_config 拒绝未知顶层键（is_default 是 GET 附加字段不在 DEFAULT_WEIGHT_CONFIG），API 函数签名用 Omit 编译期防带出"
  - "UI 未编辑常数（p/activity_floor/deprecated_cap/n_bar/锚点表/crit_weight_reserved 等）随 GET 回读原样带回，只覆盖 10 个关键常数——避免部分 payload 被后端 merge 语义重置"
  - "权重下拉用字符串值绑定 reka-ui Select（String(网格值) 双向一致），保存时统一 Number() 解析——规避 AcceptableValue 数值/字符串混型"

patterns-established:
  - "网格约束前置到 UI 控件：权重只给下拉不给自由输入，网格外取值在交互层即不可达（INV-R2/区间预校验另做内联提示）"

requirements-completed: [ROUTE-06, ROUTE-04]

coverage:
  - id: D1
    description: "运维权重编辑面：superuser 在管理页读到当前生效配置（含默认态标注）、改权重/常数/版本号并保存，保存后 GET 回读、400 错误逐条展示"
    requirement: ROUTE-06
    verification:
      - kind: other
        ref: "pnpm vue-tsc --noEmit（零类型错误）+ CI 模式 eslint 三文件零告警"
        status: pass
      - kind: other
        ref: "rg 验收：repo-router/weight-config ×2（GET/PUT）、组件内零 updateSetting、admin 挂载 ×2、WEIGHT_GRID_OPTIONS 与后端网格字面一致（10 值）"
        status: pass
    human_judgment: true
    rationale: "设置区读/改/存/错误反馈的实际交互无组件级自动化测试（plan verify 仅静态检查）；表单可用性与错误提示可读性需人工在管理页操作确认"
  - id: D2
    description: "RoutingDecisionPanel 分数分解对新信号 domain/stack/team 显示中文标签；未知 key 回退英文原名；Σbreakdown==score 候选无容差告警"
    requirement: ROUTE-04
    verification:
      - kind: unit
        ref: "web/src/components/chat/__tests__/RoutingDecisionPanel.test.ts（12 passed：新增 2 条六信号标签/回退+无告警用例，既有 10 条零改动通过）"
        status: pass
    human_judgment: false

# Metrics
duration: ~11min
completed: 2026-07-29
status: complete
---

# Phase 106 Plan 05: 前端权重设置区 + 新信号标签 Summary

**仓库路由权重运维操作面上线：`RepoRouterWeightSettings.vue`（五权重离散网格下拉 + 十关键常数 + INV-R2/区间前端预校验 + 400 errors 逐条渲染，走 106-02 专用校验端点）挂进 admin RAG tab；`RoutingDecisionPanel` 分数分解补 domain/stack/team 中文标签，未知 key 英文回退保留**

## Performance

- **Duration:** ~11 min
- **Started:** 2026-07-29T09:58:35Z
- **Completed:** 2026-07-29T10:09:28Z
- **Tasks:** 2
- **Files modified:** 5（+ deferred-items.md 挂账 1 条）

## Accomplishments

- `web/src/api/settings.ts`：`RepoRouterWeightConfig` 接口（与后端 `DEFAULT_WEIGHT_CONFIG` 全字段对齐 + GET 独有 `is_default`）与 `getRepoRouterWeightConfig` / `putRepoRouterWeightConfig`（PUT 类型 `Omit<…, 'is_default'>` 编译期防止把 GET 附加字段带回被后端拒）；不新增 SettingKey enum 值。
- `RepoRouterWeightSettings.vue`（431 行，照 RerankSettings 骨架）：加载/保存/错误态；顶部 `weight_set_version` 可编辑 + `is_default` 「当前为内置默认值」徽标；五权重下拉（`WEIGHT_GRID_OPTIONS` 与后端 `WEIGHT_GRID` 字面一致 10 值，无自由输入）；lam/b/n_cap/half_life_days/offset_days/crit_band/s_top_c_lo/s_top_c_hi/t2_c_lo/t2_c_hi 数字输入；`t2_disabled_facets` 逗号分隔（兼容中文逗号）。
- 前端预校验（保存按钮前置拦截 + 内联提示，后端为准）：INV-R2 相对形式（元数据三权重和 > 五权重总和一半 → 「文本证据必须占主导（INV-R2）」）、两组 `c_lo >= c_hi` 区间非法、常数非数值、版本号非空；改权重未改版本号时琥珀色提示「不同版本的路由结果不可比」。
- 保存成功 → toast「下一次路由立即生效，无需发版」→ 重新 GET 回读规范化结果；400 时解析 `ApiError.body.errors` 逐条渲染。
- `RoutingDecisionPanel.vue` `SIGNAL_LABELS` 追加 `domain: '业务域匹配'` / `stack: '技术栈匹配'` / `team: '团队归属'`（键与后端 `SIGNAL_DOMAIN/SIGNAL_STACK/SIGNAL_TEAM` 字面对齐）；注释更新为六信号已入分、criticality 旁路无标签。
- vitest 新增 2 条用例（值取二进制精确小数使 Σbreakdown === score）：六信号 breakdown 渲染全部中文标签 + 行数断言；未知 key `future_signal` 英文回退 + 无容差告警。12/12 全绿，既有 10 条零改动。

## Task Commits

Each task was committed atomically:

1. **Task 1: 权重配置 API 函数 + RepoRouterWeightSettings 设置区 + admin 挂载** - `a984c281` (feat)
2. **Task 2: RoutingDecisionPanel 新信号标签 + vitest 更新** - `7448d6f7` (feat)

## Files Created/Modified

- `web/src/components/settings/RepoRouterWeightSettings.vue` - 权重配置设置区（表单 + 网格下拉 + 前端预校验 + 保存回读）
- `web/src/api/settings.ts` - RepoRouterWeightConfig 类型 + get/put 专用端点函数 + 默认导出扩充
- `web/src/pages/admin/index.vue` - RAG tab 挂载 RepoRouterWeightSettings（与 RerankSettings 并列）
- `web/src/components/chat/RoutingDecisionPanel.vue` - SIGNAL_LABELS 三新键 + 注释更新
- `web/src/components/chat/__tests__/RoutingDecisionPanel.test.ts` - 新增 Phase 106 新信号标签 describe（2 用例）
- `.planning/phases/106-multi-signal-scoring/deferred-items.md` - 挂账既有 test/prefer-lowercase-title lint 项

## Decisions Made

- **PUT payload 剥离 `is_default`**：后端 `validate_weight_config` 对未知顶层键报错，而 `is_default` 是 GET 响应附加字段——API 函数参数类型 `Omit<RepoRouterWeightConfig, 'is_default'>` + 组件 buildPayload 解构剔除，双层防护。
- **非编辑字段原样带回**：后端 `_validate_constants` 以 DEFAULT 为基底 merge，若只发 10 个编辑过的常数，用户此前对 p/activity_floor 等的定制会被静默重置——组件保留完整 GET 回读对象，PUT 时在其上覆盖编辑字段。
- **接口字段全量对齐后端**：plan 字面列 6 字段，实际补齐 `crit_weight_reserved`/`embedding_model_id`/`calibrated_at`（GET 返回全量配置，缺字段会在「原样带回」时丢失）。
- **Select 字符串绑定**：网格值经 `String()` 双向一致（`String(0.10)`→`'0.1'` 加载与选项同构），展示用 `toFixed(2)`。

## Deviations from Plan

None - plan executed exactly as written.

（scope boundary 挂账 1 条非 deviation：见 Issues Encountered。）

## Issues Encountered

- **既有 CI-mode-only lint 错误**：`RoutingDecisionPanel.test.ts` L265 `it('Σbreakdown …')` 标题触发 `test/prefer-lowercase-title`（Σ 计为大写字母；编辑器模式该规则禁用，HEAD 版本原样存在）。本 plan 未触碰该行，且 plan verification 的 eslint 命令不含测试文件——按 scope boundary 记入 `deferred-items.md`，未就地修复。

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness

- ROUTE-06 运维触面闭环：权重/常数改动从管理页到「下一次路由生效」全链路就位（后端 106-02 校验 + 前端本 plan 操作面）。
- ROUTE-04 展示面就位：106-06 router 接线后新信号进 breakdown 即有中文标签，无需前端跟随改动。
- facet 来源层 T1/T2 的 UI 展示按 RESEARCH §10 裁决留给 Phase 107（本 phase 只落数据）。

## Self-Check: PASSED

- FOUND: web/src/components/settings/RepoRouterWeightSettings.vue
- FOUND: web/src/api/settings.ts（getRepoRouterWeightConfig/putRepoRouterWeightConfig）
- FOUND: commit a984c281（feat，Task 1）
- FOUND: commit 7448d6f7（feat，Task 2）
- PASS: vue-tsc --noEmit 零错误；eslint（CI 模式）三验证文件零告警
- PASS: vitest 12/12（新增 2 条）
- PASS: 验收 grep——repo-router/weight-config ×2、组件零 updateSetting、admin 挂载、网格 10 值字面一致、中文标签 ×3

---
*Phase: 106-multi-signal-scoring*
*Completed: 2026-07-29*
