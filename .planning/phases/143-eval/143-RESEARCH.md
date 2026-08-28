# Phase 143: 价值评估与中高入图 - Research

**Researched:** 2026-08-28
**Domain:** Capture persist-first durable 状态机 / Friday LLM 三档评估 / delivery_knowledge DOCUMENT 摄取
**Confidence:** HIGH（接缝均对照当前 `server/` 源码、Phase 141/142 验收与 CONTEXT 锁定决策；`initiative_profile` 与用量测试计数漂移为已核实债）

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions
- 评估结果使用严格闭集 `high`、`medium`、`low`；评估器同时产出一段可独立召回的 `distilled_essence`，只保留可复用结论、约束、根因、解决方案和验证证据。
- 价值等级必须由 Friday LLM 独立判断，不复用 `evaluate_writeback_quality`、`knowledge.llm_grader` 的 related/duplicate 词表或仓库路由 confidence；确定性质量门最多用于拒绝空输入，不能代替三档评估。
- 新 LLM 调用固定使用 `CallSource.SESSION_CAPTURE_EVAL = "session_capture_eval"`，在首次调用前同步更新 `server/agents/call_source.py`、LOGGING-SPEC 枚举/事件目录与用量断言。
- 评估失败保留原始 Capture，记录脱敏错误与可重试状态；不得删除行、把失败默认为 low，或猜测缺失模型/provider/token 元数据。
- Phase 142 的同步请求先提交 Capture，再通过 `transaction.on_commit` 把仅含 `capture_id` 的任务交给 `DurableTaskService.defer`；数据库行是工作真相，进程内 `background_runner` 不得成为唯一投递。
- 状态机覆盖 `pending_eval → evaluating → evaluated_low | ingest_pending → ingesting → ingested`，评估/入图失败进入可重试失败态并保留 attempt、last_error、next retry 所需信息；状态转移只经 `CaptureService` 扩展方法，继续满足 INV-6。
- durable 任务以 Capture id 构造稳定 idempotency key/lock，worker 每步先读当前状态并以条件更新抢占；at-least-once 重放不得重复 LLM 评估、重复版本翻转或把终态退回处理中。
- worker 入口必须从 payload 读取并用 `bind_task_context` 重新绑定 `initiated_by_user_id`；缺失时显式使用 `system`。入队失败、进程重启和临时上游失败都能由 pending/failed 扫描或重投恢复。
- 只有 `medium`/`high` 进入摄取；`low` 仅保存等级和提炼结果供回放/评测，不调用 embedding、`aschedule_ingestion` 或 Qdrant。
- 入图固定复用 `EntityKind.DOCUMENT`、现有 `delivery_knowledge` collection 与新 `source_kind="session_capture"`；不得新增 EntityKind、collection 或平行向量库。
- 新 normalizer 只从 Capture 的 `distilled_essence` 构造 `IngestionEvent.content`；原始 `question`/`answer`、完整 transcript 与 Ledger payload 永远不进入 RAG 正文或版本 payload。
- 仓库信息写入 `repository_id`；存在授权项目关联时按既有项目图谱模式附加 `REFERENCES` 边与 `space_id`，无项目不阻断仓级入图。摄取仍经既有 ingestion 六步序，禁止直接写 KnowledgeEntity/Qdrant。
- 评估与入图路径禁止调用 `MemoryService.append`、`record_hook_writeback` 或任何 active `ProjectMemory` 写入口；项目长期记忆继续遵守 draft/人工门控。
- 评估、normalizer、入图任务发 `sampling` 类 started/completed/failed 结构化事件，统一带 `component=knowledge`、`capture_id`、tier/状态、`duration_ms` 与触发用户，不记录问答或精华正文。
- LLM/embedding 既有 chokepoint 继续上报请求数、token、TTFT 与上游错误码；异常文本在日志或状态字段前经 `redact_secrets_in_text`，观测失败 best-effort 不改变状态机业务结果。
- 自动化验收必须覆盖低价值无向量、中高只索引精华、评估失败保留 Capture、重放幂等、重启后 pending 可恢复、触发用户重绑定以及 `ProjectMemory` 零写入。

### Claude's Discretion
- 具体状态枚举命名、retry backoff 参数、最大尝试次数、评估 JSON schema 与 evaluator 内部模块拆分由实现者决定，但必须保留 persist-first、可恢复和三档闭集语义。
- 可新增独立逻辑队列或复用合适的 knowledge/maintenance 队列；必须通过 `durable.queues` 常量登记并保持双后端 task/handler 参数对齐。

### Deferred Ideas (OUT OF SCOPE)
- 对外仓库/项目检索、Capture id 原文回放、`session_capture` 读白名单与 RetrievalTrace 收口延后到 Phase 144。
- Cursor / Claude Code hooks、技能和安装器接线延后到 Phase 145。
- 人工价值纠偏 UI、Capture → `ProjectMemory` 草稿提升与评估 golden set 产品化留后续版本。
- 不修复其他既有 knowledge ingestion 调用点仍使用 `background_runner` 的历史窗口；本阶段只保证 Session Capture 新路径 durable。
</user_constraints>

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| EVAL-01 | 每条已落库 Capture 异步评估 `high`/`medium`/`low` 并提炼可检索精华；失败保留原文、不得删除 | persist-first 入队 + Capture 状态机 + Friday LLM JSON；失败写 `eval_failed` 不清行。`[VERIFIED: session_capture.py; CONTEXT.md]` |
| EVAL-02 | 价值等级不得复用写回质量门或仓库路由 confidence；LLM 用 `call_source=session_capture_eval` 并上报用量 | 新 `CallSource.SESSION_CAPTURE_EVAL`；`ProviderConfigService.aresolve` + `build_chat_model` + `use_call_source` + `arecord_llm_usage`（照 `memory_distill.py`）。禁止 import `evaluate_writeback_quality` / `llm_grader` / repo router confidence。`[VERIFIED: call_source.py; memory_distill.py; cursor_writeback.py]` |
| EVAL-03 | `medium`/`high` 经既有摄取入口进入 `delivery_knowledge`（`DOCUMENT` + `source_kind=session_capture`）；`low` 不向量化仍可回放 | worker **同步** `await ingest(IngestionRequest)`（六步序），**禁止**本路径 `aschedule_ingestion`（那是 `background_runner`）。low 停在 `evaluated_low`。`[VERIFIED: knowledge/ingestion.py; CONTEXT EVAL-04]` |
| EVAL-04 | 入图投递 persist-first 且可重试（durable/outbox + 状态机）；禁止把进程内 `background_runner` 当唯一投递 | `DurableTaskService.defer` + Capture 行真相 + `has_active_by_key` 恢复扫描；SQLite in-process 不是生产真相，靠行状态 + 周期重投。`[VERIFIED: durable/service.py; durable/tasks.py retry_stalled]` |
| EVAL-05 | 评估与入图不得调用 `MemoryService.append` / `record_hook_writeback` 写成 active 项目记忆 | 静态 grep + 行为计数断言；INV-6 扩展禁止这些符号出现在 eval/ingest worker。`[VERIFIED: test_capture_inv6_guard.py; 142 VERIFICATION]` |
| OBS-04 | 后台评估/入图任务携带并 re-bind `initiated_by_user_id`；无触发用户记 `system` | payload 标量 + `bind_task_context(user_id=... or "system", source="durable")` 照 `run_runner_dispatch`。`[VERIFIED: tasks_impl.py; common/log_context.py]` |
</phase_requirements>

## Summary

Phase 143 在 Capture **已经接受**（Phase 142 `accepted=true`）之后，用 Friday 已配置供应商做一次独立三档评估，并把 **medium/high 的精华**经既有 knowledge 六步序写入统一 `delivery_knowledge`。MCP 契约、召回白名单、原文回放、IDE hooks 全部不动。`ProjectMemory` 继续 draft 门控。

当前缺口：`ReportSessionKnowledgeView` 只 `persist` 后返回，**没有** durable 入队；`SessionCaptureStatus` 只有 `pending_eval` / `eval_failed` / `ingest_pending` / `evaluated`，缺少 CONTEXT 要求的处理中与终态；`CallSource` **没有** `session_capture_eval`；`_NORMALIZERS` **没有** `session_capture`。

**EVAL-03 与 EVAL-04 的唯一正确合流：** 「既有摄取入口」是 `knowledge.ingestion.ingest` / `ingest_events`（normalizer → 版本翻转 → Qdrant），不是 `aschedule_ingestion`。后者内部是 `transaction.on_commit` + `run_in_background`，CONTEXT 与 EVAL-04 明确禁止把它当作 Session Capture 的唯一投递。Worker 内直接 `await ingest(...)`，由 Capture 状态机记录成败。`[VERIFIED: knowledge/ingestion.py:118-156]`

**Primary recommendation:** 扩展 `SessionCapture` + INV-6 CAS 方法；MCP persist 成功后 `on_commit`/`await defer` 仅含 `capture_id` 的 `durable_session_capture_eval`；LLM 用 `session_capture_eval` + JSON `{value_tier, distilled_essence}`；low 停 `evaluated_low`；medium/high 再 defer ingest 任务并 `await ingest()`；周期扫描 pending/failed 且无在途 job 的行以恢复。

## Architectural Responsibility Map

| Capability | Primary Tier | Secondary Tier | Rationale |
|------------|-------------|----------------|-----------|
| Capture 行与状态机 | API / Backend (`CaptureService`) | Database | INV-6：仅 writer 可 `update`/`create` |
| 评估入队 | API / Backend（MCP view + enqueue helper） | Durable queue | persist 已提交后投递；失败不改 `accepted` |
| LLM 价值评估 | API / Backend（evaluator 服务） | Provider HTTP | Friday 配置模型；用量落 `ModelUsageRecord` |
| medium/high 摄取 | API / Backend（durable worker） | Database + Qdrant | 复用 `ingest()` 六步；禁止直写实体/向量 |
| low 回放保留 | Database / Storage | — | 行仍在；本阶段无读 API（Phase 144） |
| 用户归因 | API / Backend contextvars | — | payload `initiated_by_user_id` + `bind_task_context` |
| 观测 | API / Backend structlog | Metrics tables | sampling 生命周期；正文永不入日志 |
| ProjectMemory | —（禁止写） | — | EVAL-05 |

## Standard Stack

### Core

| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| Django | 6.0.1 `[VERIFIED: uv run python]` | 模型/migration/`filter().update` CAS、`on_commit` | 本仓后端事实栈 |
| Python | 3.14.2 `[VERIFIED: python3 --version]` | runtime | `server/.python-version` |
| DurableTaskService + Procrastinate | 已在仓 `[VERIFIED: durable/service.py]` | persist-first 队列（Postgres） | 禁止自研 outbox |
| LangChain `build_chat_model` | 已在仓 `[VERIFIED: agents/llm_factory.py]` | Friday 供应商 chat 模型 | 禁止直连 SDK、禁止新依赖 |
| `ProviderConfigService.aresolve` | 已在仓 | 默认模型/凭证 | 缺失则评估失败可重试，不猜测 |
| knowledge `ingest` | 已在仓 | DOCUMENT 六步幂等摄取 | 禁止旁路 Qdrant/ORM |

### Supporting

| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| structlog | 已在仓 | sampling 生命周期 | 所有 eval/ingest/normalize |
| `arecord_llm_usage` | 已在仓 | token/TTFT/上游码 | 每次 LLM 成功与失败 |
| `bind_task_context` | 已在仓 | worker 用户重绑定 | 每个 durable 任务体入口 |
| `redact_secrets_in_text` | 已在仓 | 异常与 last_error | 写入状态字段与日志前 |
| `ProjectKnowledgeGraphService.ensure_project_node` | 已在仓 | 可选 REFERENCES 边 | 仅当 Capture 已绑授权项目 |
| pytest / pytest-django / pytest-asyncio | 已在仓 | 验收 | Wave 0 + phase gate |

### Alternatives Considered

| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| `await ingest()` in worker | `aschedule_ingestion` | 违反 EVAL-04；CONTEXT 仅允许历史调用点继续用 background_runner |
| 新 EntityKind / collection | `DOCUMENT` + `source_kind` | uuid5 漂移；ROADMAP 锁定禁止 |
| `evaluate_writeback_quality` 当档位 | 独立 LLM | 那是长度/Jaccard 噪音门，不是知识价值 |
| 单任务 eval+ingest | 双任务 | 入图失败会重跑 LLM；不要 |
| `QUEUE_MAINTENANCE` 兼评估 | 新 `QUEUE_KNOWLEDGE` | maintenance 已跑 stalled rescue；LLM 评估应隔离 |

**Installation:** 无新 Python/npm 包。里程碑锁定「不引入新运行时依赖」。

**Version verification:** Django 6.0.1、Python 3.14.2 本机核实。无新 registry 包。

## Package Legitimacy Audit

本阶段 **不安装** 外部包。

| Package | Registry | Age | Downloads | Source Repo | slopcheck | Disposition |
|---------|----------|-----|-----------|-------------|-----------|-------------|
| — | — | — | — | — | n/a | 无新增 |

**Packages removed due to slopcheck [SLOP] verdict:** none
**Packages flagged as suspicious [SUS]:** none

*slopcheck 本机不可用；因零新包，planner 无需 `checkpoint:human-verify` 安装门。*

## Architecture Patterns

### System Architecture Diagram

```text
MCP report_session_knowledge
        │ persist (CaptureService) ──► SessionCapture row (status=pending_eval)
        │ accepted=true 已成立，后续故障不得撤销
        ▼
transaction.on_commit / await enqueue
        │ payload = {capture_id, initiated_by_user_id}  无问答正文
        │ task=durable_session_capture_eval
        │ idempotency_key=capture-eval:{id}  lock=capture-eval:{id}
        ▼
DurableTaskService.defer ──► Postgres procrastinate jobs
        │                    SQLite：in-process（非生产真相）
        ▼
run_worker (ALL_QUEUES 含 QUEUE_KNOWLEDGE)
        │ bind_task_context(user_id or "system", source="durable")
        ▼
CAS pending_eval|eval_failed → evaluating（递增 attempt）
        │ 已是 evaluating → resume，不递增，仍调 LLM
        │ 抢占失败 / 终态 evaluated_low|ingested|legacy evaluated → skipped，不调 LLM
        ▼
Evaluator: aresolve + build_chat_model + use_call_source(SESSION_CAPTURE_EVAL)
        │ JSON {value_tier, distilled_essence}
        │ 空输入：确定性拒绝，eval_failed，不调 LLM，不标 low
        │ 缺模型/非法 JSON/上游错误：eval_failed + backoff re-defer
        │   backoff：lock + run_at，**不得**复用稳定 idempotency_key
        ├─ low  → CAS evaluating → evaluated_low  STOP（无 embed）
        └─ med/high → CAS → ingest_pending → defer durable_session_capture_ingest
                              idempotency_key=capture-ingest:{id}（首次/recovery）
                ▼
         CAS ingest_pending|ingest_failed → ingesting（递增）
         已是 ingesting → resume，不递增
                ▼
         await ingest(IngestionRequest(source_kind="session_capture", source_id=capture.id))
                │ normalizer: content=distilled_essence only
                │ DOCUMENT + delivery_knowledge + 可选 REFERENCES→project
                ├─ 成功（events>0 或 hash skip）→ ingested
                └─ 失败 → ingest_failed + backoff lock+run_at（不回退 evaluating、不重跑 LLM、不复用稳定 key）

周期 recover_stranded_session_captures（QUEUE_MAINTENANCE）
        │ status ∈ {pending_eval, eval_failed, ingest_pending, ingest_failed,
        │           evaluating, ingesting}
        │ AND due/stale AND NOT has_active_by_key
        │ 终态 evaluated_low/ingested/legacy evaluated 跳过
        └─ re-defer 对应任务（稳定 idempotency_key + lock；进程重启 / 入队失败 / in-flight 崩溃）
```

### Recommended Project Structure

```
server/initiatives/models/session_capture.py     # 扩展 TextChoices + 评估/入图字段
server/initiatives/migrations/0016_*.py          # 0015 之后
server/initiatives/services/capture_service.py   # CAS / record_eval / record_failure
server/initiatives/services/session_capture_eval.py      # LLM JSON 评估器
server/initiatives/services/session_capture_enqueue.py   # persist 后入队 + 恢复扫描
server/knowledge/sources/session_capture.py      # normalizer
server/knowledge/sources/__init__.py             # 登记 session_capture
server/knowledge/models.py                       # generate_entity_id 表注释追加一行
server/durable/queues.py / tasks.py / tasks_impl.py / handlers.py
server/agents/call_source.py + tests/test_model_usage_call_source.py
server/mcp_tools/views.py                        # persist 后 enqueue，失败吞掉
.planning/observability/LOGGING-SPEC.md          # §4.1 + §10
```

### Pattern 1: Persist-first then defer（Capture 行是真相）

**What:** 先提交 Capture，再入队仅含 id 的 durable job；job 丢失用行状态恢复。
**When to use:** 所有 Session Capture 评估/入图投递。
**Example:**

```python
# Source: server/delivery/api/views.py（async 端点直接 await defer）
# + server/knowledge/ingestion.py A1 on_commit 注册须走 sync 线程
from asgiref.sync import sync_to_async
from django.db import transaction
from durable.service import DurableTaskService
from durable.queues import QUEUE_KNOWLEDGE

async def enqueue_session_capture_eval(
    capture_id: str, *, initiated_by_user_id: str | None
) -> str | None:
    actor = initiated_by_user_id or "system"
    payload = {"capture_id": str(capture_id), "attempt": 0}

    async def _defer() -> str:
        return await DurableTaskService.defer(
            "durable_session_capture_eval",
            payload,
            queue=QUEUE_KNOWLEDGE,
            idempotency_key=f"capture-eval:{capture_id}",
            lock=f"capture-eval:{capture_id}",
            initiated_by_user_id=actor,
        )

    def _register() -> None:
        transaction.on_commit(lambda: _schedule_defer(_defer))

    try:
        await sync_to_async(_register)()
        return "scheduled"
    except Exception:
        return None
```

Planner 实现 `_schedule_defer` 时：autocommit 下 `on_commit` 立即跑，须把 async `defer` 投到已有 loop（`asyncio.get_running_loop().create_task` 不安全于 sync 回调）或 `async_to_sync(DurableTaskService.defer)`。**推荐：** MCP view 在 `persist()` 返回后 **直接 `await DurableTaskService.defer`**（`_create_locked` 的 `atomic` 已提交），再用 `on_commit` 仅当未来把 persist 包进外层事务。无论哪条，入队失败必须吞掉且 **不改 HTTP 200 / accepted**，依赖恢复扫描。`[VERIFIED: capture_service.py atomic; delivery/api/views.py:672]`

### Pattern 2: 双任务 + CAS 抢占（不在 ingest 重跑 LLM）

**What:** eval 与 ingest 分两个 task name；每步 `filter(id=, status__in=allowed).update(status=next)`，`rowcount==0` 则 skip。
**When to use:** at-least-once worker。
**Example:**

```python
# Source: 本仓 INV-6 约定 — 仅 CaptureService 内 SessionCapture.objects.filter().update
updated = await sync_to_async(
    lambda: SessionCapture.objects.filter(
        id=capture_id,
        status__in=[SessionCaptureStatus.PENDING_EVAL, SessionCaptureStatus.EVAL_FAILED],
    ).update(status=SessionCaptureStatus.EVALUATING, eval_attempts=F("eval_attempts") + 1)
)()
if updated != 1:
    return {"status": "skipped", "reason": "not_claimable"}
```

终态 `evaluated_low` / `ingested` 的 update 不得把 status 改回 processing。重放已 ingested：ingest worker 见终态 skip；`ingest()` 同 content_hash 走 `knowledge_ingest_skipped`，不新版本。`[VERIFIED: ingestion.py:219-248]`

### Pattern 3: Friday LLM JSON + 用量（照 memory_distill）

**What:** `aresolve` → `extra.default_model` → `build_chat_model(..., streaming=False)` → `use_call_source` → `ainvoke` → `content_to_text` → 解析闭集 JSON → 成功/失败都 `arecord_llm_usage`。
**When to use:** Session Capture 评估（唯一新 LLM 点）。
**Example:**

```python
# Source: server/initiatives/services/memory_distill.py
from agents.call_source import CallSource, use_call_source
from agents.llm_factory import build_chat_model, content_to_text
from interactions.ledger import arecord_llm_usage, parse_upstream_status
from services.provider_config import ProviderConfigService

resolved = await ProviderConfigService.aresolve()
model_name = (getattr(resolved, "extra", None) or {}).get("default_model", "")
if not model_name:
    raise EvalUnavailable("missing_default_model")  # → eval_failed，不猜模型
model = build_chat_model(resolved, model_name, streaming=False)
with use_call_source(CallSource.SESSION_CAPTURE_EVAL):
    response = await model.ainvoke(messages)
```

非法 `value_tier`、缺 `distilled_essence`（medium/high）、非 JSON → **失败可重试**，**禁止**当 low。空 question/answer（脱敏后 strip 空）→ 不调 LLM，`eval_failed` reason=`empty_input`。`[VERIFIED: memory_distill.py; feature_classify.py; CONTEXT]`

### Pattern 4: DOCUMENT normalizer（照 project_memory，正文换成精华）

**What:** `source_id=str(capture.id)`；`kind=DOCUMENT`；`source_kind="session_capture"`；`content=redact(distilled_essence)`；`payload` 只含 `capture_id`/`value_tier`/`repository_id` 等标量，**无** question/answer。
**When to use:** medium/high ingest。
**origin:** `EntityOrigin.MCP`（入口是 MCP 工具）。无项目则 `space_id=None`、`edges=()`，仍产出实体。有项目则 `ensure_project_node` + `REFERENCES` + `space_id`。`repository_id` 有则写入事件字段。`[VERIFIED: project_memory.py; knowledge/models.py EntityOrigin]`

### Anti-Patterns to Avoid

- **`aschedule_ingestion` 作为 Capture 投递：** 等于 `background_runner` 唯一投递，EVAL-04 失败。
- **失败默认 low：** 污染回放评测与漏召回；必须 `eval_failed`。
- **ingest 失败回退 pending_eval：** 会导致重复 LLM 与费用；ingest 只在 `ingest_*` 态循环。
- **durable payload 复制问答：** 队列/job 表泄漏；只带 id。
- **worker 内 `SessionCapture.objects.update`：** INV-6 静态守卫会红。
- **CallSource 只改枚举不改测试/LOGGING-SPEC：** `test_model_usage_call_source` 集合相等断言会失败。
- **把 `EVALUATED`（141 预留）当 low 终态：** CONTEXT 要 `evaluated_low`；`evaluated` 语义含糊，medium 不该停在「已评估」。

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| 可靠后台执行 | 自研 outbox / 只跑 daemon 线程 | `DurableTaskService` + Capture 行扫描 | 双后端、idempotency、stalled heartbeat 已有 |
| 向量写入 | 直接 Qdrant upsert | `ingest` / `ingest_events` | 四层幂等 + 版本翻转 |
| 实体 id | 自造 uuid4 | `generate_entity_id(DOCUMENT, "session_capture", capture_id)` | uuid5 稳定，重放不漂 |
| LLM 工厂 | 新 SDK 客户端 | `build_chat_model` | 凭证/thinking/usage patch |
| 用户上下文 | 假定中间件跨线程 | `bind_task_context` | contextvars 不跨线程 |
| 脱敏 | 自写 regex | `redact_secrets_in_text` | 全仓统一 |

**Key insight:** 本阶段复杂度在状态机与投递语义，不在新库。手写队列或向量层会破坏 INV-6 与 knowledge 幂等。

## Runtime State Inventory

本阶段给已存在的 `initiative_session_captures` 加列与状态值，属迁移。

| Category | Items Found | Action Required |
|----------|-------------|------------------|
| Stored data | 表 `initiative_session_captures`（migration `0015`）；生产/dev 可能已有 `status=pending_eval` 行（Phase 142 已上线工具） | **数据迁移：** 新列默认空/0；已有 pending 行保持 `pending_eval`，由 enqueue 恢复扫描补任务。禁止 DELETE。`evaluated` 若无行可保留枚举不写 |
| Live service config | 无独立 Capture 队列；worker 默认 `ALL_QUEUES` | **代码：** 新队列加入 `ALL_QUEUES` 即被 compose/helm `run_worker` 消费，无需改 YAML（未 pin `--queues`）`[VERIFIED: docker-compose.yaml run_worker; run_worker.py default ALL_QUEUES]` |
| OS-registered state | None — verified by no systemd/pm2 Capture jobs in repo | none |
| Secrets/env vars | 无 Capture 专用 env；LLM 用既有 ProviderCredential | none（禁止猜模型） |
| Build artifacts | None — verified no Capture 相关 egg/image 名 | none |

**Nothing found in category:** OS-registered / secrets / build artifacts — 已按上表明示。

## Common Pitfalls

### Pitfall 1: 把 `aschedule_ingestion` 当成 EVAL-03 合规

**What goes wrong:** 重启丢失 ingest；EVAL-04 验收失败。
**Why:** `aschedule_ingestion` 文档写明 `on_commit` + `run_in_background`。`[VERIFIED: ingestion.py:118-142]`
**How to avoid:** worker `await ingest(request)`；测试断言 Capture 路径源码不含 `aschedule_ingestion`。
**Warning signs:** INV-6 扩展守卫命中；ingest 测试要 patch `run_in_background`。

### Pitfall 2: 双后端 handler 漏登记

**What goes wrong:** pytest/SQLite 任务 no-op；Postgres 有 task 但 in-process 无 handler。
**Why:** `tasks.py` 仅 procrastinate 路径 import；`handlers.py` 必须无条件 `register_handler`。`[VERIFIED: durable/apps.py; handlers.py]`
**How to avoid:** `tasks.py` + `tasks_impl.py` + `handlers.register_business_handlers` 三处同名、keyword-only 对齐；测 `test_charter_draft_task` 同款 `QUEUE in ALL_QUEUES`。

### Pitfall 3: CallSource 计数债 + 新值

**What goes wrong:** 只加 `session_capture_eval` 时测试仍红。
**Why:** 枚举已有 46 值（含 `initiative_profile`），`_EXPECTED_CALL_SOURCES` 仍 45 且缺 `initiative_profile`。`[VERIFIED: uv run len(CallSource)==46; test_model_usage_call_source.py:114]`
**How to avoid:** 同 PR 把 `initiative_profile` 补进期望集，再加 `session_capture_eval`（目标 47），LOGGING-SPEC §4.1 改「当前 N 值」。
**Warning signs:** `assert {member.value for member in CallSource} == _EXPECTED_CALL_SOURCES` 失败。

### Pitfall 4: 幂等 persist 再次入队已 ingested 的 Capture

**What goes wrong:** first-write-wins 返回旧行后 view 仍 defer，可能打扰终态。
**Why:** 142 重复提交返回同一 `capture_id`。
**How to avoid:** enqueue 前读 status；终态 skip；`idempotency_key` 使 todo 去重；worker CAS skip。
**Warning signs:** 重复 MCP 调用触发第二次 LLM。

### Pitfall 5: 日志或 payload 泄漏精华/问答

**What goes wrong:** OBS-02 回归；141 字段白名单测试精神被破坏。
**How to avoid:** sampling 事件只记 `capture_id`/`tier`/`status`/`duration_ms`/`initiated_by_user_id`；`last_error` 先 redact。
**Warning signs:** 测试抓 structlog 事件出现 `question`/`distilled`。

### Pitfall 6: `status` max_length=20 与新枚举

**What goes wrong:** `evaluated_low`(14) / `ingest_pending`(14) 仍够；若命名超 20 会截断。
**How to avoid:** 保持 ≤20；migration 不必改 length unless 更长名。
**Warning signs:** DataError on PostgreSQL。

## Code Examples

### Durable 任务三件套（照 charter / runner_dispatch）

```python
# Source: server/durable/tasks.py + handlers.py + tasks_impl.py
@app.task(name="durable_session_capture_eval", queue=QUEUE_KNOWLEDGE)
async def durable_session_capture_eval(
    *,
    capture_id: str,
    attempt: int = 0,
    initiated_by_user_id: str | None = None,
) -> dict:
    from durable.tasks_impl import run_session_capture_eval
    return await run_session_capture_eval(
        capture_id=capture_id,
        attempt=attempt,
        initiated_by_user_id=initiated_by_user_id,
    )
```

in-process adapter：`return await run_session_capture_eval(**payload)`。Backoff 抄 `_dispatch_backoff_seconds`（5s×2^n，帽 300s）；最大尝试抄 `_FEATURE_PARSE_MAX_ATTEMPTS = 6`。**首次入队与 recovery** 使用稳定 `idempotency_key=capture-eval:{id}`（ingest 同理）。**worker 退避** 只传 `lock` + `run_at`，省略稳定 idempotency_key 或改用 `capture-eval:{id}:retry:{attempt}`，否则 Procrastinate 会把已完成 job 的同一 key 当成去重而不调度新 job。达上限：保持 `eval_failed`/`ingest_failed`，`next_retry_at=None`，**仍不删除、不标 low**。`[VERIFIED: tasks_impl.py:475-487, 233]`

### generate_entity_id 登记

```text
# Source: server/knowledge/models.py generate_entity_id docstring 表
| session_capture | SessionCapture UUID str | IDE 会话评估精华（Phase 143）|
```

拼接格式不得改：`f"{kind}:{source_kind}:{source_id}"`。

### 恢复扫描

```python
# Source: server/durable/tasks.py recover_stranded_repo_summaries 周期模式
# @app.periodic(cron="*/5 * * * *") + queueing_lock 单例
# 业务：可恢复状态 = pending/failed + stale evaluating/ingesting
# AND NOT DurableTaskService.has_active_by_key(稳定 key)
# 终态 evaluated_low/ingested/legacy evaluated 跳过
# recovery re-defer 使用与首次入队相同的稳定 idempotency_key
```

SQLite 下 `retry_stalled` 恒 0，**必须**靠 Capture 行扫描，不能只靠 Procrastinate heartbeat。`[VERIFIED: DurableTaskService.retry_stalled in-process returns 0]`

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| fire-and-forget `background_runner` 摄取 | durable job + 业务行状态 | Phase 60+ / 本阶段 Capture 路径 | 重启可恢复 |
| 项目记忆质量门当「价值」 | 独立 LLM 三档 + 精华 | 本阶段 | 不与 MEM-04 混用 |
| 新 collection / EntityKind | `DOCUMENT` + `source_kind` | Phase 85+ 锁定 | 无 uuid5 漂移 |

**Deprecated/outdated:**

- 将 `SessionCaptureStatus.EVALUATED` 当作 143 业务终态：141 仅预留；143 应写 `evaluated_low` / `ingested`。
- Capture 路径使用 `aschedule_ingestion`。

## Assumptions Log

| # | Claim | Section | Risk if Wrong |
|---|-------|---------|---------------|
| A1 | persist 返回后直接 await defer；禁止 async view 内嵌套 async_to_sync(on_commit) `[RESOLVED]` | Pattern 1 | 已选 A1：atomic 已提交；投递失败由行扫描兜底 |
| A2 | `EntityOrigin.MCP` 为 session_capture 正确 origin `[RESOLVED]` | Pattern 4 | 仓级会话不进 PROJECT origin；不进 uuid5 |
| A3 | 最大 6 次、5s 指数封顶 300s `[RESOLVED]` | Pitfalls / Code Examples | 失败行保留；显式重派仍可 retry |

**If this table is empty:** 否。A1–A3 均已 RESOLVED，实现者不得再改入队路径或 retry 上限。

## Open Questions

All items below are **RESOLVED** for Phase 143 (locked for executors; also listed in 143-07 `<resolved_research_questions>`).

1. **OQ-1 RESOLVED: 141 预留的 `EVALUATED` 是否从 choices 删除？**
   - Decision: **保留枚举成员但不作为 writer 目标**；CAS/recovery 不 claim、不 resume；terminal skip 与 evaluated_low/ingested 同等。禁止 RunPython 批量改 low。

2. **OQ-2 RESOLVED: 无仓库的 medium/high 是否仍 ingest？**
   - Decision: **仍 ingest**（`repository_id=None`，edges 空）；Phase 144 按仓召回可能看不到它们，属读侧限制，本阶段不静默丢行、不跳过评估。

3. **OQ-3 RESOLVED: evaluating/ingesting 崩溃后如何恢复？**
   - Decision: 视为可 resume 的 in-flight。recovery 扫描 stale processing 且无 active job 后用稳定 key 重派；worker resume 不递增 attempt；不得把 processing 当终态 skip。

4. **OQ-4 RESOLVED: Procrastinate 退避能否复用稳定 idempotency key？**
   - Decision: **不能**。首次入队与 recovery 用稳定 key；worker backoff 用 lock+run_at 且省略或使用 attempt-specific key，以保证新 scheduled job；tasks.py 与 handlers.py 双后端同语义。

## Environment Availability

| Dependency | Required By | Available | Version | Fallback |
|------------|-------------|-----------|---------|----------|
| Python | 全部 | ✓ | 3.14.2 | — |
| Django / uv | 测试与 migration | ✓ | Django 6.0.1 | — |
| Postgres + Procrastinate worker | 生产 persist-first | 环境相关 | compose `run_worker` | pytest：in-process + **行扫描恢复**必须测 |
| Qdrant / embedding | 真实 ingest | 测试默认 `--disable-socket` | — | mock `ingest`/`EmbeddingService`；normalizer 单测不触网 |
| Friday ProviderCredential | 真 LLM | 测试 mock `build_chat_model` | — | 缺凭证路径测 `eval_failed` |
| slopcheck | 新包审计 | ✗ | — | 无新包 |

**Missing dependencies with no fallback:** none for planning/execution in this repo.

**Missing dependencies with fallback:** 真 LLM/Qdrant — 测试必须 mock；人工探测可标 human_needed。

## Validation Architecture

`workflow.nyquist_validation` = true。

### Test Framework

| Property | Value |
|----------|-------|
| Framework | pytest 9.x + pytest-django + pytest-asyncio（`asyncio_mode=auto`） |
| Config file | `server/pyproject.toml` `[tool.pytest.ini_options]` |
| Quick run command | `cd server && uv run pytest tests/initiatives/test_session_capture_eval.py tests/initiatives/test_capture_inv6_guard.py tests/knowledge/test_session_capture_source.py tests/test_model_usage_call_source.py::TestCallSourceEnum -q --tb=short` |
| Full suite command | `cd server && uv run pytest tests/initiatives/test_session_capture_eval.py tests/initiatives/test_session_capture_eval_tasks.py tests/initiatives/test_capture_service.py tests/initiatives/test_capture_inv6_guard.py tests/initiatives/test_capture_observability.py tests/knowledge/test_session_capture_source.py tests/mcp_tools/test_report_session_knowledge.py tests/mcp_tools/test_report_project_knowledge.py tests/initiatives/test_memory_inv6_guard.py tests/test_model_usage_call_source.py tests/durable/test_charter_draft_task.py -q --tb=short` |

默认 `addopts` 含 `--disable-socket` 与 `-m 'not postgres_queue'`：durable 双后端行为用 in-process；Procrastinate 真队列不作为本阶段门禁。

### Phase Requirements → Test Map

| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| EVAL-01 | 异步三档 + 精华；失败行仍在 | unit | `pytest tests/initiatives/test_session_capture_eval.py::test_eval_writes_tier_and_essence -x` | ❌ Wave 0 |
| EVAL-01 | 失败不删除、不默认 low | unit | `...::test_eval_failure_keeps_capture_not_low -x` | ❌ Wave 0 |
| EVAL-02 | 不调用质量门/grader/confidence | static | `...::test_eval_module_does_not_import_quality_gates -x` | ❌ Wave 0 |
| EVAL-02 | `use_call_source(session_capture_eval)` + `arecord_llm_usage` | unit | `...::test_eval_records_usage_with_session_capture_eval -x` | ❌ Wave 0 |
| EVAL-03 | low 不调 ingest/embedding | unit | `...::test_low_skips_ingest -x` | ❌ Wave 0 |
| EVAL-03 | medium/high content 仅为精华 | unit | `pytest tests/knowledge/test_session_capture_source.py::test_content_is_essence_not_qa -x` | ❌ Wave 0 |
| EVAL-03 | DOCUMENT + source_kind | unit | `...::test_document_session_capture_event -x` | ❌ Wave 0 |
| EVAL-04 | persist 后 defer，非 background_runner 唯一 | unit | `pytest tests/mcp_tools/test_report_session_knowledge.py::test_accepted_enqueues_durable_eval -x` | ❌ Wave 0 |
| EVAL-04 | 重放不二次 LLM；ingest hash skip | unit | `tests/initiatives/test_session_capture_eval_tasks.py::test_replay_skips_llm_when_not_pending` | ❌ Wave 0 |
| EVAL-04 | pending/failed 与 stale evaluating/ingesting 且无在途 job 可恢复 | unit | `...::test_recovery_redefers_pending_eval` / `test_recovery_redefers_stale_evaluating` / `test_recovery_redefers_stale_ingesting` | ❌ Wave 0 |
| EVAL-05 | 零 MemoryService.append / record_hook_writeback | unit+static | INV-6 扩展 + `test_eval_does_not_write_project_memory` | ❌ Wave 0 |
| OBS-04 | worker bind user；缺省 system | unit | `...::test_worker_rebinds_initiated_by_user_id -x` | ❌ Wave 0 |
| OBS-04 / OBS-01 | sampling 无正文 | unit | 扩展 `test_capture_observability.py` 或新文件 | ❌ Wave 0 |
| CallSource | 枚举=LOGGING-SPEC=测试集 | unit | `test_model_usage_call_source.py::TestCallSourceEnum` | ✅ 需改期望集 |

### Sampling Rate

- **Per task commit:** 该任务窄 `<automated>`（禁止 full suite）
- **Per wave merge:** 该 wave 各 PLAN 任务的 `<automated>`
- **Phase gate:** Full suite（~120s）仅 Plan 07 Task 2 / `/gsd-verify-work`

### Wave 0 Gaps

- [ ] `server/tests/initiatives/test_session_capture_eval.py` — EVAL-01/02/05、空输入、缺模型
- [ ] `server/tests/initiatives/test_session_capture_eval_tasks.py` — CAS、双任务、backoff、恢复扫描、bind_task_context
- [ ] `server/tests/knowledge/test_session_capture_source.py` — normalizer 精华-only、无项目仍出事件、REFERENCES、未知 capture 空列表
- [ ] 扩展 `test_capture_inv6_guard.py` — CAS 仍只允许 writer；eval/ingest 模块禁止 `objects.create`/`MemoryService`/`aschedule_ingestion`
- [ ] 扩展 `test_report_session_knowledge.py` — persist 后入队；入队失败仍 200/`accepted=true`
- [ ] 扩展 `test_model_usage_call_source.py` — `initiative_profile` + `session_capture_eval`
- [ ] `test_writer_does_not_call_deferred_sinks` — **更新允许清单**：persist 仍禁止 `aschedule_ingestion`/`MemoryService`；enqueue 放独立模块，勿把 Durable 写进 persist 除非同步改守卫

## Security Domain

`security_enforcement` enabled（ASVS L1）。

### Applicable ASVS Categories

| ASVS Category | Applies | Standard Control |
|---------------|---------|-----------------|
| V2 Authentication | no（沿用 MCP PAT/JWT） | 不改认证 |
| V3 Session Management | no | — |
| V4 Access Control | yes（间接） | 不写未授权 ProjectMemory；ingest 用 Capture 已挂钩的 repo/project，不按 payload 改 FK |
| V5 Input Validation | yes | LLM JSON 闭集校验；非法输出当失败非 low；normalizer 再 `redact_secrets_in_text` |
| V6 Cryptography | no new | 既有 Fernet 凭证；禁止日志明文 key |

### Known Threat Patterns for Capture eval/ingest

| Pattern | STRIDE | Standard Mitigation |
|---------|--------|---------------------|
| 队列/日志注入密钥 | Information Disclosure | payload 无正文；`redact_secrets_in_text`；structlog 自动 `redact_credentials` |
| 伪造价值档绕过 | Tampering | 仅 LLM+校验器写 tier；禁止客户端传入 value_tier |
| 重复 ingest 刷向量 | Denial of Service | idempotency_key + content_hash skip + CAS |
| 把会话写成项目记忆 | Elevation of Privilege / Tampering | 禁止 Memory 写入口；回归计数 |
| 未授权项目入图边 | Information Disclosure | 仅当 persist 已绑授权 `project_id` 才 `REFERENCES` |

## Project Constraints (from .cursor/rules/)

来源：`.cursor/rules/observability-logging.mdc` + 工作区 CLAUDE/AGENTS 摘录。

- `structlog.get_logger(__name__)`，事件 snake_case `started/completed/failed`，字段 kv，禁止把变量拼进 message。
- 凭证/token 禁止入日志；异常与上游文本 `redact_secrets_in_text`；观测 `except: pass` 不反噬。
- 后台任务必须携带并 re-bind `initiated_by_user_id`，否则 `system`。
- 新 LLM：`call_source` + 请求数/token/TTFT/上游错误码。
- eval/ingest 为 **sampling** + `component=knowledge`（persist 已是 caller，本阶段不要把评估升成 caller 刷屏）。
- 高频循环禁止 INFO 刷屏（恢复扫描逐行用 debug 或单条汇总计数）。
- 凭证走 `ProviderCredential` / `ProviderConfigService`，不读 env 当模型猜测。
- 不新增运行时 Python/npm 依赖。
- GSD：本文件为 RESEARCH；实现须经后续 PLAN，本代理不改业务代码。

## Sources

### Primary (HIGH confidence)

- `server/initiatives/models/session_capture.py` — 现有状态与表
- `server/initiatives/services/capture_service.py` — INV-6 persist / atomic
- `server/mcp_tools/views.py` `ReportSessionKnowledgeView` — 无 enqueue
- `server/durable/service.py` `queues.py` `tasks.py` `tasks_impl.py` `handlers.py` `apps.py` `run_worker.py`
- `server/knowledge/ingestion.py` `sources/__init__.py` `sources/project_memory.py` `models.py` `generate_entity_id`
- `server/agents/call_source.py` `llm_factory.py`
- `server/initiatives/services/memory_distill.py` — 用量模式
- `server/tests/test_model_usage_call_source.py` — 45 vs 46 漂移
- `.planning/observability/LOGGING-SPEC.md` §4.1 / §10
- `.planning/phases/141-capture/141-VERIFICATION.md` `141-04-SUMMARY.md`
- `.planning/phases/142-mcp/142-VERIFICATION.md` `142-04-SUMMARY.md`
- `.planning/ROADMAP.md` Phase 143 / `.planning/REQUIREMENTS.md` EVAL-01..05 OBS-04
- `.planning/phases/143-eval/143-CONTEXT.md`

### Secondary (MEDIUM confidence)

- compose/helm worker 未 pin `--queues` → 新 `ALL_QUEUES` 成员自动消费
- `EntityOrigin.MCP` 选择（CONTEXT 未锁）

### Tertiary (LOW confidence)

- 无 WebSearch；无 Context7（本阶段无新第三方 API）

## Metadata

**Confidence breakdown:**

- Standard stack: HIGH — 零新包，全部为本仓已核实模块
- Architecture: HIGH — 状态机与 ingest/durable 接缝已读源码；入队 on_commit vs await 为 A1
- Pitfalls: HIGH — INV-6、aschedule、CallSource 漂移、双后端漏登记均有文件证据

**Research date:** 2026-08-28
**Valid until:** 2026-09-27（30 天；栈稳定）
