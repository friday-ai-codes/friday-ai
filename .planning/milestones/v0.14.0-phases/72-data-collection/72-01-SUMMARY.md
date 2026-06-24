---
phase: 72-data-collection
plan: "72-01"
subsystem: observability / request-metrics
tags: [RATE-01, SLA-02, SLA-04, metrics, request-instrumentation]
requires:
  - Phase 71 contextvars (user_id/request_id/source) + RequestLogContextMiddleware
  - system/log_sink.py 队列范式（镜像）
provides:
  - RequestMetric 精简事件表（每请求一行）+ 0010 迁移
  - classify_error 三口径单一收口（none/system/business/upstream）
  - record_request_metric / arecord_request_metric best-effort 写入 helper
  - metric_sink 队列 + 批量落库 worker（镜像 log_sink）
  - 全入口埋点：HTTP 中间件 / MCP / chat SSE / compat(OpenAI+Anthropic) / webhook / WS
affects:
  - Phase 72-02（LLM TPS 复用 classify_error）
  - Phase 73（Postgres percentile_cont SQL 聚合消费 RequestMetric）
tech-stack:
  added: []
  patterns:
    - 队列 + daemon worker 批量 bulk_create（镜像 log_sink，热路径零 ORM）
    - best-effort 观测（except: pass，绝不反噬业务）
    - 受控 labels 白名单过滤（禁用户输入原文）
    - 中间件「source==rest 才记录」+ 专用入口 bind_source 自记，保证每请求一行
key-files:
  created:
    - server/common/request_metrics.py
    - server/system/metric_sink.py
    - server/system/migrations/0010_requestmetric.py
    - server/tests/test_request_metric.py
  modified:
    - server/system/models.py
    - server/common/middleware.py
    - server/mcp_tools/views.py
    - server/chat/views.py
    - server/compat/views.py
    - server/system/webhook_recorder.py
    - server/workflows/consumers.py
    - server/runners/consumers.py
decisions:
  - "webhook 埋点落在 system/webhook_recorder.record_inbound_webhook（71 留痕单一收口），而非 plan files_modified 列出的 system/webhook_views.py（实为只读查看器）/ 逐个 feishu view"
  - "中间件仅当 contextvars source 仍为默认 rest 时记录；MCP/chat_sse/compat/webhook/WS 各自 bind_source + 自记，避免重复计数"
  - "流式入口（chat SSE / compat 流式）在生成器内记首 chunk ttft + 总 duration，中间件因 source!=rest 自动跳过"
metrics:
  duration_minutes: ~40
  completed_date: 2026-06-24
---

# Phase 72 Plan 01: 请求入口指标采集（RequestMetric）Summary

为所有请求入口建立"每请求一行"的精简事件采集地基：新增 `RequestMetric` 模型 + 统一 `classify_error` 三口径收口 + 队列化 best-effort 落库，并在 HTTP 中间件 / MCP / chat SSE / compat(OpenAI·Anthropic) / webhook / WS 全入口埋点，把 QPS/错误三口径/时长/TTFT 写成原始事件行，供 Phase 73 用 Postgres `percentile_cont` 做精确分位聚合。

## Per-Task 结果

| Task | 名称 | 结果 |
|------|------|------|
| 1 | RequestMetric 模型 + classify_error + metric_sink + 写入 helper + migration + 测试 | **PASS** |
| 2 | HTTP 中间件 + MCP + chat SSE 入口埋点 | **PASS** |
| 3 | compat + webhook + WS 入口埋点 | **PASS** |

## 实现要点

### Task 1 — 地基三件套
- `system/models.py` 新增 `class RequestMetric`：`BigAutoField` 主键、`ts/source/route/method/status_code/error_class/duration_ms/ttft_ms/user_id/labels`；复合索引 `(ts,source)`+`(ts,error_class)`+`(-ts)`；`db_table="request_metrics"`，append-only。
- `0010_requestmetric.py` 自动生成（`makemigrations --check` 干净）。
- `common/request_metrics.py`：`classify_error`（LLMBusyError/DRF·Django PermissionDenied/ValidationError/403/400→business；429/529 或上游标志→upstream；5xx/未捕获→system；2xx/3xx→none）+ `record_request_metric` / `arecord_request_metric`（user_id 缺省取 Phase 71 contextvars，labels 白名单过滤，整段 best-effort）。
- `system/metric_sink.py`：镜像 `log_sink`——`deque(maxlen=5000)` + `_lock` + 四计数（enqueued/written/dropped/write_failed）+ `friday-metric-sink` daemon worker + `_is_under_pytest()`（测试不起线程，用 `flush_now`）+ `_to_metric` 截断列宽 & labels 再过滤 + `snapshot_counters`/`flush_now`/`_reset_for_tests`。

### Task 2 — 中间件 + MCP + chat SSE
- `common/middleware.py` 扩展 `RequestLogContextMiddleware`：`perf_counter` 计时 + 异常捕获（记录后原样抛出），请求结束在 `finally` 记一行 `RequestMetric`；**仅当 contextvars source 仍为默认 `rest` 时记录**（专用入口自记，避免重复计数）；`route` 取 `resolver_match.route` 去 path 参数/query；health/`observability`/`dashboard`/`*/poll` 命中打 `labels.synthetic=true`。
- `mcp_tools/views.py`：`_begin` 顶 `bind_source(MCP)`（中间件跳过兜底）；`_record` 旁路 `arecord_request_metric(source=mcp, labels.call_source=tool_name + run_id)`。
- `chat/views.py` `ChatStreamView`：`post` 中 `bind_source(CHAT_SSE)`；`_stream_events` 首个真实 chunk 计 `ttft_ms`、生成器 `finally` 记总 `duration_ms`（source=chat_sse，labels.conversation_id），流中途异常经 `classify_error` 归类。

### Task 3 — compat + webhook + WS
- `compat/views.py` `ChatCompletionsView`/`MessagesView`：`post` 顶 `bind_source(compat_openai/compat_anthropic)`；流式生成器记首帧 ttft + 总 duration；非流式 + 校验/凭证缺失返回前各记一行（经 classify_error 归类）。
- `system/webhook_recorder.py` `record_inbound_webhook`（**71 留痕单一收口**）旁路 `_record_webhook_metric`：按 `kind` 映射 source（feishu→webhook_feishu / workflow→webhook_workflow / git_push→webhook_git / container_callback），user=system，labels=correlation（白名单过滤）；与留痕独立 best-effort。
- `workflows/consumers.py` + `runners/consumers.py`：connect 后记 `ws_event=connect`（status 101）、disconnect 记 `ws_event=disconnect` + 连接时长（从 connect 时刻起算），均 best-effort 不影响握手/收发。

## Deviations from Plan

### [设计决策] webhook 埋点落在 `record_inbound_webhook` 而非 plan 列出的文件
- **Found during:** Task 3。
- **原因:** plan `files_modified` 列 `server/system/webhook_views.py`，但该文件实为**只读的入站 webhook 查看 API（LOG-07 viewer，IsSuperUser）**，并非 webhook 摄入入口；其请求本就走中间件按 source=rest 记录，无需另埋。真正的「71 已留痕处」单一收口是 `system/webhook_recorder.record_inbound_webhook`（feishu/workflow/git/container 各 webhook 入口统一经此留痕，feishu webhook view 已确认调用）。
- **Fix:** 在 `record_inbound_webhook` 末尾旁路一行 `RequestMetric`（kind→source 映射），DRY 覆盖全部 webhook 种类。未改动 `system/webhook_views.py` 与 `feishu/views.py`（feishu webhook 经 recorder 链路已覆盖）。
- **Files modified:** `server/system/webhook_recorder.py`（不在 plan files_modified，但为最正确的单一收口）。

### [设计决策] 中间件「source==rest 才记录」+ 专用入口 bind_source 自记
- **原因:** plan Task 2.1 字面为「source=<当前 contextvars source 或 rest>」由中间件记录，但若中间件对 mcp/chat_sse/compat 等也记录，会与专用入口的 ttft/call_source 指标行**重复计数**，违背 success criteria「每请求恰一行」。
- **Fix:** 中间件仅在 source 仍为默认 `rest` 时兜底记录；MCP/chat_sse/compat/webhook/WS 各自 `bind_source` 改写来源并自记带 ttft/call_source/关联键的指标行 → 每请求恰一行，来源精确。

## Threat Model 落实
- T-72-01-01（labels 注入用户输入原文）：`_ALLOWED_LABEL_KEYS` 白名单在 helper + sink 双重过滤；route 取 URL pattern 去 query/path 参数。
- T-72-01-02（凭证泄漏）：RequestMetric 仅记元数据，不接收 raw body/headers/凭证；user_id 取服务端 contextvars。`test_credential_leak_protection.py` 复跑全绿。
- T-72-01-03（高频同步 ORM DoS）：enqueue 纯内存非 ORM，落库交 daemon worker 批量，`maxlen=5000` 满则丢弃计数。
- T-72-01-04（source 污染基数）：source 取 Phase 71 `LogSource` 受控枚举 / 各入口硬编码常量。

## Known Stubs
None — 所有埋点点位均写入真实 RequestMetric 行；无占位/mock 数据流。

## 验证结果

- `pytest tests/test_request_metric.py tests/test_credential_leak_protection.py -q` → **54 passed**（含 test_request_metric 30 条三任务守护 + 凭证脱敏 24 条全绿）。
- 叠加 `tests/test_log_context_propagation.py` → **71 passed**（既有中间件/飞书 webhook 守护无回归）。
- 触点回归 smoke（`-k "compat or mcp_tools or chat_stream or feishu_webhook"`）→ **234 passed, 3 skipped**，0 失败。
- `python manage.py makemigrations --check --dry-run` → **No changes detected**（0010 已生成）。
- `ruff check`（全部改动文件）→ **All checks passed**（line-length 100；chat/views.py 导入排序经 `ruff --fix` 归位）。

## Self-Check: PASSED
- 创建文件均存在：`common/request_metrics.py` / `system/metric_sink.py` / `system/migrations/0010_requestmetric.py` / `tests/test_request_metric.py`。
- RequestMetric 模型 + 迁移就位，`makemigrations --check` 干净。
- classify_error 三口径、record_request_metric 经队列 best-effort 落库、全入口埋点经测试覆盖（rest/synthetic/mcp/chat_sse/compat_openai/compat_anthropic/webhook_*/ws）。
