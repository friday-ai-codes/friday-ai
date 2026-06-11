# Phase 12: 知识模型与图存储地基 - Research

**Researched:** 2026-06-11
**Domain:** 知识图谱存储模型（bi-temporal 边 + 版本链）/ Django ORM + 递归 CTE / Qdrant collection 生命周期 — brownfield 集成
**Confidence:** HIGH（核心结论基于实读本仓库代码 + 官方文档验证；不引入任何新外部依赖）

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions

ROADMAP/研究已锁定的硬决策（不可偏离）：
- 不引入 Neo4j 等图数据库；PG 递归 CTE 实现 1–3 跳遍历，GraphStore 接口留换引擎逃生门（Out of Scope 表已排除迁移）
- 有效性过滤埋进 GraphStore 接口而非靠约定
- payload 权限字段与 natural key 规则本阶段一次定对（Phase 13+ 依赖）
- 旧版本物理删除被排除——失效置位不删除

### Claude's Discretion

All implementation choices are at Claude's discretion — pure infrastructure phase（存储模型/服务接口，无用户可见行为）。以 ROADMAP Phase 12 success criteria、REQUIREMENTS KMOD-01..04 及 `.planning/research/PITFALLS.md` 的关键防线为准，沿用代码库既有模式。

### Deferred Ideas (OUT OF SCOPE)

None — discuss skipped（infrastructure phase）。

本阶段不做（来自 CONTEXT.md domain）：摄取管线（Phase 13）、diff 归档能力（Phase 14，但归档表结构可随本阶段 migrations 建好）、检索（Phase 15）、入口暴露（Phase 16）。
</user_constraints>

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| KMOD-01 | 统一实体模型存储四类交付知识实体（work_item / tech_plan / code_change / document），携带 `source_kind` + `source_id` 稳定业务引用、来源（feishu/chat/mcp/workflow）与事件时间 | §实体表 schema（KnowledgeEntity 字段、natural key 唯一约束、uuid5 PK 派生）；§Pattern 1 双层引用原则 |
| KMOD-02 | bi-temporal 四时间戳边（`valid_at`/`invalid_at` + `created_at`/`expired_at`），失效置位不删除，历史可审计 | §边表 schema（四时间戳 + CheckConstraint + 活跃边部分唯一约束）；§Pattern 3 失效置位接口 |
| KMOD-03 | supersedes 版本链，旧版本保留且可按版本号回溯 | §版本表 schema（version + supersedes 自引用 + is_latest 部分唯一索引）；§Pattern 2 版本链 |
| KMOD-04 | 图读写收敛 GraphStore service 接口（1–3 跳递归遍历、有效性过滤、防环、深度上限），调用方不得绕过裸写 SQL | §GraphStore 设计（Protocol + 递归 CTE 实现 + SQLite/PG 双方言要点 + grep 审计验证） |
</phase_requirements>

## Summary

本阶段是纯地基工程：新建 `knowledge` Django app，落四类模型（实体 / 版本 / bi-temporal 边 /（可选）diff 归档表 stub），交付一个把递归遍历、有效性过滤、防环、深度上限全部内化的 `GraphStore` 接口，以及 `delivery_knowledge` Qdrant collection 的严格生命周期管理（维度不匹配拒绝 + 显式重建命令）。**全程零新依赖**——所有需要的能力（Django ORM 约束、`connection.cursor()` 递归 CTE、`QdrantService` 客户端基建、structlog、pytest seam）在仓库中均有现成先例。

三个最重要的研究发现：
1. **测试与本地 dev 默认跑 SQLite**（`DEFAULT_DATABASE_URL = sqlite:///...`，且测试套件用 SQLite `EXPLAIN QUERY PLAN` 断言索引），因此 GraphStore 的递归 CTE 必须同时兼容 SQLite 与 PostgreSQL。两者都支持 `WITH RECURSIVE`，但防环手段不同：PG 惯用数组，SQLite 没有数组——**用字符串 path + `NOT LIKE` 是两者通吃的可移植方案**。
2. **Django `UUIDField` 在 SQLite 存 32 位无连字符 hex、在 PG 存原生 uuid**（已实读 Django 5.x 源码验证）。raw SQL 的 UUID 参数必须经 `field.get_db_prep_value(value, connection)` 预处理，否则同一条 SQL 在两个后端只有一个能查到数据——这是本阶段最隐蔽的坑。
3. **既有 `create_collection` / `create_collection_by_name` 都不能直接用于 `delivery_knowledge`**：前者维度不匹配时静默删库重建（P8 灾难语义），后者存在时直接返回 True、**不校验任何配置**且会创建代码索引专属的 payload index。knowledge 必须自带 ensure 函数：存在时读取 collection 配置严格比对，不匹配则 raise 响亮报错。

**Primary recommendation:** 新建 `server/knowledge/` app；模型层用 Django ORM 约束（CheckConstraint + 条件 UniqueConstraint，SQLite/PG 双后端均支持）锁死不变量；GraphStore 用单一 Protocol + 关系型实现（raw SQL 仅在 `graph_store.py` 内，字符串 path 防环）；collection 生命周期独立实现于 `knowledge/collection.py` + management command，不复用 indexer 的自动重建语义。

## Architectural Responsibility Map

| Capability | Primary Tier | Secondary Tier | Rationale |
|------------|-------------|----------------|-----------|
| 实体/版本/边模型与约束 | Database / Storage（Django ORM + migrations） | — | 不变量（natural key 唯一、时间戳次序、活跃边唯一）必须 DB 层兜底，不能只靠应用层 |
| 1–3 跳递归遍历 + 有效性过滤 + 防环 | API / Backend（GraphStore service） | Database（递归 CTE 执行） | 过滤语义埋进接口（locked decision）；SQL 是实现细节，藏在 GraphStore 内 |
| supersedes 版本链回溯 | API / Backend（service 方法走 ORM 版本表） | — | 纯 PG 查询（ROADMAP RETR-03 明确不依赖向量库），本阶段交付查询能力 |
| `delivery_knowledge` collection 生命周期 | API / Backend（knowledge/collection.py + management command） | 外部服务 Qdrant | 校验/创建/重建是后端职责；Qdrant 只是被管理对象 |
| payload schema 定型 | API / Backend（常量模块，单一事实源） | — | Phase 13 摄取、Phase 15 检索都消费同一份 schema 常量 |

本阶段无前端、无 HTTP API 面（admin 最小注册即可，参照 `code_relations/admin.py`）。

## Standard Stack

### Core（全部为既有依赖，零新增）

| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| Django ORM | django>=5.1（已装） | 模型/约束/migrations | 仓库唯一持久层 [VERIFIED: 本仓库 pyproject.toml] |
| `django.db.connection` | 内置 | GraphStore 内 raw SQL 递归 CTE | 仓库已有 raw cursor 先例（`check_v81_legacy_residue.py`、`system/health_views.py`）[VERIFIED: 本仓库实读] |
| qdrant-client（经 `QdrantService`） | qdrant-client>=1.9.0（已装） | collection 创建/校验 | `QdrantService.get_client()` 已带 60s timeout 等历史事故修复，禁止绕开 [VERIFIED: 本仓库 qdrant_service.py] |
| structlog | 已装 | 结构化日志 | 仓库约定 [VERIFIED] |
| pytest + pytest-django + pytest-asyncio | 已装（`asyncio_mode=auto`，`--disable-socket`） | 测试 | 仓库约定 [VERIFIED: server/pyproject.toml] |

### Supporting

| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| `asgiref.sync_to_async` | 已装 | GraphStore 同步 cursor → async 接口桥接 | 所有 raw SQL 执行点（仓库异步约束） |
| factory-boy | 已装 | 测试数据工厂 | 实体/边/版本 fixtures |
| `unittest.mock.AsyncMock` + monkeypatch | stdlib | Qdrant seam 隔离 | collection 生命周期测试（参照 `tests/test_git_diff_index.py` 的 `_stub_qdrant_calls` autouse fixture 模式）|

### Alternatives Considered

| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| raw SQL 递归 CTE | Python 迭代 BFS（每跳一次 ORM `filter(source_entity_id__in=...)`，最多 3 次查询） | BFS 完全可移植（含 MySQL）、防环天然（Python visited set）、但与 locked decision「PG 递归 CTE」字面不符。**建议：CTE 为主方案；若 planner 担心方言维护成本，BFS 可作为 GraphStore 内部的 fallback 实现（接口不变，正是逃生门价值的体现）**——本研究按 CTE 主方案展开 |
| 字符串 path 防环 | PG 14+ `CYCLE` 子句 / 数组 `= ANY(path)` | PG 专属语法，SQLite 不支持，破坏双后端兼容 — 不用 |
| `models.py` 单文件 | `models/` 包 | 仓库两种风格并存（`code_relations` 单文件 / `workflows` 包）。本 app 4 个模型放单文件可控；超过则拆包。Claude's discretion |

**Installation:** 无需安装任何新包。

## Package Legitimacy Audit

本阶段**不安装任何新外部依赖**，全部使用仓库既有依赖（Django / qdrant-client / structlog / pytest 系），audit 不适用。

**Packages removed due to slopcheck [SLOP] verdict:** none
**Packages flagged as suspicious [SUS]:** none

## 推荐的 Django app 布局

```
server/knowledge/                       # 新 Django app（bounded context）
├── __init__.py
├── apps.py                             # KnowledgeConfig, name="knowledge"
├── models.py                           # KnowledgeEntity / KnowledgeEntityVersion / KnowledgeEdge
│                                       #   （+ 可选 CodeChangeArchive stub，见 Open Questions）
├── admin.py                            # 最小 admin 注册（参照 code_relations/admin.py）
├── migrations/
├── graph_store.py                      # GraphStore Protocol + RelationalGraphStore 实现
│                                       #   ★ 边表 raw SQL 全仓唯一存在地
├── collection.py                       # delivery_knowledge 生命周期：ensure / 校验 / payload schema 常量
├── exceptions.py                       # KnowledgeCollectionMismatchError 等领域异常
└── management/
    └── commands/
        └── rebuild_delivery_knowledge.py   # 显式重建命令（参照 init_superuser 命令风格）

server/tests/knowledge/                 # 测试镜像 app 结构（仓库惯例：tests/<app>/test_*.py）
├── test_models.py                      # 约束/索引/版本链
├── test_graph_store.py                 # 遍历/防环/深度/有效性/as-of
└── test_collection.py                  # 生命周期/维度校验/重建命令
```

接入点（均为既有惯例）：
- `server/friday/settings.py` `INSTALLED_APPS` 追加 `"knowledge"`（普通 app 直接加名字即可）[VERIFIED: settings.py L81-117]
- 本阶段**不需要** `urls.py` / `api/`（无 HTTP 面）；admin 注册仅为开发调试
- 服务命名建议 `RelationalGraphStore`（而非 `PostgresGraphStore`）——它同时服务 SQLite dev 与 PG prod，名字别撒谎

### Structure Rationale

- 领域 service 放 app 内（`graph_store.py` / `collection.py`），`server/services/` 留给跨域基础设施——`mcp_tools/*_service.py`、`chat/coding_session_service.py` 已确立此先例 [VERIFIED: .planning/research/ARCHITECTURE.md + 实读]
- `collection.py` 与 `graph_store.py` 分文件：一个管 Qdrant 生命周期、一个管 PG 图访问，职责正交，Phase 13/15 分别消费
- payload schema 常量放 `collection.py`（或独立 `payload_schema.py`），Phase 13 摄取与 Phase 15 检索 import 同一份——"第一天定型"的落点

## 实体表 / 边表 / 版本链 schema 建议

> 以下为 prescriptive 草案，字段名以 ROADMAP success criteria 字面为准（`valid_at`/`invalid_at`/`created_at`/`expired_at`），与 `.planning/research/ARCHITECTURE.md` 草案的差异已按 success criteria 修正（该草案用了 `invalidated_at`，本阶段统一为 `invalid_at` + `expired_at` 四字段命名）。

### KnowledgeEntity（实体身份表，KMOD-01）

```python
class EntityKind(models.TextChoices):
    WORK_ITEM = "work_item", "需求/缺陷"
    TECH_PLAN = "tech_plan", "技术方案"
    CODE_CHANGE = "code_change", "代码变更"
    DOCUMENT = "document", "文档"

class EntityOrigin(models.TextChoices):
    FEISHU = "feishu", "飞书"
    CHAT = "chat", "对话"
    MCP = "mcp", "MCP"
    WORKFLOW = "workflow", "工作流"

class KnowledgeEntity(models.Model):
    # PK = uuid5(NAMESPACE, f"{kind}:{source_kind}:{source_id}")
    # 沿用 ChunkRegistry "uuid5 同源稳定 PK" 模式：同一业务对象重复摄取得到同一实体 id（幂等锚点）
    id = models.UUIDField(primary_key=True, editable=False)
    kind = models.CharField(max_length=20, choices=EntityKind.choices, db_index=True)
    origin = models.CharField(max_length=20, choices=EntityOrigin.choices)   # 来源渠道
    source_kind = models.CharField(max_length=50)    # 稳定业务引用类型，见下方 natural key 规则
    source_id = models.CharField(max_length=255)     # 业务对象稳定 ID（含飞书三元组拼接）
    project = models.ForeignKey("projects.Project", null=True, blank=True, on_delete=models.SET_NULL)
    repository = models.ForeignKey("repositories.Repository", null=True, blank=True, on_delete=models.SET_NULL)
    title = models.CharField(max_length=500)
    current_version = models.PositiveIntegerField(default=1)
    event_time = models.DateTimeField()              # 业务事件时间（最近一次）
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
```

**约束/索引：**
- `UniqueConstraint(fields=["kind", "source_kind", "source_id"], name="uniq_kentity_natural_key")` — 幂等 natural key，Phase 13 摄取 upsert 的锚点
- `CheckConstraint(condition=Q(kind__in=EntityKind.values), ...)` — DB 层枚举兜底（`chunkedge_edge_type_valid` 同款双保险）[VERIFIED: code_relations/models.py]
- 索引：`(project, kind)`（权限/类型过滤）、`(source_kind, source_id)`（反查）

**Natural key 规则（本阶段一次定对，locked decision）：**

| source_kind | source_id 构成 | 对应业务对象 |
|-------------|---------------|-------------|
| `feishu_work_item` | `{project_key}:{work_item_type_key}:{work_item_id}` | 飞书工作项三元组 |
| `feishu_document` | 飞书文档 token | PRD/技术方案文档 |
| `coding_plan` | CodingPlan UUID str | chat 产出方案 |
| `mcp_technical_plan` | McpWorkItemTechnicalPlan UUID str | MCP 产出方案 |
| `workflow_plan` | `{execution_id}:{node_id}` | workflow 产出方案 |
| `task_result` | TaskResult/session UUID str | 编码产出 |

> 注意 `origin`（渠道：feishu/chat/mcp/workflow）与 `source_kind`（业务对象类型）是两个维度——KMOD-01 字面要求两者都携带。chat 纯自然语言需求的去重（P4）是 Phase 13 摄取问题，本阶段只需 natural key 结构容纳它（chat 路径有 CodingPlan UUID 可用）。

**FK 取舍（双层引用原则）：** `project`/`repository` 用 FK 但 `on_delete=SET_NULL`（组织维度可过滤，但删项目不应抹掉知识历史——bi-temporal "历史可审计"要求）；源业务对象一律弱引用 `source_kind + source_id`，不做 FK、不用 GenericForeignKey（contenttypes 在本仓库零业务使用先例，且无法表达飞书三元组）[VERIFIED: ARCHITECTURE.md 论证 + ChunkEdge 柔性引用先例]。

### KnowledgeEntityVersion（版本链表，KMOD-03）

```python
class KnowledgeEntityVersion(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    entity = models.ForeignKey(KnowledgeEntity, on_delete=models.CASCADE, related_name="versions")
    version = models.PositiveIntegerField()
    supersedes = models.ForeignKey(            # 显式 supersedes 链：v2.supersedes → v1
        "self", null=True, blank=True, on_delete=models.PROTECT, related_name="superseded_by",
    )
    content = models.TextField()               # 该版本全文（Phase 13 embedding 输入）
    content_hash = models.CharField(max_length=64)   # sha256；内容未变跳过重摄取
    payload = models.JSONField(default=dict)   # 结构化原文快照
    qdrant_point_ids = models.JSONField(default=list)  # Phase 13 写入；下线按 point id 删（P1）
    is_latest = models.BooleanField(default=True)
    event_time = models.DateTimeField()        # 该版本对应的业务事件时间
    valid_at = models.DateTimeField()          # 业务时间线：版本生效
    invalid_at = models.DateTimeField(null=True, blank=True)   # 业务时间线：被取代（置位不删除）
    created_at = models.DateTimeField(auto_now_add=True)       # 系统时间线：记录写入
    expired_at = models.DateTimeField(null=True, blank=True)   # 系统时间线：记录作废
```

**约束/索引：**
- `UniqueConstraint(fields=["entity", "version"], name="uniq_kversion_entity_version")` — 按版本号回溯的基础
- `UniqueConstraint(fields=["entity"], condition=Q(is_latest=True), name="uniq_kversion_one_latest")` — **同一实体最多一个 latest**。Django 条件 UniqueConstraint 在 SQLite 与 PG 均编译为 partial unique index，双后端可用 [VERIFIED: Django 5.x 文档行为 + 仓库 SQLite 测试可直接验证]
- `CheckConstraint(condition=Q(invalid_at__isnull=True) | Q(invalid_at__gt=F("valid_at")), name="kversion_valid_range")` — P2 时间次序兜底（`chunkreg_line_range_valid` 同模式）
- 索引：`(entity, -version)`（版本链回溯）、`is_latest`（部分索引已覆盖常用查询）

**supersedes 显式 FK 而非只靠 version 号**：version 号可推断链序，但显式链让"v3 直接推翻 v1（驳回重生成）"这类非线性历史可表达，且 `on_delete=PROTECT` 物理上防止删除被引用的旧版本（locked decision：失效置位不删除的 DB 级保险）。

### KnowledgeEdge（bi-temporal 边表，KMOD-02）

```python
class EdgeRelation(models.TextChoices):
    HAS_PLAN = "HAS_PLAN", "需求→方案"
    IMPLEMENTED_BY = "IMPLEMENTED_BY", "方案→代码变更"
    REFERENCES = "REFERENCES", "引用文档"
    RELATES_TO = "RELATES_TO", "相关"
    DUPLICATE_OF = "DUPLICATE_OF", "重复"
    MODIFIES_CHUNK = "MODIFIES_CHUNK", "修改代码块"   # Phase 14 用，枚举先占位

class KnowledgeEdge(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    source_entity = models.ForeignKey(KnowledgeEntity, on_delete=models.CASCADE, related_name="out_edges")
    target_entity = models.ForeignKey(
        KnowledgeEntity, null=True, blank=True, on_delete=models.CASCADE, related_name="in_edges",
    )
    target_chunk_id = models.UUIDField(null=True, blank=True, db_index=True)  # MODIFIES_CHUNK 弱引用 ChunkRegistry，不 FK
    relation = models.CharField(max_length=30, choices=EdgeRelation.choices)
    metadata = models.JSONField(default=dict, blank=True)
    # bi-temporal 四时间戳（success criteria 字面命名）
    valid_at = models.DateTimeField()                                  # 业务：关系成立
    invalid_at = models.DateTimeField(null=True, blank=True)           # 业务：关系失效（置位不删除）
    created_at = models.DateTimeField(auto_now_add=True)               # 系统：记录写入
    expired_at = models.DateTimeField(null=True, blank=True)           # 系统：记录作废
```

**约束/索引（关键）：**

```python
constraints = [
    # 活跃边唯一：同一对实体同 relation 只能有一条"当前有效"边
    UniqueConstraint(
        fields=["source_entity", "target_entity", "relation"],
        condition=Q(invalid_at__isnull=True) & Q(expired_at__isnull=True),
        name="uniq_kedge_active",
    ),
    # 两端二选一：实体边 XOR chunk 边
    CheckConstraint(
        condition=(Q(target_entity__isnull=False) & Q(target_chunk_id__isnull=True))
        | (Q(target_entity__isnull=True) & Q(target_chunk_id__isnull=False)),
        name="kedge_target_xor",
    ),
    # 时间次序兜底（P2）
    CheckConstraint(
        condition=Q(invalid_at__isnull=True) | Q(invalid_at__gt=F("valid_at")),
        name="kedge_valid_range",
    ),
    CheckConstraint(condition=Q(relation__in=EdgeRelation.values), name="kedge_relation_valid"),
]
indexes = [
    # 遍历 fanout 主索引：递归 CTE 每一跳走它
    models.Index(fields=["source_entity", "relation"], name="idx_kedge_fanout"),
    models.Index(fields=["target_entity"], name="idx_kedge_reverse"),
    # 活跃边部分索引：默认遍历只扫有效边（PITFALLS Performance Traps 明确建议）
    models.Index(
        fields=["source_entity"], condition=Q(invalid_at__isnull=True) & Q(expired_at__isnull=True),
        name="idx_kedge_active_fanout",
    ),
]
```

部分索引（`condition=`）SQLite 3.8+ 与 PG 均原生支持，Django 直接编译 [CITED: docs.djangoproject.com/en/5.1/ref/models/indexes/#condition]。

### CodeChangeArchive（可选 stub）

ROADMAP Note 允许"diff 归档表结构可在 Phase 12 随 migrations 建好"。若 planner 选择纳入：`version FK → KnowledgeEntityVersion`、`file_path`、`diff_text`（大文本）、`is_compressed + BinaryField`（超大 diff 压缩）、`commit_sha / mr_url / repo metadata`。**建议作为独立小 task 放最后，可裁剪**——它不阻塞 KMOD-01..04 任何 success criteria，真正交付验证在 Phase 14。

## GraphStore 设计（KMOD-04）

### 接口形态

```python
@dataclass(frozen=True)
class TraversalResult:
    """遍历命中：实体 id + 最短跳数 + 命中路径上的边 relation 链。"""
    entity_id: uuid.UUID
    depth: int

class GraphStore(Protocol):
    """图访问唯一收口。有效性过滤 / 深度上限 / 防环全部内置，调用方无法绕过。"""

    async def add_edge(self, *, source_id, target_id, relation, valid_at, metadata=None) -> uuid.UUID: ...
    async def invalidate_edge(self, edge_id, *, invalid_at) -> None:        # 置位 invalid_at，不删除
    async def expire_edge(self, edge_id, *, expired_at) -> None:            # 系统时间线作废（纠错用）
    async def neighbors(self, entity_id, *, relations=None, direction="out", as_of=None) -> list[...]: ...
    async def traverse(
        self, start_id, *, max_hops: int = 2, relations=None,
        direction="out", as_of: datetime | None = None,
    ) -> list[TraversalResult]: ...
```

要点：
- `max_hops` 接口层 clamp 到 `1..3`（硬上限常量，调用方传 10 也只走 3）
- **默认语义 = 当前有效**：`invalid_at IS NULL AND expired_at IS NULL`；历史查询走显式 `as_of` 参数（P2 防线："不让调用方手写有效性过滤"）
- 写路径（add/invalidate/expire）走 ORM——只有递归遍历需要 raw SQL；**`WITH RECURSIVE` 与边表 raw SQL 在全仓只允许出现在 `graph_store.py`**（验证手段：grep 审计测试，见 Validation Architecture）
- 异步桥接：cursor 是同步 API，实现为 `_traverse_sync()` + `await sync_to_async(self._traverse_sync)(...)`（仓库异步约束惯例）
- 模块级提供默认实例 `graph_store = RelationalGraphStore()`（`NodeRegistry` 单例同款），Phase 13+ 直接 import

### 递归 CTE：SQLite / PG 双方言要点（已验证）

两个后端均支持 `WITH RECURSIVE`（本机 SQLite 3.50/3.51，远超 3.8.3 最低要求 [VERIFIED: 本机 `sqlite3.sqlite_version`]；PG 全版本支持 [CITED: postgresql.org/docs/current/queries-with.html]）。可移植写法的全部关键点：

| 维度 | 可移植做法 | 不可移植（避免） |
|------|-----------|----------------|
| 防环 | 字符串 path：`',' || CAST(id AS TEXT) || ','` 累积，`w.path NOT LIKE '%,' || CAST(... AS TEXT) || ',%'` 判重。`||` 与 `LIKE` 两后端通吃 | PG 数组 `ARRAY[id]` / `= ANY(path)`；PG 14 `CYCLE` 子句；SQLite 均不支持 |
| 深度上限 | 递归项 `WHERE w.depth < %s`（保证终止的主手段） | 递归项内 LIMIT：SQLite 允许 [CITED: sqlite.org/lang_with.html §3]，**PG 不允许**——LIMIT 只放最外层 SELECT 作 fail-safe |
| UNION | `UNION ALL` + path 判重（SQLite 官方明确 UNION 去重要保留全部历史行、内存代价大 [CITED: sqlite.org/lang_with.html]） | 依赖 `UNION` 去重防环——depth 列使每行不同，挡不住环 |
| 占位符 | Django cursor 统一 `%s`（两后端都由 Django 适配） | 手写 `?`（sqlite3 原生风格，过不了 PG） |
| **UUID 参数** | **`KnowledgeEntity._meta.pk.get_db_prep_value(value, connection)`**：SQLite 得 32 位无连字符 hex，PG 得原生 uuid [VERIFIED: 实读 .venv Django 源码 `UUIDField.get_db_prep_value` — `has_native_uuid_field` PG=True/SQLite=False] | 直接 `str(uuid_val)`（带连字符）——SQLite 上一行都查不到，且测试全绿（测试也错）假象不会出现，反而是 PG/SQLite 行为分叉 |
| datetime 参数 | 传 aware datetime（`USE_TZ=True`，`TIME_ZONE="Asia/Shanghai"` [VERIFIED: settings.py L238-240]），Django 负责适配存储格式 | naive datetime（P2 时区漂移）；接口层 assert `tzinfo is not None` |
| 结果 UUID 还原 | `uuid.UUID(hex=row[0])` if isinstance(row[0], str) else row[0]（SQLite 回 str，PG psycopg 回 UUID 对象） | 假定单一返回类型 |

**参考实现骨架（验证过的语法要素拼装，源：sqlite.org/lang_with.html 图遍历示例 + PG queries-with 文档模式）：**

```sql
WITH RECURSIVE walk(entity_id, depth, path) AS (
    -- anchor：起点的 1 跳邻居
    SELECT e.target_entity_id, 1,
           ',' || CAST(e.source_entity_id AS TEXT) || ',' || CAST(e.target_entity_id AS TEXT) || ','
    FROM knowledge_knowledgeedge e
    WHERE e.source_entity_id = %s
      AND e.target_entity_id IS NOT NULL
      AND {validity_predicate}
      {relation_filter}
  UNION ALL
    -- 递归项：深度上限 + path 防环 + 每跳有效性过滤
    SELECT e.target_entity_id, w.depth + 1,
           w.path || CAST(e.target_entity_id AS TEXT) || ','
    FROM knowledge_knowledgeedge e
    JOIN walk w ON e.source_entity_id = w.entity_id
    WHERE w.depth < %s
      AND e.target_entity_id IS NOT NULL
      AND {validity_predicate}
      {relation_filter}
      AND w.path NOT LIKE '%%,' || CAST(e.target_entity_id AS TEXT) || ',%%'
)
SELECT entity_id, MIN(depth) AS depth FROM walk GROUP BY entity_id
ORDER BY depth LIMIT %s   -- 外层 fail-safe 上限（两后端都合法）
```

`{validity_predicate}` 由 Python 端按是否 `as_of` 生成（**仅两个固定模板字符串，不拼接用户输入**）：
- 默认：`e.invalid_at IS NULL AND e.expired_at IS NULL`
- as-of：`e.valid_at <= %s AND (e.invalid_at IS NULL OR e.invalid_at > %s) AND e.created_at <= %s AND (e.expired_at IS NULL OR e.expired_at > %s)`

`{relation_filter}`：`AND e.relation IN (...)` 只允许从 `EdgeRelation.values` 白名单生成占位符，relation 值全部走参数绑定。

**MySQL/MariaDB 注意 [ASSUMED]**：settings 名义上支持 `mysql://` DATABASE_URL；MySQL 8+ 支持 `WITH RECURSIVE` 但 `||` 默认不是字符串拼接（需 `PIPES_AS_CONCAT`）。建议 GraphStore 在 `connection.vendor not in ("sqlite", "postgresql")` 时显式 raise `NotImplementedError`（响亮失败优于静默错误结果），MySQL 支持不在本阶段范围。

### 性能基线

PITFALLS Performance Traps：递归 CTE 无深度限制/防环在"边数过万且稠密互连"时劣化——本设计 depth ≤3 + path 判重 + 活跃边部分索引三重防护。建议随接口落一个 `@pytest.mark.perf` 规模测试（数千实体/数万边下 3 跳查询延迟断言），CI 默认 skip（仓库已有 perf marker 机制 [VERIFIED: pyproject.toml markers]）。

## delivery_knowledge collection 生命周期管理

### 为什么不能复用既有路径（关键发现，已实读验证）

| 既有函数 | 行为 | 为何不可用 |
|---------|------|-----------|
| `QdrantService.create_collection`（indexer 用） | 存在且维度/hybrid 不匹配 → **`delete_collection` + 重建** [VERIFIED: qdrant_service.py L435-446] | P8 灾难语义：切 embedding 模型后第一次调用即静默清空知识库 |
| `QdrantService.create_collection_by_name` | 存在 → 直接 `return True`，**不校验任何配置**；且固定创建 `file_path/file_hash/language/branch_name` 代码索引 payload index [VERIFIED: qdrant_service.py L957-988] | 维度漂移静默放行（写入时才报错或悄悄进错库）；payload index 不符合知识 schema |
| 两者共同问题 | 异常 catch 后 `return False` 不重抛 | 知识场景失败必须响亮（P1/P8），不允许静默 False |

### 推荐实现（`knowledge/collection.py`）

```python
DELIVERY_KNOWLEDGE_COLLECTION = "delivery_knowledge"

# payload schema 第一天定型（Phase 13 摄取 / Phase 15 检索的单一事实源）
KNOWLEDGE_PAYLOAD_INDEXED_FIELDS: dict[str, PayloadSchemaType] = {
    "entity_kind": KEYWORD, "entity_id": KEYWORD, "version": INTEGER,
    "is_latest": BOOL,                        # P1 第一道防线：检索强制 filter
    "project_id": KEYWORD, "repository_id": KEYWORD,   # 权限维度（RETR-07 依赖，第一天必建）
    "source_kind": KEYWORD,
    "event_time": DATETIME,                   # 时间衰减输入（Qdrant datetime index）
}
# 非索引但必带字段：source_id / chunk_kind / file_path / text / embedding_model / version_id

async def ensure_delivery_knowledge_collection() -> None:
    """存在则严格校验配置；缺失则创建；不匹配则响亮拒绝——绝不自动删除。"""
    # 1) 读 SystemSetting EMBEDDING_DIMENSION（indexer 同款，default 1024）
    # 2) client = QdrantService.get_client()  ← 保留 60s timeout 等历史修复，不另起 client
    # 3) 不存在 → create_collection(hybrid: dense+sparse) + 全部 payload index + 记录元信息
    # 4) 存在 → get_collection 比对 dense size 与 hybrid 结构：
    #    不匹配 → logger.error("knowledge_collection_config_mismatch", existing=..., expected=...)
    #            raise KnowledgeCollectionMismatchError(
    #                "delivery_knowledge 维度不匹配（现 X 维 / 期望 Y 维）。"
    #                "请确认 embedding 配置，或运行 `manage.py rebuild_delivery_knowledge --yes` 显式重建。")
```

要点：
- 校验逻辑可抄 `create_collection` L418-435 的 vectors_config 解析（named vectors dict ⇒ hybrid；`.get("dense").size` 取维度），但分支语义反转：mismatch → raise 而非 delete [VERIFIED: 实读 L418-449]
- collection 元信息（embedding 模型名 + 维度 + schema 版本）随创建写入 SystemSetting（如 `knowledge_collection_meta` JSON），ensure 时双重校验（P8 建议）
- 同步 client 调用统一 `sync_to_async` 包装（indexer 纪律）

### 显式重建命令（`rebuild_delivery_knowledge`）

参照 `init_superuser` 的 BaseCommand 风格 [VERIFIED: 实读 accounts/management/commands/init_superuser.py]：
- `--yes` 必填确认参数（无则打印将发生什么并退出，danger 提示用 `self.style.WARNING` 横幅，init_superuser 同款视觉）
- 流程：`delete_collection_by_name` → `ensure_delivery_knowledge_collection()` → 更新 SystemSetting 元信息 → 醒目输出
- Phase 12 collection 尚无数据，重建 = 删 + 建即可；**命令 docstring 注明 Phase 13 接入摄取后需扩展"从 PG 全量重嵌入"步骤**（P8 的 reembed 完整版），给后续阶段留明确 TODO 锚点
- 测试时 Qdrant 调用全部 mock（`--disable-socket` 下真实 HTTP 会直接被 pytest-socket 拦截，这反而是双保险）

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Qdrant client/timeout/重试 | 自建 qdrant client 实例 | `QdrantService.get_client()` | 60s timeout、keepalive 禁用等三起历史事故修复都在里面（PITFALLS 技术债表：Never） |
| 唯一性/时间次序校验 | 应用层 if 检查 | `UniqueConstraint(condition=...)` + `CheckConstraint` | bulk_create / 并发路径绕过 full_clean 时 DB 兜底（ChunkEdge 双保险先例） |
| 后台执行基建 | 新线程/`asyncio.create_task` | `services/background_runner.run_in_background`（Phase 13 用，本阶段无需） | CurrentThreadExecutor 历史事故 |
| 枚举管理 | 裸字符串常量 | `models.TextChoices` | 仓库惯例 + DB CheckConstraint 联动 |
| 配置读取 | 环境变量 | `SystemSetting` / `SettingKeys` | 项目 Constraints 明文要求 |
| uuid 稳定派生 | 自拼 hash | `uuid.uuid5(NAMESPACE, key)` | ChunkRegistry 同源稳定 PK 先例 |

**Key insight:** 本阶段没有任何需要新轮子的问题——风险全部在"把既有模式的语义搬错"（indexer 的删库重建语义、`return False` 静默语义），而不是"缺能力"。

## Common Pitfalls（本阶段相关防线，提炼自 .planning/research/PITFALLS.md）

### Pitfall 1: UUID 参数跨后端格式分叉（本研究新发现，PITFALLS 未覆盖）
**What goes wrong:** raw SQL 里 `WHERE source_entity_id = %s` 直接传 `str(uuid)`——SQLite 存的是无连字符 hex，带连字符的参数永远查不到；PG 反而正常。dev（SQLite）与 prod（PG）行为分叉。
**Why it happens:** Django ORM 平时自动做 `get_db_prep_value`，raw cursor 不做。
**How to avoid:** GraphStore 内统一 `_prep_uuid(value) = KnowledgeEntity._meta.pk.get_db_prep_value(value, connection)`；CTE path 字符串里的 CAST 同理依赖列值本身（各后端内部自洽，无需额外处理）。
**Warning signs:** SQLite 测试遍历返回空但 ORM 查询有数据。

### Pitfall 2: bi-temporal 三连坑（P2）
naive datetime（`TIME_ZONE=Asia/Shanghai` + `USE_TZ=True`，±8h 漂移）/ 查询忘加有效性过滤 / 失效不级联。
**本阶段防线:** ① 写路径 service 函数 assert aware datetime（`rebuild_chunk_edges --since` 拒绝 naive 的先例）；② 过滤埋进 GraphStore（locked）；③ `invalidate_entity_version(entity, ts)` 做成单事务显式操作：同时失效版本 + 该实体出入边，并写 2–3 跳级联测试（失效后的边在多跳路径上不可达）。注意：**级联失效的完整触发时机在 Phase 13（重摄取），但操作原语和事务语义本阶段必须就位**。

### Pitfall 3: collection 自动删库重建（P8）
**防线:** 上文生命周期设计；测试显式覆盖"维度不匹配 → raise 且 collection 仍存在"。

### Pitfall 4: GraphStore 形同虚设（P9）
**防线:** grep 审计测试固化（`WITH RECURSIVE` / 边表表名 raw SQL 只允许出现在 `knowledge/graph_store.py`）；接口内置 max_hops clamp + path 防环；perf 基准测试随接口落地。

### Pitfall 5: payload 权限字段事后回填（P6）
**防线:** `project_id`/`repository_id` 进 payload schema 常量 + keyword index，第一天定型（Recovery Strategies 表标注此项回填成本 HIGH——"必须第一天就做对"）。

### Pitfall 6: 召回面/轨迹面语义分裂（P10）
**防线（本阶段的边界决策）:** 版本链回溯（KMOD-03）走 PG `KnowledgeEntityVersion` 表，**不设计任何依赖 Qdrant 的轨迹查询**；payload 里 `is_latest` 只服务召回面。本阶段把这条边界写进模型 docstring（实现契约），Phase 15 检索按此分面实现。

### Pitfall 7: 条件 UniqueConstraint 的并发竞态 [ASSUMED]
`uniq_kversion_one_latest` 在并发"翻转 is_latest"时可能出现瞬时两行 latest 撞约束（这是期望行为——撞约束即报错，优于静默双 latest）。Phase 13 摄取需 `select_for_update` 串行化同实体版本翻转；本阶段在模型 docstring 注明该契约即可。

## Code Examples

### 防环遍历 SQL 已在 §GraphStore 给出；以下为执行封装

```python
# knowledge/graph_store.py（仅此文件允许边表 raw SQL）
from asgiref.sync import sync_to_async
from django.db import connection

class RelationalGraphStore:
    """图访问唯一收口。SQLite（dev/test）与 PostgreSQL（prod）双后端。"""

    MAX_HOPS = 3
    _RESULT_LIMIT = 1000  # 外层 fail-safe

    async def traverse(self, start_id, *, max_hops=2, relations=None, as_of=None):
        hops = max(1, min(int(max_hops), self.MAX_HOPS))
        return await sync_to_async(self._traverse_sync)(start_id, hops, relations, as_of)

    def _traverse_sync(self, start_id, hops, relations, as_of):
        if connection.vendor not in ("sqlite", "postgresql"):
            raise NotImplementedError(f"GraphStore 不支持 {connection.vendor}")
        pk_field = KnowledgeEntity._meta.pk
        prep_id = pk_field.get_db_prep_value(start_id, connection)  # 关键：跨后端 UUID 格式
        sql, params = self._build_sql(prep_id, hops, relations, as_of)
        with connection.cursor() as cur:
            cur.execute(sql, params)
            rows = cur.fetchall()
        return [TraversalResult(entity_id=self._to_uuid(r[0]), depth=r[1]) for r in rows]
```

### 测试：递归遍历用例骨架（pytest-django，SQLite 直跑）

```python
# server/tests/knowledge/test_graph_store.py
import pytest
from django.utils import timezone

pytestmark = pytest.mark.django_db

async def test_cycle_does_not_loop(entity_factory, edge_factory):
    """A→B→C→A 环：3 跳遍历正常终止，每实体只出现一次。"""
    a, b, c = entity_factory(), entity_factory(), entity_factory()
    for s, t in [(a, b), (b, c), (c, a)]:
        edge_factory(source_entity=s, target_entity=t, valid_at=timezone.now())
    result = await graph_store.traverse(a.id, max_hops=3)
    assert {r.entity_id for r in result} == {b.id, c.id, a.id}  # 回到 a 算 1 次后停

async def test_invalidated_edge_invisible_by_default_but_visible_as_of(...):
    """失效边默认遍历不可见；as_of 失效前时点可见（KMOD-02 success criteria 2）。"""

async def test_depth_cap_clamped(...):
    """max_hops=10 实际只走 3 跳。"""
```

### 集中写入口（aware datetime 强制）

```python
def _require_aware(dt: datetime, field: str) -> datetime:
    """P2 防线：拒绝 naive datetime（rebuild_chunk_edges --since 同款纪律）。"""
    if dt.tzinfo is None:
        raise ValueError(f"{field} 必须是 aware datetime（USE_TZ=True，禁止 naive）")
    return dt
```

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| 图数据库（Neo4j）做多跳遍历 | PG 递归 CTE（1–3 跳负载实证反超，项目基准） | 项目选型期已定 | 零新基础设施；GraphStore 接口留逃生门 |
| 单时间戳 + 物理删除 | Graphiti/Zep 式 bi-temporal 双时间线（valid/invalid + created/expired） | 2024–2025 temporal KG 实践 | 历史可审计 + as-of 查询能力 |
| collection 自动重建（indexer 语义） | 严格校验 + 显式重建命令（知识数据不可静默丢） | 本里程碑 P8 决策 | 运维多一步显式命令，换数据安全 |

**Deprecated/outdated:** PG 14 `SEARCH`/`CYCLE` 子句虽是"更现代"写法，但 SQLite 不支持，本项目双后端约束下不可用。

## Assumptions Log

| # | Claim | Section | Risk if Wrong |
|---|-------|---------|---------------|
| A1 | MySQL/MariaDB 部署不在本阶段支持范围（`||` 拼接语义差异，vendor 检查直接 raise） | GraphStore 双方言 | 若有用户用 MySQL 跑生产，GraphStore 不可用——但 docker-compose 官方栈是 PG，风险低；逃生门接口可后补实现 |
| A2 | 条件 UniqueConstraint 并发翻转 latest 的竞态以"撞约束报错"为期望行为，串行化责任在 Phase 13 摄取 | Pitfall 7 | 若 Phase 13 未做 select_for_update，并发重摄取会偶发 IntegrityError（可观测、可重试，非静默错误） |
| A3 | 四类实体的 `EntityKind` 字面值（work_item/tech_plan/code_change/document）与 REQUIREMENTS 命名一致即为最终值 | 实体 schema | kind 进了 uuid5 PK 派生与 payload schema，改名 = 数据迁移；建议 planner 确认后锁死 |
| A4 | `EdgeRelation` 初始枚举集（HAS_PLAN/IMPLEMENTED_BY/REFERENCES/RELATES_TO/DUPLICATE_OF/MODIFIES_CHUNK）覆盖 Phase 13–15 需求 | 边 schema | TextChoices 加值只需新 migration（CheckConstraint 更新），成本低 |

## Open Questions

1. **[RESOLVED — 规划定案：不建]** CodeChangeArchive 表结构是否随本阶段 migrations 建好？
   - What we know: ROADMAP Note 允许；KMOD-05 交付验证在 Phase 14
   - What's unclear: 现在建省一次后续 migration，但 Phase 14 对字段的真实需求（压缩策略、unidiff 解析粒度）届时才清晰
   - Resolution（12-01..03 PLAN 已采纳）: 不建。Phase 14 自带 migration 成本极低，过早定型反而要改
2. **[RESOLVED — 规划定案：首版 (entity_id, depth)]** GraphStore 遍历是否需要返回路径（边链）而不止终点实体？
   - What we know: Phase 15 图扩散需要邻居集合；RETR-02 双向上下游展示可能需要边 relation 信息
   - Resolution（12-02 PLAN 已采纳）: `TraversalResult` 预留 `depth`，首版返回 (entity_id, depth)；`neighbors()` 单跳带边详情。路径重建需求出现时再扩展接口（接口演进不破坏收口）
3. **[RESOLVED — 规划定案：枚举字面值在 12-01 Task 1 docstring 锁死]** `EntityKind`/`EdgeRelation` 枚举字面值（kind 进 uuid5 PK 派生，改名即数据迁移）
   - Resolution: 12-01 PLAN Task 1 以模型 docstring 作为实现契约锁定字面值（work_item / tech_plan / code_change / document；feishu / chat / mcp / workflow）

## Environment Availability

| Dependency | Required By | Available | Version | Fallback |
|------------|------------|-----------|---------|----------|
| SQLite（递归 CTE） | 本地 dev/test GraphStore | ✓ | 3.50.4（venv）/ 3.51.2（系统）[VERIFIED] | — |
| PostgreSQL | 生产 GraphStore | compose 栈内 `postgres:17-alpine` | — | dev 用 SQLite，无需本地 PG |
| Qdrant | collection 生命周期（运行时） | compose 栈内 | — | 测试全 mock（`--disable-socket` 强制），不依赖真实 Qdrant |
| Python/uv/Django | 全部 | ✓（既有开发环境，`make dev` 在跑） | Python 3.14 / Django 5.1+ | — |

**Missing dependencies with no fallback:** 无——本阶段所有外部服务在测试中均被 seam 隔离。

## Validation Architecture

### Test Framework

| Property | Value |
|----------|-------|
| Framework | pytest >=9.0.2 + pytest-django + pytest-asyncio（`asyncio_mode=auto`）[VERIFIED: server/pyproject.toml] |
| Config file | `server/pyproject.toml [tool.pytest.ini_options]`（`testpaths=["tests"]`，`--disable-socket`） |
| Quick run command | `cd server && uv run pytest tests/knowledge/ -x` |
| Full suite command | `cd server && uv run pytest` |

### Phase Requirements → Test Map

| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| KMOD-01 | 四类实体落库；natural key 唯一约束生效；kind/origin 枚举 DB 兜底 | unit | `uv run pytest tests/knowledge/test_models.py -x` | ❌ Wave 0 |
| KMOD-02 | 四时间戳边；失效置位后默认遍历不可见、as_of 历史可见；时间次序 CheckConstraint | unit | `uv run pytest tests/knowledge/test_graph_store.py -k "invalid or as_of" -x` | ❌ Wave 0 |
| KMOD-03 | supersedes 版本链；按版本号回溯；one-latest 部分唯一约束 | unit | `uv run pytest tests/knowledge/test_models.py -k version -x` | ❌ Wave 0 |
| KMOD-04 | 1–3 跳遍历；环终止；深度 clamp；raw SQL 收口 grep 审计 | unit | `uv run pytest tests/knowledge/test_graph_store.py -x` | ❌ Wave 0 |
| SC#5 | collection 维度不匹配 raise 不删库；重建命令 `--yes` 流程 | unit（Qdrant mock） | `uv run pytest tests/knowledge/test_collection.py -x` | ❌ Wave 0 |

**特别测试（PITFALLS 防线固化）：**
- grep 审计测试：`rg "WITH RECURSIVE"` 与边表表名的 raw SQL 出现处 ⊆ {`knowledge/graph_store.py`}（P9 验证手段，可写成读源码的 pytest 用例）
- 双后端一致性：所有 GraphStore 测试在 SQLite 下跑（CI 默认）；UUID prep 路径有专测（Pitfall 1）
- 环用例（A→B→C→A）、深度用例（4 跳链只回 3 跳）、失效边用例（多跳路径中段失效 → 下游不可达）
- perf 基准（`@pytest.mark.perf`，CI skip）：数千实体/数万边 3 跳延迟断言

### Sampling Rate
- **Per task commit:** `cd server && uv run pytest tests/knowledge/ -x`
- **Per wave merge:** `cd server && uv run pytest`（全套，约束/迁移回归）
- **Phase gate:** 全套 green + `uv run python manage.py makemigrations --check --dry-run`（migrations 与模型同步）

### Wave 0 Gaps
- [ ] `server/tests/knowledge/__init__.py` + `test_models.py` + `test_graph_store.py` + `test_collection.py`
- [ ] `server/tests/knowledge/conftest.py` — entity/edge/version factory fixtures（factory-boy，参照既有 `tests/conftest.py::repository` fixture 风格）
- [ ] Qdrant seam fixture：autouse monkeypatch stub（照抄 `tests/test_git_diff_index.py::_stub_qdrant_calls` 模式）
- 框架本身零安装（pytest 基建齐备）

## Security Domain

### Applicable ASVS Categories

| ASVS Category | Applies | Standard Control |
|---------------|---------|-----------------|
| V2 Authentication | no（本阶段无 HTTP 面） | — |
| V3 Session Management | no | — |
| V4 Access Control | yes（地基预埋） | payload `project_id`/`repository_id` + keyword index 第一天定型（RETR-07 在 Phase 15 强制 service 层过滤的前提）；GraphStore 接口签名预留 scope 参数位 |
| V5 Input Validation | yes | relation/kind 全部 TextChoices 白名单 + DB CheckConstraint；raw SQL 零字符串拼接用户输入（relation 白名单生成占位符，值走参数绑定） |
| V6 Cryptography | no（本阶段不触凭证；若触碰必须走 ProviderCredential/Fernet 既有层） | — |

### Known Threat Patterns for 本阶段栈

| Pattern | STRIDE | Standard Mitigation |
|---------|--------|---------------------|
| 递归 CTE SQL 注入 | Tampering | 全参数化（`%s` 绑定）；relation/方向等枚举值白名单校验后才进 SQL 模板 |
| 无界遍历 DoS | Denial of Service | max_hops clamp ≤3 + path 防环 + 外层 LIMIT + 活跃边部分索引 |
| 权限维度缺失（事后不可补） | Information Disclosure | payload schema 含 project_id/repository_id（P6：回填成本 HIGH，Never 推迟） |
| 知识历史被静默清空 | Tampering / Repudiation | collection 不匹配拒绝 + 显式重建命令需 `--yes`；structlog error 留痕 |

## Sources

### Primary (HIGH confidence)
- 本仓库实读：`server/code_relations/models.py`（约束/索引/柔性引用范式）、`server/services/qdrant_service.py` L392-1012（create_collection 删库重建语义 / create_collection_by_name 不校验语义——本研究关键发现）、`server/services/indexer.py` `_ensure_collection`（EMBEDDING_DIMENSION 读取）、`server/accounts/management/commands/init_superuser.py`、`server/friday/settings.py`（SQLite 默认 DB / INSTALLED_APPS / TIME_ZONE+USE_TZ）、`server/tests/test_git_diff_index.py`（Qdrant seam 模式）、`server/tests/code_relations/test_models.py`（SQLite EXPLAIN 证实测试跑 SQLite）、`server/pyproject.toml`（pytest 配置）、`server/services/background_runner.py`、`server/system/models.py` SettingKeys
- Django 5.x 源码（`.venv` 实读验证）：`UUIDField.get_db_prep_value` + `has_native_uuid_field`（PG=True / base=False）——UUID 跨后端格式分叉结论
- SQLite 官方文档 `WITH` 子句：https://sqlite.org/lang_with.html（本会话抓取：UNION ALL 语义、递归项 LIMIT 允许、防环示例、聚合函数限制）
- 本机验证：SQLite 3.50.4（venv）/ 3.51.2（系统）支持递归 CTE
- `.planning/research/PITFALLS.md`（P1/P2/P8/P9/P10 防线，自带 HIGH 佐证链）、`.planning/research/ARCHITECTURE.md`（schema 草案与结构裁决，基于实读）

### Secondary (MEDIUM confidence)
- PostgreSQL `WITH` 文档：https://www.postgresql.org/docs/current/queries-with.html（递归 CTE / 递归项限制——训练知识 + 与 SQLite 文档交叉，本会话未重新抓取）
- Graphiti/Zep bi-temporal 模型（valid/invalid + created/expired 双时间线）——经 PITFALLS 前期调研引用（arXiv:2501.13956）

### Tertiary (LOW confidence)
- MySQL `WITH RECURSIVE` + `PIPES_AS_CONCAT` 行为（训练知识，未验证）——已按 A1 处理为显式 NotImplementedError

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH — 零新依赖，全部既有库实读确认
- Architecture / schema: HIGH — 字段与约束均有仓库同型先例 + success criteria 字面对齐；枚举字面值留 A3/A4 待 planner 锁定
- 递归 CTE 双方言: HIGH — SQLite 官方文档本会话抓取 + Django UUIDField 源码实读 + 本机版本验证；MySQL 例外为 LOW（已隔离为 raise）
- Pitfalls: HIGH — 直接继承 PITFALLS.md 防线（其自带事故级佐证）+ 本研究新增 UUID prep 坑（源码级验证）

**Research date:** 2026-06-11
**Valid until:** 2026-07-11（稳定领域：Django/SQLite/PG 语义不漂移；Qdrant 既有封装为仓库内事实）
