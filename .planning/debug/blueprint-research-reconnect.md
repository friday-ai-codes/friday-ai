---
status: resolved
trigger: "Multica 技术方案智能体触发的 Friday 蓝图长期停在 researching；逐仓容器已退出或消失，但调研任务、SubAgentSession 与 RunnerTaskAssignment 仍保持 running。"
created: 2026-08-27
updated: 2026-08-27
---

# Debug Session: blueprint-research-reconnect

## Symptoms

- Expected behavior: Runner 重连时，仍存活的容器继续执行；已消失的容器应可靠重派或失败收敛，并触发蓝图 barrier。
- Actual behavior: 蓝图 `807fd066-300a-4a48-a6cf-92cb11e33a3a` 长期停在 `researching`，10 个 `RepoResearchTask` 均为 `running`。
- Error messages: 首轮 6 个容器因网关额度失败；第二轮及其余容器没有终态回调，assignment 与 SubAgentSession 永久保持 `running`。
- Timeline: 2026-08-26 18:12 左右开始，至 2026-08-27 仍未收敛。
- Reproduction: Runner 执行任务期间重启或容器消失，随后以空 `running_tasks` 重连。

## Current Focus

- hypothesis: `_recover_pending_tasks` 对已消失容器直接调用 dispatcher 重派，但旧 assignment 仍是 active；dispatcher 的 `_has_active_assignment` 因此将重派误判为幂等命中并跳过。
- test: 构造 active assignment + 空 `running_tasks`，验证恢复前旧 assignment 被收敛，dispatcher 才能真正重派；仍在 running_tasks 中的任务保持不变。
- expecting: 已消失任务的旧 assignment 标为 failed，随后创建新的 active assignment；仍存活任务不重派。
- next_action: 修复已完成；提交后对历史卡住的蓝图执行一次安全恢复。
- reasoning_checkpoint:
- tdd_checkpoint:

## Evidence

- timestamp: 2026-08-27T19:40:00+08:00
  observation: 蓝图会话状态为 waiting_event/repo_research；10 个 RepoResearchTask 全为 running，最晚更新时间停在 2026-08-26 18:16。
- timestamp: 2026-08-27T19:40:00+08:00
  observation: 16 条相关 assignment 中 6 条首轮 failed，其余 10 条仍 running；Runner spider-dev 当前在线且 current_tasks=0。
- timestamp: 2026-08-27T19:40:00+08:00
  observation: `_recover_pending_tasks` 在容器不在 running_tasks 时直接调用 dispatch；`TaskDispatcher._try_assign` 会因同一旧 active assignment 存在而返回成功但不发送任务。

## Eliminated

- hypothesis: Multica 技术方案 Agent 没有继续轮询。
  reason: Friday 蓝图自身的 RepoResearchTask 未进入终态，Agent 轮询无法越过服务端 barrier。
- hypothesis: 当前仍是 MCP 缺少 idempotency_key/blueprint_project_id。
  reason: 当前 MCP schema 已具备两个参数；AGE-39 后续执行已成功取到蓝图。

## Resolution

- root_cause: `_recover_pending_tasks` 在 runner 未上报旧 task_id 时直接调用 dispatcher 重派，但旧 assignment 仍是 assigned/running；durable dispatcher 的 active-assignment 守卫因此跳过真实派发。Runner 快速重连又使断连超时清理提前退出，三者组合后任务永久卡住。
- fix: 容器确认消失时，先把旧 assignment 标为 failed 并写 completed_at，再按持久化快照进入 durable 重派；runner 明确上报仍在运行的任务保持不动。
- verification: `uv run pytest tests/test_runner_recovery.py -q`（11 passed）；`uv run ruff check runners/consumers.py tests/test_runner_recovery.py`（passed）。
- files_changed: `server/runners/consumers.py`、`server/tests/test_runner_recovery.py`
