# Architecture Research

**Domain:** 代码智能图分析升级（对标 GitNexus）— brownfield 集成架构
**Researched:** 2026-08-09
**Confidence:** HIGH（所有集成点均直接读本仓代码核实；文中文件路径全部真实存在）

> 本文档回答「新能力如何与现有架构集成」：内存图服务分层与缓存语义、MCP/对话工具接线、
> detect_changes 的 diff 通路与编码任务链挂点、社区/执行流持久化建模、模块摘要注入点、
> Semgrep 执行位置、LSP 默认开启风险面，以及建议 build order。

## Standard Architecture

### System Overview

```
┌──────────────────────────────────────────────────────────────────────────┐
│  消费面（全部复用既有入口模式）                                              │
│  ┌───────────────┐ ┌───────────────┐ ┌────────────────┐ ┌──────────────┐ │
│  │ MCP 工具面     │ │ 对话工具       │ │ task 容器       │ │ process_     │ │
│  │ mcp_tools/    │ │ agents/tools/ │ │ knowledge_tools│ │ runtime 编排  │ │
│  │ (impact/trace │ │ (@tool 注册)   │ │ (HTTP 白名单)   │ │ (模块摘要注入)│ │
│  │ /detect/...)  │ │               │ │ 提交前自查      │ │              │ │
│  └───────┬───────┘ └───────┬───────┘ └───────┬────────┘ └──────┬───────┘ │
├──────────┴─────────────────┴─────────────────┴─────────────────┴─────────┤
│  新增分析层  server/services/code_graph/（NEW）                            │
│  ┌─────────────────────────────────────────────────────────────────────┐ │
│  │ GraphService（per-worker 内存 networkx 缓存，签名失效 + LRU 逐出）      │ │
│  │  ├─ impact.py（反向 BFS + 置信度分级 + 跨仓边）                        │ │
│  │  ├─ trace.py（最短路 + 文件/行号渲染）                                │ │
│  │  ├─ change_detect.py（diff 行区间 × Symbol 区间 → 批量 impact）        │ │
│  │  ├─ community.py（社区发现 → SymbolCommunity 落库）                   │ │
│  │  ├─ process_trace.py（Endpoint 正向追踪 → ProcessTrace 落库）          │ │
│  │  └─ rename_preview.py（图引用 + grep_mirror 兜底）                    │ │
│  │ semgrep_scan.py（独立，不依赖内存图；CLI + 镜像 worktree）              │ │
│  └───────────────┬─────────────────────────────────────────────────────┘ │
├──────────────────┴────────────────────────────────────────────────────────┤
│  既有数据层（零重建，只读 + 少量新表）                                       │
│  ┌───────────┐ ┌────────────┐ ┌──────────────┐ ┌─────────────────────┐   │
│  │ codegraph │ │ code_      │ │ repo_mirror  │ │ NEW: SymbolCommunity│   │
│  │ Symbol/   │ │ relations  │ │ (bare 镜像 + │ │ ProcessTrace        │   │
│  │ CallEdge/ │ │ ChunkEdge/ │ │  worktree +  │ │ SecurityFinding     │   │
│  │ Endpoint/ │ │ ChunkReg   │ │  git diff)   │ │ (独立新模型)         │   │
│  │ CrossRepo │ │            │ │              │ │                     │   │
│  └───────────┘ └────────────┘ └──────────────┘ └─────────────────────┘   │
└──────────────────────────────────────────────────────────────────────────┘
触发/失效：indexer.py 边构建完成钩子（code_relations/tasks.py 已有
GalaxyGraphCache.refresh_repo 调用点）→ 同点追加内存图失效 + 社区/执行流重算（durable QUEUE_GRAPH）
```

### Component Responsibilities

| Component | Responsibility | 实现方式 |
|-----------|----------------|------------------------|
| `services/code_graph/graph_service.py`（NEW） | per `(repository, branch)` 构建/缓存 networkx `DiGraph`，签名失效 + LRU 逐出 | 模块级单例 dict + `asyncio.Lock`，仿 `codegraph/galaxy/cache.py` 签名范式 |
| `services/code_graph/impact.py` / `trace.py`（NEW） | 纯图算法（反向 BFS / 最短路），不碰 ORM | 纯函数，输入 `DiGraph`，可独立单测 |
| `services/code_graph/change_detect.py`（NEW） | diff 行区间 × `Symbol` 行区间定位 → 批量 impact | 依赖 `repo_mirror` 拿 diff + `Symbol` ORM 区间查询 |
| `codegraph/models.py` 新增 `SymbolCommunity` / `ProcessTrace`（NEW model） | 社区与执行流持久化（软引用 Symbol，不加 FK） | 新 migration，`(repository, branch_name)` 隔离，对齐既有约定 |
| `mcp_tools/`（MODIFIED） | `impact_analysis` / `trace_call_path` / `detect_changes` / `preview_rename` 四个新工具 | 照 `McpToolView` 现有模式（serializer + view + url + snapshot 测试） |
| `agents/tools/`（MODIFIED） | 同名对话工具薄封装 | `@tool` 装饰器 + `schemas/` Pydantic + `__init__.py` import 注册 |
| `services/code_graph/semgrep_scan.py`（NEW） | Semgrep CLI 扫 MR diff（taint mode），结果落 `SecurityFinding` | server 容器内 subprocess，跑在 `repo_mirror` worktree 上，durable 队列执行 |
| `task/core/knowledge_tools.py`（MODIFIED） | 容器内提交前自查：`detect_changes` 加入 HTTP 工具白名单 | 复用既有 `/api/mcp/tools/<name>/` PAT 通路，零新机制 |

## Recommended Project Structure

新增代码集中在一个新包，避免散落：

```
server/services/code_graph/          # NEW 包 —— 图分析层
├── __init__.py                      # 导出 GraphService / impact / trace 等 curated API
├── graph_service.py                 # 内存图构建 + 缓存 + 失效 + LRU
├── loader.py                        # ORM 批量读取（values_list + iterator，sync 函数）
├── impact.py                        # 反向 BFS + 深度分组 + 置信度（纯函数）
├── trace.py                         # 两符号最短路（纯函数）
├── change_detect.py                 # diff → 受影响 Symbol → 批量 impact
├── community.py                     # 社区发现（networkx.algorithms.community）+ 落库
├── process_trace.py                 # Endpoint 正向执行流 + 落库
├── rename_preview.py                # 图引用 + grep_mirror 兜底改名清单
├── module_summary.py                # 社区 → LLM 模块摘要（call_source 新枚举值）
└── semgrep_scan.py                  # Semgrep CLI 封装 + SecurityFinding 写入

server/codegraph/models.py           # MODIFIED：追加 SymbolCommunity / ProcessTrace
server/codegraph/migrations/00XX_*.py# NEW：纯加表 migration，零改既有表
server/system/models.py（或 codegraph）# NEW：SecurityFinding（见 §6，建议放 codegraph app）
```

**Structure Rationale:**

- **`services/code_graph/` 单独成包**：既有 `services/retrieval/`（chunk 检索面）与 `codegraph/services/`（router/summary）各有职责；新图分析既非检索也非路由，独立包边界最清晰。`code_relations` 的 contract 明确「柔性引用、不做 FK」，新包只读它们的表，不反向依赖。
- **纯算法与 ORM 分离**：`impact.py`/`trace.py` 只吃 `DiGraph`，`loader.py` 独占 ORM——`sync_to_async` 边界收敛在 `graph_service.py` 一处（见 Pattern 1），单测不需要 DB。
- **Semgrep 与内存图无依赖**，放同包但可完全并行开发。

## Architectural Patterns

### Pattern 1: per-worker 内存图缓存（签名失效 + LRU）——问题 (1)

**What:** `GraphService` 维护模块级 `dict[(repo_id, branch), CachedGraph]`；`CachedGraph` 含 `networkx.DiGraph` + 构建时的失效签名。取图时先比签名，不一致即重建；超过 `MAX_CACHED_GRAPHS`（建议 8~16，settings 外置）按 LRU 逐出。

**失效信号（两级，取廉价者）：**
1. **首选水位**：`Repository.last_indexed_commit_sha`（base 分支）/ `RepositoryBranchIndex.last_indexed_commit_sha`（feature 分支）——一条主键查询，微秒级。但它只反映向量轨完成（`persist_vector_track_complete` 在 BUILDING_GRAPH **之前**就写了 sha，见 `server/services/indexer.py:120-131`），**图数据滞后于水位**，单靠它会缓存到半新不旧的图。
2. **必须叠加边构建代数**：在 `code_relations/tasks.py` 的边构建完成点（`server/code_relations/tasks.py:224-229`，现已在此调 `GalaxyGraphCache.refresh_repo`）同点追加 `GraphService.invalidate(repository_id)`——进程内直调即可让**本 worker** 失效；跨 worker 靠签名兜底：仿 `GalaxyGraphCache.compute_signature`（`server/codegraph/galaxy/cache.py:87-104`，每表 `COUNT + MAX(时间戳)`），对 `Symbol` / `CallEdge` / `ChunkEdge` / `CrossRepoApiCall` 四表算签名，7 条带索引聚合查询毫秒级，**每次取图都比一次**。

**ASGI 多 worker 语义：每 worker 独立缓存完全可接受。** 依据：
- 生产 ASGI 是 daphne/uvicorn 多进程，本就无共享内存；`GalaxyGraphCache` 用文件缓存解决跨进程共享，但 networkx 对象无法廉价序列化共享（pickle 10 万边 ≈ 数十 MB，得不偿失）。
- 图是只读分析用途，worker 间短暂不一致无害——签名比对保证每个 worker 最迟在下次请求时拿到新图。
- 内存账：10 万 `CallEdge` + 数万 `Symbol` 的 `DiGraph`，节点用 `str(symbol_id)`、属性精简（name/file/line/type），实测量级约 150~300MB/图；LRU 上限 × worker 数是总账，settings 给运维逃生舱（`CODE_GRAPH_CACHE_MAX` / `CODE_GRAPH_CACHE_ENABLED`）。
- **反例排除**：不要用 Redis/进程外图存储——引入序列化与网络成本，且本里程碑明确「networkx 已在依赖树（v3.6.1，`server/uv.lock:2371`）」是选型前提。

**ORM 批量读取模式（10 万级 CallEdge）：**

```python
# loader.py —— 全部 sync 函数，由 graph_service 用 sync_to_async(thread_sensitive=False) 包一层
def load_call_edges(repository_id: str, branch_name: str) -> list[tuple]:
    return list(
        CallEdge.objects
        .filter(repository_id=repository_id, branch_name=branch_name)
        .values_list(
            "caller_symbol_id", "caller_file", "callee_symbol_id",
            "callee_name", "callee_file", "call_type", "line_number",
        )
        .iterator(chunk_size=5000)
    )
```

- `values_list` 避免 model 实例化开销（10 万行差一个数量级）；`iterator(chunk_size=5000)` 控峰值内存（Django 5.1 在 psycopg3 上走服务端游标）。
- **`sync_to_async` 边界**：构建全程是一次长 sync 调用（读 4 张表 + 建图），放进 **一个** `sync_to_async` 包裹的函数，别逐查询穿梭 async/sync（每次穿梭有线程切换开销，也易踩 `CurrentThreadExecutor` 生命周期坑，见 `server/services/background_runner.py:16-30` 的教训记录）。构建期间用 per-key `asyncio.Lock` 防同 key 并发重建（`repo_mirror.py:86` 的 `_lock_for` 同款范式）。
- 构建慢（预估 10 万边 2~5s）**不要**在请求线程里同步等首次构建之外的重建：命中旧签名时可先返旧图 + 后台触发重建（stale-while-revalidate，best-effort），首次无图时同步构建并明示 `building` 状态。

**Trade-offs:** 每 worker 冗余内存与冗余构建（可接受，见上）；签名查询每次访问 +几 ms（对分析类工具无感）。

### Pattern 2: MCP + 对话工具双面接线——问题 (2)

**What:** 新工具一律「Python API 内核 + 两个薄壳」：内核在 `services/code_graph/`，MCP 壳照 `McpToolView` 模式，对话壳照 `@tool` 模式。`find_related` 就是现成样板（内核 `services/retrieval/find_related.py` → MCP `FindRelatedChunksView` → 对话 `agents/tools/find_related_code.py`）。

**MCP 侧需要动的文件清单**（照 `search_rag_chunks` 逐一对齐）：

| 文件 | 动作 |
|------|------|
| `server/mcp_tools/serializers.py` | NEW class：`ImpactAnalysisRequestSerializer` / `TraceCallPathRequestSerializer` / `DetectChangesRequestSerializer` / `PreviewRenameRequestSerializer` |
| `server/mcp_tools/views.py` | NEW class：四个 `McpToolView` 子类（`tool_name` 赋值；`_begin` → `_validate` → 调内核 → `_record` 带 `RetrievalTrace`；impact/trace 的结果按 `RetrievalTrace.Kind.EDGE` 写 trace，参照 `views.py:1143`） |
| `server/mcp_tools/urls.py` | 追加四条 `path("tools/<name>/", ...)` |
| `server/mcp_tools/`（schema snapshot 测试） | `TOOL_SCHEMA_SNAPSHOT` 补四条（v0.17 UNIFY 约定：schema 变更必须同步快照测试） |
| `mcp` npm 包（跨仓） | 已知欠债模式：服务端先齐，npm 客户端另批（v0.20 已有同款缺口在案） |

**对话侧需要动的文件清单：**

| 文件 | 动作 |
|------|------|
| `server/agents/tools/schemas/`（NEW 文件×4） | Pydantic Input/Output |
| `server/agents/tools/impact_analysis.py` 等（NEW 文件×4） | `@tool` 装饰 + 结构化 `ToolResult`（错误不冒泡，per `find_related_code.py` 契约） |
| `server/agents/tools/__init__.py` | 顶层 import 触发注册（注册机制见 `find_related_code.py:17-21` 文档） |

**观测约定（强制）**：每个 view/tool 记 `xxx_started/completed/failed` + `duration_ms`，`category="caller"`、`component="mcp_tools"` 或 `"agents"`；`McpToolView._record` 已内置 `ToolCallRecord` + `RequestMetric`（`views.py:271-286`），照抄即得。

**Trade-offs:** 四工具 × 两面 = 8 个薄壳文件，样板代码多；但与 40+ 既有工具完全同构，review 与测试成本最低。⛔ 反模式：绕过 `McpToolView` 自建入口（丢 PAT fail-closed、丢 trace、丢排除文件继承）。

### Pattern 3: detect_changes 的 diff 通路与编码任务链挂点——问题 (3)

**What:** diff 一律走 `repo_mirror`（server 侧自取），不依赖 MR webhook payload。

**通路核实**：`ensure_mirror_commit(repository_id, branch)`（`server/services/repo_mirror.py:217`）在 bare 镜像里 depth-1 fetch 目标 sha/分支头并返回 `MirrorSnapshot(commit_sha)`。detect_changes 需要 base 与 head 两个 commit：
1. `ensure_mirror_commit(repo_id)` 拿 base（pin 到 `last_indexed_commit_sha`，与索引态 Symbol 行号**同源对齐**——这是关键：Symbol 行区间是按 `last_indexed_commit_sha` 时刻抽的，diff base 必须取同一 sha，否则行号错位）；
2. `ensure_mirror_commit(repo_id, branch=feature_branch)` 拿 head；
3. 同一 bare 目录下 `git diff --unified=0 <base_sha> <head_sha>`（两个 depth-1 fetch 各自带全量 tree，diff 树对树可行；需在 `repo_mirror.py` 新增一个 `diff_mirror(snapshot_base, snapshot_head)` helper，约 40 行，复用 `_run_git`）。
4. 解析 hunk 行区间 × `Symbol.objects.filter(repository, branch_name, file_path, start_line__lte=..., end_line__gte=...)` 定位受影响符号 → 批量 impact。

**MR webhook payload 不做主通路**的理由：webhook 只覆盖「MR 已建」场景，而两个核心消费点（容器提交前自查、MR 描述生成）都发生在 MR 创建**之前**；且 payload diff 有截断风险。webhook 场景后续要用时同一内核换 diff 来源即可。

**编码任务链两个挂点（都是既有缝，零新机制）：**

1. **容器提交前自查**：task 容器已有 `/api/mcp/tools/<name>/` HTTP 工具面（`task/core/knowledge_tools.py:379-383`，PAT 鉴权 + 白名单）。把 `detect_changes` 加进 `knowledge_allowed_tools()` 白名单（`knowledge_tools.py:612`）+ system prompt 注入「提交前调 detect_changes 自查」指引（`task/core/executor.py` 的 `_get_system_prompt` 段，v0.9 `follow_openspec` 注入同款方式）。注意容器内 agent 被禁止 git 写操作（`executor.py:1028-1032`），真正 commit/push 在 `task/core/runner.py`（`:611-697`）——自查发生在 agent 编码完、runner commit 前，靠 prompt 驱动 agent 主动调用即可，不必改 runner 硬门禁（v1 不做阻断，只做提示，避免误报卡死编码链）。
2. **MR 描述生成**：两条链各一个挂点——workflow 链在 `server/workflows/nodes/ai/coding.py::_finalize_and_notify`（`:1300`，create_merge_request 前拼 description，`pr_cross_reference.py` 的「## 关联 PR」同款 fail-soft 追加「## 影响面」段）；MCP 链在 `server/mcp_tools/merge_request_service.py`（`summarize_branch` 起草 description，`:65-71` 与 `:143-147` 两处拼接点）。均 best-effort：impact 失败绝不阻断 MR 创建。

### Pattern 4: 社区/执行流持久化——问题 (4)

**What:** 一律新模型，不给 `Symbol` 加字段。

**否决「Symbol 加 community_id 字段」**：`GraphWriter` 增量索引按 `caller_file` 做 per-file 幂等删除重写（`codegraph/models.py:104-110` 的 CallEdge 契约文档），Symbol 行本身在文件重索引时会删建——挂在 Symbol 上的社区标注随重写丢失，且每次社区重算要 UPDATE 数万行 Symbol。新模型 + 软引用（存 `symbol_name`/`file_path`/`chunk_id`，不 FK——对齐 `Symbol.chunk_id` 的「柔性引用」先例，`models.py:41-45`）天然免疫重写。

```python
# codegraph/models.py 追加（示意）
class SymbolCommunity(models.Model):
    repository = models.ForeignKey("repositories.Repository", on_delete=models.CASCADE)
    branch_name = models.CharField(max_length=200, default="", blank=True)  # 对齐既有隔离维度
    community_key = models.CharField(max_length=64)        # 算法产出的稳定 key（成员指纹 hash）
    algorithm = models.CharField(max_length=32)            # "louvain" / "leiden" 等
    member_count = models.IntegerField()
    members = models.JSONField(default=list)               # [{name,file_path,symbol_type,chunk_id}]
    top_files = models.JSONField(default=list)
    summary = models.TextField(blank=True)                 # LLM 模块摘要（module_summary.py 回填）
    summary_model = models.CharField(max_length=100, blank=True)
    built_at_sha = models.CharField(max_length=64, default="")  # 水位：对齐 last_indexed_commit_sha
    created_at = models.DateTimeField(auto_now_add=True)
    class Meta:
        unique_together = [("repository", "branch_name", "community_key")]

class ProcessTrace(models.Model):
    repository = models.ForeignKey("repositories.Repository", on_delete=models.CASCADE)
    branch_name = models.CharField(max_length=200, default="", blank=True)
    entry_endpoint = models.JSONField()                    # {http_method,url_path,handler,file,line} 快照
    steps = models.JSONField(default=list)                 # 有序调用链 [{symbol,file,line,depth}]
    built_at_sha = models.CharField(max_length=64, default="")
    created_at = models.DateTimeField(auto_now_add=True)
```

**Migration 影响**：纯加表，零改既有表 → 零锁表风险、`makemigrations --check` 基线不受扰。Endpoint 也可能被重索引删建，故 `ProcessTrace.entry_endpoint` 存快照 JSON 而非 FK。

**增量索引刷新语义**：整仓重算、按 `(repository, branch)` 全删全建（社区检测本质是全图算法，无增量意义；10 万边 Louvain 秒级）。触发点 = 边构建完成钩子（与 Pattern 1 失效同点，`code_relations/tasks.py:224-229` 旁），但**不在钩子内联执行**——投 durable `QUEUE_GRAPH`（`server/durable/queues.py:13`、任务注册照 `server/durable/tasks.py:64` 的 `durable_graph` 模式），带 `initiated_by_user_id`（无用户则 `system`），`queueing_lock=f"community:{repo_id}:{branch}"` 天然去重防抖。`built_at_sha` 落水位，消费方可判 stale。

### Pattern 5: 模块摘要注入 RepoRouterV2 与 process_runtime——问题 (5)

**What:** ⛔ `codegraph/services/repo_router_v2.py` 是 §13.2 冻结面（`blueprint_route.py:7-11` 与 `charter_route_signal.py:10-11` 两处重申「零改动、只调不改，证据不进 Stage1 prompt」）。模块摘要**只在 adapter 层注入**，三个注入点：

1. **蓝图路由链**：`server/services/process_runtime/blueprint_route.py` 的三分量融合处（`build_score_breakdown`，`:143`）。模块摘要不建议做第四分量（会破坏「三分量之和恒等于总分」的既有恒等式契约与前端展示），而是做 **evidence 增强**：candidate 的 `evidence` dict（`_EVIDENCE_KEYS`，`:56-70`）加 `module_summaries` 键，把命中仓的 top 社区摘要带给确认门与调研 prompt。若确需参与打分，按 `charter_match` 的先例把摘要相似度并进 `charter_match` 或经 `SettingKeys.BLUEPRINT_ROUTE_WEIGHTS` 扩权重向量——那是显式的权重 schema 变更，须单独评审。
2. **对话/MCP 路由链**：照抄 `server/services/charter_route_signal.py` 的完整范式（纯函数打分 + `aapply_charter_signal` 融合 + best-effort 降级）——新建 `services/module_summary_signal.py` 或直接扩展 charter signal 的 evidence；接线点在 `server/agents/tools/repository_relevance.py::_apply_charter_signal`（`:153`）旁与 `mcp_tools/views.py::RouteRepositoriesView`。
3. **技术方案生成（调研 prompt）**：`server/services/process_runtime/blueprint_research_adapter.py` / `artifact_injection.py` —— 逐仓调研容器的 prompt 组装处注入该仓 top-N 社区摘要（「这个仓由哪些模块组成」是调研 agent 最缺的先验）。v0.8 `render_upstream_artifacts_section` 的「空段守卫 + fail-soft」模式照抄。

另外 `RepoSummaryBuilder.build`（`codegraph/services/repo_summary_builder.py:35`，索引 FINALIZING 期跑）的 `description` 现在只用 `Repository.ai_summary` 兜底——社区摘要就绪后可把 top 社区名并进 repo summary 向量文本，路由召回免费受益。

**LLM 调用约定**：`module_summary.py` 的 LLM 调用赋新 `call_source` 枚举值（LOGGING-SPEC §4.1 加一条，如 `module_summary`），上报 token/TTFT/错误码。

### Pattern 6: Semgrep 执行位置与落库——问题 (6)

**What:** **server 容器内跑 CLI，durable 任务执行，扫 `repo_mirror` worktree**。

- **执行位置选型**：`repo_mirror` 已具备把 bare 镜像物化成 worktree 的能力（`repo_mirror.py:335-366` `_worktree_root`/`_ensure_worktree`，grep 链在用）——Semgrep 需要真实文件树，这个缝现成。经 runner 分发独立容器的方案否决（v1）：要新增镜像、走 WS dispatch/callback 协议、改 `runner/`+`task/` 两个组件，为一个 CLI 扫描不成比例；「买不是造」的精神是最小集成。**代价**：semgrep 是重依赖（pyproject 加 `semgrep>=1.x` 或 server 镜像 Dockerfile 装二进制，建议后者——pip 依赖树污染更小），扫描吃 CPU，必须限并发。
- **执行形态**：durable 任务（建议复用 `QUEUE_MAINTENANCE` 或新增 `QUEUE_SCAN`，注册照 `durable/tasks.py` 模式），`ConcurrencyWindow` 限 1~2 并发；MR 门禁场景由 `_finalize_and_notify` / MR webhook 触发 defer，结果异步回填。taint mode 扫 diff 涉及的文件集（`--include` 收窄），不全仓扫。
- **落库**：新建 `SecurityFinding` 模型（放 `codegraph` app 或新 `scanning` app）。既有模型无一适配：`AuditEvent` 是操作审计（append-only 语义不符）、`McpRepositoryAnalysis` 是 LLM 仓库分析产物、`RetrievalTrace` 是召回留痕。字段：repository/branch/mr_url/rule_id/severity/file_path/line/message/fingerprint（去重键）/status（open/resolved/dismissed）/scan_sha。**脱敏**：Semgrep 输出含代码片段，入库前过 `redact_secrets_in_text`（规范强制）。
- **呈现**：MR 描述追加「## 安全扫描」段（挂点同 Pattern 3 的两处）；REST 查询面后续按需（v1 可只有 MCP `get_security_findings` 读工具）。

### Pattern 7: LSP 默认开启的风险面——问题 (7)

现状：`VOLAR_BACKEND_ENABLED` / `GOPLS_BACKEND_ENABLED` 默认双 False（`settings.py:968/977`），Phase 66 主动关闭，注释写明关闭原因是「图谱构建慢与 LSP 冷启动等待」。`EXTRACTOR_BACKENDS`（`settings.py:840-850`）是声明性目标表，kill-switch 才是实际开关（`codegraph/apps.py:129-137`）。

| 风险 | 证据 | 缓解 |
|------|------|------|
| 索引耗时显著上升 | `settings.py:903-904` 注释：大插件链场景 volar 启动 60-90s；gopls 冷启动慢是 go 回落 tree_sitter 的显式理由（`:838`） | 默认开启前先跑基准（大仓索引全程耗时对比）；`LSP_STARTUP_TIMEOUT_SECONDS` 运维文档化；失败 fallback 链已在（`LspUnhealthyError → TreeSitterBackend`，`test_registry_integration.py` 已锁） |
| 容器内依赖 | `vue-language-server` 需 node + tsdk 发现（`node_check.discover_tsdk()` 动态注入，`settings.py:901-902`）；gopls 需 go 工具链——server 镜像需确认已含这些二进制，否则开了也起不来 | Dockerfile 审计 + 启动健康探测日志；缺依赖时 kill-switch 语义保证静默回落 tree-sitter（行为已测试锁定） |
| 回归面 | `test_go_extractor.py:163-171` 记录了 gopls/tree-sitter 抽取结果**不同**（gin 路由 endpoint gopls 路径不抽）——切换会改变 Endpoint/Symbol 产出，影响执行流与路由 | 切换作为独立 Phase，先在少数仓灰度（kill-switch 是全局的，可考虑加 per-repo facet 覆盖，工作量小）；golden 对比抽取产物 |

**建议**：本里程碑做「降低开启门槛」而非无条件默认开——补依赖健康探测 + 文档 + 基准数据，默认值翻转留给基准结果说话。

## Data Flow

### 主流程 1：impact 查询（MCP 链）

```
LLM 调 impact_analysis(symbol, repo, branch)
    ↓
McpToolView(_begin: PAT fail-closed) → serializer 校验
    ↓
GraphService.get_graph(repo, branch)
    ├─ 签名一致 → 命中内存 DiGraph（毫秒）
    └─ 失效/未建 → sync_to_async 一次性批量读 4 表 → 建图 → 缓存
    ↓
impact.py 反向 BFS（深度分组；解析边=high / 裸名边=medium / CrossRepoApiCall 按 match_confidence）
    ↓
_record（ToolCallRecord + RetrievalTrace.Kind.EDGE + RequestMetric）→ Response
```

### 主流程 2：detect_changes 进编码链

```
task 容器 agent 编码完成
    ↓ (system prompt 指引)
容器经 /api/mcp/tools/detect_changes/（PAT）
    ↓
server: ensure_mirror_commit ×2（base=last_indexed_commit_sha, head=feature 分支）
    → git diff base..head → hunk 行区间 × Symbol 区间 → 受影响符号 → 批量 impact
    ↓
agent 依结果自查/修补 → runner commit+push → server 回调
    ↓
_finalize_and_notify: MR description 追加「## 影响面」（fail-soft）→ create_merge_request
（Semgrep durable 任务同点触发，异步回填 SecurityFinding）
```

### 主流程 3：索引后台刷新链

```
indexer 边构建完成（code_relations/tasks.py 钩子点，现有 GalaxyGraphCache.refresh_repo 旁）
    ↓ best-effort，绝不反噬索引
GraphService.invalidate(repo)（本 worker 直接失效；他 worker 靠签名）
    ↓
DurableTaskService.defer(QUEUE_GRAPH, community_rebuild, queueing_lock 去重)
    → 社区检测 → SymbolCommunity 全删全建 → module_summary.py LLM 摘要回填
    → process_trace 重算（Endpoint 入口 × 正向追踪）
    → RepoSummaryBuilder 增益（可选）
```

## Scaling Considerations

| Scale | 架构调整 |
|-------|--------------------------|
| 单仓 ≤1 万边 | 全部默认值即可，图构建 <1s，社区检测内联都行（仍建议走队列保一致性） |
| 单仓 10 万边（设计目标） | `values_list+iterator` 批读；LRU=8~16；社区/执行流必须走 `QUEUE_GRAPH`；impact BFS 加 `max_nodes` 硬上限（防全图返回） |
| 260 仓全热 / 单仓 50 万边+ | 内存账爆 worker：需按需降级——大仓改「不缓存、每次 SQL 递归 CTE」或图裁剪（只入解析边）；这是 v2 问题，接口留 `settings` 阈值即可 |

**First bottleneck:** 首次建图的冷启动延迟（秒级）——stale-while-revalidate + 索引后预热（可选仿 `warm_stale`）。
**Second bottleneck:** worker 内存（LRU 上限 × 图大小 × worker 数）——`CODE_GRAPH_CACHE_MAX` 外置 + gauge 上报缓存占用。

## Anti-Patterns

### Anti-Pattern 1: 动 `repo_router_v2.py` 或把新证据塞进其 Stage1 prompt

**What people do:** 为模块摘要参与路由直接改 router 内核。
**Why it's wrong:** §13.2 冻结面，两个既有模块（`blueprint_route.py`、`charter_route_signal.py`）文档均显式承诺零改动；破坏会撕裂 v0.19/v0.20 的回放与 golden set 契约。
**Do this instead:** adapter 层融合（Pattern 5 三注入点）。

### Anti-Pattern 2: 观测/刷新钩子反噬主流程

**What people do:** 在索引钩子里内联跑社区检测/Semgrep，失败抛回 indexer。
**Why it's wrong:** 违反「图谱失败不阻塞向量轨 INDEXED」既有不变量（`indexer.py:1414` 注释）与观测规范「best-effort 绝不反噬」。
**Do this instead:** 钩子内只 defer durable 任务 + try/except 吞异常记 warning（`_run_sdd_detect` 范式，`indexer.py:3685-3706`）。

### Anti-Pattern 3: 给 Symbol/CallEdge 加社区字段或新 FK

**What people do:** `Symbol.community_id` 或 `SymbolCommunity` M2M 到 Symbol。
**Why it's wrong:** 增量索引 per-file 删建 Symbol，标注随行丢失；FK 级联使社区表被索引重写牵连。
**Do this instead:** 独立模型 + JSON 软引用 + `built_at_sha` 水位（Pattern 4）。

### Anti-Pattern 4: 逐边 async ORM 读取建图

**What people do:** `async for edge in CallEdge.objects.filter(...)` 逐行搬进图。
**Why it's wrong:** 10 万次 async/sync 穿梭，分钟级；且散落的 ORM 调用让 `sync_to_async` 边界不可审计。
**Do this instead:** 单次 `sync_to_async` 包裹的批量 `values_list+iterator`（Pattern 1）。

## Integration Points

### 新增 vs 修改 清单（汇总）

| 类型 | 路径 | 说明 |
|------|------|------|
| NEW | `server/services/code_graph/`（约 10 文件） | 图分析层全部内核 |
| NEW | `server/codegraph/migrations/00XX`（加表） | `SymbolCommunity` / `ProcessTrace` / `SecurityFinding` |
| NEW | `server/agents/tools/{impact_analysis,trace_call_path,detect_changes,preview_rename}.py` + `schemas/` ×4 | 对话工具壳 |
| MODIFIED | `server/codegraph/models.py` | 追加 3 模型（零改既有表） |
| MODIFIED | `server/mcp_tools/serializers.py` / `views.py` / `urls.py` + schema snapshot 测试 | MCP 工具壳 ×4（+可选 `get_security_findings`） |
| MODIFIED | `server/agents/tools/__init__.py` | import 注册 |
| MODIFIED | `server/services/repo_mirror.py` | 新增 `diff_mirror` helper（~40 行） |
| MODIFIED | `server/code_relations/tasks.py` | 边构建完成钩子旁追加失效 + durable defer（best-effort） |
| MODIFIED | `server/durable/queues.py` / `tasks.py` | 社区重算 / Semgrep 任务注册 |
| MODIFIED | `server/services/process_runtime/blueprint_route.py` + `blueprint_research_adapter.py`（或 `artifact_injection.py`） | 模块摘要 evidence 注入 |
| MODIFIED | `server/agents/tools/repository_relevance.py` / `mcp_tools/views.py::RouteRepositoriesView` | 对话/MCP 路由链摘要信号 |
| MODIFIED | `server/workflows/nodes/ai/coding.py::_finalize_and_notify` + `server/mcp_tools/merge_request_service.py` | MR 描述追加影响面/扫描段（fail-soft） |
| MODIFIED | `task/core/knowledge_tools.py`（白名单）+ `task/core/executor.py`（prompt 段） | 容器提交前自查 |
| MODIFIED | `server/friday/settings.py` | `CODE_GRAPH_CACHE_*` / Semgrep 路径与并发 / LSP 基准相关 |
| MODIFIED | `server/Dockerfile` | semgrep 二进制（+若翻 LSP 默认：node/vue-language-server/gopls 依赖审计） |

### Internal Boundaries

| Boundary | Communication | Notes |
|----------|---------------|-------|
| `code_graph` ↔ `codegraph`/`code_relations` 模型 | 只读 ORM（loader.py 独占） | 软引用不 FK；branch_name 隔离必须透传（unique 约束 Pitfall 4 在案） |
| `code_graph` ↔ `repo_mirror` | 直接函数调用 | diff/worktree 均复用；镜像 per-repo `asyncio.Lock` 已防并发 |
| MCP/对话壳 ↔ `code_graph` 内核 | async Python API | 壳零业务逻辑；错误结构化返回不冒泡 |
| 索引钩子 ↔ 社区/摘要重算 | durable `QUEUE_GRAPH` defer | `queueing_lock` 去重；`initiated_by_user_id`/`system` 必带 |
| task 容器 ↔ detect_changes | HTTP `/api/mcp/tools/` + PAT | 排除文件 fail-closed 天然继承；白名单加一条即可 |

## 建议 Build Order

```
Wave 0（三线并行，互不依赖）
├─ A. GraphService + loader + 失效/LRU + impact/trace 纯函数（地基，最长线先动）
├─ B. semgrep_scan + SecurityFinding + durable 任务（完全独立）
└─ C. LSP 依赖审计 + 索引耗时基准（调研型，产出开关决策数据）

Wave 1（依赖 A）
├─ D. impact/trace 的 MCP + 对话双面接线（8 壳文件 + snapshot 测试）
├─ E. detect_changes（diff_mirror helper + 内核 + 双面接线）
└─ F. rename_preview（图引用 + grep_mirror 兜底，双面接线）

Wave 2（依赖 A；E 完成后 G2 可并行）
├─ G1. 社区检测 + SymbolCommunity + 索引钩子 defer 链
├─ G2. detect_changes 接编码链（容器白名单 + prompt 段 + 两处 MR 描述挂点）
└─ H. 执行流 ProcessTrace（依赖 A + Endpoint，与 G1 并行）

Wave 3（依赖 G1）
├─ I. module_summary LLM 摘要 + call_source 枚举
└─ J. 摘要注入三点（blueprint_route evidence / 对话信号 / 调研 prompt）
   （B 的 Semgrep 门禁挂 MR 描述可在 G2 同批收口）
```

排序理由：A 是五个功能的共同依赖，必须最先；B/C 无依赖抢跑；detect_changes 的「工具本体」（E）与「链路集成」（G2）拆开——前者只依赖 A，后者要动 task/workflow 两条链，风险面不同；模块摘要（I/J）依赖社区结果，天然最后。

## Sources

全部为本仓一手代码核实（2026-08-09，工作区含 charter UI 在途改动不影响本文结论）：

- `server/codegraph/models.py`（Symbol/CallEdge 契约、branch_name 隔离、软引用先例）
- `server/codegraph/galaxy/cache.py`（签名失效 + refresh_repo + warm_stale 缓存范式）
- `server/code_relations/tasks.py:224-229`（边构建完成钩子 = 失效/重算挂点）
- `server/services/indexer.py:120-131, 1413-1421, 3685-3706`（水位时序、FINALIZING 钩子、best-effort 范式）
- `server/services/repo_mirror.py:217-366`（ensure_mirror_commit、worktree、per-repo 锁）
- `server/mcp_tools/{views.py,urls.py}`（McpToolView 模式、RetrievalTrace/ToolCallRecord）
- `server/agents/tools/{find_related_code.py,registry.py,repository_relevance.py}`（@tool 注册与 charter 信号融合范式）
- `server/services/charter_route_signal.py`、`server/services/process_runtime/blueprint_route.py`（§13.2 冻结面 + adapter 层融合先例）
- `server/durable/{queues.py,tasks.py}`（QUEUE_GRAPH、queueing_lock 模式）
- `task/core/{knowledge_tools.py,executor.py,runner.py}`（容器 HTTP 工具面、git 写禁令、commit/push 时序）
- `server/workflows/nodes/ai/coding.py`、`server/mcp_tools/merge_request_service.py`（MR 创建与描述拼接点）
- `server/friday/settings.py:825-977`、`server/codegraph/apps.py:129-140`（LSP kill-switch 与风险注释）
- `server/uv.lock:2371`（networkx 3.6.1 在依赖树）

---
*Architecture research for: Friday AI v0.22.0 代码智能图分析升级*
*Researched: 2026-08-09*
