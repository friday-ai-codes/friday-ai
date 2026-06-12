# Phase 13: 统一摄取与版本化 - Pattern Map

**Mapped:** 2026-06-11
**Files analyzed:** 15（新建 10 + 修改 5）
**Analogs found:** 12 / 15（3 个文件无直接类比，按 RESEARCH 规格自建）

> 行号基于当前工作区（git 有未提交改动）；planner 落任务时以函数名/语义锚点为主、行号为辅。

## File Classification

| New/Modified File | Role | Data Flow | Closest Analog | Match Quality |
|-------------------|------|-----------|----------------|---------------|
| `server/knowledge/ingestion.py`（新建） | service（摄取核心） | event-driven + CRUD | `server/code_relations/signals.py`（调度层）+ `server/knowledge/graph_store.py::invalidate_entity_version`（事务层） | role-match（组合） |
| `server/knowledge/chunking.py`（新建） | utility | transform | 无（indexer/CodeParser 被 RESEARCH 明确裁决不复用） | no-analog |
| `server/knowledge/vector_ops.py`（新建） | service（Qdrant 写薄层） | file-I/O（向量库写） | `server/knowledge/collection.py` + `server/services/indexer.py::_build_points` | exact（语义沿 collection.py） |
| `server/knowledge/sources/__init__.py`（新建） | config/barrel | — | `server/workflows/engine/__init__.py` 式 curated re-export | role-match |
| `server/knowledge/sources/coding_plan.py`（新建） | service（normalizer） | transform | 无直接类比；字段取材锚定 `chat/models.py::CodingPlan` | no-analog |
| `server/knowledge/sources/mcp_plan.py`（新建） | service（normalizer） | transform | 无直接类比；字段取材锚定 `mcp_tools/technical_plan_service.py` | no-analog |
| `server/knowledge/management/commands/reconcile_delivery_knowledge.py`（新建） | command | batch | `server/code_relations/management/commands/verify_payload_consistency.py` | exact |
| `server/knowledge/migrations/0002_*.py`（新建，vector_synced） | migration | — | `server/knowledge/migrations/0001_initial.py` | exact |
| `server/tests/knowledge/test_ingestion.py` / `test_chunking.py` / `test_triggers.py` / `test_reconcile.py`（新建） | test | — | `server/tests/knowledge/conftest.py` + 既有 test_collection.py 模式 | exact |
| `server/tests/knowledge/conftest.py`（扩展 mock_embedding） | test fixture | — | 同文件 `mock_qdrant_client`（L102–114） | exact |
| `server/chat/models.py`（修改：CodingPlan 两方法接线） | model | request-response | 接线模板见 Pattern Assignments | exact（锚点已实读） |
| `server/chat/coding_session_service.py`（修改：create_sessions_for_plan 尾部） | service | request-response | 同上 | exact |
| `server/mcp_tools/technical_plan_service.py`（修改：acreate 后接线） | service | request-response | 同上 | exact |
| `server/mcp_tools/work_item_execution_service.py`（修改：成功尾部接线） | service | request-response | 同上 | exact |
| `server/knowledge/management/commands/rebuild_delivery_knowledge.py`（修改：_rebuild 扩展全量重嵌入） | command | batch | 自身（TODO 锚点 L10–11） | exact |

## Pattern Assignments

### `server/knowledge/ingestion.py`（service，event-driven + CRUD）

**Analog 1（调度层）：** `server/code_relations/signals.py` — 仓库唯一成熟的 "on_commit + run_in_background + 异常隔离" 范式。

**on_commit 注册 + rollback 边界**（signals.py 88–92）：

```88:92:server/code_relations/signals.py
def _accumulate_dirty(repository_id: str, source_ids: list[uuid.UUID]) -> None:
    """累积 dirty source_chunk_ids 到 thread-local，注册 commit 后批量 flush。"""
    pending = _get_pending()
    pending.setdefault(repository_id, set()).update(source_ids)
    transaction.on_commit(_flush_pending)
```

**run_in_background 投递 + 异常隔离（"永不阻塞主流程"纪律）**（signals.py 95–123）：

```106:123:server/code_relations/signals.py
    try:
        run_in_background(
            lambda: enqueue_edge_build(repository_id, source_ids),
            name=f"chunkregistry-reconcile-{repository_id}",
        )
        logger.info(
            "chunk_registry_reconcile_scheduled",
            repository_id=repository_id,
            dirty_sources=len(source_ids),
        )
    except Exception as exc:
        logger.warning(
            "chunk_registry_reconcile_schedule_failed",
            repository_id=repository_id,
            dirty_sources=len(source_ids),
            error=str(exc),
            error_type=type(exc).__name__,
        )
```

**关键差异（仓库无先例，RESEARCH Pattern 2 / A1）**：signals.py 是 sync signal handler，本阶段 4 个触发点全是 async——`aschedule_ingestion` 必须 `await sync_to_async(_register)()` 包裹 `transaction.on_commit` 注册（thread_sensitive=True 保证与 ORM 同线程），不能在 coroutine 里直接调。这是 Wave 0 首验点。

**run_in_background factory 契约**（`server/services/background_runner.py` 98–119）——必须传无参 factory 不传 coroutine：

```98:110:server/services/background_runner.py
def run_in_background(
    coro_factory: Callable[[], Awaitable[T]],
    *,
    name: str | None = None,
) -> Future[T]:
    """在常驻 worker 线程的事件循环里运行 coroutine。

    必须传 *factory*（无参函数返回 coroutine）而不是 coroutine 本身，因为
    coroutine 只能在创建它的事件循环里 await — 跨线程提交时由 worker loop
    在自己上下文里 call 这个 factory，得到一个新鲜的、绑定到 worker loop
    的 coroutine 对象。

    这避免了 "coroutine ... was created in a different event loop" 类问题。
```

**Analog 2（事务层）：** `server/knowledge/graph_store.py::invalidate_entity_version`（L449–485）— "sync 事务函数 + sync_to_async 包装" 的 `_persist_sync` 直接模板：

```464:478:server/knowledge/graph_store.py
    _require_aware(invalid_at, "invalid_at")

    def _invalidate_sync() -> tuple[int, int]:
        with transaction.atomic():
            version_count = KnowledgeEntityVersion.objects.filter(
                entity_id=entity_id, is_latest=True, invalid_at__isnull=True
            ).update(invalid_at=invalid_at)
            edge_count = KnowledgeEdge.objects.filter(
                Q(source_entity_id=entity_id) | Q(target_entity_id=entity_id),
                invalid_at__isnull=True,
                expired_at__isnull=True,
            ).update(invalid_at=invalid_at)
        return version_count, edge_count

    version_count, edge_count = await sync_to_async(_invalidate_sync)()
```

注意（RESEARCH Pattern 3）：重摄取版本翻转**不要**直接调 `invalidate_entity_version`（它失效实体全部出入边，是"实体作废"语义）；`_persist_sync` 内手工翻转版本行，边只在关系目标变化时经 `graph_store.invalidate_edge` + `add_edge` 精细置位。

**Analog 3（content_hash 短路）：** `server/chat/models.py::CodingPlan.aget_or_create_for_conversation`（L243–279）— sha256 去重同款手法：

```256:266:server/chat/models.py
        content_hash = hashlib.sha256(tech_plan.encode("utf-8")).hexdigest()
        async for existing in cls.objects.filter(conversation=conversation).aiterator():
            existing_hash = hashlib.sha256(existing.tech_plan.encode("utf-8")).hexdigest()
            if existing_hash == content_hash:
                logger.info(
                    "coding_plan_get_or_created",
                    conversation_id=str(conversation.id),
                    plan_id=str(existing.id),
                    created=False,
                )
                return existing, False
```

**实体 id 派生唯一入口**（`server/knowledge/models.py` 80–108，禁止散落复刻 uuid5）：

```108:108:server/knowledge/models.py
    return uuid.uuid5(KNOWLEDGE_NAMESPACE, f"{kind}:{source_kind}:{source_id}")
```

幂等约束兜底（models.py）：`uniq_kentity_natural_key`（L157–160）、`uniq_kversion_entity_version` + `uniq_kversion_one_latest`（L225–234，并发翻转撞约束是期望行为，`select_for_update` 串行化责任在本阶段）、`uniq_kedge_active`（L296–300）。

---

### `server/knowledge/vector_ops.py`（service，向量库写薄层）

**Analog：** `server/knowledge/collection.py` — "get_client 直用 + sync_to_async + 异常一律重抛" 的既定先例（与 indexer 的静默语义刻意相反）：

```140:157:server/knowledge/collection.py
    client = QdrantService.get_client()

    collections = await sync_to_async(client.get_collections)()
    existing_names = [c.name for c in collections.collections]

    if DELIVERY_KNOWLEDGE_COLLECTION not in existing_names:
        await sync_to_async(client.create_collection)(
            collection_name=DELIVERY_KNOWLEDGE_COLLECTION,
            vectors_config={
                "dense": models.VectorParams(
                    size=expected_dimension,
                    distance=models.Distance.COSINE,
                ),
            },
            sparse_vectors_config={
                "sparse": models.SparseVectorParams(),
            },
        )
```

**hybrid point 构造**（`server/services/indexer.py::_build_points` 3167–3184，named vectors 实证格式）：

```3167:3184:server/services/indexer.py
            if hybrid and sparse_vectors and i < len(sparse_vectors):
                from qdrant_client.http.models import SparseVector

                sparse = sparse_vectors[i]
                vector: Any = {
                    "dense": embedding,
                    "sparse": SparseVector(
                        indices=sparse["indices"],
                        values=sparse["values"],
                    ),
                }
            else:
                vector = embedding

            points.append({
                "id": str(chunk_id),
                "vector": vector,
                "payload": payload,
```

**payload 键集合必须 import 单一事实源**（`server/knowledge/collection.py` 54–75）：

```54:75:server/knowledge/collection.py
KNOWLEDGE_PAYLOAD_INDEXED_FIELDS: dict[str, models.PayloadSchemaType] = {
    "entity_kind": models.PayloadSchemaType.KEYWORD,
    "entity_id": models.PayloadSchemaType.KEYWORD,
    "version": models.PayloadSchemaType.INTEGER,
    "is_latest": models.PayloadSchemaType.BOOL,
    "project_id": models.PayloadSchemaType.KEYWORD,
    "repository_id": models.PayloadSchemaType.KEYWORD,
    "source_kind": models.PayloadSchemaType.KEYWORD,
    "event_time": models.PayloadSchemaType.DATETIME,
}

# 非索引但每个 point payload 必带的字段（Phase 13 摄取写入契约）：
# source_id（业务对象稳定 ID）、chunk_kind（切块类型）、file_path（来源路径，可空串）、
# text（切块原文）、embedding_model（向量来源模型）、version_id（KnowledgeEntityVersion PK）。
KNOWLEDGE_PAYLOAD_REQUIRED_FIELDS: tuple[str, ...] = (
    "source_id",
    "chunk_kind",
    "file_path",
    "text",
    "embedding_model",
    "version_id",
)
```

**upsert 调用与返回值检查**：`QdrantService.upsert_vectors_by_name`（qdrant_service.py 1013–1087）catch 全部异常后 `return False` 不重抛（L1051–1087 四个 except 分支全部 `return False`）——知识路径调用处**必须检查返回值并 raise**。分 batch ≤100 的编排手法见 indexer.py 1374–1378：

```1374:1378:server/services/indexer.py
                # upsert to overlay collection
                batch_size = 100
                for i in range(0, len(points), batch_size):
                    batch = points[i : i + batch_size]
                    await qdrant_upsert_vectors_by_name(collection_name, batch)
```

**tombstone / 删点不可复用 `batch_set_payload`**（qdrant_service.py 1317–1342）：该方法绑定 `repository_id` 推导 collection 名（L1346）、`wait=False`（L1365）且超时 catch 不重抛（docstring L1336–1341 明言"与 upsert_vectors 同语义"）——三点全部与知识路径要求相反。vector_ops 自建：`sync_to_async(client.set_payload)(collection_name=…, payload={"is_latest": False}, points=old_point_ids, wait=True)` 与 `sync_to_async(client.delete)(collection_name=…, points_selector=models.PointIdsList(points=old_point_ids), wait=True)`，失败重抛/响亮记录。

---

### `server/knowledge/chunking.py`（utility，transform）— 无类比，自建

indexer 的 CodeParser 是 tree-sitter 代码切块，RESEARCH 明确裁决不复用。规格按 RESEARCH Pattern 5（markdown 标题分段 + 贪心合并 ≤3000 字符 + chunk 0 = summary）。**唯一可借的模式**是确定性 uuid5 派生纪律（models.py L80–108 的 docstring 警告同款）：point id = `uuid.uuid5(KNOWLEDGE_NAMESPACE, f"point:{version_id}:{index}")`，`KNOWLEDGE_NAMESPACE` 从 `knowledge.models` import（models.py L77），拼接格式一旦落地即锁死。纯函数 + 同输入同输出的确定性以单测锁定。

---

### `server/knowledge/sources/coding_plan.py` / `mcp_plan.py`（normalizer，transform）— 无直接类比

模块形态参照仓库"领域 service 放 app 内"惯例（`mcp_tools/*_service.py`）。取材字段锚点：

- **coding_plan.py**：`CodingPlan` 字段 `title`（chat/models.py L189）、`tech_plan`（L195）、`affected_files`（L196）、`recommended_repository_ids`（L217）；content = `title + "\n\n" + tech_plan`（守住"对话原文不入图"）；project 经 `conversation.project` select_related 取。
- **mcp_plan.py**：`McpWorkItemTechnicalPlan` 的 `markdown`（technical_plan_service.py L501 acreate 入参，`render_technical_plan_markdown` 产物 L435）、`plan_body`（L500）、`repository_tasks`（L502）、三元组 `feishu_project_key/work_item_type/work_item_id`（L495–497）；同时产出 work_item 锚实体（source_id = `f"{feishu_project_key}:{work_item_type}:{work_item_id}"`，natural key 规则表 models.py L89–98 锁定）+ `HAS_PLAN` EdgeSpec。

注意 `select_related("context", "project")` 后台重读，避免 async 下隐式同步 DB 访问（coding_session_service.py L466–468 docstring 有同款约束警告）。

---

### `server/knowledge/management/commands/reconcile_delivery_knowledge.py`（command，batch）

**Analog（exact）：** `server/code_relations/management/commands/verify_payload_consistency.py` — 命令骨架、默认 dry-run + `--fix` opt-in、单点异常 skip 不崩整命令、表格+计数输出，全部照搬。

**BaseCommand 骨架 + add_arguments**（verify_payload_consistency.py 51–77）：

```51:77:server/code_relations/management/commands/verify_payload_consistency.py
class Command(BaseCommand):
    """校验 Qdrant payload.related_chunks 与 ChunkRegistry 一致性。"""

    help = (
        "校验 Qdrant payload.related_chunks 中 chunk_id 在 ChunkRegistry 仍存在；"
        "--fix 触发增量 reconcile（默认 dry-run）"
    )

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument(
            "--repo",
            type=str,
            default=None,
            help="Repository UUID；不传时遍历所有 is_deleted=False 仓库",
        )
        parser.add_argument(
            "--sample",
            type=int,
            default=100,
            help="每仓库随机采样的 chunk 数量上限（default 100）",
        )
        parser.add_argument(
            "--fix",
            action="store_true",
            help="发现 orphan 时调 enqueue_edge_build 触发增量 reconcile（默认 dry-run）",
        )
    ```

**批量 retrieve（1 次 roundtrip 替代 N 次）+ 单点异常隔离**（verify_payload_consistency.py 144–173）：

```146:162:server/code_relations/management/commands/verify_payload_consistency.py
        records_by_id: dict[str, Any] = {}
        try:
            records = client.retrieve(
                collection_name=collection_name,
                ids=[str(cid) for cid in sample_chunk_ids],
                with_payload=["related_chunks"],
            )
            for r in records:
                records_by_id[str(r.id)] = r
        except Exception as exc:
            logger.warning(
                "verify_payload_batch_retrieve_failed",
                repo_id=repo_id,
                sample_size=len(sample_chunk_ids),
                error=str(exc),
                error_type=type(exc).__name__,
            )
```

**--fix dispatch + drain 后台任务**（verify_payload_consistency.py 259–302，`asyncio.run(self._dispatch_and_drain(...))` 确保 fix 真正生效再退出命令）。汇总输出形态（L226–230）：`Summary: total_chunks_checked=N total_orphans=N total_skipped=N`。

检查项内容按 RESEARCH §Reconcile 五项表实现（latest 点存在性/payload 正确、非 latest tombstone、单 latest、孤儿点、DB 不变量）。

---

### `server/knowledge/management/commands/rebuild_delivery_knowledge.py`（修改，扩展全量重嵌入）

自身即类比——TODO 锚点已留（L10–11）。`_rebuild` 现状（L87–95）：

```87:95:server/knowledge/management/commands/rebuild_delivery_knowledge.py
    @staticmethod
    async def _rebuild() -> int:
        """删除 → 经 ensure 重建（创建 + payload index + 元信息更新都在 ensure 内完成）。

        任何异常不吞——自然冒泡为非零退出码。返回重建后的 dense 维度（醒目输出用）。
        """
        await sync_to_async(QdrantService.delete_collection_by_name)(DELIVERY_KNOWLEDGE_COLLECTION)
        await ensure_delivery_knowledge_collection()
        return await get_expected_dimension()
```

扩展：ensure 之后追加"从 `KnowledgeEntityVersion.objects.filter(is_latest=True)` 全量重嵌入"步骤（复用 ingestion 核心的 chunk+embed+upsert 向量步骤，不重走版本翻转）。

---

### 四个触发点接线（chat ×2 + MCP ×2，每处 3–5 行）

统一模板（RESEARCH Pattern 4，lazy import 防循环）：

```python
from knowledge.ingestion import IngestionRequest, aschedule_ingestion  # lazy import 防循环

await aschedule_ingestion(IngestionRequest(
    source_kind="mcp_technical_plan",
    source_id=str(artifact.id),
    trigger="mcp_plan_created",
))
```

精确插入位置（已实读验证）：

| 文件 | 锚点 | 插入位置 |
|------|------|---------|
| `server/chat/models.py` | `CodingPlan.aget_or_create_for_conversation`（L243）created=True 分支 | `acreate`（L267）+ logger.info 之后、`return plan, True`（L279）之前 |
| `server/chat/models.py` | `CodingPlan.aupdate_plan`（L281） | `asave`（L289）之后 |
| `server/chat/coding_session_service.py` | `create_sessions_for_plan`（L449） | 成功尾部 `return result`（L586）之前（per-repo `transaction.atomic` 之外） |
| `server/mcp_tools/technical_plan_service.py` | `build_work_item_technical_plan`（L368） | `McpWorkItemTechnicalPlan.objects.acreate`（L491–511）之后、`return TechnicalPlanResult(...)`（L527）之前 |
| `server/mcp_tools/work_item_execution_service.py` | `execute_work_item_repo_tasks`（L531） | output 组装（L583–597）之后、`return RepoTaskExecutionResult(...)`（L598）之前 |

注意：模型方法挂钩会让 `migrate_coding_sessions_to_plans` 历史迁移命令也触发摄取（RESEARCH Open Question 2，建议不排除，SUMMARY 记录副作用）。

---

### `server/tests/knowledge/test_*.py`（test）

**Analog（exact）：** `server/tests/knowledge/conftest.py` — 工厂闭包 + mock seam 模式直接复用：

```102:114:server/tests/knowledge/conftest.py
@pytest.fixture
def mock_qdrant_client(monkeypatch: pytest.MonkeyPatch) -> MagicMock:
    """QdrantService.get_client 的 MagicMock seam（test_collection.py 显式使用）。

    mock 的 ``get_collections.return_value`` / ``get_collection.return_value``
    由用例自行配置。非 autouse——只有触碰 Qdrant 的用例才需要它；
    pytest 全局 ``--disable-socket`` 是第二道保险（漏 mock 的真实 HTTP 直接被拦截）。
    """
    client = MagicMock()
    from services.qdrant_service import QdrantService

    monkeypatch.setattr(QdrantService, "get_client", classmethod(lambda cls: client))
    return client
```

既有工厂：`entity_factory`（L32–55，id 经 `generate_entity_id` 派生）、`version_factory`（L58–75）、`edge_factory`（L78–99）。新增 `mock_embedding` fixture：`monkeypatch.setattr(EmbeddingService, "generate_embeddings_batch", AsyncMock(return_value=[[0.1]*1024, ...]))` + SparseEncoderService.encode_batch 同步 monkeypatch。

**worker 线程隔离**：autouse `_reset_background_runner`（tests/conftest.py L36–59）已兜底 wait+reset——摄取核心测试直接 `await ingest(...)` 绕过调度层；调度层用 monkeypatch `run_in_background` 测投递行为，不真跑 worker 线程写库（RESEARCH Pitfall 5）。

---

## Shared Patterns

### structlog 结构化日志
**Source:** 全仓惯例（signals.py、graph_store.py、collection.py 同款）
**Apply to:** 全部新文件

```110:115:server/code_relations/signals.py
        logger.info(
            "chunk_registry_reconcile_scheduled",
            repository_id=repository_id,
            dirty_sources=len(source_ids),
        )
```

事件名 snake_case 前缀域名（本阶段用 `knowledge_ingest_*`）；error 分支必带 `error=str(exc), error_type=type(exc).__name__`。

### 异常隔离（触发点"永不阻塞主流程"）
**Source:** `server/code_relations/signals.py` L132–137（handler 顶层 try/except 全吞 + warning）
**Apply to:** `aschedule_ingestion` 顶层、4 个触发点接线；触发点测试含"ingestion 模块抛错时主流程仍成功"用例。

### 知识路径失败响亮（与 indexer 相反）
**Source:** `server/knowledge/collection.py` docstring L7–14（"任何 Qdrant 异常一律重抛，禁止静默吞掉"）
**Apply to:** `vector_ops.py` 全部写操作、`ingest()` 内 embedding None 检查（`EmbeddingService.generate_embeddings_batch` 失败项返回 None，embedding.py L139–160——任何 None 整体 abort）。

### aware datetime 纪律
**Source:** `server/knowledge/graph_store.py::_require_aware`（L81–85）
**Apply to:** 所有 event_time/valid_at/invalid_at 传参处；一律 `timezone.now()` 或确认源字段 aware。

### sync_to_async ORM 桥接
**Source:** `graph_store.py::invalidate_entity_version`（sync 事务函数 + `sync_to_async` 包装）、`collection.py`（client 同步调用包装）
**Apply to:** `_persist_sync`、vector_ops 全部 client 调用、sparse `encode_batch`（indexer.py L951 同款 `await sync_to_async(...)`）。

### 中文 docstring + 契约引用
**Source:** 全仓惯例（每个模块 docstring 引用 Phase/requirement ID 与 locked decision）
**Apply to:** 全部新文件（注明 INGEST-03/05/06/07/08 与 P1/P2 防线归属）。

## No Analog Found

| File | Role | Data Flow | Reason |
|------|------|-----------|--------|
| `server/knowledge/chunking.py` | utility | transform | 仓库唯一切块器是 tree-sitter 代码切块（CodeParser），对 markdown 知识文本无意义；按 RESEARCH Pattern 5 规格自建（~80 行纯函数） |
| `server/knowledge/sources/coding_plan.py` | normalizer | transform | 仓库无 "ORM 模型 → 统一 DTO" normalizer 先例；形态按 RESEARCH Pattern 1 DTO 规格自建 |
| `server/knowledge/sources/mcp_plan.py` | normalizer | transform | 同上 |

另：**async 上下文注册 `transaction.on_commit`** 全仓无先例（现有用法全在 sync signal handler）——RESEARCH Pattern 2 给出唯一正确写法（`await sync_to_async(_register)()`），列为 Wave 0 首验。

## Metadata

**Analog search scope:** `server/knowledge/`、`server/code_relations/`、`server/services/`、`server/chat/`、`server/mcp_tools/`、`server/tests/knowledge/`、`server/tests/conftest.py`
**Files scanned:** 14（全部实读或定向区段读取）
**Pattern extraction date:** 2026-06-11
