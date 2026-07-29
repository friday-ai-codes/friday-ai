---
phase: quick-260729-emz-task-category-ask-clarification
plan: 01
status: complete
subsystem: agents
tags: [task-category, feature-solution, clarification-guard, repo-association]
requires:
  - phase: quick-260728-ppb-start-feature-solution
    provides: start_feature_solution 工具与项目级方案引导
provides:
  - 项目级强方案意图在 LLM 前服务端直驱 FeatureSolutionService
  - 方案类 clarification resume 直达正式编排且不回流 chat ask_clarification
  - 项目级方案范围澄清护栏与受约束 task_category
  - 经 RepoAssociationService 写入的 propose_project_repos 运维命令
affects: [agents, orchestration, initiatives, project-chat]
tech-stack:
  added: []
  patterns: [server-side intent dispatch, fail-soft task category normalization, INV-6 command]
key-files:
  created:
    - server/agents/feature_solution_dispatch.py
    - server/initiatives/management/commands/propose_project_repos.py
    - server/tests/agents/test_feature_solution_dispatch.py
    - server/tests/initiatives/test_propose_project_repos_command.py
  modified:
    - server/agents/intent_router.py
    - server/orchestration/graph.py
    - server/agents/tools/clarification.py
key-decisions:
  - 强方案关键词与方案类 task_category 均在服务端直驱 FeatureSolutionService
  - 工具层阻断项目级方案覆盖范围澄清，不增加 graph marker 二次兜底
  - 仓库提案与确认只经 RepoAssociationService，执行期不连接生产
requirements-completed: [QUICK-EMZ-ROUTER, QUICK-EMZ-GUARD, QUICK-EMZ-REPOS]
duration: 14min
completed: 2026-07-29
---

# Quick Task 260729-emz: task_category 与方案澄清路由 Summary

**项目级技术方案请求现在由服务端幂等直驱正式编排，方案覆盖范围不再落入 chat 单题澄清，并提供符合 INV-6 的仓库候选补数命令。**

## Performance

- **Duration:** 14 分钟
- **Started:** 2026-07-29T02:41:45Z
- **Completed:** 2026-07-29T02:56:04Z
- **Tasks:** 3
- **Tests:** 85 passed

## Accomplishments

- 增加 `TaskCategory` 白名单、规范化函数和项目级强方案意图分类器。
- `_execute_first_run` 与 clarification resume 双挂载 `dispatch_feature_solution`；复用 active `ConvergenceSession`，状态只映射到 `plan_clarification`、`blocking_tasks`、`finalizing` 或 `error`。
- `ask_clarification` 自动注入 `conversation_id`，拦截 bound project 的方案范围问题，同时放行 `coding_change` 选仓并 strip 未知分类。
- 新增 `propose_project_repos`，dry-run 零写入，正式路径只经 `RepoAssociationService.propose`，可选经 `confirm_repos` 确认。

## Task Commits

1. **Task 1: Router — task_category + feature_solution_dispatch + graph 双挂载** — `c0f7a578`
2. **Task 2: Guard — 项目级方案范围 ask_clarification 护栏** — `860d8ccc`
3. **Task 3: propose_project_repos 命令 + 生产补数说明** — `f50884f0`

## Verification

```bash
cd server
uv run pytest \
  tests/test_intent_router.py \
  tests/agents/test_feature_solution_dispatch.py \
  tests/test_chat_graph_clarification_interrupt.py \
  tests/test_ask_clarification_tool.py \
  tests/initiatives/test_propose_project_repos_command.py \
  --reuse-db -q --tb=short
```

结果：`85 passed`。未修改 `chat_runner` 工具白名单、Prompt Center 或 `coding_guidance`，未删除 `create_coding_plan`。

## 生产补数步骤

本任务未 SSH、未连接 `10.8.8.153`、未写生产库。部署代码后，由运维在生产执行：

```bash
# 在 10.8.8.153 friday-server 容器内
python manage.py propose_project_repos 75248ff9-3a22-4175-b940-6093d71eb4dc --initiated-by-user-id <owner>
# 然后 UI/API repo-decision accept
```

`feature_solution` 编排本身不依赖 `RepoAssociation`：它按项目所属 space 的全量仓库运行。补充 `propose_project_repos` 主要用于修复项目面板空关联，并补齐 plan deepen 对 verified 仓库关联的消费链。

## Observability

- Router：`solution_intent_detected`、`solution_intent_dispatched`、`solution_intent_dispatch_failed`。
- Guard：`task_category_rejected`、`ask_clarification_scope_blocked`，不记录问题与选项正文。
- Command：`propose_project_repos_started/completed/failed`，携 `duration_ms`、触发用户和项目关联键。
- 全部事件使用 `structlog`、snake_case、`category/component`，观测调用 best-effort，异常文本脱敏。

## Deviations from Plan

None - plan executed exactly as written.

## Known Stubs

None.

## Threat Flags

None - 新增管理命令、会话注入与服务端 dispatch 均已在计划 threat model 中覆盖。

## Self-Check: PASSED

已确认关键产物存在，三个 task commit 均可解析；工作树仅保留按约定不提交的本 SUMMARY。
