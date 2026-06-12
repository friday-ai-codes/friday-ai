# Phase 14: 全触发点接入与 diff 归档 - Pattern Map

**Mapped:** 2026-06-11
**Files analyzed:** 20（新建 7 + 修改 13）
**Analogs found:** 17 / 20（3 处无仓库内先例，按 RESEARCH 设计落地）

## File Classification

| 新建/修改文件 | 角色 | 数据流 | 最近 Analog | 匹配度 |
|---------------|------|--------|-------------|--------|
| `server/knowledge/sources/workflow_plan.py`（新） | normalizer/service | event-driven | `knowledge/sources/mcp_plan.py` | exact（双事件 + HAS_PLAN exclusive） |
| `server/knowledge/sources/task_result.py`（新） | normalizer/service | event-driven | `knowledge/sources/mcp_plan.py` | exact（双事件 + 边挂锚事件） |
| `server/knowledge/sources/feishu_work_item.py`（新） | normalizer/service | event-driven | `knowledge/sources/coding_plan.py` + `mcp_plan.py` | exact（单/双事件 + 源缺失降级） |
| `server/knowledge/diff_archive.py`（新） | service + 纯函数 | file-I/O + transform | `knowledge/chunking.py`（纯函数哲学）+ `orchestration/coding_graph.py:582-594`（凭证→client） | role-match |
| `server/knowledge/models.py`（改，+CodeChangeArchive） | model | CRUD | 同文件 `KnowledgeEntityVersion`/`KnowledgeEdge`（Phase 12 约束范式） | exact（同文件内） |
| `server/knowledge/migrations/0003_*.py`（新） | migration | — | `knowledge/migrations/0001_initial.py`（makemigrations 自动生成） | exact |
| `server/knowledge/ingestion.py`（改，EdgeSpec+apply_edge_specs） | service | event-driven | 同文件 `apply_edge_specs`（L295-334） | exact（同文件扩展） |
| `server/knowledge/chunking.py`（改，diff-aware 分支） | utility 纯函数 | transform | 同文件 `_split_segments`/`_hard_split` | exact（同文件扩展） |
| `server/knowledge/sources/__init__.py`（改，注册 3 行） | config/registry | — | 同文件 `_NORMALIZERS` | exact |
| `server/knowledge/graph_store.py`（改，可选 `chunk_in_edges`） | service | request-response | 同文件 `invalidate_edge`（纯 ORM 方法风格） | exact |
| `server/workflows/nodes/ai/plan_generation.py`（改，接线） | 宿主接线 | event-driven | `chat/coding_session_service.py:586-591` | exact（13-03 范式） |
| `server/workflows/engine/scheduler.py`（改，approve_node 接线） | 宿主接线 | event-driven | 同上 | exact |
| `server/orchestration/coding_graph.py`（改，create_pr_or_skip_node 接线 ×2） | 宿主接线 | event-driven | 同上 | exact |
| `server/workflows/nodes/ai/coding.py`（改，_resume_after_containers 接线） | 宿主接线 | event-driven | 同上 | exact |
| `server/feishu/views.py`（改，三 handler 接线） | 宿主接线 | event-driven | 同上 | exact |
| `server/services/git_platform/*`（改，get_branch_diff 抽象） | service/client | request-response | `git_platform/github_client.py:168-214` `get_merge_request_diff` | exact（同类方法） |
| `server/tests/knowledge/test_triggers.py`（改，三组新用例） | test | — | 同文件 `captured_requests` fixture（L197-210）+ `TestExceptionIsolation`（L416+） | exact |
| `server/tests/knowledge/conftest.py`（改，fake git/feishu client） | test fixture | — | `test_triggers.py` monkeypatch 范式 | role-match |
| `server/tests/knowledge/test_diff_archive.py`（新） | test | — | `tests/knowledge/test_chunking.py`（纯函数 golden）+ `test_ingestion.py`（DB 幂等） | role-match |
| `server/tests/knowledge/test_modifies_chunk.py`（新） | test | — | `test_ingestion.py` 幂等三连发模式 | role-match |

## Pattern Assignments

### 1. 五处宿主接线（plan_generation / scheduler.approve_node / coding_graph / coding.py / feishu/views.py）

**Analog:** `server/chat/coding_session_service.py`（Phase 13 已验证的唯一正确形态）

**接线模式**（lines 586-591，逐字复制此形态——lazy import + 属性调用，13-03 Deviation 1 定案，保证 monkeypatch 可拦截且不命中 grep 验收误判）：

```586:591:server/chat/coding_session_service.py
    if result.created:
        from knowledge import ingestion  # lazy import 防循环

        await ingestion.aschedule_ingestion(
            ingestion.IngestionRequest("coding_plan", str(plan.id), "chat_coding_started")
        )
```

**纪律**：接线处**不包 try/except**——`aschedule_ingestion` 内部已异常全吞（`knowledge/ingestion.py:105-130`，warning 不上抛）。禁止 `from knowledge.ingestion import aschedule_ingestion`（RESEARCH Pitfall 9）。

**各锚点插入位置（行级，源自 RESEARCH 实读）：**

| 宿主文件 | 锚点 | trigger / source_id |
|---------|------|---------------------|
| `workflows/nodes/ai/plan_generation.py` `execute` | L396-399 `result.status != "failed"` 的 else 分支内（`emit_sub_step("review", COMPLETED)` 之后、`return result` 之前） | `("workflow_plan", f"{context.execution_id}:{context.node_id}", "workflow_plan_generated")` |
| `workflows/engine/scheduler.py` `approve_node` | L1210-1215 `hooks.trigger("node_approved", ...)` 之后；按 `node_type == "ai_plan_approval"` 过滤（node FK 未必预加载，需 `sync_to_async` 安全取或补 `select_related("node")`）；source_id 沿 execution 查 ai_plan_generation 节点 key（RESEARCH OQ-2 推荐） | `("workflow_plan", <生成节点 key>, "workflow_plan_approved")` |
| `orchestration/coding_graph.py` `create_pr_or_skip_node` | skip 分支 L571-579（`amark_completed(pr_url="")` 后）与 PR 成功分支 L605-613（`amark_completed(pr_url=result.mr_url)` 后）各一次 | `("task_result", str(session_id), "chat_coding_pr_skipped" / "chat_coding_pr_created")` |
| `workflows/nodes/ai/coding.py` `_resume_after_containers` | L620 `mr_results.append` 之后逐 session 投递（MR 已建，Pitfall 1：不可挂容器回调） | `("task_result", str(session_id), "workflow_coding_completed")` |
| `feishu/views.py` `_handle_workitem_create`(L751) / `_handle_workitem_status`(L763) / `_handle_workitem_update`(L857) | 各 handler 尾部（既有 `_fetch_and_update_work_item` 调用之后），只投 ID 零取材（Pitfall 3） | `("feishu_work_item", f"{project.feishu_project_key}:{type}:{id}", "feishu_workitem_<event>")` |

宿主 handler 既有风格参考（接线追加在此类尾部）：

```751:761:server/feishu/views.py
    async def _handle_workitem_create(self, project, payload, trigger_log):
        """处理工作项创建事件。"""
        work_item_id = payload.get("id")
        work_item_type = payload.get("work_item_type_key", "story")

        if not work_item_id:
            logger.warning("workitem_create_missing_id")
            return

        await self._fetch_and_update_work_item(project, work_item_id, work_item_type, trigger_log)
        logger.info("workitem_create_processed", work_item_id=work_item_id)
```

---

### 2. `sources/workflow_plan.py` / `task_result.py`（normalizer，双事件 + 边）

**Analog:** `server/knowledge/sources/mcp_plan.py`（双事件 + exclusive 边的唯一既有实现，逐结构复制）

**源缺失降级模式**（lines 31-43——所有新 normalizer 开头一致）：

```31:43:server/knowledge/sources/mcp_plan.py
    artifact = (
        await McpWorkItemTechnicalPlan.objects.select_related("context", "project")
        .filter(id=request.source_id)
        .afirst()
    )
    if artifact is None:
        logger.warning(
            "knowledge_normalize_source_missing",
            source_kind=request.source_kind,
            source_id=request.source_id,
            trigger=request.trigger,
        )
        return []
```

**锚事件 + exclusive EdgeSpec 模式**（lines 74-102；workflow_plan 的 work_item—HAS_PLAN→tech_plan、task_result 的 tech_plan—IMPLEMENTED_BY→code_change 均按此挂——**边永远挂在 source 端事件上**，EdgeSpec 语义为"以本事件实体为 source 的出边"）：

```92:102:server/knowledge/sources/mcp_plan.py
        edges=(
            EdgeSpec(
                relation=EdgeRelation.HAS_PLAN,
                target_entity_id=generate_entity_id(
                    "tech_plan", "mcp_technical_plan", str(artifact.id)
                ),
                exclusive=True,
            ),
        ),
    )
    return [work_item_event, tech_plan_event]
```

**模块结构模式**（imports + docstring 风格，lines 14-24——中文 docstring 引用契约/Plan ID，`__all__ = ["normalize"]`，业务模型 lazy import 在函数体内）：

```14:24:server/knowledge/sources/mcp_plan.py
from __future__ import annotations

import structlog

from knowledge.ingestion import EdgeSpec, IngestionEvent, IngestionRequest
from knowledge.models import EdgeRelation, EntityKind, EntityOrigin, generate_entity_id

logger = structlog.get_logger(__name__)

__all__ = ["normalize"]
```

**IngestionEvent 字段填法**（`coding_plan.py:47-65` 单事件参考——title 截断、project_id 判空转 str、event_time 取业务时间）：

```47:65:server/knowledge/sources/coding_plan.py
    return [
        IngestionEvent(
            kind=EntityKind.TECH_PLAN,
            origin=EntityOrigin.CHAT,
            source_kind="coding_plan",
            source_id=str(plan.id),
            title=title,
            # OQ-3 锁定拼法：title + 空行 + tech_plan，别无其他来源
            content=f"{plan.title}\n\n{plan.tech_plan}",
            payload={
                "title": plan.title,
                "affected_files": plan.affected_files,
                "recommended_repository_ids": plan.recommended_repository_ids,
            },
            project_id=project_id,
            # 多仓方案无单一仓库归属
            repository_id=None,
            event_time=plan.updated_at,
        )
    ]
```

**task_result 特别注意**：normalizer 即 DiffArchiver 的后台执行体（重 IO 全在此），归属字段从服务端权威 FK 取（`CodingSession.repository` / `session.node_execution`），不信任 `session.last_output`；审批事件（workflow_plan_approved）必须把审批信息追加进 content 否则被 hash 短路（RESEARCH Pitfall 5）。

---

### 3. `sources/__init__.py` 注册（3 行加法）

**Analog:** 同文件 `_NORMALIZERS`（lines 19-22）：

```19:22:server/knowledge/sources/__init__.py
_NORMALIZERS: dict[str, str] = {
    "coding_plan": "knowledge.sources.coding_plan",
    "mcp_technical_plan": "knowledge.sources.mcp_plan",
}
```

新增三行：`"workflow_plan"` / `"task_result"` / `"feishu_work_item"` → 对应模块路径。注意 `feishu_work_item` 此前只作为 mcp_plan 内的锚实体 source_kind 出现，注册后 13-03 轻量锚同 key 重摄即升级为全量快照（零迁移）。

---

### 4. `knowledge/models.py` 新增 `CodeChangeArchive`

**Analog:** 同文件 `KnowledgeEntityVersion`（L180-253）与 `KnowledgeEdge`（L256-337）——Phase 12 模型范式：uuid4 PK、SET_NULL 组织维度 FK、`source_kind + source_id` 弱引用、Meta constraints + indexes 全显式命名、中文 verbose_name 与 help_text。

**约束/索引命名模式**（lines 152-174，新表照此风格：`uniq_codechange_source_commit` / `idx_cca_*`）：

```155:174:server/knowledge/models.py
        constraints = [
            # 幂等 natural key：Phase 13 摄取 upsert 的锚点
            UniqueConstraint(
                fields=["kind", "source_kind", "source_id"],
                name="uniq_kentity_natural_key",
            ),
            # DB 层枚举兜底（bulk_create / 直接 Manager.create 绕过 full_clean 时挡 typo）
            CheckConstraint(
                condition=Q(kind__in=EntityKind.values),
                name="kentity_kind_valid",
            ),
            CheckConstraint(
                condition=Q(origin__in=EntityOrigin.values),
                name="kentity_origin_valid",
            ),
        ]
        indexes = [
            models.Index(fields=["project", "kind"], name="idx_kentity_proj_kind"),
            models.Index(fields=["source_kind", "source_id"], name="idx_kentity_source"),
        ]
```

**弱引用 + SET_NULL FK 模式**（lines 139-145，CodeChangeArchive.repository 同款）：

```139:145:server/knowledge/models.py
    repository = models.ForeignKey(
        "repositories.Repository",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="knowledge_entities",
    )
```

完整字段清单按 RESEARCH §CodeChangeArchive schema（L209-250）落地；**同步加一条 KnowledgeEdge partial unique**：`(source_entity, target_chunk_id, relation)` condition 同 `uniq_kedge_active`（Pitfall 4 DB 防线，RESEARCH 推荐）。migration 用 `makemigrations` 自动生成（`0003_`），phase gate 用 `makemigrations --check --dry-run` 验干净。

---

### 5. `knowledge/ingestion.py` 扩展 EdgeSpec + apply_edge_specs（chunk 边幂等，RESEARCH 选项 A）

**Analog:** 同文件既有实现（扩展而非新写）。

**EdgeSpec 现状**（lines 75-86，增加 `target_chunk_id: uuid.UUID | None = None` + `metadata: dict | None = None`，保持 frozen dataclass）：

```75:86:server/knowledge/ingestion.py
@dataclass(frozen=True)
class EdgeSpec:
    """出边规格：以本事件实体为 source 的出边（规划定案 4）。

    ``exclusive=True``（如 HAS_PLAN）表示同 relation 同时只允许指向一个 target：
    重摄取时指向其他 target 的活跃边被逐条 ``invalidate_edge``，再建新边。
    """

    relation: str  # EdgeRelation 字面值
    target_entity_id: uuid.UUID  # 已派生目标实体 id（generate_entity_id 产物）
    exclusive: bool = False
```

**apply_edge_specs 幂等核心模式**（lines 309-334——neighbors 查活跃出边 → 同 target 跳过 → add_edge + IntegrityError 幂等放弃；chunk 边按 `edge.target_chunk_id` 比对，`neighbors` 返回的 EdgeRecord 已含该字段，`graph_store.py:285`）：

```309:334:server/knowledge/ingestion.py
    for spec in edges:
        existing = await graph_store.neighbors(
            entity_id, relations=[spec.relation], direction="out"
        )
        if any(edge.target_id == spec.target_entity_id for edge in existing):
            continue
        if spec.exclusive:
            for edge in existing:
                if edge.target_id != spec.target_entity_id:
                    await graph_store.invalidate_edge(edge.edge_id, invalid_at=event_time)
        try:
            await graph_store.add_edge(
                source_id=entity_id,
                target_id=spec.target_entity_id,
                relation=spec.relation,
                valid_at=event_time,
            )
        except IntegrityError as exc:
            logger.warning(
                "knowledge_ingest_edge_conflict",
                source_id=str(entity_id),
                target_id=str(spec.target_entity_id),
                relation=spec.relation,
                error=str(exc),
                error_type=type(exc).__name__,
            )
```

**graph_store.add_edge 已就位接口**（XOR 校验，chunk 边直接传 `target_chunk_id` + `metadata`）：

```156:175:server/knowledge/graph_store.py
    async def add_edge(
        self,
        *,
        source_id: uuid.UUID,
        target_id: uuid.UUID | None = None,
        target_chunk_id: uuid.UUID | None = None,
        relation: str,
        valid_at: datetime,
        metadata: dict | None = None,
    ) -> uuid.UUID:
        """新增一条边，返回 edge id。

        target_id（实体边）与 target_chunk_id（chunk 边，Phase 14）XOR 二选一：
        DB 层 ``kedge_target_xor`` 约束兜底，接口层先行校验给出友好错误。
        """
        require_aware(valid_at, "valid_at")
        if relation not in EdgeRelation.values:
            raise ValueError(f"非法 relation 值: {relation!r}（必须 ∈ {EdgeRelation.values}）")
        if (target_id is None) == (target_chunk_id is None):
            raise ValueError("target_id 与 target_chunk_id 必须二选一（XOR）")
```

可选 `chunk_in_edges(chunk_id)` 反查方法照同文件 `invalidate_edge`（L194-217）的"纯 ORM + 结构化日志"方法风格写，维持图访问收口。

---

### 6. `knowledge/chunking.py` diff-aware 分支

**Analog:** 同文件既有纯函数（探测→split→硬切→合并管道，扩展不破坏确定性契约）。

**探测/分段模式**（lines 31-52——diff 分支照此加 `_DIFF_PROBE_RE = re.compile(r"^diff --git ", re.MULTILINE)` 与 `re.split(r"^(?=diff --git )", ...)`，超长文件段按 `^@@ ` 再切，仍超长走 `_hard_split`）：

```31:52:server/knowledge/chunking.py
# markdown 二级及以下标题行（lookahead split：标题行保留在所属段首）
_HEADING_SPLIT_RE = re.compile(r"^(?=##+ )", re.MULTILINE)
_HEADING_PROBE_RE = re.compile(r"^##+ ", re.MULTILINE)
_BLANK_LINE_RE = re.compile(r"\n\s*\n")


@dataclass(frozen=True)
class KnowledgeChunk:
    """切块值对象：chunk 0 固定 ``summary``（整体召回面），其余 ``section``。"""

    index: int
    text: str
    chunk_kind: str


def _split_segments(content: str) -> list[str]:
    """按 markdown 标题（``^##+ ``）分段；无标题时按双换行分段。"""
    if _HEADING_PROBE_RE.search(content):
        parts = _HEADING_SPLIT_RE.split(content)
    else:
        parts = _BLANK_LINE_RE.split(content)
    return [part.strip() for part in parts if part.strip()]
```

**硬约束**：`chunk_knowledge_text(title, content)` 签名不变、纯函数确定性不变（`revectorize_version` ingestion.py:347 从 content 重派生，Pitfall 8）；diff chunk 标 `chunk_kind="diff"`（payload 自由字符串，零迁移）；`MAX_CHUNK_CHARS = 3000`（L29）沿用。

---

### 7. `knowledge/diff_archive.py`（DiffArchiver service + 纯函数）

**Analog（组合）：** 纯函数层（unidiff 解析/生成文件判定/压缩）仿 `chunking.py` 哲学（模块顶常量 + 无 IO 纯函数 + frozen dataclass 值对象）；service 层凭证→client 取法仿 `coding_graph.py`。

**凭证解析 + client 构造模式**（lines 582-594——锁定决策：DB 加密凭证经 service 层，缺凭证降级不 raise）：

```582:594:server/orchestration/coding_graph.py
    try:
        cred = await GitCredential.objects.aget(repository=repo)
        token = decrypt_value(cred.encrypted_token or "")
    except GitCredential.DoesNotExist:
        error_msg = "Git 凭据未配置，无法创建 PR"
        await coding_session.amark_failed(error_msg)
        logger.warning(
            "coding_graph_pr_no_credential",
            coding_session_id=state["coding_session_id"],
        )
        return {"phase": "failed", "error": error_msg}

    client = get_git_platform_client(repo, token)
```

（DiffArchiver 内缺凭证的降级动作改为 warning + 跳过归档，不 mark failed——后台路径无宿主可失败。）

**diff 拉取消费的既有方法签名**（`get_merge_request_diff` 默认参数是 code_review 语义，DiffArchiver 必须放大并尊重 truncated，Pitfall 2）：

```168:173:server/services/git_platform/github_client.py
    async def get_merge_request_diff(
        self,
        mr_id: str,
        max_files: int = 50,
        max_diff_lines: int = 500,
    ) -> MRDiffResult:
```

git_platform 扩展 `get_branch_diff(source, target) -> MRDiffResult` 抽象方法时，结构照 `get_merge_request_diff` 实现体（L184-214：`asyncio.to_thread` 包同步 SDK 调用 + truncated 标记 + MRDiffFile 列表），GitLab 包 `repository_compare`、GitHub 包 `compare` + `file.patch`。

---

### 8. 测试文件（test_triggers.py 扩展 / test_diff_archive.py / test_modifies_chunk.py / conftest.py）

**Analog:** `server/tests/knowledge/test_triggers.py`（投递断言 + 异常隔离两大范式逐字复用）。

**投递捕获 fixture**（lines 197-210——全部新触发点测试复用此 fixture，断言 `(source_kind, source_id, trigger)` 三元组）：

```197:210:server/tests/knowledge/test_triggers.py
@pytest.fixture
def captured_requests(monkeypatch: pytest.MonkeyPatch) -> list[IngestionRequest]:
    """monkeypatch ``knowledge.ingestion.aschedule_ingestion`` 收集投递请求。

    接线处经 ``from knowledge import ingestion`` + 调用时属性解析，
    monkeypatch 模块属性即可拦截全部 5 锚点投递（Pitfall 5：不真跑 worker）。
    """
    captured: list[IngestionRequest] = []

    async def _collect(request: IngestionRequest) -> None:
        captured.append(request)

    monkeypatch.setattr("knowledge.ingestion.aschedule_ingestion", _collect)
    return captured
```

**异常隔离模式**（lines 419-440——`run_in_background` 抛 RuntimeError，断言宿主流程仍成功；新触发点对 approve_node / create_pr_or_skip / webhook handler 各写一例）：

```426:429:server/tests/knowledge/test_triggers.py
        def _boom(factory, *, name=None):
            raise RuntimeError("runner down")

        monkeypatch.setattr("knowledge.ingestion.run_in_background", _boom)
```

**同步工厂 + sync_to_async 建数据模式**（lines 217-238 `_make_fanout_plan`——conftest 新 fixture（fake git client / fake FeishuClient）照此风格；git client mock 另可参照 `tests/test_batch_pr.py` / `tests/mcp_tools/test_mr_tools.py` 既有先例）。

**幂等三连发模式**（`test_ingestion.py`——同事件投 3 次断言边数不变；MODIFIES_CHUNK 无 DB 唯一约束防线，此用例必写）。纯函数测试（unidiff 解析/生成文件判定/zlib 往返/大 diff 夹具）参照 `test_chunking.py` golden 断言风格，大 diff 夹具用 RESEARCH `build_large_diff()` 程序化生成不提交大文件。

---

## Shared Patterns

### 触发接线（应用于全部 5 个宿主文件）
**Source:** `server/chat/coding_session_service.py:586-591`
形态铁律：`from knowledge import ingestion`（lazy，函数体内）+ `ingestion.aschedule_ingestion(ingestion.IngestionRequest(...))` 属性调用 + 接线处零 try/except + 只传 ID 零取材。

### 源缺失/取材失败降级（应用于全部 3 个 normalizer + DiffArchiver）
**Source:** `server/knowledge/sources/mcp_plan.py:36-43`
`afirst()` 判 None → `logger.warning("knowledge_normalize_source_missing", source_kind=..., source_id=..., trigger=...)` → return []；部分缺料（如飞书文档拉取失败）降级产出降配事件 + warning，不 raise。

### 结构化日志（应用于所有新文件）
**Source:** 全仓约定（如 `graph_store.py:184-191`）
`structlog.get_logger(__name__)` + 事件名 snake_case 带域前缀（`knowledge_*`）+ key-value 全 str 化（uuid 显式 `str(...)`）。

### async ORM 访问（应用于 normalizer / DiffArchiver / 接线处）
**Source:** `mcp_plan.py:31-35` / `scheduler.py:1218`
查询链 `select_related(...)` 防 async 隐式同步访问 + `afirst()/aget()/aexists()/acreate()`；同步工厂经 `sync_to_async` 包裹（测试同款）。

### 中文 docstring 契约引用（应用于所有新模块）
**Source:** `coding_plan.py:1-12` / `models.py:1-12`
模块 docstring 标注需求 ID（KMOD-05/INGEST-0x/ENH-01）与取材边界/锁定决策，函数 docstring 说明降级语义。

## No Analog Found

| 文件/部件 | 角色 | 原因 | 替代依据 |
|-----------|------|------|---------|
| `diff_archive.py` 的 unidiff 解析 | 纯函数 | 仓库内无任何 unidiff/diff 解析先例（grep 零命中） | RESEARCH §unidiff 解析要点（PyPI 官方 API，逐文件单独 PatchSet 解析） |
| `CodeChangeArchive.diff_compressed` | model 字段 | 仓库内无 BinaryField/zlib 先例（grep 零命中） | RESEARCH §压缩归档示例（zlib level 6 + sha256 + 双 size 记录） |
| 生成文件判定常量表 | utility | 无既有生成文件过滤逻辑 | RESEARCH §生成文件判定规则（GENERATED_PATH_PATTERNS / CONTENT_MARKERS） |

## Metadata

**Analog search scope:** `server/knowledge/`（含 sources/、migrations/、tests/knowledge/）、`server/chat/`、`server/orchestration/`、`server/workflows/`（nodes/ai/、engine/）、`server/feishu/`、`server/services/git_platform/`
**Files scanned:** 13 个 analog 实读（行级摘录）+ 2 次全仓 grep（BinaryField/zlib/unidiff 零命中确认、测试范式定位）
**Pattern extraction date:** 2026-06-11
