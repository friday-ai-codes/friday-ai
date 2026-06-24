---
phase: 72-data-collection
verified: 2026-06-24T15:38:08Z
status: passed
score: 6/6 success criteria met in code; test-isolation gap CLOSED (test_model_usage_call_source 三个 async 写库测试类改用 django_db(transaction=True)，合并命令 95 passed + 随机序 34 passed)
gaps:
  - truth: "运行规范命令 `cd server && uv run pytest tests/test_request_metric.py tests/test_model_usage_call_source.py tests/test_container_token_chain.py tests/test_rag_metrics_trace.py tests/test_credential_leak_protection.py -q` 应全绿"
    status: partial
    reason: "Phase 72 自身新增的测试存在跨连接 DB 隔离缺陷：test_model_usage_call_source.py 的 async 测试用普通 @pytest.mark.django_db（非 transaction=True），其经 sync_to_async 在独立连接 create 的 ModelUsageRecord 行被提交且不回滚 → 泄漏到后续文件；test_container_token_chain.py::test_coding_token_usage_bridges_to_model_usage_record 断言的是 ModelUsageRecord.objects.all() 全表计数==1（未按 session 过滤），因此被泄漏行污染。在 pytest-randomly 随机顺序下复现为 `assert 10 == 1`。固定顺序 `test_model_usage_call_source.py → test_container_token_chain.py` 稳定复现。注：这与 RAG/structlog 既有跨模块污染是不同的一类问题，且为本 Phase 测试文件引入（72-04 已为 test_rag_metrics_trace.py 用 transaction=True 修复同类问题，但 72-02 未对 test_model_usage_call_source.py 应用）。生产采集代码本身正确——每个套件单独跑均全绿，桥接确实只落一行 ModelUsageRecord。"
    artifacts:
      - path: "server/tests/test_model_usage_call_source.py"
        issue: "async 写库测试用 @pytest.mark.django_db（行 147/251/341 等三个测试类），跨连接提交的 ModelUsageRecord 不被回滚，泄漏到其它测试文件"
      - path: "server/tests/test_container_token_chain.py"
        issue: "test_coding_token_usage_bridges_to_model_usage_record 断言 len(ModelUsageRecord.objects.all())==1 为全表计数，对泄漏行脆弱"
    missing:
      - "对 test_model_usage_call_source.py 中写 ModelUsageRecord 的 async 测试类改用 @pytest.mark.django_db(transaction=True)（对齐 72-04 对 test_rag_metrics_trace.py 的修复）"
      - "或将 test_container_token_chain.py 的断言改为按 session/run 过滤计数（ModelUsageRecord.objects.filter(...).acount()==1）而非全表 all()"
deferred: []
---

# Phase 72: 调用数据采集（AI/LLM + 召回 + 请求入口）Verification Report

**Phase Goal:** 把所有"能成时序"的调用数据采集到精简事件表——QPS/TPS/召回/请求错误三口径/上游错误码/时长/TTFT。本 Phase 只写数据，查询/出图在 Phase 73。
**Verified:** 2026-06-24T15:38:08Z
**Status:** gaps_found
**Re-verification:** No — initial verification

## Goal Achievement

### Observable Truths (ROADMAP Phase 72 Success Criteria)

| # | Truth (Success Criterion) | Status | Evidence |
|---|---------------------------|--------|----------|
| 1 | QPS 每入口一行 RequestMetric，覆盖 REST/MCP/对话 SSE/OpenAI·Anthropic 兼容/召回/embedding·reranker/webhook/WS；轮询·health 打标隔离 | ✓ VERIFIED | `system/models.py` `class RequestMetric`（ts/source/route/method/status_code/error_class/duration_ms/ttft_ms/user_id/labels + 复合索引）；33 处埋点/`bind_source`/`set_call_source` 散落 `common/middleware.py`、`mcp_tools/views.py`、`chat/views.py`、`compat/views.py`、`system/webhook_recorder.py`、`workflows/consumers.py`、`runners/consumers.py`；中间件 health/observability/dashboard/poll → `labels.synthetic=true`；`tests/test_request_metric.py` 14 passed（含 rest/synthetic/mcp/chat_sse/compat/webhook/ws） |
| 2 | TPS per provider（ModelUsageRecord +call_source/ttft_ms/upstream_status_code），22 类 call_source，input/output/cache token；**含容器侧端到端** | ✓ VERIFIED | `agents/call_source.py` `CallSource` 恰 22 个枚举值；`interactions/models.py` ModelUsageRecord 扩 call_source/ttft_ms/upstream_status_code/user_id/source + run nullable；`interactions/ledger.py` `arecord_llm_usage`(run 可选)；容器链闭合：`task/integrations/callback.py::report_token_usage` → `task/core/executor.py` 在 `_write_usage_data` 后主动 emit（四类容器经 `_execute_claude` 单一 chokepoint）→ `subagent/api/callbacks.py::_handle_token_usage` 桥接 `arecord_llm_usage(run=None, source="container_callback")`，`call_source` 由 `_derive_container_call_source(session)` 服务端权威派生四类。**链路真实闭合**：`tests/test_container_token_chain.py` 9 passed（isolation）+ `task/tests/test_usage_emit.py` 14 passed + `tests/test_model_usage_call_source.py` 15 passed |
| 3 | 召回条数 + 分层耗时(embedding/sparse/qdrant/rerank) + score，按来源(MCP/对话/workflow)区分 | ✓ VERIFIED | `services/retrieval/rag_search.py` `_record_rag_metric` 用 perf_counter 旁路计四阶段 `stage_embedding_ms/stage_sparse_ms/stage_qdrant_ms/stage_rerank_ms` + `recall_count` + `top_score` + `rag_status`，出口（含 error 早退）写 `record_request_metric(source="rag")`；来源经 `call_source` 区分；zero-drift；`tests/test_rag_metrics_trace.py` 7 passed |
| 4 | 召回内容留痕扩展到 MCP + AI 对话两条链（RetrievalTrace：query+chunk+score+会话/用户） | ✓ VERIFIED | `interactions/ledger.py` `arecord_retrieval_trace` 增 run 可空 + user_id/conversation_id/source（默认 contextvars），payload 经 `redact_for_ledger`；`agents/tools/space_tools.py::search_repository_code` 注入 conversation_id + top-N 采样写 RetrievalTrace（覆盖对话链）；MCP 既有写入经 helper 默认值自动获 user 绑定；`tests/test_rag_metrics_trace.py` + `tests/mcp_tools/test_retrieval_trace.py` 绿（isolation） |
| 5 | 请求错误三口径（system/business[LLMBusyError 等]/upstream）+ 上游码 429/529 单列 | ✓ VERIFIED | `common/request_metrics.py` `classify_error` 单一收口（business=LLMBusyError/PermissionDenied/ValidationError；upstream=429/529 或上游标志；system=5xx/未捕获；none=2xx/3xx），`_UPSTREAM_STATUS_CODES={429,529}`；`interactions/ledger.py` `parse_upstream_status` 只取数值码 → ModelUsageRecord.upstream_status_code + failure_type；测试覆盖三口径 + 429 单列 |
| 6 | duration_ms + ttft_ms（流式首 chunk 计时）可采集 | ✓ VERIFIED | RequestMetric.duration_ms/ttft_ms + ModelUsageRecord.ttft_ms 字段就位；`agents/chat_runner.py`（L815-947）与 `agents/langchain_runner.py`（L500+）用 perf_counter 在首个真实 chunk 记 ttft_ms、turn 收尾记 duration_ms；chat SSE / compat 流式入口在生成器内记首 chunk ttft + 总 duration |

**Score:** 6/6 success criteria 在代码层面满足（且每个测试套件单独跑全绿）。

### Required Artifacts

| Artifact | Expected | Status | Details |
|----------|----------|--------|---------|
| `server/system/models.py` | RequestMetric 模型 | ✓ VERIFIED | `class RequestMetric` 全字段 + (ts,source)/(ts,error_class)/(-ts) 复合索引 |
| `server/common/request_metrics.py` | classify_error + record helper | ✓ VERIFIED | 三口径单一收口 + record/arecord best-effort + 受控 labels 白名单 |
| `server/system/metric_sink.py` | 队列 + 批量落库 worker | ✓ VERIFIED | 镜像 log_sink（deque maxlen=5000 + 四计数 + flush_now/_reset_for_tests） |
| `server/agents/call_source.py` | CallSource 22 值 + contextvar | ✓ VERIFIED | 恰 22 枚举成员 + normalize + get/set/use_call_source |
| `server/interactions/models.py` | ModelUsageRecord/RetrievalTrace 扩展 | ✓ VERIFIED | +call_source/ttft_ms/upstream_status_code/user_id/source/conversation_id + run nullable + 索引 |
| `server/interactions/ledger.py` | arecord_llm_usage / parse_upstream_status / retrieval helper 扩展 | ✓ VERIFIED | run 可空 + user/source contextvars 兜底 + best-effort |
| `task/integrations/callback.py` | report_token_usage | ✓ VERIFIED | 镜像 report_completed/failed，best-effort 返回 bool 不抛 |
| `task/core/executor.py` | _write_usage_data 后主动 emit | ✓ VERIFIED | `_execute_claude` 单一 chokepoint 覆盖四类容器 + usage 富化 |
| `server/subagent/api/callbacks.py` | _handle_token_usage 桥接 | ✓ VERIFIED | 服务端权威派生 call_source/user + 桥接 arecord_llm_usage |
| `server/services/retrieval/rag_search.py` | 分层计时 + 指标 | ✓ VERIFIED | `_record_rag_metric` 四阶段 + zero-drift |
| `server/agents/tools/space_tools.py` | 对话链留痕 | ✓ VERIFIED | conversation_id 注入 + top-N 采样写 RetrievalTrace |

### Key Link Verification

| From | To | Via | Status |
|------|----|----|--------|
| middleware/各入口 | record_request_metric | 请求结束记一行 + source==rest 兜底 + 专用入口自记 | ✓ WIRED |
| chat_runner / langchain_runner | arecord_llm_usage | astream 首 chunk ttft + 收尾写 ModelUsageRecord | ✓ WIRED |
| task executor | callback.report_token_usage → server callback | 补全 task→回调断点 | ✓ WIRED |
| _handle_token_usage | arecord_llm_usage | 容器 token 桥接入统一 TPS（run=None, source=container_callback） | ✓ WIRED |
| rag_search | record_request_metric | source=rag + 分层耗时/条数/score | ✓ WIRED |
| space_tools | arecord_retrieval_trace | 对话链留痕透传 conversation_id/user | ✓ WIRED |

### Requirements Coverage

| Requirement | Source Plan | Status | Evidence |
|-------------|------------|--------|----------|
| RATE-01 | 72-01 | ✓ SATISFIED | RequestMetric 全入口埋点 + synthetic 隔离 |
| RATE-02 | 72-02 / 72-03 | ✓ SATISFIED | ModelUsageRecord 扩展 + 22 call_source + 容器侧链路闭合 |
| RAG-01 | 72-04 | ✓ SATISFIED | search_rag 分层耗时/条数/score |
| RAG-02 | 72-04 | ✓ SATISFIED | RetrievalTrace MCP + 对话链 |
| SLA-02 | 72-01 | ✓ SATISFIED | classify_error 三口径 |
| SLA-03 | 72-02 | ✓ SATISFIED | upstream_status_code/failure_type 429·529 单列 |
| SLA-04 | 72-01 / 72-02 | ✓ SATISFIED | duration_ms + ttft_ms 首 chunk |

### Behavioral Spot-Checks (test execution)

| Suite | Command | Result | Status |
|-------|---------|--------|--------|
| 全部 5 个 server 套件（规范命令） | `uv run pytest test_request_metric test_model_usage_call_source test_container_token_chain test_rag_metrics_trace test_credential_leak_protection -q` | 94 passed, **1 failed**（test_coding_token_usage_bridges_to_model_usage_record：assert 10 == 1） | ✗ FAIL（随机顺序下复现） |
| test_container_token_chain（隔离） | `uv run pytest tests/test_container_token_chain.py -q` | 9 passed | ✓ PASS |
| test_model_usage → test_container（固定序） | `uv run pytest ...model_usage... ...container... -p no:randomly -q` | 1 failed, 33 passed | ✗ FAIL（稳定复现泄漏） |
| task 侧 | `cd task && uv run pytest tests/test_usage_emit.py tests/test_callback.py -q` | 31 passed | ✓ PASS |
| test_credential_leak_protection（脱敏守护） | combined | 22 passed | ✓ PASS |

**结论**：每个套件单独跑全绿；规范的 5 套件合并命令在 `pytest-randomly` 随机顺序下失败一项——根因为本 Phase 测试文件的跨连接 DB 隔离缺陷（详见 gaps），**非生产采集代码缺陷**。

### Anti-Patterns Found

| File | Pattern | Severity | Impact |
|------|---------|----------|--------|
| （Phase 72 修改/新增源码文件）| TBD/FIXME/XXX/HACK/placeholder | — | 无（扫描 0 命中，无 stub/占位/调试遗留）|

### Gaps Summary

6 条 ROADMAP 成功标准在代码层面全部满足，11 个核心 artifact 全部 VERIFIED（含 C2「容器侧 TPS 链路闭合」这一难点——task 主动 emit → 回调 → 服务端桥接 ModelUsageRecord 已端到端证明），所有测试套件**单独运行均全绿**，凭证脱敏守护不破，无 stub/debt marker。

唯一阻碍：用户指定的 5 套件**合并**命令在 `pytest-randomly` 随机顺序下会失败 1 项（`test_coding_token_usage_bridges_to_model_usage_record`，`assert 10 == 1`）。根因是 Phase 72 自身新增测试的跨连接事务隔离缺陷——`test_model_usage_call_source.py` 的 async 写库测试未用 `transaction=True`，其经 `sync_to_async` 提交的 `ModelUsageRecord` 行不回滚而泄漏，污染了 `test_container_token_chain.py` 中的**全表**计数断言。这与用户预先豁免的 structlog/retrieval 跨模块污染是不同的一类问题，且确由本 Phase 引入（72-04 已对 RAG 测试用 `transaction=True` 修复同类问题，但 72-02 的测试未跟进）。该缺陷不削弱数据采集能力，属 WARNING 级测试可靠性问题，修复面很窄（二选一）：

1. `test_model_usage_call_source.py` 三个写 ModelUsageRecord 的 async 测试类改用 `@pytest.mark.django_db(transaction=True)`；或
2. `test_container_token_chain.py` 断言改为按 session/run 过滤计数（`ModelUsageRecord.objects.filter(...).acount()==1`）而非 `all()` 全表。

---

_Verified: 2026-06-24T15:38:08Z_
_Verifier: Claude (gsd-verifier)_
