# Phase 142: MCP 会话回写契约 - Pattern Map

**Mapped:** 2026-08-28
**Files analyzed:** 8
**Analogs found:** 8 / 8

Phase 141 已交付 `CaptureService.persist`；本阶段只接 MCP HTTP + 三面契约。挂钩状态机、脱敏、幂等、`unknown` 归一**不要**再实现一遍。

## File Classification

| New/Modified File | Role | Data Flow | Closest Analog | Match Quality |
|-------------------|------|-----------|----------------|---------------|
| `server/mcp_tools/serializers.py`（`ReportSessionKnowledgeRequestSerializer` + `TOOL_SCHEMA_SNAPSHOT["report_session_knowledge"]`） | controller (serializer + snapshot) | request-response | `ReportProjectKnowledgeRequestSerializer` + `TOOL_SCHEMA_SNAPSHOT["report_project_knowledge"]` | role-match（字段风格 exact；**禁止**抄 `validate` 定位门闩） |
| `server/mcp_tools/views.py`（`ReportSessionKnowledgeView`） | controller | request-response | `McpToolView` + `ReportProjectKnowledgeView.post` 外壳 | role-match（壳 exact；业务反模式对照） |
| `server/mcp_tools/urls.py` | route | request-response | `tools/report_project_knowledge/` 旁 `path(...)` | exact |
| `mcp/src/tools.ts` | config | request-response | `FRIDAY_TOOLS` 中 `report_project_knowledge` 条目 + `graph_query` 的 `additionalProperties: false` | exact（注解**不要**抄 `generator()`） |
| `server/tests/mcp_tools/test_report_session_knowledge.py` | test | request-response | `test_report_project_knowledge.py`（HTTP）+ `test_capture_service.py`（挂钩语义） | exact / inverted |
| `server/tests/mcp_tools/test_schema_snapshot.py` | test | — | 同文件 `test_registered_tools_match_snapshot` + 字面量 dict | exact |
| `server/tests/mcp_tools/test_mcp_package_alignment.py` | test | — | 同文件名集守卫；新工具另加字段三面 | exact（扩展） |
| `server/tests/mcp_tools/test_report_project_knowledge.py` | test | request-response | 自身（MCP-04 零回归，不改断言） | exact（只跑不改语义） |

**Out of scope（不要新建/不要改挂钩）：** `capture_service.py`、`session_capture.py`、migration、`skills/`、`ide_hook_assets.py`、`test_skills_snapshot_guard.py` 前缀表（`report_` 已覆盖）。

---

## Pattern Assignments

### `server/mcp_tools/serializers.py` (serializer + snapshot, request-response)

**Analog A (字段风格):** `ReportProjectKnowledgeRequestSerializer` (`server/mcp_tools/serializers.py` 782–813)

复制：`CharField(required=True, allow_blank=False, max_length=20000)` 给正文；可选 `UUIDField(required=False, allow_null=True, default=None)`；可选 `CharField(required=False, allow_blank=True, default="", max_length=255)`。

**不要复制** `validate` 里「`project_id` 与 `branch_name` 至少给一个」——新工具允许无仓无项目（`unanchored`）。

```python
# Analog — 仅抄字段类型，不抄定位门闩
content = serializers.CharField(required=True, allow_blank=False, max_length=20000)
project_id = serializers.UUIDField(required=False, allow_null=True, default=None)
branch_name = serializers.CharField(
    required=False, allow_blank=True, default="", max_length=255
)
```

锁定请求键（CONTEXT 全集，不得缩减）：

| 键 | 建议类型 | 必填 |
|----|----------|------|
| `question` | `CharField` `allow_blank=False` `max_length=20000` | 是 |
| `answer` | 同上 | 是 |
| `repository_id` | `UUIDField` optional/null | 否 |
| `git_url` | `CharField` optional `max_length<=500` | 否 |
| `branch_name` | `CharField` optional max 255 | 否 |
| `project_id` | `UUIDField` optional/null | 否 |
| `session_id` | `CharField` max 255（**不是** UUID；persist 缺省 → `"unspecified"`） | 否 |
| `response_model` / `provider` / `input_tokens` / `output_tokens` | 可选 `CharField`（**不要** `IntegerField`；省略 → persist `_scalar_or_unknown`） | 否 |
| `client` | 可选 `CharField`（请求面收键；**persist 无此参数，view 丢弃**） | 否 |

`client` 闭集 `ChoiceField` 仅当未知字符串仍能 200 入库；更稳是开放 `CharField`。

**Analog B (snapshot 条目形状):** `TOOL_SCHEMA_SNAPSHOT["report_project_knowledge"]` (serializers.py 1737–1740)

新工具从第一天完整对齐（旧条目漂移**禁止**顺手修）：

```python
"report_session_knowledge": {
    "request": [
        "question",
        "answer",
        "repository_id",
        "git_url",
        "branch_name",
        "project_id",
        "session_id",
        "response_model",
        "provider",
        "input_tokens",
        "output_tokens",
        "client",
    ],
    "response": [
        "accepted",
        "capture_id",
        "reason",
        "repository_id",
        "project_id",
        "idempotent_hit",
        "run_id",
    ],
},
```

`test_mcp_read_tool_schema_snapshot` 是**字面量全表相等**，必须同步改 `test_schema_snapshot.py` 里同一条目。旧 `report_project_knowledge` request 仍是 `["project_id","content","source_conversation_id"]`（与 serializer/npm 漂移）——保持原样。

Response serializer 是否独立成类：discretionary；实际 JSON 键必须 = snapshot `response`。

---

### `server/mcp_tools/views.py` (`ReportSessionKnowledgeView`, controller, request-response)

**Analog (壳):** `McpToolView` 257–344 + `ReportProjectKnowledgeView.post` 3761–3769 的 `_begin` → `_validate` → `_record` → `Response`。

**Auth / 校验 / 留痕（抄基类，勿重写）：**

```python
# McpToolView 257–303
authentication_classes = [AccessTokenAuthentication, CookieJWTAuthentication]
permission_classes = [IsAuthenticated]
# _begin → bind_source(LogSource.MCP) + begin_interaction_run(..., source="mcp")
# 无 token → error_response("authentication_failed", ..., 401)
# _validate → ValidationError → error_response("invalid_params", ..., 400)
```

**导入：** 在 `views.py` 81–133 的 `.serializers` 块追加 `ReportSessionKnowledgeRequestSerializer`（紧挨 `ReportProjectKnowledgeRequestSerializer`）。

**Core 业务（唯一写点）:** `CaptureService.persist` 签名 `server/initiatives/services/capture_service.py` 59–75。

```python
from initiatives.services.capture_service import CaptureService

class ReportSessionKnowledgeView(McpToolView):
    tool_name = "report_session_knowledge"

    async def post(self, request: Request) -> Response:
        run, err = await self._begin(request)
        if err is not None:
            return err
        assert run is not None
        input_data, err = await self._validate(
            ReportSessionKnowledgeRequestSerializer, request
        )
        if err is not None:
            return err
        assert input_data is not None
        started_at = time.perf_counter()

        result = await CaptureService().persist(
            question=input_data["question"],
            answer=input_data["answer"],
            actor=request.user,
            initiated_by_user_id=request.user.id,
            session_id=input_data.get("session_id"),
            project_id=input_data.get("project_id"),
            repository_id=input_data.get("repository_id"),
            git_url=input_data.get("git_url") or None,
            branch_name=input_data.get("branch_name") or None,
            response_model=input_data.get("response_model"),
            provider=input_data.get("provider"),
            input_tokens=input_data.get("input_tokens"),
            output_tokens=input_data.get("output_tokens"),
            # 禁止传 client
        )
        capture = result.capture
        output_data = {
            "accepted": True,
            "capture_id": str(capture.id),
            "reason": result.link_reason,
            "repository_id": str(capture.repository_id) if capture.repository_id else None,
            "project_id": str(capture.project_id) if capture.project_id else None,
            "idempotent_hit": result.idempotent_hit,
            "run_id": str(run.run_id),
        }
        await self._record(
            run,
            input_data=input_data,
            output_data=output_data,
            traces=[],  # Phase 144 才 RetrievalTrace
            started_at=started_at,
        )
        return Response(output_data, status=status.HTTP_200_OK)
```

`reason` **原样透传** `CapturePersistResult.link_reason`。闭集比 CONTEXT 举例更宽：`linked` / `linked_with_project` / `project_only` / `repo_unauthorized` 也是合法挂钩结果（`capture_service.py` 140–160、173–193）。

**HTTP：** 成功路径一律 **200**（含挂钩失败、幂等命中）。不要抄旧工具 draft 的 `201`。npm `callFridayTool` 用 `resp.ok`（`mcp/src/server.ts` 107–108）；ROADMAP/CONTEXT 锁定挂钩失败也是 200。

**Error handling：** persist 抛异常走 DRF/`error_response` 5xx，**不得**声称 `accepted=true`。不要抄 `_handle_active_writeback` 的 blanket `except` → `accepted=false`。

**观测：** persist 已打 `session_capture_persist_started/completed/failed`（`capture_service.py` 288–317，`category=caller` `component=knowledge`）。View **不要**再 log `question`/`answer`/`git_url`。Ledger 只经 `_record` → `arecord_tool_call`（内部 `redact_for_ledger`）。`_record` 已写 `arecord_request_metric(route=f"mcp:{self.tool_name}")`。

---

### `server/mcp_tools/urls.py` (route)

**Analog:** 175–185 同文件 Cursor 回流块。

```python
path(
    "tools/report_project_knowledge/",
    ReportProjectKnowledgeView.as_view(),
    name="mcp-tool-report-project-knowledge",
)
```

在 import 列表与 `urlpatterns` 追加 `ReportSessionKnowledgeView`：

```python
path(
    "tools/report_session_knowledge/",
    ReportSessionKnowledgeView.as_view(),
    name="mcp-tool-report-session-knowledge",
)
```

完整路径：`POST /api/mcp/tools/report_session_knowledge/`（`friday/urls.py` `path("mcp/", include("mcp_tools.urls"))`）。

`test_registered_tools_match_snapshot` 用正则 `tools/([a-z0-9_]+)/` 抽名；漏注册或漏 snapshot 都会红。

---

### `mcp/src/tools.ts` (config, npm 白名单)

**Analog (条目形状):** `report_project_knowledge` 733–748。**Analog (严格 schema):** `graph_query` 62–66 `additionalProperties: false`。

文件头注释「51 个」→ **52**。`FRIDAY_TOOLS` 增加一项；`TOOL_ANNOTATIONS` 必须同步（ListTools 用 annotations）。

```typescript
{
  name: 'report_session_knowledge',
  description: '提交本轮问题与可见答案精华到 Friday Capture 账本（accepted=true 仅表示已收 Capture，不表示已挂钩仓库或已入知识库/RAG）。不要上传隐藏思维链或全文 transcript。',
  inputSchema: {
    type: 'object',
    additionalProperties: false,
    properties: {
      question: str('本轮用户问题（必填，非空白）'),
      answer: str('客户端可见答案精华（必填；不是 transcript / 隐藏思维链）'),
      repository_id: uuid('仓库 UUID（可选）'),
      git_url: str('git remote URL（可选；与 repository_id 一起交给挂钩，服务端不猜测）'),
      branch_name: str('分支名（可选元数据，不用于拒绝入库）'),
      project_id: uuid('项目 UUID（可选）'),
      session_id: str('宿主会话 id（可选，非必须 UUID）'),
      response_model: str('响应模型名（可选，缺省服务端存 unknown）'),
      provider: str('供应商（可选）'),
      input_tokens: str('输入 token 计数原文（可选，字符串）'),
      output_tokens: str('输出 token 计数原文（可选，字符串）'),
      client: str('宿主客户端标识（可选；服务端可丢弃不入库）'),
    },
    required: ['question', 'answer'],
  },
}
```

**注解：不要用 `generator()`。** `generator()`（865–871）把 `idempotentHint` 设为 `false`。CONTEXT 要求非破坏、可幂等、非只读：

```typescript
report_session_knowledge: {
  title: '会话 · 上报 Capture 账本',
  readOnlyHint: false,
  destructiveHint: false,
  idempotentHint: true,
  openWorldHint: false,
},
```

`properties` 键必须 = snapshot `request` = serializer `fields`。`test_mcp_package_tools_match_server_snapshot` 只比**工具名**；字段三面必须另测。

stdio 透传：`callFridayTool` POST `{baseUrl}/api/mcp/tools/${toolName}/`（`mcp/src/server.ts` 58–69）。未知名不在 `FRIDAY_TOOLS` 则 Cursor 调不到——只改 Django 会重现 23/30 漂移。

---

### `server/tests/mcp_tools/test_report_session_knowledge.py` (test)

**Analog A (HTTP 夹具):** `test_report_project_knowledge.py` 1–73

```python
pytestmark = pytest.mark.django_db(transaction=True)
_URL = "/api/mcp/tools/report_session_knowledge/"
# mcp_client + access_user；client.post(..., format="json")
# sync_to_async(client.post) 包异步用例
```

`mcp_client`：`server/tests/mcp_tools/conftest.py` 20–25（Bearer PAT）。

**Analog B (挂钩语义，不要在 MCP 测重做全矩阵):** `test_capture_service.py`

| MCP 用例（RESEARCH Wave 0） | 抄语义自 | 与旧 MCP 工具差异 |
|----------------------------|----------|-------------------|
| `test_unanchored_still_accepted` | `test_persist_without_project_or_repo` → `link_reason=unanchored` | 旧 `test_missing_project_id_and_branch_is_validation_error` 是 400 |
| `test_unresolved_repo_still_accepted` | `test_unresolved_repo_still_persists` → `repo_unresolved` | 仍 200 + 有行 |
| `test_default_branch_does_not_mean_rejected` | 仅 `branch_name=main` | **反转** `test_unresolvable_branch_fail_soft`（旧：`accepted=false` + `branch_unresolved` 无草稿） |
| `test_idempotent_hit_keeps_first_write` | `test_idempotent_returns_existing` | 同三元组；答案不覆盖 |
| `test_redaction_on_mcp_path` | `test_redaction_and_actor` | 经 HTTP；行内无 `sk-` |
| `test_session_tool_does_not_write_project_memory` | `test_persist_does_not_write_memory_or_ledger` | MCP 路径会 `_record` Ledger；断言 **Memory 计数不变**、无 `MemoryService.append` |

旧工具 fail-soft（**新工具禁止复制断言方向**）`test_unresolvable_branch_fail_soft` 346–360：

```python
assert resp.status_code == 200
assert body["accepted"] is False
assert body["reason"] == "branch_unresolved"
```

新工具：`accepted is True`、DB 有 `SessionCapture`、`reason != "branch_unresolved"`（无仓无项目应为 `unanchored`）。

**契约断言清单：**

- 201 **不是**成功码；挂钩失败仍 200 + `accepted=True` + `SessionCapture.objects.filter(id=capture_id).exists()`
- 缺 `question`/`answer` → 400 `error_code=invalid_params`（`mcp_tools/errors.py` `error_response`）
- 无 `Authorization` → 401 `authentication_failed`（可另起无 credentials 的 `APIClient`）
- 响应键 = snapshot `response`；`reason` 透传 persist（含 `repo_unauthorized` 等，不要只允许 CONTEXT 举例的 6 个）
- 零 `ProjectMemory` 增量；源码/调用栈不出现 `evaluate_writeback_quality`、`MemoryService.append`、`create_draft`

仓挂钩代表路径：复用 `repository` fixture + 用户进 space（见 `test_capture_service._make_visible_repo` / `test_lookup_project_by_branch` 建仓方式）。细矩阵仍以 `test_capture_service.py` 为准。

---

### `server/tests/mcp_tools/test_schema_snapshot.py` (test)

**Analog:** 同文件 28–53、607–610。

1. `test_registered_tools_match_snapshot`：urls 名集 ↔ snapshot 键——加 url + snapshot 后自动覆盖新名。
2. `test_mcp_read_tool_schema_snapshot`：`assert TOOL_SCHEMA_SNAPSHOT == { ... }` **巨型字面量**。必须在字面量里加入与 serializers 完全相同的 `report_session_knowledge` 条目（不能从 serializers import 该条目再比，会假绿——见文件头 7–8 对 feature 响应键的说明）。

**禁止**把 `report_project_knowledge` 的 snapshot request 扩成与 serializer 一致。

---

### `server/tests/mcp_tools/test_mcp_package_alignment.py` (test)

**Analog:** 同文件 `_TOOL_NAME_RE` / `test_mcp_package_tools_match_server_snapshot`（45–58）。改 `tools.ts` 后名集测试自然绿。

**必须新增**（MCP-03 字段级，仅新工具）：

```python
def test_report_session_knowledge_request_keys_aligned() -> None:
    from mcp_tools.serializers import (
        ReportSessionKnowledgeRequestSerializer,
        TOOL_SCHEMA_SNAPSHOT,
    )
    serializer_keys = set(ReportSessionKnowledgeRequestSerializer().fields)
    snapshot_keys = set(TOOL_SCHEMA_SNAPSHOT["report_session_knowledge"]["request"])
    # 从 tools.ts 解析 report_session_knowledge 的 properties 键（局部正则，勿对全文件 51 工具做字段对齐）
    assert serializer_keys == snapshot_keys == npm_property_keys
```

不要对全部工具做 properties 对齐（会被迫修旧漂移）。

---

### `server/tests/mcp_tools/test_report_project_knowledge.py` (zero regression)

**Analog:** 自身。Phase 142 **不改**这些断言：

- `test_member_report_creates_pending_draft` → 201 + draft
- `test_quality_gate_rejects_too_short` / `duplicate`
- `test_unresolvable_branch_fail_soft` → `accepted=False` `branch_unresolved`
- `test_missing_project_id_and_branch_is_validation_error` → 400

新工具不得让这些变红；不得把 `ReportProjectKnowledgeView` 改成 Capture 入口。

**INV-6 持续守护（不改文件）：** `test_capture_inv6_guard.py` 禁止 view 出现 `SessionCapture.objects.create` / `SessionCapture(`。writer 仍只能是 `initiatives/services/capture_service.py`。`test_writer_does_not_call_deferred_sinks` 禁止 CaptureService 调 `_resolve_report_project_id`——新 view 也不得调用该 helper。

---

## Shared Patterns

### Authentication

**Source:** `McpToolView` `server/mcp_tools/views.py` 260–287  
**Apply to:** `ReportSessionKnowledgeView`

`AccessTokenAuthentication` + `CookieJWTAuthentication` + `IsAuthenticated`；`handle_exception` 把未认证映射为 `authentication_failed` 401。不要新 permission class。

### Error envelope

**Source:** `server/mcp_tools/errors.py` 10–15  
**Apply to:** 401/400（及 persist 失败 5xx）

```python
{"error_code": error_code, "detail": detail}
```

挂钩失败**不是** error envelope，是 200 + `accepted=true` + `reason=...`。

### Ledger / metrics

**Source:** `McpToolView._record` 305–344  
**Apply to:** 成功路径必须 `_record(..., traces=[])`

禁止手写 `ToolCallRecord` / 第二套 QPS。禁止 `traces` 塞问答。MCP 路径 Ledger 审计 ≠ Capture 正文（141 `test_persist_does_not_write_memory_or_ledger` 在 service 层断言无 Ledger；MCP 层允许 `_record`，正文仍只在 `SessionCapture`）。

### Persist as only writer

**Source:** `CaptureService.persist` + `test_capture_inv6_guard.py`  
**Apply to:** view 唯一业务写调用

透传 `actor=request.user`、`initiated_by_user_id=request.user.id`。不要 view 内 `normalize_git_url` / `resolve_allowed_*`。

### Three-face contract

**Sources:** `test_schema_snapshot.py`、`test_mcp_package_alignment.py`、`mcp/src/tools.ts` `FRIDAY_TOOLS`  
**Apply to:** 仅 `report_session_knowledge` 字段级相等；全工具只锁**名集**。

`test_skills_snapshot_guard.py`：`report_` 前缀已覆盖新名；本阶段不写 skills 则文档 ⊆ snapshot 仍绿。

---

## Anti-Patterns（Planner 必写进 PLAN 禁止项）

| Anti-pattern | Analog / evidence | Why it fails Phase 142 |
|--------------|-------------------|------------------------|
| `_resolve_report_project_id` 当接受门闩 | `views.py` 3719–3738, 3772–3789 | 无/多命中 → `accepted=false` + `branch_unresolved` **不入库**（MCP-02 反面） |
| `evaluate_writeback_quality` / 短答案拒收 | `ReportProjectKnowledgeView` 3802–3819 | Capture 无质量门；短 Q/A 仍应收 |
| `MemoryService.create_draft` / `append` / `record_hook_writeback` | 3822–3829, 3908–3913 | MCP-04；INV-6 账本是 `SessionCapture` |
| 成功 `HTTP_201_CREATED` | 3846 | 与挂钩失败 200 分裂；CONTEXT 锁定 200 |
| `accepted=false` 表示挂钩失败 | active `_reject` 3863–3877 | 新工具挂钩失败仍 `accepted=true` |
| View `SessionCapture.objects.create` | INV-6 `test_capture_inv6_guard.py` | CI 红 |
| `generator()` 注解 | `tools.ts` 865–871, 935 | `idempotentHint: false` 违反「可幂等写」 |
| 修旧 snapshot 漂移 | `report_project_knowledge` request 三键 | MCP-03 明确禁止 |
| persist 传 `client=` | `CaptureService.persist` 无该参数 | 模型无列；请求收、view 丢 |
| token 字段 `IntegerField` | 141 模型 `CharField` + `_scalar_or_unknown` | 数字/缺省应变 `unknown` 而非 400 |
| View 再打带正文的 lifecycle | persist 已有 `session_capture_persist_*` | OBS-02；勿复制问答/git URL |
| `aschedule_ingestion` / eval | Phase 143 | 本阶段 `pending_eval` 即可 |
| 扩展 `report_project_knowledge` 成 Capture | ROADMAP MCP-04 | 旧工具保留项目门闩 + git-diff 记忆 |

---

## Exact symbols (planner cheat sheet)

| Symbol | Path |
|--------|------|
| `CaptureService.persist` / `CapturePersistResult` | `server/initiatives/services/capture_service.py` |
| `SessionCapture` | `initiatives.models`（view 只读断言用，不 create） |
| `McpToolView._begin` `_validate` `_record` | `server/mcp_tools/views.py` |
| `_resolve_report_project_id` | **禁止**新 view 引用 |
| `ReportProjectKnowledgeView` | 壳参考 + MCP-04 隔离 |
| `TOOL_SCHEMA_SNAPSHOT` | `server/mcp_tools/serializers.py` |
| `FRIDAY_TOOLS` / `TOOL_ANNOTATIONS` | `mcp/src/tools.ts` |
| `callFridayTool` | `mcp/src/server.ts` |
| `error_response` | `server/mcp_tools/errors.py` |
| `mcp_client` | `server/tests/mcp_tools/conftest.py` |

---

## Contract alignment tests

| Guard | What it locks | Change in 142 |
|-------|---------------|---------------|
| `test_registered_tools_match_snapshot` | urls 工具名 == snapshot 键 | 加 path + snapshot 键即覆盖 |
| `test_mcp_read_tool_schema_snapshot` | snapshot 字面量全表 | **必须**加新工具 request/response 全键 |
| `test_mcp_package_tools_match_server_snapshot` | `tools.ts` `name:` == snapshot 键 | 加 FRIDAY_TOOLS 条目 |
| **new** `test_report_session_knowledge_request_keys_aligned` | serializer.fields ↔ snapshot.request ↔ npm properties | Wave 0 必写 |
| `test_report_project_knowledge.py` 全文件 | 旧门闩 / 201 / `branch_unresolved` | 只跑不改语义 |
| `test_capture_inv6_guard.py` | 无旁路 SessionCapture 写 | 新 view 零 ORM create |
| `test_skills_snapshot_guard` | skills ⊆ snapshot；前缀覆盖 | 不加 skills 则无需改 |

---

## No Analog Found

无。所有拟改文件都有同目录/同角色对照。业务状态机已在 Phase 141，本阶段没有「从零发明挂钩」的文件。

## Metadata

**Analog search scope:** `server/mcp_tools/`（views, serializers, urls, errors）、`mcp/src/tools.ts` + `server.ts`、`server/initiatives/services/capture_service.py`、`server/tests/mcp_tools/`、`server/tests/initiatives/test_capture_*.py`、`.planning/phases/141-capture/141-VERIFICATION.md`

**Files scanned:** ~20 primary + grep 定位  
**Pattern extraction date:** 2026-08-28
