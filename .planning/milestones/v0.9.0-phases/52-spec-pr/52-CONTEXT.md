# Phase 52: spec↔需求/PR 关联 + 交付验收视图 - Context

**Gathered:** 2026-06-17
**Status:** Ready for planning
**Mode:** Smart discuss (autonomous — 灰区由设计文档 + 实地读码自动决策，未向用户提问)

<domain>
## Phase Boundary

让 SDD spec 沿 spec → 需求(WorkItem) → 实现 PR 形成可追溯的交付验收闭环：编码产出的 PR 回填到 spec，用户可见交付验收视图。本里程碑收官 phase。

**In scope:**
- spec 挂接 WorkItem（Phase 49 已有 FK）+ 关联实现 PR/MR（编码产出回填）（LINK-01）
- 交付验收视图：沿 spec → WorkItem → 实现 PR 链路追溯 spec-driven 交付状态（LINK-02）
- 关联回填全程 fail-soft（链断/缺数据降级展示，不报错）

**Out of scope（本 phase）:**
- spec drift 检测（v2 SDDX-02）
- 真实容器 E2E（编码产真实 PR 回填）→ 真实环境人工验收
</domain>

<decisions>
## Implementation Decisions（smart discuss 自动决策）

### D-52-1 `SddSpec.implementation_prs` JSON 字段承载实现 PR 关联
SddSpec 加 `implementation_prs = JSONField(default=list)`，元素 `{pr_url, repository_id, linked_at}`。migration 自动生成（nullable 无回填）。spec→WorkItem 关联已由 Phase 49 `work_item` FK 承载，本 phase 只补 spec→PR。

### D-52-2 `SddSpecService.link_implementation_pr` 单一入口（INV-6）
新增 async `link_implementation_pr(*, plan_version_id, repository_id, pr_url)`：
- 按 `(plan_version_id, repository_id)` 找 SddSpec；无 → no-op（非 SDD 仓无 spec，零回归）
- 追加 PR ref（按 pr_url 去重幂等，不重复追加）
- spec 当前 `approved` → 经既有 `mark_implemented`（approved→implemented）流转（gate 保证被编码的 SDD 仓 spec 已 approved）；非 approved → 仅记 PR ref 不强转状态（记 warning，宽容）
- 单一事务 + 条件更新；状态/字段写入只经 service（INV-6）

### D-52-3 PR 回填挂接 `_finalize_and_notify`（fail-soft）
`AICodingNode._finalize_and_notify`（coding.py:1174）算出 `successful_mrs`（含 `repository_id`+`mr_url`）后，对每个 successful MR best-effort 调 `link_implementation_pr(plan_version_id, repository_id, pr_url)`：
- 非 SDD 仓（无 SddSpec）→ no-op；SDD 仓 → 回填 PR + 转 implemented
- 整段 try/except 吞为 warning `sdd_spec_pr_link_failed`，**绝不阻断 PR 创建/通知流程**（对齐 v0.8 `_finalize_and_notify` 既有 fail-soft 范式，如 cross-ref ≥2 守门）
- `plan_version_id` 取 `_finalize_and_notify` 上下文已有的 plan 锚（无则跳过）

### D-52-4 交付验收视图（LINK-02，复用 Phase 50 spec 详情页）
后端：扩 Phase 50 `SddSpecDetailSerializer` 增 `implementation_prs` + work_item 摘要（已有 work_item，补 url/title）+ plan_version 摘要——形成 spec→需求→PR 追溯数据。
前端：在 Phase 50 spec 详情页（`/specs/[id]`）**增「交付验收」追溯面板**——展示链路：WorkItem（需求，可点链接）→ spec（当前状态徽标）→ 实现 PR 列表（pr_url 可点）。复用 Phase 50 `SpecReviewTimeline` 时间线/卡片范式 + Phase 48/50 徽标。**fail-soft 渲染**：work_item/PR 缺失 → 降级显「未关联」占位，绝不报错/空白崩溃。i18n zh-CN。

### D-52-5 零回归 + fail-soft + INV-6
- 非 SDD 仓编码/PR 流程完全不受影响（link no-op，v0.8 PR 创建零回归）。
- spec→PR 写入只经 `SddSpecService`（INV-6 grep 守护扩展含 link_implementation_pr）。
- async ORM 用 `*_id` 标量 / `afirst`，禁裸 lazy-FK。
</decisions>

<code_context>
## Existing Code Insights

- **`SddSpec`**（Phase 49）：`server/delivery/models/sdd_spec.py`——已有 work_item/plan_version/repository FK + status（含 IMPLEMENTED）；本 phase 加 `implementation_prs` JSON。
- **`SddSpecService`**（Phase 49/50）：已有 `create_draft` + 状态机流转（含 `mark_implemented` approved→implemented）；本 phase 加 `link_implementation_pr`。
- **`SddSpecDetailSerializer`**（Phase 50）：`server/delivery/api/spec_*`——spec 详情含正文/评审历史/关联摘要；本 phase 扩 implementation_prs + 追溯摘要。
- **PR 创建挂接**：`AICodingNode._finalize_and_notify`（`server/workflows/nodes/ai/coding.py:1174`）——`_create_mr_for_repo` 产 MR，`successful_mrs = [r for r in mr_results if r.get("mr_url") and not r.get("error")]`（line 1210，每项含 `repository_id`/`mr_url`），≥2 时 `add_cross_references`（既有 fail-soft 范式可镜像）。在此挂 spec↔PR 回填。
- **Phase 50 前端 spec 详情页**（`web/src/pages/specs/[id].vue` + `SpecReviewTimeline.vue` + `SddSpecStatusBadge.vue`）——本 phase 增追溯面板，复用既有组件/范式 + MarkdownRenderer + TanStack Query。
- **WorkItem**（delivery）：有标题/url 字段供追溯展示（详情序列化补摘要）。
</code_context>

<specifics>
## Specific Ideas

- 后端：`SddSpec.implementation_prs` JSON 字段 + migration；`SddSpecService.link_implementation_pr`；`_finalize_and_notify` best-effort 回填；`SddSpecDetailSerializer` 扩追溯摘要。
- 前端：spec 详情页「交付验收」追溯面板（WorkItem→spec→PR 链路）+ i18n + fail-soft 降级占位。
- 守护测试：
  - 后端：link_implementation_pr SDD 仓回填+转 implemented / 非 SDD no-op / pr_url 去重幂等 / 非 approved 宽容记录不强转 / _finalize_and_notify fail-soft（link 异常不阻断 PR 通知）/ 零回归（非 SDD PR 流程不变）/ INV-6 grep / detail serializer 含 implementation_prs+追溯摘要。
  - 前端：追溯面板渲染 WorkItem→spec→PR 链路 / 缺 work_item 或 PR 降级占位（fail-soft）/ PR 链接可点 / 真实 zh-CN.json 文案。
- 后端 ruff + pytest + makemigrations --check（有新 migration：implementation_prs）；前端 vue-tsc + eslint + vitest。
- 真实容器 E2E（真实编码产 PR 回填 + 验收视图真实数据）→ human_needed deferred。
</specifics>

<deferred>
## Deferred Ideas

- spec drift 检测（实现偏离 approved spec 告警）（v2 SDDX-02）。
- 跨 work_item 的交付看板/聚合验收视图——本 phase 聚焦单 spec 详情追溯，聚合视图留 follow-up。
- spec→PR 关联接入统一 AuditEvent（v0.10）。
- 真实容器 E2E（编码产真实 PR 回填）→ 真实环境人工验收。
</deferred>
