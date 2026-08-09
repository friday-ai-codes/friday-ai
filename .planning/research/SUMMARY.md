# Project Research Summary

**Project:** Friday AI — 里程碑 v0.22.0 代码智能图分析升级（对标 GitNexus）
**Domain:** brownfield 增量 — graph-based code intelligence for AI coding agents（内存图服务 / impact / trace / detect_changes / 社区检测 + LLM 模块摘要 / 执行流 / rename_preview / Semgrep taint 门禁 / LSP 默认开启）
**Researched:** 2026-08-09
**Confidence:** HIGH

## Executive Summary

本里程碑的本质是：在既有 tree-sitter 符号图（`Symbol`/`CallEdge`/`Endpoint`/`CrossRepoApiCall`，SQL 存储）之上叠加一层**内存图分析服务**，把 GitNexus 已经验证过的 agent 消费范式（impact 深度分组 + 语义标签、逐边 confidence、风险四级、截断纪律、重名消歧、staleness 声明）落到 Friday 的服务端多用户场景，并在三个点上反超：跨仓 impact（穿 `CrossRepoApiCall` 边界，GitNexus 每仓独立图做不到）、LLM 模块摘要（GitNexus 只有目录启发式标签）、detect_changes 直接闭环进「需求→PR」编码链（容器提交前自查 + MR 描述自动生成）。行业交叉验证（Sourcegraph 双层精度、Aider 排序+预算截断、CodeQL 重路线反例）确认这条「tree-sitter 图 + 外购 Semgrep taint、不自研数据流」的路线与业界一致。

技术选型的结论是**几乎零新增 Python 依赖**：图引擎用已在依赖树的 networkx 3.6.1（rustworkx 没有社区检测算法，引入后仍须保留 networkx，得不偿失）；图缓存纯 stdlib（`OrderedDict` + `threading.Lock`，失效走 `last_indexed_commit_sha` 水位比对而非时间 TTL）；Semgrep 以独立 CLI 形态安装（`semgrep==1.172.*`，绝不进 server venv），门禁语义按 CE 免费版能力上限收敛（仅单函数内 taint），Pro 留 opt-in。架构上新增代码集中在 `server/services/code_graph/` 一个新包，持久化一律新模型（`SymbolCommunity`/`ProcessTrace`/`SecurityFinding`）软引用不加 FK，消费面全部复用既有 `McpToolView` / `@tool` / durable 队列 / `repo_mirror` 模式——集成点均已逐一在本仓代码中核实。

最大的风险不是造不出来，而是**精度与信任**：裸名调用边（`callee_symbol` 为空、只有 `callee_name` 兜底）若默认参与 impact 扩散，两跳后影响面就是整个仓库，工具信任直接破产——置信度分层透出（resolved / bare_name / cross_repo）必须是 P1 的输出契约而非优化项。其次是**运行时资源**：多 worker 各持一份内存图（10 万符号仓约 150–500MB/图），LRU 必须按字节预算而非条目数，并配 single-flight 建图锁与取图时水位校验。第三是**成本与稳定性**：社区检测结果漂移会让 LLM 模块摘要反复重生成，成员指纹（member fingerprint）跳过机制是需求级验收。Semgrep 门禁按「diff-aware + advisory 起步 + 异步不阻塞」铁律设计，否则重蹈「门禁两周内被关」的行业覆辙。

## 交叉冲突裁决：Louvain vs Leiden（社区检测确定性）

STACK 与 PITFALLS 存在一处需要显式裁决的矛盾：

- **STACK 的立场**：leidenalg 是 GPL-3.0（依赖的 python-igraph 为 GPL-2），本仓 MIT license 且分发 Docker 镜像，GPL 传染风险不可接受 ⇒ 否决 leidenalg，用 networkx 内置 `louvain_communities(seed=固定)`（BSD，零新增依赖）。networkx 3.6 的 `leiden_communities` 只有 dispatch 接口、无 CPU 默认实现，不可用。
- **PITFALLS 的立场**：networkx issue #6655（官方 wontfix）证实 Louvain 即使固定 seed，节点插入顺序不同结果仍会漂移；Leiden 在同 seed 下确定性且保证社区连通（Traag 2019），倾向用 Leiden。

**裁决：license 约束优先，采用 Louvain + 成员指纹稳定化；Leiden 列为触发条件升级项。**理由：

1. GPL 传染是**分发合规问题**，对一个 MIT + ghcr.io 预构建镜像分发的产品是硬约束；Louvain 漂移是**工程可缓解问题**——两者不对等。
2. 本场景社区只是 LLM 模块摘要的粗分组输入（摘要质量主要取决于 LLM 与提示词），不是用户可见的最终产物，Louvain 分区质量够用。
3. 漂移的实际危害（摘要反复重生成烧 LLM 成本、路由输入不稳定）可以在**消费侧**阻断：不依赖「划分逐节点一致」，只依赖「成员集近似不变 ⇒ 不重生成」。

**具体做法（写进 P-社区的需求级验收）：**

- 建图前节点按 `symbol_id` 排序 + `louvain_communities(seed=固定值)`——尽力压低漂移，但**不作为唯一保证**；
- 每个社区落库带 `member_fingerprint = hash(sorted(symbol_ids))`；重跑后新旧划分按成员 Jaccard 匹配对账，**只有 Jaccard < 0.8 的社区才重生成 LLM 摘要**，指纹不变直接跳过（LLM 调用数为 0 是「无变更重建两次」的验收用例）;
- 预处理：只对最大弱连通分量 + 规模 ≥ 5 符号的分量跑算法，孤立节点归目录兜底社区或标 `unclustered`，绝不给单节点社区发摘要；
- `SymbolCommunity.algorithm` 字段已预留（"louvain"/"leiden"），**Leiden 升级触发条件**：(a) 指纹跳过后摘要重生成率仍 > 阈值（如每次重建 > 20% 社区变动且人工核对为算法漂移而非真实代码变化）；或 (b) 部署方明确接受 GPL（如内部私有部署 opt-in 安装 leidenalg，运行时探测可用则切换）。升级只换 `community.py` 内一个函数调用，落库 schema 不变。

## Key Findings

### Recommended Stack

本里程碑 Python 侧**零新增依赖**：networkx 3.6.1 已在 `uv.lock`（llama-index 传递依赖），API 覆盖全部算法需求（反向 BFS / 最短路 / `louvain_communities`）；10万–100万边规模下构图秒级（缓存后摊销为零）、查询毫秒–百毫秒级。唯一真实风险是内存（100 万边约 0.5–1GB/图），靠属性瘦身 + 字节 LRU 管控。rustworkx 留 adapter seam 与明确升级触发条件（单仓 > 50 万边 / impact p95 > 2s / 缓存 > 2GB）。

**Core technologies:**
- networkx 3.6.1（已在依赖树）：内存图构建 + 全部图算法 — 零新增依赖，纯 Python wheel 天然兼容 Py3.14
- Python stdlib（`OrderedDict` + `threading.Lock`）：图缓存 LRU — 失效走 `last_indexed_commit_sha` 水位比对，不用时间 TTL，不引 cachetools
- Semgrep CLI 1.172.0（LGPL-2.1，独立 venv / `uv tool`，subprocess 调用）：MR diff taint 门禁 — 绝不进 server venv；CE 只有单函数内 taint，门禁承诺按此收敛，`SEMGREP_APP_TOKEN` 走加密凭证存储留 Pro opt-in；不要用 < 1.172 的版本（baseline 扫描误报 bug 刚修）
- gopls v0.23.0 + @vue/language-server 3.x：LSP 抽取后端 — **真正前置是改 `server/Dockerfile`**（当前 `python:3.14-slim` 无 Node 无 Go，kill-switch 打开也会全量回落 tree-sitter），镜像体积 +400–550MB 须进发布说明

### Expected Features

GitNexus 官方文档一手调研给出完整工具契约参照（输入参数、输出结构、截断策略、消歧协议均可直接照搬）。

**Must have (table stakes):**
- impact 深度分组 + 语义标签（d1=WILL BREAK / d2=LIKELY AFFECTED / d3=MAY NEED TESTING）+ 每边独立 confidence + reason + `minConfidence` 参数
- 风险四级（LOW/MEDIUM/HIGH/CRITICAL）判定标准写死可解释，不用 LLM 判
- 结果截断 + summary 计数 + `include_content` 默认关 — token 纪律是 agent 工具的生命线
- detect_changes 受影响符号清单（uid/name/type/filePath/changeType/linesChanged 六字段最小集）— agent 的行动指南，无它无法行动
- 重名消歧协议（uid 优先 + disambiguation 候选列表，绝不静默取第一个）+ 索引 staleness 声明（`as_of: <commit_sha>`）
- rename 只做只读 preview：图边 + 文本兜底双源、graph/text_search 二值 confidence、context 片段、动态引用限制显式声明
- Semgrep diff-aware（baseline 取 merge-base）+ severity 透出 + `nosemgrep` 通道 + 默认报告不阻断

**Should have (competitive):**
- 跨仓 impact（穿 `CrossRepoApiCall`，带 `cross_repo: true` + 独立置信档）— 反超 GitNexus 的核心点
- LLM 模块摘要（超越 heuristicLabel）喂 RepoRouter / 技术方案生成 — 消费端按 Aider 范式「排序 + token 预算截断」，不全量灌入
- detect_changes → MR 描述自动生成闭环（照 GitNexus `detect_impact` prompt 的 Changes/Affected Processes/Risk/Recommendations 四段结构）
- 执行流以 `Endpoint` 为确定性一等入口（优于 GitNexus 启发式打分），保留其 BFS 参数纪律（depth 10 / branching 4 / minSteps 3 / conf ≥ 0.5）
- impact-analysis / refactoring skills 进 `@friday-ai-codes/skills` 同源分发

**Defer (v2+):**
- detect_impact 式编排 MCP prompt — 等工具面稳定
- taint finding 台账化（主干 full scan + 状态机 + 跨分支 triage）— 平台级能力，等门禁用量验证
- 模块摘要进 Galaxy 可视化 — 展示层增值，不影响 agent 链路

### Architecture Approach

新增代码集中在 `server/services/code_graph/` 一个新包：纯算法（`impact.py`/`trace.py` 只吃 `DiGraph`）与 ORM（`loader.py` 独占，单次 `sync_to_async` 包裹批量 `values_list+iterator`）严格分离；消费面全部复用既有模式——MCP 壳照 `McpToolView`（PAT fail-closed + `RetrievalTrace` + snapshot 测试）、对话壳照 `@tool` 注册、容器自查走既有 `/api/mcp/tools/` HTTP 白名单加一条、重算走 durable `QUEUE_GRAPH` + `queueing_lock` 去重。diff 一律走 `repo_mirror`（base 强制 pin 到 `last_indexed_commit_sha` 与 Symbol 行号同源对齐），不依赖 MR webhook payload。⛔ `repo_router_v2.py` 是 §13.2 冻结面，模块摘要只在 adapter 层三点注入（blueprint_route evidence / charter signal 同款范式 / 调研 prompt）。

**Major components:**
1. `GraphService`（per-worker 内存 networkx 缓存）— 签名失效（仿 `GalaxyGraphCache.compute_signature`，水位 + 边构建代数双信号）+ 字节 LRU + single-flight 锁；一切图工具的共同地基
2. `impact/trace/change_detect/rename_preview` 内核 + MCP/对话双面薄壳 ×4 — 与 40+ 既有工具完全同构
3. `SymbolCommunity`/`ProcessTrace`/`SecurityFinding` 新模型 — 纯加表零改既有表，软引用不 FK（增量索引 per-file 删建 Symbol，FK 会被牵连），`built_at_sha` 落水位
4. `semgrep_scan.py` — server 容器内 subprocess 扫 `repo_mirror` worktree，durable 任务限 1–2 并发，与内存图零耦合可完全并行开发
5. 编码链挂点 — 容器提交前自查（prompt 驱动，v1 不做硬门禁）+ MR 描述两处拼接点（workflow 链 `_finalize_and_notify` / MCP 链 `merge_request_service`），均 fail-soft

### Critical Pitfalls

1. **裸名边假阳性灾难** — 默认只走 `callee_symbol IS NOT NULL` 的解析边 + `CrossRepoApiCall`；置信度分层透出（resolved / bare_name / cross_repo）是输出契约；裸名边仅 `include_low_confidence=true` 显式开启且加同目录/qualifier/常见名黑名单三道过滤；索引完成时统计解析率，低于阈值在输出头部声明
2. **多 worker 内存放大 + 构建风暴 + 失效窗口** — 字节预算 LRU（不按条目数）+ per-key single-flight 建图锁 + **取图时**（不只建图时）水位校验 + 超大仓不进缓存走按需子图降级，四件套同相位落齐
3. **社区漂移 ⇒ LLM 成本失控** — 见上文冲突裁决：member fingerprint + Jaccard 对账跳过重生成是需求级验收；「无变更重建两次 LLM 调用数为 0」是验收用例
4. **detect_changes 行号错位** — diff 强制锚定 `last_indexed_commit_sha`；`git diff -M` 开 rename 检测（否则纯 rename PR 误报满屏）；format diff 降级 `formatting_only`、超阈值切文件级摘要
5. **Semgrep 门禁死亡螺旋** — diff-aware 只报增量 + advisory 起步不阻断 + 异步不挂 MR 创建同步路径 + 超时 fail-open 显式标注，四项同相位必选不可拆
6. **越权与 exclusion 漏接** — 鉴权/`is_excluded` 拦截做进图服务读取层统一收口（所有上层工具天然继承）；跨仓 impact 每穿一仓复核权限，未授权整仓折叠 `redacted_repository`；`purge_file` 从五面扩到六面

## Implications for Roadmap

建议 8 个相位，依赖关系遵循 ARCHITECTURE 的 build order（Wave 0–3），三条独立线（图地基 / Semgrep / LSP）可并行开工：

### Phase 1: 内存图服务基座（P-基座）
**Rationale:** 五个图功能的共同依赖，必须最先；且安全/精度的两大横切纪律（边准入 + 读取层鉴权/exclusion 收口）必须做进地基，让上层工具天然继承
**Delivers:** `GraphService` + `loader.py` + 签名失效 + 字节 LRU + single-flight + impact/trace 纯函数 + 边准入词表与置信度枚举 + exclusion/权限统一拦截
**Addresses:** 一切图工具的地基（FEATURES P1）
**Avoids:** Pitfall 2（缓存四件套）、Pitfall 1（边准入）、Pitfall 8（读取层收口）

### Phase 2: impact / trace 工具面（P-impact）
**Rationale:** 里程碑核心承诺，agent「改前自查」主工具；MCP + 对话双面接线模式在此相位定型，后续工具照抄
**Delivers:** `impact_analysis` / `trace_call_path` 双面接线（8 壳文件 + schema snapshot 测试）+ 深度分组 + 置信度分层输出 + 跨仓边 + golden 符号集精度回归
**Uses:** networkx 反向 BFS / 最短路；`McpToolView` + `@tool` 既有模式
**Implements:** 分析层 → 消费面完整链路首通；断链标注词表在此相位先定（P-执行流复用）

### Phase 3: detect_changes 工具本体（P-detect）
**Rationale:** 只依赖 Phase 1/2 基建；与链路集成（Phase 4）风险面不同，拆开交付
**Delivers:** `repo_mirror.diff_mirror` helper + diff 行区间 × Symbol 区间定位 + 批量 impact + 符号清单输出 + rename 检测 + 水位锚定 + stale 声明
**Avoids:** Pitfall 5（锚定 + `-M` + 噪声压制是功能正确性，第一批落）

### Phase 4: 编码链闭环（detect_changes 集成）
**Rationale:** 「提交前自查 + MR 描述」是 Friday 区别于 GitNexus 的落点，也是本里程碑对用户最可感知的价值；动 task/workflow 两条链，单独相位控风险
**Delivers:** 容器工具白名单 + system prompt 自查指引（v1 提示不阻断）+ workflow/MCP 两处 MR 描述「## 影响面」fail-soft 挂点
**Addresses:** detect_changes → MR 描述闭环（FEATURES 差异化项）

### Phase 5: 社区检测 + LLM 模块摘要（P-社区）
**Rationale:** GitNexus 索引管线中社区先于执行流（Process 需要 community 归属）；摘要消费接线依赖社区落库
**Delivers:** `SymbolCommunity` 模型 + Louvain（seed + 节点排序）+ member fingerprint / Jaccard 对账跳过 + 孤立节点预处理 + `module_summary.py`（新 `call_source` 枚举）+ 摘要三注入点（blueprint_route evidence / 对话·MCP 路由信号 / 调研 prompt）
**Uses:** `louvain_communities`（冲突裁决见上）；durable `QUEUE_GRAPH` defer
**Avoids:** Pitfall 3（指纹跳过是需求级验收）；⛔ 不动 `repo_router_v2.py` 冻结面

### Phase 6: 执行流追踪（P-执行流）
**Rationale:** 依赖社区结果（intra/cross_community 分类）；随后回填 detect_changes/impact 的 `affected_processes` 叙事层
**Delivers:** `ProcessTrace` 模型 + `Endpoint` 确定性入口正向追踪 + 三重预算硬上限（depth/nodes/fanout）+ 环显式标注 + async 断链标注（`boundary: async_dispatch`）
**Avoids:** Pitfall 4（预算与环处理；存摘要不存全展开节点集）

### Phase 7: rename_preview + skills 固化
**Rationale:** 独立性强，何时插入均可；工具面稳定后一并固化 impact-analysis / refactoring skills
**Delivers:** 图引用 + grep 兜底双源清单（grep 半边走既有已拦截的 grep 路径）+ graph/text_search 二值 confidence + 按文件分组 + skills 进 `@friday-ai-codes/skills`

### Phase 8: Semgrep taint 门禁（P-semgrep，可与 Phase 2 起并行）
**Rationale:** 与内存图零耦合，独立轨道任何时点可插入；但 diff-aware + advisory + 异步化三件套必须同相位不可拆
**Delivers:** Dockerfile 装 semgrep 二进制（独立于 server venv）+ `semgrep_scan.py` + `SecurityFinding` 模型（snippet 过 `redact_secrets_in_text`）+ durable 任务限并发 + MR 描述「## 安全扫描」段 + CE 单函数 taint 边界如实声明 + Pro opt-in 配置面
**Avoids:** Pitfall 6（门禁死亡螺旋）

**LSP 默认开启（P-LSP）** 建议本里程碑做成「降低开启门槛」而非无条件翻默认：Dockerfile 补 Node 22 + volar + Go 工具链 + gopls、依赖健康探测、孤儿进程收口、索引耗时基准——默认值翻转留给基准数据说话（gopls/tree-sitter 抽取结果有差异，切换会改变 Endpoint/Symbol 产出，须灰度）。可作为独立小相位或并入基建相位，但**不与 Phase 5/6 并行上线**（同时引入多个内存大户会让 OOM 归因困难）。

### Phase Ordering Rationale

- **Phase 1 绝对先行**：五个图功能全部踩在图缓存上，且边准入/鉴权/exclusion 三个横切纪律后补的代价是「必有一个工具漏接」（PITFALLS 的技术债表将其列为 never acceptable）
- **detect_changes 拆「本体」与「链路集成」两相位**：前者只依赖图基建，后者要动 task 容器与 workflow 两条链，风险面与回归面完全不同
- **社区先于执行流**：GitNexus 索引管线的既证顺序；Process 的 intra/cross_community 分类依赖社区归属
- **Semgrep / LSP 两条独立线**：与图功能零耦合，可随时并行插入，用于平衡各 wave 的工作量
- **摘要注入放在社区相位内而非独立相位**：注入点全部是 adapter 层 fail-soft 追加（v0.8 / charter signal 既有范式照抄），单独成相位过薄

### Research Flags

Phases likely needing deeper research during planning:
- **Phase 5（社区+摘要）:** Louvain 稳定化的经验阈值（Jaccard 0.8、最小分量规模 5）为 MEDIUM 置信，相位内需用本仓真实图数据校准；摘要注入 blueprint_route 若要参与打分（而非仅 evidence），涉及权重 schema 变更须单独评审
- **Phase 6（执行流）:** depth/nodes/fanout 默认值为经验值，需在大仓实测校准；async 断链模式词表（`sync_to_async`/`defer_task`/`.delay(`/`group_send`）需在本仓穷举核实
- **P-LSP:** 索引耗时基准与灰度策略本身就是调研型工作（Wave 0 C 线）

Phases with standard patterns (skip research-phase):
- **Phase 2/3/4/7:** 工具双面接线、diff 通路、MR 描述挂点、grep 兜底全部有本仓既有先例逐文件核实在案（ARCHITECTURE 的集成清单精确到行号）
- **Phase 8（Semgrep）:** 官方文档对 diff-aware / baseline / 超时 / 分级实践给足了成熟范式，照方抓药

## Confidence Assessment

| Area | Confidence | Notes |
|------|------------|-------|
| Stack | HIGH | 所有依赖版本与 Py3.14 wheel 可用性经 PyPI/官方 release notes 核实；性能数字 MEDIUM（官方 benchmark + 第三方实测，未本仓复现） |
| Features | HIGH | GitNexus 全部工具契约来自官方 Mintlify docs 一手引用；Semgrep/Sourcegraph/Aider 均官方文档或源码 |
| Architecture | HIGH | 全部集成点直接读本仓代码核实，文中路径与行号真实存在 |
| Pitfalls | HIGH | 核心结论有代码事实或官方文档/论文佐证；个别经验阈值 MEDIUM 需相位内实测校准 |

**Overall confidence:** HIGH

### Gaps to Address

- **Louvain 漂移的实际幅度**：issue #6655 证实理论上会漂移，但本仓图（节点排序 + 固定 seed 后）的实际漂移率未知——Phase 5 首个交付物应包含「同一仓重建两次的 Jaccard 对账数据」，用真实数据决定是否触发 Leiden 升级条件
- **networkx 内存放大系数**：150–500MB/图为经验估算区间，Phase 1 验收需在本仓最大仓实测并据此定 `CODE_GRAPH_CACHE_MAX` 默认值
- **裸名边解析率现状**：per repo per language 的 `callee_symbol` 回填率未统计，Phase 1 应先出这个指标（它决定 impact 输出「偏保守」声明的阈值与 grep 兜底的必要性）
- **LSP 切换的抽取产物差异面**：`test_go_extractor.py` 已证实 gopls 与 tree-sitter 结果不同，但差异全貌未量化——P-LSP 的基准工作需产出 golden 对比
- **`mcp` npm 包跨仓欠债**：服务端四个新工具先齐，npm 客户端另批（v0.20 已有同款缺口在案），roadmap 需显式记账

## Sources

### Primary (HIGH confidence)
- 本仓代码一手核实：`server/uv.lock`、`server/Dockerfile`、`server/codegraph/`（models/galaxy/lsp）、`server/code_relations/tasks.py`、`server/services/`（indexer/repo_mirror/charter_route_signal/process_runtime）、`server/mcp_tools/`、`server/agents/tools/`、`server/durable/`、`task/core/`、`server/friday/settings.py` — 全部集成点与既有契约
- GitNexus 官方文档（Mintlify，2026-08-09 抓取）+ GitHub README — 全部工具契约、Clusters/Processes、skills 分发、detect_impact prompt
- Semgrep 官方 docs — CE/Pro taint 边界、diff-aware baseline、Rules License、CLI 语义、1.172.0 bugfix
- PyPI / 官方 release notes：networkx 3.6.1、rustworkx 0.18.0（含 issue #1141）、leidenalg 0.12.0（GPL-3.0）、semgrep 1.172.0、gopls v0.23.0
- networkx issue #6655（Louvain 同 seed 非确定，官方 wontfix）；Traag, Waltman & van Eck 2019（Leiden 连通性保证）
- Aider 官方 repomap 文档 + `aider/repomap.py` 源码；Go 官方博客与 golang/go#45457（gopls 内存特征）

### Secondary (MEDIUM confidence)
- rustworkx JOSS 论文 + 官方 benchmark — 3x–100x 提速数字（未本仓复现）
- Sourcegraph docs（precise vs search-based 双层精度）— 与置信度分层设计交叉印证
- 经验性阈值（Jaccard 0.8、解析率 60%、depth/nodes/fanout 默认值、内存放大系数）— 需相位内实测校准

---
*Research completed: 2026-08-09*
*Ready for roadmap: yes*
