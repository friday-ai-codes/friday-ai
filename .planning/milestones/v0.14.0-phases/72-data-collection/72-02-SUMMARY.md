---
phase: 72-data-collection
plan: "72-02"
subsystem: observability / llm-metrics
tags: [RATE-02, SLA-03, SLA-04, call_source, model_usage, ttft]
requires: ["72-01 (classify_error / RequestMetric)", "71 (log_context contextvars)"]
provides:
  - "ModelUsageRecord 扩展（call_source/ttft_ms/upstream_status_code/user_id/source + run nullable）"
  - "RetrievalTrace 扩展（run nullable + user_id/conversation_id/source，供 72-04 复用）"
  - "CallSource 枚举（22 值）+ call_source contextvar 传播"
  - "interactions.ledger.arecord_llm_usage（run 可选的单一 LLM 写入入口）"
  - "interactions.ledger.parse_upstream_status（只取数值上游码）"
affects: ["72-03 容器侧 token 链路（复用 schema + helper + 枚举）", "72-04 chat 召回留痕（RetrievalTrace 新字段）"]
tech-stack:
  added: []
  patterns: ["best-effort 观测（try/except 返 None）", "sync_to_async ORM 包装", "contextvar caller 标注 + chokepoint 读取兜底"]
key-files:
  created:
    - server/agents/call_source.py
    - server/interactions/migrations/0003_modelusage_retrievaltrace_metrics.py
    - server/tests/test_model_usage_call_source.py
  modified:
    - server/interactions/models.py
    - server/interactions/ledger.py
    - server/agents/llm_concurrency.py
    - server/agents/chat_runner.py
    - server/agents/langchain_runner.py
    - server/compat/views.py
    - server/chat/views.py
decisions:
  - "compat/chat 入口用 set_call_source（非 scoped），而非计划字面的 with use_call_source —— 因 StreamingHttpResponse 生成器在 post 返回后才消费，scoped 上下文无法覆盖流式期；与既有 bind_source 范式一致（同一请求 task 内 contextvar 持续有效）"
  - "上游码解析 parse_upstream_status 落在 interactions.ledger（与 LLM 写入邻近），两个 Runner 复用；只取数值 status_code，绝不落异常文本（T-72-02-01）"
  - "_record_llm_usage 用 CallSource.normalize 默认回退 unknown（非法/空 call_source → unknown），杜绝基数失控（T-72-02-03）"
metrics:
  completed: 2026-06-24
---

# Phase 72 Plan 02: LLM TPS / 上游错误采集（RATE-02 / SLA-03 / SLA-04）Summary

一句话：扩展 `ModelUsageRecord`（+`call_source`/`ttft_ms`/`upstream_status_code`/`user_id`/`source` + `run` 改 nullable）与 `RetrievalTrace`（run nullable + user/conversation/source），定义 22 类 `CallSource` 枚举与 contextvar 传播，新增 run 可选的 `arecord_llm_usage` 单一写入入口，并在 `acquire_llm_slot`（排队/QPS）与两个 Runner 的 astream（TTFT/TPS/上游 429·529 单列）埋点，全链路 best-effort 不反噬 LLM。

## Task 结果

| Task | 说明 | 结果 |
|------|------|------|
| Task 1 | ModelUsageRecord/RetrievalTrace schema 扩展 + CallSource 枚举 + arecord_llm_usage helper + migration 0003 | **PASS** |
| Task 2 | acquire_llm_slot 排队埋点 + chat_runner/langchain_runner astream TTFT·token·上游码 + compat/chat 入口 set call_source | **PASS** |

## 验证结果

- `pytest tests/test_model_usage_call_source.py tests/test_credential_leak_protection.py -q` → **49 passed**（含枚举 22 值完整性、normalize 兜底、contextvar set/get/恢复、arecord_llm_usage run=None 落行 + user 从 contextvars 取 + 写库失败 best-effort、上游 429 单列、chat_runner TTFT+token、langchain_runner token、compat/chat call_source 传播；凭证脱敏守护 22 项保持绿）。
- `python manage.py makemigrations --check --dry-run` → **No changes detected**（0003 已生成提交，干净）。
- `ruff check`（9 个改动文件）→ **All checks passed!**（修正 3 处 import 排序）。
- 回归：`tests/test_chat_runner.py tests/agents/ tests/test_request_metric.py tests/test_ai_node_chain.py` → **209 passed, 2 skipped**；`tests/test_stream_view.py tests/workflows/test_chat_nodes.py tests/test_plan_generation_node.py tests/agents/test_llm_concurrency.py` → **69 passed**。零回归。
- 导入冒烟：`compat.views / chat.views / agents.chat_runner / agents.langchain_runner` 全部 import OK（无循环依赖）。

## 文件变更

**新增**
- `server/agents/call_source.py` — `CallSource(str, Enum)` 22 值（照抄 LOGGING-SPEC §4.1）+ `normalize(default="unknown")` + `call_source` contextvar（`get_call_source`/`set_call_source`/`use_call_source`）。
- `server/interactions/migrations/0003_modelusage_retrievaltrace_metrics.py` — AddField×8 + AlterField run→nullable(SET_NULL)×2 + AddIndex×2，`makemigrations` 自动生成。
- `server/tests/test_model_usage_call_source.py` — Task 1+2 守护测试（25 用例）。

**修改**
- `server/interactions/models.py` — `ModelUsageRecord`：`run` 改 nullable(SET_NULL)；新增 `call_source`/`ttft_ms`/`upstream_status_code`/`user_id`/`source`；新增索引 `(call_source,-created_at)` + `(upstream_status_code)`。`RetrievalTrace`：`run` 改 nullable(SET_NULL)；新增 `user_id`/`conversation_id`/`source`。
- `server/interactions/ledger.py` — 新增 `parse_upstream_status`（只取数值上游码）+ `_record_llm_usage`（同步实现，run 可选 + user 从 contextvars 兜底 + best-effort）+ `arecord_llm_usage`（async 包装）。既有 `record_model_usage`/`arecord_model_usage` 零改动（MCP 路径向后兼容）。
- `server/agents/llm_concurrency.py` — `acquire_llm_slot` 加排队计时 + `_log_slot_acquired`（`llm_slot_acquired`，category=sampling/component=llm/queue_wait_ms/call_source）；两处 `llm_slot_busy_timeout` 补 category=caller/component=llm。控制流不变。
- `server/agents/chat_runner.py` — astream 每 turn 计首 chunk TTFT + 收尾 `arecord_llm_usage(call_source=get_call_source() or chat, …)`；generic except 解析上游码落 failure 行。整段 try/except 包裹，不触碰 interrupt-latch 保护区。
- `server/agents/langchain_runner.py` — 对称处理：astream 计 TTFT + 收尾 `arecord_llm_usage(call_source=… or workflow_agent_node, input/output/cache token)`；provider 异常 except 落上游码 failure 行。
- `server/compat/views.py` — `ChatCompletionsView.post` set `CallSource.CHAT_COMPAT_OPENAI`；`MessagesView.post` set `CHAT_COMPAT_ANTHROPIC`。
- `server/chat/views.py` — `ChatStreamView.post` set `CallSource.CHAT`。

## Deviations from Plan

**1. [Rule 3 - 阻塞修正] compat/chat 入口用 `set_call_source` 取代字面的 `with use_call_source`**
- 计划 `<action>` 字面写 `with use_call_source(...)` 包裹调用链；但 compat/chat 的流式响应是 `StreamingHttpResponse(streaming_content=<async gen>)`，生成器在 `post` 返回**之后**才被 ASGI 消费，scoped 上下文管理器无法覆盖流式 LLM 调用期 → 流式调用会丢失 call_source 归类。
- 修正：改用非 scoped 的 `set_call_source(...)`，与既有 `bind_source` 完全同一范式（同一请求 task 内 contextvar 持续有效，流式生成器消费期可读到）。`use_call_source` 上下文管理器仍保留并被测试覆盖（供 workflow 节点等同步作用域 caller 使用）。
- 影响：仅入口标注方式不同，语义/安全等价（call_source 经 normalize 受控）。

**2. [范围] workflow ainvoke 站点（AIPromptNode/AIVariableExtractorNode）未直接埋点**
- 计划 Task 2.3 提及各 `ainvoke` 站点写一行；但这些站点位于 workflow 节点文件（**不在本 plan 的 `files_modified`**），且 `langchain_runner` 自身只有 astream（无 ainvoke）。本 plan 在 `langchain_runner.astream` 收尾埋点并以 `get_call_source()` 读取 caller 经 `use_call_source` 设定的 call_source 兜底 `workflow_agent_node`；节点级 caller 标注（设 `workflow_prompt_node`/`workflow_variable_extractor` 等）留待引用方按需接入，不越界改动计划外文件。

## 安全 / 脱敏校验

- `arecord_llm_usage` 只记 token 计数 + 数值上游码 + 受控枚举标签，**绝不**落 prompt/completion 明文（T-72-02-02）或上游响应体/异常文本（T-72-02-01，`parse_upstream_status` 只取 int）。
- `user_id` 取服务端 Phase 71 contextvars，不取客户端输入（T-72-02-04）。
- 全部观测调用 try/except 包裹 + helper 内部 best-effort 返 None，写库失败不反噬 LLM 主流程（T-72-02-05）。
- `test_credential_leak_protection.py` 22 项保持全绿。

## Self-Check: PASSED

- `server/agents/call_source.py`、`server/interactions/migrations/0003_modelusage_retrievaltrace_metrics.py`、`server/tests/test_model_usage_call_source.py` 均存在。
- migration `makemigrations --check` 干净；新测试 + 凭证脱敏守护 49 passed；回归 209+69 passed；ruff 干净。
