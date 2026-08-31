---
quick_id: 260809-3kc
plan: 260809-3kc
subsystem: repositories-ui
tags: [repo-charter, confirm-create, vue, django]

requires:

  - phase: 111 / CHARTER-01
    provides: RepoCharter 模型、draft/confirm API、charter_service INV-6 写入纪律
provides:

  - confirm 无行 + 非空 edits → 人手创建 human_confirmed
  - 仓库详情「仓库章程」分区（读 / AI 起草 / 手填确认）
  - 新建仓跳转 `#charter` 锚点

affects: [仓库详情 UX, 章程人工确认闭环]

tech-stack:
  added: []
  patterns:

    - "详情读面 fetchRepositoryCharter（404→null）与 citation 容错 getRepositoryCharter 分流"
    - "confirm 单端点兼创建：空 body 仍 404，非空 edits 走 normalize 后 create"

key-files:
  created:

    - web/src/components/repository/RepoCharterSection.vue
    - web/src/components/repository/__tests__/RepoCharterSection.spec.ts
  modified:

    - server/repositories/services/charter_service.py
    - server/repositories/charter_views.py
    - server/tests/repositories/test_charter_service.py
    - server/tests/repositories/test_charter_api.py
    - web/src/api/repositoryChunks.ts
    - web/src/locales/zh-CN.json
    - web/src/pages/repositories/[id]/index.vue
    - web/src/pages/repositories/index.vue
    - web/src/components.d.ts

key-decisions:

  - "不新开第四端点：扩展 POST confirm，无行+非空 edits 即创建"
  - "观测增加 created/duration_ms；非预期异常记 charter_confirm_failed（脱敏后 re-raise）"
  - "未覆盖 charter_service 中 release-link 相关未提交改动，仅追加 confirm 分支"

requirements-completed: []

duration: 12min
completed: 2026-08-09
audit_acknowledged:
  milestone: v0.25.0
  at: 2026-08-31
  status: unknown
---

# Quick Task 260809-3kc：仓库章程详情 UI Summary

**无章程仓可用 `POST confirm` + edits 一次落成 `human_confirmed`；详情页可看/编/确认/AI 起草，新建仓落地即到 `#charter`。**

## Performance

- **Duration:** ~12 min
- **Started:** 2026-08-08T18:35:48Z
- **Completed:** 2026-08-08T18:43:00Z（约）
- **Tasks:** 3/3
- **Commits:** 无（按用户要求不提交）

## Accomplishments

- `aconfirm_charter` 在章程缺失且 `edits` 非空时经 `normalize_charter_draft` 创建 `human_confirmed`（version=1）；空确认仍 404。
- 新增 `RepoCharterSection` 与 API 写方法，详情页 AnchorNav/正文可见「仓库章程」。
- 建仓成功跳转改为 `/repositories/:id#charter`，可立即手填维护。

## Task Commits

按用户要求**未创建任何 git commit**；工作保留在当前工作区。

1. **Task 1: 后端 confirm 支持人手创建** — 未提交
2. **Task 2: API + RepoCharterSection** — 未提交
3. **Task 3: 详情页与新建仓接线** — 未提交

## Files Created/Modified

### 本任务改动

- `server/repositories/services/charter_service.py` — 追加无行创建逻辑与 `created`/`duration_ms`/`charter_confirm_failed` 观测
- `server/repositories/charter_views.py` — docstring 对齐「无行 + 非空 edits → 创建」
- `server/tests/repositories/test_charter_service.py` — 新增 create / missing-without-edits 用例
- `server/tests/repositories/test_charter_api.py` — 新增 API 创建用例，保留空 body 404
- `web/src/api/repositoryChunks.ts` — 收紧类型；新增 `fetch`/`draft`/`confirm`
- `web/src/components/repository/RepoCharterSection.vue` — 详情章程分区
- `web/src/components/repository/__tests__/RepoCharterSection.spec.ts` — 空态 / confirm edits / draft 提示
- `web/src/locales/zh-CN.json` — `repositories.charter.*`
- `web/src/pages/repositories/[id]/index.vue` — AnchorNav + 分区接线
- `web/src/pages/repositories/index.vue` — 建仓跳转 `#charter`
- `web/src/components.d.ts` — 自动注册 `RepoCharterSection`

### 刻意未动 / 保留的既有未提交改动

- `server/repositories/services/charter_service.py` 中 release-link 相关逻辑（`recent_releases`、`acquire_llm_slot`、关联状态扩到 confirmed/verifying/verified/rejected 等）已保留
- 未触碰 `mcp/`、`skills/`、`.planning/quick/260809-charter-release-link/` 等无关产物
- `server/services/process_runtime/blueprint_route_history.py` 为工作区既有改动，本任务未修改

## Decisions Made

- 扩展既有 confirm，而非新增 create 端点。
- 详情读面与 citation 读面分流，避免破坏引用预览的恒不抛语义。
- 观测不记录 edits 全文；失败路径 best-effort 日志后 re-raise。

## Deviations from Plan

### Auto-fixed Issues

None — 计划按约束执行。

### 相对计划输出的约束覆盖

- **未更新** `.planning/STATE.md`（用户明确要求）
- **未做** 任何 git commit（用户明确要求）

## Test Results

| Suite | Result |
|-------|--------|
| `uv run pytest tests/repositories/test_charter_service.py tests/repositories/test_charter_api.py -x -q` | **43 passed** |
| `pnpm vitest run RepoCharterSection.spec.ts + repositories/index.spec.ts` | **4 passed**（2 files） |

## Self-Check

- [x] `aconfirm` 无行+edits 可创建；空 confirm 仍 404
- [x] release-link 相关未提交逻辑仍在 `charter_service.py`
- [x] 详情页有 charter 分区与组件
- [x] 建仓跳转含 `#charter`
- [x] SUMMARY 已写中文；未改 STATE；未 commit

## Self-Check: PASSED

## Known Stubs

无。空态为真实产品空态（尚未建立章程），非占位 stub。

## Remaining Issues

- 详情页 `#charter` 锚点滚动依赖既有 `AnchorNavLayout` / `scroll-mt-22`；未做 E2E 浏览器验证。
- `test_charter_api` teardown 有既有 DB 占用 warning（与本改动无关，测试仍全绿）。
