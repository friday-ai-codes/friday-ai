# Phase 144: 仓库召回与 Capture 回放 - Pattern Map

**Mapped:** 2026-08-28
**Files analyzed:** 22 个拟新增/修改文件
**Analogs found:** 22 / 22

## 范围结论

本阶段应沿用现有四条主干，不新增平行检索或权限体系：

1. 会话知识检索统一委托 `DeliveryKnowledgeSearchService.search_similar`，只在向量
   `must` filter 增加可选 `source_kinds`。
2. MCP 入口沿用 `McpToolView` 的 `_begin → _validate → service → serialize → _record`
   壳；Chat 入口沿用 `knowledge_read_tools.py` 的 owner 解析、统一 DTO 与
   `_record_chat_retrieval`。
3. Capture 回放只读 `initiatives.SessionCapture`，授权语义为
   `superuser OR (创建者 AND 所有已挂钩 scope 仍可见)`；不存在与未授权统一中性 404。
4. 默认分支守卫只阻断 `RepoAssociation` 第三兜底源；work item 与显式
   `ProjectBranch` 两个高置信源保持优先并可在默认分支命中。

当前 `main` 分支通过 `lookup_project_by_branch` 实际返回了不相关项目的
`matched=true`，与 `LookupProjectByBranchView` 第三源在
`server/mcp_tools/views.py:3579-3583` 无默认分支判定完全一致，属于本阶段应锁住的现存缺陷。

## File Classification

| New/Modified File | Role | Data Flow | Closest Analog | Match Quality |
|---|---|---|---|---|
| `server/knowledge/vector_recall.py` | service/utility | request-response transform | 同文件 `_build_knowledge_must_filter` 的 `entity_kinds` | exact |
| `server/knowledge/retrieval.py` | service | request-response | 同文件 `search_similar` 的 scope 透传 | exact |
| `server/knowledge/session_capture_retrieval.py`（推荐新增共享 helper） | service | request-response | `server/mcp_tools/learning_case_service.py:254-346` | role/data-flow match |
| `server/services/project_context_packer.py` | service | aggregate + request-response | 同文件 `_layer_rag` | exact |
| `server/services/branch_parsing.py` | utility | transform | 同文件 `parse_work_item_id_from_branch` | exact |
| `server/initiatives/services/capture_access.py`（推荐新增） | service | request-response authorization | `server/services/process_runtime/stage_sandbox.py:619-637` + `knowledge/access_scope.py` | composite exact |
| `server/initiatives/services/__init__.py` | package export | config | 同文件 `CaptureService` re-export | exact |
| `server/mcp_tools/views.py` | controller | request-response | `SearchDeliveryKnowledgeView` / `GetRepoResearchView` / `LookupProjectByBranchView` | exact |
| `server/mcp_tools/serializers.py` | validation/config | request-response | `SearchDeliveryKnowledgeRequestSerializer` / UUID read serializers | exact |
| `server/mcp_tools/urls.py` | route | request-response | 现有 knowledge / Capture routes | exact |
| `server/agents/tools/knowledge_read_tools.py` | provider/tool | request-response | `search_project_context` | exact |
| `server/agents/tools/schemas/delivery_knowledge.py` | validation | transform | `SearchDeliveryKnowledgeInput` | exact |
| `server/agents/chat_runner.py` | config | tool discovery | `_INDEXED_TOOL_NAMES` knowledge entries | exact |
| `mcp/src/tools.ts` | config/schema | request-response | `search_delivery_knowledge` + `get_repo_research` | exact |
| `server/tests/knowledge/test_vector_recall.py` | test | transform | entity kind/filter tests | exact |
| `server/tests/services/test_project_context_packer.py` | test | aggregate + request-response | packer scope/trace tests | exact |
| `server/tests/mcp_tools/test_search_session_knowledge.py`（新增） | test | request-response | `test_delivery_knowledge_tools.py` | exact |
| `server/tests/mcp_tools/test_get_session_capture.py`（新增） | test | request-response | `test_report_session_knowledge.py` + `GetRepoResearchView` tests | role/data-flow match |
| `server/tests/mcp_tools/test_lookup_project_by_branch.py` | test | request-response | 同文件第三源用例 | exact |
| `server/tests/mcp_tools/test_report_session_knowledge.py` | test | request-response | 同文件默认分支接受测试 | exact |
| `server/tests/agents/tools/test_search_session_knowledge.py`（新增；也可并入 `test_knowledge_read_tools.py`） | test | request-response | `test_knowledge_read_tools.py` | exact |
| `server/tests/mcp_tools/test_schema_snapshot.py`, `test_mcp_package_alignment.py`, `mcp/tests/server.test.ts` | contract tests | schema alignment | 同文件现有三面对齐守卫 | exact |

## Pattern Assignments

### `server/knowledge/vector_recall.py`（service/utility, transform）

**Analog:** 同文件 `entity_kinds` 的 filter 构造与 embedding 前短路。

**Filter 模式**（`server/knowledge/vector_recall.py:114-118`）：

```python
if entity_kinds:
    must.append(
        models.FieldCondition(key="entity_kind", match=models.MatchAny(any=entity_kinds))
    )
```

`source_kinds` 应以同型 `FieldCondition(key="source_kind", match=MatchAny(...))`
追加到同一个 `must`，而不是 hydrate 后过滤。参数必须从
`recall_similar_chunks` 透传到 demand/code 两路共用的
`_build_knowledge_must_filter`。

**零回归短路模式**（`server/knowledge/vector_recall.py:250-264`）：

```python
if entity_kinds is None:
    demand_kinds = demand_allowed
    code_kinds = list(_CODE_KINDS)
else:
    demand_kinds = [k for k in entity_kinds if k in demand_allowed]
    code_kinds = [k for k in entity_kinds if k in _CODE_KINDS]
    if not demand_kinds and not code_kinds:
        return []
```

新增契约应为：

- `source_kinds is None`：不添加条件，所有旧调用逐字保持。
- `source_kinds == []`：embedding 前返回 `[]`。
- 非空列表：Qdrant `must` 中包含 `source_kind MatchAny`。
- 会话专用调用固定同时传
  `entity_kinds=["document"]`、`include_document_kind=True`、
  `source_kinds=["session_capture"]`。

**不得破坏的权限逃生支**（`server/knowledge/vector_recall.py:70-105`）：
`project_id ∈ allowed` OR
`project_id == "" AND repository_id ∈ allowed` 必须保留；仅仓挂钩 Capture
正是依赖此分支召回。

---

### `server/knowledge/retrieval.py`（service, request-response）

**Analog:** `search_similar` 先收口 project，再用收口后的 project 解析 repository。

**权限与透传模式**（`server/knowledge/retrieval.py:33-63`）：

```python
allowed_projects = await resolve_allowed_project_ids(user, project_ids)
allowed_repos = await resolve_allowed_repository_ids(
    user, repository_ids, project_ids=allowed_projects
)
if not allowed_projects:
    return []

hits = await recall_similar_chunks(
    query,
    allowed_project_ids=allowed_projects,
    allowed_repository_ids=allowed_repos,
    top_k=top_k,
    entity_kinds=entity_kinds,
    include_superseded=include_superseded,
    include_document_kind=include_document_kind,
)
```

只新增 `source_kinds: list[str] | None = None` 并原样透传。不要放宽
`if not allowed_projects: return []`，也不要在 service 外自行计算权限。

仓库与项目参数语义由 `knowledge/access_scope.py:88-94,137-145` 锁定为 caller
集合必须是 allowed 集合的子集；任一不可见 id 导致空 scope，而不是部分放行。

---

### `server/knowledge/session_capture_retrieval.py`（推荐新增共享 service helper）

**Analog:** `server/mcp_tools/learning_case_service.py:254-346` 把多个入口收口到统一
`DeliveryKnowledgeSearchService`，对异常 fail-soft；但会话知识 helper 不做回捞
`SessionCapture`，只返回统一 `SearchResultDTO`。

建议唯一函数形态：

```python
async def search_session_knowledge(
    query: str,
    *,
    user: Any,
    repository_id: str,
    project_id: str | None = None,
    top_k: int = 5,
) -> list[SearchResultDTO]:
    return await DeliveryKnowledgeSearchService().search_similar(
        query,
        user=user,
        top_k=top_k,
        repository_ids=[repository_id],
        project_ids=[project_id] if project_id else None,
        entity_kinds=["document"],
        include_document_kind=True,
        source_kinds=["session_capture"],
    )
```

MCP 与 Chat 都只能调用此 helper；不得各自拼三件套 filter。输出继续走
`knowledge.exposure.serialize_search_results`，该出口已包含
`source_kind/source_id`（`server/knowledge/exposure.py:87-110`）。

helper 不写 RetrievalTrace：MCP 需要 `InteractionRun/tool_call`，Chat 需要
`conversation_id`，留痕仍由各 adapter 壳完成。

---

### `server/services/project_context_packer.py`（service, aggregate）

**Analog:** `_layer_rag` 的统一 search service 调用。

**现状**（`server/services/project_context_packer.py:457-480`）：

```python
results = await DeliveryKnowledgeSearchService().search_similar(
    query,
    user=user,
    top_k=8,
    include_document_kind=True,
)
```

必须至少补 `project_ids=[str(project_id)]`，确保 pack 当前项目时不会从用户其它可见
项目混入 RAG。`session_capture` 是通用项目上下文 DOCUMENT 的新增允许来源，不得把
packer 改成 `source_kinds=["session_capture"]` 的排他检索，否则会丢失 project_doc、
memory、artifact、Feishu document 等既有 DOCUMENT。

若计划选择“显式 inclusion 白名单”，白名单必须是既有全部允许 document source
加 `session_capture`，并用回归测试证明旧来源仍出现；不能临时猜一个不完整集合。
优先使用 `source_kinds=None` 表达“所有当前允许 DOCUMENT（自然包含
session_capture）”，同时以测试锁定 inclusion。

**既有 trace 不可照抄给会话专用工具**（`server/services/project_context_packer.py:493-534`）：
packer payload 当前含 `query`，Phase 144 的会话 MCP/Chat RetrievalTrace 明确禁止
query/正文，因此只能复用 best-effort 结构，不能复制 payload。

---

### `server/services/branch_parsing.py`（utility, transform）

**Analog:** 纯函数、无 IO、fail-soft 的 `parse_work_item_id_from_branch`
（`server/services/branch_parsing.py:27-48`）。

新增 `is_default_branch` 应保持同一模块的纯函数风格：

```python
_WELL_KNOWN_DEFAULT_BRANCHES = frozenset({"main", "master", "develop"})

def is_default_branch(branch_name: str | None, default_branch: str | None = None) -> bool:
    candidate = (branch_name or "").strip()
    if not candidate:
        return False
    configured = (default_branch or "").strip()
    return candidate in _WELL_KNOWN_DEFAULT_BRANCHES or bool(
        configured and candidate == configured
    )
```

分支名是 Git case-sensitive 标识，不做 `.lower()`。仓库模型的配置字段为
`Repository.default_branch`（`server/repositories/models.py:142-163`）。

---

### `server/initiatives/services/capture_access.py`（推荐新增只读授权 service）

**Analog 1：创建者 + 中性 None**
（`server/services/process_runtime/stage_sandbox.py:619-637`）：

```python
session = await ConvergenceSession.objects.filter(id=session_id).afirst()
if session is None or str(session.process_type) != SANDBOX_PROCESS_TYPE:
    return None
user_id = getattr(user, "id", None)
created_by_id = getattr(session, "created_by_id", None)
if user_id is None or created_by_id is None or str(created_by_id) != str(user_id):
    return None
```

**Analog 2：挂钩 scope 收口**
（`server/initiatives/services/capture_service.py:335-351`）：

```python
allowed_repositories = await resolve_allowed_repository_ids(
    actor, repository_ids=[str(repository.id)]
)
allowed_projects = await resolve_allowed_project_ids(actor, [str(project.id)])
```

推荐由 `aget_readable_capture(capture_id, user) -> SessionCapture | None` 一次完成：

1. `SessionCapture.objects.select_related("repository", "project").filter(pk=...).afirst()`；
2. `superuser` 可读；
3. 普通用户必须 `capture.initiated_by_user_id == str(user.id)`；
4. 有 repository FK 时，其 id 必须仍在 `resolve_allowed_repository_ids` 结果；
5. 有 project FK 时，其 id 必须仍在 `resolve_allowed_project_ids` 结果；
6. 任一步失败统一返回 `None`。

不要复用 `CaptureService.get_capture` 直接暴露结果；该方法
`server/initiatives/services/capture_service.py:62-66,199-206` 只有 UUID 解析与 get，
没有读授权。回放是只读 service，不允许调用 `persist`、状态机方法或 eval/ingest enqueue。

响应字段只从 `SessionCapture` allowlist 取：

- `capture_id`
- `question`, `answer`
- `response_model`, `provider`, `input_tokens`, `output_tokens`
- `session_id`, `branch_name`
- `repository_id`, `project_id`, `link_reason`
- `value_tier`, `status`
- `created_at`, `updated_at`, `evaluated_at`, `ingested_at`

明确排除 `last_error`、`distilled_essence`、`question_hash`、内部 attempts/retry 字段。
`client` 不在模型上（`server/initiatives/models/session_capture.py:37-109`），不得为补
client 查询 `ToolCallRecord` 或其它 Ledger 表。

如新增 service，应按 `server/initiatives/services/__init__.py:7-16,59-97` 的
显式 import + `__all__` 模式 re-export。

---

### `server/mcp_tools/views.py`（controller, request-response）

#### `SearchSessionKnowledgeView`

**Analog:** `SearchDeliveryKnowledgeView`
（`server/mcp_tools/views.py:3308-3385`）。

严格沿用：

```python
run, err = await self._begin(request)
input_data, err = await self._validate(..., request)
started_at = time.perf_counter()
...
serialized = serialize_search_results(results)
...
await self._record(
    run,
    input_data=input_data,
    output_data=output_data,
    traces=traces,
    started_at=started_at,
)
```

差异必须是：

- `repository_id` 必填单 UUID；`project_id` 可选单 UUID。
- 调共享 `search_session_knowledge` helper，不直接调 Qdrant。
- 基础设施异常沿用 `mcp_vector_search_degraded` 模式降级 `results=[]`、HTTP 200。
- 即使空结果也组装一条汇总 `RetrievalTrace.Kind.CHUNK`。
- trace payload 只含
  `source, repository_id, project_id, source_kind, result_count, scores, top_score, duration_ms`。
- 不复制 `SearchDeliveryKnowledgeView:3366-3377` 的逐结果 `title` trace，也不放
  `query/text/question/answer/essence`。

`McpToolView._record` 已在 `server/mcp_tools/views.py:309-348` 把 traces 绑定
`run/tool_call` 并委托 `arecord_retrieval_trace`，不应另写 Ledger。

#### `GetSessionCaptureView`

**Analog:** `GetRepoResearchView`
（`server/mcp_tools/views.py:6047-6084`）：

```python
result = await aget_research_sandbox(..., user=request.user)
if result is None:
    return error_response(
        "not_found", "调研会话不存在", status_code=status.HTTP_404_NOT_FOUND
    )
```

回放 view 应调用 `aget_readable_capture`，对不存在、非法 UUID、非创建者、scope
不可见全部返回相同 `error_code/detail/status`。成功时显式构造 allowlist 响应，再
`_record(traces=[])`。这是只读工具，不能 enqueue、评估、入图或推进状态。

#### `LookupProjectByBranchView`

**Analog:** 现有三源合并（`server/mcp_tools/views.py:3564-3608`）。

改动只放在第三源块：

```python
if not merged and repository_id:
    association_projects = await self._lookup_by_repo_association(repository_id)
```

应先读取 repository 的 `default_branch`，调用 `is_default_branch`：

- 默认分支：`association_projects` 仅映射到 `candidates`，设置
  `binding_source="repo_association_skipped_default_branch"`（或同义闭集 reason），
  `matched=False`，`context=""`，不得调用 `pack_project_context`。
- 非默认分支：保持现有第三源合并。
- work item / `ProjectBranch` 已命中时根本不进入第三源，零回归。

注意当前 `output_data`（`views.py:3551-3561`）没有 `binding_source`；若在 unmatched
响应新增该键，serializer snapshot 和 npm contract 必须同步。

---

### `server/mcp_tools/serializers.py` 与 `urls.py`（validation/route）

**Search serializer analog**（`server/mcp_tools/serializers.py:682-707`）：

```python
query = serializers.CharField(required=True, max_length=4000)
top_k = serializers.IntegerField(required=False, default=5, min_value=1, max_value=20)
```

会话检索新增：

- `repository_id = serializers.UUIDField(required=True)`
- `project_id = serializers.UUIDField(required=False, allow_null=True, default=None)`
- `query` 非空、`top_k` 1..20

Capture get 新增：

- `capture_id = serializers.UUIDField(required=True)`

`TOOL_SCHEMA_SNAPSHOT` 沿用
`server/mcp_tools/serializers.py:1732-1794` 的 request/response 字面键列表。
lookup 若新增 unmatched `binding_source`，将其加入响应键；不要只改 body。

URL 沿用 `server/mcp_tools/urls.py:161-190` 的 knowledge/Capture tool 命名：

- `tools/search_session_knowledge/`
- `tools/get_session_capture/`

新增 view import 与 urlpatterns 必须成对；不要另建 REST-only 平行路由。

---

### `server/agents/tools/knowledge_read_tools.py` 与 schema（provider, request-response）

**Analog:** `search_project_context`
（`server/agents/tools/knowledge_read_tools.py:182-261`）。

复制模式：

1. `@tool` JSON schema 声明 `query/repository_id/project_id/top_k/conversation_id`；
2. `top_k = max(1, min(int(top_k), 20))`；
3. `_resolve_conversation_user(conversation_id)`，无 owner 返回 fail-closed `ToolResult`；
4. 调共享 `search_session_knowledge`；
5. `serialize_search_results`；
6. `_record_chat_retrieval`；
7. 结构化 caller 日志；
8. `ToolResult(success=True, output=...)`。

`_record_chat_retrieval` 已在 `knowledge_read_tools.py:41-61` 用 try/except 包住
`arecord_retrieval_trace`。新 payload 使用与 MCP 相同字段闭集，仅 `source` 改为
`chat_search_session_knowledge`。异常文本在返回 ToolResult 与日志前必须经
`redact_secrets_in_text`（同文件 `223-227`）。

如果新增 Pydantic 输入模型，复制
`server/agents/tools/schemas/delivery_knowledge.py:23-33` 的
`ConfigDict(strict=True, extra="forbid")`；但不得形成 MCP serializer、Chat schema、
helper 三套业务 filter。

更新同文件 `__all__`，并在 `server/agents/chat_runner.py:129-138` 的
`_INDEXED_TOOL_NAMES` 加入 `search_session_knowledge`。它是仓库索引知识工具，不应挂到
仅 bound project 才出现的 `_PROJECT_READ_TOOL_NAMES`。

---

### `mcp/src/tools.ts`（npm schema/config）

**Search analog**（`mcp/src/tools.ts:519-535`）：

```typescript
{
  name: 'search_delivery_knowledge',
  inputSchema: {
    type: 'object',
    properties: {
      query: str(...),
      top_k: int(...),
      ...
    },
    required: ['query'],
  },
}
```

`search_session_knowledge` 必须 `required: ['repository_id', 'query']`，project 可选；
描述明确 repository 是主 scope、project 只做 AND 收窄、只返回中高价值
`session_capture` 精华。

**只读 get analog**（`mcp/src/tools.ts:619-627`）：
`get_session_capture` 只接收 `capture_id`，描述明确创建者授权、原始结构化问答和
中性 404。

annotations 使用 `query(...)`，其行为为 readOnly/non-destructive/idempotent。
不要复用 `report_session_knowledge` 的写工具 annotations
（`mcp/src/tools.ts:959-965`）。

---

## Test Pattern Assignments

### `server/tests/knowledge/test_vector_recall.py`

**Analog:** filter 结构断言
（`server/tests/knowledge/test_vector_recall.py:77-100,222-253`）。

新增测试：

- `source_kinds=["session_capture"]` 时两路实际 query filter 的顶层 must 含
  `source_kind MatchAny(["session_capture"])`；
- `source_kinds=None` 时无 `source_kind` condition；
- `source_kinds=[]` 时返回 `[]` 且 `hybrid_calls == []`，证明 embedding/Qdrant 前短路；
- DOCUMENT 三件套只发 demand 一路；
- project 空串 + allowed repository 逃生支仍存在。

不要只测 helper 的 kwargs；必须至少一条断言真实 Qdrant filter shape。

### `server/tests/services/test_project_context_packer.py`

**Analog:** fail-closed、trace 与聚合测试
（`server/tests/services/test_project_context_packer.py:45-83,128-139`）。

monkeypatch `DeliveryKnowledgeSearchService.search_similar`，断言：

- `project_ids == [str(project.id)]`；
- `include_document_kind is True`；
- 不存在排他的 `source_kinds=["session_capture"]`；
- 返回 `source_kind=session_capture` DTO 时可进入 RAG layer；
- 既有 project document DTO 仍可进入，防“白名单加入”误做成 exclusive。

### `server/tests/mcp_tools/test_search_session_knowledge.py`（新增）

**Analog:** `server/tests/mcp_tools/test_delivery_knowledge_tools.py:42-92,128-168`。

覆盖：

- 缺 repository / 空 query / top_k 越界 → 400；
- repository 必传，project 可选；
- 调共享 helper时 `repository_id` 与 `project_id` 同时存在（AND，不是 OR）；
- 无权限 repository → 200 空 results；
- 只返回 `source_kind=session_capture`；
- service 异常 → 200 空 results；
- 空结果也写一条 trace；
- trace 只含标量/计数/分数/标识，禁止 query/title/text/question/answer；
- monkeypatch `RetrievalTrace.objects.create` 抛异常后仍 HTTP 200 且业务结果不变；
- `ToolCallRecord` 仍存在。

### `server/tests/mcp_tools/test_get_session_capture.py`（新增）

**Analogs:**

- `test_report_session_knowledge.py:76-103` 的真实 Capture + 精确响应键；
- `GetRepoResearchView` 的创建者/中性 404；
- `test_capture_service.py:108-122` 的 Ledger 分离守卫。

覆盖：

- 创建者 + 无挂钩 Capture → 200；
- 创建者 + 可见 repo/project → 200；
- 他用户、已失去 repo scope、已失去 project scope、不存在 UUID → 完全相同 404 body；
- superuser 可读；
- 响应精确 allowlist，包含已脱敏 `question/answer`；
- 不含 `last_error/distilled_essence/question_hash`；
- 不含 client 或隐藏 CoT；
- monkeypatch `ToolCallRecord` / `RetrievalTrace` 查询入口为抛错，成功回放仍成立，证明正文
  只读 SessionCapture；
- 请求不改变 status/attempts/timestamps，不触发 eval/ingest enqueue。

### `server/tests/mcp_tools/test_lookup_project_by_branch.py`

**Analog:** 第三源回归
（`server/tests/mcp_tools/test_lookup_project_by_branch.py:333-423`）。

保留 `feat/login-page` + confirmed association → matched true 用例；新增：

- `main/master/develop` + 唯一 association → matched false、context 空、候选一项；
- repository 自定义 `default_branch="trunk"` 同上；
- 默认分支 + 显式 `ProjectBranch` → matched true；
- 默认分支 + 可解析 work item → matched true；
- skip 响应含稳定 `binding_source/reason`（若采用该响应扩展）；
- monkeypatch `pack_project_context`，第三源 skip 时断言未调用。

不要修改现有 `test_unparseable_branch_fail_soft` 为“有 repository 的 main”；它验证的是无
repository 的纯空返回，应该保留。

### `server/tests/mcp_tools/test_report_session_knowledge.py`

**Analog:** `test_default_branch_does_not_mean_rejected`
（`server/tests/mcp_tools/test_report_session_knowledge.py:168-182`）。

新增带真实 repository + 唯一 `RepoAssociation` 的 `main` 用例，且不传 project_id：

- `accepted is True`；
- `capture.repository_id == repository.id`；
- `capture.project_id is None`；
- reason 不是 `branch_unresolved`；
- 写路径不调用 lookup/packer。

这锁定“修读侧 lookup，不反噬 Capture 仓库优先写路径”。

### `server/tests/agents/tools/test_search_session_knowledge.py`

**Analog:** `server/tests/agents/tools/test_knowledge_read_tools.py:131-175,212-232`。

覆盖：

- 无效 conversation owner fail-closed；
- repository 必填、top_k 钳到 20；
- 调用共享 helper并传 repo + optional project；
- `serialize_search_results` 输出；
- 空结果也记录 `result_count=0`；
- trace payload 与 MCP 同字段口径且无正文/query；
- `arecord_retrieval_trace` 抛异常仍 `ToolResult.success=True`；
- registry 与 `_INDEXED_TOOL_NAMES` 都包含新工具。

可直接扩展 `test_knowledge_read_tools.py`，若单独新建则仍复用其 fixtures。

### Schema / npm 三面对齐测试

**Analogs:**

- `server/tests/mcp_tools/test_schema_snapshot.py:28-49`：URL 注册集合 == snapshot；
- `server/tests/mcp_tools/test_mcp_package_alignment.py:59-72`：npm 工具集合 ==
  server snapshot；
- 同文件 `75-97`：新工具 serializer/snapshot/npm properties 三面对齐；
- `mcp/tests/server.test.ts:19-69`：工具总数、唯一性、发现性、annotations。

新增两个工具时，52 应变 54；如果最终只新增一个 MCP 工具则变 53，但计划不能在各测试里
写不同计数。两个工具都应有 `query(...)` 只读 annotations。为新工具各增加 request key
对齐测试，不扩大历史工具字段门禁。

## Shared Patterns

### 权限：caller 只收窄，不放宽

**Source:** `server/knowledge/access_scope.py:52-145`

应用于向量检索与 Capture 回放。`project_id` 是 repository scope 的进一步交集；不得出现
`project OR repository`。现有 `allowed_projects` 空短路是平台 ACL 的一部分，不在本阶段
修订。

### MCP 生命周期与可观测

**Source:** `server/mcp_tools/views.py:261-348`

所有新 MCP 工具使用统一认证、run、校验、RequestMetric、ToolCallRecord 与
RetrievalTrace helper。MCP retrieval traces 通过 `_record(traces=...)` 绑定 run；
不在 view 内直接 `RetrievalTrace.objects.create`。

### Chat RetrievalTrace

**Source:** `server/agents/tools/knowledge_read_tools.py:41-61`

Chat 使用 `arecord_retrieval_trace(run=None, conversation_id=..., user_id=..., source="chat")`，
由 helper try/except 保证 best-effort。

### Ledger 脱敏与失败降级

**Source:** `server/interactions/ledger.py:172-224,404-423`

```python
return RetrievalTrace.objects.create(
    ...
    payload=redact_for_ledger(payload or {}),
)
```

写入异常 warning + `None`，不得改变检索结果。Phase 144 的 payload 仍应先按字段闭集
构造，不能以“ledger 会脱敏”为理由写 query/正文。

### SessionCapture 是回放唯一真源

**Source:** `server/initiatives/models/session_capture.py:37-109`

模型已保存脱敏 question/answer 与关联元数据。`knowledge/sources/session_capture.py`
则明确只把 `distilled_essence` 投影为 `DOCUMENT/source_kind=session_capture`，原始
question/answer 不进 RAG。回放和检索必须维持这两层分离。

## Anti-Patterns

1. **按 `entity_kind=document` 或标题识别会话知识**：会混入 project_doc、artifact、
   memory；必须用 Qdrant `source_kind=session_capture`。
2. **hydrate 后过滤 source_kind**：浪费 top_k，且让无关点进入计分/扩散；filter 必须进
   Qdrant `must`。
3. **把通用 `search_similar` 默认 source 改成 session_capture**：破坏所有旧消费者；
   默认必须是 `None`。
4. **packer 只搜 session_capture**：RECALL-02 是 inclusion，不是排他替换。
5. **project_id 替代 repository_id**：专用会话检索中 repository 永远必填，project
   只能 AND 收窄。
6. **MCP/Chat 分别拼 filter**：必须共享同一 helper 与同一 service。
7. **回放读取 ToolCallRecord/RetrievalTrace/InteractionRun**：Ledger 不是正文来源，也
   不能用于补 client、CoT 或内部错误。
8. **回放复用 `CaptureService.get_capture` 后直接返回**：现有 getter没有授权；必须增加
   创建者与挂钩 scope 校验。
9. **未授权返回 403、缺失返回 404**：会泄漏 UUID 是否存在；两者必须同一 404。
10. **回放返回 model 全字段**：会泄漏 `last_error/distilled_essence/question_hash`；
    必须显式 allowlist。
11. **默认分支第三源仍调用 packer**：即使最终 `matched=false`，也会发生项目上下文读取/
    trace；skip 必须在 pack 之前。
12. **默认分支禁用全部匹配源**：显式 ProjectBranch 与 work item 是可审计高置信证据，
    必须继续命中。
13. **因 lookup 不唯一拒绝 Capture 或清空 repository FK**：Capture 写路径以显式
    repository 挂钩为主，仍应 accepted。
14. **会话 trace 复制 `SearchDeliveryKnowledgeView` 的 title/query**：Phase 144 trace
    只允许标量、计数、分数和标识。
15. **trace 写入失败向外抛**：MCP 与 Chat 都必须保持原业务结果。
16. **只改 Django URL 或只改 npm schema**：服务端 serializer/snapshot/URL、npm tool、
    annotations、计数与对齐测试必须一起变化。
17. **新增 EntityKind、collection、CallSource 或运行时依赖**：本阶段均不需要。
18. **在回放入口调用 `SessionCapture.objects.create`**：违反 INV-6；回放只 get。

## No Analog Found

无。所有拟新增文件都有同 role/data-flow 的现有模式；无需依赖 RESEARCH.md 中的泛化示例
发明新架构。

## Metadata

**Analog search scope:** `server/knowledge/`, `server/services/`,
`server/initiatives/`, `server/mcp_tools/`, `server/agents/`, `server/interactions/`,
`server/tests/`, `mcp/src/`, `mcp/tests/`

**Primary analog files read:** 24

**Pattern extraction date:** 2026-08-28

**Friday branch lookup evidence:** 当前分支 `main` 的实时召回返回 `matched=true` 且上下文来自
唯一仓库关联项目，验证默认分支第三源误注入确实可复现；本文件未采信该不相关项目上下文。
