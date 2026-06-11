# Phase 12: 知识模型与图存储地基 - Pattern Map

**Mapped:** 2026-06-11
**Files analyzed:** 15（14 新建 + 1 修改）
**Analogs found:** 13 / 15（递归 CTE 与 Qdrant"拒绝式校验"两处无直接类比，以 RESEARCH.md 骨架补位）

## File Classification

| New/Modified File | Role | Data Flow | Closest Analog | Match Quality |
|-------------------|------|-----------|----------------|---------------|
| `server/knowledge/__init__.py` | config | — | `server/code_relations/__init__.py` | exact |
| `server/knowledge/apps.py` | config | — | `server/code_relations/apps.py` | exact |
| `server/knowledge/models.py` | model | CRUD | `server/code_relations/models.py` | exact |
| `server/knowledge/admin.py` | config | CRUD | `server/code_relations/admin.py` | exact |
| `server/knowledge/migrations/0001_initial.py` | migration | — | `makemigrations` 自动生成 | exact |
| `server/knowledge/graph_store.py` | service | request-response（raw SQL 遍历） | `server/system/health_views.py`（cursor 用法）+ RESEARCH.md CTE 骨架 | partial |
| `server/knowledge/collection.py` | service | request-response（Qdrant 生命周期） | `server/services/indexer.py::_ensure_collection` + `server/services/qdrant_service.py::create_collection`（语义需反转） | role-match |
| `server/knowledge/exceptions.py` | utility | — | `server/agents/core/exceptions.py` | exact |
| `server/knowledge/management/commands/rebuild_delivery_knowledge.py` | controller（CLI command） | request-response | `server/accounts/management/commands/init_superuser.py` + `server/code_relations/management/commands/rebuild_chunk_edges.py` | exact |
| `server/tests/knowledge/__init__.py` | test | — | `server/tests/code_relations/`（空包） | exact |
| `server/tests/knowledge/conftest.py` | test | — | `server/tests/conftest.py::repository` + `server/tests/test_git_diff_index.py::_stub_qdrant_calls` | exact |
| `server/tests/knowledge/test_models.py` | test | CRUD | `server/tests/code_relations/test_models.py` | exact |
| `server/tests/knowledge/test_graph_store.py` | test | request-response | `server/tests/code_relations/test_models.py`（DB 约束/EXPLAIN）+ `test_git_diff_index.py`（async marker） | role-match |
| `server/tests/knowledge/test_collection.py` | test | request-response | `server/tests/test_git_diff_index.py`（Qdrant seam） | exact |
| `server/friday/settings.py`（修改） | config | — | 既有 `INSTALLED_APPS` 列表 | exact |

## Pattern Assignments

### `server/knowledge/apps.py`（config）

**Analog:** `server/code_relations/apps.py`（整文件 21 行）

```1:11:server/code_relations/apps.py
"""代码关系图谱 App 配置。"""

from django.apps import AppConfig


class CodeRelationsConfig(AppConfig):
    """code_relations 关系图谱（ChunkRegistry + ChunkEdge）数据持久化 App。"""

    default_auto_field = "django.db.models.BigAutoField"
    name = "code_relations"
    verbose_name = "代码关系图谱"
```

直接照抄改名 `KnowledgeConfig` / `name = "knowledge"`。本阶段无 signals，**不需要** `ready()` 钩子（code_relations 的 `ready()` 是为 pre_delete signal 服务的，knowledge 没有）。

---

### `server/knowledge/models.py`（model, CRUD）

**Analog:** `server/code_relations/models.py` —— 本阶段最重要的类比，五个模式全部从这取。

**模块头 + imports 模式**（lines 1-19）：中文模块 docstring 列出每个模型一句话职责 + `__all__` 显式导出：

```11:19:server/code_relations/models.py
from __future__ import annotations

import uuid

from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from django.db.models import CheckConstraint, F, Q, UniqueConstraint

__all__ = ["ChunkRegistry", "ChunkEdge", "EdgeType"]
```

**TextChoices 枚举模式**（lines 22-36）：value 大写下划线，docstring 注明字面值契约。`EntityKind` / `EntityOrigin` / `EdgeRelation` 同款：

```22:33:server/code_relations/models.py
class EdgeType(models.TextChoices):
    """ChunkEdge 8 类关系边枚举（per contract 字面 value 大写下划线）。

    implementation 新增 IMPLEMENTS（Go interface 实现关系，per work item）。
    implementation 新增 API_CALLS（跨仓 API 调用关系，per work item）。
    """

    CALL = "CALL", "Call"
    IMPORT = "IMPORT", "Import"
    SAME_FILE = "SAME_FILE", "Same File"
    TEST_OF = "TEST_OF", "Test Of"
    CO_CHANGED = "CO_CHANGED", "Co-Changed"
```

**uuid5 同源稳定 PK 模式**（`KnowledgeEntity.id` 派生）：照 `code_relations/utils.py::generate_chunk_id` 的"唯一入口纯函数"纪律——knowledge 同样要有唯一的 `generate_entity_id(kind, source_kind, source_id)` 入口（建议放 `knowledge/utils.py` 或 models 模块内），禁止散落复刻：

```44:49:server/code_relations/utils.py
    Returns:
        uuid.UUID 实例（不是 str；调用方按需 `str(cid)` 自行转字符串）。
    """
    if branch_name:
        return uuid.uuid5(
            NAMESPACE_REPO, f"{repo_id}:{branch_name}:{file_path}:{chunk_index}"
        )
    return uuid.uuid5(NAMESPACE_REPO, f"{repo_id}:{file_path}:{chunk_index}")
```

注意：`NAMESPACE_REPO` 在 `code_relations/constants.py` 定义；knowledge 需要自己的独立 NAMESPACE 常量（不要复用 code_relations 的，避免跨域 id 空间纠缠）。拼接格式锁定后任何变更都构成 id 漂移——docstring 必须写明（generate_chunk_id 同款警告）。

**柔性引用（不做 FK）模式**（lines 142-151）：`KnowledgeEdge.target_chunk_id` 弱引用 ChunkRegistry 照此办理：

```142:151:server/code_relations/models.py
    target_repository_id = models.UUIDField(
        null=True,
        blank=True,
        db_index=True,
        help_text=(
            "跨仓边的 target chunk 所在仓库 ID（implementation）。"
            "单仓边（v24 既有 6 类边）为 NULL——backward compatible。"
            "不做 ForeignKey（per contract 柔性引用原则）；与 Repository.id UUID 类型对齐。"
        ),
    )
```

**Meta 约束/索引双保险模式**（lines 154-191）：UniqueConstraint + 枚举 CheckConstraint（防 bulk_create 绕过 full_clean）+ 命名索引。knowledge 的 `uniq_kentity_natural_key` / `kedge_relation_valid` / `idx_kedge_fanout` 全部同型：

```154:181:server/code_relations/models.py
    class Meta:
        verbose_name = "Chunk 边"
        verbose_name_plural = "Chunk 边"
        constraints = [
            # branch_name 进唯一约束（Critical 1 防御性冗余，
            # implementation 写入侧必须同步透传 branch_name，否则跨分支同三元组撞约束）。
            UniqueConstraint(
                fields=["source_chunk_id", "target_chunk_id", "edge_type", "branch_name"],
                name="uniq_chunkedge_triple",
            ),
            CheckConstraint(
                condition=Q(weight__gte=0.0) & Q(weight__lte=1.0),
                name="chunkedge_weight_range",
            ),
            # DB 层兜底 edge_type 枚举，避免 implementation EdgeBuilder 绕过
            # full_clean() 时（如 bulk_create / 直接 Manager.create）typo 静默落库；
            # 与 chunkedge_weight_range 同模式（双保险），满足 ROADMAP 成功条件 #4。
            CheckConstraint(
                condition=Q(edge_type__in=EdgeType.values),
                name="chunkedge_edge_type_valid",
            ),
        ]
        indexes = [
            models.Index(fields=["target_chunk_id"], name="idx_chunkedge_target"),
            models.Index(
                fields=["repository", "source_chunk_id"],
                name="idx_chunkedge_fanout",
            ),
```

**时间次序 CheckConstraint 模式**（lines 86-95）：`kversion_valid_range` / `kedge_valid_range`（`invalid_at > valid_at`）照 `chunkreg_line_range_valid` 的"允许 NULL | 比较"结构：

```86:95:server/code_relations/models.py
        constraints = [
            CheckConstraint(
                condition=(
                    Q(line_start__isnull=True)
                    | Q(line_end__isnull=True)
                    | Q(line_end__gte=F("line_start"))
                ),
                name="chunkreg_line_range_valid",
            ),
        ]
```

knowledge 特有、analog 没有的两个约束（直接照 RESEARCH.md §边表 schema 草案）：条件 UniqueConstraint（`uniq_kedge_active` 活跃边唯一、`uniq_kversion_one_latest` 单 latest）和 XOR CheckConstraint（`kedge_target_xor`）——Django 条件约束语法与上面普通约束同构，加 `condition=Q(...)` 参数即可，SQLite/PG 均编译为 partial unique index。

---

### `server/knowledge/admin.py`（config）

**Analog:** `server/code_relations/admin.py`（整文件 37 行，全抄结构）

```10:21:server/code_relations/admin.py
@admin.register(ChunkRegistry)
class ChunkRegistryAdmin(admin.ModelAdmin):
    """ChunkRegistry 最小 admin。"""

    list_display = ("chunk_id", "repository", "file_path", "chunk_index", "updated_at")
    list_filter = ("repository",)
    search_fields = ("file_path", "content_hash")
    # `chunk_id` 在模型层已是 `editable=False`，admin 自动 readonly；
    # `created_at` / `updated_at` 是 auto_now_add / auto_now 字段，同理。
    readonly_fields = ("created_at", "updated_at")
```

三个模型各注册一个最小 Admin：`list_display` 放 id/kind/title 类字段、`list_filter` 放枚举字段、`readonly_fields` 放时间戳。

---

### `server/knowledge/graph_store.py`（service, raw SQL 遍历）

**Analog（partial）:** 仓库**没有任何 `WITH RECURSIVE` 先例**（已 grep 验证），CTE 主体以 RESEARCH.md §GraphStore 骨架为准。可借的仓库模式有三处：

**raw cursor 用法**（`server/system/health_views.py` lines 46-51，仓库 raw SQL 标准姿势——`with connection.cursor()` 上下文 + 同步函数封装）：

```46:51:server/system/health_views.py
    def _ping() -> None:
        connection = connections["default"]
        connection.ensure_connection()
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1")
            cursor.fetchone()
```

**sync→async 桥接**（`server/services/indexer.py` line 1335，仓库异步纪律——同步实现 + `sync_to_async` 包一层）：

```1335:1335:server/services/indexer.py
        await sync_to_async(QdrantService.create_branch_payload_index)(collection_name)
```

GraphStore 形态：`async def traverse(...)` → `await sync_to_async(self._traverse_sync)(...)`，`_traverse_sync` 内 `with connection.cursor() as cur`。

**模块级默认单例**：`graph_store = RelationalGraphStore()` 模块尾部实例化（`NodeRegistry` 单例同款，`server/workflows/nodes/registry.py` 末行 `registry = NodeRegistry()` 模式）。

**必须遵守的 knowledge 特有要点**（来自 RESEARCH.md，无仓库先例，列出防漏）：
- UUID 参数预处理：`KnowledgeEntity._meta.pk.get_db_prep_value(value, connection)`（SQLite 无连字符 hex / PG 原生 uuid 分叉，Pitfall 1）
- `connection.vendor not in ("sqlite", "postgresql")` → raise `NotImplementedError`
- `max_hops` clamp 到 1..3；字符串 path + `NOT LIKE` 防环；占位符统一 `%s`
- `WITH RECURSIVE` 与边表表名 raw SQL **全仓只允许出现在本文件**（grep 审计测试固化）

---

### `server/knowledge/collection.py`（service, Qdrant 生命周期）

**Analog（语义需反转）:** `server/services/indexer.py::_ensure_collection`（维度读取）+ `server/services/qdrant_service.py::create_collection`（配置比对，但 mismatch 分支语义必须反转）。

**EMBEDDING_DIMENSION 读取模式**（indexer lines 1531-1538，照抄）：

```1531:1538:server/services/indexer.py
    async def _ensure_collection(self) -> None:
        """确保 Qdrant collection 存在，不存在则创建。"""
        dimension_setting = await SystemSetting.objects.filter(
            key=SettingKeys.EMBEDDING_DIMENSION
        ).afirst()
        vector_size = int(dimension_setting.value) if dimension_setting else 1024
        hybrid_enabled = await self._is_hybrid_enabled()
        await qdrant_create_collection(self.repository_id, vector_size, hybrid=hybrid_enabled)
```

（`SettingKeys.EMBEDDING_DIMENSION = "embedding_dimension"` 定义于 `server/system/models.py` line 55。）

**vectors_config 解析/比对模式**（qdrant_service lines 418-435，hybrid 判定 + dense size 提取逻辑可整段借用）：

```418:435:server/services/qdrant_service.py
            if collection_name in existing_names:
                # 检测现有 collection 是否需要重建（维度变化或 hybrid 模式变化）
                collection_info = client.get_collection(collection_name)
                vectors_config = collection_info.config.params.vectors

                # 判断现有 collection 类型
                if isinstance(vectors_config, dict):
                    # Named vectors 模式（hybrid）
                    existing_hybrid = True
                    existing_size = vectors_config.get(
                        "dense", models.VectorParams(size=0, distance=models.Distance.COSINE)
                    ).size
                else:
                    # 单向量模式（非 hybrid）
                    existing_hybrid = False
                    existing_size = vectors_config.size  # type: ignore[union-attr]

                need_recreate = existing_size != vector_size or existing_hybrid != hybrid
```

**⚠️ 三处语义禁止照抄**（RESEARCH.md 关键发现）：
1. `need_recreate` 后面的 `client.delete_collection(...)`（lines 445-446）——knowledge 必须改为 `logger.error(...)` + `raise KnowledgeCollectionMismatchError(...)`，**绝不自动删库**
2. `except UnexpectedResponse: return False`（lines 495-497）——knowledge 失败必须重抛，不允许静默 False
3. `create_collection_by_name` 的"存在即 return True 不校验"（lines 957-959）——knowledge 存在时必须严格比对配置

**hybrid 创建 + payload index 模式**（qdrant_service lines 452-491 可借结构）：`vectors_config={"dense": VectorParams(...)}` + `sparse_vectors_config={"sparse": SparseVectorParams()}`，payload index 循环创建——但字段换成 knowledge 自己的 `KNOWLEDGE_PAYLOAD_INDEXED_FIELDS` 常量（entity_kind/entity_id/version/is_latest/project_id/repository_id/source_kind/event_time），不要抄代码索引的 file_path/file_hash/language。

client 一律 `QdrantService.get_client()`（lines 124-150，60s timeout + keepalive 禁用 + trust_env=False 三处历史事故修复都在里面），同步调用经 `sync_to_async` 包装。

---

### `server/knowledge/exceptions.py`（utility）

**Analog:** `server/agents/core/exceptions.py`

```12:23:server/agents/core/exceptions.py
class AgentError(Exception):
    """Base exception for all agent-related errors."""

    def __init__(self, message: str, details: dict | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.details = details or {}

    def __str__(self) -> str:
        if self.details:
            return f"{self.message} | Details: {self.details}"
        return self.message
```

同型建 `KnowledgeError` 基类 + `KnowledgeCollectionMismatchError` 子类（message 携带现有/期望维度 + 指引运行 `manage.py rebuild_delivery_knowledge --yes`）。

---

### `server/knowledge/management/commands/rebuild_delivery_knowledge.py`（CLI command）

**Analog 1:** `server/accounts/management/commands/init_superuser.py` —— WARNING 横幅视觉模式（lines 72-79）：

```72:79:server/accounts/management/commands/init_superuser.py
            self.stdout.write("")
            self.stdout.write(self.style.WARNING("=" * 60))
            self.stdout.write(self.style.WARNING("  work item PASSWORD (save this now!)"))
            self.stdout.write(self.style.WARNING("=" * 60))
            self.stdout.write(f"  Username: {username}")
            self.stdout.write(f"  Password: {password}")
            self.stdout.write(self.style.WARNING("=" * 60))
            self.stdout.write("")
```

**Analog 2:** `server/code_relations/management/commands/rebuild_chunk_edges.py` —— 更完整的命令骨架（参数校验 / CommandError / asyncio.run / structlog 始末日志 / 退出码契约）：

参数定义 + 校验模式（lines 60-113 节选；`--yes` 确认参数用 `action="store_true"` 同 `--dry-run`/`--all` 写法）：

```91:113:server/code_relations/management/commands/rebuild_chunk_edges.py
    def handle(self, *args: Any, **options: Any) -> None:
        repo_filter: str | None = options["repo"]
        all_mode: bool = options["all"]
        dry_run: bool = options["dry_run"]
        since_raw: str | None = options.get("since")
        since: datetime | None = None
        if since_raw is not None:
            since = parse_datetime(since_raw)
            if since is None:
                raise CommandError(
                    f"--since 不是合法 ISO8601 时间戳: {since_raw!r} "
                    "（示例：2026-05-01T00:00:00+08:00）"
                )
            if timezone.is_naive(since):
                raise CommandError(
                    "--since 必须带 timezone（USE_TZ=True 项目惯例），"
                    f"got naive datetime: {since_raw!r}"
                )

        if repo_filter and all_mode:
            raise CommandError("--repo 与 --all 互斥，请只传其一")
        if not repo_filter and not all_mode:
            raise CommandError("必须指定 --repo <uuid> 或 --all")
```

> 上面 `timezone.is_naive` 拒绝 naive datetime 的写法同时是 GraphStore 写路径 `_require_aware` 防线（P2）的仓库先例。

async 流程封装模式（line 249）：`asyncio.run(self._dispatch_and_drain(...))` —— rebuild_delivery_knowledge 内调 `ensure_delivery_knowledge_collection()`（async）同样走 `asyncio.run(...)`。

structlog 始末事件模式（lines 137-142 / 169-176）：`logger.info("rebuild_chunk_edges_started", ...)` / `..._finished` 键值对事件命名。

命令流程（RESEARCH.md 定案）：无 `--yes` → 打印将发生什么 + WARNING 横幅后退出；有 `--yes` → `delete_collection_by_name` → `ensure_delivery_knowledge_collection()` → 更新 SystemSetting 元信息 → 醒目输出。docstring 注明 Phase 13 后需扩展"从 PG 全量重嵌入"TODO 锚点。

---

### `server/tests/knowledge/conftest.py`（test fixtures）

**Analog 1:** `server/tests/conftest.py::repository`（lines 235-243）—— 简单 model fixture 风格（注意：仓库现状是**直接 `objects.create`，不是 factory-boy 类**，knowledge fixtures 沿用此风格即可，参数化用 fixture 函数参数）：

```235:243:server/tests/conftest.py
@pytest.fixture
def repository(db):
    """创建测试仓库。"""
    return Repository.objects.create(
        name="Test Repo",
        git_url="https://github.com/test/repo.git",
        git_platform="github",
        default_branch="main",
    )
```

knowledge 需要 `entity_factory` / `edge_factory` / `version_factory` 三个 fixture（RESEARCH.md 测试骨架按"可调用工厂"使用：`entity_factory()` 返回新实体），建议形态为返回闭包的 fixture（`def entity_factory(db): def _make(**kw): return KnowledgeEntity.objects.create(...); return _make`）。

**Analog 2:** `server/tests/test_git_diff_index.py::_stub_qdrant_calls`（lines 33-65）—— Qdrant seam autouse fixture，test_collection.py 照此隔离：

```33:53:server/tests/test_git_diff_index.py
@pytest.fixture(autouse=True)
def _stub_qdrant_calls(monkeypatch: pytest.MonkeyPatch) -> None:
    """全局 stub 所有 Qdrant 同步调用，避免 pytest-socket 阻塞真实 HTTP。

    implementation 双轨索引引入后 IndexerService 在 git diff 路径上会触碰 Qdrant
    （_ensure_collection / get_stored_file_hashes / upsert_vectors 等）。本文件
    集中验证 git diff 解析与分发逻辑，不验证向量库写入；用 AsyncMock seam
    一次性 stub 掉所有 qdrant_* helper 即可保证测试隔离。
    """
    from services import indexer as ix

    monkeypatch.setattr(ix, "qdrant_create_collection", AsyncMock(return_value=True))
    monkeypatch.setattr(
        ix, "qdrant_create_branch_payload_index", AsyncMock(return_value=True)
    )
    monkeypatch.setattr(
        ix, "qdrant_get_stored_file_hashes", AsyncMock(return_value={})
    )
    monkeypatch.setattr(ix, "qdrant_delete_by_file_path", AsyncMock(return_value=True))
    monkeypatch.setattr(ix, "qdrant_upsert_vectors", AsyncMock(return_value=True))
```

knowledge 版本 stub 对象是 `QdrantService.get_client`（返回 `MagicMock` client，`get_collection` 返回可控的 vectors_config），放 `tests/knowledge/conftest.py` 供 test_collection.py 用。

---

### `server/tests/knowledge/test_models.py` / `test_graph_store.py`（test）

**Analog:** `server/tests/code_relations/test_models.py` —— 模型约束测试全套模式。

**文件头模式**（lines 1-25）：docstring 列用例清单 + `pytestmark = pytest.mark.django_db`。

**DB 层 CheckConstraint 兜底测试模式**（lines 197-208，knowledge 的 `kedge_relation_valid` / `kversion_valid_range` / `kedge_target_xor` 全部同型——绕过 full_clean 直接 `.create()` 期望 IntegrityError，注意 `transaction.atomic()` 包裹）：

```197:208:server/tests/code_relations/test_models.py
def test_chunkedge_weight_check_constraint_db_level(repository) -> None:
    """绕过 validator 直接 .create(weight=-0.5) → DB CheckConstraint 拒绝（IntegrityError）。"""
    with pytest.raises(IntegrityError):
        with transaction.atomic():
            ChunkEdge.objects.create(
                source_chunk_id=uuid.uuid4(),
                target_chunk_id=uuid.uuid4(),
                edge_type=EdgeType.CALL,
                weight=-0.5,
                metadata={},
                repository=repository,
            )
```

**唯一约束冲突测试模式**（lines 242-263）：natural key / `uniq_kversion_one_latest` / `uniq_kedge_active` 同型（二次 create → IntegrityError）。

**SQLite EXPLAIN 索引断言模式**（lines 271-282，证实测试套件跑 SQLite；`idx_kedge_fanout` 可加同款断言）：

```271:282:server/tests/code_relations/test_models.py
def test_chunkedge_fan_in_query_uses_target_index(repository) -> None:
    """按 target_chunk_id 查询应走 idx_chunkedge_target 索引（SQLite EXPLAIN QUERY PLAN）。"""
    tgt = uuid.uuid4()
    with connection.cursor() as cur:
        cur.execute(
            'EXPLAIN QUERY PLAN '
            'SELECT * FROM code_relations_chunkedge WHERE target_chunk_id = %s',
            [str(tgt)],
        )
        rows = cur.fetchall()
    plan_text = " ".join(str(row) for row in rows)
    assert "idx_chunkedge_target" in plan_text, f"plan: {plan_text}"
```

**test_graph_store.py 的 async marker 模式**取自 `test_git_diff_index.py` line 30（GraphStore 接口是 async，SQLite + async 需要 transaction=True）：

```29:30:server/tests/test_git_diff_index.py
# SQLite 内存数据库 + async 需要 transaction=True 避免跨线程锁冲突
pytestmark = [pytest.mark.django_db(transaction=True), pytest.mark.asyncio]
```

（`asyncio_mode=auto` 已全局开启，`pytest.mark.asyncio` 可省，但 `django_db(transaction=True)` 对 `sync_to_async` 跨线程访问 SQLite 是必须的。）

用例集（环终止 / 失效边 as-of / 深度 clamp / UUID prep 双后端）直接用 RESEARCH.md §Code Examples 测试骨架。grep 审计测试（`WITH RECURSIVE` 只许出现在 `knowledge/graph_store.py`）无先例，读源码文本断言即可。

---

### `server/friday/settings.py`（修改）

**Analog:** 既有 `INSTALLED_APPS`（lines 81-117）。在第一方 app 段追加一行 `"knowledge",`（普通 app 直接加名字，参照 `"code_relations",` line 99；不需要 `services.code_intel.apps.CodeIntelConfig` 那种 dotted path 形式）。

## Shared Patterns

### structlog 结构化日志
**Source:** `server/code_relations/management/commands/rebuild_chunk_edges.py` lines 49, 137-142
**Apply to:** `graph_store.py` / `collection.py` / management command

```python
logger = structlog.get_logger(__name__)
logger.info("rebuild_chunk_edges_started", repo_count=len(repos), dry_run=dry_run, mode=...)
```

事件名 snake_case 动词短语，上下文全走关键字参数。knowledge 关键事件：`knowledge_collection_created` / `knowledge_collection_config_mismatch`（error 级）。

### TextChoices + DB CheckConstraint 双保险
**Source:** `server/code_relations/models.py` lines 164-174（`chunkedge_edge_type_valid`）
**Apply to:** `models.py` 全部枚举字段（kind / origin / relation）

```python
CheckConstraint(condition=Q(edge_type__in=EdgeType.values), name="chunkedge_edge_type_valid"),
```

### aware datetime 强制（P2 防线）
**Source:** `rebuild_chunk_edges.py` lines 104-108（`timezone.is_naive(since)` → 报错）
**Apply to:** GraphStore 全部写路径（add_edge / invalidate_edge / expire_edge）与 as_of 参数

### sync_to_async 桥接
**Source:** `server/services/indexer.py` line 1335 等
**Apply to:** `graph_store.py`（cursor 调用）、`collection.py`（Qdrant 同步 client 调用）

### 中文 docstring 记录实现契约
**Source:** `code_relations/models.py` / `generate_chunk_id` 全篇
**Apply to:** 所有新文件。重点契约要写进 docstring：id 拼接格式锁定、`uniq_kversion_one_latest` 并发竞态语义（撞约束即报错，串行化责任在 Phase 13）、召回面/轨迹面边界（P10）。

## No Analog Found

| File / 部分 | Role | Data Flow | Reason |
|------|------|-----------|--------|
| `graph_store.py` 递归 CTE 主体 | service | raw SQL 遍历 | 全仓无 `WITH RECURSIVE` 先例（已 grep 验证）——以 RESEARCH.md §GraphStore SQL 骨架为唯一规格（字符串 path 防环 + `%s` 占位 + UUID prep） |
| `collection.py` "mismatch → raise" 分支 | service | Qdrant 生命周期 | 既有两条路径语义均错误（自动删库 / 不校验），只能借配置解析代码、语义必须反写 |

## Metadata

**Analog search scope:** `server/code_relations/`（models/admin/apps/utils/commands）、`server/services/`（qdrant_service/indexer）、`server/accounts/management/commands/`、`server/system/`（health_views/models）、`server/agents/core/`、`server/tests/`（conftest/code_relations/test_git_diff_index）、`server/friday/settings.py`
**Files scanned:** 12 个类比文件实读 + 4 次定向 grep（WITH RECURSIVE / connection.cursor / sync_to_async / INSTALLED_APPS）
**Pattern extraction date:** 2026-06-11
