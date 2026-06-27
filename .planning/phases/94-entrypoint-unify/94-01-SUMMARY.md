---
phase: 94-entrypoint-unify
plan: 01
subsystem: workflow
tags: [plan_orchestration, ai_plan_research, merged_plan, lark_md, workflow_template, render]

# Dependency graph
requires:
  - phase: 92-slot-system-backend
    provides: "ai_plan_research clarify/resume 插槽端口 + default 输出 schema 基线"
  - phase: 40-merged-plan
    provides: "§7 MergedPlan content schema（title/summary/execution_plan/compat_risks）"
provides:
  - "render_merged_plan_markdown 共享渲染 helper（MergedPlan §7 → lark_md 卡片正文，barrel 导出）"
  - "ai_plan_research default 输出端口声明 plan_markdown + done 出口填充渲染结果"
  - "technical_plan_generation 模板切到 ai_plan_research 编排路径（消除 field_not_found）"
affects: [94-03-mcp-technical-plan-delegate, 94-02-deprecate-ai-plan-generation]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "纯函数渲染 helper 移植 plan_generation._render_plan_markdown 范式适配 §7 MergedPlan + barrel 共享"
    - "节点输出端口 schema 显式声明字段以满足下游模板字段引用契约（规避 validator field_not_found）"

key-files:
  created:
    - server/services/plan_orchestration/render.py
  modified:
    - server/services/plan_orchestration/__init__.py
    - server/workflows/nodes/ai/plan_research.py
    - server/workflows/templates/technical_plan_generation.json
    - server/tests/workflows/test_plan_research_node.py
    - server/tests/workflows/test_template_loader.py

key-decisions:
  - "render_merged_plan_markdown 只读 MergedPlan 结构化字段（title/summary/execution_plan/compat_risks），绝不内联 raw_* / LLM 原文（T-94-01-INFO）"
  - "compat_risks 用 • 字面项目符号而非 Markdown `- ` 列表（lark_md 跨客户端稳定）"
  - "plan_markdown 渲染输入用 pv.content（未注入 plan_version_id 的 canonical content）；content 缺失/非 dict 时空串不改 plan={} 零回归"
  - "默认输出端口 schema 显式声明 plan_markdown(type string)，satisfies 模板 {{nodes.generate_plan.plan_markdown}} 引用，消除既有 field_not_found"
  - "技术方案模板切换只改定义、删 notify_clarify/need_clarification 出边（ai_plan_research 无该端口），不写数据迁移（既有 DB 实例不受影响 T-94-01-COMPAT）"

patterns-established:
  - "共享渲染 helper：MCP delegate（UNIFY-03）与工作流节点 done 出口复用同一 render_merged_plan_markdown（不造两套）"

requirements-completed: [UNIFY-01, UNIFY-06]

# Metrics
duration: ~9min
completed: 2026-06-27
---

# Phase 94 Plan 01: 入口统一（工作流侧 done 渲染 + 模板切换）Summary

**新建共享 render_merged_plan_markdown helper 把 §7 MergedPlan 渲染为干净 lark_md，ai_plan_research done 出口产 plan_markdown 并声明到端口 schema，technical_plan_generation 模板切到 ai_plan_research 编排路径并消除既有 field_not_found 失败**

## Performance

- **Duration:** ~9 min
- **Started:** 2026-06-27T14:56:48Z
- **Completed:** 2026-06-27T15:05:34Z
- **Tasks:** 3
- **Files modified:** 6（1 created + 5 modified）

## Accomplishments
- 新建 `render_merged_plan_markdown` 纯函数共享渲染 helper（§7 MergedPlan → 飞书 lark_md，`•` 项目符号、coding_instruction 300 截断、半可信防御、不 dump LLM 原文），barrel 导出供 MCP delegate 与节点共用。
- `ai_plan_research` done 出口产结构化 `plan_markdown`（render 结果）并在 `default` 输出端口 schema 显式声明该字段。
- `technical_plan_generation` 模板方案节点切到 `ai_plan_research`（requirement_text config + work_item_id 锚），删废弃 `notify_clarify` 节点及 `need_clarification` 出边。
- 消除既有 `field_not_found` 失败：`test_template_validates_with_zero_errors[technical_plan_generation]` 与 `test_acreate_accepts_valid_templates` 转绿。

## Task Commits

Each task was committed atomically（TDD 任务 test 与 feat 合并提交）：

1. **Task 1: 共享 render_merged_plan_markdown helper** - `d73127290` (feat)
2. **Task 2: ai_plan_research done 出口产 plan_markdown + schema 声明** - `07f18f989` (feat)
3. **Task 3: technical_plan_generation 模板切到 ai_plan_research + loader 断言** - `12b6a7c74` (feat)

_Note: TDD 任务（Task 1/2）的失败测试与实现在同一原子提交内（RED 先验后 GREEN 实现，单 commit 落地）。_

## Files Created/Modified
- `server/services/plan_orchestration/render.py` - 新建纯函数 `render_merged_plan_markdown`（§7 MergedPlan → lark_md）
- `server/services/plan_orchestration/__init__.py` - barrel import + `__all__` 导出 render_merged_plan_markdown
- `server/workflows/nodes/ai/plan_research.py` - default 输出端口 schema 加 plan_markdown；`_map_terminal` DONE 分支调 render 填充
- `server/workflows/templates/technical_plan_generation.json` - generate_plan 切 ai_plan_research + requirement_text/work_item_id；删 notify_clarify 节点与 need_clarification 出边
- `server/tests/workflows/test_plan_research_node.py` - render helper 5 行为 + plan_markdown 输出/schema/failed 零回归 4 测
- `server/tests/workflows/test_template_loader.py` - technical_plan_generation 切换断言（mirror code_generation）

## Decisions Made
见 frontmatter key-decisions。要点：渲染只消费结构化字段（脱敏纵深）；模板只改定义不写数据迁移；schema 显式声明 plan_markdown 是消除 field_not_found 的关键。

## Deviations from Plan

None - plan executed exactly as written.

（说明：PLAN 的 Task 1/2 标 `tdd="true"`，本次按 TDD RED→GREEN 顺序执行——先写失败测试验证证伪，再实现转绿——但 RED 测试与 GREEN 实现合入同一原子 commit，未拆分 test/feat 两次提交。此为提交粒度选择，非范围偏离。）

## Issues Encountered
- 执行中途 shell cwd 漂移（持久 cwd 叠加 `cd server` 导致路径错位致 `git add` 找不到文件）——改用 `working_directory` 绝对根路径 + 显式 `server/...` 路径解决，未影响产物。

## User Setup Required
None - no external service configuration required.

## Next Phase Readiness
- UNIFY-06 工作流侧 done 渲染 + UNIFY-01 模板切换完成；共享 helper `render_merged_plan_markdown` 已就位，供 94-03 MCP delegate 复用（不造两套）。
- 既有 `field_not_found` 失败消除；`test_plan_research_node` / `test_template_loader` 全绿。
- 下游：94-02（ai_plan_generation deprecated）、94-03/04（MCP delegate）、94-05（澄清单一来源）。

## Self-Check: PASSED
- `server/services/plan_orchestration/render.py` — FOUND
- Commit `d73127290` / `07f18f989` / `12b6a7c74` — FOUND
- `cd server && uv run pytest tests/workflows/test_template_loader.py tests/workflows/test_plan_research_node.py` → 61 passed
- `ruff check` + `mypy`（plan_research.py / render.py / __init__.py）干净；`makemigrations --check` 无变化

---
*Phase: 94-entrypoint-unify*
*Completed: 2026-06-27*
