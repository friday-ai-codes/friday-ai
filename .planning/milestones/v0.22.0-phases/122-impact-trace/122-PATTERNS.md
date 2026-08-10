# Phase 122: impact / trace 工具面 - Pattern Map

**Mapped:** 2026-08-09
**Files analyzed:** 17（源码 11 + 测试 6 组）
**Analogs found:** 15 / 17（2 项无先例，见 `## No Analog Found`）

> 本文件**不重复** `122-RESEARCH.md`。RESEARCH 已给出 networkx 算法骨架、`McpToolView`
> 契约清单、四条机械守护与生产数据分布；本文件只回答一个问题：**每个新文件应该照抄
> 哪个现有文件的哪几行**，并把 RESEARCH 提出的三个重点（双面同源 / 跨仓一跳 /
> `behind_commits` 消费者）落到真实代码上。

---

## File Classification

| New/Modified File | Role | Data Flow | Closest Analog | Match |
|---|---|---|---|---|
| `services/code_graph/impact.py` (NEW) | kernel（纯函数） | transform（内存图遍历） | `services/code_graph/signature.py` | role-match（同包同形，非同算法） |
| `services/code_graph/trace.py` (NEW) | kernel（纯函数） | transform | `services/code_graph/signature.py` | role-match |
| `services/code_graph/symbol_resolve.py` (NEW) | kernel（解析器） | lookup | `loader.py::_resolve_by_file_and_name` + `_AMBIGUOUS`（loader.py:424-431） | partial（图内定位有，候选列表无） |
| `services/code_graph_tools.py` (NEW，壳共享编排) | service（ORM） | request-response 编排 | `knowledge/retrieval` + `knowledge/exposure` 双面共享对；`agents/tools/find_api_callers.py` | partial（见 §双面同源） |
| `mcp_tools/views.py` (+2 View) | controller | request-response | `ReverseLookupView`（views.py:1213-1261）+ `FindRelatedChunksView`（views.py:1077-1210） | exact |
| `mcp_tools/serializers.py` (+2 Serializer, +2 snapshot) | serializer/config | 输入校验 | `FindRelatedChunksRequestSerializer`（:158-189）/ `TOOL_SCHEMA_SNAPSHOT`（:985+） | exact |
| `mcp_tools/urls.py` (+2 path) | route | — | `urls.py:50-58` | exact |
| `agents/tools/graph_tools.py` (NEW，2 个 `@tool`) | controller（对话面） | request-response | `agents/tools/find_api_callers.py`（全文 213 行） | exact |
| `agents/tools/schemas/graph_tools.py` (NEW) | schema | 输入校验 | `agents/tools/schemas/api_tools.py`（被 find_api_callers 引用） | exact |
| `agents/tools/__init__.py` (MOD) | registry | — | `__init__.py:31-32, 76-78` | exact |
| `agents/chat_runner.py` (MOD) | config | — | `chat_runner.py:97-100` | exact |
| `tests/services/code_graph/conftest.py` (MOD) | test fixture | — | 同文件既有 4 个工厂 + autouse 重置钩子 | partial（合成冻结图 fixture 无先例） |
| `tests/services/code_graph/test_impact.py` / `test_trace.py` / `test_symbol_resolve.py` (NEW) | test（零 DB） | — | `tests/services/code_graph/test_model.py`（全文零 `django_db`） | exact |
| `tests/services/code_graph/test_cross_repo_hop.py` (NEW) | test（DB） | — | `tests/services/code_graph/test_loader.py::_make_cross_repo_call`（:102-154） | exact |
| `tests/services/code_graph/test_staleness.py` / `test_impact_shell.py` (NEW) | test（DB） | — | `tests/services/code_graph/test_access.py` + conftest `indexed_repo` | exact |
| `tests/mcp_tools/test_impact_trace_tools.py` (NEW) | test（DB） | — | `tests/mcp_tools/test_reverse_lookup_tool.py`（全文 149 行） | exact |
| `tests/agents/tools/test_graph_tools.py` (NEW) | test | — | `tests/agents/tools/test_knowledge_read_tools.py:39-48` | exact |

---

## Pattern Assignments

### `services/code_graph/impact.py` / `trace.py` (kernel, pure transform)

**Analog:** `server/services/code_graph/signature.py` —— 包内唯一的「纯函数模块」
（全同步、`__all__` 两项、模块级 `Final[str]` 事件常量、docstring 分
「问题背景 / 方案 / 边界与已知翻车点」三段）。⚠️ 它 import 了 Django settings；
impact/trace 按 D-01 **不能**跟这一点，只跟模块形状。

**模块骨架**（`signature.py:1-70`，逐段照抄结构）：

```python
"""内存图服务的**缓存有效性判据** —— 复合签名与 in-flight 边构建判定（Phase 121，GRAPH-02）。

问题背景
========
...

方案（同结构不同分量 + 一个独立的在途判定）
==========================================
...

边界与已知翻车点
================
① **两条边构建轨互相独立，必须都纳入**（121-CONTEXT D-02）。
"""

from __future__ import annotations

import hashlib
from datetime import timedelta
from typing import Any, Final

import structlog

logger = structlog.get_logger(__name__)

# 事件名常量（形态对齐 ``access.py`` / ``codegraph/lsp/volar_pool.py``）。
# ⚠️ 前缀不得缩写：``graph_build_*`` 已被 ``services/graph_builder.py`` 占用。
_EVENT_SIGNATURE_COMPUTED: Final[str] = "code_graph_signature_computed"
_EVENT_EDGE_BUILD_IN_FLIGHT: Final[str] = "code_graph_edge_build_in_flight"

__all__ = [
    "compute_signature",
    "detect_edge_build_in_flight",
]
```

包内 16 个事件常量全部是这个形状（`loader.py:90-92`、`cache.py:81-89`、
`signature.py:58-59`、`access.py:65-66`）——**一个都没有走 helper**。这不是巧合，
是 `test_observability_contract` 的直接后果（见下）。

**埋点调用形态**（`access.py:105-117`，本包里最短的一个完整埋点函数）：

```python
def _log_access_denied(*, repository_id: Any, reason: str, user: Any | None) -> None:
    """拒绝出口的结构化埋点。观测 best-effort —— 任何异常吞掉，绝不反噬主流程。"""
    try:
        logger.warning(
            _EVENT_ACCESS_DENIED,
            component="code_graph",
            category="sampling",
            repository_id=str(repository_id),
            reason=reason,
            initiated_by_user_id=_initiated_by(user),
        )
    except Exception:  # noqa: BLE001 — 观测失败绝不反噬业务（不是安全降级分支）
        pass
```

**异常文本脱敏**（`access.py:244-253`，`error=` 关键字的唯一合法写法）：

```python
    except Exception as exc:  # noqa: BLE001 — 整仓 fail-closed，见下方 raise
        try:
            logger.warning(
                _EVENT_MATCHER_FAILED,
                component="code_graph",
                category="sampling",
                repository_id=key,
                error=redact_secrets_in_text(str(exc))[:500],
                error_type=type(exc).__name__,
            )
        except Exception:  # noqa: BLE001 — 观测失败绝不反噬业务
            pass
```

**为什么必须逐字照抄这四件事**（`tests/services/code_graph/test_access.py:398-453`
用 `package_dir.glob("*.py")` 扫全包，新建模块自动进扫描）：

```python
    for source_path in sorted(package_dir.glob("*.py")):
        ...
        for call in _iter_logger_calls(tree):
            # ① 事件名必须能静态解析成 snake_case 字面量（不得拼变量）
            event = None
            if call.args:
                first = call.args[0]
                if isinstance(first, ast.Constant) and isinstance(first.value, str):
                    event = first.value
                elif isinstance(first, ast.Name):
                    event = constants.get(first.id)
            ...
            # ④ 前缀 code_graph_
            # ② component == "code_graph"（字面量）
            # ③ category  == "sampling"（字面量）
            # ⑤ error= 的 ast.unparse 必须含 "redact_secrets_in_text"
```

`elif isinstance(first, ast.Name): event = constants.get(first.id)` 就是模块级
`Final[str]` 常量被放行的那一行；任何包一层的 `_emit()` 都落进
`f"{where}:<unresolved> 事件名不是字符串字面量/模块级字面量常量"`。

**值对象形态**（`model.py:250-262`，frozen + slots + 「必填无默认」的理由写进 docstring）：

```python
@dataclass(frozen=True, slots=True)
class GraphMeta:
    """一张图的元数据——上层工具向用户/agent 声明「结果有多可信」的唯一依据。

    五个**标记类**字段（...）刻意设为必填、无默认值：漏透出会在 review 阶段
    暴露，而不是变成一次静默的错误结论。
    """
```

**阈值常量表 + 逐条解释**（D-15 的风险分级表照这个写，`model.py:193-224`）：

```python
# resolved / (resolved + bare_name) 低于该值时，图元数据置 low_resolution=True，
# 上层工具须在输出头部声明「本仓解析率偏低，影响面可能偏保守」。
#
# 2026-08-09 **已按生产库实测校准**（Plan 121-10，交付物 ...）：
#   p10=0.0762 / p50=0.1697 / p90=0.2426 ...
LOW_RESOLUTION_THRESHOLD: Final[float] = 0.10
```

⚠️ D-15/D-29 的阈值**没有**这段校准记录，docstring 必须反过来写明「未经真实数据
校准的初值」——照抄格式，不要照抄「已校准」的语气。

**取图必须经 barrel**（`cache.py:734-742` 是 `get_graph` 的实际入口，注意
`ensure_repository_readable` 在 `sync_to_async` 之前、每次都跑）：

```python
        await access.ensure_repository_readable(user, repository_id)
        return await sync_to_async(self._get_graph_sync)(
            str(repository_id),
            branch,
            include_low_confidence,
            _validated_seed_ids(seed_symbol_ids, repository_id=repository_id),
            _clamped_depth(depth),
            _initiated_by(user),
        )
```

---

### `services/code_graph/symbol_resolve.py` (kernel, lookup)

**Analog A（图内定位，可照抄语义）：** `loader.py:424-431` —— 本仓唯一的
「(file, name) → node」索引及其歧义哨兵：

```python
        # 同文件同名撞车 ⇒ 标歧义，两个消费者一律放弃解析（理由见 :data:`_AMBIGUOUS`）。
        # ⚠️ 节点本身照常入图，被放弃的只是「按名字反查到它」这条通路。
        name_key = (norm_path, name)
        if name_key in by_file_and_name:
            by_file_and_name[name_key] = _AMBIGUOUS
            ambiguous_name_count += 1
        else:
            by_file_and_name[name_key] = node_id
```

D-19 与它的关系：loader 遇歧义**放弃解析**（返回 `None`），Phase 122 遇歧义要
**返回候选列表**。语义相反但方向一致——两者都拒绝「静默取第一个」。

**Analog B（`signature` 不在节点属性上，候选列表必须 ORM 补取）：** `loader.py:354-356`

```python
    # ⚠️ 字段清单**不等于**节点属性来源：``signature``（TextField，数 KB）根本不取；
    #    ``chunk_id`` 取但**不进节点属性**——它只喂 :attr:`_SymbolNodeIndex.chunk_to_symbols`
    #    这个旁挂映射，节点属性仍恒 5 个。
```

节点属性恒 5 个（`loader.py:414-422`）：`name` / `symbol_type` / `file_path` /
`start_line` / `end_line`。候选条目要的 `signature` 只能在壳层
（`code_graph_tools.py`）补一次 `Symbol.objects.filter(id__in=…)`。

**⚠️ Anti-analog（**不要**照抄）：** `FindRelatedChunksView._resolve_source_chunk`
（views.py:1153-1210）是仓里唯一的「chunk_id / file_path / symbol_name 三选一解析器」，
形状很像，但它对重名的处理正是 D-19 明令禁止的：

```python
        symbol = (
            await Symbol.objects.filter(
                repository_id=repository_id,
                branch_name__in=branch_names,
                name__iexact=symbol_name,
                chunk_id__isnull=False,
            )
            .order_by("branch_name", "file_path", "start_line")
            .afirst()          # ⛔ 静默取第一个 —— D-19 的反面教材
        )
```

可照抄的只有它的两样东西：① `branch_names = ["", graph_branch] if graph_branch else [""]`
的分支口径；② 「三选一」在 Serializer 层用 `validate()` 强制（见下）。

---

### `services/code_graph_tools.py` (shared orchestrator, ORM)

这是本相位的**新层**（RESEARCH 建议、CONTEXT D-21 要求的「两面共用同一内核」的载体）。
四个片段各有分别的出处。

**① 跨仓一跳的 ORM 查询** —— Analog: `agents/tools/find_api_callers.py:146-188`
（仓里唯一的 `CrossRepoApiCall` 消费者，方向与 IMPACT-03 完全一致：
后端 handler → 前端调用点）：

```python
    # 步骤1：找对应的 endpoint(s)（同名 handler 可能有多个 endpoint）
    endpoint_ids = [
        ep_id
        async for ep_id in Endpoint.objects.filter(
            repository_id=repo_id,
            handler_name=validated.handler_name,
        ).values_list("id", flat=True)
    ]
    ...
    # 步骤2：CrossRepoApiCall → ApiCallSite（select_related 避 N+1）
    callers: list[CallerResult] = []
    async for cross_call in CrossRepoApiCall.objects.filter(
        endpoint_id__in=endpoint_ids,
    ).select_related("call_site", "call_site__api_wrapper"):
        cs = cross_call.call_site
        callers.append(
            CallerResult(
                caller_file=cs.caller_file,
                caller_function=cs.caller_function,
                line_number=cs.line_number,
                api_wrapper_symbol=cs.api_wrapper.function_symbol,
                match_confidence=cross_call.match_confidence,
            )
        )
    # 按 caller_file + line_number 排序，让结果稳定可读
    callers.sort(key=lambda c: (c.caller_file, c.line_number))
```

与 Phase 122 的三点差异（必须显式补上，`find_api_callers` 一条都没做）：
- 它**不按对端仓分组**，也**不 `.exclude(call_site__repository_id=local)`——
  同仓与跨仓混在一起返回。D-25 需要显式排除同仓行。
- 它**不做任何权限校验**（无 `user` 参数）。D-12 要求每穿一仓复核。
- `match_confidence` 它是原样透传的 ✅ —— 这一点照抄即可（D-13 同款）。

对照 `loader._load_cross_repo_edges`（loader.py:812-828）证明为什么必须走 ORM 而非图边：

```python
        caller_node = (
            _resolve_by_file_and_name(
                by_file_and_name, caller_file, caller_function, normalize_rel_path
            )
            if str(call_site_repository_id) == local_repository_id
            else None
        )
        callee_node = (
            _resolve_by_file_and_name(
                by_file_and_name, endpoint_file_path, handler_name, normalize_rel_path
            )
            if str(endpoint_repository_id) == local_repository_id
            else None
        )
        if caller_node is None or callee_node is None:
            unresolved_count += 1
            continue
```

loader.py:751-754 的注释把这笔账直接记给了本相位：

```python
    **对端仓的符号不在本图内**：本相位**不做多仓合并大图**（CONTEXT Area 1），跨仓
    impact 由 Phase 122 通过「按需再取对端仓的图」组合。
```

**② 多仓扇出 + 逐仓复核** —— Analog: `SearchRagChunksView`（views.py:525-542），
仓里唯一的「一次请求打多个仓、逐仓校验」形状：

```python
        # 逐仓校验：单仓失败保留旧 404/400 行为；多仓某仓不存在/未索引则跳过
        # （不越权、不致命），仅对通过校验的仓检索。
        repos: dict[str, Repository] = {}
        for repository_id in target_ids:
            repo, repo_err = await self._get_indexed_repo(repository_id)
            if repo_err is not None:
                if single_target:
                    return repo_err
                continue
            assert repo is not None
            repos[repository_id] = repo
```

🚨 **本相位必须在这里分叉**：`continue` 就是 D-12/D-14 明令禁止的「静默丢弃」。
Phase 122 的对应位置要产出两种显式条目——`REDACTED_REPOSITORY`（`GraphAccessDenied`，
且按 D-30 **不带** `affected_count`）与 `{"unavailable_reason": …}`（`GraphNotIndexed` /
`GraphBuildTimeout`）。可复用的只有「循环 + 逐仓取权限对象 + 单目标/多目标区别对待」
这个骨架。

真正的逐仓权限点仍是 `get_graph`（`cache.py:689-694` 的注释说明它为什么不能被缓存跳过）：

```python
        🚨 ``ensure_repository_readable`` 绝不因缓存命中而跳过。缓存键是
        ``(repository_id, branch, include_low_confidence)``，键本身不带用户维度——命中即
        返回意味着任何拿得到 ``repository_id`` 的调用方都能读到别人建好的图 ...
```

**③ staleness（D-22）** —— `Repository.behind_commits` 的**真实消费者**只有两处，
都不是「读来算」而是「读来透出」：

写入侧（唯一）`repositories/freshness_service.py:56-65`：

```python
    for repo in repos:
        if compute_freshness_status(repo) != "stale":
            continue
        try:
            count = await _calculate_commit_distance(repo)
            if count is not None:
                await Repository.objects.filter(id=repo.id).aupdate(
                    behind_commits=count,
                    behind_commits_calculated_at=timezone.now(),
                )
```

读出侧（唯一，且是 read-only 直出）`repositories/serializers.py:91-94, 118-121`：

```python
            # contract freshness 字段（contract/contract）
            "remote_head_sha",
            "remote_head_checked_at",
            "behind_commits",
            "last_indexed_commit_sha",
        ]
        read_only_fields = [
            ...
            "behind_commits",
```

三态判定照抄 `freshness_service.compute_freshness_status`（:25-40），⛔ 不要自己比 sha：

```python
def compute_freshness_status(repo: Repository) -> FreshnessStatus:
    """三态分级：FRESH / STALE / UNKNOWN（contract）。

    决策表：
      remote_head_sha 空 OR remote_head_checked_at None → unknown
      last_indexed_commit_sha 空 → unknown
      last_indexed_commit_sha == remote_head_sha → fresh
      其余 → stale
    """
```

⚠️ `_calculate_commit_distance` 在**本地无 clone 时返回 `None`**（:88-94），
`update_behind_commits_for_stale_repos` 只刷 `auto_index_enabled=True` 的仓
（:51-54）——D-22 的 `None` 降级分支是真实可达的，不是形式主义。

**④ GraphError → 工具文案的映射表（D-03）** —— Analog: `views.py:190-206`
（`MirrorError` 的同款映射，本仓唯一的「异常类 → 错误码 + HTTP 码」表）：

```python
_MIRROR_ERROR_STATUS = {
    "repository_not_found": status.HTTP_404_NOT_FOUND,
    "invalid_params": status.HTTP_400_BAD_REQUEST,
    "mirror_disabled": status.HTTP_400_BAD_REQUEST,
    ...
    "git_timeout": status.HTTP_502_BAD_GATEWAY,
}


def _mirror_error_response(exc: MirrorError) -> Response:
    return error_response(
        exc.code,
        exc.detail,
        status_code=_MIRROR_ERROR_STATUS.get(exc.code, status.HTTP_400_BAD_REQUEST),
    )
```

⚠️ `GraphError.details` 含 `estimated_bytes` / `max_graph_bytes`（`model.py:367-375`），
映射时只取 `exc.message`，⛔ 不把 `str(exc)` 直出（`__str__` 会拼上 details）。

---

### `mcp_tools/views.py` (+2 View)

**Analog（最短完整实现）：** `ReverseLookupView`（views.py:1213-1261）——
49 行、含 docstring、有 `RetrievalTrace`、无仓库闸：

```python
class ReverseLookupView(McpToolView):
    """片段→需求反查 MCP 工具（Phase 34 RREF-01）。

    与 REST `repositories.reverse_lookup_views.ReverseLookupView` 同形返回，复用
    `services.reverse_lookup.reverse_lookup`（纯读、fail-closed、默认当前视图）。
    鉴权沿用基类 AccessToken/CookieJWT + IsAuthenticated。
    """

    tool_name = "reverse_lookup_requirements"

    async def post(self, request: Request) -> Response:
        run, err = await self._begin(request)
        if err is not None:
            return err
        assert run is not None
        input_data, err = await self._validate(ReverseLookupRequestSerializer, request)
        if err is not None:
            return err
        assert input_data is not None
        started_at = time.perf_counter()

        from services.reverse_lookup import reverse_lookup      # ← 函数体内延迟 import

        result = await reverse_lookup(...)
        output_data = {**result, "run_id": str(run.run_id)}
        traces: list[tuple[str, dict[str, Any]]] = [
            (RetrievalTrace.Kind.EDGE, {"source": "reverse_lookup", **item})
            for item in result["related_work_items"]
        ]
        await self._record(
            run,
            input_data=input_data,
            output_data=output_data,
            traces=traces,
            started_at=started_at,
        )
        return Response(output_data, status=status.HTTP_200_OK)
```

**Analog（形状最接近图查询工具）：** `FindRelatedChunksView`（views.py:1080-1151）——
多了「仓库闸 + 分支解析 + 起点解析」三步，正是 impact/trace 需要的：

```python
        repository_id = str(input_data["repository_id"])
        repo, err = await self._get_indexed_repo(repository_id)
        if err is not None:
            return err
        assert repo is not None
        graph_branch, _collection_name = await self._resolve_graph_branch(
            repository_id, repo, input_data.get("branch")
        )
        source = await self._resolve_source_chunk(input_data, repository_id, graph_branch)
        if isinstance(source, Response):
            return source
        ...
        output_data = {
            "repository_id": repository_id,
            "branch": graph_branch or (repo.base_branch or repo.default_branch),
            "source": source,
            "related_chunks": related_chunks,
            "run_id": str(run.run_id),
        }
        traces = [(RetrievalTrace.Kind.EDGE, item) for item in related_chunks]
```

⚠️ `_resolve_graph_branch` 返回的 `graph_branch` 为 `None` 表示 base 分支，
传给 `get_graph` 时要转成 `""`（`get_graph` 的 `branch` 口径见 cache.py:719：
「`""` = base 分支（与 `Symbol.branch_name` 同口径）」）。

⚠️ `FindRelatedChunksView` 在输出前又过了一遍 `_exclusion_matcher`（views.py:1121-1135）。
Phase 122 **不要**照抄这一段：Phase 121 已在装配阶段过滤（`loader.py:393-403`），
输出阶段再过是多余的（RESEARCH `## Don't Hand-Roll` 已裁定）。

**逐条透出降级标记（D-23）** 的字段来源是 `GraphMeta`（`model.py:263-316`），
注释里已逐字标注哪些「上层工具必须透出」：`resolution_rate`（数值，必带）/
`low_resolution` / `partial_edges` + `partial_reason` / `degraded`（三个字面量：
`""` / `on_demand_subgraph` / `on_demand_subgraph_truncated`）/
`cross_repo_unresolved_count` / `cross_repo_branch_unfiltered` / `include_low_confidence`。

---

### `mcp_tools/serializers.py` (+2 Serializer, +2 snapshot)

**Analog:** `FindRelatedChunksRequestSerializer`（serializers.py:158-189）——
`UUIDField` + 带上下界的 `IntegerField` + `ChoiceField` + 跨字段 `validate()`：

```python
class FindRelatedChunksRequestSerializer(serializers.Serializer):
    repository_id = serializers.UUIDField(required=True)
    branch = serializers.CharField(required=False, allow_blank=True, allow_null=True, default=None)
    chunk_id = serializers.UUIDField(required=False, allow_null=True, default=None)
    file_path = serializers.CharField(required=False, allow_blank=True, default="")
    symbol_name = serializers.CharField(required=False, allow_blank=True, default="")
    hops = serializers.IntegerField(required=False, default=1, min_value=0, max_value=2)
    direction = serializers.ChoiceField(
        required=False, default="both", choices=("downstream", "upstream", "both")
    )
    limit = serializers.IntegerField(required=False, default=20, min_value=1, max_value=50)

    def validate(self, attrs: dict[str, object]) -> dict[str, object]:
        provided = [
            bool(attrs.get("chunk_id")),
            bool(str(attrs.get("file_path") or "").strip()),
            bool(str(attrs.get("symbol_name") or "").strip()),
        ]
        if sum(provided) != 1:
            raise serializers.ValidationError(
                "必须且只能提供 chunk_id、file_path、symbol_name 之一"
            )
```

`max_depth` / `min_confidence` / `limit` / `max_cross_repo_hops` 全部照这个写死上下界
（T-122-遍历 DoS 的第一道闸就在这里）。

**Snapshot 条目**（`serializers.py:985-1013`）：

```python
TOOL_SCHEMA_SNAPSHOT: dict[str, dict[str, object]] = {
    "route_repositories": {
        "request": ["query", "top_k"],
        "response": ["query", "ranked_repos", "total", "run_id"],
    },
```

**测试侧必须手写第二份字面量**（`tests/mcp_tools/test_schema_snapshot.py:7-8` 的注释是明令）：

```python
# 三个 feature 方案工具共用的响应键集。**刻意在测试里独立写一份字面量**——从
# serializers 导入同一个常量会让本守卫退化为自我比较，改错源码也照样绿。
```

以及 urls ↔ snapshot 的双向断言（`test_schema_snapshot.py:35-49`）：

```python
    from mcp_tools.urls import urlpatterns

    registered: set[str] = set()
    for p in urlpatterns:
        m = re.fullmatch(r"tools/([a-z0-9_]+)/", str(p.pattern))
        if m:
            registered.add(m.group(1))

    snapshot = set(TOOL_SCHEMA_SNAPSHOT)
    assert registered == snapshot, (...)
```

---

### `mcp_tools/urls.py` (+2 path)

**Analog:** `urls.py:51-58`（工具名 snake_case、route name 用 dash）：

```python
    path("tools/find_related_chunks/", FindRelatedChunksView.as_view(), name="mcp-tool-find-related-chunks"),
    path("tools/reverse_lookup_requirements/", ReverseLookupView.as_view(), name="mcp-tool-reverse-lookup-requirements"),
```

导入列表（`urls.py:5-48`）按字母序，新增两个 View 名要插进去。

---

### `agents/tools/graph_tools.py` (2 个 `@tool`)

**Analog:** `agents/tools/find_api_callers.py` —— 与本相位主题最近的对话工具
（同样吃 `repository_id`、同样查代码图、同样透传 `match_confidence`）。四段照抄：

**模块 docstring 声明注册路径**（:1-16）：

```python
"""``find_api_callers`` agent tool —— per implementation work item。
...
**注册路径**：通过 ``agents/tools/__init__.py`` 顶层 import 触发 ``@tool`` 注册。
"""
```

**描述与参数抽成模块级常量**（:37-68），描述里带 USE WHEN / DO NOT USE 决策树：

```python
_TOOL_DESCRIPTION = (
    "Given a backend handler function name, find all frontend business call sites ...\n"
    "USE WHEN you know the backend handler and want to trace who calls it from the frontend:\n"
    ...
    "DO NOT USE FOR finding the handler by URL — use `find_api_handler` instead."
)

_TOOL_PARAMETERS: dict[str, Any] = {
    "type": "object",
    "properties": {
        "repository_id": {
            "type": "string",
            "description": "**REQUIRED.** 后端仓库 UUID（handler 所在的 Go/Python 后端仓库）",
        },
    },
    "required": ["handler_name", "repository_id"],
}
```

**双层防御 + 永不冒泡**（:71-118 —— 装饰的函数只做日志与异常翻译，实现放 `_impl`）：

```python
@tool(
    name="find_api_callers",
    description=_TOOL_DESCRIPTION,
    category="PROJECT",
    parameters=_TOOL_PARAMETERS,
)
async def find_api_callers(
    handler_name: str | None = None,
    repository_id: str | None = None,
) -> ToolResult:
    logger.info("find_api_callers_called", handler_name=handler_name, repository_id=repository_id)
    try:
        return await _find_api_callers_impl(...)
    except (ValueError, TypeError, DjangoValidationError) as exc:
        logger.warning("find_api_callers_failed", error_type=type(exc).__name__, error=str(exc))
        return ToolResult(success=False, error=f"invalid input or downstream failure: {exc}")
    except ValidationError as exc:
        logger.warning("find_api_callers_failed", error_type="ValidationError", error=str(exc))
        return ToolResult(success=False, error=str(exc))
```

Phase 122 的 `except` 元组要多加 `GraphError`（D-03：翻译，不吞成空结果）。
⚠️ 这两处 `logger.warning(... error=str(exc))` **没有**过
`redact_secrets_in_text`——AST 守护只扫 `services/code_graph/*.py`，`agents/tools/`
不在其中，但 `.cursor/rules/observability-logging.mdc` 仍然要求脱敏。本相位新写的
对话壳按规范补上 `redact_secrets_in_text(str(exc))`，⛔ 不照抄这一处的疏漏。

**输出信封**（:199-210，`{"data": …, "metadata": …}` 两段式）：

```python
    return ToolResult(
        success=True,
        output={
            "data": output.model_dump(),
            "metadata": {
                "repository_id": repo_id,
                "handler_name": validated.handler_name,
                "endpoint_count": len(endpoint_ids),
                "caller_count": len(callers),
            },
        },
    )
```

**用户解析（对话面的权限来源）** —— Analog: `delivery_knowledge_tools.py:56-65, 116-118`：

```python
async def _resolve_conversation_user(conversation_id: str):
    if not conversation_id:
        return None
    try:
        conversation = await Conversation.objects.select_related("created_by").aget(
            id=conversation_id
        )
    except (Conversation.DoesNotExist, ValueError):
        return None
    return conversation.created_by

# 调用侧：
    user = await _resolve_conversation_user(conversation_id)
    if user is None:
        return ToolResult(success=False, error="无法解析会话 owner，拒绝检索（fail-closed）")
```

🚨 这条 fail-closed 对本相位是**硬要求**而不是可选：`get_graph(user=None)` 会走
「系统路径」（`access._initiated_by` 返回 `"system"`，`_check_user_acl` 空实现放行），
即拿不到会话 owner 时**不会**被拒。所以必须在工具入口先挡住 `user is None`。
`conversation_id` 参数由 chat_runner 注入，schema 里要声明
（`delivery_knowledge_tools.py:98-101`）。

**注册两处，缺一 LLM 看不见** —— `agents/tools/__init__.py:31-32 / 76-78`：

```python
from agents.tools.find_api_callers import find_api_callers
from agents.tools.find_api_handler import find_api_handler
...
    # API graph tools (implementation)
    "find_api_handler",
    "find_api_callers",
    "list_endpoints",
```

`agents/chat_runner.py:92-100`（注释本身就是「漏挂白名单」这笔债的现场记录）：

```python
    # 代码关系 / GraphRAG 游走：拿到具体起点（文件 / chunk / 符号）后沿
    # CALL / IMPORT / TEST_OF 等 chunk 级关系图遍历，补足 search_repository_code
    # 的 RAG 模糊检索拿不到的"调用方/被调用方/测试"等结构化关联。
    # 这些工具早已在 agents/tools/__init__.py 注册，此前漏挂进 chat 白名单导致
    # LLM 全程只能 RAG 搜索、无法利用 graph 能力。
    "find_related_code",
    "list_endpoints",
    "find_api_handler",
    "find_api_callers",
```

`impact` / `trace` 语义上属于同一簇，紧挨着这四个加即可。

---

### 测试文件

**零 DB 内核测试** —— Analog: `tests/services/code_graph/test_model.py`（全文无
`pytest.mark.django_db`，纯 import + AST 自省 + 值断言）。可直接照抄的两类断言：
「docstring 里必须写清理由」（`test_module_docstring_carries_cross_phase_disciplines`）
与「`__all__` 精选且有序」（`test_all_is_curated_and_sorted`）。

**合成冻结图 fixture** —— 现有 conftest 全是 DB 工厂（`indexed_repo` /
`branch_index` / `symbols_factory` / `call_edges_factory` / `exclusion_rule_factory`），
**没有**任何 networkx fixture。新 fixture 照 conftest 既有工厂的写法（模块级
`@pytest.fixture` + 闭包工厂 + docstring 写清「为什么这么造」），图本体照
RESEARCH `## Code Examples` §5 的 `known_topology()`。conftest 顶部的两条约定要遵守：

```python
约定：
- ORM 模型一律走**函数体内 lazy import**，避免 ``services`` 包在 Django app
  loading 早期触发模型导入 ...
- 分支语义两套、不可混用：``Symbol`` / ``CallEdge`` 的 ``branch_name=""`` 表示
  base；``RepositoryBranchIndex.branch_name`` 存**真实分支名** ...
```

autouse 重置钩子（conftest.py:151-182）已覆盖 `GraphService` 单例与两份 matcher memo，
**不需要**为本相位新增重置——除非内核引入模块级状态（建议不要）。

**跨仓 DB 测试** —— Analog: `tests/services/code_graph/test_loader.py::_make_cross_repo_call`
（:102-154），已经支持造**真跨仓**行，直接复用其形状（注意它要 4 个模型：
`ApiWrapper` → `ApiCallSite` → `Endpoint` → `CrossRepoApiCall`）：

```python
def _make_cross_repo_call(
    repository,
    *,
    caller_file: str,
    caller_function: str,
    endpoint_file: str,
    handler_name: str,
    match_confidence: float = 0.7,
    caller_line: int = 33,
    endpoint_repository=None,
):
    """造一条 ``CrossRepoApiCall`` 及其两端（``ApiCallSite`` / ``Endpoint``）。

    :param endpoint_repository: 端点所属仓库；缺省与 ``repository`` 同仓。传入**另一个
        仓库**即造出一条真正的跨仓行——两侧分属不同仓，正是 HI-01 要覆盖的形状。
    """
```

⚠️ 它定义在 `test_loader.py` 里而不是 conftest。本相位若要在
`test_cross_repo_hop.py` 复用，**移进 conftest**（跨模块 import 测试模块内的私有
helper 不是本仓做法）。

**MCP 壳测试** —— Analog: `tests/mcp_tools/test_reverse_lookup_tool.py`（149 行，
四个用例正好覆盖 IMPACT-06 要求的四条）：

```python
pytestmark = pytest.mark.django_db

URL = "/api/mcp/tools/reverse_lookup_requirements/"


def test_reverse_lookup_tool_unauthenticated(indexed_repository) -> None:
    client = APIClient()
    response = client.post(URL, {...}, format="json")
    assert response.status_code == 401
    assert response.json()["error_code"] == "authentication_failed"


def test_reverse_lookup_tool_excluded_file_no_leak(
    mcp_client: tuple[APIClient, str],
    indexed_repository,
) -> None:
    client, _plaintext = mcp_client
    _build_chain(indexed_repository, file_path=".env")
    response = client.post(URL, {..., "file_path": ".env", ...}, format="json")
    assert response.status_code == 200
    body = response.json()
    assert body["chunks"] == []
```

fixtures `mcp_client` / `indexed_repository` 来自 `tests/mcp_tools/conftest.py:20-50`
（`mcp_client` 返回 `(APIClient, plaintext_token)` 二元组，已带 Bearer 头）。
最后一个用例正是 GRAPH-04 回填（「被排除文件不出现在 impact/trace 输出」）的现成模板。

**对话壳注册测试** —— Analog: `tests/agents/tools/test_knowledge_read_tools.py:39-48`：

```python
def test_tools_registered_and_whitelisted() -> None:
    from agents.chat_runner import _INDEXED_TOOL_NAMES, _PROJECT_READ_TOOL_NAMES

    assert "search_learning_cases" in _INDEXED_TOOL_NAMES
    assert {"search_project_context", "read_project_doc"} <= set(_PROJECT_READ_TOOL_NAMES)
    assert {
        "search_learning_cases",
        "search_project_context",
        "read_project_doc",
    } <= set(_tool_registry)
```

---

## Shared Patterns

### 双面同源（D-21）—— **有半个先例，本相位要补齐另一半**

**Source:** `search_delivery_knowledge` 这一对：
`SearchDeliveryKnowledgeView`（views.py:2582-2659）与
`@tool search_delivery_knowledge`（delivery_knowledge_tools.py:106-168）。

**共享的部分（可照抄）：** 两面都调**同一个 service 单例**与**同一个序列化器**，
产出的四个数据键逐字相同：

```python
# MCP 侧（views.py:2605-2634）
results = await _delivery_knowledge_service.search_similar(
    str(input_data["query"]), user=request.user, top_k=..., include_document_kind=True,
)
serialized = serialize_search_results(results)
output_data = {
    "query": str(input_data["query"]),
    "results": serialized,
    "total": len(serialized),
    "as_of": as_of.isoformat() if as_of else None,
    "run_id": str(run.run_id),        # ← 只有 MCP 面多这一个键
}

# 对话侧（delivery_knowledge_tools.py:142-168）
results = await _service.search_similar(
    validated.query, user=user, top_k=validated.top_k, include_document_kind=True,
)
serialized = serialize_search_results(results)
return ToolResult(success=True, output={
    "query": validated.query,
    "results": serialized,
    "total": len(serialized),
    "as_of": as_of_dt.isoformat() if as_of_dt else None,
})
```

**没有共享的部分（正是 D-21 要防的漂移，本相位必须做得更好）：**

1. **没有共享编排函数**——两侧各自手写 `search_similar(...)` 的七个关键字参数，
   连 `include_document_kind=True` 那段五行注释都是复制粘贴的两份（views.py:2614-2616
   与 delivery_knowledge_tools.py:151-153）。加一个参数就要改两处。
2. **失败语义已经漂移**：MCP 面把检索异常 fail-soft 成空结果（`results = []` +
   `mcp_vector_search_degraded` 埋点，views.py:2618-2626）；对话面同样的异常直接
   `ToolResult(success=False, error=f"检索失败: {exc}")`（:156-158）。同一个故障，
   一面报「没有结果」、一面报「工具坏了」。
3. **用户来源不同且无共同抽象**：`request.user` vs `_resolve_conversation_user()`。
4. **没有任何测试断言两面一致**（全仓无此类用例）。

**Apply to:** `services/code_graph_tools.py` 的
`async def run_impact(repository_id, symbol, *, user, …) -> dict` /
`run_trace(...)`。两个壳各自只做「校验 → 调它 → 渲染 → 留痕」，
`user` 作为显式参数传入（把上面第 3 点收进函数签名），失败语义在编排层裁决一次
（把第 2 点收口）。RESEARCH 的 Validation 表里那条
`test_two_surfaces_same_payload` 是本仓**第一条**此类守护——它没有先例可抄，
但它正是让「半个先例」变成完整范式的那一步。

### 权限：唯一收口点，⛔ 不在壳里自查

**Source:** `services/code_graph/access.py:134-180`（`ensure_repository_readable`
的四道判定），由 `cache.get_graph` 每次调用（`cache.py:734`）。

**Apply to:** 所有取图路径，包括跨仓一跳的每一个对端仓。

```python
    try:
        repo = await Repository.objects.aget(id=repo_uuid, is_deleted=False)
    except Repository.DoesNotExist:
        # 「不存在」与「已软删」共用同一句文案与同一个异常类型（不泄漏存在性差异）。
        _log_access_denied(repository_id=repository_id, reason="not_found_or_deleted", user=user)
        raise GraphAccessDenied("仓库不存在或已删除", {"repository_id": str(repository_id)}) from None

    if repo.index_status != IndexStatus.INDEXED:
        _log_access_denied(repository_id=repository_id, reason="not_indexed", user=user)
        raise GraphNotIndexed("仓库尚未建立索引", {...})
```

注意 MCP 壳的 `_get_indexed_repo`（views.py:363-381）做的是**同一组判定的 HTTP 版**
（404 `repository_not_found` / 400 `repository_not_indexed`）。本仓库（起点仓）走
`_get_indexed_repo` 拿 `Repository` 对象（staleness 要用），对端仓**只**走
`get_graph`——⛔ 不要为对端仓再查一次 `Repository`，那会绕过 `GraphAccessDenied`
的统一出口并制造存在性预言机。

### `@tool` 注册契约

**Source:** `agents/tools/base.py:134-160`

```python
    def decorator(func: Callable[P, R]) -> Callable[P, R]:
        # Validate that the function is async
        if not inspect.iscoroutinefunction(func):
            raise TypeError(f"Tool '{name}' must be an async function (use 'async def'). ...")

        # Check for duplicate registration
        if name in _tool_registry:
            raise ValueError(f"Tool '{name}' is already registered. ...")

        # Parse category
        try:
            tool_category = ToolCategory[category.upper()]
        except KeyError:
            ...
```

`ToolCategory`（base.py:19-32）可选值：`PROJECT` / `KNOWLEDGE` / `FEISHU` /
`SUBAGENT` / `GENERAL` / `RETRIEVAL` / `COMMUNICATION`。
`find_api_callers` / `list_endpoints` / `find_api_handler` 用的都是 `"PROJECT"`
——impact / trace 同簇，建议同档。

### MCP 错误信封

**Source:** `mcp_tools/errors.py:10-15`

```python
def error_response(error_code: str, detail: Any, *, status_code: int) -> Response:
    """返回 MCP tool 统一错误体。"""
    return Response({"error_code": error_code, "detail": detail}, status=status_code)
```

### 架构红线：新内核不进 `_INTERNAL_SUBMODULES`（Pitfall 4 的裁决依据）

**Source:** `tests/services/code_graph/test_access.py:545`

```python
# 上层直连即架构违规的四个内部子模块（``model`` 是纯契约层，从包根导出，不在此列）。
_INTERNAL_SUBMODULES = frozenset({"loader", "cache", "signature", "access"})
```

以及 barrel 的逐字断言（:476-524，`assert len(exported) == 17`）。D-28 选「不进
barrel」后，壳层写 `from services.code_graph.impact import analyze_impact` 合法；
但 `__init__.py` 的 docstring 要补一句说明这条边界——docstring 本身也有守护
（`test_barrel_docstring_records_the_architecture_red_line`，:613-624，断言 doc 里
含 "架构" 与 "loader"，且源码里 `"from ." not in source`）。

---

## No Analog Found

| File / 能力 | Role | Data Flow | Reason |
|---|---|---|---|
| `tests/services/code_graph/conftest.py` 的**合成冻结 `MultiDiGraph` fixture** | test fixture | in-memory | 全仓没有任何 networkx fixture。`tests/services/code_graph/` 的 5 个 fixture 全是 DB 工厂；`tests/codegraph/` 是兄弟分支且不可见（conftest 顶部已记录）。按 RESEARCH `## Code Examples` §5 新建，**记得 `nx.freeze(g)`**——不冻结的话「内核不改图」这条断言就是空的 |
| `test_two_surfaces_same_payload`（MCP 与对话壳产出逐字节相同） | test | — | 全仓无先例。最接近的一对（`search_delivery_knowledge`）恰恰**没有**这条守护，且已经在失败语义上漂移（见 `## Shared Patterns`）。本相位建立该范式 |

**部分无先例（有骨架、关键分支要新写）：**

- **跨仓一跳的「查 A 仓 ORM → 取 B 仓图 → 逐仓复核权限」全链路**：ORM 半边有
  `find_api_callers`，多仓扇出有 `SearchRagChunksView`，逐仓权限有 `get_graph`——
  但三者从未组合过，且 `SearchRagChunksView` 对失败仓的处理（静默 `continue`）
  与 D-12/D-14 直接相反。
- **`REDACTED_REPOSITORY` 折叠条目**：常量已在 barrel（`model.py:224`，注释明写
  「折叠动作本身在 Phase 122 的跨仓 impact 里实现」），但全仓**零个使用点**——
  本相位是第一个消费者，输出形状无处可抄，按 D-30（只出裸标记、不带 `affected_count`）
  自定。

---

## Metadata

**Analog search scope:** `server/services/code_graph/`、`server/mcp_tools/`、
`server/agents/tools/`、`server/agents/chat_runner.py`、`server/repositories/`、
`server/codegraph/models.py`、`server/tests/{services/code_graph,mcp_tools,agents}/`

**Files read (full or targeted):** 23 —— `code_graph/{__init__,model,access,signature}.py`
（全文/头部）、`code_graph/{cache,loader}.py`（定向段）、`mcp_tools/{urls,errors}.py`
（全文）、`mcp_tools/views.py`（1-420 / 488-637 / 1077-1275 / 2582-2660）、
`mcp_tools/serializers.py`（定向段）、`agents/tools/{base,find_api_callers}.py`（全文）、
`agents/tools/{delivery_knowledge_tools,repository_relevance,__init__}.py`（头部）、
`agents/chat_runner.py`（55-130）、`repositories/freshness_service.py`（全文）、
`repositories/serializers.py`（定向段）、`codegraph/models.py`（170-330）、
`tests/services/code_graph/{conftest,test_access,test_loader,test_model}.py`、
`tests/mcp_tools/{conftest,test_schema_snapshot,test_reverse_lookup_tool,test_retrieval_trace}.py`、
`tests/agents/tools/test_knowledge_read_tools.py`

**跨面 import 交集扫描（AST）：** `mcp_tools/views.py` 与 `agents/tools/*.py` 共享
22 个一方模块，其中与本相位相关的三对：`codegraph.models`（跨仓表）、
`knowledge.{exposure,retrieval}`（双面同源半先例）、`codegraph.services.repo_router_v2`。

**Pattern extraction date:** 2026-08-09
