---
status: verifying
trigger: "AGE-65 真实 canary 暴露 Team 字段未进入 canonical gate、missing_team 生成空 repo_confirmation、MCP 请求超时留下永久 idempotency_pending"
created: 2026-09-01
updated: 2026-09-01
---

# Symptoms

- Expected: 工作项可信团队字段“学习A”进入 canonical Team gate；若团队仍缺失，应打开团队澄清题而非仓库确认题。
- Actual: Team gate 记录 `missing_team`，随后打开 `kind=repo_confirmation`、`repo_count=0`、`options=0`。
- Error: 首次 MCP create 超时被 ASGI 取消后，预留记录永久保持 `failed_stage=idempotency_pending`，重试只返回 `in_progress`。
- Timeline: 2026-09-01 AGE-65 真实回归中复现。
- Reproduction: 使用 eventId `gaosan-routing-fix-canary-20260901-02` 创建高三提分专项蓝图。

# Current Focus

- hypothesis: Team 上下文未从 McpWorkItemContext 投影到 route stage；确认门未区分 team clarification；幂等预留无租约/陈旧接管机制。
- test: 增加生产形态回归覆盖可信 Team、missing_team 澄清类型、超时后同 key 恢复。
- expecting: canonical 链不再需要 Agent 手工调用 route_repositories/start_repo_research，且超时重试能继续原会话或安全接管。
- next_action: 定位三个状态转换与既有测试落点。

# Evidence

- timestamp: 2026-09-01T10:48:23Z
  observation: `team_gate_completed gate_outcome=clarify clarify_reason=missing_team team_core_count=0`
- timestamp: 2026-09-01T10:48:31Z
  observation: `blueprint_confirmation_opened kind=repo_confirmation repo_count=0 option_count=0`
- timestamp: 2026-09-01T10:45:46Z
  observation: pending 记录无 artifact、无 ConvergenceSession；条件化删除后同 key 成功创建蓝图。
- timestamp: 2026-09-01T11:07:53Z
  observation: 后端扩展回归 147 passed；MCP 32 passed 且 build 成功；Ruff 通过。
- timestamp: 2026-09-01T11:09:15Z
  observation: 本机与 Multica skill/MCP/Agent 要求已同步；新建真实 canary AGE-66，运行中。
- timestamp: 2026-09-01T11:13:40Z
  observation: AGE-66 完成；primary_team=学习A 已贯穿，但 Space 仓库的“团队归属”仅为 backend/frontend，零仓可映射业务团队，正确停在 Team clarification。

# Eliminated

- hypothesis: PostgreSQL 服务整体宕机
  reason: 经 vision 隧道完成 PostgreSQL 17.10 认证与查询，数据库本体健康。

# Resolution

- root_cause:
- fix: 显式可信 primary_team 贯穿 MCP→session；missing_team 打开 Team clarification；取消前置阶段释放幂等预留并允许同 key 接管。
- verification: AGE-66 验证 MCP 参数与澄清门生效；发现 Repository facets 把技术职能团队与业务团队混用，需独立业务 Team 映射后再验路由。
- files_changed: server/mcp_tools/*, server/services/process_runtime/{entrypoint,blueprint_confirm_gate}.py, mcp/src/tools.ts, friday-solution skill, tests
