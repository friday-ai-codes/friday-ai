# Phase 13: 统一摄取与版本化 - Research

**Researched:** 2026-06-11
**Domain:** 知识摄取管线（幂等 / 异步 / 版本化）— Friday AI brownfield，零新依赖
**Confidence:** HIGH（全部结论基于实读本仓库代码验证，文件:行号锚点齐全；无外部新库引入）

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions

All implementation choices are at Claude's discretion — pipeline/infrastructure phase，无直接用户界面。以 ROADMAP Phase 13 success criteria、REQUIREMENTS INGEST-03/05/06/07/08、Phase 12 已定型的契约为准。

已锁定的硬约束（不可偏离）：
- Phase 12 契约是上游事实源：实体经 `generate_entity_id`（uuid5 natural key）落 `knowledge` app 三模型；payload schema 8 字段以 `knowledge/collection.py` 常量为唯一事实源；图写入只走 GraphStore 接口（不得绕过）；边失效用 GraphStore 置位原语（不可覆盖已置位时间戳）
- 摄取一律 `transaction.on_commit` + `services/background_runner.run_in_background` 异步执行，不阻塞请求/工作流主链路
- 幂等：同一事件重复投递不产生重复实体/版本（幂等键约束兜底 + reconcile 对账命令可验证）
- `is_latest` 翻转是版本下线第一道防线，物理删除向量只是优化（PITFALLS 防线）
- 对话原文不入图——只摄取提炼后的需求文本与方案
- 触发点只做接线（调用统一摄取 service），不在各触发点内重复实现摄取逻辑

### Claude's Discretion

全部实现选择（模块布局、DTO 形态、chunk 策略、reconcile 检查项等）。

### Deferred Ideas (OUT OF SCOPE)

None — discuss skipped（infrastructure phase）。

不在本阶段：workflow/编码回调/飞书触发点与 diff 归档（Phase 14）、检索（Phase 15）、入口暴露（Phase 16）。
</user_constraints>

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| INGEST-03 | chat 产出 CodingPlan / 触发编码时自动摄取提炼后文本（对话原文不入图） | §触发点锚点（chat）：模型方法收口 + 编码触发点；§取材策略 |
| INGEST-05 | MCP 工具链产出方案 / 执行编码时自动摄取 | §触发点锚点（MCP）：`technical_plan_service` acreate 尾部 + `execute_work_item_repo_tasks` 成功路径尾部 |
| INGEST-06 | 重摄取为新版本：新向量入库、旧向量下线（is_latest 翻转 + 物理删除）、旧边置位 | §版本翻转事务序（六步序 + 失败恢复矩阵）；Open Question 1（expired_at 措辞） |
| INGEST-07 | on_commit + background runner 异步；幂等键 + reconcile 对账命令 | §异步投递边界（async 上下文注册 on_commit 的写法）；§幂等设计（四层幂等）；§reconcile 检查项 |
| INGEST-08 | 确定性 chunk + EmbeddingService 向量化写入 delivery_knowledge（hybrid，payload 完整） | §确定性 chunk 策略；§hybrid 写入实际 API 调用链（含 vector dict 格式实证） |
</phase_requirements>

## Summary

Phase 13 是纯本仓库模式拼装，零新外部依赖。Phase 12 已交付全部地基且刻意为本阶段留好了挂点：`generate_entity_id` 是幂等锚（uuid5 同源 PK + natural key 唯一约束），`uniq_kversion_one_latest` 条件唯一约束在 DB 层兜底单 latest，`invalidate_entity_version` 是为"重摄取"专门交付的单事务级联失效原语（12-02 SUMMARY 明言"Phase 13 摄取消费"），`collection.py` 的 8+6 字段 payload 常量是写入契约的唯一事实源，`rebuild_delivery_knowledge` 命令的 docstring 留了"从 PG 全量重嵌入"的 TODO 锚点。

本阶段的全部新代码集中在 `server/knowledge/` 内：一个摄取核心（`ingestion.py`，幂等 upsert + 版本翻转 + 向量写入编排）、一个确定性 chunker（知识文本是 markdown/纯文本，**不要**复用 indexer 的 tree-sitter 代码切块）、一个 Qdrant 写操作薄层（沿 `collection.py` 既有的 `QdrantService.get_client()` + `sync_to_async` 模式，语义与 indexer 刻意相反：`wait=True` + 失败重抛，绝不 `return False` 静默）、两个 source normalizer、一个 reconcile 管理命令。四个触发点（chat 两个、MCP 两个）每处只加 3–5 行接线。

最大的实现风险点有三个：① async 上下文注册 `transaction.on_commit` 必须经 `sync_to_async` 桥接（仓库现有 on_commit 用法全在 sync signal handler 中，async 路径无先例，写法见 §异步投递边界）；② `QdrantService.upsert_vectors_by_name` 返回 `False` 不重抛（P1 防线要求知识路径失败必须响亮，调用处必须检查返回值并 raise）；③ `EmbeddingService.generate_embeddings_batch` 失败项返回 `None`（任何 None 必须整体 abort，禁止写入残缺向量）。

**Primary recommendation:** 摄取核心做成"一个 async 入口函数 + 单 sync 事务函数"的两层结构：DB 写全部在一个 `transaction.atomic()` + `select_for_update` 的同步函数内完成（含确定性 point id 预先落库），向量写入在 DB commit 之后按"upsert 新 → tombstone 旧 → 物理删旧"次序执行，任一步失败只影响优化层，检索正确性由 `is_latest` filter 兜底。

## Architectural Responsibility Map

| Capability | Primary Tier | Secondary Tier | Rationale |
|------------|-------------|----------------|-----------|
| 触发点接线（4 处） | API / Backend（既有 view/service/model 方法） | — | 只组装 ID 调统一入口，不写摄取逻辑（locked） |
| 摄取调度（on_commit + 投递） | Backend service（`knowledge/ingestion.py`） | background_runner worker 线程 | 请求路径只付一次注册成本 |
| 实体/版本/边写入 | Database / Storage（PG，经 ORM + GraphStore） | — | 幂等约束与版本链全在 DB 层兜底 |
| chunk + 向量化 | Backend service（chunker + EmbeddingService 远程 API） | — | embedding 是远程调用，必须在后台线程 |
| 向量写入/下线 | Database / Storage（Qdrant delivery_knowledge） | — | payload schema 以 collection.py 常量为准 |
| 对账（reconcile） | Backend management command | — | 运维入口，`verify_payload_consistency` 同款形态 |

## Standard Stack

### Core（全部为仓库既有件，零安装）

| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| Django ORM + `transaction.atomic`/`on_commit` | django>=5.1（已装） | 幂等约束、版本翻转事务、commit 后调度 | 仓库唯一持久化路径 [VERIFIED: 本仓库 pyproject] |
| `services/background_runner.run_in_background` | 仓库内 | 脱离请求生命周期的后台 coroutine | CurrentThreadExecutor 事故的既定解法（模块 docstring）[VERIFIED: 实读] |
| `knowledge/graph_store.graph_store` 单例 | Phase 12 产物 | `add_edge` / `invalidate_entity_version` | 图写入唯一收口（grep 审计测试守护）[VERIFIED: 实读] |
| `knowledge/collection.py` 常量 + `ensure_delivery_knowledge_collection` | Phase 12 产物 | payload schema / collection 自检 | 唯一事实源（locked）[VERIFIED: 实读] |
| `services/embedding.EmbeddingService` | 仓库内 | dense 向量化（远程 API，批量） | 既有路径，系统配置驱动 [VERIFIED: 实读] |
| `services/sparse_encoder.SparseEncoderService` | 仓库内 | BM25 sparse 向量（同步，需 sync_to_async） | hybrid 既有路径 [VERIFIED: 实读] |
| `services/qdrant_service.QdrantService` | 仓库内 | `get_client()` / `upsert_vectors_by_name` | timeout/keepalive/retry 历史修复全在其中 [VERIFIED: 实读] |

### Supporting

| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| `hashlib.sha256` | stdlib | content_hash（`KnowledgeEntityVersion.content_hash` 字段契约） | 版本短路判定（CodingPlan 去重同款手法） |
| `uuid.uuid5` | stdlib | 实体 id（唯一经 `generate_entity_id`）与确定性 point id | point id 派生：`uuid5(KNOWLEDGE_NAMESPACE, f"point:{version_id}:{chunk_index}")` |
| pytest-django `django_capture_on_commit_callbacks` | pytest-django>=4.8（已装） | 测试 on_commit 注册/回滚边界 | 调度层测试 |

### Alternatives Considered

| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| `transaction.on_commit` + run_in_background | 新建摄取请求表 + apscheduler 轮询 | 表+轮询引入分钟级延迟与新基础设施；CONTEXT 已锁定 on_commit 方案，natural key 约束本身就是幂等键，无需请求表 |
| knowledge 内薄层 Qdrant 写操作（get_client 直用） | 给 QdrantService 加 `*_by_name` 的 set_payload/delete 包装 | QdrantService 的语义是"catch 后 return False 不重抛"（indexer 容错哲学），知识路径要求失败响亮——在 QdrantService 内混两种语义比在 knowledge 内自建薄层更危险；`collection.py` 已确立 get_client 直用先例 |
| markdown 标题分段 chunker（自建 ~80 行） | 复用 indexer/CodeParser | CodeParser 是 tree-sitter 代码切块，对 markdown 方案文本无意义；indexer 可复用的只有"批量 embed + 分 batch upsert"编排手法，不是 chunker 本身 |

**Installation:** 无 —— 本阶段零新依赖。

## Package Legitimacy Audit

本阶段不安装任何外部包（全部为仓库既有依赖与 stdlib）。**Packages removed: none. Packages flagged: none.** slopcheck 无需运行。

## Architecture Patterns

### System Architecture Diagram

```
触发点（4 处，只接线）                          knowledge app（本阶段新增）
─────────────────────────                      ──────────────────────────────────────────
chat:                                          ingestion.py
  CodingPlan.aget_or_create_… (created=True) ─┐    aschedule_ingestion(req)      ← async 入口（吞异常，永不阻塞主流程）
  CodingPlan.aupdate_plan ────────────────────┤      └ sync_to_async(transaction.on_commit)
  coding_session_service.create_sessions_…  ──┤            └ run_in_background(lambda: ingest(req))
mcp:                                          │
  technical_plan_service（acreate 后）─────────┤    ingest(req)                   ← background worker 内执行
  work_item_execution_service（成功尾部）──────┘      1. ensure_delivery_knowledge_collection()   [mismatch → raise，响亮 abort]
                                                     2. sources/ normalizer：按 ID 重读源模型 → IngestionEvent(s)
                                                     3. chunking.py 确定性切块 + 派生 point ids
                                                     4. EmbeddingService.generate_embeddings_batch + SparseEncoder（任一 None → raise）
                                                     5. _persist_sync()（单事务，sync_to_async）:
                                                          select_for_update(entity) → content_hash 短路判定
                                                          → 新版本行(is_latest=True, qdrant_point_ids 预写)
                                                          → 旧版本 is_latest=False + invalid_at + supersedes 链
                                                          → 边置位（graph_store 原语）+ 新边
                                                     6. commit 后向量序：upsert 新点(payload is_latest=true)
                                                          → tombstone 旧点(set_payload is_latest=false, wait=True)
                                                          → 物理删除旧点(按 point id 列表, wait=True)
                                                            [5 成功后 6 任一步失败 = 仅优化受损，检索由 is_latest filter 兜底]
                                                     ↓                    ↓
                                               Postgres/SQLite        Qdrant delivery_knowledge
                                               knowledge_* 三表        (hybrid dense+sparse, payload 8+6 字段)

manage.py reconcile_delivery_knowledge [--fix]  ← 对账：DB ↔ Qdrant 漂移检测/修复
manage.py rebuild_delivery_knowledge --yes      ← 扩展：删建后从 PG 全量重嵌入（TODO 锚点已留）
```

### Recommended Project Structure

```
server/knowledge/
├── ingestion.py                 # 摄取核心：DTO + aschedule_ingestion + ingest + _persist_sync
├── chunking.py                  # 确定性 chunk（markdown 标题分段 + 上限合并 + point id 派生）
├── vector_ops.py                # delivery_knowledge 写/tombstone/删点（wait=True，失败 raise）
├── sources/
│   ├── __init__.py
│   ├── coding_plan.py           # chat.CodingPlan → IngestionEvent
│   └── mcp_plan.py              # McpWorkItemTechnicalPlan(+McpWorkItemContext) → IngestionEvent(s)
└── management/commands/
    └── reconcile_delivery_knowledge.py

server/tests/knowledge/
├── test_ingestion.py            # 幂等/版本翻转/失败注入
├── test_chunking.py             # 确定性断言（同输入同输出同 point id）
├── test_triggers.py             # 4 触发点接线 + on_commit 边界
└── test_reconcile.py            # 对账命令
```

结构理由：领域 service 放 app 内是既定惯例（`mcp_tools/*_service.py`、`chat/coding_session_service.py` 先例）；`sources/` 隔离"各触发点 payload 形态差异"，ingestion 核心只认统一 DTO；`vector_ops.py` 单独成文件是为了让"知识路径的 Qdrant 写语义与 indexer 刻意相反（wait=True + raise）"有一个可被 grep 审计的收口。

### Pattern 1: 摄取 DTO 与函数签名（建议规格）

**What:** hook 只传"最小定位信息"，normalizer 在后台重读源模型构建完整事件——避免 hook 处组装大 payload（数据可能在 commit 前，且 hook 必须 3–5 行）。

```python
# knowledge/ingestion.py（建议签名，供 planner 直接引用）
from dataclasses import dataclass, field

@dataclass(frozen=True)
class IngestionRequest:
    """触发点传入的最小定位信息（hook 唯一构造的对象）。"""
    source_kind: str       # natural key 规则表字面值：coding_plan / mcp_technical_plan / feishu_work_item
    source_id: str         # 业务对象稳定 ID（CodingPlan UUID str / 飞书三元组拼接 …）
    trigger: str           # 结构化日志用："chat_plan_created" / "chat_coding_started" / "mcp_plan_created" / "mcp_tasks_executed"

@dataclass(frozen=True)
class EdgeSpec:
    relation: str                  # EdgeRelation 字面值
    target_entity_id: uuid.UUID    # 已派生的实体 id（generate_entity_id 产物）

@dataclass(frozen=True)
class IngestionEvent:
    """normalizer 产出的统一事件（ingest 核心唯一消费的形态）。"""
    kind: str                      # EntityKind 字面值
    origin: str                    # EntityOrigin 字面值
    source_kind: str
    source_id: str
    title: str
    content: str                   # 提炼后全文（embedding 输入；对话原文禁止出现在此）
    payload: dict                  # 结构化原文快照（落 KnowledgeEntityVersion.payload）
    project_id: str | None
    repository_id: str | None
    event_time: datetime           # aware（naive 进 GraphStore 会被拒）
    edges: tuple[EdgeSpec, ...] = ()

async def aschedule_ingestion(request: IngestionRequest) -> None:
    """触发点唯一入口：注册 on_commit → run_in_background。任何异常 log warning 不上抛。"""

async def ingest(request: IngestionRequest) -> None:
    """background worker 内执行的完整摄取（normalizer → embed → 落库 → 向量序）。失败 raise（由 background_task_failed 日志兜底）。"""
```

**When to use:** 所有 4 个触发点。Phase 14 新触发点只需新增 normalizer + 一行接线，核心不动。

### Pattern 2: 异步投递边界 —— async 上下文注册 on_commit（仓库无先例，必须写对）

**What:** 仓库现有 `transaction.on_commit` 用法全部在 sync signal handler 内（`code_relations/signals.py:92`）。本阶段 4 个触发点全是 async（async view / async @tool / async model classmethod），**不能**在 coroutine 里直接调 `transaction.on_commit`（它操作 per-thread connection 状态，必须在 ORM 所在的 sync 线程执行）。

```python
# 正确写法（aschedule_ingestion 内部）：
from asgiref.sync import sync_to_async
from django.db import transaction
from services.background_runner import run_in_background

async def aschedule_ingestion(request: IngestionRequest) -> None:
    def _register() -> None:
        # 在 sync_to_async 的 thread_sensitive 线程内注册——与 ORM 写共用同一 connection。
        # autocommit（async 视图无 atomic 包裹）下回调立即执行；atomic 块内则延迟到 commit；
        # rollback 时回调被丢弃（signals.py 同款边界语义）。
        transaction.on_commit(
            lambda: run_in_background(
                lambda: ingest(request),
                name=f"knowledge-ingest-{request.source_kind}-{request.source_id}",
            )
        )
    try:
        await sync_to_async(_register)()
    except Exception as exc:
        logger.warning("knowledge_ingest_schedule_failed", trigger=request.trigger, error=str(exc))
```

**关键事实（实证）：** `sync_to_async` 默认 `thread_sensitive=True`，所有 sync ORM 操作落在同一线程 → `transaction.on_commit` 看到的 connection 与触发点的 `asave()` 一致。Django 文档语义：无事务进行时 on_commit 回调**立即执行**——async 视图默认 autocommit，因此多数触发点上等价于"commit 后立即投递"，行为正确。`create_sessions_for_plan` 内有 per-repo `transaction.atomic`，hook 放在事务外的成功尾部即可。

**Why it matters:** 直接在 coroutine 调 `transaction.on_commit` 在某些执行路径下落在错误线程/connection 上，注册的回调可能永不触发或触发于错误时机——这是本阶段唯一一处"仓库无先例、必须新验证"的技术点（确认方式：触发点单测 + `django_capture_on_commit_callbacks`）。

### Pattern 3: 版本翻转事务序（INGEST-06 核心，P1/P2 合规序）

**正确次序（六步）与失败恢复矩阵：**

| # | 步骤 | 事务边界 | 失败后果 | 恢复方式 |
|---|------|---------|---------|---------|
| 0 | `ensure_delivery_knowledge_collection()` | 无 | mismatch raise → 整次摄取 abort（响亮） | 运维处理维度问题后重触发/reconcile |
| 1 | chunk + embed（dense batch + sparse batch） | 无（纯计算+远程 API） | 任一 None → raise，DB/Qdrant 零写入 | 重新触发即可（无副作用，天然可重试） |
| 2 | **单 DB 事务**（`_persist_sync`，sync_to_async 包装）：`select_for_update(entity)` → content_hash 对比 latest 版本（相同 → 整体 no-op return）→ 新版本行 `is_latest=True` + `supersedes=旧latest` + **确定性 point ids 预写 `qdrant_point_ids`** → 旧版本 `is_latest=False` + `invalid_at=now` → `entity.current_version+=1`、`event_time` 刷新 → 旧边置位 + 新边 `graph_store` 写入 | `transaction.atomic()` | 整体回滚，无半态 | 重新触发（幂等） |
| 3 | upsert 新版本 points（payload `is_latest=true`，8+6 字段齐全） | commit 后 | DB 已是新版但向量缺失 → 检索暂时召回不到新版（不召回旧版！旧点已在步 2 后注定被 tombstone/reconcile） | reconcile `--fix` 重嵌入；或重新触发（hash 相同短路，需 reconcile 兜底——见 Open Question 3） |
| 4 | tombstone 旧版本 points：`set_payload {"is_latest": false}`（按步 2 读出的旧 `qdrant_point_ids`，`wait=True`） | commit 后 | 旧点 payload 仍 is_latest=true → 检索可能命中旧版 ← **唯一影响正确性的失败**，必须 structlog error 响亮 | reconcile 检测"非 latest 版本的点 payload 仍 latest"并修复 |
| 5 | 物理删除旧 points（`client.delete(points_selector=PointIdsList, wait=True)`） | commit 后 | 旧点残留但 payload 已 false → 检索不受影响（纯优化层） | reconcile 清理 |

**为什么这个序是对的：**
- 步 2 一次事务完成全部 DB 状态翻转——`uniq_kversion_one_latest` 约束保证并发翻转撞约束即报错（模型 docstring 明言这是期望行为，串行化责任在摄取侧 `select_for_update`）。
- 步 3 在步 4 之前：Qdrant 短暂出现"新旧两版都 is_latest=true"窗口 → 检索可能同时命中两版（可接受的秒级窗口）；若反序（先 tombstone 再 upsert），窗口内一个版本都查不到。
- 物理删除按 **point id 列表**（从 DB 取），绝不按业务 filter 删（P1：避免 delete-by-filter 与并发 upsert 的 weak ordering 竞态，qdrant#6556）。确定性 point id 让"删旧"与"写新"天然不重叠（version_id 不同 → uuid5 不同）。
- 旧边置位**必须在步 2 事务内**与版本翻转同生死（P2 级联防线）。

**边置位的具体做法**（结合 Phase 12 原语）：`invalidate_entity_version(entity_id, invalid_at=now)` 会失效该实体 latest 版本 + **全部活跃出入边**——它是"实体作废"语义。重摄取场景更精细：版本翻转后**关系通常仍成立**（work_item HAS_PLAN plan 不因方案改了一版而失效）。推荐：重摄取 = 步 2 内手工翻转版本行（不调 invalidate_entity_version），边只在**关系目标变化**时置位旧边 + 建新边（如 MCP 重生成方案产生新 plan 实体时，旧 HAS_PLAN 边 `invalidate_edge` + 新 HAS_PLAN 边）；同实体同关系未变时复用既有活跃边（`uniq_kedge_active` 约束撞了说明边已存在，catch IntegrityError 或先查后写）。`invalidate_entity_version` 留给"源对象删除/作废"场景。

### Pattern 4: 触发点确切锚点与取材（行级，已实读验证）

> 注意：git 工作区当前有未提交改动（`server/chat/conversation_service.py`、`server/chat/views.py` 等），下列行号以当前工作区为准，planner 落任务时以函数名/语义锚点为主、行号为辅。

**chat（INGEST-03）— 两个挂点：**

| 触发语义 | 锚点 | 接线位置 | 取材 |
|---------|------|---------|------|
| 产出 CodingPlan | `server/chat/models.py::CodingPlan.aget_or_create_for_conversation`（L244；`created=True` 分支 L267–279 acreate 之后） | 模型方法收口——@tool `create_coding_plan`（`agents/tools/coding_tools.py:259`）、legacy 迁移命令等所有写路径必经 | entity：kind=`tech_plan`, source_kind=`coding_plan`, source_id=`str(plan.id)`, origin=`chat`；content=`title + "\n\n" + tech_plan`（方案 markdown 本身含提炼后需求描述，满足"对话原文不入图"）；payload 快照 `{title, affected_files, recommended_repository_ids}`；project 经 `conversation.project` 取（normalizer 内 select_related） |
| 修改 CodingPlan | `server/chat/models.py::CodingPlan.aupdate_plan`（L281；asave 之后） | 同上（@tool `update_coding_plan` 经 `coding_tools.py:413` 调它） | 同上 → content_hash 不同 → 自动走版本翻转（INGEST-06 chat 路径的天然验证场景） |
| 触发编码 | `server/chat/coding_session_service.py::create_sessions_for_plan`（L449，成功返回前） | fan-out endpoint `CodingPlanSessionsBatchCreateView`（chat/views.py:2377）唯一调它；另一候选 `CodingSessionConfirmView`（chat/views.py:1730）见 Open Question 4 | 重新投递同一 plan 的 IngestionRequest——hash 未变则 no-op（幂等性的实战验证点），变了则补摄取；保证"用户没产生过 plan 摄取事件但直接触发编码"时知识也入图 |

**MCP（INGEST-05）— 两个挂点：**

| 触发语义 | 锚点 | 接线位置 | 取材 |
|---------|------|---------|------|
| 产出技术方案 | `server/mcp_tools/technical_plan_service.py::build_work_item_technical_plan`（L368；`McpWorkItemTechnicalPlan.objects.acreate` 在 L491，接线放 acreate 之后、return 之前） | service 层而非 view（`CreateFeishuTechnicalPlanView` mcp_tools/views.py:836 只是壳） | ① tech_plan entity：source_kind=`mcp_technical_plan`, source_id=`str(artifact.id)`, origin=`mcp`；content=`artifact.markdown`（L373 字段，render_technical_plan_markdown 产物）；payload 摘要自 `plan_body`/`repository_tasks`。② work_item 锚实体：kind=`work_item`, source_kind=`feishu_work_item`, source_id=`f"{feishu_project_key}:{work_item_type}:{work_item_id}"`（natural key 规则表锁定格式；字段在 artifact L362–364 / context L290–292），title=`context.name`，content=`context.name + description`（轻量锚；Phase 14 INGEST-04 全量快照同 key 重摄取为新版本，天然衔接）。③ 边：work_item —HAS_PLAN→ tech_plan |
| 执行编码 | `server/mcp_tools/work_item_execution_service.py::execute_work_item_repo_tasks`（L531；output 组装完成后、return RepoTaskExecutionResult 之前，L583–598 区段） | service 层（`ExecuteWorkItemRepoTasksView` views.py:969 只是壳） | 重新投递 tech_plan + work_item 的 IngestionRequest（event_time 刷新；plan 可能经 `_ensure_coding_plan` 路径补建过）。**不建 code_change 实体**——编码产物摄取归 INGEST-02/Phase 14（Traceability 表锁定），diff 归档/TaskResult 回调挂点都在 Phase 14 |

**接线代码形态（每处 3–5 行，统一模板）：**

```python
# 触发点尾部（以 build_work_item_technical_plan 为例）
from knowledge.ingestion import IngestionRequest, aschedule_ingestion  # lazy import 防循环

await aschedule_ingestion(IngestionRequest(
    source_kind="mcp_technical_plan",
    source_id=str(artifact.id),
    trigger="mcp_plan_created",
))
```

normalizer（`sources/mcp_plan.py`）在后台按 source_id 重读 `McpWorkItemTechnicalPlan`（select_related context/project），同时产出 work_item 锚实体事件 + HAS_PLAN EdgeSpec——触发点对"产出几个实体几条边"完全无感知。

### Pattern 5: 确定性 chunk 策略（INGEST-08）

**裁决：不复用 indexer/CodeParser。** indexer 的切块是 tree-sitter 代码语法块（`services/code_parser.py`），对 markdown 方案/需求文本无意义。indexer 可借鉴的只有编排手法：批量 embed（`generate_embeddings_batch`，indexer.py:947）、sparse 经 `sync_to_async` 调 `encode_batch`（indexer.py:951、2537–2541）、upsert 分 batch ≤100（indexer.py:1375）。

**知识文本 chunker（`knowledge/chunking.py`，自建 ~80 行）：**

1. 按 markdown 二级/三级标题（`^##+ `）分段；无标题的纯文本按双换行分段。
2. 贪心合并相邻段到上限（建议 3000 字符，对 2560 维 doubao/bge-m3 类模型的 token 上限留足余量；常量集中可配）。超长单段硬切。
3. 产出 `KnowledgeChunk(index, text, chunk_kind)`：chunk 0 固定为 `chunk_kind="summary"`（title + 首段，整体召回面），其余 `chunk_kind="section"`。
4. **确定性保证**：纯函数，同 content 输入 → 同 chunk 列表 → 同 point ids。point id = `uuid.uuid5(KNOWLEDGE_NAMESPACE, f"point:{version_id}:{index}")`——同一版本重复 upsert 是覆盖而非新增（点级幂等）；不同版本 point id 必不同（version_id 是 uuid4 PK）。
5. 单元测试锁定确定性：同输入跑两遍字节级一致。

### Pattern 6: hybrid 写入实际 API 调用链（INGEST-08，已实证）

**Point 构造（与 indexer `_build_points` 同构，indexer.py:3167–3177 实证 named vectors 格式）：**

```python
# knowledge/vector_ops.py — point 形态
from qdrant_client.http.models import SparseVector

point = {
    "id": str(point_id),                       # uuid5 确定性 id
    "vector": {
        "dense": embedding,                    # list[float]，维度 = get_expected_dimension()
        "sparse": SparseVector(indices=sp["indices"], values=sp["values"]),
    },
    "payload": {
        # 8 个索引字段（KNOWLEDGE_PAYLOAD_INDEXED_FIELDS 键集合，单一事实源）
        "entity_kind": ..., "entity_id": ..., "version": ..., "is_latest": True,
        "project_id": ..., "repository_id": ..., "source_kind": ..., "event_time": iso8601,
        # 6 个必带非索引字段（KNOWLEDGE_PAYLOAD_REQUIRED_FIELDS）
        "source_id": ..., "chunk_kind": ..., "file_path": "",   # 知识文本无文件路径，空串（契约注明可空串）
        "text": chunk_text_truncated, "embedding_model": ..., "version_id": ...,
    },
}
```

**调用链（三个写操作的归属）：**

| 操作 | API | 语义要求 |
|------|-----|---------|
| upsert 新点 | `await sync_to_async(QdrantService.upsert_vectors_by_name)(DELIVERY_KNOWLEDGE_COLLECTION, points)`（qdrant_service.py:1014） | **返回 False 必须 raise**——该方法 catch 全部网络异常后 `return False`（L1051–1087），知识路径禁止沿用静默语义；分 batch ≤100 |
| tombstone 旧点 | `client = QdrantService.get_client()` + `sync_to_async(client.set_payload)(collection_name=…, payload={"is_latest": False}, points=old_point_ids, wait=True)` | 既有 `batch_set_payload`（L1318）**绑定 repository_id 推导 collection 名且超时不重抛**，不可直接用；knowledge 自建薄层（collection.py 的 get_client 先例），`wait=True` + 异常重抛 |
| 物理删除旧点 | `sync_to_async(client.delete)(collection_name=…, points_selector=models.PointIdsList(points=old_point_ids), wait=True)` | 按 id 列表删（P1），`wait=True`，失败 structlog error（优化层，可吞但必须响亮记录） |

payload 字段写入处必须 `from knowledge.collection import KNOWLEDGE_PAYLOAD_INDEXED_FIELDS, KNOWLEDGE_PAYLOAD_REQUIRED_FIELDS` 并以测试断言"写入 payload 键集合 ⊇ 两常量键集合"（schema 锁定回归测试与 12-03 同款）。

### Anti-Patterns to Avoid

- **各触发点各写摄取逻辑**：版本翻转是状态机，多份实现必然漂移（PITFALLS P3；locked decision）。
- **hook 内同步 embed / 写 Qdrant**：CurrentThreadExecutor 事故模式（background_runner.py docstring 记载）；hook 只传 ID。
- **沿用 indexer 的 return False 静默语义**：知识路径漏删/漏写是正确性错误不是噪音（P1）。
- **delete-by-filter 下线旧版本**：weak ordering 竞态会误删新点（qdrant#6556）；只按 point id 列表删。
- **直接调 `invalidate_entity_version` 做重摄取翻转**：该原语失效实体**全部**出入边，是"实体作废"语义；重摄取应精细置位（见 Pattern 3）。
- **绕过 graph_store 写边表**：grep 审计测试会抓（`WITH RECURSIVE` / `knowledge_knowledgeedge` 仅允许在 graph_store.py）。
- **naive datetime**：GraphStore 与模型层都会拒绝/漂移；一律 `timezone.now()` 或源字段确认 aware。

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| 实体 id 派生 | 散落 uuid5 拼接 | `generate_entity_id`（knowledge/models.py:80，唯一入口） | 拼接格式锁死，复刻即漂移 |
| 级联失效 | 手写多表 update | `graph_store.invalidate_entity_version` / `invalidate_edge`（置位原语，不覆盖已置位） | locked decision；幂等语义已实现并有测试 |
| 后台执行 | asyncio.create_task / 线程自管 | `run_in_background`（background_runner.py:98，传 factory 不传 coroutine） | executor/contextvars 问题已解 |
| collection 自检 | 摄取前手查维度 | `ensure_delivery_knowledge_collection`（mismatch raise 不删库） | P8 防线已实现 |
| dense/sparse 向量化 | 直连 embedding API | `EmbeddingService.generate_embeddings_batch` + `SparseEncoderService.encode_batch` | 系统配置驱动、批量、已调优 |
| Qdrant client 获取 | 自建 QdrantClient | `QdrantService.get_client()` | 代理禁用/timeout/keepalive 历史修复全在其中 |
| 幂等键 | 新建摄取请求去重表 | natural key 唯一约束 + `(entity, version)` 唯一 + content_hash 短路 + 确定性 point id | DB 约束即幂等键（CONTEXT "幂等键约束兜底"指的就是这组约束）；ProcessedEvent 模式留给 Phase 14 飞书 webhook（外部重推场景才需要事件表） |

**Key insight:** Phase 12 把所有"难做对"的原语都交付了；本阶段价值在编排次序与失败语义，不在新机制。

## Common Pitfalls

### Pitfall 1: async 上下文 on_commit 注册落错线程
**What goes wrong:** coroutine 里直接 `transaction.on_commit(...)` → 回调注册到非 ORM 线程的 connection 上，可能永不触发。
**Why it happens:** 仓库 on_commit 先例全在 sync signal handler；async 触发点是新场景。
**How to avoid:** `await sync_to_async(_register)()` 包裹注册（Pattern 2 模板）；触发点测试断言 run_in_background 被投递。
**Warning signs:** 测试里 ingest 永远不执行但无任何报错。

### Pitfall 2: content_hash 短路掩盖向量缺失
**What goes wrong:** 上次摄取在"DB 已 commit、向量未写入"间崩溃；重新触发时 hash 相同 → 短路 no-op → 向量永久缺失。
**Why it happens:** 短路判定只看 DB，不看 Qdrant。
**How to avoid:** reconcile 命令把"latest 版本的 qdrant_point_ids 是否全部存在且 payload 正确"列为第一检查项；可选增强：版本行加 `vector_synced` 布尔（步 3 成功后置 True），短路条件改为 `hash 相同 AND vector_synced`——推荐落这个字段，成本一列、消灭整类窗口。
**Warning signs:** DB 有 latest 版本但检索召回不到；reconcile 报 missing points。

### Pitfall 3: 并发重摄取同一实体撞 `uniq_kversion_one_latest`
**What goes wrong:** 两个 worker 同时翻转 → 一方 IntegrityError。
**Why it happens:** 模型 docstring 明言撞约束是期望行为，串行化责任在 Phase 13。
**How to avoid:** `_persist_sync` 开头 `KnowledgeEntity.objects.select_for_update().get(...)`（PG 真锁；SQLite 测试下整库写锁等效）；catch IntegrityError → log warning + 放弃本次（对方已写入更新内容，重触发会 hash 短路）。
**Warning signs:** 日志 IntegrityError 频繁出现（说明触发点重复投递异常密集）。

### Pitfall 4: 触发点异常回流主流程
**What goes wrong:** 接线代码抛异常 → 用户的创建方案/执行编码请求 500。
**How to avoid:** `aschedule_ingestion` 顶层 try/except 全吞 + structlog warning（`_update_agent_session_cross_repo_relevance` 同款"永不阻塞主流程"纪律）；触发点测试含"ingestion 模块抛错时主流程仍成功"用例。

### Pitfall 5: worker 线程 DB 写污染测试
**What goes wrong:** background worker 的写不在 pytest 事务里，不被 rollback。
**How to avoid:** 既有 autouse `_reset_background_runner`（tests/conftest.py:36–59）已兜底 wait+reset；摄取核心测试**直接 await `ingest(...)`**（绕过调度层），调度层单独用 monkeypatch run_in_background 测投递行为——不要在单测里真跑 worker 线程写库。

### Pitfall 6: 测试期 Qdrant/embedding 漏 mock 触发 socket 拦截
**What goes wrong:** `--disable-socket` 下任何真实网络调用直接报错。
**How to avoid:** 复用 `tests/knowledge/conftest.py` 的 `mock_qdrant_client` seam（monkeypatch `QdrantService.get_client`）；EmbeddingService 用 `monkeypatch.setattr(EmbeddingService, "generate_embeddings_batch", AsyncMock(return_value=[[0.1]*1024, ...]))`；SparseEncoderService.encode_batch 同步 monkeypatch。

## Code Examples

### `_persist_sync`（步 2 单事务骨架）

```python
# knowledge/ingestion.py（来源：本仓库模式拼装——select_for_update + 约束语义见 models.py docstring）
def _persist_sync(event: IngestionEvent, chunks: list[KnowledgeChunk], point_ids: list[str]) -> _PersistResult:
    with transaction.atomic():
        entity_id = generate_entity_id(event.kind, event.source_kind, event.source_id)
        entity, created = KnowledgeEntity.objects.select_for_update().get_or_create(
            id=entity_id,
            defaults=dict(kind=event.kind, origin=event.origin, source_kind=event.source_kind,
                          source_id=event.source_id, title=event.title[:500],
                          project_id=event.project_id, repository_id=event.repository_id,
                          event_time=event.event_time),
        )
        content_hash = hashlib.sha256(event.content.encode("utf-8")).hexdigest()
        latest = entity.versions.filter(is_latest=True).first()
        if latest is not None and latest.content_hash == content_hash and latest.vector_synced:
            return _PersistResult(skipped=True, ...)          # 幂等短路
        old_point_ids = list(latest.qdrant_point_ids) if latest else []
        if latest is not None:
            latest.is_latest = False
            latest.invalid_at = event.event_time
            latest.save(update_fields=["is_latest", "invalid_at"])
        new_version = KnowledgeEntityVersion.objects.create(
            entity=entity, version=(latest.version + 1 if latest else 1), supersedes=latest,
            content=event.content, content_hash=content_hash, payload=event.payload,
            qdrant_point_ids=point_ids, is_latest=True,
            event_time=event.event_time, valid_at=event.event_time,
        )
        entity.current_version = new_version.version
        entity.event_time = event.event_time
        entity.save(update_fields=["current_version", "event_time", "updated_at", "title"])
        # 边：目标变化才置位旧边 + 建新边（graph_store 原语，async → 经 async_to_sync 或在外层处理）
    return _PersistResult(new_version=new_version, old_point_ids=old_point_ids, ...)
```

（注：`graph_store` 方法是 async，DB 事务函数是 sync——planner 需决定边写入放事务函数内（用 ORM 等价操作不可行，必须走 graph_store）还是紧随其后的 async 步骤。推荐：边操作在 `ingest()` 内、`sync_to_async(_persist_sync)` 之后立即 `await graph_store.add_edge(...)` / `invalidate_edge(...)`——边非严格同事务，活跃边唯一约束+置位幂等保证可重入；若要求严格同事务，graph_store 写路径是 ORM `acreate`，可在 `_persist_sync` 里直接用 `KnowledgeEdge.objects.create/update`——**不行**，这绕过收口。结论：边随后异步写，失败可由 reconcile 兜底——列为 planner 显式决策点。）

### on_commit 测试（pytest-django）

```python
# 来源：pytest-django 官方 fixture django_capture_on_commit_callbacks（pytest-django>=4.4，本仓库 4.8+）
@pytest.mark.django_db(transaction=True)
async def test_schedule_registers_on_commit(monkeypatch, django_capture_on_commit_callbacks):
    submitted = []
    monkeypatch.setattr("knowledge.ingestion.run_in_background", lambda f, name=None: submitted.append(name))
    with django_capture_on_commit_callbacks(execute=True) as callbacks:
        await aschedule_ingestion(IngestionRequest("coding_plan", "abc", "chat_plan_created"))
    assert len(callbacks) == 1 and submitted  # 注册一次且 commit 后投递
```

（注意：async 测试 + 该 fixture 的组合需验证；备选等价方案——直接断言 monkeypatch 的 run_in_background 在 await 返回后已被调用（autocommit 下 on_commit 立即执行），rollback 边界用 sync 测试 + `transaction.atomic` 内 raise 验证不投递。）

### 幂等三连发测试（PITFALLS "Looks Done But Isn't" 第 3 条）

```python
@pytest.mark.django_db
async def test_ingest_idempotent(mock_qdrant_client, mock_embedding):
    req = IngestionRequest("coding_plan", str(plan.id), "chat_plan_created")
    for _ in range(3):
        await ingest(req)
    assert await KnowledgeEntity.objects.acount() == 1
    assert await KnowledgeEntityVersion.objects.acount() == 1
    assert mock_qdrant_client.upsert.call_count == 1   # 后两次 hash 短路
```

## 幂等设计（INGEST-07 细则）

四层幂等，全部依托既有约束，无新表：

| 层 | 机制 | 兜底约束 |
|----|------|---------|
| 实体 | `generate_entity_id` uuid5 PK + `get_or_create` | `uniq_kentity_natural_key` |
| 版本 | content_hash 与 latest 对比短路（+ 推荐 `vector_synced` 字段堵 Pitfall 2 窗口） | `uniq_kversion_entity_version` + `uniq_kversion_one_latest` |
| 点 | 确定性 point id（uuid5 of version_id+index）→ 重复 upsert 即覆盖 | Qdrant upsert 天然 by-id 幂等 |
| 边 | 活跃边先查后建（或 catch IntegrityError） | `uniq_kedge_active` 条件唯一 |

**version 推进规则：** 新 version = latest.version + 1；`supersedes` FK 指向被替代行（显式链，支持非线性历史）。content 完全相同（hash 相等）绝不产生新版本——重复投递、重试、migrate 命令历史回放都被此规则吸收。

**`vector_synced` 字段（推荐新增 migration）：** `KnowledgeEntityVersion` 加 `vector_synced = BooleanField(default=False)`，步 3 upsert 成功后置 True。短路条件 = hash 相同 AND vector_synced。这是本阶段唯一建议的模型变更（knowledge app 自有，migration 干净）。

## Reconcile 对账命令检查项（`reconcile_delivery_knowledge`）

形态沿 `verify_payload_consistency`（默认 dry-run，`--fix` 显式 opt-in，单点异常 skip 不崩整命令，输出表格+计数）：

| # | 检查项 | --fix 动作 |
|---|--------|-----------|
| 1 | 每个 latest 版本：`qdrant_point_ids` 全部存在于 Qdrant 且 payload `is_latest=true`、`version` 匹配 | 缺失/错误 → 重嵌入 upsert（调 ingest 核心的向量步骤） |
| 2 | 每个非 latest 版本：其 point ids 在 Qdrant 中要么不存在、要么 payload `is_latest=false` | 仍 true → tombstone + 物理删除 |
| 3 | Qdrant scroll `is_latest=true`：每个 entity_id 至多一个 version 命中 | 多版本 latest → 按 DB 真值修复 |
| 4 | 孤儿点（entity_id/version_id 不在 PG） | 物理删除 |
| 5 | DB 不变量抽检：单实体单 latest、`invalid_at > valid_at`、`vector_synced=False` 的 latest 版本数 | 报告（约束兜底，理论恒 0） |

另：扩展 `rebuild_delivery_knowledge --yes` 的 `_rebuild`——删建 collection 后从 `KnowledgeEntityVersion.objects.filter(is_latest=True)` 全量重嵌入（docstring TODO 锚点在 rebuild_delivery_knowledge.py:10）。

## Runtime State Inventory

非 rename/refactor phase——但有一项相关事实：**当前 delivery_knowledge collection 无数据**（Phase 12 仅交付生命周期管理），本阶段是第一个写入者，无存量数据迁移负担。其余类别（stored data / live config / OS state / secrets / build artifacts）：None — 全新增路径，verified by Phase 12 SUMMARY（"当前 collection 无数据，重建 = 删 + 建"）。

## State of the Art

| Old Approach（indexer 代码索引语义） | Current Approach（knowledge 知识语义） | When Changed | Impact |
|--------------|------------------|--------------|--------|
| upsert 失败 return False 继续 | 失败 raise / 响亮记录 | Phase 12 定调（collection.py "异常一律重抛"） | 漏删旧方案是正确性事故而非噪音 |
| collection 不匹配自动删建 | mismatch raise + 显式 `--yes` 重建 | Phase 12 | 知识库不可静默清空 |
| delete-by-filter | set_payload tombstone + 按 point id 删（wait=True） | 本阶段落地（PITFALLS P1） | 防 weak ordering 竞态 |

## Assumptions Log

| # | Claim | Section | Risk if Wrong |
|---|-------|---------|---------------|
| A1 | async 触发点经 `sync_to_async(transaction.on_commit 注册)` 后，autocommit 下回调立即执行、atomic 内延迟到 commit | Pattern 2 | 若 sync_to_async 线程亲和性与预期不符，投递可能不触发——Wave 0 触发点测试必须首先验证此行为（Django 官方文档语义 [CITED: docs.djangoproject.com/en/5.1/topics/db/transactions/#django.db.transaction.on_commit]，但 async 组合未在本仓库实证） |
| A2 | `django_capture_on_commit_callbacks` fixture 在 asyncio_mode=auto 的 async 测试中可用 | Code Examples | 不可用则退化为"monkeypatch run_in_background + autocommit 立即执行"断言，等价覆盖 |
| A3 | 3000 字符 chunk 上限对部署所用 embedding 模型（默认 bge-m3 / 可配 doubao 2560 维）token 限制安全 | Pattern 5 | 超限报 4xx——常量可配，摄取失败响亮可观测，调整成本低 |

## Open Questions

1. **[RESOLVED — 规划定案：按 Recommendation 采纳，`invalidate_edge` 置位 `invalid_at`（业务失效语义）；措辞映射已记入 13-02-PLAN.md"规划定案"节供 verify-work 对照]** **INGEST-06 措辞"旧边写 expired_at" vs Phase 12 置位原语写 invalid_at**
   - What we know：REQUIREMENTS/ROADMAP/CONTEXT domain 文案均写"旧边写 `expired_at`"；但 Phase 12 为重摄取交付的原语（`invalidate_edge` / `invalidate_entity_version`）写的是 `invalid_at`（业务时间线），`expired_at` 在模型 docstring 中定义为"系统时间线：记录作废（纠错用）"。GraphStore 默认遍历同时过滤两者，置位任一边都从默认结果消失——功能上等价。
   - What's unclear：verifier 是否按字面检查 expired_at。
   - Recommendation：按 bi-temporal 语义用 `invalidate_edge`（invalid_at）——版本替代是业务失效不是记录纠错；PLAN 中显式记录该措辞映射（"REQUIREMENTS 的 expired_at 按 Phase 12 已定型的 GraphStore 置位原语实现，语义为业务失效置位"），供 verify-work 对照。
2. **[RESOLVED — 规划定案：不排除（历史知识入图符合里程碑目标，幂等无害）；副作用记录责任落在 13-03-PLAN.md output 节（SUMMARY 必记）]** **migrate_coding_sessions_to_plans 命令会经模型方法触发摄取**
   - 模型层挂钩使历史迁移命令（chat/management/commands/migrate_coding_sessions_to_plans.py:146,214）也会触发摄取。幂等保证无害（历史 plan 入图甚至是福利），但 planner 应知情；如需排除，给模型方法加 `skip_ingestion=False` 参数由命令显式传 True。Recommendation：不排除（历史知识入图符合里程碑目标），在 SUMMARY 记录该副作用。
3. **[RESOLVED — 规划定案：content = title + tech_plan，不引入任何 conversation 消息；不为 chat 创建 work_item 实体。取材规格落在 13-03-PLAN.md Task 1，特征串断言测试钉死]** **chat "提炼后的需求文本"取材边界**
   - CodingPlan 无独立"需求文本"字段；tech_plan markdown 通常自含需求描述，title 是提炼标题。Recommendation：content = title + tech_plan，不引入任何 conversation 消息内容（守住"对话原文不入图"）；不为 chat 创建 work_item 实体（chat 自然语言需求无稳定 ID，PITFALLS P4 明确"裸新建不可接受"，归并策略是 Phase 14+ 课题）。
4. **[RESOLVED — 规划定案：挂 `create_sessions_for_plan` 成功尾部（result.created 非空时投递），confirm 不挂；接线规格落在 13-03-PLAN.md Task 2，含 chat/views.py 零接线的 grep 验收]** **chat "触发编码"挂点选 fan-out 还是 confirm**
   - `create_sessions_for_plan`（fan-out，session 批量创建）与 `CodingSessionConfirmView`（confirm + dispatch）都可代表"触发编码"。Recommendation：挂 `create_sessions_for_plan` 成功尾部（单一 service 函数、有 plan 上下文、被唯一 view 调用）；confirm 不挂（同一 plan 的重复投递只会 hash 短路，无增益）。

## Environment Availability

| Dependency | Required By | Available | Version | Fallback |
|------------|------------|-----------|---------|----------|
| Postgres/SQLite | 三模型 + 事务 | ✓（dev SQLite / prod PG，Phase 12 双后端已验证） | — | — |
| Qdrant | 向量写入 | 测试全 mock（`mock_qdrant_client` seam + `--disable-socket`）；运行时 compose 栈自带 | — | 测试不需要真实例 |
| Embedding API | 向量化 | 测试 mock（AsyncMock）；运行时系统配置 | — | 未配置时 `generate_embeddings_batch` 返回 None → 摄取响亮失败（正确行为） |
| uv + pytest | 测试 | ✓ | pytest>=9.0.2 | — |

**Missing dependencies with no fallback:** 无。

## Validation Architecture

### Test Framework
| Property | Value |
|----------|-------|
| Framework | pytest>=9.0.2 + pytest-django>=4.8 + pytest-asyncio（asyncio_mode=auto）+ pytest-socket（--disable-socket 默认开） |
| Config file | `server/pyproject.toml` `[tool.pytest.ini_options]` |
| Quick run command | `uv run pytest tests/knowledge/ -x`（working dir `server/`） |
| Full suite command | `uv run pytest tests/knowledge/ tests/test_coding_tools.py tests/mcp_tools/ -x` |

### Phase Requirements → Test Map
| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| INGEST-03 | CodingPlan 创建/更新/触发编码 → 投递摄取；对话原文不入 content | unit | `uv run pytest tests/knowledge/test_triggers.py -k chat -x` | ❌ Wave 0 |
| INGEST-05 | MCP 两工具成功路径 → 投递摄取（plan + work_item 锚 + HAS_PLAN 边） | unit | `uv run pytest tests/knowledge/test_triggers.py -k mcp -x` | ❌ Wave 0 |
| INGEST-06 | 重摄取 → 新版本 + 旧版 is_latest=False/invalid_at + 旧边置位 + tombstone/删点调用序；删除失败注入下 is_latest 翻转仍生效 | unit | `uv run pytest tests/knowledge/test_ingestion.py -k "version or flip or chaos" -x` | ❌ Wave 0 |
| INGEST-07 | 同事件 3 连发 → 单实体单版本；rollback 不投递；reconcile 检测并修复注入漂移 | unit + command | `uv run pytest tests/knowledge/test_ingestion.py -k idempotent -x && uv run pytest tests/knowledge/test_reconcile.py -x` | ❌ Wave 0 |
| INGEST-08 | chunk 确定性（同输入同 point id）；payload 键集合 ⊇ 8+6 常量；hybrid vector dict 含 dense+sparse | unit | `uv run pytest tests/knowledge/test_chunking.py tests/knowledge/test_ingestion.py -k payload -x` | ❌ Wave 0 |

### Sampling Rate
- **Per task commit:** `uv run pytest tests/knowledge/ -x`
- **Per wave merge:** `uv run pytest tests/knowledge/ tests/test_coding_tools.py tests/mcp_tools/ -x`（触发点宿主测试零回归）
- **Phase gate:** 全量 `uv run pytest tests/ -x` 绿 + `manage.py makemigrations --check --dry-run` 干净，再进 `/gsd-verify-work`

### Wave 0 Gaps
- [ ] `tests/knowledge/test_ingestion.py` — INGEST-06/07/08 核心
- [ ] `tests/knowledge/test_chunking.py` — INGEST-08 确定性
- [ ] `tests/knowledge/test_triggers.py` — INGEST-03/05 接线 + on_commit 边界（A1 假设最先验证）
- [ ] `tests/knowledge/test_reconcile.py` — INGEST-07 对账
- [ ] `tests/knowledge/conftest.py` 扩展：`mock_embedding`（AsyncMock dense + sync sparse）fixture（`mock_qdrant_client` 已有）
- 框架安装：无需（全部已就位）

## Security Domain

### Applicable ASVS Categories

| ASVS Category | Applies | Standard Control |
|---------------|---------|-----------------|
| V2 Authentication | no（无新入口；触发点宿主认证不变：chat OptionalJWT / MCP PAT） | — |
| V3 Session Management | no | — |
| V4 Access Control | yes（数据维度） | payload 必带 `project_id`/`repository_id`（Phase 12 schema 已锁，写入即合规）——这是 Phase 15 RETR-07 权限过滤的前提，缺写即 HIGH 回填成本 |
| V5 Input Validation | yes | normalizer 只读本系统 ORM 模型（非用户直接输入）；relation/kind 经 TextChoices + DB CheckConstraint 双保险；GraphStore relations 白名单已内置 |
| V6 Cryptography | no（不触凭证；EmbeddingService 内部已处理 api_key 解密） | — |

### Known Threat Patterns for 本阶段

| Pattern | STRIDE | Standard Mitigation |
|---------|--------|---------------------|
| 对话原文泄入知识库 | Information Disclosure | content 只来自 CodingPlan 字段/MCP artifact 字段，normalizer 单测断言不含 conversation 消息 |
| payload 缺权限字段 → 检索期 IDOR 温床 | Information Disclosure | 写入处 import schema 常量 + 键集合回归测试（P6 第一天做对） |
| 摄取失败静默 → 旧方案被检索（数据完整性） | Tampering | wait=True + raise/响亮 error + reconcile 对账 |
| raw SQL 绕过 GraphStore | Tampering | 既有 grep 审计测试自动守护新增代码 |

## Sources

### Primary (HIGH confidence — 全部实读)
- `server/knowledge/models.py`（natural key 规则表 L89–98、三约束语义）、`graph_store.py`（原语签名与幂等语义、`invalidate_entity_version` L449）、`collection.py`（schema 常量、ensure 语义）、`rebuild_delivery_knowledge.py`（TODO 锚点 L10）
- `.planning/phases/12-kmod/12-0{1,2,3}-SUMMARY.md`（Phase 12 决策与交付契约）
- `server/services/qdrant_service.py`（upsert_vectors_by_name L1014 return-False 语义、batch_set_payload L1318 repo 绑定、get_client L124）、`embedding.py`（generate_embeddings_batch L139 None 语义）、`sparse_encoder.py`（encode_batch L90）、`indexer.py`（hybrid vector dict L3167–3177、批量编排）、`background_runner.py`（run_in_background L98、factory 契约）
- `server/code_relations/signals.py`（on_commit + 去重调度 + rollback 边界范式）、`management/commands/verify_payload_consistency.py`（reconcile 命令形态）
- `server/chat/models.py`（CodingPlan L174、aget_or_create L244、aupdate_plan L281）、`agents/tools/coding_tools.py`（@tool L112/L349）、`chat/coding_session_service.py`（create_sessions_for_plan L449）、`chat/views.py`（ConfirmView L1730、BatchCreateView L2377）
- `server/mcp_tools/technical_plan_service.py`（build L368、acreate L491、markdown 字段）、`work_item_execution_service.py`（execute L531、成功尾部 L583–598）、`mcp_tools/views.py`（两 View L836/L969）、`mcp_tools/models.py`（McpWorkItemTechnicalPlan/Context 字段）
- `server/tests/conftest.py`（_reset_background_runner L36）、`server/pyproject.toml`（pytest 配置 L103–113）
- `.planning/research/PITFALLS.md`（P1/P2/P3/P4/P8/P9 防线）、`.planning/research/ARCHITECTURE.md`（Pattern 2/3、触发点清单）

### Secondary (MEDIUM)
- Django `transaction.on_commit` autocommit/atomic/rollback 语义 [CITED: docs.djangoproject.com/en/5.1/topics/db/transactions/]
- pytest-django `django_capture_on_commit_callbacks` fixture [CITED: pytest-django.readthedocs.io]
- qdrant/qdrant#6556（delete/upsert weak ordering 竞态，PITFALLS 已引证）

### Tertiary (LOW)
- A1（async + sync_to_async + on_commit 组合行为）：基于 Django 文档语义推导，本仓库无先例——Wave 0 首条测试验证。

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH — 零新依赖，全部既有件实读验证
- Architecture: HIGH — 触发点/原语/API 全部有文件:行号实证；唯一 MEDIUM 点是 A1（async on_commit 组合），已列 Wave 0 首验
- Pitfalls: HIGH — 直接继承 milestone PITFALLS 实证 + 本阶段代码级补充

**Research date:** 2026-06-11
**Valid until:** 2026-07-11（稳定内部代码库；注意 git 工作区有未提交改动，行号锚点以函数名为准）

## RESEARCH COMPLETE

Phase 13 为既有模式拼装（Phase 12 原语 + background_runner + EmbeddingService/Qdrant 既有链路），零新依赖；关键产出为六步版本翻转事务序、四层幂等设计、4 个触发点行级锚点与 async on_commit 注册写法（唯一需 Wave 0 首验的新组合），及 1 处措辞冲突（expired_at vs invalid_at）的处置建议。
