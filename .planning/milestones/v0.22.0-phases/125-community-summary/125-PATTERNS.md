# Phase 125: 社区检测 + 模块摘要 - Pattern Map

**Mapped:** 2026-08-10
**Files analyzed:** 22
**Analogs found:** 20 / 22（2 个为冻结面 / 禁止改动，不找实现类比）

## Hard Locks（规划必守）

| Lock | Implication for planner |
|------|-------------------------|
| ⛔ `server/codegraph/services/repo_router_v2.py` 零改动 | 不得出现在任何 plan 的 modify 列表；不得 stage |
| ⛔ `mcp/` submodule 零改动 | 只改 `server/mcp_tools/views.py` 接线，不碰 npm 客户端 |
| `SymbolCommunity` 软引用 | 照抄 `Symbol.chunk_id`：UUID 字符串 / 无 FK / 不挂 `Symbol.community_id` |
| Louvain 固定 seed + 节点排序 | 模块常量 `LOUVAIN_SEED`；投影 `nx.Graph` 时 `sorted` 节点/边 |
| `call_source=module_summary` | Wave 0：**先** LOGGING-SPEC §4.1 → `CallSource` 枚举 → 守护测 44→45，**再**写 LLM 调用点 |
| Adapter-only 注入 | 镜像 `charter_route_signal` / `blueprint_route` evidence；不进 Stage1；不破三分量恒等式 |
| Durable `QUEUE_GRAPH` | 新任务名 `durable_community_rebuild`；`queueing_lock=community:{repo}:{branch}`；钩子只 enqueue |

## File Classification

| New/Modified File | Role | Data Flow | Closest Analog | Match Quality |
|-------------------|------|-----------|----------------|---------------|
| `server/codegraph/models.py` (+`SymbolCommunity`) | model | CRUD | `Symbol` soft-ref `chunk_id` in same file | exact |
| `server/codegraph/migrations/0011_*symbolcommunity*.py` | migration | CRUD | `0006_symbol_chunk_id.py`（纯加字段/表风格） | role-match |
| `server/services/code_graph/community.py` | service | batch / transform | `services/code_graph/impact.py`（包内非 barrel 内核）+ Louvain 投影（RESEARCH Pattern 1） | role-match |
| `server/services/code_graph/module_summary.py` | service | request-response (LLM) | `repositories/services/charter_service.py` `_agenerate_draft` / `adraft_charter` | exact |
| `server/services/community_enqueue.py` | utility | event-driven | `repositories/charter_enqueue.py` | exact |
| `server/durable/tasks.py` (+`durable_community_rebuild`) | route / task shell | event-driven | `durable_graph`（同 `QUEUE_GRAPH`）+ `durable_charter_draft`（形参透传） | exact |
| `server/durable/tasks_impl.py` (+`run_community_rebuild`) | service | batch | `run_charter_draft`（`bind_task_context` + started/completed） | exact |
| `server/durable/handlers.py` (+register) | middleware / registry | event-driven | `_charter_draft` + `register_handler` | exact |
| `server/services/graph_builder.py`（钩子旁 enqueue） | service | event-driven | 同文件 Galaxy + `invalidate_repository` 块 | exact |
| `server/code_relations/tasks.py`（钩子旁 enqueue） | service | event-driven | 同文件边构建完成后失效块 | exact |
| `server/agents/call_source.py` (+`MODULE_SUMMARY`) | config / enum | transform | 同文件 `BLUEPRINT_CHARTER_DRAFT` 登记块 | exact |
| `.planning/observability/LOGGING-SPEC.md` §4.1 | config / docs | — | 同文件 `blueprint_charter_draft` 行 | exact |
| `server/services/module_summary_signal.py` | service / adapter | request-response | `services/charter_route_signal.py` | exact |
| `server/agents/tools/repository_relevance.py` | service / tool | request-response | `_apply_charter_signal` 旁路 | exact |
| `server/mcp_tools/views.py`（`RouteRepositoriesView`） | controller | request-response | 同 view 章程信号块 ~L448–474 | exact |
| `server/services/process_runtime/blueprint_route.py` | service / adapter | request-response | `_EVIDENCE_KEYS` + `_normalize_evidence` + evidence 组装 | exact |
| `server/services/process_runtime/blueprint_research_adapter.py` | service | transform | `_build_prompt` 章程段 + `artifact_injection.render_upstream_*` 空守卫 | exact |
| `server/tests/test_model_usage_call_source.py` | test | — | 同文件 `_EXPECTED_CALL_SOURCES` / 44 值断言 | exact |
| `server/tests/services/code_graph/test_community.py` | test | — | `tests/services/code_graph/test_impact.py`（合成冻结图 + 纯算法） | role-match |
| `server/tests/services/test_module_summary_signal.py` | test | — | `tests/services/test_charter_route_signal.py` | exact |
| `server/tests/services/process_runtime/test_blueprint_route_breakdown.py`（扩展） | test | — | 同文件 `test_evidence_missing_keys_get_neutral_defaults` | exact |
| `server/tests/services/code_graph/test_frozen_surface_125.py` 等 Wave 0 测 | test | — | `test_access.py` AST 守卫风格 | role-match |
| ⛔ `repo_router_v2.py` | — | — | **FORBIDDEN** | n/a |
| ⛔ `mcp/` | — | — | **FORBIDDEN** | n/a |

## Pattern Assignments

### `server/codegraph/models.py` — `SymbolCommunity`（model, CRUD）

**Analog:** `Symbol` soft-ref `chunk_id` + `branch_name` 隔离（同文件）

**Soft-ref / branch isolation** (lines 31–45, 49–60):
```python
# 分支隔离维度。"" = base 分支（与向量 overlay 语义同构）
branch_name = models.CharField(max_length=200, default="", blank=True)
# ...
# 不做 FK（per code_relations contract 柔性引用）。
chunk_id = models.UUIDField(null=True, blank=True, db_index=True)
# ...
unique_together = [("repository", "branch_name", "file_path", "name", "start_line")]
```

**Copy for `SymbolCommunity`:**
- `repository` FK + `branch_name`（`""`=基线）
- `members` JSON：每项含 `symbol_id` **字符串**软引用（⛔ 不加 FK、⛔ 不挂 `Symbol.community_id`）
- `unique_together = (repository, branch_name, community_key)`
- migration **只 ADD TABLE**，零改既有表

---

### `server/services/code_graph/community.py`（service, batch/transform）

**Analog:** `services/code_graph/impact.py`（包内非 barrel 内核）+ RESEARCH Louvain 投影

**Barrel / 边界纪律**（`__init__.py` lines 29–42）——`community.py` 与 `impact`/`trace` 同档：
```python
# impact / trace / symbol_resolve 三个新内核与 model 同属契约/算法层，
# 刻意不进本 barrel，也不进 test_access.py 的 _INTERNAL_SUBMODULES。
# 取图仍然必须经 get_graph_service → get_graph()
```

**⚠️ ORM 例外（D-12 / RESEARCH Pitfall 5）：** `community.py` 持 ORM 写入（全删全建），视作与 `loader` 同类的 ORM 例外同伴——**不进** `__all__`；**不进** `_INTERNAL_SUBMODULES` 黑名单；durable / 钩子可 `import services.code_graph.community`。取图仍走 barrel。

**Core Louvain projection**（照抄 RESEARCH Pattern 1，勿就地改冻结 MultiDiGraph）:
```python
from networkx.algorithms.community import louvain_communities
import networkx as nx

LOUVAIN_SEED = 42  # 模块级常量，写入测试

def project_undirected(g: nx.MultiDiGraph) -> nx.Graph:
    # ⛔ 不就地改 g（可能已 freeze）；投影到新 Graph
    u = nx.Graph()
    u.add_nodes_from(sorted(g.nodes()))
    edges = {(a, b) if a <= b else (b, a) for a, b in g.edges()}
    u.add_edges_from(sorted(edges))
    return u
```

**Observability:** `component="code_graph"`；生命周期 `community_rebuild_started/completed/failed` + `duration_ms`；高频 `category=sampling`；字段含 `communities_total` / `summaries_skipped` / `summaries_generated`。

**Fingerprint / Jaccard:** 纯函数可放同文件或 `_fingerprint.py` helper；指纹 short-circuit → 贪心 Jaccard≥0.8；仅当旧 `summary` 非空才跳过（D-08）。

---

### `server/services/code_graph/module_summary.py`（service, LLM request-response）

**Analog:** `repositories/services/charter_service.py` `_agenerate_draft` (lines 264–454)

**Imports + call_source + fail-soft LLM** (lines 278–433):
```python
from agents.call_source import CallSource, use_call_source
from agents.llm_concurrency import acquire_llm_slot
from agents.llm_factory import build_chat_model
from services.provider_config import ProviderConfigService, ProviderMissingError

model_obj = build_chat_model(resolved, model_name, streaming=False)
# ...
with use_call_source(CallSource.BLUEPRINT_CHARTER_DRAFT):  # → MODULE_SUMMARY after Wave 0
    async with acquire_llm_slot(cred_id, max_c):
        response = await model_obj.ainvoke(messages)
except Exception as exc:  # noqa: BLE001 — 上游不可用 → best-effort None
    _draft_failed(..., error=redact_secrets_in_text(str(exc)))
    return None
```

**Copy for module summary:**
- Wave 0 登记后使用 `CallSource.MODULE_SUMMARY`
- 事件名：`module_summary_started/completed/failed`，`component="code_graph"`
- 输入只喂 top 成员元数据（路径/符号名/类型），**默认不喂源码正文**
- 单社区失败返空不抛，不阻断整仓落库（D-08）
- 批处理默认串行；size&lt;5 / `unclustered` 不调 LLM

---

### `server/services/community_enqueue.py`（utility, event-driven）

**Analog:** `repositories/charter_enqueue.py`（全文）

**Core enqueue pattern** (lines 17–69):
```python
async def enqueue_charter_draft(
    repository_id: str,
    *,
    initiated_by_user_id: str | None = None,
) -> str | None:
    from durable.queues import QUEUE_CHARTER  # → QUEUE_GRAPH for community
    from durable.service import DurableTaskService

    try:
        job_id = await DurableTaskService.defer(
            "durable_charter_draft",  # → durable_community_rebuild
            {"repository_id": str(repository_id)},
            queue=QUEUE_CHARTER,  # → QUEUE_GRAPH
            idempotency_key=f"charter:{repository_id}",  # → community:{repo}:{branch}
            initiated_by_user_id=initiated_by_user_id,
        )
        # logger.info enqueue_*_completed ... duration_ms
        return job_id
    except Exception as exc:  # noqa: BLE001
        # logger.warning enqueue_*_failed + redact_secrets_in_text
        return None
```

**Community deltas:**
- `queue=QUEUE_GRAPH`（⛔ 不要用 `QUEUE_CHARTER`）
- payload: `{repository_id, branch_name}`（缺省 `""`）
- `idempotency_key=f"community:{repository_id}:{branch or ''}"`
- 失败 swallow，钩子不反噬边/图构建

---

### Durable 三件套：`tasks.py` / `tasks_impl.py` / `handlers.py`

**Analogs:** `durable_graph`（队列）+ `durable_charter_draft` / `run_charter_draft` / `_charter_draft`

**Task shell on QUEUE_GRAPH** (`tasks.py` lines 65–83):
```python
@app.task(name="durable_graph", queue=QUEUE_GRAPH)
async def durable_graph(
    *,
    repository_id: str,
    # ...
    initiated_by_user_id: str | None = None,
) -> Any:
    from durable.tasks_impl import run_graph
    return await run_graph(..., initiated_by_user_id=initiated_by_user_id)
```

**Worker body with bind_task_context** (`tasks_impl.py` lines 631–666):
```python
async def run_charter_draft(
    *,
    repository_id: str,
    initiated_by_user_id: str | None = None,
) -> dict[str, Any]:
    actor = initiated_by_user_id or "system"
    logger.info("charter_draft_job_started", category="caller", ...)
    with bind_task_context(user_id=actor, source="durable", component="charter_service"):
        # ... business call ...
```

**Handler register** (`handlers.py` lines 86–109):
```python
async def _charter_draft(payload: dict[str, Any]) -> Any:
    from durable.tasks_impl import run_charter_draft
    return await run_charter_draft(**payload)

# inside register_business_handlers:
register_handler("durable_charter_draft", _charter_draft)
```

**Community worker body outline:**
1. `bind_task_context(user_id=actor or "system", source="durable", component="code_graph")`
2. `get_graph_service().get_graph(repo, branch)` —— ⛔ 不直连 loader/cache
3. Louvain → fingerprint/Jaccard → module_summary → replace rows by `(repository, branch_name)`
4. ⛔ **不要**给 `durable_graph` / `run_graph` 加 payload 分支

---

### 钩子：`graph_builder.py` + `code_relations/tasks.py`（event-driven）

**Analog:** 现有 Galaxy + invalidate 旁（只追加 enqueue，不内联 Louvain）

**graph_builder.py** (lines 517–533):
```python
from services.code_graph import invalidate_repository
await sync_to_async(GalaxyGraphCache.refresh_repo)(repository_id)
await sync_to_async(invalidate_repository)(repository_id)
# NEW (best-effort, after invalidate):
# await enqueue_community_rebuild(repository_id, branch_name=..., initiated_by_user_id=...)
```

**code_relations/tasks.py** (lines 224–242) — 同形，在 `inserted > 0` 分支的 invalidate 旁追加。

**纪律:** 钩子内 ⛔ 禁止跑 Louvain/LLM；只 `defer`。

---

### Wave 0：`call_source` 双登记（config）

**Analog:** `CallSource.BLUEPRINT_CHARTER_DRAFT` + LOGGING-SPEC §4.1 行 + 守护测

**Enum append** (`call_source.py` lines 131–134):
```python
# v0.20.0 Phase 111：仓库章程 AI 起草……
BLUEPRINT_CHARTER_DRAFT = "blueprint_charter_draft"
# NEW — Phase 125：社区模块摘要（先登记再写 module_summary.py）
# MODULE_SUMMARY = "module_summary"
```

**Guardian test** (`test_model_usage_call_source.py`):
- `_EXPECTED_CALL_SOURCES` 加 `"module_summary"`
- `assert len(_EXPECTED_CALL_SOURCES) == 45`（44→45）
- docstring 同步「升至 45 值」

**LOGGING-SPEC §4.1:** 在 `blueprint_charter_draft` 旁加一行；正文「当前 44 值」改为 45。

**顺序铁律:** SPEC → enum → test 绿 → 再写 `module_summary.py` 调用点。

---

### `server/services/module_summary_signal.py`（adapter, request-response）

**Analog:** `services/charter_route_signal.py`

**Frozen-surface docstring** (lines 10–17):
```python
"""§13.2 冻结面：`codegraph/services/repo_router_v2.py` 零改动、只调不改；
证据也绝不进它的 Stage1 prompt。融合一律在调用方拿到 router 结果之后做。

best-effort：失败一律退化为原样返回 router 排序，绝不阻断路由。
"""
```

**Fail-soft apply + sampling log** (lines 208–243):
```python
except Exception as exc:  # noqa: BLE001
    logger.warning(
        "charter_route_signal_failed",
        error=redact_secrets_in_text(str(exc)),
        duration_ms=...,
        category="sampling",
        component=_COMPONENT,
    )
    return [/* passthrough items */]
```

**v1 deltas（D-15 / Discretion）:**
- 以 evidence / reason **文本追加**为主
- **默认不改** `router_base` 分数、不加新权重键
- 候选补入 v1 **不做**（不算缺口）；若日后做，上限严控类比 `DEFAULT_SUPPLEMENT_LIMIT=3`

---

### 接线：`repository_relevance.py` + `mcp_tools/views.py`

**Analog:** charter 应用点旁路（⛔ 不改 `RepoRouterV2` 本体）

**对话链** (`repository_relevance.py` lines 153–177):
```python
async def _apply_charter_signal(...) -> list[RepositoryRelevanceCandidate]:
    from services.charter_route_signal import aapply_charter_signal, resolve_charter_weight
    try:
        items = await aapply_charter_signal(...)
    except Exception as exc:  # noqa: BLE001
        logger.warning("repository_relevance_charter_signal_failed", error=str(exc))
        return candidates
```
→ 新增 `_apply_module_summary_signal`（或在 charter 应用之后链式调用 `aapply_module_summary_signal`），best-effort 追加 evidence。

**MCP 链** (`mcp_tools/views.py` lines 448–474) — 在 `aapply_charter_signal` **之后**同样旁路：
```python
from services.charter_route_signal import aapply_charter_signal
signal_items = await aapply_charter_signal(...)
# NEW: signal_items = await aapply_module_summary_signal(query=query, items=signal_items)
# reason 拼接 evidence；默认不改 score
```

---

### `blueprint_route.py` — evidence only（adapter）

**Analog:** 同文件 `_EVIDENCE_KEYS` / `_normalize_evidence` / evidence 组装

**Keys + normalize** (lines 57–71, 173–191):
```python
_EVIDENCE_KEYS = (
    # ... existing ...
    # "module_summaries",  # NEW — list, default []
)

def _normalize_evidence(evidence: dict | None) -> dict:
    defaults: dict[str, Any] = {
        # ... existing ...
        # "module_summaries": [],
    }
    return {key: src.get(key, defaults[key]) for key in _EVIDENCE_KEYS}
```

**Evidence assembly** (lines 615–629) — fail-soft 填入该仓 top 社区摘要（相关度排序后截断）。

**⛔ 不要改:**
- `_COMPONENT_KEYS` / `DEFAULT_ROUTE_WEIGHTS`
- `build_score_breakdown` 三分量恒等式
- `repo_router_v2.py`

---

### `blueprint_research_adapter.py` — prompt 段（transform）

**Analogs:** `_build_prompt` 章程段 + `artifact_injection.render_upstream_artifacts_section` 空守卫

**Charter injection site** (`blueprint_research_adapter.py` lines 769–775):
```python
return (
    f"你正在为仓库「{repo_name}」评估它与本次需求的适配度...\n\n"
    f"{summarize_requirement_context(session)}\n\n"
    f"## 路由证据（服务端已算，供你核对，不要盲信）\n"
    f"{self._summarize_route_evidence(candidate)}\n\n"
    f"## 仓库章程\n{self._summarize_charter(charter)}\n\n"
    # NEW: f"## 模块摘要\n{render_module_summaries_section(...)}\n\n"  # 空 → ""
    ...
)
```

**Empty-section + budget truncate** (`artifact_injection.py` lines 71–91):
```python
def render_upstream_artifacts_section(artifacts: list[dict]) -> str:
    if not artifacts:
        return ""  # 零回归命门，绝不渲染空标题
    # ... _safe_inline + 截断 ...
```

**Copy:** 空 → `""`；相关度排序 → per-repo ~2000 字符或 top 5；超限注明 truncated；半可信字段过 `_safe_inline` 同类消毒。

---

### Tests

| New test | Analog | Pattern to copy |
|----------|--------|-----------------|
| `test_community.py`（Louvain 稳定 / Jaccard / rebuild×2 LLM=0） | `test_impact.py` | 合成冻结 `MultiDiGraph`；零 DB 纯算法；spy LLM invoke |
| `test_module_summary.py` | charter service 单测 / call_source 包裹 | `use_call_source` + fail-soft |
| `test_module_summary_signal.py` | `test_charter_route_signal.py` | fail-soft 原样返回；不改 base score（v1） |
| `test_blueprint_route_breakdown.py` 扩展 | 同文件 `test_evidence_missing_keys_get_neutral_defaults` | 断言 `module_summaries == []` 默认；三分量恒等式仍成立 |
| `test_model_usage_call_source.py` | 同文件 | 45 值 |
| `test_community_enqueue.py` | charter_enqueue 测 / defer mock | `DurableTaskService.defer` + lock 键 + 不内联 |
| `test_frozen_surface_125.py` | `test_access.py` AST 守卫 | diff/导入面不含 `repo_router_v2` / `mcp/` |
| `test_symbol_community_model.py` | codegraph model 测 | 无 `Symbol.community*` 字段；soft members |

**验收钉死（MOD-02）:** `test_rebuild_twice_zero_llm` — 无代码变更连续 rebuild×2 → spy LLM 调用数 = 0。

## Shared Patterns

### Authentication / Access（取图三道闸）
**Source:** `services/code_graph/__init__.py` + `GraphService.get_graph`
**Apply to:** `community.py` worker、一切读图路径
```python
from services.code_graph import get_graph_service
# ⛔ from services.code_graph.loader import ...
graph = await get_graph_service().get_graph(repository_id, branch_name=branch or "")
```

### Adapter-only 路由增强（冻结面）
**Source:** `charter_route_signal.py` docstring + `blueprint_route.py` evidence
**Apply to:** `module_summary_signal.py`、`blueprint_route` evidence、`repository_relevance` / MCP 接线
- 只调不改 `repo_router_v2`
- 证据不进 Stage1 prompt
- best-effort：失败原样返回

### Durable enqueue + user context
**Source:** `charter_enqueue.py` + `run_charter_draft` `bind_task_context`
**Apply to:** community enqueue / worker
- `initiated_by_user_id` 透传；无则 `"system"`
- worker 入口 `bind_task_context(user_id=..., source="durable")`
- `idempotency_key` = queueing_lock 去重

### LLM call_source lifecycle
**Source:** `charter_service._agenerate_draft`
**Apply to:** `module_summary.py`
- 先双登记再调用
- `use_call_source` + `acquire_llm_slot` + `build_chat_model(streaming=False)`
- `redact_secrets_in_text` 异常文本；started/completed/failed + `duration_ms`

### Observability
**Source:** `.cursor/rules/observability-logging.mdc` + LOGGING-SPEC
**Apply to:** community rebuild、module_summary、enqueue、signal
- `structlog.get_logger(__name__)`；事件 snake_case；字段 kv
- `category`：调用入口 `caller`；高频循环 `sampling`
- `component="code_graph"`（已登记）；观测 best-effort 不反噬

### Prompt 空段 + 预算截断
**Source:** `artifact_injection.render_upstream_artifacts_section`
**Apply to:** 调研 prompt 模块摘要段、evidence 列表截断
- 空 → `""`
- 排序 + 字符/条数预算
- `_safe_inline` 消毒半可信字段

## No Analog Found / Forbidden

| File | Role | Data Flow | Reason |
|------|------|-----------|--------|
| `server/codegraph/services/repo_router_v2.py` | — | — | **FORBIDDEN** §13.2；本相位零 stage。注入走 adapter |
| `mcp/` (submodule) | — | — | **FORBIDDEN**；仅 `server/mcp_tools/views.py` 接线 |
| Leiden / `leidenalg` | — | — | OUT OF SCOPE（GPL）；算法升级只换 `community.py` 内调用 |

## Metadata

**Analog search scope:**
- `server/services/code_graph/`
- `server/services/charter_route_signal.py`
- `server/repositories/{charter_enqueue.py,services/charter_service.py}`
- `server/durable/{tasks,tasks_impl,handlers,queues}.py`
- `server/services/process_runtime/{blueprint_route,blueprint_research_adapter,artifact_injection}.py`
- `server/agents/{call_source.py,tools/repository_relevance.py}`
- `server/mcp_tools/views.py`
- `server/codegraph/models.py` + migrations
- `server/tests/services/code_graph/`、`test_charter_route_signal.py`、`test_model_usage_call_source.py`
- `.planning/observability/LOGGING-SPEC.md`

**Files scanned:** ~35（含 targeted Grep）
**Pattern extraction date:** 2026-08-10
**Primary analogs (top 5):**
1. `charter_route_signal.py` — adapter 冻结面范式
2. `charter_service.py` / `charter_enqueue.py` — LLM + durable 入队
3. `blueprint_route.py` — evidence 键扩展（非打分分量）
4. `code_graph/impact.py` + `__init__.py` — 包内非 barrel 内核 / 取图纪律
5. `durable_graph` + `run_charter_draft` — `QUEUE_GRAPH` 任务壳 + `bind_task_context`
