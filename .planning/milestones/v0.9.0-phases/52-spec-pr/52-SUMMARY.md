---
phase: 52-spec-pr
plans: [52-01, 52-02, 52-03]
subsystem: [api, ui]
tags: [sdd-spec, pr-link, delivery-acceptance, traceability, fail-soft, inv-6, link-01, link-02]

requires:
  - phase: 49-sdd-spec
    provides: SddSpec 脊柱 + SddSpecService 写入收口（INV-6）+ work_item FK
  - phase: 50-spec-governance
    provides: SddSpecService 状态机（mark_implemented）+ spec 详情页 / 徽标 / 时间线范式
  - phase: 44-coding-wave
    provides: AICodingNode._finalize_and_notify successful_mrs 收尾链路
provides:
  - spec→实现 PR 关联写入侧（implementation_prs + link_implementation_pr + 收尾回填挂接）
  - spec→需求→PR 追溯只读 API（SddSpecDetailSerializer 扩展）
  - 交付验收追溯视图（SpecDeliveryPanel 前端面板）
affects: []

requirements-completed: [LINK-01, LINK-02]

duration: 28min
completed: 2026-06-17
---

# Phase 52: spec↔需求/PR 关联 + 交付验收视图 Summary（收官 phase）

**让 SDD spec 沿 spec → 需求(WorkItem) → 实现 PR 形成可追溯交付验收闭环：编码产出的 PR 经单一写入入口幂等回填到 spec（approved→implemented），detail API 暴露完整追溯 JSON，前端 SpecDeliveryPanel 沿链路 fail-soft 渲染交付验收视图——非 SDD 仓全链路零回归**

## Performance

- **Duration:** ~28 min（3 plans / 2 waves）
- **Completed:** 2026-06-17
- **Tasks:** 7（Plan 01: 3 / Plan 02: 1 / Plan 03: 3）
- **Files modified:** 13（7 created + 6 modified）

## Plan Breakdown

| Plan | Wave | 内容 | 提交 |
|------|------|------|------|
| 52-01 | 1 | 后端写入侧：implementation_prs 字段 + migration 0020 + link_implementation_pr 单一写入入口 + _finalize_and_notify best-effort fail-soft 回填（LINK-01） | `352127eb`, `ffda84a9`, `22a8e318` |
| 52-02 | 2 | 后端追溯只读：SddSpecDetailSerializer 扩 implementation_prs + work_item url + plan_version 摘要（LINK-01/LINK-02） | `27dde7de` |
| 52-03 | 1 | 前端交付验收：specs.ts 契约 + zh-CN 文案 + SpecDeliveryPanel + [id].vue 挂接 + vitest（LINK-02） | `b8e7035d`, `f584a579`, `5f9f4f44` |

## Accomplishments
- **写入侧（LINK-01）**：`SddSpec.implementation_prs` JSON 字段（`{pr_url, repository_id, linked_at}`）+ migration 0020；`SddSpecService.link_implementation_pr` 单一写入入口——`select_for_update` 命中 SddSpec → pr_url 去重幂等追加；approved → 复用 `mark_implemented` 源/目标常量同事务条件更新转 implemented，非 approved 宽容记录不强转（warning）；无 spec（非 SDD 仓）→ no-op 零回归；INV-6 收口。
- **回填挂接（LINK-01）**：`AICodingNode._finalize_and_notify` 算出 `successful_mrs` 后逐 MR best-effort 调 `link_implementation_pr`，整段 try/except 吞为 warning `sdd_spec_pr_link_failed`，绝不阻断 PR 创建/通知/节点完成；`plan_version_id` 缺失零回归。
- **追溯 API（LINK-01/LINK-02）**：`SddSpecDetailSerializer` 暴露 `implementation_prs`（无回填→[]）+ `relations.work_item.url`（取 prd_url，不臆造）+ `plan_version` 摘要；缺数据降级（省键/空列表）。
- **交付验收视图（LINK-02）**：`SpecDeliveryPanel.vue` 沿 WorkItem（可点 prd_url）→ spec（状态徽标）→ 实现 PR 列表（pr_url 可点）渲染；fail-soft 降级真实中文占位；外链 `:href` + `rel=noopener`（规避注入）；真实 zh-CN.json 文案接通。

## Verification
- **后端**：`test_sdd_spec_pr_link.py`（8）+ `test_sdd_spec_inv6_guard.py`（3）+ `test_coding_pr_link_failsoft.py`（3）+ `test_coding_wave.py`（零回归）= 21 passed；`test_sdd_spec_detail_serializer.py`（7）+ `test_spec_api.py`（17 零回归）= 24 passed。ruff（改动文件全绿）+ makemigrations --check 干净。
- **前端**：vue-tsc 通过 + eslint 通过 + `SpecDeliveryPanel.spec.ts` 4 passed（真实 zh-CN 断言）。

## Decisions Made
- approved→implemented 复用 `_LEGAL_TRANSITIONS["mark_implemented"]` 源/目标常量作单一真相（不重复硬编码状态表）。
- work_item.url 取 `prd_url or ""`（对齐 pr_cross_reference 不构造臆造 URL 范式）。
- detail-only 暴露 implementation_prs（List 序列化器不变）。
- 前端 interface-first 按 D-52-4 契约编码，wave 1 与后端 Plan 01 并行；vitest 用契约 fixture 不依赖后端运行时。

## Deviations from Plan

None - 三个 plan 均按计划执行。

## Issues Encountered
- 执行环境：`uv run pytest` 落到 pyenv 全局 python（venv 未将 pytest 作模块入口），改用 `uv run python -m pytest` 并固定 `working_directory=server`。
- `ruff check delivery workflows tests` 报 172 个**既有**告警（与本 phase 无关历史文件）；本 phase 全部改动文件 `ruff check` 全绿，按 SCOPE BOUNDARY 不修既有告警。
- `components.d.ts` 未变更（SpecDeliveryPanel 经显式 import，非 auto-import），无需提交。

## Deferred (human_needed)
- 真实容器 E2E（真实编码产 PR 回填 + 验收视图真实数据）→ 真实环境人工验收（CONTEXT Out of scope / deferred）。
- spec drift 检测（v2 SDDX-02）、跨 work_item 聚合验收看板、spec→PR 接入统一 AuditEvent（v0.10）。

## Next Phase Readiness
- 里程碑 v0.9.0 全 5 phase（48–52）交付完毕，待里程碑审计 / 收官（`/gsd-complete-milestone` 或 `/gsd-audit-milestone`）。

---
*Phase: 52-spec-pr*
*Completed: 2026-06-17*
