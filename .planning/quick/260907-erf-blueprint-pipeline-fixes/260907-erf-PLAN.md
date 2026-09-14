---
quick_id: 260907-erf
slug: blueprint-pipeline-fixes
date: 2026-09-07
status: complete
description: 修复蓝图流水线七个平台问题（示例功能专项实战复盘）
verification: .planning/debug/resolved/quick-260907-audit.md
---

# Quick 260907-erf：蓝图流水线七个平台问题修复

本计划的实现状态已于 2026-09-13 逐项对照生产调用路径和回归测试复核，审计记录见
`.planning/debug/resolved/quick-260907-audit.md`。

## Task 1（P0）：分仓方案校验顺序 bug

- **files**：`server/subagent/api/callbacks.py`、`server/tests/subagent/test_blueprint_repo_plan_callback.py`
- **action**：采用复盘文档方案 A —— `_parse_blueprint_repo_plan` 加 `repository_id`
  keyword 参数，在 `coerce_repo_plan_shapes` + `validate_repo_plan` **之前**权威写入。
  不改 schema required（服务端仍要求该键存在，只是由服务端负责填）。
- **verify**：容器 output 省略 `repository_id` 的合规 repo_plan 校验通过且落库值 = task 的仓。
- **done**：`test_parse_injects_repository_id_before_validation` 绿。

## Task 2（P0）：degraded 仓永远无法重派

- **files**：`server/delivery/services/research_service.py`、`server/tests/delivery/test_research_service.py`
- **action**：采用复盘文档方案 A —— `_mark_stale_sync` 的终态集合加入 `STALE`，让已 stale
  task 名下 `valid=True` 的 PartialPlan 照常失效。
  ⛔ **不采用方案 B**（改 `dispatch_plans` 完成判据）：`dispatch_plans` 由 barrier 每次容器
  回调驱动，把 degraded 视为「未完成」会形成「派容器 → 又 degraded → barrier → 再派」的
  无界循环，直接烧光额度。方案 A 让「显式重跑/驳回」恰好触发一次重派，自动路径零扰动。
- **verify**：stale task + valid degraded PartialPlan → `mark_stale` 后 partial 失效。
- **done**：`test_mark_stale_invalidates_partials_of_already_stale_task` 绿。

## Task 3（P1）：融合对账误判五仓外 existing 依赖

- **files**：`server/services/process_runtime/blueprint_merge.py`
- **action**：方案 B（堵漏）—— `_apply_needs_support` 跳过「已标 `existing` 且 `from_service`
  非空且该 service 不可解析为锁定仓」的契约。方案 A（给 `ignored_support_aliases` 装写入
  门把手）配套落在裁决动作端点。
- **verify**：含一条 `availability=existing` + 外部 `from_service` 的消费契约 → 融合后
  `missing_support_repos` 为空且该契约仍是 `existing`。
- **done**：外部既有依赖跳过误报、作答排除名单写入会话均有直接回归测试。

## Task 4（P1）：确认门静默丢仓

- **files**：`server/services/process_runtime/blueprint_confirm_gate.py`
- **action**：方案 B —— `_human_kept_despite_unsuitable` 把 `edit_responsibility` /
  `reclassify_role` 等人工留痕也算作「人要这个仓」；方案 A —— 锁定时把被自动移除的仓
  写进结果与会话事件，人可见。
- **done**：人工留仓不被晚到 unsuitable 移除，自动移除仓 ID 可经 service、事件和 HTTP
  响应观察。

## Task 5（P1）：作答后僵尸挂起

- **files**：`server/services/process_runtime/blueprint_resume.py`
- **action**：方案 A —— 恢复扫描补「waiting_clarification 且零 open+blocking 线程」特征；
  方案 B —— 驱动租约加 TTL，持有者崩溃后可被接管。
- **done**：僵尸扫描、开放线程反例、租约到期接管和续租均有回归覆盖。

## Task 6（P2）：重试预算被基础设施故障烧光

- **files**：`server/subagent/api/callbacks.py`、`server/delivery/services/research_service.py`、
  管理命令
- **action**：方案 A —— 容器基础设施类失败（额度/认证/runner）退还 attempt；
  方案 B —— `reset_research_attempts` 管理命令。
- **done**：基础设施失败分类与退还预算、service 清零复活及管理命令入口均有回归覆盖。

## Task 7（P2）：Claude Code 凭证指针 UX

- **files**：`server/system/`、`web/src/`
- **action**：凭证列表/详情标出「Claude Code 编码容器使用中」，编辑他条凭证时明示不影响 CC。
- **done**：当前凭证徽标、指针加载失败降级、编辑非当前凭证提示均有组件测试。
