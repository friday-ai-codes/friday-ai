# Stack Research

**Domain:** 交付知识图谱（需求/缺陷 ↔ 技术方案 ↔ 代码 diff 的 GraphRAG 关联）— brownfield 增量（v0.3.0）
**Researched:** 2026-06-11
**Confidence:** HIGH（关键版本均经 PyPI / 官方文档核实；与现有 `server/` 代码逐一对照）

## 总体结论（TL;DR）

本里程碑**几乎不需要新增运行时依赖**。核心增量是：

1. **新增 1 个依赖**：`unidiff==0.7.5`（diff/patch 解析，纯 Python、零传递依赖）
2. **可选新增 1 个依赖**：`django-cte>=3.0.0`（仅当希望递归 CTE 走 ORM 组合；推荐先用 raw SQL，不加依赖）
3. 其余全部复用既有栈：`qdrant-client 1.16.2`（锁定版已支持全部所需 API）、`EmbeddingService` + `sparse_encoder`（fastembed 0.7.4）、Postgres 17（TOAST lz4 压缩）、Python 3.14 stdlib `compression.zstd`（如需应用层压缩）

## Recommended Stack

### Core Technologies（全部为既有依赖，零升级即可用）

| Technology | Version（现状） | Purpose | Why Recommended |
|------------|----------------|---------|-----------------|
| Django ORM + Postgres 17 | django>=5.1 / postgres:17-alpine | bi-temporal 边模型 + 递归 CTE 1–3 跳遍历 | 沿用 ChunkEdge 同模式（UUID 柔性引用 + CheckConstraint + 复合索引）；PG 递归 CTE 在 1–3 跳负载下吞吐已有基准背书（项目已定决策） |
| qdrant-client | 1.16.2（锁定，spec `>=1.9.0`） | 新 collection 的向量化/混合检索/版本化删除 | 锁定版已包含 Query API（`query_points` + `Prefetch` + `FusionQuery(RRF)`，`qdrant_service.py` 已在用）、scalar 量化、datetime payload index、`delete` by filter、`set_payload`，**无需升级**。最新版 1.18.0（2026-05-11）非必需 |
| EmbeddingService + sparse_encoder | 既有（fastembed 0.7.4 供 sparse BM25） | 需求/方案/diff 文本向量化 | 项目硬约束：Embedding 走系统配置远程 HTTP API（当前 doubao-embedding-text 2560 维），不绑定模型；sparse 沿用 fastembed BM25 |
| Python 3.14 stdlib `compression.zstd` | stdlib（PEP 784，3.14 新增） | 超大 diff 的应用层压缩兜底 | 项目已 pin `>=3.14`，stdlib 原生 zstd（`compress`/`decompress`/`ZstdFile`），**省掉 `zstandard` PyPI 包** |

### Supporting Libraries（新增项）

| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| `unidiff` | `==0.7.5`（PyPI 最新，2023 起 API 冻结、稳定） | 解析 `git diff` 统一格式 → 按 file/hunk 切块、提取 added/removed 行数与 file_path 元数据 | 全量 diff 归档后做"per-file/per-hunk 向量化 chunk"与统计（`PatchSet` + `metadata_only=True` 高效模式）。**必加**，自研 diff parser 不值得 |
| `django-cte` | `>=3.0.0,<4`（2026-02-05 发布，Production/Stable，显式适配 Django 5.1/5.2） | 用 ORM 组合方式写 `WITH RECURSIVE` 遍历 | **可选**。仅当图遍历查询需要与既有 QuerySet（权限过滤、租户过滤）深度组合时引入；首选方案是 raw SQL（见下） |

### Development Tools

| Tool | Purpose | Notes |
|------|---------|-------|
| pytest + factory-boy（既有） | bi-temporal 边/遍历/版本化重摄取测试 | 注意：本地测试可能跑 SQLite——`WITH RECURSIVE` SQLite 3.8.3+ / PG / MySQL 8 全支持，raw SQL 写法保持三库兼容（避免 PG 专属 `= ANY(path)` 数组语法时需条件分支，或测试标记 `@pytest.mark.django_db` 限定 PG） |
| `EXPLAIN ANALYZE` + 复合/部分索引 | 递归 CTE 调优 | 关键索引：`(source_id) WHERE expired_at IS NULL` 部分索引（只扫活跃边），仿照 `idx_chunkedge_fanout` 模式 |

## 逐题结论

### 1) bi-temporal 边模型 + 递归 CTE：原生 ORM vs raw SQL vs django-cte

**字段模型（借鉴 Graphiti，已验证其官方定义）**：每条边四时间戳——

- 事实时间：`valid_at`（事实开始为真）/ `invalid_at`（事实不再为真，nullable）
- 系统时间：`created_at`（摄取时间，恒有值）/ `expired_at`（被新版本取代时间，nullable）
- 失效用**置位 `expired_at`/`invalid_at` 而非删除**（历史可溯）；"当前有效"谓词 = `expired_at IS NULL`
- Django 落地：沿用 `ChunkEdge` 既有模式（UUIDField 柔性引用、`CheckConstraint` 兜底、`UniqueConstraint` 含版本维度）；新增部分索引 `models.Index(fields=["source_id"], condition=Q(expired_at__isnull=True), name=...)`

**遍历方案取舍**：

| 方案 | 结论 | 理由 |
|------|------|------|
| 原生 ORM 逐跳查询（Python BFS） | ❌ 不推荐为主路径 | 1–3 跳每跳一次往返，N+1 放大；但现有 `hop1_reader`（payload 直读 + `in_bulk`）模式对"一跳"仍最快，可保留为 fast path |
| **raw SQL `WITH RECURSIVE`（`connection.cursor()`）** | ✅ **首选** | 零新依赖；bi-temporal 谓词（`expired_at IS NULL AND (invalid_at IS NULL OR invalid_at > %s)`）、深度上限、`path` 数组防环（PG `point_id = ANY(path)`）在 SQL 里直写最清晰；查询条数少且稳定，收敛在 GraphStore service 内部，正符合"留换引擎逃生门"的接口收敛决策 |
| `django-cte` 3.0.0 | ⚪ 备选 | 若后续遍历需要与 RBAC/租户 QuerySet 组合再引入。注意 3.0.0 有 Django 5.2 行为 breaking changes（LOUTER 隐式 join、`values('fk_name')` 列名一致性），升级 Django 5.2 时需回归 |

> 防环提示：纯靠 `UNION`（去重）防环在带 `depth`/`path` 列时失效（每行不同），必须显式 `path` 数组 + `NOT (id = ANY(path))`，并加 `depth < 3` 硬上限。

### 2) Qdrant 多 collection 管理（2560 维）

**结论：复用 `QdrantService` 既有 `*_by_name` 系列方法（`create_collection_by_name` / `upsert_vectors_by_name` / `hybrid_search_by_name`），新增 1 个业务 collection，不需要升级 qdrant-client。**

- **命名**：沿用前缀约定（现有 `code_index_{repository_id}`、`repo_summaries`）→ 建议单一全局 `delivery_knowledge`（交付知识跨仓库/跨项目，靠 payload 过滤分域），避免 per-entity collection 爆炸
- **2560 维内存/磁盘策略**（Qdrant 官方推荐已验证）：

```python
vectors_config={"dense": models.VectorParams(
    size=2560, distance=models.Distance.COSINE,
    on_disk=True,                      # 原始向量落盘（不设这个量化不省内存）
)},
sparse_vectors_config={"sparse": models.SparseVectorParams()},
quantization_config=models.ScalarQuantization(
    scalar=models.ScalarQuantizationConfig(
        type=models.ScalarType.INT8,
        quantile=0.99,                 # 排除极端值，保 int8 映射精度
        always_ram=True,               # 量化向量常驻内存
    )
),
```

  高维向量量化误差更小（官方明示），scalar int8 + 原始向量 on_disk 是"内存省 4x、召回基本无损"的标准组合；rescore 需要时读盘，2560 维候选集小、可接受
- **payload index**（keyword 除非注明）：`entity_type`（requirement/plan/diff…）、`entity_id`、`version`（integer）、`is_latest`（bool）、`repository_id`、`valid_at`（datetime index，时间感知检索用范围过滤）。沿用 `create_payload_index` 既有调用模式
- **版本化 upsert/删除模式**：
  - point ID 用确定性 `uuid5(NAMESPACE, f"{entity_id}:{version}:{chunk_index}")` → 重摄取天然幂等（与 ChunkRegistry"同 chunk_id 触发 update"同哲学）
  - 新版本写入后，旧版本**两段式下线**：先 `set_payload({"is_latest": False})`（保历史可查、检索默认过滤 `is_latest=True`），需要硬删除时 `delete(points_selector=FilterSelector(filter=Filter(must=[entity_id==X, version<N])))`
  - `batch_set_payload`（`qdrant_service.py:1318` 已有）可直接复用
- **Qdrant 服务端**：docker-compose 目前 `qdrant/qdrant:latest` —— 建议本里程碑顺手 pin 具体版本（如 `v1.16+`），量化/datetime index 均为多年稳定特性，无版本风险

### 3) 全量 git diff/patch 归档

**结论：Postgres `TextField` + 列级 TOAST lz4 压缩为主，`unidiff` 解析切块；不引入大对象（Large Object）、不引入 `zstandard` 包。**

| 层 | 方案 | 理由 |
|----|------|------|
| 存储 | `TextField`（diff 原文）+ migration `RunSQL("ALTER TABLE ... ALTER COLUMN patch_text SET COMPRESSION lz4")` | PG14+ 列级 TOAST 压缩；`postgres:17-alpine` 官方镜像 `--with-lz4` 编译（已验证 Dockerfile）。透明压缩、ORM 无感知、psql 可直查调试 |
| 超大 diff 兜底 | 设大小阈值（如 5–10MB）：超限存 `BinaryField` + stdlib `compression.zstd.compress()`，或仅存摘要+文件清单 | Python 3.14 stdlib 含 zstd（PEP 784），零依赖；diff 文本压缩率通常 5–10x |
| 解析 | `unidiff==0.7.5`：`PatchSet(text)` → per `PatchedFile` / `Hunk` 切块向量化，`metadata_only=True` 做纯统计 | 唯一仍是事实标准的纯解析库（MIT，284 stars）；项目只需"解析"不需"apply"，排除 `whatthepatch`/`patch-ng` |
| 注意 | migration 的 `SET COMPRESSION` 只影响**新写入**行；SQLite 测试环境无此语句 → RunSQL 需 `state_operations=[]` + 按 vendor 跳过（`connection.vendor != "postgresql"` no-op） | 兼容既有"本地 SQLite 开发"路径 |

### 4) 长文本（需求/PRD/技术方案 markdown）chunking

**结论：自研轻量 markdown 标题感知分块（~100 行），不加依赖。**

- 现有代码已自研 AST-aware code chunker（`services/code_parser.py` `_ast_aware_chunk`），文本侧同样自研符合项目惯例
- 策略：按 heading 层级（`#`/`##`/`###`）切 section → 超长 section 按段落（空行）二次切 → 仍超长按字符窗口 + overlap 兜底；每 chunk 携带 heading path（如 `需求背景 > 验收标准`）入 payload，提升召回可解释性
- **关键约束**：版本化重摄取要求 chunking **确定性**（同输入同切分 → 同 `uuid5` point ID 幂等），自研最可控；第三方 splitter 升级可能改变切分边界导致全量重写
- 备选（零新增依赖但不推荐扩大使用）：`llama-index` 在 `pyproject.toml` 声明但**代码零 import**（事实死依赖），其 `MarkdownNodeParser`/`SentenceSplitter` 可用却会把死依赖变活；`langchain-text-splitters` 则是**净新增依赖**（langchain 1.x 已不传递依赖它，uv.lock 无此包）——均排除

### 5) 明确排除项（不需要新增的依赖）

| Avoid | Why | Use Instead |
|-------|-----|-------------|
| `neo4j` / 任何图数据库 driver | 已定决策不引图库；八引擎基准 1–3 跳负载 PG 递归 CTE 吞吐反超 Neo4j（22.5K vs 14.5K RPS） | Postgres 递归 CTE + GraphStore 接口收敛 |
| `graphiti-core` | 强绑定 Neo4j/FalkorDB driver + LLM 实体抽取（项目明确不做自由文本抽取）；只**借鉴**其四时间戳 bi-temporal 模型，自实现 ~4 个字段即可 | 自建 Django 模型（见第 1 题） |
| `graphrag`（Microsoft）/ `lightrag-hku` | 批处理索引贵 / LLM 抽实体，选型对比已否决 | 结构化业务数据直建边（工作项/方案/MR 自带稳定 ID） |
| `pgvector` / `django-pgvector` | 双向量存储徒增一致性负担；Qdrant hybrid（dense+sparse+RRF）已成熟在用 | 既有 `QdrantService` |
| `networkx` | 图在 DB 内遍历（1–3 跳 + 深度上限），无需全图载入内存做算法 | 递归 CTE |
| `zstandard`（PyPI） | Python 3.14 stdlib `compression.zstd`（PEP 784）完全覆盖 | stdlib |
| `whatthepatch` / `patch-ng` | 只需解析不需 apply；unidiff 对 hunk/行级元数据建模更细 | `unidiff` |
| `langchain-text-splitters` | 净新增依赖且切分非确定性风险（版本升级改边界 → 幂等性破坏） | 自研 markdown chunker |
| `django-mptt` / `django-treebeard` | 面向树（单父），交付图是带时间维的有向图 | 自建边表 |
| Celery / 任务队列 | 摄取/重摄取走既有 `background_runner` + `django-apscheduler` 即可 | 既有基础设施 |
| qdrant-client 升级到 1.18 | 锁定的 1.16.2 已含全部所需 API（Query API/量化/datetime index/filter delete）；1.18 主要是 fastembed 0.8 bump 与 turboquant，非必需 | 维持 `>=1.9.0` spec（或收紧为 `>=1.16` 表达真实下限） |

## Stack Patterns by Variant

**If 遍历查询需要与 RBAC/QuerySet 组合（后续演进）：**
- 引入 `django-cte>=3.0.0,<4`，用 `CTE.recursive()` 重写 GraphStore 内部实现
- Because GraphStore 接口已收敛，内部实现可替换而不影响调用方

**If diff 普遍超大（监控发现 p95 > 10MB）：**
- 切换该实体到 `BinaryField` + stdlib zstd + 仅向量化 per-file 摘要
- Because TOAST 单字段上限 1GB 但性能在数十 MB 级开始劣化

**If 本地开发用 SQLite：**
- 递归 CTE 写法避免 PG 数组语法（防环改用 depth 上限 + 结果端去重），或 GraphStore 留 vendor 分支
- Because SQLite 支持 `WITH RECURSIVE` 但无 `ANY(array)`

## Version Compatibility

| Package A | Compatible With | Notes |
|-----------|-----------------|-------|
| `unidiff==0.7.5` | Python 3.14 | 纯 Python、零依赖，2023 年后无 release 但 API 冻结稳定（GitHub 活跃度低是风险点，但库本身 ~1k 行、可 fork 兜底） |
| `django-cte==3.0.0` | Django 5.1 / 5.2，Python >=3.9 | 3.0.0 专为 Django 5.2 行为变更发布；当前项目 Django 5.1 用 2.x 语法亦可，直接上 3.0.0 免二次迁移 |
| `qdrant-client==1.16.2` | Qdrant server（compose 现为 `latest`） | client minor 版本官方兼容 server ±1 minor；建议 pin server 镜像消除漂移 |
| `compression.zstd` | Python >=3.14（stdlib） | 项目 `.python-version` 已 pin 3.14，无条件可用 |
| Postgres TOAST lz4 | postgres:17-alpine 官方镜像 | `--with-lz4` 编译已验证（docker-library Dockerfile）；MySQL 部署路径无此特性（该列退化为无压缩，功能不受影响） |

## Installation

```bash
# server/ 下（uv 管理）
cd server
uv add "unidiff==0.7.5"

# 可选（仅当决定走 ORM 组合式 CTE）
uv add "django-cte>=3.0.0,<4"
```

## 与既有服务的集成点速查

| 新能力 | 复用点 |
|--------|--------|
| 向量化 | `services/embedding.py` EmbeddingService（dense）+ `services/sparse_encoder.py`（sparse BM25） |
| collection 管理/检索 | `services/qdrant_service.py`：`create_collection_by_name` / `upsert_vectors_by_name` / `hybrid_search_by_name`（已含 RRF Prefetch）/ `batch_set_payload` |
| 一跳 fast path | `services/retrieval/hop1_reader.py` payload 直读模式可平移（交付实体邻居快照入 payload） |
| 边模型范式 | `code_relations/models.py` ChunkEdge：UUID 柔性引用、CheckConstraint 双保险、复合索引命名 |
| 摄取调度 | `services/background_runner.py` + `django-apscheduler` |
| 来源快照 | `mcp_tools` 的 `McpWorkItemContext` / `McpWorkItemTechnicalPlan`；执行结果 `TaskResult`/`CodingTask`（diff 全量归档为新增字段/新表） |

## Sources

- https://pypi.org/project/django-cte/ + GitHub CHANGELOG v3.0.0 — 版本 3.0.0（2026-02-05）、Django 5.1/5.2 适配与 breaking changes（HIGH）
- https://dimagi.github.io/django-cte/ — `CTE.recursive()` 用法（HIGH）
- https://qdrant.tech/documentation/manage-data/quantization/ + /operations/optimize/ — scalar int8 + `on_disk=True` + `always_ram=True` + `quantile=0.99` 官方推荐组合；高维量化误差更小（HIGH）
- https://pypi.org/project/qdrant-client/ + GitHub releases — 最新 1.18.0（2026-05-11）；锁定版 1.16.2 能力核对（HIGH）
- https://pypi.org/project/unidiff/ + GitHub matiasb/python-unidiff — 0.7.5 为最新；`metadata_only` 模式（HIGH；维护活跃度 LOW 已标注风险）
- https://pypi.org/project/whatthepatch/（1.0.7）、conan-io/python-patch-ng（1.19.0）— 排除项核对（MEDIUM）
- https://getzep-graphiti.mintlify.app/concepts/temporal-model + Zep 官方博客 — bi-temporal 四时间戳定义与失效语义（HIGH）
- https://docs.python.org/3/library/compression.zstd.html + PEP 784 — Python 3.14 stdlib zstd（HIGH）
- docker-library/postgres Dockerfile（alpine template）+ issue #1191 — alpine 镜像 `--with-lz4` 编译、`ALTER COLUMN SET COMPRESSION lz4` 可用（HIGH）
- 本仓库实地核对：`server/uv.lock`（qdrant-client 1.16.2 / fastembed 0.7.4 / llama-index 声明未用 / 无 langchain-text-splitters）、`server/services/qdrant_service.py`（Query API + RRF 已用、`*_by_name` 系列、`batch_set_payload`）、`server/code_relations/models.py`、`server/services/retrieval/hop1_reader.py`、`docker-compose.yaml`（qdrant `latest`）

---
*Stack research for: 交付知识图谱（v0.3.0，brownfield 增量）*
*Researched: 2026-06-11*
