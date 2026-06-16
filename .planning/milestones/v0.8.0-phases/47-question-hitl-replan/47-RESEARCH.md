## RESEARCH COMPLETE

# Phase 47 — Technical Research: 编码遇阻 → question 抛人（HITL，非全自动 replan）

**Researched:** 2026-06-17
**Phase requirement IDs:** HITL-01

---

## 1. 问题定位（病根）

编码 wave 路径（`AICodingNode` 派发 `RepoCodingTask` 容器）遇阻时的现状死路：

- 容器执行失败 / agent 遇阻无法自解 → `task/core/runner.py` 走 `callback.report_error(...)` → `CallbackClient.report_failed` → server `subagent/api/callbacks.py:_handle_failed`。
- `_handle_failed` 的注释明确：「Runner 端独立处理重试，Server 端不再重试」——直接 `amark_failed` → `wave_progression._backfill_running_terminal` 把 `RepoCodingTask` 标 `failed` → `_block_downstream_transitive` 阻断下游 → **dead-end，无人介入**。

**关键观察**：task 侧当前**没有**任何「遇阻向人提问」的能力（`task/` grep `question` 仅命中注释；`CallbackClient` 无 `report_question`；executor 无 `ask_user` 工具、无 answer 等待循环）。这是本 phase 的主要新增面。

---

## 2. 既有 question 协议契约（复用目标，不另造）

完整的容器提问协议**已存在**（server 侧），供本 phase 复用：

- **协议帧**：`CallbackType.QUESTION`（`services/protocols.py`），`QuestionPayloadSerializer`（`subagent/api/serializers.py`）字段：`question` / `options` / `context` / `code_snippet` / `default_option` / `timeout_minutes`。
- **接收处理**：`subagent/api/callbacks.py:_handle_question` —— 生成 `question_id`、创建 `InteractionLog`、写 `session.last_output.pending_question`、fire-and-forget 发飞书卡片。对任意 `SubAgentSession`（含带 `node_execution_id` 的 wave 编码任务）通用。
- **发卡**：`subagent/question_handler.py:send_question_card_enhanced` —— 但**仅**从 `session.main_session.metadata.chat_id` 取 chat_id；wave 编码任务（`node_execution_id`、可能无 `main_session`）**取不到 chat_id → 不发卡**（gap）。
- **回答回灌**：`handle_container_answer_enhanced` —— 更新 `InteractionLog`、`_send_answer_to_container`（HTTP 直达 `last_output.answer_endpoint`）优先、`write_answer_to_volume`（`ANSWER_FILE = answer.json` 共享卷 `/workspace/.friday/`）兜底、清 `pending_question`。
- **协议文件常量**：`QUESTION_FILE` / `ANSWER_FILE` / `CONTAINER_PROTOCOL_DIR=/workspace/.friday`（`services/protocols.py`）。容器内映射 = 宿主 `server/data/transfers/{session_id}/.friday/`。

**结论**：server 侧接收/回灌/清理**已闭环**；唯一 server 缺口 = wave 编码任务（node_execution）的发卡路由（`send_question_card_enhanced` 只认 main_session chat_id）。

---

## 3. 既有 resume 通路（复用目标，不另造）

- **Phase 43**：`_schedule_workflow_resume`（`callbacks.py`）—— 容器终态回调 → 检查节点全部 `SubAgentSession` 终态 → 写 `_resume_from_callback` → `WorkflowEngine._continue_after_node` 节点重入。
- **Phase 44**：`wave_progression.aadvance_coding_waves` —— 节点重入时回填在途终态 → 传递闭包阻断 → 决策出口（`waiting` / `dispatch` / `all_terminal`）。**关键**：`_backfill_running_terminal` 只回填 `SubAgentSession` 已终态（completed/error/timeout/cancelled）的 task；`RUNNING` 在途 task **跳过**（等下次回调），决策出口因有 RUNNING 而返回 `{"waiting": True}`。

**承接 HITL 的机制**：容器发起 question 后**保持 RUNNING**（在容器内阻塞等回答 + 持续心跳保活）→ `aadvance_coding_waves` 视其为在途 → `waiting`，**不阻断下游、不死锁、不 dead-end**。回答后容器继续编码 → 最终 `report_completed`/`report_failed` → 既有 `_handle_completed`/`_handle_failed` → `_schedule_workflow_resume` → `aadvance_coding_waves` 推进。**无需新增任何 resume 通路**。

---

## 4. task 侧新增面（主要工作）

### 4.1 `CallbackClient.report_question`（`task/integrations/callback.py`）
镜像既有 `report_failed`/`report_completed`：POST `type=question`，payload 严格对齐 `QuestionPayloadSerializer`（`question`/`options`/`context`/`code_snippet`/`default_option`/`timeout_minutes`）。复用既有 `_callback_endpoint()` + token 注入 + httpx 异常 fail-soft（返回 bool）。脱敏：日志只记 `has_question`/`status`，绝不记问题正文敏感片段。

### 4.2 `ask_user` 进程内 SDK MCP 工具 + 等待回答循环（`task/core/`）
- 编码 agent 遇阻时调 `ask_user` 工具（mirror `remote_tools.py` 的 `SdkMcpTool` + `create_sdk_mcp_server` 范式，及 `executor.py:384` 的 repo_summary MCP server 范式）。
- handler：① `report_question` 发卡 → ② 轮询 `answer.json`（`CONTAINER_PROTOCOL_DIR/ANSWER_FILE`）等回答，期间持续 `report_status`（heartbeat/progress）保活 → ③ 取到回答 → 作为工具结果文本 return 给 agent 继续编码。
- **超时（最安全默认）**：超过 `timeout_minutes` 无回答 → 有 `default_option` 用之续跑；否则返回结构化工具错误（is_error）让 agent 自行收尾，或由 runner 在 agent 结束后判定 → 绝不无限挂起、绝不 replan。handler 永不 raise（RTOOL-04 范式）。
- 工具落点：新模块 `task/core/question_loop.py`（`ask_user_and_wait` 纯逻辑可单测 + `build_ask_user_mcp_server(config, callback)`）；executor 在 coding/execute 模式经 `_build_options` 的 `extra_mcp_servers`/`extra_allowed_tools` 扩展点挂载（向后兼容：无 callback 时不挂）。

---

## 5. server 侧改动面（最小）

- **唯一生产改动**：`send_question_card_enhanced` 增加 node_execution chat_id fallback —— 复用 `callbacks._resolve_notification_chat_id`（已支持 main_session + node_execution 双路由），lazy import 防环。缺 chat_id 仍 fail-soft（不发卡、不抛、`InteractionLog` 仍创建供 orchestrator 轮询）。
- 其余（`_handle_question` / `handle_container_answer_enhanced` / resume）**全部复用，不改**。

---

## 6. 非目标守护（HITL-01c，硬约束）

编码遇阻 question/answer/resume 全链路**绝不**触发 replan / 重调研 / `start_*_research` / research 容器重派发。全自动回溯（REPLAN-01）留 backlog。守护方式：单测断言该路径不调用任何 research/replan 编排入口（mock spy + 路径审查）。

---

## 7. 测试策略（IO 边界 mock，真实 Docker 沿用既有 deferred）

| 层 | 测试 | 文件 |
|----|------|------|
| task | `report_question` payload 对齐 serializer；`ask_user_and_wait` 取回答/超时→default/超时→fail；轮询解析 answer.json 幂等 | `task/tests/test_question_loop.py` |
| server | wave 编码（node_execution）question 回调 → InteractionLog + 卡片路由 node_execution chat_id；缺 chat_id fail-soft | `server/tests/test_coding_question_hitl.py` |
| server e2e | wave 编码遇阻 → SubAgentSession RUNNING + pending_question → `aadvance_coding_waves` 返回 `waiting`（不阻断下游/不死锁）→ 回答 → 容器 completed → `aadvance_coding_waves` 推进 | `server/tests/test_coding_question_hitl.py` |
| guard | no-replan：HITL 链路不触发 research/replan 编排 | `server/tests/test_coding_question_hitl.py` |
| 零回归 | 既有 chat 编码提问循环（`test_question_loop_integration.py`）不变；happy-path wave 编码（`test_coding_wave.py`）不变 | 既有套件 |

## Validation Architecture
（见 47-VALIDATION.md —— 复用既有 pytest 基建，无新增框架。）

---

## 8. 关键 Pitfalls

1. **等待期必须保 RUNNING**：若 task 侧遇阻走 `report_failed` 或容器退出，wave 即 dead-end；HITL 必须在容器内阻塞 + 心跳，使 SubAgentSession 保持 RUNNING。
2. **import 环**：`question_handler` 复用 `_resolve_notification_chat_id` 须 lazy import（callbacks 已 lazy import question_handler）。
3. **脱敏**：question/answer 文本不入日志，仅 `has_*`/id/status。
4. **幂等**：重复 question 回调（同 session 多轮）各自独立 InteractionLog；回答覆盖式幂等。
5. **超时不挂起不 replan**：default_option 或优雅失败，绝不无限等、绝不触发回溯重规划。
