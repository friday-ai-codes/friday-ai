---
phase: quick-260806-d9y
plan: 01
subsystem: ui
tags: [blueprint, title, sorting, Asia/Shanghai, display_title]

requires: []
provides:
  - "format_blueprint_title / formatBlueprintTitle 统一标题派生"
  - "列表按 created_at 倒序 + created_at 字段"
  - "文档 display_title 与查看器顶栏对齐"
affects: [knowledge-blueprints-tab, project-blueprints-card, blueprint-viewer]

tech-stack:
  added: []
  patterns:
    - "展示层派生标题（不 migration 回填旧 Artifact.title）"
    - "前后端同模板：{project} - 技术方案 - YYYY-MM-DD HH:mm（Asia/Shanghai）"

key-files:
  created:
    - server/services/process_runtime/blueprint_title.py
    - server/tests/services/process_runtime/test_blueprint_title.py
    - web/src/utils/blueprintTitle.ts
    - web/src/utils/__tests__/blueprintTitle.test.ts
  modified:
    - server/services/process_runtime/blueprint_intake.py
    - server/delivery/api/blueprint_list_views.py
    - server/delivery/api/blueprint_doc_views.py
    - server/tests/services/process_runtime/test_blueprint_intake.py
    - server/tests/delivery/test_blueprint_list_views.py
    - server/tests/delivery/test_blueprint_doc_views.py
    - web/src/types/blueprint.ts
    - web/src/components/knowledge/BlueprintListCard.vue
    - web/src/components/project/warroom/ProjectBlueprintsCard.vue
    - web/src/components/blueprint/BlueprintViewerHeader.vue
    - web/src/pages/knowledge/__tests__/blueprintsTab.spec.ts
    - web/src/components/project/warroom/__tests__/ProjectBlueprintsCard.spec.ts
    - web/src/pages/knowledge/__tests__/blueprintViewer.spec.ts

key-decisions:
  - "列表 title / 文档 display_title 始终服务端派生，不依赖 DB 回填"
  - "排序键与标题时间戳均用 artifact.created_at，不用 updated_at"
  - "空项目名前缀固定为「未关联项目」"
  - "intake 缺省 _MAX_TITLE_CHARS 提到 200，避免静默裁掉时间后缀"

patterns-established:
  - "Blueprint title format: `{name} - 技术方案 - YYYY-MM-DD HH:mm` (Asia/Shanghai)"
  - "Frontend list time via formatBlueprintListTime — never toLocaleString with seconds"

requirements-completed: [QUICK-260806-D9Y]

duration: 14min
completed: 2026-08-06
---

# Phase quick-260806-d9y Plan 01: Blueprint Title & Order Summary

**蓝图标题统一为「项目名 - 技术方案 - YYYY-MM-DD HH:mm」，列表按创建时间倒序并展示到分钟；旧数据在展示层派生，无需 migration。**

## Performance

- **Duration:** 14 min
- **Started:** 2026-08-06T01:39:03Z
- **Completed:** 2026-08-06T01:53:24Z
- **Tasks:** 2/2
- **Files modified:** 17

## Accomplishments

- 后端 `format_blueprint_title` + intake 缺省标题、列表 `-created_at` 排序与派生 title、文档纯追加 `display_title`
- 前端 `formatBlueprintTitle` / `formatBlueprintListTime`，列表与项目卡时间到分钟，查看器顶栏优先 `display_title`
- pytest（针对性 10 绿）+ vitest（4 文件 50 绿）；未触碰 runners 未提交文件；无新日志事件 / 无新依赖

## Task Commits

按用户约束**未执行** git commit / add / 切分支：

1. **Task 1: 后端标题纯函数 + 列表/文档派生 + intake 默认标题** — _(uncommitted)_
2. **Task 2: 前端列表时间到分钟 + 查看器顶栏用派生标题** — _(uncommitted)_

**Plan metadata:** _(SUMMARY only; STATE/ROADMAP 未更新)_

## Files Created/Modified

- `server/services/process_runtime/blueprint_title.py` — 标题纯函数
- `server/services/process_runtime/blueprint_intake.py` — 缺省 title 改派生格式
- `server/delivery/api/blueprint_list_views.py` — `order_by(-created_at)`、派生 title、暴露 `created_at`
- `server/delivery/api/blueprint_doc_views.py` — 追加 `display_title`
- `web/src/utils/blueprintTitle.ts` — 前后端口径一致的标题/时间工具
- `web/src/types/blueprint.ts` — `created_at` / `display_title` 类型
- `web/src/components/knowledge/BlueprintListCard.vue` — 分钟精度时间
- `web/src/components/project/warroom/ProjectBlueprintsCard.vue` — 同上
- `web/src/components/blueprint/BlueprintViewerHeader.vue` — 优先 `display_title`
- 对应 pytest / vitest

## Decisions Made

- 展示派生优先于 DB 原标题；新建仍写入同格式便于搜索/导出
- 列表保留 `updated_at` 键，新增 `created_at`
- 可观测性：纯展示/排序，无新 caller/sampling 事件

## Deviations from Plan

None - plan executed exactly as written（除用户明确禁止的 commit / STATE / ROADMAP 更新）。

## Issues Encountered

- 全量四文件 pytest 首跑时 `test_friday` 库被并发占用，前 3 条 intake 骨架用例 setup ERROR；重跑针对性 10 条全部通过。与本改动无关。

## User Setup Required

None

## Known Stubs

None

## Threat Flags

None — 无新信任边界；标题仅为已授权可见的项目名 + 创建时间派生。

## Next Phase Readiness

- 可选人工走查：`/knowledge` 技术方案 tab 与项目物料卡，确认最新在上、标题/时间格式符合示例
- 工作区含本 quick 的未提交改动；用户自行提交时勿带入 `server/runners/consumers.py` 等无关 WIP

## Self-Check: PASSED

- FOUND: `server/services/process_runtime/blueprint_title.py`
- FOUND: `web/src/utils/blueprintTitle.ts`
- FOUND: `.planning/quick/260806-d9y-blueprint-title-order/260806-d9y-SUMMARY.md`
- VERIFY: protected files `server/runners/consumers.py` / `server/tests/runners/test_ws_terminal_propagation.py` — no status changes from this task
- VERIFY: backend focused pytest 10 passed; frontend vitest 50 passed
