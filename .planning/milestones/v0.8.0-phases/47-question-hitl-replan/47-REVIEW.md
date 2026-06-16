---
phase: 47-question-hitl-replan
depth: standard
reviewed: 2026-06-17
status: resolved
---

# Phase 47 — Code Review

**Scope (changed source files):**
- `task/integrations/callback.py` — `report_question`
- `task/core/question_loop.py` — ask_user 工具 + 等待回答循环
- `task/core/executor.py` — coding 模式挂载 ask_user
- `task/core/runner.py` — 传入 callback
- `server/subagent/question_handler.py` — chat_id 解析统一委派

---

## Findings

| # | Severity | File | Finding | Disposition |
|---|----------|------|---------|-------------|
| 1 | Warning | task/core/question_loop.py | `ask_user_and_wait` 读取 `answer.json` 后未清除——多轮提问时下一轮会立即误读上一轮的陈旧回答 | **Fixed**：消费后 `os.remove(answer_path)`（best-effort）；新增测试断言文件被清除 |
| 2 | Info | task/core/executor.py | ask_user 挂载使 execute 模式 `allowed_tools` 成为排他白名单 | Accept：白名单含 `_BUILTIN_CODING_TOOLS`（对齐 server runner 内建集），仅 callback 配置时触发；standalone/测试零回归 |
| 3 | Info | task/core/question_loop.py | 等待期 `report_status(progress)` 非真正 heartbeat 帧 | Accept：容器存活由 Go runner 独立心跳维持（python 任务阻塞在工具内，进程存活 → runner 持续心跳），progress 仅作进度提示 |
| 4 | Info | server/subagent/question_handler.py | chat_id 解析改为统一委派 `_resolve_notification_chat_id` | Accept（改进）：消除原直接访问 `session.main_session` 的 async lazy-FK（SynchronousOnlyOperation）风险，chat 路径行为等价 |

## Security
- 凭证/问题/回答正文均不入日志（仅 `has_*`/id/status）——符合 RTOOL-03 脱敏与项目约定。
- chat_id 取服务端权威字段（main_session.metadata / node.config），不取 runner 可篡改的 last_output（T-47-01 缓解）。
- 等待循环有界（timeout_minutes），handler 永不 raise（RTOOL-04）——无挂起/崩容器风险（T-47-03）。
- no-replan 链路守护测试通过（T-47-06）。

## Resolution
- Finding 1 已修复并提交；其余为 Accept。无 Critical。
