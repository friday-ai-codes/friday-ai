# Phase 124: 编码链闭环 - Pattern Map

**Mapped:** 2026-08-10
**Files analyzed:** 17
**Analogs found:** 17 / 17

> Freeze (D-16): ⛔ 不改 `mcp/` submodule；⛔ 不改 `server/codegraph/services/repo_router_v2.py`；⛔ 不改 `task/core/runner.py` commit/push 门禁。

## File Classification

| New/Modified File | Role | Data Flow | Closest Analog | Match Quality |
|-------------------|------|-----------|----------------|---------------|
| `task/core/knowledge_tools.py` | utility | request-response | same file (`KNOWLEDGE_TOOL_SCHEMAS` + `knowledge_allowed_tools`) | exact |
| `task/core/executor.py` | utility | transform | same file (`_openspec_guidance` / `_get_system_prompt`) | exact |
| `server/services/code_graph/impact_report.py` | service | request-response | `server/services/code_graph_tools.py::run_detect_changes` + `pr_cross_reference.py` | role-match |
| `server/workflows/nodes/ai/coding.py` | service | request-response | same file (`_create_mr_for_repo`) + `pr_cross_reference.py` | exact |
| `server/mcp_tools/merge_request_service.py` | service | request-response | same file (`_draft_from_summary` / `create_merge_request`) | exact |
| `server/mcp_tools/views.py` | api | request-response | same file (`CreateMergeRequestView.post` user 透传；对照既有 MCP view 传 `request.user`） | exact |
| `server/mcp_tools/work_item_execution_service.py` | service | request-response | same file (`create_merge_request` 调用点 + `initiating_user`） | exact |
| `server/workflows/services/mr_service.py` | service | request-response | same file (`build_mr_description` / `create_mr_for_task`) | exact |
| `server/friday/settings.py` | config | — | same file (`CODE_GRAPH_BUILD_WAIT_TIMEOUT_SECONDS`) | exact |
| `task/tests/test_knowledge_tools.py` | test | — | same file (whitelist / `EXPECTED_TOOL_NAMES`) | exact |
| `task/tests/test_detect_changes_prompt.py` | test | — | `task/tests/test_openspec_prompt.py` | exact |
| `task/tests/test_claude_sdk_integration.py` | test | — | same file (`len(knowledge_allowed_tools()) == 10`) | exact |
| `task/tests/test_blueprint_context_tools_schema.py` | test | — | same file (count + schema shape) | exact |
| `task/tests/test_blueprint_context_wait.py` | test | — | same file (`== 10`) | exact |
| `server/tests/services/code_graph/test_impact_report.py` | test | — | `server/tests/mcp_tools/test_detect_changes_tools.py` + orchestrator tests | role-match |
| `server/tests/workflows/test_coding_impact_report.py` | test | — | `server/tests/workflows/test_coding_pr_target_branch.py` | exact |
| `server/tests/mcp_tools/test_mr_impact_report.py` | test | — | `server/tests/mcp_tools/test_mr_tools.py` + dual-surface sentinel | exact |

## Pattern Assignments

### `task/core/knowledge_tools.py` (utility, request-response)

**Analog:** same file — append one schema entry; factory/`knowledge_allowed_tools` auto-pick up.

**Schema entry pattern** (append after `await_blueprint_context`, ~lines 306–346; mirror serializer fields):

```python
# Source: task/core/knowledge_tools.py:52-80 (shape) + server/mcp_tools/serializers.py:222-238
{
    "name": "detect_changes",
    "description": (
        "编码完成后、提交前自查影响面：对当前功能分支相对索引水位做变更交叠 + 批量 impact。"
        "`compare` 用当前任务功能分支；可选 `base_ref` 仅声明 MR 目标分支（勿传工作树 tip 当 base）。"
        "结果仅供决策参考；失败/未索引/配额用尽时记录原因并继续交付，不要重试刷屏。"
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "repository_id": {"type": "string", "description": "仓库 UUID（必填）"},
            "compare": {
                "type": "string",
                "description": "对比 head：当前功能分支名或 40 位 commit SHA（必填）",
            },
            "base_ref": {
                "type": "string",
                "description": "可选：MR 目标分支声明（仅透出，不改 diff 左端）",
            },
            "max_depth": {"type": "integer", "description": "impact 深度 1..3（默认 3）"},
            "min_confidence": {"type": "number", "description": "最小置信度 0..1（默认 1.0）"},
            "include_low_confidence": {
                "type": "boolean",
                "description": "是否含低置信边（默认 false）",
            },
            "limit": {"type": "integer", "description": "结果上限 1..200（默认 200）"},
        },
        "required": ["repository_id", "compare"],
    },
},
```

**Allowed-tools derivation** (lines 612–616) — do not hand-roll names:

```python
def knowledge_allowed_tools() -> list[str]:
    return [
        f"mcp__{KNOWLEDGE_MCP_SERVER_NAME}__{schema['name']}" for schema in KNOWLEDGE_TOOL_SCHEMAS
    ]
```

**Do not change:** `_make_knowledge_handler` factory signature / timeout / quota counter (113 freeze; `test_blueprint_context_tools_schema.py` guards).

**Docstring drift:** module header still says「7 工具」in places; update counts to **11** where touched (comments only as needed).

---

### `task/core/executor.py` (utility, transform)

**Analog:** same file — `_openspec_guidance` + conditional append in `_get_system_prompt`.

**Current openspec pattern** (lines 1003–1052) — copy structure, extend join:

```python
def _get_system_prompt(self) -> str:
    base = """你是 Friday AI 的编码执行代理..."""
    # Phase 51: follow_openspec 条件追加
    if bool(self.config.follow_openspec):
        return base + "\n\n" + self._openspec_guidance()
    return base

def _openspec_guidance(self) -> str:
    """独立 helper（静态可信文本，无外部输入拼接）。"""
    return """openspec / SDD 编码约定..."""
```

**Target pattern** (D-01 / RESEARCH Pattern 1) — parts join, not early-return:

```python
def _detect_changes_guidance(self) -> str:
    return (
        "影响面自查（编码完成后、结束 turn 前）：\n"
        "- 若已挂载 friday-knowledge，调用 `detect_changes`："
        "`repository_id`=本任务仓 UUID，`compare`=当前功能分支"
        "（可选 `base_ref`=MR 目标分支，仅声明；勿传工作树 tip 当 base）。\n"
        "- 根据返回的受影响符号与风险决定是否继续修补；结果仅供决策参考。\n"
        "- 工具失败 / 未索引 / 配额用尽：记录原因并继续交付，不要重试刷屏；"
        "不要因为 HIGH/CRITICAL 而停止交付（提交由 Runner 负责）。"
    )

def _get_system_prompt(self) -> str:
    base = """..."""  # 既有 base 不变
    parts = [base]
    if bool(self.config.follow_openspec):
        parts.append(self._openspec_guidance())
    if (
        self.config.knowledge_endpoint
        and self.config.user_token
        and self.config.task_mode in {"plan", "execute"}
    ):
        parts.append(self._detect_changes_guidance())
    return "\n\n".join(parts)
```

**Hard constraints:** static Chinese text only; no runner/commit changes; explore/repo_summary must not append.

---

### `server/services/code_graph/impact_report.py` (service, request-response) — NEW

**Analogs:**
1. Consumer of `run_detect_changes` — `server/services/code_graph_tools.py:1056-1141`
2. Fail-soft markdown section — `server/workflows/services/pr_cross_reference.py:62-111`
3. Observability + redact — `code_graph_tools.py:100-135` / `1140-1141` ACL raise note

**API surface** (RESEARCH discretionary defaults):

```python
IMPACT_SECTION_MARKER = "## 影响面"

async def build_impact_report_section(
    *,
    repository,  # Repository
    user,        # User for ACL
    compare: str,
    base_ref: str | None = None,
) -> str:
    ...

def append_impact_report(description: str, section: str) -> str:
    if not section:
        return description or ""
    if IMPACT_SECTION_MARKER in (description or ""):
        return description  # 幂等
    base = (description or "").rstrip()
    return f"{base}\n\n{section}" if base else section
```

**Call orchestration** (consume, never rewrite BFS):

```python
# Source: code_graph_tools.py:1056-1141 — ACL raises GraphAccessDenied; catch here → stub
from services.code_graph_tools import run_detect_changes
# asyncio.wait_for(..., timeout=settings.CODE_GRAPH_IMPACT_REPORT_TIMEOUT_SECONDS)
envelope = await run_detect_changes(
    repository_id=str(repository.id),
    repo=repository,
    user=user,
    compare=compare,
    base_ref=base_ref,
)
```

**Observability skeleton** (static event names; best-effort):

```python
# Source: code_graph_tools.py:1100-1138 + D-15
logger.info(
    "impact_report_started",
    component="code_graph",
    category="caller",
    repository_id=repository_id,
    initiated_by_user_id=str(user.id) if user is not None and getattr(user, "id", None) is not None else "system",
)
# completed: duration_ms, section_chars, ok=, initiated_by_user_id=
# failed: duration_ms, error_code=, initiated_by_user_id=  (redact_secrets_in_text on any exception text)
```

**Fail-soft / stub** (D-09/D-11; align empty-string last-resort with pr_cross_reference):

```python
# Source: pr_cross_reference.py:109-111
except Exception as exc:  # noqa: BLE001
    logger.warning("pr_traceability_render_failed", error=str(exc))
    return ""
```

Stub body (prefer over silent omit):

```markdown
## 影响面

_影响面报告未能生成（`{error_code}`）。MR 已照常创建，请人工复核变更影响。_
```

**error_code map:** `repository_not_indexed`→`not_indexed`; `asyncio.TimeoutError`→`timeout`; `GraphAccessDenied`/other→`unavailable`; pass through other envelope codes when stable/short.

**Four-section render** from envelope (`code_graph_tools.py:1418-1432`):
- `### Changes` ← `files[]` / `summary.file_level_only`
- `### Affected` ← `impacts[]` groups + truncation counts
- `### Risk` ← aggregate `impacts[*].impact.risk_level` (uppercase display; enum is lowercase in `impact.py:RiskLevel`)
- `### Recommendations` ← rule phrases; do not invent `affected_processes`

**Volume:** `CODE_GRAPH_IMPACT_REPORT_MAX_CHARS` (~10240); top files=15, symbols/file=8, impact seeds=10; note `truncated`; never embed source bodies.

---

### `server/workflows/nodes/ai/coding.py` (service, request-response)

**Analog:** same file `_create_mr_for_repo` (lines 2163–2282) + fail-soft append from `pr_cross_reference`.

**Hook point** — after `body = (...)` (~2204–2209), **before** `MRCreateRequest(...)` (~2215):

```python
# Source: coding.py:2204-2219 — insert impact append between body assembly and MRCreateRequest
body = (
    f"## {plan_title}\n\n"
    f"### 任务清单\n{task_checklist}\n\n"
    f"### 变更摘要\n{summary_text}\n\n"
    f"---\n*由 Friday AI 自动创建*"
)

# Phase 124 DIFF-04: fail-soft 影响面段（与 pr_cross_reference 同姿态）
try:
    from services.code_graph.impact_report import (
        append_impact_report,
        build_impact_report_section,
    )
    section = await build_impact_report_section(
        repository=repository,
        user=user,  # from _resolve_dispatch_user / call-site plumbing
        compare=branch_name,
        base_ref=resolved_target,  # note: resolve target first if needed
    )
    body = append_impact_report(body, section)
except Exception:  # noqa: BLE001 — 最后兜底；helper 内应已吞
    pass

request = MRCreateRequest(
    source_branch=branch_name,
    target_branch=resolved_target,
    title=plan_title,
    description=body,
    ...
)
```

**User resolution for ACL** — reuse `_resolve_dispatch_user` (lines 1800–1823):

```python
async def _resolve_dispatch_user(self, context: ExecutionContext):
    execution = context.workflow_execution
    if execution is None:
        return None
    triggered_by_id = getattr(execution, "triggered_by_id", None)
    ...
```

Planner note: `_create_mr_for_repo` currently has no `user`/`context` param — either thread `dispatch_user` into the method signature (minimal) or resolve inside via stored context; missing user → stub `unavailable` (still fail-soft).

**Preserve:** dedup fence (`find_open_merge_request`), return `"description": body` for cross-ref rewrite (impact section must already be in `body`).

---

### `server/mcp_tools/merge_request_service.py` (service, request-response)

**Analog:** same file `_draft_from_summary` (51–71) + `create_merge_request` (129–147).

**Draft hook** (append after description string built):

```python
# Source: merge_request_service.py:65-71
description = (
    f"## Summary\n\nMerge `{source_branch}` into `{target_branch}`.\n\n"
    f"## Changed Files\n\n{file_lines}\n\n"
    f"## Risks\n\n{risk_lines}\n\n"
    f"## Tests\n\n{test_lines}"
)
# → append_impact_report(description, await build_impact_report_section(...))
return {"title": title[:200], "description": description}
```

**Create hook** (after default description fill, before `MRCreateRequest`):

```python
# Source: merge_request_service.py:143-156
if not description:
    ...
    description = description or f"Merge `{source_branch}` into `{target_branch}`."
# 显式 description：若尚无 ## 影响面 则 append；已有则幂等跳过
description = append_impact_report(description, section)
request = MRCreateRequest(..., description=description, ...)
```

**User:** MCP view supplies `request.user` into service (extend signature if needed). Never duplicate markdown logic in the view.

---

### `server/mcp_tools/views.py` (api, request-response)

**Analog:** same file `CreateMergeRequestView.post` (~2842–2871) + other MCP tools that pass `request.user` into services for ACL/attribution.

**Role:** HTTP/MCP 入口只做鉴权与参数解包；**不**渲染 `## 影响面` markdown。签名扩展后调用：

```python
# Source: mcp_tools/views.py CreateMergeRequestView — pass ACL user only
await create_merge_request(
    repository=repository,
    source_branch=...,
    target_branch=...,
    title=...,
    description=...,
    user=request.user,  # Phase 124：供 build_impact_report_section ACL
    ...
)
```

**Do not:** 在 view 内 import/拼装 impact 四段；重复业务逻辑属于 anti-pattern（D-14）。

---

### `server/mcp_tools/work_item_execution_service.py` (service, request-response)

**Analog:** same file `create_merge_request(...)` call (~405–414) already receives `initiating_user` on the enclosing function.

**Hook:** after signature adds `user=`, pass through:

```python
mr = await create_merge_request(
    repository=task.repository,
    source_branch=task.branch_name,
    target_branch=task.target_branch or task.repository.default_branch,
    title=...,
    description=...,
    reviewer_usernames=reviewer_usernames,
    remove_source_branch=True,
    trace=trace,
    user=initiating_user,  # Phase 124：缺传 → 永久 unavailable stub
)
```

---

### `server/workflows/services/mr_service.py` (service, request-response)

**Analog:** same file `build_mr_description` (13–41) + `create_mr_for_task` (122–168).

**Dialect elimination (D-06):** after `description = build_mr_description(...)` in `create_mr_for_task`, call same `build_impact_report_section` + `append_impact_report` with `compare=branch_name`, `base_ref=target_branch or repository.default_branch`. Prefer async append at create site (not inside pure `build_mr_description`) so the pure formatter stays sync-safe.

```python
# Source: mr_service.py:152-163
title = build_mr_title(task.name)
description = build_mr_description(feishu_url, feishu_title, tech_summary, modified_files)
# Phase 124: append impact section (same helper as AICodingNode / MCP)
```

**User for ACL:** task owner / workflow triggered_by if available; else stub.

---

### `server/friday/settings.py` (config)

**Analog:** `CODE_GRAPH_BUILD_WAIT_TIMEOUT_SECONDS` (lines 919–921).

```python
CODE_GRAPH_BUILD_WAIT_TIMEOUT_SECONDS: int = env.int(
    "CODE_GRAPH_BUILD_WAIT_TIMEOUT_SECONDS", default=30
)
# Add beside the CODE_GRAPH_* family:
CODE_GRAPH_IMPACT_REPORT_TIMEOUT_SECONDS: float = env.float(
    "CODE_GRAPH_IMPACT_REPORT_TIMEOUT_SECONDS", default=30.0
)
CODE_GRAPH_IMPACT_REPORT_MAX_CHARS: int = env.int(
    "CODE_GRAPH_IMPACT_REPORT_MAX_CHARS", default=10240
)
```

No product kill-switch (D-13).

---

### `task/tests/test_detect_changes_prompt.py` (test) — NEW

**Analog:** `task/tests/test_openspec_prompt.py` (full file pattern).

```python
# Source: task/tests/test_openspec_prompt.py:14-42
def _runner(follow_openspec: bool) -> ClaudeRunner:
    config = MagicMock()
    config.follow_openspec = follow_openspec
    return ClaudeRunner(config, Path("/tmp"))

def test_prompt_appends_openspec_when_true() -> None:
    prompt = _runner(True)._get_system_prompt()
    assert "openspec" in prompt
```

Extend MagicMock with `knowledge_endpoint`, `user_token`, `task_mode`; assert keywords (`detect_changes`, 自查/影响面); assert explore / empty knowledge → no append; assert `_detect_changes_guidance` independent helper.

---

### `task/tests/test_knowledge_tools.py` + count tests (test)

**Analog:** same files — bump 10→11 and add name literal.

```python
# Source: test_blueprint_context_tools_schema.py:64-72
assert len(KNOWLEDGE_TOOL_SCHEMAS) == 10  # → 11
assert len(knowledge_allowed_tools()) == 10  # → 11
# + assert "detect_changes" in names / allowed
```

Also update: `test_claude_sdk_integration.py:330`, `test_blueprint_context_wait.py:417-418`, `EXPECTED_TOOL_NAMES` / `_NEW_*` lists in `test_knowledge_tools.py`. Assert schema `required == ["repository_id", "compare"]`.

---

### `server/tests/services/code_graph/test_impact_report.py` (test) — NEW

**Analogs:** envelope fixtures from Phase 123 orchestrator tests; observability style from `code_graph` tests.

Cover:
- fixture envelope → four headings `## 影响面` / `### Changes|Affected|Risk|Recommendations`
- `ok=False` / timeout / `GraphAccessDenied` → stub with stable `error_code`, no raise
- soft max chars + `truncated` note; no source bodies
- `append_impact_report` idempotent on marker
- observability event names static / `component=code_graph` / `category=caller`

Mock `run_detect_changes` at the orchestrator boundary (do not retest diff/BFS).

---

### `server/tests/workflows/test_coding_impact_report.py` (test) — NEW

**Analog:** `server/tests/workflows/test_coding_pr_target_branch.py` (direct `_create_mr_for_repo`).

```python
# Source: test_coding_pr_target_branch.py:55-81
async def _call_create_mr(...):
    node = AICodingNode()
    with (
        patch("workflows.nodes.ai.coding.aresolve_git_token", _fake_token),
        patch("workflows.nodes.ai.coding.get_git_platform_client", get_client_mock),
    ):
        result = await node._create_mr_for_repo(...)
```

Add patch of `build_impact_report_section` / `run_detect_changes`: failure still calls `create_merge_request`; `description` contains stub or full section; no exception bubbles.

---

### `server/tests/mcp_tools/test_mr_impact_report.py` (test) — NEW

**Analogs:**
- MCP MR path: `server/tests/mcp_tools/test_mr_tools.py` (`FakeGitClient`, create flow)
- Parity sentinel spirit: `server/tests/mcp_tools/test_detect_changes_tools.py:207-218` (D-14 adapted to MR dual-path)

```python
# Source: test_detect_changes_tools.py:215-218 — adapt to workflow vs MCP section parity
"""同一 (repo, compare) fixture 下，workflow 拼装段与 MCP 拼装段规范化后一致。"""
# test_workflow_mcp_impact_section_parity
# Both call build_impact_report_section — assert identical section string / stub text
```

Also: explicit description without marker gets append; with marker no double section; draft+create path idempotent.

## Shared Patterns

### Fail-soft MR description append
**Source:** `server/workflows/services/pr_cross_reference.py:109-111`, `:197-204`  
**Apply to:** `impact_report.py`, `coding.py::_create_mr_for_repo`, `merge_request_service.py`, `mr_service.py`

```python
except Exception as exc:  # noqa: BLE001 — fail-soft，绝不阻塞收尾
    logger.warning("...", error=str(exc))  # 或 pass 若 helper 已记日志
    return ""  # / omit section
```

### Shared orchestration (no shell fork)
**Source:** `server/services/code_graph_tools.py:1056-1082` (`run_detect_changes` 唯一编排)  
**Apply to:** only `impact_report.build_impact_report_section`  
Shells must not reimplement impact/diff.

### Dual-path parity sentinel
**Source:** `server/tests/mcp_tools/test_detect_changes_tools.py:207-218` (MCP↔chat)  
**Apply to:** workflow↔MCP MR description sections via same helper (D-14).

### Observability (caller lifecycle)
**Source:** `server/services/code_graph_tools.py:1100-1138`  
**Apply to:** `impact_report.py`  
- Events: `impact_report_started` / `_completed` / `_failed`  
- Fields: `component="code_graph"`, `category="caller"`, `duration_ms`, `repository_id`, `section_chars`, `error_code`, **`initiated_by_user_id`**（`str(user.id)` 或 `"system"`）  
- `except: pass` around log emits; `redact_secrets_in_text` on error strings  
- Hook-site components may also log with `workflows` / `mcp_tools` if needed

### Risk level display
**Source:** `server/services/code_graph/impact.py:166-176`  
**Apply to:** Risk section renderer — map lowercase enum → `LOW|MEDIUM|HIGH|CRITICAL` for MR markdown.

### Task whitelist growth discipline
**Source:** `task/tests/test_blueprint_context_tools_schema.py:64-72`  
**Apply to:** all task count assertions 10→11; keep legacy name lists; add `detect_changes` literal.

### Prompt conditional append
**Source:** `task/core/executor.py:1034-1052` + `task/tests/test_openspec_prompt.py`  
**Apply to:** `_detect_changes_guidance` + knowledge+mode gate.

### Settings env family
**Source:** `server/friday/settings.py:919-921`  
**Apply to:** `CODE_GRAPH_IMPACT_REPORT_TIMEOUT_SECONDS` / `MAX_CHARS`.

## No Analog Found

| File | Role | Data Flow | Reason |
|------|------|-----------|--------|
| — | — | — | All Phase 124 files have strong in-repo analogs |

## Freeze / Anti-Pattern Reminder

| Forbidden | Why |
|-----------|-----|
| Edit `mcp/` submodule | D-16 / 122 D-27 |
| Edit `repo_router_v2.py` | Frozen until Phase 125 MOD-04 |
| Edit `runner.py` commit/push for hard gate | D-04 |
| Duplicate markdown render in workflow vs MCP shells | D-14 |
| Product kill-switch for impact report | D-13 |
| Put stack traces / tokens / absolute paths in MR body | D-11 + logging rules |

## Metadata

**Analog search scope:** `task/core/`, `task/tests/`, `server/services/code_graph*`, `server/workflows/nodes/ai/coding.py`, `server/workflows/services/`, `server/mcp_tools/`（含 `views.py` / `work_item_execution_service.py`）, `server/friday/settings.py`, `server/tests/{workflows,mcp_tools,services/code_graph}/`  
**Files scanned:** ~27 primary + test analogs  
**Pattern extraction date:** 2026-08-10
