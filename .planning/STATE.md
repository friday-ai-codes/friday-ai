---
gsd_state_version: 1.0
milestone: v0.5.0
milestone_name: 索引检索地基与排除文件
status: planning
stopped_at: 6 项遗留代码全部实现并原子提交（37a3bd6b2 / 5435fef23 / 9ab638f13 / 8cb50e928）；
last_updated: "2026-06-14T08:15:38.056Z"
last_activity: 2026-06-14 — Milestone v0.5.0 started
progress:
  total_phases: 5
  completed_phases: 0
  total_plans: 0
  completed_plans: 0
  percent: 0
---

# Project State

## Project Reference

See: .planning/PROJECT.md (updated 2026-06-12 after v0.3.0 milestone)

**Core value:** 让团队"开箱即用、安全地"把需求自动变成代码；v0.5.0 补齐索引/检索地基——敏感文件全链路 fail-closed 不可见（两种 purge 模式）、commit 历史可检索、行级反查、多仓凭证统一。
**Current focus:** Phase 22 — 排除配置与统一过滤（fail-closed）

## Current Position

Phase: Not started (defining requirements)
Plan: —
Status: Planning（REQUIREMENTS/ROADMAP 已生成，待 plan-phase）
Last activity: 2026-06-14 — Milestone v0.5.0 started

## Milestone Overview (v0.5.0)

| Phase | Name | Requirements | Status |
|-------|------|--------------|--------|
| 22 | 排除配置与统一过滤（fail-closed） | EXCL-01..02 | Not started |
| 23 | 清理对账（普通/敏感两模式） | EXCL-04..06 | Not started |
| 24 | 敏感文件 AI 识别建议名单 | EXCL-03 | Not started |
| 25 | Commit 历史索引 + 行号反查 | IDX-01..02 | Not started |
| 26 | 多仓凭证统一 + MCP 多仓参数 | REPO-01..02 | Not started |

**Execution order:** 22 → 23（23 依赖 22 配置源）；24 依赖 22；25、26 相对独立可并行。

**前置修复（PREFLIGHT，里程碑内处理）:** PF-03（incremental 删除一致性）、PF-04（scan_directory 注释）、PF-05（delete_by_file_path overlay）。

**设计底座:** `.planning/ROADMAP-vNext.md`（前瞻路线）、`.planning/DOMAIN-MODEL.md §9`（purge 矩阵/数据面/边界）、`.planning/PREFLIGHT.md`（风险台账）。

## Milestone Overview (v0.4.0 — shipped 2026-06-13)

| Phase | Name | Requirements | Status |
|-------|------|--------------|--------|
| 17 | 变量引用链路修复 | VAR-01..04 | ✅ Complete |
| 18 | 执行引擎状态机修复 | ENG-01..05 | ✅ Complete |
| 19 | 节点定义单一事实源 | SSOT-01..03 | ✅ Complete |
| 20 | 保存即合法与模板修复 | VAL-01..03, TPL-01..03 | ✅ Complete |
| 21 | 触发模型与执行可观测 | TRIG-01..03, OBS-01..03 | ✅ Complete |

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

- ✅ ~~v0.2.0 follow-up：实时明文 PAT 通道（contextvar）未接入，RemoteTool 链路休眠~~ —
  已于 2026-06-14 接入（commit 8cb50e928）：带 `friday_pat_` Bearer 的手动触发经请求级
  ContextVar → start_execution → ExecutionContext 瞬态字段下传，AICodingNode 据此注入
  `env_FRIDAY_TASK_USER_TOKEN`。明文绝不落库/进日志（PAT-02 守护测试通过）。
  **剩余**：chat/MCP 编码 dispatch 路径（`coding_session_service`）的 PAT 注入未覆盖；
  真实容器端 RTOOL-02/03/04 运行时仍需带 PAT 的真实 dispatch + 容器 E2E 人工验收（见 Deferred）。

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

Items acknowledged and deferred at milestone close. 2026-06-14 复盘清理后分三类：✅ 已解决、
🔒 需外部系统/全新实例（本地无法闭环）、🖐 纯观感人工验收（可后续浏览器抽验）。

### ✅ Resolved 2026-06-14（历史遗留清理）

| Category | Item | Resolution |
|----------|------|------------|
| tech_debt | VALIDATION.md（18-21）nyquist_compliant frontmatter 未翻转 | 回写 true（commit 37a3bd6b2，复核 tests/workflows/ 479 passed） |
| tech_debt | v0.3.0 W1：交付知识 `searchDeliveryKnowledge` 无 UI 消费 | index 占位页改为真实搜索页（5435fef23），浏览器实测搜索/空态正常 |
| tech_debt | v0.3.0 W2：timeline 节点级 provenance 未填充 | 前端渲染 node.provenance + 修后端 code_change 跨版本串味 bug（5435fef23） |
| tech_debt | v0.3.0 W3：graph enrich/related 边类型 | related.py 多跳取真实 edge.relation + 前端 relation 标签（5435fef23） |
| scope_v2 | Phase 21 project_ids/exclude_* 触发负向过滤 | _include/_exclude + Project UUID→feishu_project_key 映射（9ab638f13） |
| scope_v2 | Phase 20 input.*/trigger.* 严格静态校验 + IssuesPanel 点击居中 | graph_validator 严格校验（宽松降级）+ provide/inject fitView 居中（9ab638f13） |
| follow-up | v0.2.0 实时明文 PAT 通道未接入（RemoteTool 休眠） | ContextVar → ExecutionContext 瞬态字段下传，点亮 AICoding RTOOL（8cb50e928） |
| quick_task | 260610-oug-url-https / 260611-ghb-workflow-card-uniform（状态 unknown） | 复核两者均有 SUMMARY.md，确认已完成（标记过时，非遗留） |

### 🔒 需真实外部系统才能闭环（本地无法验证，保持 deferred）

| Item | 需要的环境 |
|------|-----------|
| Phase 14 真实 git platform 超大 diff 截断（TD-14） | 真实 GitLab/GitHub 大 MR |
| Phase 18 真实容器回调续跑 E2E | runner + Docker + 任务容器 + 真实编码 agent |
| Phase 21 真实飞书事件触发 + WS 断线降级观感 | 真实飞书应用 + 事件推送 |
| RTOOL-02/03/04 运行时（带 PAT 注入容器端到端） | 带 PAT 的真实 dispatch + 容器执行（通道已接入，待真实环境验收） |

### 🖐 纯观感人工验收（可后续浏览器抽验；2026-06-14 已部分实测）

| Item | 2026-06-14 状态 |
|------|----------------|
| Phase 17 变量所选即所得 / 端口防护 / 选择器去重（17-HUMAN-UAT 3 pending） | 有 P17 UAT 种子工作流；运行态错误展示由 tests/workflows 覆盖；未逐项点击 |
| Phase 19 画布编辑观感 | ✅ 浏览器实测：节点库 + 画布编辑器正常渲染（全节点类型可见） |
| Phase 20 IssuesPanel 交互 + 模板端到端执行 | ✅ 浏览器实测：编辑器打开 + 保存流程执行正常；校验逻辑由 graph_validator 测试覆盖 |
| Phase 21 suspended 显示 | 有 P21 suspended UAT 种子工作流 + 执行记录；前端 ExecutionStatus 由 vitest 覆盖 |
| Phase 01/02/06–11 人工验收 | 多为首启向导（需 no-superuser 全新实例）/ 身份令牌；本实例已有 superuser，需独立环境复验 |

## Session Continuity

Last session: 2026-06-14（历史遗留 tech debt 清理）
Stopped at: 6 项遗留代码全部实现并原子提交（37a3bd6b2 / 5435fef23 / 9ab638f13 / 8cb50e928）；
git 工作树干净；浏览器抽验 W1/P19/P20 正常
Resume file: None

## Operator Next Steps

- 真实环境人工验收 🔒 项（飞书/容器/git platform/带 PAT 容器 E2E），见 Deferred Items
- 可选：chat/MCP 编码 dispatch 路径的 PAT 注入（PAT 通道已就绪，复用同一 ContextVar）
- 可选：POLISH-PLAN.md P0-2b（~900 行 GSD 流程痕迹文案清洗）
- Start the next milestone with /gsd-new-milestone
