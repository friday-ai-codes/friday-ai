# GSD Debug Knowledge Base

Resolved debug sessions. Used by `gsd-debugger` to surface known-pattern hypotheses at the start of new investigations.

---

## repo-plan-poisoned-resume — poisoned resume, retry gaps, and clarification self-spin
- **Date:** 2026-08-19
- **Error patterns:** missing thinking, socket connection was closed unexpectedly, repo_plan_invalid_retrying, container_failed, process.session.failed, stale barrier deadlock, 7/9 plans, needs_clarification repeated, advance_step_limit, 8/8 plans
- **Root cause:** Seven coupled contracts: unsafe cross-mode/malformed SDK resume; late SDK ID capture; retry callbacks without wakeup; naked failed accepted by the barrier; unbounded structured submit and generic repo-plan limits; and a stage-wide wait_status that forced repo_plan needs_clarification into WAITING_EVENT. Indirect degraded synthesis also opened a blocking thread unlike the direct callback path.
- **Fix:** Scope and validate resume; use stable SDK UUIDs; bounded redispatch then explicit schema-valid degraded RepoPlans; require actual repo_plan sections; bound submit schema/payload and raise repo-plan limits; add event-specific self-loop wait statuses so needs_clarification pauses while plan_dispatched waits for callbacks; make degraded-plan clarifications nonblocking.
- **Files changed:** server/chat/sdk_resume.py, server/delivery/services/convergence_session_service.py, server/services/process_runtime/registry.py, server/services/process_runtime/builtin_processes.py, server/services/process_runtime/blueprint_research_adapter.py, server/services/process_runtime/blueprint_repo_plan.py, server/subagent/api/callbacks.py, server/tests/test_sdk_resume.py, server/tests/delivery/test_blueprint_repo_resume.py, server/tests/services/process_runtime/test_blueprint_process_graph.py, server/tests/services/process_runtime/test_blueprint_repo_plan_stage.py, server/tests/subagent/test_blueprint_repo_plan_callback.py, task/core/agent_submit_mcp.py, task/core/executor.py, task/tests/test_agent_submit_mcp.py, task/tests/test_explore_structured_submit.py, task/tests/test_claude_sdk_integration.py
---

## repo-plan-poisoned-resume — merge support_repository_id alias false positives
- **Date:** 2026-08-19
- **Error patterns:** missing_support_repos, support_repo_missing, onion-learning, waiting_clarification, support_repository_id, course-business, onion-auth, alias
- **Root cause:** reconcile and review compared support_repository_id only to association UUIDs; merge persisted raw RepoPlan full/short names without canonicalizing unique aliases, so locked frontend/onion-learning was flagged missing as onion-learning.
- **Fix:** Shared pure resolver (exact UUID, exact repository_name, unique basename; ambiguous unresolved; case-sensitive after strip). Merge canonicalizes before reconcile; reconcile and review share the same semantics. True absences remain blocking.
- **Files changed:** server/services/process_runtime/blueprint_repo_alias.py, server/services/process_runtime/blueprint_reconcile.py, server/services/process_runtime/blueprint_review.py, server/services/process_runtime/blueprint_merge.py, server/tests/services/process_runtime/test_blueprint_repo_alias.py, server/tests/services/process_runtime/test_blueprint_reconcile.py, server/tests/services/process_runtime/test_blueprint_review_rules.py, server/tests/services/process_runtime/test_blueprint_merge_stage.py
---

## wanda-blueprint-7b67b615 — 蓝图耗时、仓库进度、标签与引用异常
- **Date:** 2026-08-21
- **Error patterns:** 1621m duration, 9/23 research progress, citation_missing, 其他信息, 未知仓库, empty repository_id
- **Root cause:** 前端用首末事件墙钟差计算跨夜耗时并按事件次数统计仓库进度；结构化字段缺少 i18n；仓库名称只取最终关联且确认事件发送空 repository_id；历史确认门还清空了 fitness citations。
- **Fix:** 改为累计活跃片段并按仓库终态并集统计进度，补齐字段标签和事件仓库名称，后端兼容新旧计数字段且省略空 repository_id；回填历史引用并从 merge 重跑生成 v12。
- **Files changed:** web/src/utils/blueprintActivity.ts, web/src/utils/__tests__/blueprintActivity.spec.ts, web/src/components/blueprint/BlueprintStageStepper.vue, web/src/pages/knowledge/blueprints/[id].vue, web/src/locales/zh-CN.json, server/services/process_runtime/blueprint_confirm_gate.py, server/delivery/services/blueprint_lifecycle_service.py
---
