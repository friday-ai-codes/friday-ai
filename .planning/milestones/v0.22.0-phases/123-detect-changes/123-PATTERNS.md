# Phase 123: detect_changes 工具本体 - Pattern Map

**Mapped:** 2026-08-10
**Files analyzed:** 15
**Analogs found:** 15 / 15

## File Classification

| New/Modified File | Role | Data Flow | Closest Analog | Match Quality |
|-------------------|------|-----------|----------------|---------------|
| `server/services/code_graph/detect_changes.py` | service (pure kernel) | transform | `server/services/code_graph/impact.py` | exact |
| `server/services/repo_mirror.py` (`diff_mirror` / `ensure_mirror_sha`) | service | file-I/O | `server/services/repo_mirror.py` (`ensure_mirror_commit` / `_run_git` / pin fetch) | exact |
| `server/services/code_graph_tools.py` (`run_detect_changes`) | service | request-response | `server/services/code_graph_tools.py` (`run_impact`) | exact |
| `server/mcp_tools/views.py` (`DetectChangesView`) | controller | request-response | `server/mcp_tools/views.py` (`ImpactAnalysisView`) | exact |
| `server/mcp_tools/urls.py` | route | request-response | `server/mcp_tools/urls.py` (impact/trace paths) | exact |
| `server/mcp_tools/serializers.py` (+ `TOOL_SCHEMAS`) | utility | request-response | `ImpactAnalysisRequestSerializer` + `TOOL_SCHEMAS["impact_analysis"]` | exact |
| `server/agents/tools/graph_tools.py` (`detect_changes`) | component (tool shell) | request-response | `server/agents/tools/graph_tools.py` (`impact_analysis`) | exact |
| `server/agents/tools/schemas/graph_tools.py` | utility | request-response | `ImpactAnalysisToolInput` | exact |
| `server/agents/tools/__init__.py` | config | request-response | same file (`impact_analysis` export) | exact |
| `server/agents/chat_runner.py` | config | request-response | same file (`_INDEXED_TOOL_NAMES`) | exact |
| `server/tests/services/code_graph/test_detect_changes.py` | test | transform | `server/tests/services/code_graph/test_impact.py` | exact |
| `server/tests/services/code_graph/test_detect_changes_orchestrator.py` | test | request-response | `server/tests/services/code_graph/test_impact_shell.py` | exact |
| `server/tests/services/test_diff_mirror.py` | test | file-I/O | indexer rename parsing + bare-repo fixture patterns | role-match |
| `server/tests/mcp_tools/test_detect_changes_tools.py` | test | request-response | `server/tests/mcp_tools/test_impact_trace_tools.py` | exact |
| rename classification reference | utility | transform | `server/services/indexer.py` (`_parse_git_diff_output` / `DiffAction.RENAME`) | role-match |

## Pattern Assignments

### `server/services/code_graph/detect_changes.py` (service, transform)

**Analog:** `server/services/code_graph/impact.py`

**Imports / zero-ORM discipline** (lines 58–77):
```python
from __future__ import annotations

import time
from collections import deque
from collections.abc import Mapping
from dataclasses import dataclass
from enum import Enum
from types import MappingProxyType
from typing import TYPE_CHECKING, Any, Final

import structlog

from services.code_graph import EdgeConfidence, EdgeKind, confidence_score, derive_reason

if TYPE_CHECKING:
    import networkx as nx

logger = structlog.get_logger(__name__)
```

**Core pattern — pure kernel, structured dict out, no GraphError swallow** (docstring boundaries ①–⑥, lines 32–55):
- 零 I/O、零 Django、零 ORM；只吃已解析结构 + 内存 symbol records
- 输出结构化 dict，渲染留给壳层
- 不吞错误；「空结果」与「查询失败」分形
- 模块级常量 `Final` + `structlog`；高频循环用 `category="sampling"` + DEBUG

**Rename classification reference** — `server/services/indexer.py` lines 639–661（对照 R*；detect_changes 走 unified hunk，但 RENAME 单条逻辑映射纪律相同；⚠️ 注意 indexer 对 similarity≠100 拆 D+A，而 D-06 要求纯 rename / 内容变更 rename 均 `changeType=renamed` 单条，**不得照抄 D+A 拆分**）:
```python
def _parse_git_diff_output(output: str) -> list[FileDiff]:
    """解析 git diff --name-status --find-renames 输出为 FileDiff 列表。"""
    diffs: list[FileDiff] = []
    for line in output.strip().split("\n"):
        if not line.strip():
            continue
        parts = line.split("\t")
        status_code = parts[0]
        # ...
        elif status_code.startswith("R"):
            old_path, new_path = parts[1], parts[2]
            similarity = int(status_code[1:]) if len(status_code) > 1 else 100
            if similarity == 100:
                diffs.append(FileDiff(new_path, DiffAction.RENAME, old_path=old_path))
            else:
                # 内容变更的 rename：拆为 DELETE + ADD  ← detect_changes 禁止照抄此分支
                diffs.append(FileDiff(old_path, DiffAction.DELETE))
                diffs.append(FileDiff(new_path, DiffAction.ADD))
    return diffs
```

**Barrel 纪律** — `server/services/code_graph/__init__.py` lines 31–33 / 92–110：
- `impact` / `trace` **不**进 `__all__` barrel；包外用 `import services.code_graph.detect_changes` 或经 `code_graph_tools` 编排
- ⛔ 不要把 `detect_changes` 塞进 17 项 barrel

---

### `server/services/repo_mirror.py` (`diff_mirror` / `ensure_mirror_sha`) (service, file-I/O)

**Analog:** same file — `MirrorError` / `MirrorSnapshot` / `_run_git` / `ensure_mirror_commit` pin path

**Error + snapshot types** (lines 61–78):
```python
class MirrorError(Exception):
    """镜像不可用 / 调用非法。code 对齐 MCP error_response。"""

    def __init__(self, code: str, detail: str) -> None:
        super().__init__(detail)
        self.code = code
        self.detail = detail


@dataclass(frozen=True)
class MirrorSnapshot:
    repository_id: str
    repo_dir: Path
    commit_sha: str
    ref: str
    matches_index: bool
```

**`_run_git` + scrub** (lines 81–83, 157–177):
```python
def _scrub(text: str) -> str:
    return _CREDENTIAL_URL_RE.sub("://***@", text)

async def _run_git(
    args: list[str],
    *,
    cwd: Path | None = None,
    proxy_url: str | None = None,
    timeout: float = _GIT_TIMEOUT_SECONDS,
    max_output_bytes: int | None = None,
) -> tuple[int, bytes, bytes]:
    from repositories.views import _build_git_env
    cmd: list[str] = ["git"]
    if proxy_url:
        cmd.extend(["-c", f"http.proxy={proxy_url}"])
    cmd.extend(args)
    return await _run_cmd(
        cmd, cwd=cwd, env=_build_git_env(proxy_url),
        timeout=timeout, max_output_bytes=max_output_bytes,
    )
```

**Pin base to `last_indexed_commit_sha`** (lines 244–288) — D-01 关键语义；`diff_mirror` 左端必须来自这次 pin:
```python
indexed_sha = str(params["last_indexed_commit_sha"] or "")
pin_sha = indexed_sha if (ref == base_ref and _SHA_RE.match(indexed_sha)) else ""
# ...
if pin_sha:
    rc, _, _ = await _run_git(
        [*fetch_base, f"+{pin_sha}:{_local_ref_for(f'pin-{pin_sha[:12]}')}"],
        cwd=repo_dir,
        proxy_url=proxy_url,
    )
```

**`ensure_mirror_sha` 形态** — 复用上段 `+{sha}:refs/friday/pin-…`；勿走 `refs/heads/{ref}`（纯 sha 会失败）。

**`diff_mirror` 形状**（RESEARCH 推荐；复用 `_run_git`，rc∈{0,1} 成功）:
```python
rc, out, stderr = await _run_git(
    ["diff", "--unified=0", "--find-renames", base.commit_sha, head.commit_sha],
    cwd=base.repo_dir,
    timeout=timeout,
    max_output_bytes=16 * 1024 * 1024,
)
if rc not in (0, 1):
    raise MirrorError(
        "mirror_fetch_failed",
        f"git diff 失败: {_scrub(stderr.decode(errors='replace'))[:300]}",
    )
```

**Mirror 错误在 MCP 壳的翻译** — `views.py` lines 211–216 / Grep 用法 763–787（编排层宜折成 `ok=False` + `error_code=MirrorError.code`，保证双面同形；MCP 也可 catch 后 `_mirror_error_response`，但 RESEARCH 推荐编排层折信封）:
```python
def _mirror_error_response(exc: MirrorError) -> Response:
    return error_response(
        exc.code,
        exc.detail,
        status_code=_MIRROR_ERROR_STATUS.get(exc.code, status.HTTP_400_BAD_REQUEST),
    )
```

---

### `server/services/code_graph_tools.py` (`run_detect_changes`) (service, request-response)

**Analog:** `run_impact` (lines 739–897) + helpers `staleness_payload` / `degradation_payload` / `graph_error_to_tool_error` / `fetch_graph_for_tool` / `_exclusion_matcher_for_repo`

**ACL-first + envelope** (lines 792–897):
```python
await _code_graph_access().ensure_repository_readable(user, repository_id)
# ... resolve / fetch / kernel ...
return {
    "ok": True,
    "tool": "impact_analysis",
    "repository_id": str(repository_id),
    "branch": _branch_label(repo, graph_branch),
    "seed": seed,
    # ... domain fields ...
    "affected_processes": [],
    "staleness": await staleness_payload(repo),
    "graph": degradation_payload(graph.meta),
}
```

**Hard-reject translation discipline** (lines 218–248) — D-03：⛔ 不得 catch `GraphError` 成空 affected:
```python
def graph_error_to_tool_error(exc: GraphError) -> tuple[str, str]:
    # 按 MRO 查 GRAPH_ERROR_MESSAGES；文案只取常量 + exc.message
    # 不得把 str(exc) / details 直出
```

**Staleness** (lines 308–356) — 请求路径不起 git；`as_of = repo.last_indexed_commit_sha`:
```python
async def staleness_payload(repo: Any) -> dict[str, Any]:
    from repositories.freshness_service import compute_freshness_status
    status = compute_freshness_status(repo)
    as_of = repo.last_indexed_commit_sha or ""
    behind = repo.behind_commits
    # ... declaration ...
    return {
        "as_of": as_of,
        "freshness": status,
        "behind_commits": behind,
        "behind_commits_calculated_at": (...),
        "declaration": declaration,
    }
```

**Exclusion matcher** (lines 446–454):
```python
async def _exclusion_matcher_for_repo(repository_id: str):
    from services.exclusion import build_matcher_for_repo
    return await build_matcher_for_repo(str(repository_id))
```

**Batch impact call shape** (D-09/D-10) — 顺序 for-loop，种子一律 `symbol_id`，`graph_branch=None`:
```python
one = await run_impact(
    repository_id=repository_id,
    repo=repo,
    graph_branch=None,  # base 图；交叠坐标同源
    user=user,
    symbol_id=sid,
    max_depth=3,
    min_confidence=1.0,
    include_low_confidence=False,
    limit=200,
)
```

**Fail-soft per seed** (D-12):
```python
except GraphError as exc:
    code, msg = graph_error_to_tool_error(exc)
    impacts.append({"symbol_id": sid, "impact_error": code, "unavailable_reason": msg})
```

**`tool_trace_payload`** (lines 1090–1190) — 扩 `detect_changes` 分支：只计数（affected 文件数 / 符号数 / impacts 成功失败数 / truncated），⛔ 不落符号名/路径正文。

---

### `server/mcp_tools/views.py` (`DetectChangesView`) (controller, request-response)

**Analog:** `ImpactAnalysisView` lines 1286–1392

**Core thin-shell pattern:**
```python
class ImpactAnalysisView(McpToolView):
    tool_name = "impact_analysis"

    async def post(self, request: Request) -> Response:
        run, err = await self._begin(request)
        if err is not None:
            return err
        input_data, err = await self._validate(ImpactAnalysisRequestSerializer, request)
        if err is not None:
            return err
        repository_id = str(input_data["repository_id"])
        repo, err = await self._get_indexed_repo(repository_id)
        if err is not None:
            return err

        from services.code_graph import GraphError
        from services.code_graph_tools import run_impact, tool_trace_payload

        try:
            result = await run_impact(...)
        except GraphError as exc:
            return _graph_error_response(exc)

        output_data = {**result, "run_id": str(run.run_id)}
        traces = [(RetrievalTrace.Kind.EDGE, tool_trace_payload(result, tool=self.tool_name, ...))]
        await self._record(run, input_data=input_data, output_data=output_data, traces=traces, ...)
        # caller 事件 best-effort try/except pass
        return Response(output_data, status=status.HTTP_200_OK)
```

**Indexed-repo gate** (lines 385–403) — `_get_indexed_repo` 复用；空 `last_indexed_commit_sha` 的硬拒可在编排层补 `repository_not_indexed`。

**DetectChanges 差异点（相对 impact）:**
- 参数：`compare`（必填）+ 可选 `base_ref`；**不要**复用 `branch` 作图 overlay（D-02 / RESEARCH Open Q2）
- 不调 `resolve_tool_graph_branch` 换交叠坐标；可选声明透出即可
- `ok=False` 仍 HTTP 200（与 impact 一致）

---

### `server/mcp_tools/urls.py` + `serializers.py` (route / utility)

**Analog:** urls lines 61–62; serializers `ImpactAnalysisRequestSerializer` 191–213 + `TOOL_SCHEMAS["impact_analysis"]` 1146–1179

**URL:**
```python
path("tools/impact_analysis/", ImpactAnalysisView.as_view(), name="mcp-tool-impact-analysis"),
path("tools/trace_call_path/", TraceCallPathView.as_view(), name="mcp-tool-trace-call-path"),
# → path("tools/detect_changes/", DetectChangesView.as_view(), name="mcp-tool-detect-changes"),
```

**Serializer 同表纪律** — 上下界与对话 pydantic 必须同表；`TOOL_SCHEMAS["detect_changes"]` 增键后接受 mcp 包漂移 +1（D-27）。

---

### `server/agents/tools/graph_tools.py` + schemas (component, request-response)

**Analog:** `impact_analysis` @tool + `_impact_analysis_impl` (lines 239–438) + `ImpactAnalysisToolInput`

**Registration comment** (lines 5–8) — 注册 ≠ 暴露，必须同时挂 `chat_runner._INDEXED_TOOL_NAMES`。

**Shell pattern:**
```python
@tool(name="impact_analysis", description=_DESC_IMPACT, category=ToolCategory.PROJECT.value, parameters=_PARAMS_IMPACT)
async def impact_analysis(...) -> ToolResult:
    # ValidationError / Exception → success=False + redact
    # 编排 ok=False → success=True，信封里的 ok 才是查询结论

async def _impact_analysis_impl(...) -> ToolResult:
    user = await _resolve_conversation_user(conversation_id)  # fail-closed 第一步
    validated = ImpactAnalysisToolInput(...)
    repo, err_code = await _resolve_tool_repo(validated.repository_id)
    try:
        result = await run_impact(..., user=user, ...)
    except GraphError as exc:
        code, message = graph_error_to_tool_error(exc)
        return ToolResult(success=False, error=message)
    await _record_chat_retrieval(RetrievalTrace.Kind.EDGE, tool_trace_payload(...), ...)
    return ToolResult(success=True, output={"data": result, "metadata": {...}})
```

**Pydantic schema** (`schemas/graph_tools.py` lines 15–83):
```python
class ImpactAnalysisToolInput(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid", frozen=True)
    # Field ge/le 与 MCP serializer 同表
```

**Whitelist** — `agents/tools/__init__.py` import + `__all__`；`chat_runner.py` lines 104–105 旁加 `"detect_changes"`。

---

### Tests

| New test file | Analog | Copy |
|---------------|--------|------|
| `test_detect_changes.py` | `test_impact.py` | 零 DB；纯字符串/结构 fixture；模块 docstring 写明「不得引入 django_db」 |
| `test_detect_changes_orchestrator.py` | `test_impact_shell.py` | `pytest.mark.django_db`；mock mirror / spy `run_impact`；硬拒 / 阈值 / `base_ref` 不改 argv |
| `test_diff_mirror.py` | pin/`_run_git` + indexer rename | 临时 bare repo：`git init` + 两 commit + rename + format；断言 argv 含 `--find-renames` / `--unified=0` |
| `test_detect_changes_tools.py` | `test_impact_trace_tools.py` | `pytestmark = django_db`；`_reset_code_graph_state` autouse；`test_two_surfaces_same_payload` 变体（成功 + 硬错误）；⛔ 不许 mock `run_detect_changes` |

**双面哨兵核心** (`test_impact_trace_tools.py` 301–359):
```python
mcp_data = {k: v for k, v in mcp_body.items() if k != "run_id"}
tool_result = await impact_analysis(**payload, conversation_id=str(conversation.id))
tool_data = tool_result.output["data"]
_assert_surfaces_byte_equal(mcp_data, tool_data)
```

## Shared Patterns

### Dual-surface thin shell (D-13 / 122 D-21)
**Source:** `ImpactAnalysisView` + `impact_analysis` @tool + `run_impact`
**Apply to:** MCP `DetectChangesView` + 对话 `detect_changes`
- 唯一编排入口 `run_detect_changes`
- 壳内零算法；MCP 加 `run_id`；对话 `output["data"]` 原样透出
- `ok=False` → MCP HTTP 200；对话 `success=True`（工具故障才 `success=False`）

### Envelope: ok / error_code / staleness / degradation
**Source:** `code_graph_tools.run_impact` return + `staleness_payload` / `degradation_payload`
**Apply to:** `run_detect_changes` 成功态必含 `staleness` + `graph`（数值 `resolution_rate`）；另透 `diff_base_sha` / `diff_head_sha` / 可选 `base_ref`；`affected_processes: []`

### Auth / ACL
**Source:** `_code_graph_access().ensure_repository_readable`（编排）+ MCP PAT/`_begin` + 对话 `_resolve_conversation_user`
**Apply to:** 所有 detect_changes 入口；ACL 失败硬拒，不空清单

### Exclusion fail-closed
**Source:** `_exclusion_matcher_for_repo` / `build_matcher_for_repo`
**Apply to:** Symbol 批量加载后、交叠输出前；排除文件不得出现在 affected

### Observability
**Source:** impact MCP/chat completed events + LOGGING-SPEC
**Apply to:**
- `component="code_graph"`（内核/编排）；MCP 壳可用 `component="mcp_tools"`
- 工具入口 `category="caller"`：`code_graph_detect_changes_started|completed|failed` + `duration_ms`
- hunk 循环 `category="sampling"`：`code_graph_diff_parsed`
- `RetrievalTrace` 经扩后的 `tool_trace_payload`（计数 only）
- best-effort `try/except: pass`；凭证走 `_scrub` / `redact_secrets_in_text`

### Error handling matrix
| Failure | Shape |
|---------|--------|
| `GraphError` | 上抛 → 壳 `_graph_error_response` / `graph_error_to_tool_error` |
| 空 `last_indexed_commit_sha` / 未索引 | `ok=False`, `error_code=repository_not_indexed` |
| `MirrorError` | 编排折 `ok=False` + `error_code=<MirrorError.code>`（推荐）或 MCP `_mirror_error_response` |
| 单符号 impact 失败 | 条目 `impact_error`；整体仍 `ok=True` |
| behind 很大 | 仍 `ok=True` + 加强 `staleness.declaration` |

### Diff coordinate system (Phase-123 specific)
**Source:** RESEARCH Pattern 1–2 + `ensure_mirror_commit` pin
**Apply to:** 全部交叠与 batch impact
- two-dot `git diff A B`，左端 = `last_indexed_commit_sha`
- Symbol 查询 `branch_name=""`；`run_impact(..., graph_branch=None)`
- `base_ref` 只声明，不进 diff argv 左端

## No Analog Found

| File | Role | Data Flow | Reason |
|------|------|-----------|--------|
| — | — | — | 无；unified hunk 解析为本相位新纯函数，但模块纪律对齐 `impact.py`，rename 语义对照 `indexer._parse_git_diff_output`（勿照抄 D+A 拆分） |

## Metadata

**Analog search scope:** `server/services/code_graph/`, `server/services/code_graph_tools.py`, `server/services/repo_mirror.py`, `server/services/indexer.py`, `server/mcp_tools/`, `server/agents/tools/`, `server/agents/chat_runner.py`, `server/tests/services/code_graph/`, `server/tests/mcp_tools/`
**Files scanned:** ~25 primary + targeted greps
**Pattern extraction date:** 2026-08-10
