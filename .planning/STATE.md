---
gsd_state_version: 1.0
milestone: v0.4.0
milestone_name: 工作流系统契约重构
status: executing
stopped_at: v0.4.0 roadmap created (Phase 17–21, 24/24 requirements mapped)
last_updated: "2026-06-12T16:11:17.536Z"
last_activity: 2026-06-12 -- Phase 17 planning complete
progress:
  total_phases: 5
  completed_phases: 0
  total_plans: 4
  completed_plans: 0
  percent: 0
---

# Project State

## Project Reference

See: .planning/PROJECT.md (updated 2026-06-12 after v0.3.0 milestone)

**Core value:** 让团队"开箱即用、安全地"把需求自动变成代码；v0.4.0 收敛工作流系统的编辑态与运行态契约——保存即合法、模板开箱能跑、变量所选即所得、执行状态真实可见。
**Current focus:** Milestone v0.4.0 工作流系统契约重构（Phase 17–21）

## Current Position

Phase: 17 of 21 — 变量引用链路修复（Not started）
Plan: —
Status: Ready to execute
Last activity: 2026-06-12 -- Phase 17 planning complete

Progress: [□□□□□] 0/5 phases

## Milestone Overview (v0.4.0)

| Phase | Name | Requirements | Status |
|-------|------|--------------|--------|
| 17 | 变量引用链路修复 | VAR-01..04 | Not started |
| 18 | 执行引擎状态机修复 | ENG-01..05 | Not started |
| 19 | 节点定义单一事实源 | SSOT-01..03 | Not started |
| 20 | 保存即合法与模板修复 | VAL-01..03, TPL-01..03 | Not started |
| 21 | 触发模型与执行可观测 | TRIG-01..03, OBS-01..03 | Not started |

**Execution order:** 17 → 18 → 19 → 20 → 21（19 可与 17/18 并行；20 依赖 17/18/19；21 依赖 17/18）

## Performance Metrics

**Milestone v0.3.0:**

| Metric | Value |
|--------|-------|
| Phases completed | 5/5 |
| Plans completed | 23/23 |
| Requirements delivered | 28/28 |
| Phase 12 P01 | 10min | 3 tasks | 10 files |
| Phase 12 P02 | 12min | 3 tasks | 2 files |
| Phase 12 P03 | 8min | 3 tasks | 7 files |
| Phase 13 P13-02 | 12min | 2 tasks | 3 files |
| Phase 13 P13-03 | ~16min | 3 tasks | 7 files |
| Phase 14 P02 | ~8min | 2 tasks | 4 files |
| Phase 14 P03 | 16min | 3 tasks | 4 files |
| Phase 14 P04 | 14min | 2 tasks | 4 files |
| Phase 14 P05 | 12min | 2 tasks | 3 files |
| Phase 14 P06 | 14min | 2 tasks | 5 files |

## Accumulated Context

### Decisions

Decisions are logged in PROJECT.md Key Decisions table; v0.2.0 full phase detail in `.planning/milestones/v0.2.0-ROADMAP.md`.

- [Phase 12]: EntityKind/EdgeRelation 枚举字面值锁死（kind 进 uuid5 PK 派生，改名即数据迁移）；MODIFIES_CHUNK 为 Phase 14 占位
- [Phase 12]: generate_entity_id 拼接格式 kind:source_kind:source_id + 独立 KNOWLEDGE_NAMESPACE；CodeChangeArchive 不预建（Phase 14 自带 migration）
- [Phase 12]: GraphStore 递归 CTE anchor path 不含起点（环回到起点计 1 次后终止）；direction=both 多跳与 MySQL 后端显式 NotImplementedError
- [Phase 12]: payload schema 8 索引字段第一天定型（含权限维度），回归测试锁键集合；ensure 不匹配 raise 绝不删库，重建唯一入口 rebuild_delivery_knowledge --yes 命令
- [Phase ?]: 13-02: hash 相等绝不产生新版本——needs_revector 走 revectorize_version 补写向量，不建版本行不置 invalid_at
- [Phase ?]: 13-02: 边非严格同事务——apply_edge_specs 幂等可重入，skipped/needs_revector 事件仍执行边阶段自愈
- [Phase ?]: 14-02: 截断 helper truncate_diff_lines 放 base.py 模块级双客户端共用；既有 get_merge_request_diff 内联截断不动（零回归）
- [Phase ?]: 14-02: base get_branch_diff 抽象化分两步——Task 1 NotImplementedError 占位、Task 2 双实现齐备后转 @abstractmethod，避免瞬时打破 GitHubClient 实例化
- [Phase 14]: 14-04: 审批事件 source_id 恒为生成节点 key（OQ-2），接线处换算、normalizer 单纯
- [Phase 14]: 14-04: workflow_plan normalizer 兼容 trigger_data.raw_payload 与 payload 双键取飞书工作项锚
- [Phase 14]: 14-05：飞书三 handler 只投三元组 ID（取材全在 normalizer 后台），文档拉取失败降级为缺段快照 + warning
- [Phase ?]: 14-06: workflow mr_results 回退键按引擎实际落点 merge_requests（checker 建议的 succeeded_repos 实为计数 int）
- [Phase ?]: 14-06: workflow 仓库归属经 output_data.pending_sessions 匹配 + session.repo_url 兜底（双源均服务端写入，T-14-22）

### Pending Todos

[From .planning/todos/pending/ — ideas captured during sessions]

None.

### Blockers/Concerns

[Issues that affect future work]

- v0.2.0 follow-up（by-design）：实时明文 PAT 通道（contextvar）未接入，RemoteTool 链路端到端运行时休眠；接入后才点亮 MCPB-02 / RTOOL-02·03·04 运行时（受 PAT-02 约束）。候选下一里程碑工作。

### Quick Tasks Completed

| # | Description | Date | Commit | Directory |
|---|-------------|------|--------|-----------|
| 260610-oug | 修复仓库 URL 提示文案为仅支持 HTTPS，并将所有英文校验/错误提示汉化 | 2026-06-10 | c4c60c4f | [260610-oug-url-https](./quick/260610-oug-url-https/) |
| 260610-shc | OIDC 回调 URL 与登录跳转优先消费「站点 Host」(site_host) 系统设置 | 2026-06-10 | b01dc066 | [260610-shc-site-host-oidc](./quick/260610-shc-site-host-oidc/) |
| 260610-qmv | 修复 compose 部署下任务容器回调失败（发布 runner callback 端口）并抑制 claude CLI 403 遥测噪音 | 2026-06-10 | 68ddaa4c | [260610-qmv-compose-runner-callback-claude-cli-403](./quick/260610-qmv-compose-runner-callback-claude-cli-403/) |
| 260611-0pm | 打磨第 1 批：全仓口径对齐 + 过程痕迹清洗 + 社区脚手架 | 2026-06-11 | 7f0c4381 | [260611-0pm-polish-batch1](./quick/260611-0pm-polish-batch1/) |
| 260611-fky | 打磨仓库列表索引完成界面视觉 | 2026-06-11 | fa5e1b0a | [260611-fky-repository-list-polish](./quick/260611-fky-repository-list-polish/) |
| 260612-crc | 修复 clarification 答复后 resume 后台任务因继承请求 contextvars 崩溃、会话永久卡在等待态 | 2026-06-12 | e6374837 | [20260612-fix-clarification-resume-context](./quick/20260612-fix-clarification-resume-context/) |
| 260611-g31 | 打磨工作流列表与执行监控界面视觉 | 2026-06-11 | 9bc59746 | [260611-g31-workflow-execution-polish](./quick/260611-g31-workflow-execution-polish/) |
| 260611-ghb | 统一工作流卡片高度并收纳节点标签 | 2026-06-11 | c7af69b6 | [260611-ghb-workflow-card-uniform](./quick/260611-ghb-workflow-card-uniform/) |
| 260612-cifix | 修复 CI：smoke 列表移除已删除的 test_tool_bindings.py | 2026-06-12 | ec839757 | — |

## Deferred Items

Items acknowledged and deferred at milestone close.

| Category | Item | Status | Deferred At |
|----------|------|--------|-------------|
| verification | Phase 01 人工验收（01-VERIFICATION.md） | human_needed | 2026-06-09 (v0.1.0 close) |
| verification | Phase 02 人工验收（02-VERIFICATION.md） | human_needed | 2026-06-09 (v0.1.0 close) |
| verification | Phase 06 人工验收（06-VERIFICATION.md） | human_needed | 2026-06-10 (v0.2.0 close) |
| verification | Phase 07 人工验收（07-VERIFICATION.md） | human_needed | 2026-06-10 (v0.2.0 close) |
| verification | Phase 08 人工验收（08-VERIFICATION.md） | human_needed | 2026-06-10 (v0.2.0 close) |
| verification | Phase 09 人工验收（09-VERIFICATION.md） | human_needed | 2026-06-10 (v0.2.0 close) |
| verification | Phase 10 人工验收（10-VERIFICATION.md） | human_needed | 2026-06-10 (v0.2.0 close) |
| verification | Phase 11 人工验收（11-VERIFICATION.md） | human_needed | 2026-06-10 (v0.2.0 close) |
| verification | Phase 14 真实 git platform 超大 diff 截断人工验收（TD-14） | human_needed | 2026-06-12 (v0.3.0 close) |

## Session Continuity

Last session: 2026-06-12
Stopped at: v0.4.0 roadmap created (Phase 17–21, 24/24 requirements mapped)
Resume file: None

## Operator Next Steps

- Start planning the first phase with /gsd-plan-phase 17
