---
phase: 72-data-collection
plan: "72-04"
subsystem: observability/retrieval
tags: [RAG-01, RAG-02, metrics, retrieval-trace, observability]
requires: ["72-01", "72-02", "71"]
provides:
  - "search_rag 出口召回指标（source=rag，分层耗时/条数/top score，按 call_source 区分）"
  - "RetrievalTrace 留痕覆盖 MCP + AI 对话两条链（run 可空 + user/conversation/source 透传）"
affects:
  - server/services/retrieval/rag_search.py
  - server/interactions/ledger.py
  - server/agents/tools/space_tools.py
tech-stack:
  added: []
  patterns: ["best-effort 旁路观测 try/except", "labels 受控键白名单", "contextvars 透传 user/source", "top-N 采样留痕"]
key-files:
  created:
    - server/tests/test_rag_metrics_trace.py
  modified:
    - server/services/retrieval/rag_search.py
    - server/interactions/ledger.py
    - server/agents/tools/space_tools.py
    - server/common/request_metrics.py
    - server/system/metric_sink.py
    - server/tests/agents/fixtures/search_repository_code_signature.json
    - server/tests/services/retrieval/test_hybrid_e2e_callsites.py
decisions:
  - "召回指标走 RequestMetric(source=rag) + 受控 labels（复用 72-01），不新建专用表"
  - "rag_status 新增进 labels 白名单（request_metrics + metric_sink 双过滤点对齐）"
  - "chat 链 conversation_id 走既有注入机制（tool 参数 auto-inject，LLM 不可见）"
  - "召回内容留痕按 top-N=10 采样，绝不进 metric labels（基数控制 + 防泄漏）"
metrics:
  duration_min: 25
  completed: 2026-06-24
---

# Phase 72 Plan 04: 召回可观测（RAG 指标 + 留痕扩覆盖）Summary

在 `search_rag` 单一 chokepoint 旁路落召回指标（条数 + embedding/sparse/qdrant/rerank 分层耗时 + top score，按 `call_source` 区分来源），并把 `RetrievalTrace` 留痕从仅 MCP 扩展到 MCP + AI 对话两条链；全程 best-effort、zero-drift，召回内容仅入留痕不入指标。

## Tasks

### Task 1 — RAG-01 召回指标（PASS）
- `server/services/retrieval/rag_search.py`：新增模块级 `_record_rag_metric`，用 `time.perf_counter()` 旁路累计四阶段耗时（embedding / sparse / qdrant gather / rerank），在 `search_rag` 出口（含 embedding 失败早退 + 外层 except 兜底）写一行 `record_request_metric(source="rag", route="search_rag", method="RAG", ...)`。labels 取受控键：`call_source=get_call_source() or ""`、`recall_count`、`top_score`、四个 `stage_*_ms`；error 路径加 `rag_status="error"`（status_code=500 / error_class=system）。整段 `try/except: pass`，**步骤顺序/去重/排序/返回结构逐字未改**（zero-drift）。
- `server/common/request_metrics.py` + `server/system/metric_sink.py`：`rag_status` 加入两处 `_ALLOWED_LABEL_KEYS` 白名单（72-01 未含该键）。

### Task 2 — RAG-02 留痕扩覆盖（PASS）
- `server/interactions/ledger.py`：`record_retrieval_trace` / `arecord_retrieval_trace` 增 `run=None`（改可选）、`user_id`/`conversation_id`/`source`；`user_id`/`source` 缺省从 Phase 71 `structlog.contextvars` 取（无则 `system`/空）；seq 分配 run 非空沿用 `run.retrieval_traces.count()`，run 为空按 `conversation_id` 维度计数。payload 仍必经 `redact_for_ledger`。**MCP 既有调用零改动**即自动获 user 绑定。
- `server/agents/tools/space_tools.py`：`search_repository_code` 增 auto-inject 的 `conversation_id` 参数（tool properties + 函数签名），召回结果末尾 best-effort 对 top-10 命中写 `arecord_retrieval_trace(run=None, kind=CHUNK, conversation_id=..., payload={query/file_path/chunk/score})`，覆盖 AI 对话链；整段 `try/except: pass` 绝不影响工具返回。

## Verification
- `uv run pytest tests/test_rag_metrics_trace.py tests/mcp_tools/test_retrieval_trace.py tests/test_credential_leak_protection.py -q` → **33 passed**。
- `uv run pytest tests/test_rag_metrics_trace.py tests/services/retrieval -q` → **157 passed, 1 skipped**（search_rag zero-drift 行为契约零回归）。
- `uv run pytest tests/test_sdk_mcp_adapter.py tests/test_chat_runner.py tests/test_search_diagnosis.py tests/agents/test_tool_descriptions_decision_tree.py tests/agents/test_tool_contracts.py tests/test_chat_tools.py tests/agents/test_tools_exclusion.py -q` → **68 passed**（conversation_id 注入对 LLM 可见 schema 无影响）。
- `uv run ruff check <changed files>` → **All checks passed**。
- `uv run python manage.py makemigrations --check --dry-run` → **No changes detected**（无模型变更，72-02 已加 RetrievalTrace 列）。

## Deviations from Plan

### 必要的契约守护同步（files_modified 之外，但 strictly required）
**1. [Rule 3 - 契约守护] 更新 search_repository_code 签名守护**
- 原因：Task 2 给 `search_repository_code` 增 `conversation_id` 参数（计划要求），触发两处字节级签名守护失败。
- 改动：
  - `server/tests/agents/fixtures/search_repository_code_signature.json` 增 `conversation_id` 条目。
  - `server/tests/services/retrieval/test_hybrid_e2e_callsites.py::test_callsite_signature_unchanged` 的 `expected_agent_params` 增 `conversation_id`。
- 这两个测试本就为「新增/移除 callsite 入参时提醒 reviewer 同步」而设，此处即其预期用途。

### Auto-fixed Issues
**2. [Rule 1 - 测试隔离] async 测试跨连接行泄漏**
- 发现于：Task 1/2 测试落库。
- 问题：async 测试经 `sync_to_async` 在独立连接 `bulk_create`/`create` 写 `RequestMetric`/`RetrievalTrace`，普通 `@pytest.mark.django_db` 事务回滚兜不住跨连接提交 → 行泄漏到后续测试文件（`test_request_metric::test_non_rest_source_skipped_by_middleware` 的 `count()==0` 被污染）。
- 修复：三个写库 async 测试类改用 `@pytest.mark.django_db(transaction=True)`（TransactionTestCase 语义在 teardown truncate）。
- 文件：`server/tests/test_rag_metrics_trace.py`。

**3. [Rule 1 - lint] 修复 space_tools.py 既有 F541**
- 既有 `_diagnose_empty_search` 内一处 f-string 无占位符（非本次新增代码），为满足 plan「ruff check 干净」在已修改文件内顺手去掉多余 `f` 前缀。

## Pre-existing Issues (NOT introduced, NOT fixed — out of scope)
- `tests/services/retrieval/test_hybrid_structured_logging.py` / `test_hybrid_concurrency.py` 共 8 个用例在「`test_credential_leak_protection.py` 等先跑 → retrieval 后跑」的跨模块顺序下失败（structlog 全局配置被前序测试重配导致的捕获断言失败）。已 `git stash` 本 plan 全部改动后在 clean HEAD 复现同样 8 个失败 → 确认为**既有跨模块测试污染**，与本 plan 无关；retrieval 套件单独跑全绿。

## Known Stubs
None。

## Threat Flags
None（无新增网络入口/认证路径/schema 变更；留痕 payload 经 `redact_for_ledger`，指标 labels 仅受控枚举/数值）。

## Self-Check: PASSED
- `server/tests/test_rag_metrics_trace.py` 存在（7 用例全绿）。
- `server/services/retrieval/rag_search.py` 含 `_record_rag_metric`（4 处引用）。
- `server/interactions/ledger.py` 含 `conversation_id` 透传。
- ruff 干净；makemigrations 无变更。
