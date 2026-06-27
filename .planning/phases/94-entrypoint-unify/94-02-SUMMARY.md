---
phase: 94-entrypoint-unify
plan: 02
subsystem: workflow
tags: [workflow-node, deprecation, node-palette, ai_plan_research, ai_plan_generation, unify]

# Dependency graph
requires:
  - phase: 94-01
    provides: ai_plan_research 统一编排入口（done 渲染 plan_markdown + technical_plan_generation 模板切换）
  - phase: 92-02
    provides: ai_plan_research clarify/resume 插槽端口 + fixture 含 ai_plan_research/ai_plan_generation
provides:
  - ai_plan_generation 标 deprecated（ClassVar + docstring + 实例化 warning）但保留 @register_node 注册
  - BaseNode.deprecated ClassVar（默认 False）废弃标记基础设施
  - NodePalette 移除 ai_plan_generation 裸项 + 暴露 ai_plan_research 裸项
  - docs/workflows/ai-plan-generation-deprecation.md 迁移指引
  - node-sync 双向不变量守护（ai_plan_generation ∉ palette ∧ ∈ fixture；ai_plan_research ∈ palette ∧ ∈ fixture）
affects: [94-03, 94-04, 94-05, 95-decompose]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "节点废弃 = ClassVar deprecated=True + docstring DEPRECATED 顶注 + __init__ 一次性 warning（category=sampling），保留注册供既有实例运行"
    - "前端节点库收口：从 NodePalette 移除废弃裸项的同时暴露统一入口裸项，node-sync 守护 palette ⊆ fixture 单向约束"

key-files:
  created:
    - docs/workflows/ai-plan-generation-deprecation.md
  modified:
    - server/workflows/nodes/base.py
    - server/workflows/nodes/ai/plan_generation.py
    - server/tests/workflows/test_node_schema.py
    - web/src/components/workflow/sidebar/NodePalette.vue
    - web/src/components/__tests__/node-sync.test.ts

key-decisions:
  - "deprecated 作为 BaseNode ClassVar（对齐 requires_container/supports_retry 声明形态），默认 False，子类显式 True"
  - "deprecated 实例化 warning 用 category=sampling（避免高频 INFO 刷屏）+ best-effort 不反噬，仅记 node_type/migration 标量"
  - "NodePalette ai_plan_research 用裸项（type/name/description），requirement_text 默认 config 由节点 schema 字段默认值承担（对齐既有裸项形态）"
  - "不改 node-types.fixture.json：ai_plan_generation 后端仍注册仍在 fixture，删 palette 项后 palette ⊆ fixture 约束依然成立"

patterns-established:
  - "废弃节点向后兼容命门：不删代码、不注销注册、不从 fixture 删——既有 DB 实例 registry 查找与 execute 不破坏"

requirements-completed: [UNIFY-02]

# Metrics
duration: ~12min
completed: 2026-06-27
---

# Phase 94 Plan 02: 废弃 ai_plan_generation + 节点库收口到 ai_plan_research Summary

**ai_plan_generation 标 deprecated（ClassVar + docstring + 实例化 warning）但保留 @register_node 注册，从 NodePalette 移除并暴露 ai_plan_research，附迁移指引——既有实例零回归**

## Performance

- **Duration:** ~12 min
- **Started:** 2026-06-27T15:09:00Z
- **Completed:** 2026-06-27T15:16:00Z
- **Tasks:** 2
- **Files modified:** 6（新建 1 + 修改 5）

## Accomplishments
- `BaseNode` 新增 `deprecated: ClassVar[bool] = False` 废弃标记基础设施，`AIPlanGenerationNode` 设 `deprecated=True`
- docstring 顶部 DEPRECATED 注 + `__init__` 一次性 `logger.warning("deprecated_node_instantiated", category="sampling", component="workflow_node", migration="ai_plan_research")`
- 保留 `@register_node` 与全部节点类代码/端口/map_output（既有 `node_type="ai_plan_generation"` 工作流仍可加载/运行）
- 新建中文迁移指引 `docs/workflows/ai-plan-generation-deprecation.md`
- NodePalette AI 分组移除 ai_plan_generation 裸项、新增 ai_plan_research 裸项
- test_node_schema + node-sync 守护固化「deprecated 仍注册」与「palette/fixture 双向不变量」

## Task Commits

Each task was committed atomically:

1. **Task 1: ai_plan_generation 标 deprecated（保留注册）+ 迁移指引** - `ddd1998cc` (feat)
2. **Task 2: NodePalette 移除 ai_plan_generation + 暴露 ai_plan_research + node-sync 守护** - `d6187da8a` (feat)

_Note: Task 1 commit 经 amend 合并 4 文件为一个原子提交（见 Issues Encountered）。_

## Files Created/Modified
- `server/workflows/nodes/base.py` - 新增 `deprecated: ClassVar[bool] = False`
- `server/workflows/nodes/ai/plan_generation.py` - docstring DEPRECATED 注 + `deprecated=True` ClassVar + `__init__` 一次性 warning
- `server/tests/workflows/test_node_schema.py` - `TestDeprecatedNodeRegistration`（ai_plan_generation 仍注册且 deprecated True；ai_plan_research deprecated False）
- `docs/workflows/ai-plan-generation-deprecation.md` - 迁移指引（废弃原因 / 既有不受影响 / 改用 ai_plan_research / 不自动迁移）
- `web/src/components/workflow/sidebar/NodePalette.vue` - AI 分组 ai_plan_generation → ai_plan_research 裸项
- `web/src/components/__tests__/node-sync.test.ts` - 双向不变量守护断言

## Decisions Made
- `deprecated` 作 BaseNode ClassVar（对齐既有 requires_container 等声明形态），默认 False
- 实例化 warning 用 `category=sampling` 避免高频 INFO 刷屏，best-effort 不反噬
- ai_plan_research 用裸项；requirement_text 默认 config 由节点 schema 字段默认值承担（对齐既有裸项形态，本仓裸项不内联 config）
- 不改 fixture：ai_plan_generation 后端仍注册仍在 fixture，删 palette 项后 palette ⊆ fixture 约束依然成立

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered
- **节点测试标题大小写 lint**：新增 node-sync `it(...)` 标题原以「UNIFY-02」大写起头触发 `test/prefer-lowercase-title`，改为以 `ai_plan_generation`/`ai_plan_research` 小写起头（UNIFY-02 标记移到括注内），eslint 转绿。
- **git stash 误扫工作树在制品**：执行期为核对 mypy 基线运行 `git stash` 时，连带把工作树中其它会话未提交的大量在制品一并入栈，且随后的 `git stash pop` 因被管道过滤而未即时生效，导致 Task 1 首个提交 `2d440f27a` 只含迁移文档。随后 `git stash pop` 恢复全部改动，确认我的 3 个后端文件编辑完好并 ruff-formatted，遂以 `git commit --amend` 把 base.py/plan_generation.py/test_node_schema.py 并入 Task 1 提交（→ `ddd1998cc`，4 文件原子）。HEAD 提交为本会话所建且未推送，amend 合法。工作树其它在制品（chat/initiatives/knowledge 等）全程未被本 plan 暂存或提交。

## Deferred Issues
- `server/workflows/nodes/base.py:515` `result` 缺类型注解的 mypy `var-annotated` 错误为**既有**（经 `git stash` 隔离后在 base 基线复跑确认改动前已存在），与本 plan 无关，超出范围未修。

## Known Stubs
None.

## Threat Flags
None - 改动仅废弃标记 + 节点库裸项增删 + 守护测试，未引入新网络端点/认证路径/schema 变更。

## Verification
- `cd server && uv run pytest tests/workflows/test_node_schema.py -k "Deprecated"` → 2 passed
- `cd server && uv run ruff format/check`（受改文件）→ All checks passed
- `cd web && pnpm vitest run node-sync` → 7 passed（5 既有 + 2 新增）
- `cd web && pnpm exec eslint`（受改 2 文件）→ clean
- `cd web && pnpm vue-tsc --noEmit` → 0 errors
- 本 plan 不触模型，无新迁移。

## Next Phase Readiness
- UNIFY-02 完成；ai_plan_generation 废弃但向后兼容、节点库收口到 ai_plan_research。
- 共享 `render_merged_plan_markdown`（94-01 已就位）供 94-03/94-04 MCP delegate 复用；94 余 plan（03/04/05）可继续推进。

## Self-Check: PASSED

- Files verified present: `docs/workflows/ai-plan-generation-deprecation.md`, `.planning/phases/94-entrypoint-unify/94-02-SUMMARY.md`, `web/src/components/workflow/sidebar/NodePalette.vue`
- Commits verified: `ddd1998cc`, `d6187da8a`

---
*Phase: 94-entrypoint-unify*
*Completed: 2026-06-27*
