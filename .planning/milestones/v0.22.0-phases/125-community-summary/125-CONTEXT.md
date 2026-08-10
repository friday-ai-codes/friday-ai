# Phase 125: 社区检测 + 模块摘要 - Context

**Gathered:** 2026-08-10
**Status:** Ready for planning

<domain>
## Phase Boundary

每仓在 Phase 121 内存图上跑社区检测，把符号聚成模块并以独立模型软引用落库；用成员指纹 + Jaccard 对账跳过未变社区的 LLM 摘要重生成；为每个社区生成「关键文件 / 入口 / 职责」模块摘要；再把摘要以 **adapter 层 evidence / prompt 注入**喂给 RepoRouter 消费链与技术方案调研——回答「这段代码属于哪个模块、这个仓有哪些职责」。

**In scope (MOD-01…04):** `SymbolCommunity` 新模型 + Louvain（固定 seed + 节点排序）+ 增量索引后 durable 刷新；member fingerprint / Jaccard 跳过（验收：无代码变更连续重建两次 → LLM 调用数 0）；`module_summary` LLM（`call_source` 先登记 LOGGING-SPEC §4.1）；三点 adapter 注入（blueprint_route evidence / 对话·MCP 信号 / 调研 prompt）+ 消费端相关度排序与 token 预算截断。

**Out of scope / frozen:**
- ⛔ `server/codegraph/services/repo_router_v2.py` **全程零改动**（§13.2 冻结面；并发会话可能有脏改动——本相位不 stage、不依赖改该文件）
- ⛔ `mcp/` submodule 零改动（沿用 122 D-27 / 123 / 124）
- ⛔ 不给 `Symbol` 加 `community_id` / FK / M2M
- Galaxy 社区着色 / 可视化（REQUIREMENTS Future）
- Leiden 默认切换（触发条件升级项，见 D-04）
- 摘要参与 blueprint 打分第四分量 / 权重 schema 变更（须单独评审；本相位只做 evidence）
- Phase 126 Process / rename / skills；Phase 127 Semgrep / LSP

**Depends on:** Phase 121（`get_graph` / MultiDiGraph / 边准入）。可与 122–124 并行，但不依赖其未完成项。

</domain>

<decisions>
## Implementation Decisions

### Area 1: 社区模型 / 软引用 / 刷新触发（MOD-01）

- **D-01 — 独立模型 `SymbolCommunity`，纯加表、零改既有表**。落点 `server/codegraph/models.py`（research ARCHITECTURE Pattern 4）；migration 只 ADD TABLE。字段最小集：`repository` FK、`branch_name`（`""`=基线，对齐 Symbol/图隔离）、`community_key`（稳定 key，见 D-02）、`algorithm`（`"louvain"` / 预留 `"leiden"`）、`member_count`、`members` JSON、`top_files` JSON、`member_fingerprint`、`summary` / `summary_model` / `summary_generated_at`（可空）、`built_at_sha`（对齐 `last_indexed_commit_sha` 水位）、时间戳。`unique_together = (repository, branch_name, community_key)`。
- **D-02 — 软引用成员，⛔ 不加 FK、⛔ 不挂 `Symbol.community_id`**。`members` 存快照列表，每项至少 `{symbol_id, name, file_path, symbol_type, chunk_id?}`——`symbol_id` 为 UUID **字符串软引用**（对齐 `Symbol.chunk_id` 柔性引用先例），不建 FK/CASCADE。理由：增量索引 per-file 删建 Symbol 会丢挂在 Symbol 上的标注；社区重算也不应 UPDATE 数万行 Symbol。孤儿 soft-id 在消费时忽略即可。
- **D-03 — 全仓全删全建刷新，投 durable `QUEUE_GRAPH`，不在索引钩子内联跑**。社区检测是全图算法，无增量意义。触发点 = 边构建完成钩子旁（与 Phase 121 图失效同点，`code_relations` lifecycle / graph build completed），`defer` 入队；`queueing_lock=f"community:{repo_id}:{branch}"` 去重防抖；`initiated_by_user_id` 透传（无则 `system`）。任务内：`get_graph`（经 barrel，⛔ 不直连 loader/cache）→ Louvain → 指纹对账 → 摘要回填 → 按 `(repository, branch_name)` 替换该仓社区行。`built_at_sha` 落水位，消费方可判 stale。
- **D-04 — 算法 = networkx `louvain_communities`，固定 seed + 节点排序；Leiden 否决默认引入**。裁决依据 research/SUMMARY「Louvain vs Leiden」：GPL-3.0 `leidenalg` 对 MIT + ghcr 预构建镜像是硬约束；漂移用工程护栏缓解。实现：构图/跑算法前对节点 ID **稳定排序**后喂入；`seed` 固定为模块级常量（写入测试）。预处理：只对规模 ≥ **5** 符号的弱连通分量跑算法；孤立/过小分量归目录兜底社区或标 `unclustered`，**绝不给单节点社区发 LLM 摘要**。`algorithm` 字段预留 Leiden；升级触发：(a) 指纹跳过后摘要重生成率仍 > ~20% 且人工核认为算法漂移；(b) 部署方 opt-in 接受 GPL。升级只换 `community.py` 内调用，schema 不变。

### Area 2: 成员指纹 / Jaccard 跳过（MOD-02）

- **D-05 — `member_fingerprint = hash(sorted(稳定成员键))`**。稳定键优先 `symbol_id` 字符串；缺 id 时回退 `f"{file_path}:{name}:{symbol_type}"`。哈希算法 Claude's Discretion（sha256 hex 截断即可），须确定性、与集合序无关。指纹写入行；重跑时先比指纹。
- **D-06 — Jaccard 阈值初值 0.8；匹配策略 = 贪心最大 Jaccard 对账**。重跑后新旧社区做成员集 Jaccard；**Jaccard ≥ 0.8**（或指纹全等）→ 视为同一社区：**复用旧 `summary` / `summary_model` / `community_key`（若 key 由指纹派生则保持）并跳过 LLM**；**Jaccard < 0.8** 或无匹配 → 视为新/变社区 → 生成摘要。一对一贪心（按 Jaccard 降序配边，已配过的不再配），避免一对多洗摘要。阈值标注为 MEDIUM 置信初值——相位内用「同一仓连续重建两次」真实图数据校准，写进 SUMMARY；校准后可改 settings/env，但验收用例语义不变。
- **D-07 — 验收铁律：无代码变更连续重建两次 → LLM 调用数 = 0**。测试路径：mock/spy `use_call_source(MODULE_SUMMARY)` 或 LLM invoke；两次 community rebuild（图与成员不变）第二次（及指纹命中路径）零调用。指纹全等应 short-circuit，连 Jaccard 循环都可跳过。观测事件记录 `communities_total` / `summaries_skipped` / `summaries_generated`（sampling）。
- **D-08 — 跳过语义不含「摘要为空也跳过」的漏洞**：指纹/Jaccard 判定未变 **且** 已有非空 `summary` 才跳过；未变但 `summary` 空白（上次 LLM 失败）→ **允许重试生成**（仍计 LLM 调用）。失败 best-effort：单社区 LLM 失败不阻断整仓落库，该行留空 summary + 结构化 failed 事件。

### Area 3: LLM 模块摘要 / call_source / 批处理（MOD-03）

- **D-09 — `call_source=module_summary`：先登记再写代码**。计划必须含任务：① `.planning/observability/LOGGING-SPEC.md` §4.1 加一行；② `server/agents/call_source.py` 的 `CallSource` 枚举加 `MODULE_SUMMARY = "module_summary"`；③ 同步 `test_model_usage_call_source`（或既有枚举守护）。调用点经 `use_call_source(CallSource.MODULE_SUMMARY)`，上报 token/TTFT/上游错误码。`component="code_graph"`（已在 §5 登记，复用）；关键事件 `module_summary_started/completed/failed` 带 `duration_ms`；高频循环 `category=sampling`。
- **D-10 — 摘要内容契约：关键文件 / 入口 / 职责叙述**。LLM 产出结构化字段（JSON 优先，失败则抽文本兜底）：`key_files[]`、`entry_points[]`（符号或文件路径）、`responsibility`（短段落）。落库时可把结构化结果序列进 `summary`（markdown 或 JSON——Claude's Discretion，消费端有单一 render helper）。输入侧只喂该社区 top 成员元数据（文件路径/符号名/类型/度数启发式），**默认不喂源码正文**（token 纪律，沿用 122 D-17）；必要时仅允许极短 signature 片段。
- **D-11 — 批处理：按社区串行（或极小有界并发 ≤3），已跳过的不进队列**。同仓共享图；默认串行最稳，避免 LLM 槽位风暴。`unclustered` / 规模 &lt; 5 不调用 LLM。模型解析走既有 `aresolve` / `build_chat_model` 范式（照抄 charter draft / decompose 单轮 helper）；temperature=0 或本仓 aux 默认；失败返空不抛（D-08）。
- **D-12 — 模块落点：`community.py`（检测+落库）+ `module_summary.py`（LLM）在 `server/services/code_graph/`**。纯算法可测；ORM 写入收口单一 service 函数（INV-6 精神）。与 impact/trace 一样：**不强制进 barrel 转发**，但取图必须经 `get_graph_service`；若需避免上层误用内部子模块，按 122 D-28 边界在 docstring 写清。⛔ 不把社区逻辑塞进 `repo_router_v2.py`。

### Area 4: Adapter 注入 / 冻结面 / token 预算（MOD-04）

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

</decisions>

<code_context>
## Existing Code Insights

### Reusable Assets
- **内存图服务** `server/services/code_graph/`：`get_graph_service` / `GraphService.get_graph`、`MultiDiGraph`、签名水位、`component=code_graph` 观测契约（Phase 121）。社区检测只吃图，经 barrel 取图。
- **networkx 3.6.1** 已在依赖树，含 `louvain_communities`——零新增 Python 依赖（research STACK）。
- **Symbol / CallEdge / Endpoint** `server/codegraph/models.py`：`Symbol.chunk_id` 已是「柔性引用不加 FK」先例；`branch_name` 隔离维度可原样复用。
- **Adapter 范式** `server/services/charter_route_signal.py`：冻结 `repo_router_v2`、调用方后融合、evidence 字符串、best-effort——模块摘要信号应镜像此结构。
- **蓝图 evidence 契约** `blueprint_route.py` `_EVIDENCE_KEYS`（固定键清单 + `_normalize_evidence` 默认值）——加 `module_summaries` 是合法扩展面。
- **durable** `QUEUE_GRAPH` + `queueing_lock` + `initiated_by_user_id`（`durable/queues.py` / `tasks.py`）。
- **CallSource** `server/agents/call_source.py` + LOGGING-SPEC §4.1——新值必须双登记；守护测 `test_model_usage_call_source`。
- **单轮 LLM helper 样板**：`charter_service.adraft` / `decompose_segments`（`use_call_source` + `build_chat_model(streaming=False)` + fail-soft）。

### Established Patterns
- 新持久化 → 独立模型 + 软引用，不加在会被 per-file 删建的行上（ARCHITECTURE Pattern 4）。
- 重计算 → 钩子只 enqueue，不内联；同仓 lock 去重。
- 路由增强 → adapter evidence，不进冻结 Stage1；三分量恒等式不可破。
- 消费截断 → Aider 范式「排序 + token 预算」（research SUMMARY）。
- 观测 → started/completed/failed + `duration_ms`；后台任务绑发起用户；脱敏不可绕过。

### Integration Points
| 点 | 文件 / 钩子 | 本相位动作 |
|----|-------------|-----------|
| 图输入 | `services.code_graph.get_graph_service` | Louvain 输入 |
| 落库 | `codegraph/models.py` + migration | `SymbolCommunity` |
| 刷新 | 边构建完成 → durable `QUEUE_GRAPH` | community rebuild task |
| LLM | `code_graph/module_summary.py` | `call_source=module_summary` |
| 蓝图路由 | `process_runtime/blueprint_route.py` | evidence `module_summaries` |
| 对话路由 | `agents/tools/repository_relevance.py` | 旁路 apply signal |
| MCP 路由 | `mcp_tools/views.py` RouteRepositories | 旁路 apply signal |
| 调研 prompt | `blueprint_research_adapter` / `artifact_injection` | top-N + 预算截断 |
| 冻结 | `codegraph/services/repo_router_v2.py` | **零改动** |
| npm | `mcp/` submodule | **零改动** |

</code_context>

<specifics>
## Specific Ideas

- research/SUMMARY **「交叉冲突裁决：Louvain vs Leiden」**是本相位算法与验收内核：license 优先 → Louvain + 指纹/Jaccard；Leiden 仅触发条件升级。相位首批交付应含「同一仓重建两次的 Jaccard 对账数据」。
- MOD-02 的「无变更重建两次 LLM=0」是**需求级验收用例**，不是优化项——计划里必须有自动化测试钉死。
- 注入三点全部是 fail-soft 追加；单独成相位过薄，故收进 125（research 相位划分理由）。
- 并发会话可能改动 `repo_router_v2.py`：本相位 CONTEXT/后续提交 **只 stage 本相位相关路径**，绝不顺手整理该冻结文件。
- Prior CONTEXT 锚点：121（图缓存/软边界/观测）、122（取图纪律/截断/双面）、123–124（编码链消费图工具）——本相位不重开这些决策。

</specifics>

<deferred>
## Deferred Ideas

- Leiden 默认算法 / `leidenalg` 进依赖树（触发条件满足后再做）
- 模块摘要作为 blueprint 第四打分分量或扩 `BLUEPRINT_ROUTE_WEIGHTS`（单独评审）
- Galaxy / 前端社区着色与模块摘要可视化
- 摘要写入 RepoSummary 向量文本的深度产品化（可选顺手并入除外）
- Process 的 intra/cross_community 分类（Phase 126 EXEC-02）
- `mcp/` npm 客户端为新工具补条目（本相位若未新增 MCP 工具名则无此项；若仅 adapter 接线既有 route 工具则不增工具）

None of the above blocks Phase 125 planning.

</deferred>
