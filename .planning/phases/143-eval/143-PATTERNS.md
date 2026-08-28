# Phase 143: 价值评估与中高入图 - Pattern Map

**Mapped:** 2026-08-28
**Files analyzed:** 19 个拟新增/修改文件
**Analogs found:** 19 / 19（其中 evaluator 使用组合 analog，无单文件完全匹配）

## File Classification

| New/Modified File | Role | Data Flow | Closest Analog | Match Quality |
|---|---|---|---|---|
| `server/initiatives/models/session_capture.py` | model / state machine | CRUD / event-driven | `server/initiatives/models/feature_list_draft.py` | role-match |
| `server/initiatives/migrations/0016_*.py` | migration | schema transform | `server/initiatives/migrations/0015_session_capture.py` | exact |
| `server/initiatives/services/capture_service.py` | service / sole writer | CAS CRUD | `server/delivery/services/research_service.py::retry_task` + 本文件 `_create_locked` | composite exact |
| `server/initiatives/services/session_capture_eval.py` | service / evaluator | request-response LLM | `server/services/process_runtime/initiative_profile.py::build_profile` + `server/initiatives/services/memory_distill.py::_acall_llm` | composite role-match |
| `server/initiatives/services/session_capture_enqueue.py` | service / queue producer / recovery | event-driven / batch | `server/repositories/charter_enqueue.py` + `server/runners/dispatcher.py::arecover_stranded_dispatch_sessions` | composite role-match |
| `server/mcp_tools/views.py::ReportSessionKnowledgeView` | controller | request-response | 当前 `ReportSessionKnowledgeView` + `enqueue_charter_draft` 的 fail-soft 调用边界 | exact extension |
| `server/durable/queues.py` | config | event-driven | `QUEUE_CHARTER` / `ALL_QUEUES` | exact |
| `server/durable/tasks.py` | task wrapper / periodic task | event-driven / batch | `feature_list_parse_module` + `recover_stranded_repo_summaries` | exact |
| `server/durable/tasks_impl.py` | task handler | event-driven / request-response | `run_runner_dispatch` + `run_feature_list_parse_module` | exact |
| `server/durable/handlers.py` | adapter | event-driven | `_charter_draft` + `register_business_handlers` | exact |
| `server/knowledge/sources/session_capture.py` | source normalizer | transform / CRUD | `server/knowledge/sources/project_memory.py` | role-match |
| `server/knowledge/sources/__init__.py` | registry | transform | `_NORMALIZERS["project_memory"]` | exact |
| `server/knowledge/models.py::generate_entity_id` docstring | model documentation | transform | 既有 natural-key 表 | exact |
| `server/agents/call_source.py` | config / context provider | request-response | `INITIATIVE_PROFILE` 枚举成员 | exact |
| `server/tests/test_model_usage_call_source.py` | test | transform | `_EXPECTED_CALL_SOURCES` 集合相等守卫 | exact |
| `server/tests/initiatives/test_session_capture_eval.py` | test | request-response LLM | `test_initiative_profile.py` + `test_model_usage_call_source.py` | role-match |
| `server/tests/initiatives/test_session_capture_eval_tasks.py` | test | event-driven / batch | `test_charter_draft_task.py` + `test_runner_dispatch.py` | role-match |
| `server/tests/knowledge/test_session_capture_source.py` | test | transform | `test_project_memory_source.py` | exact |
| `.planning/observability/LOGGING-SPEC.md` | documentation / config contract | event-driven | §4.1 与 §10.10 | exact |

## Pattern Assignments

### `server/initiatives/models/session_capture.py`

**Analog:** 当前 `SessionCapture` 保持 INV-6、UUID、索引和 `status max_length=20`；状态枚举形状参考 `FeatureListDraftStatus`。

**现有字段与索引锚点**（`session_capture.py:14-20,43-79`）：

```python
class SessionCaptureStatus(models.TextChoices):
    PENDING_EVAL = "pending_eval", "待评估"
    EVAL_FAILED = "eval_failed", "评估失败"
    INGEST_PENDING = "ingest_pending", "待入图"
    EVALUATED = "evaluated", "已评估"

status = models.CharField(max_length=20, choices=SessionCaptureStatus.choices, ...)
indexes = [
    models.Index(fields=["repository", "status"]),
    models.Index(fields=["status", "created_at"]),
]
```

**应复制的模式：**
- 增加闭集 `EVALUATING`、`EVALUATED_LOW`、`INGESTING`、`INGESTED`、`INGEST_FAILED`；保留 legacy `EVALUATED` 但 writer 不再写入。
- `value_tier` 使用 `TextChoices` 或同等 choices 闭集；非法 LLM 值不得落库。
- `eval_attempts` / `ingest_attempts` 使用非负整型默认 0；`last_error` blank default；`next_retry_at` nullable；精华字段 blank default。
- 为恢复扫描增加 `status + next_retry_at` 索引；所有新状态字面值保持不超过 20 字符。
- 不修改 question/answer、first-write-wins 唯一约束或原始 Capture 保留语义。

### `server/initiatives/migrations/0016_*.py`

**Analog:** `server/initiatives/migrations/0015_session_capture.py:9-15,56-69,95-118`。

```python
class Migration(migrations.Migration):
    dependencies = [("initiatives", "0015_session_capture")]
    operations = [
        migrations.AlterField(...),
        migrations.AddField(...),
        migrations.AddIndex(...),
    ]
```

迁移只加列、choices 和索引；既有 `pending_eval` 行原值保留。禁止数据删除、批量改成 low，或为 `unknown` provider/model 猜值。

### `server/initiatives/services/capture_service.py`

**Analogs:**
- 唯一 writer/事务：本文件 `_create_locked`（`capture_service.py:233-285`）。
- 条件状态转换：`server/delivery/services/research_service.py:128-172`。

```python
updated = RepoResearchTask.objects.filter(
    id=task.id,
    status__in=[RepoResearchTaskStatus.FAILED, RepoResearchTaskStatus.STALE],
).update(
    status=RepoResearchTaskStatus.PENDING,
    attempt=F("attempt") + 1,
    updated_at=timezone.now(),
)
if updated != 1:
    raise ValueError(...)
```

**应新增的 symbol 形状：**
- `get_capture(capture_id)`：worker 只读。
- `claim_evaluation(capture_id)`：仅 `pending_eval|eval_failed -> evaluating`，同一 CAS 内 `eval_attempts=F()+1`。
- `record_evaluation(capture_id, tier, essence)`：仅 `evaluating -> evaluated_low|ingest_pending`。
- `record_eval_failure(...)`：仅 `evaluating -> eval_failed`，错误先 `redact_secrets_in_text`，写 `next_retry_at`。
- `claim_ingestion(capture_id)`：仅 `ingest_pending|ingest_failed -> ingesting`，递增 ingest attempt。
- `record_ingested` / `record_ingest_failure`：仅从 `ingesting` 转终态/失败态。

所有 `SessionCapture.objects.create/update/save` 继续只存在于该服务；worker 和 normalizer 不直接写 Capture。终态 CAS 返回 0 时按 `not_claimable` no-op，不抛成任务失败。

### `server/initiatives/services/session_capture_eval.py`

**组合 analog 1（Friday 默认模型，无猜测）：** `initiative_profile.py:312-352`。

```python
resolved = await ProviderConfigService.aresolve()
model_name = (getattr(resolved, "extra", None) or {}).get("default_model", "")
if not model_name:
    return ...  # 明确不可用
model = build_chat_model(resolved, model_name, streaming=False)
with use_call_source(CallSource.INITIATIVE_PROFILE):
    response = await model.ainvoke(messages)
```

**组合 analog 2（用量成功/失败均记录）：** `memory_distill.py:174-211,235-263`。

```python
try:
    with use_call_source(call_source):
        ai_msg = await chat_model.ainvoke(...)
except Exception as exc:
    await self._record_usage(
        resolved, model, upstream_status_code=parse_upstream_status(exc), ...
    )
    return None
usage = self._extract_usage(ai_msg)
await self._record_usage(
    resolved, model,
    prompt_tokens=usage.get("input_tokens", 0),
    completion_tokens=usage.get("output_tokens", 0),
    ttft_ms=ttft_ms,
    duration_ms=...,
)
```

**组合 analog 3（content block 归一）：** `agents/llm_factory.py:54-69` 的 `content_to_text`，不要再复制本地 `_content_to_text`。

**Phase 143 差异：**
- 返回强类型结果（如 frozen dataclass）`value_tier + distilled_essence`。
- 仅接受严格 JSON object；tier 必须逐字为 `high|medium|low`。非法/缺字段是可重试失败，绝不能像 `feature_classify.py:118-123` 那样把非法值降级成 low。
- 空 question/answer 在模型调用前失败；不调用质量门、`knowledge.llm_grader` 或 repo confidence。
- 不使用 `memory_distill.py:41,170-171` 的硬编码 model fallback；默认模型缺失即失败。
- started/completed/failed 均为 `sampling`, `component="knowledge"`，只记 `capture_id/tier/status/duration_ms`，不记输入和精华正文。

### `server/initiatives/services/session_capture_enqueue.py`

**Producer analog:** `server/repositories/charter_enqueue.py:18-83`。

```python
job_id = await DurableTaskService.defer(
    "durable_charter_draft",
    payload,
    queue=QUEUE_CHARTER,
    idempotency_key=f"charter:{mode_norm}:{repository_id}",
    lock=lock,
    initiated_by_user_id=initiated_by_user_id,
)
```

Capture helper 必须：
- eval payload 只含 `capture_id`、`attempt`；ingest 同理。用户字段由 `DurableTaskService.defer(... initiated_by_user_id=...)` 注入。
- 使用稳定 key/lock：`capture-eval:{id}`、`capture-ingest:{id}`。
- enqueue 异常脱敏记录并返回 `None`，不得撤销 `accepted=true`。
- 重复 MCP 命中旧 Capture 时先按状态判断；终态不重派。

**Recovery analog:** `runners/dispatcher.py::arecover_stranded_dispatch_sessions` 的“扫描候选、逐条隔离、恒定计数”与 `DurableTaskService.has_active_by_key`（`durable/service.py:154-169`）。

恢复扫描只取 due 的 `pending_eval|eval_failed|ingest_pending|ingest_failed`；每条先查对应 deterministic key 是否 active，再重派；单条失败不终止 sweep。恢复是保险丝，不是第二 writer。

### `server/mcp_tools/views.py::ReportSessionKnowledgeView`

**当前稳定契约:** `views.py:3743-3793`。

```python
result = await CaptureService().persist(...)
capture = result.capture
output_data = {
    "accepted": True,
    "capture_id": str(capture.id),
    ...
}
await self._record(...)
return Response(output_data, status=status.HTTP_200_OK)
```

在 `persist()` 成功提交后调用 enqueue helper。保持响应键、HTTP 200、ledger `_record` 与 first-write-wins 不变；enqueue 失败仍返回 accepted。当前 `_create_locked` 自带 `transaction.atomic()` 并已返回，优先直接 `await enqueue...`，不要在 async view 的 sync `on_commit` callback 中嵌套 `async_to_sync`。

### Durable 四件套

**队列:** `durable/queues.py:10-52,54-68`。新增 `QUEUE_KNOWLEDGE = "knowledge"`，同时加入 `ALL_QUEUES` 与 `__all__`。

**Procrastinate wrapper:** `durable/tasks.py:195-217`。

```python
@app.task(name="feature_list_parse_module", queue=QUEUE_FEATURE_PARSE)
async def feature_list_parse_module(
    *, project_id: str, draft_id: str, module_index: int,
    attempt: int = 0, initiated_by_user_id: str | None = None,
) -> dict[str, Any]:
    from durable.tasks_impl import run_feature_list_parse_module
    return await run_feature_list_parse_module(...)
```

分别注册 `durable_session_capture_eval` 与 `durable_session_capture_ingest`，keyword-only 参数与共用任务体完全一致。

**in-process adapter:** `durable/handlers.py:80-89,110-130`。

```python
async def _charter_draft(payload: dict[str, Any]) -> Any:
    from durable.tasks_impl import run_charter_draft
    return await run_charter_draft(**payload)

register_handler("durable_charter_draft", _charter_draft)
```

两个 Capture task 都必须添加 adapter 和注册；否则 SQLite/pytest 路径会 no-op。

**worker:** `durable/tasks_impl.py:475-486,489-604` 与 `317-404`。

```python
with bind_task_context(
    user_id=initiated_by_user_id or "system",
    source="durable",
    component="knowledge",
):
    # 先 CAS claim；claim 失败立即 skipped
```

worker 顺序固定：bind 用户 → CAS claim → eval 或 `await ingest(IngestionRequest(...))` → CaptureService 回写 → 失败态 + 有界 backoff re-defer。ingest worker 不得调用 evaluator；eval 得到 medium/high 后只落 `ingest_pending` 并 defer 第二任务。退避可复制 `_dispatch_backoff_seconds` 的 `5 * 2**attempt`、300 秒封顶，以及 `_FEATURE_PARSE_MAX_ATTEMPTS = 6` 的有界尝试。

**periodic recovery:** `durable/tasks.py:375-403`。

```python
@app.periodic(cron="*/5 * * * *")
@app.task(
    name="recover_stranded_repo_summaries",
    queue=QUEUE_MAINTENANCE,
    queueing_lock="recover_stranded_repo_summaries",
    pass_context=True,
)
async def recover_stranded_repo_summaries(context, timestamp):
    ...
```

逐行恢复日志用 debug；每 tick 仅一条汇总 sampling 事件，避免 INFO 刷屏。

### `server/knowledge/sources/session_capture.py`

**Analog:** `knowledge/sources/project_memory.py:47-116`。

```python
memory = (
    await ProjectMemory.objects.select_related("project", "project__space")
    .filter(id=request.source_id)
    .afirst()
)
body = redact_secrets_in_text(memory.content or "")
event = IngestionEvent(
    kind=EntityKind.DOCUMENT,
    source_kind="project_memory",
    source_id=str(memory.id),
    content=body,
    payload={"project_id": str(project.id), "memory_id": str(memory.id)},
    space_id=str(project.space_id) if project.space_id else None,
    repository_id=None,
    event_time=memory.updated_at,
    edges=(EdgeSpec(relation=EdgeRelation.REFERENCES, target_entity_id=project_node_id),),
)
```

Phase 143 normalizer 的精确差异：
- 查询 `SessionCapture` 并可 `select_related("project", "project__space", "repository")`。
- 仅 medium/high 且有非空 `distilled_essence` 时产一个事件；未知/low/未就绪返回空。
- `content` 只取再次脱敏后的 `distilled_essence`。
- payload 只含 `capture_id/value_tier/repository_id/project_id` 等标量；禁止 question、answer、transcript、ledger payload、distilled_essence 副本。
- `kind=DOCUMENT`、`source_kind="session_capture"`、稳定 `source_id=str(capture.id)`、`repository_id` 取 Capture FK。
- 无 project 时 `space_id=None, edges=()` 仍产事件；有 project 时才 `ensure_project_node` 并建 `REFERENCES`。
- lifecycle sampling 事件不记录正文；缺源 warning 也带 `component/category`。

### Knowledge registry、摄取和 natural key

`knowledge/sources/__init__.py:18-56` 只增加：

```python
"session_capture": "knowledge.sources.session_capture",
```

worker 调用 `knowledge.ingestion.ingest`（`ingestion.py:158-179`），后者负责 normalizer → `ingest_events`。必须复用 `ingest_events` 的 hash 预短路（`219-249`）、六步版本翻转和 Qdrant 写入；不得调用 `aschedule_ingestion`（`118-156`，内部是 `background_runner`），也不得直接写 `KnowledgeEntity` 或 Qdrant。

`knowledge/models.py:96-138` 只在 docstring natural-key 表追加 `session_capture`；生成公式保持：

```python
return uuid.uuid5(KNOWLEDGE_NAMESPACE, f"{kind}:{source_kind}:{source_id}")
```

### `server/agents/call_source.py` 与用量守卫

`call_source.py:40-45,136-141` 的枚举追加：

```python
SESSION_CAPTURE_EVAL = "session_capture_eval"
```

`tests/test_model_usage_call_source.py:39-87,95-114` 的期望集必须同时补齐既有漂移 `initiative_profile` 和新值 `session_capture_eval`，长度从错误的 45 更新到 47。不要只改长度；集合相等是权威守卫。

`.planning/observability/LOGGING-SPEC.md:62-115` 同步“当前 47 值”和表格行；§10.10（`382-391`）扩展 eval/ingest/normalize 的 sampling started/completed/failed 事件。事件字段不含问答或精华。

## Exact Test Assignments

### 新增 `server/tests/initiatives/test_session_capture_eval.py`

参考 `test_initiative_profile.py:125-210` 的 `AsyncMock model.ainvoke` + provider/factory patch，以及 `test_model_usage_call_source.py:192-280` 的 usage 落行断言。至少覆盖：

- `test_eval_writes_high_medium_low_and_essence`（三档参数化）。
- `test_invalid_json_or_tier_is_failure_not_low`。
- `test_empty_input_skips_llm_and_fails`。
- `test_missing_default_model_fails_without_guessing`。
- `test_eval_failure_keeps_capture_and_redacts_error`。
- `test_eval_records_usage_with_session_capture_eval`（成功 token/TTFT 与失败 upstream status）。
- `test_eval_module_does_not_import_quality_gates`（禁止符号静态守卫）。
- `test_eval_does_not_write_project_memory`。

### 新增 `server/tests/initiatives/test_session_capture_eval_tasks.py`

参考 `test_charter_draft_task.py:20-46,106-136` 与 `test_runner_dispatch.py:324-366`：

- `QUEUE_KNOWLEDGE in ALL_QUEUES`。
- 两个 in-process adapter 均以 `**payload` 调共用任务体。
- payload 无 `question/answer/distilled_essence/transcript`。
- eval 重放在非 claimable 状态不二次调用 LLM。
- ingest 重放不调用 evaluator；已 ingested no-op。
- medium/high defer ingest；low 不 defer、不调用 ingest/embedding。
- eval/ingest 失败分别留在各自失败域，ingest 失败不退回 pending_eval。
- backoff attempt/run_at/稳定 key/lock。
- recovery 对 due 且无 active job 的行重派；active、fresh、终态跳过；单条失败隔离。
- worker re-bind 真实 user；缺失值绑定 `system`（参考 `common/log_context.py:123-153`）。

### 新增 `server/tests/knowledge/test_session_capture_source.py`

逐字镜像 `test_project_memory_source.py:38-76`，增加：

- `test_document_session_capture_event`。
- `test_content_is_essence_not_qa`：sentinel question/answer 不在 `content`、`payload`。
- `test_payload_contains_only_scalar_provenance`。
- `test_low_returns_empty`。
- `test_missing_returns_empty`。
- `test_unanchored_medium_still_emits_event_without_edges`。
- `test_project_capture_adds_references_edge_and_space`。
- `test_repository_id_propagates`。
- `test_secret_redacted_from_essence`。

### 扩展既有测试

- `test_capture_inv6_guard.py:22-104`：继续只允许 `capture_service.py` 写 Capture；新增 eval/enqueue/worker/normalizer 模块禁止 `SessionCapture.objects.*` 写、`MemoryService`、`record_hook_writeback`、`aschedule_ingestion`、`background_runner`。
- `test_capture_service.py:57-136`：增加每条合法/非法状态转换、CAS 竞争只有一个 claim 成功、终态不可回退、错误脱敏、attempt/next_retry 更新。
- `test_report_session_knowledge.py:76-103,204-249`：accepted 后 durable eval 入队；重复终态 Capture 不二次入队；enqueue 抛异常仍 200/accepted 且 Capture 存在；继续断言 ProjectMemory 零写入。
- `test_capture_observability.py:62-181`：把 Phase 141 的 `test_no_eval_sampling_events` 替换为 Phase 143 lifecycle 白名单；断言 category/component/user/duration，序列化日志无 question/answer/essence/token，logger 失败不改变状态结果。
- `test_ingestion.py:249-272,449-495`：无需复制 ingestion 内核测试；Capture task 测试只证明调用统一 `ingest`，hash 幂等由既有三连发、预短路、边自愈和 revector 测试承担。

## Shared Patterns

### 用户归因

**Source:** `common/log_context.py:123-153`。所有 durable worker 最外层使用 `bind_task_context(user_id=initiated_by_user_id or "system", source="durable", component="knowledge")`；不要假定 request contextvars 跨线程。

### 错误处理与脱敏

**Source:** `capture_service.py:321-333`、`charter_enqueue.py:69-83`、`tasks_impl.py:593-604`。状态字段与日志错误先 `redact_secrets_in_text(str(exc))`；观测自身包 `try/except: pass`。业务失败必须落可恢复状态，不能被“日志 best-effort”吞成成功。

### LLM 用量

**Source:** `memory_distill.py:174-211,235-263`。成功记录 token/TTFT/duration；失败记录 `parse_upstream_status(exc)`；`arecord_llm_usage` 自身 best-effort。新 evaluator 使用 `content_to_text`、`build_chat_model(... streaming=False)` 和 `use_call_source(CallSource.SESSION_CAPTURE_EVAL)`。

### delivery_knowledge 幂等

**Source:** `knowledge/ingestion.py:198-353` 与 `tests/knowledge/test_ingestion.py:249-272,449-495`。相同 content hash 在 embedding 前短路，仍修复缺边；unsynced 同 hash 走 revector；调用方不得复制该状态机。

## Anti-Patterns / Hard Guards

| Anti-pattern | Exact guard/test |
|---|---|
| 用 `evaluate_writeback_quality`、`knowledge.llm_grader`、repo confidence 代替价值评估 | `test_eval_module_does_not_import_quality_gates` 静态扫描 evaluator imports/symbols |
| 非法/失败输出默认成 low | `test_invalid_json_or_tier_is_failure_not_low` |
| eval 与 ingest 合成单任务，ingest 失败重跑 LLM | `test_ingest_failure_does_not_reenter_eval` + 调用计数 |
| Capture 路径调用 `aschedule_ingestion` / `background_runner` | INV-6 扩展静态守卫 |
| durable payload 携带问答/精华正文 | enqueue defer 捕获 payload 精确键集断言 |
| worker 直接 `SessionCapture.objects.update/create/save` | `test_capture_inv6_guard.py` 全仓扫描 |
| 终态重放回到 processing | CAS 状态表参数化测试 + replay LLM/ingest 调用计数 |
| normalizer 把 question/answer 放入 content/version payload | sentinel 精确断言 + payload 键白名单 |
| low 调 embedding/Qdrant/ingest | mocks `assert_not_awaited` |
| 新 collection、EntityKind 或手写 Qdrant upsert | 静态禁止 import `QdrantService`/`KnowledgeEntity` writer；event 断言 DOCUMENT/session_capture |
| 无项目 medium/high 被错误跳过 | unanchored normalizer 测试仍返回事件 |
| `MemoryService.append` / `record_hook_writeback` | 静态守卫 + mock 调用计数 + ProjectMemory 行数前后相等 |
| 只注册 `tasks.py` 不注册 `handlers.py` | in-process defer 端到端 adapter 测试 |
| recovery 只依赖 `retry_stalled` | pending 行 + 空 in-process job registry 仍能重派测试 |
| 只新增 CallSource，不同步 spec/测试 | enum 与完整 expected set 相等；文档值数量人工/静态校验 |
| 日志含 question/answer/essence 或明文异常 | `structlog.testing.capture_logs()` 序列化 sentinel/secret 断言 |
| 直接使用 `memory_distill` 的硬编码模型 fallback | missing-default-model 测试断言 factory/ainvoke 未调用 |

## No Analog Found

没有单文件同时满足“严格三档 JSON + 用量成功/失败 + 缺模型不猜 + 可重试失败”的 evaluator；`session_capture_eval.py` 必须组合 `initiative_profile` 的 provider/default-model 路径、`memory_distill` 的 usage 路径和 `llm_factory.content_to_text`。其余拟改文件均有直接或同角色 analog。

## Metadata

**Analog search scope:** `server/initiatives`, `server/durable`, `server/agents`, `server/interactions`, `server/knowledge`, `server/mcp_tools`, `server/tests`, `.planning/observability`

**Primary analogs read:** 24

**Pattern extraction date:** 2026-08-28

**Local-only decision:** 本任务只读取当前已 checkout 工作区并写规划产物，不涉及跨仓、历史交付或远端代码。
