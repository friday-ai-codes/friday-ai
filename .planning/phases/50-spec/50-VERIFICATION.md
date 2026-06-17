---
phase: 50-spec
verified: 2026-06-17T03:30:00Z
status: human_needed
score: 4/4 must-haves verified (code + automated tests); 真实浏览器视觉/E2E 待人工
re_verification:
  previous_status: none
  previous_score: n/a
human_verification:
  - test: "登录普通认证用户访问 /specs，查看 spec 列表 → 点击进详情 → 查看正文 markdown 渲染 / 评审历史时间线"
    expected: "列表按状态/仓库筛选可用；详情页正文（MarkdownRenderer）正常渲染、状态徽标 5 态色彩正确、评审时间线倒序展示 reviewer/decision/comment/time"
    why_human: "视觉渲染、markdown 排版、徽标色彩对比、时间线视觉层级无法由 grep/单测断言；需真实浏览器目测"
  - test: "以 superuser 在 in_review 详情点击「批准」/「驳回」，普通用户在同一详情查看操作区"
    expected: "superuser 见 approve/reject 按钮且弹出带 textarea 的 SpecReviewDialog（reject comment 必填空则禁用确认）；普通用户仅见「等待管理员评审」提示，不渲染 approve/reject/archive 按钮"
    why_human: "按钮按 state×权限的真实显隐、对话框交互、reject 必填禁用态需真实会话 + 浏览器交互验证（单测已覆盖逻辑分支，但真实权限会话端到端未跑）"
  - test: "完整生命周期端到端走一遍：draft → 提交评审 → 批准 → 标记已实现 → 归档，每步观察 toast 与列表/详情自动刷新"
    expected: "每次流转成功后 toast 提示对应文案、invalidateQueries 触发列表/详情即时刷新到新状态；非法流转（如已 archived 再操作）走 useErrorHandler 显示错误文案"
    why_human: "TanStack Query invalidate→真实重拉、toast 时序、跨页状态一致性属运行时实时行为，需真实后端 + 浏览器端到端确认"
  - test: "详情页关联链接区（repository / work_item / plan_version）真实数据下的展示与跳转"
    expected: "有关联时展示仓库链接（跳 /repositories/<id>）+ 方法论徽标 + 关联需求/方案文本；缺失关联项不渲染空占位"
    why_human: "关联摘要在真实 detail API 数据 + 路由跳转下的展示/缺省降级需浏览器目测（序列化器 get_relations 已验证缺失项不输出）"
---

# Phase 50: spec 状态机 + 变更记录 + 评审状态 + 前端展示 Verification Report

**Phase Goal:** spec 具备完整可治理生命周期，评审留痕、用户可见可操作
**Verified:** 2026-06-17T03:30:00Z
**Status:** human_needed
**Re-verification:** No — initial verification

## Goal Achievement

### Observable Truths

| #   | Truth | Status | Evidence |
| --- | ----- | ------ | -------- |
| 1 | **SPECST-01** spec 经单一 service 入口完成 `draft→in_review→approved→implemented→archived` 状态流转，非法流转被拒、防双推进幂等 | ✓ VERIFIED | `sdd_spec_service.py:52-148` 合法流转表 + `.filter(status=from).update(status=to)` 影响行数判定，0 行 → `SddSpecTransitionError`（line 96-103, 111-112, 121-122, 147-148）；`archive` 任意非 archived → archived（line 114-122）。`SddSpecService` 是唯一写入入口（INV-6 grep 守护 `test_sdd_spec_inv6_guard.py`，3 用例通过）。后端 76 用例含 transitions/idempotent/atomic 全绿 |
| 2 | **SPECST-02** spec 评审产生不可篡改记录（reviewer/decision/comment/time），审批驱动状态、单一事务建记录+流转 | ✓ VERIFIED | `sdd_spec_review.py` append-only：模型层零 edit/delete/update 业务写方法（仅 `__str__`），FK CASCADE/SET_NULL、ordering `-created_at`、`decision` approve/reject 枚举。`_review_transition`（service line 124-148）`transaction.atomic` 内先建评审再条件更新，0 行 raise → 回滚评审（无孤儿）。INV-6 守护扩展覆盖 `SddSpecReview` 旁路写（3 正则 + 有效性反向用例） |
| 3 | **SPECST-03 后端** `/api/specs/` list+detail+transition + 权限分流（approve/reject/archive/mark_implemented=superuser） | ✓ VERIFIED | `spec_views.py`：`SpecListView`(IsAuthenticated, ?status/?repository_id 过滤前置 400)、`SpecDetailView`(404 中性)、`SpecTransitionView`(action 级 `_RESTRICTED_ACTIONS` superuser 分流 line 133-137 fail-closed；reviewer=request.user；reject comment 必填；非法流转 400/不存在 404)；序列化器全 read_only（`SddSpecDetailSerializer` body/reviews/relations，缺失项不输出）。挂载 `friday/urls.py:66`。`test_spec_api.py` 17 用例全绿 |
| 4 | **SPECST-03 前端** spec 列表/详情/评审历史/状态流转操作按状态+权限显隐 | ✓ VERIFIED（code+unit）/ ⚠ 视觉与 E2E 待人工 | `pages/specs/index.vue`（过滤+列表+徽标+点击进详情+空/错/加载态）、`[id].vue`（正文 MarkdownRenderer+关联链接+评审时间线+操作区）、`SpecTransitionActions.vue`（state×权限矩阵 canSubmit/canApprove/.../showAwaiting + useMutation→invalidate+toast/errorHandler）、`SpecReviewDialog.vue`（reject comment 必填禁用）；`api/specs.ts` 接真实端点；i18n `specs` 命名空间 + 侧边栏入口 `AppSidebar.vue:88`。前端 16 用例全绿；真实浏览器渲染/交互未跑（见下） |

**Score:** 4/4 truths verified（代码 + 自动化测试层面）；真实浏览器视觉/端到端交互转人工。

### Required Artifacts

| Artifact | Expected | Status | Details |
| -------- | -------- | ------ | ------- |
| `server/delivery/models/sdd_spec_review.py` | append-only 评审模型 + ReviewDecision | ✓ VERIFIED | 67 行，零业务写方法，FK/枚举/ordering 完整 |
| `server/delivery/services/sdd_spec_service.py` | 5 流转方法 + SddSpecTransitionError | ✓ VERIFIED | 232 行，合法表+条件更新+原子评审事务 |
| `server/delivery/api/spec_views.py` | list/detail/transition + 权限分流 | ✓ VERIFIED | 174 行，fail-closed superuser 分流 |
| `server/delivery/spec_urls.py` + `friday/urls.py` | `/api/specs/` 路由挂载 | ✓ VERIFIED | spec_urls 3 路由 + urls.py:66 include |
| `server/delivery/api/serializers.py` | List/Detail/Review 全 read_only | ✓ VERIFIED | line 145-241，body/reviews/relations SerializerMethodField |
| `server/delivery/migrations/0019_sddspecreview.py` | 建表 migration | ✓ VERIFIED | 存在，`makemigrations --check` 无漂移 |
| `web/src/api/specs.ts` | API client + TS 类型 | ✓ VERIFIED | list/detail/transition + 契约对齐类型 |
| `web/src/pages/specs/{index,[id]}.vue` | 列表/详情页 | ✓ VERIFIED | reuse-first，接真实数据源 |
| `web/src/components/spec/*.vue` | 徽标/时间线/操作/对话框 4 组件 | ✓ VERIFIED | 全部落盘且被引用 |

### Key Link Verification

| From | To | Via | Status | Details |
| ---- | -- | --- | ------ | ------- |
| `SpecTransitionView` | `SddSpecService` | action→service 方法分派 | ✓ WIRED | spec_views.py:153-164 |
| `SddSpecService.approve/reject` | `SddSpecReview` | transaction.atomic create+update | ✓ WIRED | service line 124-148（唯一写入点） |
| `specs.ts` | `/api/specs/` | get/post client | ✓ WIRED | specs.ts:70-81 |
| `index.vue/[id].vue` | `specsApi` | useQuery list/detail | ✓ WIRED | data 渲染至列表/详情 |
| `SpecTransitionActions` | `specsApi.transition` | useMutation→invalidate(['specs']/['spec',id])+toast | ✓ WIRED | SpecTransitionActions.vue:36-56 |
| `[id].vue` | `SpecTransitionActions/SpecReviewTimeline/SpecReviewDialog` | 子组件组合 | ✓ WIRED | [id].vue:84-95 |
| `AppSidebar` | `/specs` | 导航入口 | ✓ WIRED | AppSidebar.vue:88 |

### Data-Flow Trace (Level 4)

| Artifact | Data Variable | Source | Produces Real Data | Status |
| -------- | ------------- | ------ | ------------------ | ------ |
| `index.vue` | `specs` | `specsApi.list` → `SpecListView` ORM 查询 | Yes（真实 ORM queryset，非静态） | ✓ FLOWING |
| `[id].vue` | `spec` | `specsApi.detail` → `SpecDetailView` select_related/prefetch | Yes（含 body/reviews/relations） | ✓ FLOWING |
| `SpecReviewTimeline` | `reviews` | detail.reviews（嵌套序列化器，模型 ordering 倒序） | Yes（真实评审记录） | ✓ FLOWING |

### Behavioral Spot-Checks

| Behavior | Command | Result | Status |
| -------- | ------- | ------ | ------ |
| 后端 spec 相关测试 | `uv run pytest tests/delivery/ -k "sdd_spec or transition or review or spec_api or inv6"` | 76 passed, 286 deselected | ✓ PASS |
| migration 无漂移 | `manage.py makemigrations --check --dry-run` | No changes detected | ✓ PASS |
| 前端 spec 套件 | `pnpm vitest run src/components/spec src/pages/specs` | 16 passed (4 files) | ✓ PASS |
| 前端类型检查 | `pnpm vue-tsc --noEmit` | EXIT 0, 0 error TS | ✓ PASS |
| 前端 lint | `pnpm eslint src/api/specs.ts src/components/spec src/pages/specs` | 干净（exit 0） | ✓ PASS |

### Requirements Coverage

| Requirement | Source Plan | Description | Status | Evidence |
| ----------- | ----------- | ----------- | ------ | -------- |
| SPECST-01 | 50-02 | 状态机单一入口 + 非法流转拒绝 | ✓ SATISFIED | service 合法表 + 影响行数判定 + 测试 |
| SPECST-02 | 50-01/50-02 | append-only 评审 + 审批驱动状态 | ✓ SATISFIED | 模型零写方法 + 单一事务 + INV-6 守护 |
| SPECST-03 | 50-03/04/05 | 前端可见列表/详情/状态/评审 + 发起流转 | ✓ SATISFIED（后端+前端代码/单测）；真实浏览器交互 → human_needed | API + 页面 + 组件 + 16 前端单测 |

### Anti-Patterns Found

| File | Line | Pattern | Severity | Impact |
| ---- | ---- | ------- | -------- | ------ |
| — | — | 未发现新增 TODO/FIXME/XXX/占位/空实现 | ℹ️ Info | SUMMARY「Known Stubs: 无」经抽查属实；所有组件接真实数据源 |
| `delivery/migrations/0008..0019` | import | ruff I001（自动生成 migration 排序） | ℹ️ Info | Pre-existing，0019 与 9 个 siblings 同形态；属团队既有约定（不对自动生成 migration 跑 --fix），非本 phase 引入 |
| `test_plan_session_event.py::test_all_events_equals_v07_orchestration_set` | — | Phase 49 遗留测试债（`spec.drafted` 未纳入 v0.7 集合） | ℹ️ Info | 本 phase 未触碰 event_taxonomy.py，deselected，与 spec 状态机/评审/前端无关 |

### Human Verification Required

按用户明确要求，真实浏览器视觉与端到端交互标 human_needed：

#### 1. 列表 → 详情视觉渲染
**Test:** 登录普通认证用户访问 `/specs`，查看列表 → 点击进详情 → 查看正文 markdown 渲染 / 评审历史时间线
**Expected:** 列表按状态/仓库筛选可用；详情正文 MarkdownRenderer 正常渲染、状态徽标 5 态色彩正确、评审时间线倒序展示 reviewer/decision/comment/time
**Why human:** 视觉渲染、markdown 排版、徽标色彩对比、时间线层级无法由 grep/单测断言

#### 2. 权限显隐 + 评审对话框
**Test:** superuser 在 in_review 详情点「批准」/「驳回」；普通用户在同详情查看操作区
**Expected:** superuser 见 approve/reject 并弹出带 textarea 的对话框（reject comment 必填空则禁用确认）；普通用户仅见「等待管理员评审」，不渲染 approve/reject/archive
**Why human:** 真实权限会话下 state×权限显隐、对话框交互、reject 必填禁用态的端到端验证

#### 3. 生命周期端到端 + toast/刷新
**Test:** draft → 提交评审 → 批准 → 标记已实现 → 归档，逐步观察 toast 与列表/详情自动刷新
**Expected:** 每步成功 toast 文案正确、invalidate 触发即时刷新到新状态；非法流转走 errorHandler 错误文案
**Why human:** invalidate→真实重拉、toast 时序、跨页状态一致性属运行时实时行为

#### 4. 关联链接区真实数据展示与跳转
**Test:** 详情页 repository/work_item/plan_version 关联区在真实数据下的展示与跳转
**Expected:** 有关联展示链接（跳 `/repositories/<id>`）+ 方法论徽标 + 文本；缺失项不渲染空占位
**Why human:** 关联摘要在真实 detail API + 路由跳转下的展示/降级需浏览器目测

### Gaps Summary

无阻断性 gap。SPECST-01/02/03 三需求在代码层与自动化测试层（后端 76、前端 16、vue-tsc 0 错、eslint 干净、makemigrations 无漂移）均已交付且实证通过：状态机单一入口 + 非法流转 fail-loud + 防双推进幂等成立；评审 append-only + 单一事务原子驱动状态成立；REST 端点权限 fail-closed 分流成立；前端列表/详情/评审/流转 UI 接真实数据源并按状态×权限显隐。

唯一未自动覆盖的是真实浏览器视觉渲染与端到端交互（SPECST-03 的用户可见可操作的最终目测），按指令归入 human_needed。SUMMARY 列举的两项 deferred（Phase 49 event taxonomy 测试债、自动生成 migration 的 ruff I001）经核实均为 pre-existing、与本 phase 范围无关，不构成 gap。

---

_Verified: 2026-06-17T03:30:00Z_
_Verifier: Claude (gsd-verifier)_
