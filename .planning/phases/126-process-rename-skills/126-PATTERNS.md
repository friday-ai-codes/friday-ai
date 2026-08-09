# Phase 126: process-rename-skills - Pattern Map

**Mapped:** 2026-08-10
**Files analyzed:** 33
**Analogs found:** 33 / 33

## Hard Locks (planner must honor)

| Lock | Constraint |
|------|------------|
| Model name | ORM class **`ProcessTrace` only** — ⛔ never `Process` (collides with `ProcessEngine` / `ProcessDefinition`) |
| BFS constants | `maxDepth=10`, `maxBranching=4`, `minSteps=3`, edge conf ≥ `0.5`; cycle + async boundary explicit |
| Durable queue | `QUEUE_GRAPH`; `idempotency_key` / lock `process:{repo_id}:{branch}`; enqueue **after** community success |
| affected_processes | Single helper; fill empty arrays in `run_impact` / `run_detect_changes` only |
| rename_preview | Read-only; `applied` always `false`; dual-source `graph` \| `text_search`; no apply API |
| Skills | `friday-impact` + `friday-refactoring` in `SKILL_NAMES` + hash sync |
| ⛔ FROZEN | Do **not** modify `server/codegraph/services/repo_router_v2.py` or `mcp/` submodule — not modification targets |

## File Classification

| New/Modified File | Role | Data Flow | Closest Analog | Match Quality |
|-------------------|------|-----------|----------------|---------------|
| `server/codegraph/models.py` (+`ProcessTrace`) | model | CRUD | `SymbolCommunity` in same file | exact |
| `server/codegraph/migrations/00xx_processtrace.py` | migration | CRUD | latest `SymbolCommunity` migration | exact |
| `server/services/code_graph/process_trace.py` | service | batch / transform | `server/services/code_graph/community.py` + forward-mirror of `impact.py` | exact |
| `server/services/process_enqueue.py` | service | event-driven | `server/services/community_enqueue.py` | exact |
| `server/durable/tasks.py` (+`durable_process_rebuild`) | route | event-driven | `durable_community_rebuild` in same file | exact |
| `server/durable/tasks_impl.py` (+`run_process_rebuild`) | service | batch | `run_community_rebuild` in same file | exact |
| `server/durable/handlers.py` | middleware | event-driven | `_community_rebuild` registration | exact |
| `server/services/code_graph_tools.py` (`run_list/get_process`, `run_rename_preview`, `assemble_affected_processes`) | service | request-response | `run_impact` / `run_detect_changes` in same file | exact |
| `server/services/code_graph/impact_report.py` | utility | transform | `_render_affected` / `_render_recommendations` in same file | exact |
| `server/services/code_graph/rename_preview.py` | service | request-response / transform | `impact.py` resolve + `GrepRepositoryView` grep half | role-match |
| `server/mcp_tools/views.py` (list/get/rename shells) | controller | request-response | `ImpactAnalysisView` / `DetectChangesView` | exact |
| `server/mcp_tools/urls.py` | route | request-response | impact/detect/trace paths | exact |
| `server/mcp_tools/serializers.py` | utility | request-response | `ImpactAnalysisRequestSerializer` | exact |
| `server/agents/tools/graph_tools.py` | provider | request-response | `impact_analysis` `@tool` | exact |
| `server/agents/tools/schemas/graph_tools.py` | utility | request-response | existing Impact/Detect schemas | exact |
| `server/friday/settings.py` (`CODE_GRAPH_PROCESS_*`) | config | — | existing `CODE_GRAPH_*` knobs | role-match |
| `task/core/knowledge_tools.py` (whitelist) | utility | request-response | `detect_changes` whitelist entry | exact |
| `task/scripts/sync_skills.py` | utility | file-I/O | same file `SKILL_NAMES` | exact |
| `task/tests/test_skills_injection.py` | test | file-I/O | `TestSkillsHashConsistency` | exact |
| `skills/skills/friday-impact/SKILL.md` | config | — | `skills/skills/friday-code/SKILL.md` | exact |
| `skills/skills/friday-refactoring/SKILL.md` | config | — | `skills/skills/friday-code/SKILL.md` | exact |
| `skills/README.md` / `installer.mjs` / `plugin.json` / `friday/SKILL.md` | config | — | friday-routing 7→N copy precedent | role-match |
| `task/assets/skills/friday-{impact,refactoring}/**` | config | file-I/O | sync output of friday-code/memory | exact |
| `server/tests/codegraph/test_process_trace_model.py` | test | CRUD | SymbolCommunity model tests (if any) / Endpoint Meta shape | role-match |
| `server/tests/services/code_graph/test_process_trace.py` | test | batch | `test_community.py` | exact |
| `server/tests/services/code_graph/test_process_enqueue.py` | test | event-driven | `test_community_enqueue.py` | exact |
| `server/tests/services/code_graph/test_rename_preview.py` | test | request-response | impact/detect tool tests + grep exclusion tests | role-match |
| `server/tests/services/code_graph/test_affected_processes.py` | test | transform | envelope assertions around `affected_processes: []` | role-match |
| `server/tests/services/code_graph/test_frozen_surface_126.py` | test | — | `test_frozen_surface_125.py` | exact |
| `server/tests/services/code_graph/test_impact_report.py` | test | transform | existing impact_report tests | exact |
| `server/tests/mcp_tools/test_schema_snapshot.py` | test | request-response | same file drift accounting | exact |

**Not modification targets (frozen — listed for planner exclusion only):**

| Path | Reason |
|------|--------|
| `server/codegraph/services/repo_router_v2.py` | D-16 frozen |
| `mcp/` git submodule | D-16 / 122 D-27 |

## Pattern Assignments

### `server/codegraph/models.py` — `ProcessTrace` (model, CRUD)

**Analog:** `SymbolCommunity` (+ `Endpoint` for entry snapshot fields)

**Soft-ref independent model** (lines 341–387):
```python
class SymbolCommunity(models.Model):
    """符号社区 —— Louvain（等）划分结果，成员以 JSON 软引用 Symbol.id。
    Phase 125 / MOD-01：独立模型纯加表，⛔ 不给 Symbol 加 community_id / FK / M2M。
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    repository = models.ForeignKey(
        "repositories.Repository",
        on_delete=models.CASCADE,
        related_name="symbol_communities",
    )
    branch_name = models.CharField(max_length=200, default="", blank=True)
    community_key = models.CharField(max_length=64)
    members = models.JSONField(default=list)
    built_at_sha = models.CharField(max_length=64, blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = [("repository", "branch_name", "community_key")]
```

**Endpoint snapshot fields to copy into `entry_endpoint` JSON** (lines 176–202) — ⛔ no FK:
```python
http_method = models.CharField(max_length=16)
url_path = models.CharField(max_length=512, db_index=True)
handler_name = models.CharField(max_length=255)
file_path = models.CharField(max_length=512)
line_number = models.IntegerField()
```

**Copy for ProcessTrace:** same soft-ref + `unique_together=(repository, branch_name, process_key)` + `built_at_sha`; add `community_class` TextChoices `intra_community` \| `cross_community`; export in `__all__`. Name must be **`ProcessTrace`**.

---

### `server/services/code_graph/process_trace.py` (service, batch/transform)

**Analogs:** `community.py` (rebuild/persist) + `impact.py` (BFS edge discipline, direction flipped to `successors`)

**Imports / graph access** (community.py ~484–508):
```python
from services.code_graph import get_graph_service
# …
code_graph = await get_graph_service().get_graph(
    str(repository_id),
    branch=branch,
)
```

**Full delete + bulk create** (community.py 433–469):
```python
with transaction.atomic():
    SymbolCommunity.objects.filter(repository=repo, branch_name=branch_name).delete()
    if rows:
        SymbolCommunity.objects.bulk_create(rows)
```

**Reverse BFS edge discipline to mirror as forward BFS** (impact.py 376–463) — Process uses `successors` + D-02 caps:
```python
# impact uses predecessors; ProcessTrace MUST use successors
for pred in graph.predecessors(node):
    if pred in best:
        continue
    for attrs in graph[pred][node].values():
        score = _edge_score(attrs)
        if score < min_confidence:
            continue
# ⛔ never nx.bfs_layers / graph.copy() / graph.reverse(copy=True)
```

**Hard constants (CONTEXT D-02 — lock in module Finals):**
```python
MAX_DEPTH = 10
MAX_BRANCHING = 4
MIN_STEPS = 3
MIN_CONF = 0.5
# maxProcesses = max(MIN, min(CAP, symbol_count // 10))
```

**Observability:** `process_rebuild_started` / `_completed` / `_failed` with `category`/`component="code_graph"`/`duration_ms`; BFS loop = sampling/debug only.

---

### `server/services/process_enqueue.py` (service, event-driven)

**Analog:** `server/services/community_enqueue.py` (entire file)

**Core enqueue** (lines 17–72):
```python
async def enqueue_community_rebuild(
    repository_id: str,
    *,
    branch_name: str = "",
    initiated_by_user_id: str | None = None,
) -> str | None:
    from durable.queues import QUEUE_GRAPH
    from durable.service import DurableTaskService

    job_id = await DurableTaskService.defer(
        "durable_community_rebuild",
        {"repository_id": str(repository_id), "branch_name": branch},
        queue=QUEUE_GRAPH,
        idempotency_key=f"community:{repository_id}:{branch}",
        initiated_by_user_id=initiated_by_user_id,
    )
```

**Copy for process:** task name `durable_process_rebuild`; key `process:{repository_id}:{branch}`; swallow failures; `initiated_by_user_id or "system"` in logs.

---

### `server/durable/tasks.py` + `tasks_impl.py` + `handlers.py` (event-driven)

**Analog:** community durable triplet

**tasks.py shell** (288–308):
```python
@app.task(name="durable_community_rebuild", queue=QUEUE_GRAPH)
async def durable_community_rebuild(
    *,
    repository_id: str,
    branch_name: str = "",
    initiated_by_user_id: str | None = None,
) -> dict[str, Any]:
    from durable.tasks_impl import run_community_rebuild
    return await run_community_rebuild(
        repository_id=repository_id,
        branch_name=branch_name,
        initiated_by_user_id=initiated_by_user_id,
    )
```

**tasks_impl job body** (747–811): bind context → call rebuild → log → return; on failure redact + re-raise.

**Chain point (RESEARCH discretionary default):** at end of successful `run_community_rebuild`, best-effort `enqueue_process_rebuild(...)` — do **not** enqueue if community raises.

**handlers.py** (92–116):
```python
async def _community_rebuild(payload: dict[str, Any]) -> Any:
    from durable.tasks_impl import run_community_rebuild
    return await run_community_rebuild(**payload)

register_handler("durable_community_rebuild", _community_rebuild)
# add: register_handler("durable_process_rebuild", _process_rebuild)
```

---

### `server/services/code_graph_tools.py` (service, request-response)

**Analog:** `run_impact` / `run_detect_changes` shared orchestration (122 D-21)

**Envelope with empty `affected_processes` to fill** (748–906):
```python
async def run_impact(...) -> dict[str, Any]:
    # ACL → resolve_symbol → fetch_graph → analyze_impact → envelope
    return {
        "ok": True,
        "tool": "impact_analysis",
        # …
        "affected_processes": [],  # ← replace via assemble_affected_processes
        "staleness": await staleness_payload(repo),
        "graph": degradation_payload(graph.meta),
    }
```

**New `run_*` pattern:** same ACL + branch resolve + `ok`/`error_code`/`error` + staleness/degradation; shells must not fork algorithms.

**Single helper (RESEARCH Code Examples) — one dialect only:**
```python
def assemble_affected_processes(
    *,
    hit_symbol_ids: set[str],
    hit_file_name_keys: set[str],
    processes: list,  # ProcessTrace rows
) -> list[dict]:
    # intersect hits ∩ steps → {name, process_key, affected_steps, total_steps, community_class, step?}
    # no rows / no intersection → []
```

Batch detect_changes: load all `ProcessTrace` for repo/branch once, invert index in memory (Pitfall 4).

---

### `server/services/code_graph/impact_report.py` (utility, transform)

**Analog:** same file `_render_affected` / `_render_recommendations`

**Affected section** (185–242) — extend with「受影响执行流」from `envelope["affected_processes"]`.

**Placeholder to replace** (285–286):
```python
# ⛔ 不编造 affected_processes Process 叙事（Phase 126）
lines.append("- 执行流叙事（affected_processes）待 Phase 126，本报告不编造 Process 影响")
```

Empty → short「暂无匹配执行流 / 未构建 Process」; never invent. Keep top-N + truncate (124 D-08). Single formatter for workflow MR + MCP create_merge_request.

---

### `server/services/code_graph/rename_preview.py` (service, transform)

**Analogs:** `run_impact` symbol resolve (122 D-19) + MCP grep exclusion path

**Grep half must reuse exclusion** (`views.py` 691–719):
```python
async def _filter_grep_result(self, result, repository_id):
    matcher = await _exclusion_matcher(repository_id)
    kept_matches = [
        m for m in orig_matches if not matcher.is_excluded(str(m.get("file_path", "")))
    ]
```

**Also:** `grep_mirror` from `services.repo_mirror` — ⛔ no bare walk/re.

**Envelope hard locks (D-09/D-10):**
- `applied: false` always
- `confidence: "graph" | "text_search"` (+ optional `sources[]`)
- same `file:line` → keep one, prefer `graph`
- `coverage_limitations` string for dynamic refs
- ACL / ambiguous / not indexed → `ok=False`, never silent empty pretending zero refs

---

### `server/mcp_tools/{views,urls,serializers}.py` (controller / route / validation)

**Analog:** `ImpactAnalysisView` (1299–1405) + URL + serializer

**Thin shell** (zero algorithm):
```python
class ImpactAnalysisView(McpToolView):
    tool_name = "impact_analysis"

    async def post(self, request: Request) -> Response:
        run, err = await self._begin(request)
        # …
        input_data, err = await self._validate(ImpactAnalysisRequestSerializer, request)
        repo, err = await self._get_indexed_repo(repository_id)
        result = await run_impact(...)  # shared orchestration only
        # RetrievalTrace + caller log; ok=False → HTTP 200 + envelope
        return Response(output_data, status=status.HTTP_200_OK)
```

**urls.py** (62–64):
```python
path("tools/impact_analysis/", ImpactAnalysisView.as_view(), name="mcp-tool-impact-analysis"),
path("tools/detect_changes/", DetectChangesView.as_view(), name="mcp-tool-detect-changes"),
# add: list_processes / get_process / rename_preview
```

**Serializer pattern** (`serializers.py` 197–218): UUID `repository_id`; symbol_id XOR symbol validate; min/max on limit.

⛔ Do not edit `mcp/` submodule — only `server/mcp_tools`; SUMMARY accounts snapshot drift.

---

### `server/agents/tools/graph_tools.py` (+ schemas) (provider, request-response)

**Analog:** `impact_analysis` `@tool` (313–459)

```python
@tool(
    name="impact_analysis",
    description=_DESC_IMPACT,
    category=ToolCategory.PROJECT.value,
    parameters=_PARAMS_IMPACT,
)
async def impact_analysis(...) -> ToolResult:
    # conversation owner fail-closed → validate → _resolve_tool_repo
    # → run_impact(...) → RetrievalTrace; ok=False still ToolResult(success=True)
```

Register via `agents/tools/__init__.py` import side-effect. Same for `list_processes` / `get_process` / `rename_preview`.

---

### `task/core/knowledge_tools.py` (utility, request-response)

**Analog:** `detect_changes` whitelist block (347–379)

```python
{
    "name": "detect_changes",
    "description": "...失败/配额用尽时记录原因并继续交付...",
    "input_schema": {
        "type": "object",
        "properties": {
            "repository_id": {"type": "string", ...},
            # …
        },
        "required": ["repository_id", "compare"],
    },
},
```

**Copy for `rename_preview`:** whitelist entry only; fail-soft (do not block delivery). Update count assertions in task tests (11 → 12 tools).

---

### Skills pack: `friday-impact` / `friday-refactoring` (config + file-I/O)

**Analogs:** `skills/skills/friday-code/SKILL.md` (coding-period checklist) + `task/scripts/sync_skills.py`

**sync_skills SKILL_NAMES** (22–23) — must become:
```python
SKILL_NAMES = (
    "friday-code",
    "friday-memory",
    "friday-impact",
    "friday-refactoring",
)
```

**Hash guard** (`task/tests/test_skills_injection.py`):
```python
SKILL_NAMES = ("friday-code", "friday-memory")  # extend same tuple
class TestSkillsHashConsistency:
    @pytest.mark.parametrize("skill_name", SKILL_NAMES)
    # sha256 source vs task/assets/skills/<name>
```

**Skill frontmatter** (friday-code L1–3):
```markdown
---
name: friday-code
description: "…"
---
```

Body = zh-CN trigger + tool-order checklist (context/staleness → detect_changes/impact/list_processes → rename_preview). ⛔ No second hand-written copy in main repo; run `python task/scripts/sync_skills.py` after submodule edit.

---

### `server/tests/services/code_graph/test_frozen_surface_126.py` (test)

**Analog:** `test_frozen_surface_125.py` (1–78)

```python
_NO_ROUTER_IMPORT = (
    "services/code_graph/community.py",
    # … extend with process_trace.py, rename_preview.py, process_enqueue.py
)

def test_phase_125_does_not_touch_repo_router_v2() -> None:
    for rel in _NO_ROUTER_IMPORT:
        # AST forbid import repo_router_v2
    # optional git log --grep forbid mcp/ path touches
```

Phase 126 list must include new kernels; still allow `mcp_tools/views.py` adapters.

---

### Tests: process / enqueue / rename / affected

| New test file | Analog |
|---------------|--------|
| `test_process_trace.py` | `test_community.py` (inject graph, assert rebuild counts) |
| `test_process_enqueue.py` | `test_community_enqueue.py` (`QUEUE_GRAPH` + lock key assert) |
| `test_affected_processes.py` | assert helper + `run_impact`/`run_detect_changes` fill non-placeholder |
| `test_rename_preview.py` | dual-source merge + `applied is False` + exclusion fail-closed |
| `test_process_trace_model.py` | Meta unique_together; no Endpoint FK on ProcessTrace |
| extend `test_impact_report.py` | no「待 Phase 126」string when data present / empty-state wording |

## Shared Patterns

### Dual-face tool shell (MCP + agents)
**Source:** `ImpactAnalysisView` + `agents/tools/graph_tools.py::impact_analysis`
**Apply to:** list_processes, get_process, rename_preview
- Shared `run_*` only; shells validate/ACL/trace
- `ok=False` → HTTP 200 / `ToolResult(success=True)` with envelope
- `component="mcp_tools"` / agents component; `category="caller"`; RetrievalTrace

### Durable QUEUE_GRAPH rebuild
**Source:** `community_enqueue.py` + `durable_community_rebuild` + `run_community_rebuild`
**Apply to:** process rebuild chain
- `idempotency_key=f"process:{repo}:{branch}"`
- `initiated_by_user_id` required (default `system`)
- get graph via `get_graph_service` only
- full delete + bulk create

### Soft-ref derived model
**Source:** `SymbolCommunity`
**Apply to:** `ProcessTrace`
- JSON soft refs; `built_at_sha`; branch `""` = baseline
- ⛔ no FK to Endpoint / Symbol

### Forward BFS = impact reverse flipped
**Source:** `impact.py::_reverse_layers` + `_edge_score`
**Apply to:** `process_trace.py`
- `successors` + MultiDiGraph `.values()` per edge
- Cap depth/branching/minSteps/conf; mark cycle & async_boundary
- ⛔ no `nx.bfs_layers` materialization of whole component

### Grep exclusion fail-closed
**Source:** `GrepRepositoryView._filter_grep_result` + `grep_mirror`
**Apply to:** rename_preview text half only

### Skills single source of truth
**Source:** `sync_skills.py` + `TestSkillsHashConsistency`
**Apply to:** friday-impact / friday-refactoring
- Edit submodule → sync → never hand-edit `task/assets/skills/`

### Observability
**Source:** `.cursor/rules/observability-logging.mdc` + community/MCP logs
**Apply to:** rebuild, enqueue, all new tools
- started/completed/failed + `duration_ms` + `category` + `component="code_graph"`
- BFS loops: sampling/debug only
- redact secrets in context/grep text

### affected_processes single dialect
**Source:** empty arrays at `code_graph_tools.py` L903 / L1427 + RESEARCH helper
**Apply to:** `run_impact` and `run_detect_changes` only — no third assembler

## No Analog Found

| File | Role | Data Flow | Reason |
|------|------|-----------|--------|
| — | — | — | All planned files have role/exact analogs; Process forward-BFS is a directional flip of impact, not a greenfield algorithm |

## Metadata

**Analog search scope:** `server/codegraph/`, `server/services/code_graph/`, `server/services/code_graph_tools.py`, `server/services/community_enqueue.py`, `server/durable/`, `server/mcp_tools/`, `server/agents/tools/`, `task/{scripts,core,tests}/`, `skills/skills/`, `server/tests/services/code_graph/`
**Files scanned:** ~40 primary + grep hits
**Pattern extraction date:** 2026-08-10
**Frozen surfaces excluded from modification mapping:** `repo_router_v2.py`, `mcp/` submodule
