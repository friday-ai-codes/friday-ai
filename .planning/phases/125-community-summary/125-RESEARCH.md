# Phase 125: 社区检测 + 模块摘要 - Research

**Researched:** 2026-08-10
**Domain:** 内存符号图社区检测（networkx Louvain）+ LLM 模块摘要 + RepoRouter adapter 注入
**Confidence:** HIGH

## Summary

Phase 125 在 Phase 121 的 `(repository, branch)` 内存 `MultiDiGraph` 上跑 Louvain 社区检测，把结果以独立模型 `SymbolCommunity`（软引用成员、不加在 `Symbol` 上）落库；用成员指纹 + Jaccard≥0.8 对账跳过未变社区的 LLM 摘要；再把摘要以 **adapter / 调用方之后** 的形式注入蓝图路由 evidence、对话·MCP 路由信号、调研 prompt 三点——全程 ⛔ 零改动 `repo_router_v2.py` 与 `mcp/` submodule。

本仓已具备全部机械依赖：`networkx==3.6.1`（含 `louvain_communities(seed=...)`）、`get_graph_service` barrel、`charter_route_signal` / `blueprint_route._EVIDENCE_KEYS` / `artifact_injection` 注入范式、`QUEUE_GRAPH` + `queueing_lock` + `initiated_by_user_id` durable 链路、`CallSource` + LOGGING-SPEC §4.1 双登记守护测。**零新增 Python 依赖。** 规划时最大风险不是算法选型（Louvain vs Leiden 已在 CONTEXT/research 锁定），而是：(1) 钩子只 enqueue 不内联；(2) `call_source=module_summary` 先登记再写调用点；(3) 冻结面提交纪律；(4) 「无变更重建两次 → LLM=0」必须有自动化验收钉死。

**Primary recommendation:** 按 CONTEXT D-01…D-16 落地——`SymbolCommunity` migration → `community.py`/`module_summary.py` → 新 durable 任务名挂 `QUEUE_GRAPH` → 双钩子 enqueue → 三点 adapter 注入；Wave 0 先登记 `call_source` 与测试骨架。

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions

#### Area 1: 社区模型 / 软引用 / 刷新触发（MOD-01）

- **D-01 — 独立模型 `SymbolCommunity`，纯加表、零改既有表**。落点 `server/codegraph/models.py`（research ARCHITECTURE Pattern 4）；migration 只 ADD TABLE。字段最小集：`repository` FK、`branch_name`（`""`=基线，对齐 Symbol/图隔离）、`community_key`（稳定 key，见 D-02）、`algorithm`（`"louvain"` / 预留 `"leiden"`）、`member_count`、`members` JSON、`top_files` JSON、`member_fingerprint`、`summary` / `summary_model` / `summary_generated_at`（可空）、`built_at_sha`（对齐 `last_indexed_commit_sha` 水位）、时间戳。`unique_together = (repository, branch_name, community_key)`。
- **D-02 — 软引用成员，⛔ 不加 FK、⛔ 不挂 `Symbol.community_id`**。`members` 存快照列表，每项至少 `{symbol_id, name, file_path, symbol_type, chunk_id?}`——`symbol_id` 为 UUID **字符串软引用**（对齐 `Symbol.chunk_id` 柔性引用先例），不建 FK/CASCADE。理由：增量索引 per-file 删建 Symbol 会丢挂在 Symbol 上的标注；社区重算也不应 UPDATE 数万行 Symbol。孤儿 soft-id 在消费时忽略即可。
- **D-03 — 全仓全删全建刷新，投 durable `QUEUE_GRAPH`，不在索引钩子内联跑**。社区检测是全图算法，无增量意义。触发点 = 边构建完成钩子旁（与 Phase 121 图失效同点，`code_relations` lifecycle / graph build completed），`defer` 入队；`queueing_lock=f"community:{repo_id}:{branch}"` 去重防抖；`initiated_by_user_id` 透传（无则 `system`）。任务内：`get_graph`（经 barrel，⛔ 不直连 loader/cache）→ Louvain → 指纹对账 → 摘要回填 → 按 `(repository, branch_name)` 替换该仓社区行。`built_at_sha` 落水位，消费方可判 stale。
- **D-04 — 算法 = networkx `louvain_communities`，固定 seed + 节点排序；Leiden 否决默认引入**。裁决依据 research/SUMMARY「Louvain vs Leiden」：GPL-3.0 `leidenalg` 对 MIT + ghcr 预构建镜像是硬约束；漂移用工程护栏缓解。实现：构图/跑算法前对节点 ID **稳定排序**后喂入；`seed` 固定为模块级常量（写入测试）。预处理：只对规模 ≥ **5** 符号的弱连通分量跑算法；孤立/过小分量归目录兜底社区或标 `unclustered`，**绝不给单节点社区发 LLM 摘要**。`algorithm` 字段预留 Leiden；升级触发：(a) 指纹跳过后摘要重生成率仍 > ~20% 且人工核认为算法漂移；(b) 部署方 opt-in 接受 GPL。升级只换 `community.py` 内调用，schema 不变。

#### Area 2: 成员指纹 / Jaccard 跳过（MOD-02）

- **D-05 — `member_fingerprint = hash(sorted(稳定成员键))`**。稳定键优先 `symbol_id` 字符串；缺 id 时回退 `f"{file_path}:{name}:{symbol_type}"`。哈希算法 Claude's Discretion（sha256 hex 截断即可），须确定性、与集合序无关。指纹写入行；重跑时先比指纹。
- **D-06 — Jaccard 阈值初值 0.8；匹配策略 = 贪心最大 Jaccard 对账**。重跑后新旧社区做成员集 Jaccard；**Jaccard ≥ 0.8**（或指纹全等）→ 视为同一社区：**复用旧 `summary` / `summary_model` / `community_key`（若 key 由指纹派生则保持）并跳过 LLM**；**Jaccard < 0.8** 或无匹配 → 视为新/变社区 → 生成摘要。一对一贪心（按 Jaccard 降序配边，已配过的不再配），避免一对多洗摘要。阈值标注为 MEDIUM 置信初值——相位内用「同一仓连续重建两次」真实图数据校准，写进 SUMMARY；校准后可改 settings/env，但验收用例语义不变。
- **D-07 — 验收铁律：无代码变更连续重建两次 → LLM 调用数 = 0**。测试路径：mock/spy `use_call_source(MODULE_SUMMARY)` 或 LLM invoke；两次 community rebuild（图与成员不变）第二次（及指纹命中路径）零调用。指纹全等应 short-circuit，连 Jaccard 循环都可跳过。观测事件记录 `communities_total` / `summaries_skipped` / `summaries_generated`（sampling）。
- **D-08 — 跳过语义不含「摘要为空也跳过」的漏洞**：指纹/Jaccard 判定未变 **且** 已有非空 `summary` 才跳过；未变但 `summary` 空白（上次 LLM 失败）→ **允许重试生成**（仍计 LLM 调用）。失败 best-effort：单社区 LLM 失败不阻断整仓落库，该行留空 summary + 结构化 failed 事件。

#### Area 3: LLM 模块摘要 / call_source / 批处理（MOD-03）

- **D-09 — `call_source=module_summary`：先登记再写代码**。计划必须含任务：① `.planning/observability/LOGGING-SPEC.md` §4.1 加一行；② `server/agents/call_source.py` 的 `CallSource` 枚举加 `MODULE_SUMMARY = "module_summary"`；③ 同步 `test_model_usage_call_source`（或既有枚举守护）。调用点经 `use_call_source(CallSource.MODULE_SUMMARY)`，上报 token/TTFT/上游错误码。`component="code_graph"`（已在 §5 登记，复用）；关键事件 `module_summary_started/completed/failed` 带 `duration_ms`；高频循环 `category=sampling`。
- **D-10 — 摘要内容契约：关键文件 / 入口 / 职责叙述**。LLM 产出结构化字段（JSON 优先，失败则抽文本兜底）：`key_files[]`、`entry_points[]`（符号或文件路径）、`responsibility`（短段落）。落库时可把结构化结果序列进 `summary`（markdown 或 JSON——Claude's Discretion，消费端有单一 render helper）。输入侧只喂该社区 top 成员元数据（文件路径/符号名/类型/度数启发式），**默认不喂源码正文**（token 纪律，沿用 122 D-17）；必要时仅允许极短 signature 片段。
- **D-11 — 批处理：按社区串行（或极小有界并发 ≤3），已跳过的不进队列**。同仓共享图；默认串行最稳，避免 LLM 槽位风暴。`unclustered` / 规模 &lt; 5 不调用 LLM。模型解析走既有 `aresolve` / `build_chat_model` 范式（照抄 charter draft / decompose 单轮 helper）；temperature=0 或本仓 aux 默认；失败返空不抛（D-08）。
- **D-12 — 模块落点：`community.py`（检测+落库）+ `module_summary.py`（LLM）在 `server/services/code_graph/`**。纯算法可测；ORM 写入收口单一 service 函数（INV-6 精神）。与 impact/trace 一样：**不强制进 barrel 转发**，但取图必须经 `get_graph_service`；若需避免上层误用内部子模块，按 122 D-28 边界在 docstring 写清。⛔ 不把社区逻辑塞进 `repo_router_v2.py`。

#### Area 4: Adapter 注入 / 冻结面 / token 预算（MOD-04）

- **D-13 — ⛔ `repo_router_v2.py` 零改动；注入只在 adapter / 调用方之后**。照抄 `charter_route_signal.py` / `blueprint_route.py` 文档承诺：「只调不改；证据不进 Stage1 prompt」。本相位提交 **不得** stage 该文件。并发会话若已有脏改动——忽略、不依赖、不整理。
- **D-14 — 蓝图路由链：evidence 增强，不做第四打分分量**。在 `server/services/process_runtime/blueprint_route.py` 的 `_EVIDENCE_KEYS` 增加 `module_summaries`（默认 `[]`），在 candidate evidence 组装处 fail-soft 填入该仓 top 社区摘要（相关度排序后截断）。**不**破坏 `router_base + charter_match + history_match` 恒等式；若未来要参与打分，须单独评审权重 schema（research 明文）。
- **D-15 — 对话 / MCP 路由链：新建 `services/module_summary_signal.py`（或等价名），照抄 charter signal 范式**。纯函数取仓摘要 + `aapply_module_summary_signal`（best-effort，失败原样返回）；接线旁路 `repository_relevance.py` 的 charter 应用点与 `mcp_tools/views.py::RouteRepositoriesView`。v1：**evidence / reason 文本追加为主**；可做轻量相关度排序辅助展示，**默认不改 router_base 分数、不加新权重键**（避免与冻结面/golden 回放纠缠）。候选补入（能力树未召回但摘要强相关）列为 Claude's Discretion，上限须严（类比 charter `DEFAULT_SUPPLEMENT_LIMIT=3`），不做不算缺口。
- **D-16 — 技术方案 / 调研 prompt：在 `blueprint_research_adapter` / `artifact_injection`（或同源拼装点）注入 top-N 模块摘要**。照抄 v0.8 `render_upstream_artifacts_section`「空段守卫 + fail-soft」。消费端统一纪律：**按 query↔摘要相关度排序 → token/字符预算截断 → 不全量灌入**。预算初值建议 per-repo **~1.5–2KB** 或 top **3–5** 社区（settings/env 可调，Claude's Discretion 标定）；超限注明 truncated。⛔ 不把全仓社区摘要塞进 Stage1 或调研 prompt。

### Claude's Discretion

- `community_key` 是指纹派生还是稳定序号+指纹映射表；`summary` 存 markdown vs JSON 的最终形状（须有单一 render）。
- Jaccard 校准后是否外置 `SystemSetting`；LLM 有界并发具体数字；目录兜底社区的命名启发式。
- `module_summary_signal` 是否做候选补入；RepoSummaryBuilder 向量文本是否顺手并入 top 社区名（research 提到的免费收益，推荐做但不做不算缺口）。
- 测试组织、管理命令/诊断「同仓重建两次 Jaccard 分布」的交付形态。
- durable 任务函数命名与是否复用既有 `durable_graph` payload 分支 vs 新 task name（须仍走 `QUEUE_GRAPH` + queueing_lock）。

### Deferred Ideas (OUT OF SCOPE)

- Leiden 默认算法 / `leidenalg` 进依赖树（触发条件满足后再做）
- 模块摘要作为 blueprint 第四打分分量或扩 `BLUEPRINT_ROUTE_WEIGHTS`（单独评审）
- Galaxy / 前端社区着色与模块摘要可视化
- 摘要写入 RepoSummary 向量文本的深度产品化（可选顺手并入除外）
- Process 的 intra/cross_community 分类（Phase 126 EXEC-02）
- `mcp/` npm 客户端为新工具补条目（本相位若未新增 MCP 工具名则无此项；若仅 adapter 接线既有 route 工具则不增工具）

None of the above blocks Phase 125 planning.
</user_constraints>

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| MOD-01 | 每仓图上运行社区检测（networkx `louvain_communities` 固定 seed），社区归属以独立模型 + 软引用落库（⛔ 不加在 `Symbol` 上），增量索引后自动刷新 | `SymbolCommunity` 模型字段/migration；`community.py` Louvain 投影；双钩子 enqueue → `QUEUE_GRAPH`；`get_graph_service` 取图纪律 |
| MOD-02 | 社区成员指纹稳定化——指纹（Jaccard 阈值）判定未变的社区跳过摘要重生成；「无代码变更连续重建两次，LLM 调用数为 0」是验收用例 | fingerprint/Jaccard 纯函数 + greedy测；rebuild×2 spy LLM=0；观测 `summaries_skipped` |
| MOD-03 | 每个社区生成 LLM 模块摘要（关键文件 / 入口 / 职责叙述，LLM 调用赋 `call_source`） | Wave 0 先登记 `module_summary`；`module_summary.py` 照抄 `adraft_charter`；规模&lt;5 / unclustered 不调 LLM |
| MOD-04 | 模块摘要注入 RepoRouter adapter 层（evidence 侧）与技术方案生成 prompt（⛔ `repo_router_v2.py` 冻结面）；消费端相关度排序 + token 预算截断 | `_EVIDENCE_KEYS`+`module_summary_signal`+调研 prompt 段；冻结面提交纪律；预算截断 helper |
</phase_requirements>

## Project Constraints (from .cursor/rules/)

来自 `.cursor/rules/observability-logging.mdc`（强制，与 LOGGING-SPEC 对齐）：

- 用 `structlog.get_logger(__name__)`，事件名 snake_case（`xxx_started`/`xxx_completed`/`xxx_failed`），字段用 kv，**不要**把变量拼进 message。
- 脱敏不可绕过：`redact_credentials` / `redact_secrets_in_text`；入库留痕走 `redact_for_ledger`。
- 后台任务必须显式携带 `initiated_by_user_id` 并在 worker 入口 `bind_task_context`；无触发用户记 `system`。
- 新增 LLM 调用点：赋 `call_source`，上报请求数/token/TTFT/上游错误码——**本相位须先登记再使用**。
- 观测代码 best-effort，失败吞掉，绝不打断主流程。
- 高频循环内禁止 INFO 刷屏：用 `category=sampling` + debug 或采样。
- `component`：社区检测/摘要服务用已登记的 `code_graph`（LOGGING-SPEC §5）；durable enqueue 可用 `durable` 或业务 component。

## Architectural Responsibility Map

| Capability | Primary Tier | Secondary Tier | Rationale |
|------------|-------------|----------------|-----------|
| Louvain 社区检测（纯算法） | API / Backend (`services/code_graph/community.py`) | — | 吃内存图，零前端 |
| `SymbolCommunity` 持久化 | Database / Storage (`codegraph` app) | API / Backend (单一 ORM 写入函数) | 纯加表；软引用免疫 Symbol 删建 |
| 增量后刷新触发 | API / Backend (edge/graph 完成钩子) | durable `QUEUE_GRAPH` worker | 钩子只 enqueue；全图重算在 worker |
| LLM 模块摘要 | API / Backend (`module_summary.py`) | LLM provider | 单轮 ainvoke；`call_source=module_summary` |
| 蓝图路由 evidence 注入 | API / Backend (`blueprint_route.py` adapter) | — | 不进 Stage1；不改三分量恒等式 |
| 对话 / MCP 路由信号 | API / Backend (`module_summary_signal.py`) | Browser (展示 evidence 文本) | 调用方之后融合；默认不改 router 分 |
| 调研 prompt 注入 | API / Backend (`blueprint_research_adapter`) | task 容器（消费 prompt） | 服务端拼装；空段守卫 |
| 冻结面 `repo_router_v2` | —（禁止改） | — | §13.2；本相位零 stage |

## Standard Stack

### Core

| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| `networkx` | 3.6.1（`>=3.6,<4`，已 pin） | `louvain_communities` + 弱连通分量 | 已在 server 依赖树；rustworkx 无社区算法 [VERIFIED: uv.lock + 运行时 `nx.__version__`] |
| Django ORM | 5.1+（项目栈） | `SymbolCommunity` 模型 + migration | 既有 `codegraph` app 落点 |
| `structlog` | 项目既有 | 生命周期 / sampling 事件 | 可观测性规范强制 |
| LangChain chat model | 项目既有 (`build_chat_model`) | 单轮模块摘要 | 照抄 `charter_service.adraft` |

### Supporting

| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| `hashlib` (stdlib) | — | `member_fingerprint` sha256 | 指纹计算 |
| procrastinate / durable | 项目既有 | `QUEUE_GRAPH` 任务 | 社区刷新异步化 |
| `asgiref.sync_to_async` | 项目既有 | 异步视图/任务桥 ORM | durable / 信号加载 |

### Alternatives Considered

| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| Louvain (`networkx`) | Leiden (`leidenalg`) | Leiden 更确定且保证连通，但 **GPL-3.0**——对本仓 MIT + ghcr 预构建镜像是硬否决；CONTEXT D-04 锁定 Louvain |
| 新 durable 任务名 | 给 `durable_graph` 加 payload 分支 | 分支会与 IndexHistory/`run_graph` 图谱抽取语义纠缠；**推荐新任务名**仍挂 `QUEUE_GRAPH`（Discretion 建议） |
| 独立 `scanning` app | 放 `codegraph` | CONTEXT/ARCHITECTURE 已指定 `codegraph/models.py` |

**Installation:** 无。本相位 **零新增** PyPI / npm 包。

**Version verification:**
- `networkx==3.6.1` — `uv.lock` sdist upload-time 2025-12-08；运行时 `uv run python -c "import networkx; print(networkx.__version__)"` → `3.6.1` [VERIFIED]
- `louvain_communities` signature: `(G, weight='weight', resolution=1, threshold=1e-07, max_level=None, seed=None, ...)` [VERIFIED: networkx 3.6.1 docs + inspect]

## Package Legitimacy Audit

> 本相位不安装外部新包。既有 `networkx` 已在 lockfile。

| Package | Registry | Age | Downloads | Source Repo | slopcheck | Disposition |
|---------|----------|-----|-----------|-------------|-----------|-------------|
| networkx（既有） | PyPI | 多年成熟 | 高 | github.com/networkx/networkx | N/A（不新装） | Approved — already locked |
| leidenalg | — | — | — | — | — | **REMOVED / OUT OF SCOPE**（GPL；D-04） |

**Packages removed due to slopcheck [SLOP] verdict:** none（无新装包）
**Packages flagged as suspicious [SUS]:** none

## Architecture Patterns

### System Architecture Diagram

```text
                    ┌─────────────────────────────────────┐
                    │  Index / Graph build complete       │
                    │  graph_builder.py                   │
                    │  code_relations/tasks.py (edges)    │
                    └──────────────┬──────────────────────┘
                                   │ invalidate_repository (exist)
                                   │ + enqueue community rebuild
                                   ▼
                    ┌─────────────────────────────────────┐
                    │  Durable QUEUE_GRAPH                │
                    │  durable_community_rebuild          │
                    │  lock=community:{repo}:{branch}     │
                    └──────────────┬──────────────────────┘
                                   │ bind_task_context(user)
                                   ▼
              get_graph_service().get_graph(repo, branch)
                                   │
                                   ▼
                    ┌─────────────────────────────────────┐
                    │  community.py                       │
                    │  1. project undirected Graph        │
                    │     (sorted nodes/edges)            │
                    │  2. WCC filter size≥5               │
                    │  3. louvain_communities(seed=CONST) │
                    │  4. fingerprint + Jaccard match     │
                    │  5. module_summary for changed only │
                    │  6. replace rows (repo, branch)     │
                    └──────────────┬──────────────────────┘
                                   │ SymbolCommunity rows
           ┌───────────────────────┼───────────────────────┐
           ▼                       ▼                       ▼
  blueprint_route.py     module_summary_signal.py   blueprint_research_adapter
  evidence.module_       aapply_* (evidence text)   ## 模块摘要 section
  summaries              + repository_relevance     (budget truncate)
                         + mcp RouteRepositories
           │                       │                       │
           └─────────── ⛔ NEVER touch repo_router_v2.py ──┘
```

### Recommended Project Structure

```
server/codegraph/
├── models.py                 # + SymbolCommunity（纯加表）
└── migrations/0011_*.py      # ADD TABLE only

server/services/code_graph/
├── community.py              # Louvain + 指纹/Jaccard + ORM 替换写入（不进 barrel）
├── module_summary.py         # LLM 摘要 helper（不进 barrel）
└── __init__.py               # 不变：仍只导出 get_graph / 契约

server/services/
├── module_summary_signal.py  # 对话/MCP 链 adapter（镜像 charter_route_signal）
└── community_enqueue.py      # 可选：enqueue helper（镜像 charter_enqueue）

server/durable/
├── tasks.py                  # + durable_community_rebuild @ QUEUE_GRAPH
├── tasks_impl.py             # + run_community_rebuild
└── handlers.py               # + register_handler

server/services/process_runtime/
├── blueprint_route.py        # _EVIDENCE_KEYS + evidence 组装
└── blueprint_research_adapter.py  # _build_prompt 注入模块摘要段

.planning/observability/LOGGING-SPEC.md  # §4.1 +1 行（Wave 0 最先）
server/agents/call_source.py             # MODULE_SUMMARY
server/tests/test_model_usage_call_source.py  # 44→45
```

### Pattern 1: 无向投影 + 固定 seed Louvain（确定性护栏）

**What:** 缓存图是 **frozen `MultiDiGraph`**（节点 id = `str(Symbol.id)`，属性恰好 5 个：`name/symbol_type/file_path/start_line/end_line`）。社区检测前 **copy 投影** 为新的 `nx.Graph`：节点按 id 排序加入，边按 `(min,max)` 去重排序加入；再对每个规模 ≥5 的弱连通分量调用 `louvain_communities(H, seed=LOUVAIN_SEED)`。

**When to use:** 每次 community rebuild。

**Why:** 官方文档明确：「The order in which the nodes are considered can affect the final output… ordering happens using a random shuffle」——`seed` 控制 shuffle；节点插入序仍影响，故必须稳定构图。[CITED: networkx.org louvain_communities docs]

**Example:**
```python
# Source: networkx 3.6.1 docs + 本仓实测
from networkx.algorithms.community import louvain_communities
import networkx as nx

LOUVAIN_SEED = 42  # 模块级常量，写入测试

def project_undirected(g: nx.MultiDiGraph) -> nx.Graph:
    # ⛔ 不就地改 g（可能已 freeze）；投影到新 Graph
    u = nx.Graph()
    u.add_nodes_from(sorted(g.nodes()))
    edges = {(a, b) if a <= b else (b, a) for a, b in g.edges()}
    u.add_edges_from(sorted(edges))
    return u
```

### Pattern 2: 指纹 short-circuit → Jaccard 贪心对账

**What:**
1. 新社区算 `member_fingerprint = sha256("\n".join(sorted(keys))).hexdigest()[:32]`
2. 与旧行 fingerprint 全等且 `summary` 非空 → 直接复用，**不进 Jaccard、不调 LLM**
3. 其余按成员集 Jaccard 降序一对一配对；≥0.8 且旧 summary 非空 → 复用
4. 未匹配或 summary 空 → 进 LLM 队列

**When to use:** 每次 rebuild 落库前。

### Pattern 3: Durable enqueue（钩子旁、不内联）

**What:** 在 Phase 121 已有的两处 `invalidate_repository` 旁追加 best-effort enqueue（镜像 `charter_enqueue.py`）：

| 钩子文件 | 现有动作 | 本相位追加 |
|----------|----------|------------|
| `server/services/graph_builder.py` ~L524–533 | Galaxy refresh + invalidate | `enqueue_community_rebuild` |
| `server/code_relations/tasks.py` ~L224–242 | Galaxy refresh + invalidate | 同上 |

**推荐任务名（Discretion）：** `durable_community_rebuild`（**不要**给 `durable_graph`/`run_graph` 加分支——后者绑定 IndexHistory 图谱抽取）。仍 `queue=QUEUE_GRAPH`，`idempotency_key`/`queueing_lock=f"community:{repo_id}:{branch or ''}"`。

**Worker 体：** `bind_task_context` → `get_graph_service().get_graph` → rebuild → 观测事件。

### Pattern 4: Adapter-only 三注入点

1. **蓝图：** `blueprint_route.py` L57–71 `_EVIDENCE_KEYS` + L615–630 evidence dict 组装处加 `module_summaries`；`_normalize_evidence` defaults 加 `[]`。**不**改 `_COMPONENT_KEYS`。
2. **对话/MCP：** 新 `services/module_summary_signal.py`；接线 `repository_relevance._apply_charter_signal` 旁与 `mcp_tools/views.py::RouteRepositoriesView`（约 L450 章程信号之后）。v1 只追加 evidence/reason 文本。
3. **调研：** `blueprint_research_adapter._build_prompt`（约 L769–774 章程段旁）插入 `## 模块摘要`；空 → `""`（照抄 `render_upstream_artifacts_section`）。

### Anti-Patterns to Avoid

- **在钩子内联跑 Louvain/LLM：** 拉长索引/边构建关键路径；违反 D-03。
- **给 Symbol 加 community_id / M2M：** per-file 删建丢标注；违反 D-02。
- **改 `repo_router_v2.py` 或 Stage1 prompt：** 冻结面；golden/回放纠缠。
- **把模块摘要做成第四打分分量：** 破坏 `total == sum(components)` 恒等式；递延。
- **跳过「summary 为空」社区的重试：** D-08 漏洞。
- **直连 `services.code_graph.loader/cache`：** AST 守护测红（`test_no_upper_layer_imports_internal_submodules`）。`community.py` 自身取图仍走 barrel。
- **把 `signature` TextField 灌进 LLM 输入：** 节点属性刻意不含 signature（内存契约）；默认不喂源码。
- **全仓社区摘要灌入 prompt：** 必须排序 + 预算截断。

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| 社区检测算法 | 自研模块度优化 | `networkx.algorithms.community.louvain_communities` | 已依赖；API 含 seed |
| 路由融合框架 | 改 Stage1 / 改 v2 router | `charter_route_signal` 镜像 + evidence 键 | 冻结面 + 既有范式 |
| LLM 调用上下文 | 手写 call_source 字符串 | `CallSource` + `use_call_source` | 枚举守护防基数失控 |
| durable 入队 | 自建线程/队列 | `DurableTaskService.defer` + `QUEUE_GRAPH` | 幂等 lock + 多副本 |
| Prompt 空段 | 硬拼标题 | `render_upstream_artifacts_section` 空守卫模式 | 零回归 |
| 用户上下文传播 | 靠线程局部隐式 | `initiated_by_user_id` + `bind_task_context` | CTX-02 |

**Key insight:** 本相位几乎全是「既有缝上的组装」——算法、队列、观测、adapter 范式都已存在；手写新基础设施只会破坏冻结面与验收纪律。

## Common Pitfalls

### Pitfall 1: Louvain 同 seed 仍漂移（networkx #6655）

**What goes wrong:** 固定 seed 后社区划分仍随节点插入序变化，导致摘要反复重生成、成本失控。
**Why it happens:** 官方文档与 issue #6655（wontfix）确认节点考虑顺序影响输出。
**How to avoid:** 投影 Graph 时 **sorted nodes + sorted edges**；指纹 + Jaccard 跳过；验收用例钉死「无变更 LLM=0」。
**Warning signs:** 同仓连续 rebuild 的 `summaries_generated` 居高不下、Jaccard 分布大量 &lt;0.8。

### Pitfall 2: 就地修改缓存 MultiDiGraph

**What goes wrong:** 污染本 worker 全部后续 `get_graph` 命中；freeze 下直接抛 `NetworkXError`。
**Why it happens:** `CodeGraph.graph` 是共享冻结对象。
**How to avoid:** 只对投影副本跑算法；只读遍历度数可用原图（勿 `add_edge`）。
**Warning signs:** 偶发 `NetworkXError: Frozen graph`；impact 结果被污染。

### Pitfall 3: `call_source` 先写代码后登记

**What goes wrong:** `CallSource.normalize` 把未知值打成 `unknown`；守护测 44 值断言失败；指标维度污染。
**How to avoid:** Wave 0 任务顺序：LOGGING-SPEC → 枚举 → `_EXPECTED_CALL_SOURCES`（44→45）→ 再写 `module_summary.py`。
**Warning signs:** CI `test_enum_has_all_22_values` 红；ModelUsageRecord `call_source=unknown`。

### Pitfall 4: 误 stage `repo_router_v2.py`

**What goes wrong:** 违反 §13.2；与并发会话脏改动纠缠。
**How to avoid:** 提交前 `git status` / `git diff --name-only` 显式排除；计划写清「不得 stage」。
**Warning signs:** PR 文件列表出现该路径。

### Pitfall 5: community.py ORM 与 121/122「仅 loader 持 ORM」张力

**What goes wrong:** 执行者把社区逻辑塞进包外兄弟模块或强行进 barrel，破坏 D-12。
**How to avoid:** CONTEXT D-12 锁定落点 `services/code_graph/community.py`——视作与 `loader` 同类的 **ORM 例外同伴**；**不进** `__all__` barrel；**不进** `test_access._INTERNAL_SUBMODULES` 黑名单（壳层/durable 可 `import services.code_graph.community`）。取图仍必须 `get_graph_service`。
**Warning signs:** barrel 膨胀；或 durable 任务绕过 get_graph 直查 Symbol 拼边。

### Pitfall 6: 证据键加了但 `_normalize_evidence` 默认值未同步

**What goes wrong:** 下游 `.get` 行为不一致；缺键时不是 `[]`。
**How to avoid:** `_EVIDENCE_KEYS` 与 `defaults` 同 diff；扩展 `test_blueprint_route_breakdown`。
**Warning signs:** KeyError 或前端拿到 `null`。

### Pitfall 7: 图节点无 `chunk_id` 属性

**What goes wrong:** 执行者以为节点属性有 chunk_id，或为取 chunk 去改 loader 内存契约。
**How to avoid:** members 的 `chunk_id` 可选——从 `CodeGraph.chunk_evidence` 反查（symbol→chunks 的逆映射取首个）或留 `null`；**勿**给节点加第 6 属性。
**Warning signs:** loader 节点属性数守护测失败。

## Code Examples

### Louvain 调用（官方）

```python
# Source: https://networkx.org/documentation/stable/reference/algorithms/generated/networkx.algorithms.community.louvain.louvain_communities.html
import networkx as nx
G = nx.petersen_graph()
nx.community.louvain_communities(G, seed=123)
# [{0, 4, 5, 7, 9}, {1, 2, 3, 6, 8}]
```

### CallSource 作用域（照抄 charter）

```python
# Source: server/repositories/services/charter_service.py（既有模式）
from agents.call_source import CallSource, use_call_source
from agents.llm_concurrency import acquire_llm_slot
from agents.llm_factory import build_chat_model

with use_call_source(CallSource.MODULE_SUMMARY):  # 登记后才存在
    async with acquire_llm_slot(cred_id, max_c):
        response = await model_obj.ainvoke(messages)
```

### Evidence 键扩展（契约面）

```python
# Source: server/services/process_runtime/blueprint_route.py L57-71 / L173-191
_EVIDENCE_KEYS = (
    # ... existing ...
    "module_summaries",  # NEW — list[dict|str], default []
)

def _normalize_evidence(evidence: dict | None) -> dict:
    defaults = {
        # ... existing ...
        "module_summaries": [],
    }
    return {key: src.get(key, defaults[key]) for key in _EVIDENCE_KEYS}
```

### Durable enqueue（镜像 charter）

```python
# Source: server/repositories/charter_enqueue.py 模式
job_id = await DurableTaskService.defer(
    "durable_community_rebuild",
    {"repository_id": str(repository_id), "branch_name": branch or ""},
    queue=QUEUE_GRAPH,
    idempotency_key=f"community:{repository_id}:{branch or ''}",
    initiated_by_user_id=initiated_by_user_id,  # None → worker 内 system
)
```

### Jaccard

```python
def jaccard(a: set[str], b: set[str]) -> float:
    if not a and not b:
        return 1.0
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)
```

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| Leiden 默认（部分调研倾向） | Louvain + 指纹/Jaccard（license 优先） | v0.22.0 research 交叉裁决 | 零 GPL 依赖；漂移工程缓解 |
| Symbol 上挂 community_id | 独立 `SymbolCommunity` 软引用 | ARCHITECTURE Pattern 4 | 免疫 per-file 删建 |
| 改 RepoRouter Stage1 | adapter evidence / 调用方后信号 | §13.2 冻结面 | 与 golden 回放解耦 |

**Deprecated/outdated:**
- 默认引入 `leidenalg`：本里程碑否决（D-04 / Deferred）。
- 模块摘要作第四打分分量：本相位否决（D-14）。

## Discretion Recommendations（供 planner 落定）

| Topic | Recommendation | Rationale |
|-------|----------------|-----------|
| `community_key` | 指纹派生：`fp[:16]`；Jaccard 命中时 **复用旧 key** | 稳定跨 rebuild；避免序号漂移洗 key |
| `summary` 存储 | JSON 文本（`key_files/entry_points/responsibility`）+ `render_module_summary()` → markdown | 结构化消费 + 单一 render |
| 指纹哈希 | `sha256` hex **截断 32** | 够用、确定性、短于 CharField |
| Louvain seed | 模块常量 `LOUVAIN_SEED = 42` | 测试可断言 |
| LLM 并发 | **串行（1）** | D-11；避免槽位风暴 |
| Jaccard 配置 | 先模块常量 `JACCARD_THRESHOLD = 0.8`；校准后再考虑 SettingKeys | 验收语义不变 |
| 目录兜底 | `unclustered:{top_dir}` 按文件路径首段聚合过小分量；不调 LLM | D-04 |
| durable 任务名 | **新** `durable_community_rebuild` | 与 `run_graph` 解耦 |
| signal 候选补入 | **v1 不做**（不算缺口） | 降低与 golden 纠缠；evidence 追加已满足 MOD-04 |
| RepoSummaryBuilder | **推荐顺手**：description 追加 top-3 社区责任一句话 | 免费召回收益；失败 skip |
| 预算 | per-repo **2000 字符** 或 top **5** 社区（先到为准） | D-16 初值 |
| 诊断交付 | pytest 夹具 + 可选 management command 打 Jaccard 分布 JSON | CONTEXT Specific Ideas |

## Assumptions Log

| # | Claim | Section | Risk if Wrong |
|---|-------|---------|---------------|
| A1 | 无向投影（忽略边方向/多重边）对模块摘要质量够用 | Pattern 1 | 社区边界略糊；可用 resolution 调，不阻塞 |
| A2 | 仅 `graph_builder` + `code_relations` 两处 invalidate 旁 enqueue 即覆盖「增量索引后刷新」 | Pattern 3 | 若存在第三条建边完成路径会漏刷新——计划应 grep `invalidate_repository(` 全覆盖 |
| A3 | v1 signal 不做候选补入仍满足 MOD-04 | Discretion | 召回面略窄；可后续加 |
| A4 | `chunk_id` 可空不阻塞消费 | Pitfall 7 | 下游若强依赖 chunk 需补反查 |

**已验证、非 ASSUMED 的关键事实：** networkx 3.6.1 API、冻结图可只读跑 Louvain、节点 id=symbol UUID 字符串、证据键扩展面、charter signal 接线坐标、CallSource 44 值守护、QUEUE_GRAPH 注册模式。

## Open Questions (RESOLVED)

1. **真实仓连续重建两次的 Jaccard 分布**
   - What we know: #6655 理论漂移 + 节点排序护栏；阈值 0.8 为 MEDIUM 初值。
   - What's unclear: 本仓生产图实际漂移率。
   - Recommendation: 相位内交付诊断数据进 SUMMARY；若跳过后重生成率仍 &gt;20% 再评 Leiden 触发条件（不在本相位默认切换）。
   - **RESOLVED:** 自动化验收用合成 MultiDiGraph fixture（`test_rebuild_twice_zero_llm` 等）钉死跳过语义；真实仓 Jaccard 分布校准写入相位 SUMMARY，不阻塞 AC。验收阈值保持 **Jaccard ≥ 0.8**（指纹全等 short-circuit）；校准后可外置 settings/env，但用例语义不变。

2. **branch_name 透传**
   - What we know: Symbol/图以 `branch_name=""` 为基线。
   - What's unclear: feature 分支图构建完成钩子是否总带 branch。
   - Recommendation: enqueue payload 显式 `branch_name`；缺省 `""`；lock 含 branch。
   - **RESOLVED:** `enqueue_community_rebuild` / `DurableTaskService.defer` payload **必须显式传 `branch_name`**（缺省 `""`）；`queueing_lock` / `idempotency_key` 含 branch（`community:{repo_id}:{branch or ''}`）。钩子侧从建图/失效上下文透传，禁止静默省略导致基线串扰。

## Environment Availability

| Dependency | Required By | Available | Version | Fallback |
|------------|------------|-----------|---------|----------|
| Python | server | ✓ | 3.14.6 | — |
| uv | deps/tests | ✓ | /opt/homebrew/bin/uv | — |
| networkx | Louvain | ✓ | 3.6.1 | —（已 pin） |
| pytest | Validation | ✓ | 9.0.2 | — |
| Qdrant / 真仓图 | 校准 Jaccard | 可选 | — | 合成 MultiDiGraph fixture 即可过验收；校准用真实图另记 SUMMARY |
| leidenalg | — | N/A | — | 明确不装 |

**Missing dependencies with no fallback:** none

**Missing dependencies with fallback:** 真实生产图（用 fixture 验收 MOD-02；校准另做）

Step 2.6: 外部依赖均已满足；本相位以代码/配置为主。

## Validation Architecture

### Test Framework

| Property | Value |
|----------|-------|
| Framework | pytest 9.0.2 + pytest-django + pytest-asyncio |
| Config file | `server/pyproject.toml`（`[tool.pytest.ini_options]`） |
| Quick run command | `cd server && uv run pytest tests/services/code_graph/test_community.py tests/services/code_graph/test_module_summary.py tests/services/test_module_summary_signal.py tests/test_model_usage_call_source.py -q --no-header` |
| Full suite command | `cd server && uv run pytest tests/services/code_graph/ tests/services/process_runtime/test_blueprint_route_breakdown.py tests/services/test_charter_route_signal.py tests/test_model_usage_call_source.py -q` |

### Phase Requirements → Test Map

| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| MOD-01 | Louvain 固定 seed + 节点排序 → 同图两次划分一致；落库 `SymbolCommunity` 软引用无 FK | unit + db | `uv run pytest tests/services/code_graph/test_community.py::test_louvain_seed_stable -x` | ❌ Wave 0 |
| MOD-01 | 钩子/enqueue 调用 `DurableTaskService.defer` 且不内联 Louvain | unit | `uv run pytest tests/services/code_graph/test_community_enqueue.py -x` | ❌ Wave 0 |
| MOD-01 | migration 只 ADD TABLE；`Symbol` 无 community 字段 | migration/static | `uv run pytest tests/codegraph/test_symbol_community_model.py -x` | ❌ Wave 0 |
| MOD-02 | 指纹全等 short-circuit；Jaccard≥0.8 复用 summary | unit | `uv run pytest tests/services/code_graph/test_community.py::test_fingerprint_jaccard_skip -x` | ❌ Wave 0 |
| MOD-02 | **无变更 rebuild×2 → LLM invoke 次数 = 0** | unit（spy） | `uv run pytest tests/services/code_graph/test_community.py::test_rebuild_twice_zero_llm -x` | ❌ Wave 0 |
| MOD-02 | summary 空允许重试（仍计 LLM） | unit | `uv run pytest tests/services/code_graph/test_community.py::test_empty_summary_retries -x` | ❌ Wave 0 |
| MOD-03 | `CallSource.MODULE_SUMMARY` 在枚举 + LOGGING-SPEC 对齐；守护 45 值 | unit | `uv run pytest tests/test_model_usage_call_source.py::TestCallSourceEnum -x` | ✅（须改期望集） |
| MOD-03 | `use_call_source(MODULE_SUMMARY)` 包裹 ainvoke；失败不阻断落库 | unit | `uv run pytest tests/services/code_graph/test_module_summary.py -x` | ❌ Wave 0 |
| MOD-03 | size&lt;5 / unclustered 不调 LLM | unit | 同上 | ❌ Wave 0 |
| MOD-04 | `_EVIDENCE_KEYS` 含 `module_summaries`；三分量恒等式仍成立 | unit | `uv run pytest tests/services/process_runtime/test_blueprint_route_breakdown.py -x` | ✅（须扩展） |
| MOD-04 | signal fail-soft；不改 router_base 分（v1） | unit | `uv run pytest tests/services/test_module_summary_signal.py -x` | ❌ Wave 0 |
| MOD-04 | 调研 prompt 空段守卫 + 预算截断 | unit | `uv run pytest tests/services/process_runtime/test_module_summary_prompt.py -x` | ❌ Wave 0 |
| MOD-04 | 静态：本相位 diff 不含 `repo_router_v2.py` / `mcp/` | static/guard | `uv run pytest tests/services/code_graph/test_frozen_surface_125.py -x` | ❌ Wave 0 |

### Sampling Rate

- **Per task commit:** Quick run command（上表）
- **Per wave merge:** Full suite command（上表）
- **Phase gate:** Full suite green + MOD-02 `test_rebuild_twice_zero_llm` 必绿，再 `/gsd-verify-work`

### Wave 0 Gaps

- [ ] `tests/services/code_graph/test_community.py` — Louvain 稳定 / 指纹 / Jaccard / rebuild×2 LLM=0（MOD-01/02）
- [ ] `tests/services/code_graph/test_module_summary.py` — call_source + fail-soft + 规模门槛（MOD-03）
- [ ] `tests/services/test_module_summary_signal.py` — adapter fail-soft（MOD-04）
- [ ] `tests/services/process_runtime/test_module_summary_prompt.py` — 空段 + 预算（MOD-04）
- [ ] `tests/codegraph/test_symbol_community_model.py` — 模型字段 / 无 Symbol FK（MOD-01）
- [ ] `tests/services/code_graph/test_community_enqueue.py` — defer + lock 键（MOD-01）
- [ ] `tests/services/code_graph/test_frozen_surface_125.py` — 冻结面守卫（MOD-04）
- [ ] 扩展 `tests/test_model_usage_call_source.py`：`module_summary` → 45 值
- [ ] 扩展 `tests/services/process_runtime/test_blueprint_route_breakdown.py`：`module_summaries` 默认 `[]`
- [ ] Wave 0 文档任务：LOGGING-SPEC §4.1 登记 `module_summary`（**先于**调用点代码）

## Security Domain

### Applicable ASVS Categories

| ASVS Category | Applies | Standard Control |
|---------------|---------|-----------------|
| V2 Authentication | no（无新认证面） | — |
| V3 Session Management | no | — |
| V4 Access Control | yes | 取图经 `get_graph_service` → `ensure_repository_readable` + exclusion fail-closed；社区重建 worker 仅内部 durable |
| V5 Input Validation | yes | LLM JSON 解析 fail-soft；prompt 注入侧对半可信字段做 `_safe_inline` 同类消毒；members JSON schema 最小校验 |
| V6 Cryptography | no（指纹用 sha256 做内容寻址非密钥） | stdlib hashlib — 勿当 MAC |

### Known Threat Patterns for this stack

| Pattern | STRIDE | Standard Mitigation |
|---------|--------|---------------------|
| 被排除文件符号漏进社区/摘要 | Information Disclosure | 只经 `get_graph` 取图；禁止直连 loader |
| LLM/摘要 prompt 注入 | Tampering | 只喂路径/符号名元数据；不喂源码正文；渲染消毒 |
| 凭证进日志 | Information Disclosure | `redact_secrets_in_text`；不记 prompt 全文含 secret |
| 恶意超大 members JSON | Denial of Service | top_files / 成员入 LLM 截断；预算截断消费端 |
| 未授权触发重建 | Elevation | durable 仅内部 enqueue；API 若暴露须鉴权（v1 无新公共写 API） |

## Sources

### Primary (HIGH confidence)

- [VERIFIED] 本仓代码：`server/services/code_graph/{__init__,model,loader,cache}.py`；`server/codegraph/models.py`；`server/services/charter_route_signal.py`；`server/services/process_runtime/blueprint_route.py`；`server/services/process_runtime/blueprint_research_adapter.py`；`server/services/process_runtime/artifact_injection.py`；`server/durable/{queues,tasks,tasks_impl,handlers,service}.py`；`server/agents/call_source.py`；`server/repositories/services/charter_service.py`；`server/repositories/charter_enqueue.py`；`server/code_relations/tasks.py`；`server/services/graph_builder.py`；`server/tests/test_model_usage_call_source.py`
- [CITED] https://networkx.org/documentation/stable/reference/algorithms/generated/networkx.algorithms.community.louvain.louvain_communities.html — `seed`、节点顺序影响输出、返回 `list[set]`
- [VERIFIED] `uv.lock` networkx 3.6.1；运行时 inspect signature
- [CITED] `.planning/research/SUMMARY.md` Louvain vs Leiden 交叉裁决；`.planning/research/ARCHITECTURE.md` Pattern 4/5
- [CITED] `.planning/observability/LOGGING-SPEC.md` §4.1 / §5（`code_graph` component）
- [CITED] `.planning/phases/125-community-summary/125-CONTEXT.md` D-01…D-16

### Secondary (MEDIUM confidence)

- networkx issue #6655（Louvain 同 seed 非确定，官方 wontfix）— research/SUMMARY 引用；本相位用工程护栏缓解
- Jaccard 0.8 / 最小分量 5 — research MEDIUM 经验阈值，相位内校准

### Tertiary (LOW confidence)

- 生产图实际漂移率与 Leiden 触发条件是否会被命中 — 待相位内数据

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH — 零新依赖；API 与 lockfile 已核实
- Architecture: HIGH — 落点/钩子/注入坐标均在本仓核实；与 CONTEXT 一致
- Pitfalls: HIGH — 冻结面、call_source 顺序、缓存 freeze、#6655 均有代码或官方依据

**Research date:** 2026-08-10
**Valid until:** 2026-09-09（30 天；networkx 主版本未升前有效）
