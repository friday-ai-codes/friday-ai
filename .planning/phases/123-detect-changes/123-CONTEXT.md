# Phase 123: detect_changes 工具本体 - Context

**Gathered:** 2026-08-10
**Status:** Ready for planning

<domain>
## Phase Boundary

本相位交付 **detect_changes 工具本体**（DIFF-01 / DIFF-02）：用户/agent 对分支（或 MR）diff 一键得到「这次改动碰了哪些符号、波及多大」——受影响符号清单（`changeType` / 行数 / `file:line`）+ 批量 impact，且 **diff base 强制锚定 `last_indexed_commit_sha`**，保证行区间与 `Symbol` 行号同源；`git diff -M` 识别 rename，纯 rename PR 不产生满屏误报；输出带索引 staleness 声明（`as_of` commit）。

本相位**定型** diff 通路（`repo_mirror` + `diff_mirror`）与「定位受影响符号 → 复用 Phase 122 `run_impact`」的编排，并按 D-21 双面薄壳暴露（MCP + 对话）。

**明确不在本相位：**
- 编码任务容器白名单 / system prompt 自查指引、MR 描述「## 影响面」挂点（Phase 124 / DIFF-03·04）
- `affected_processes` 叙事回填（Phase 126 / EXEC-03；本相位预留空数组字段位，与 122 一致）
- `mcp/` git submodule 客户端补条目（沿用 122 D-27）
- ⛔ 不改 `server/codegraph/services/repo_router_v2.py`（冻结至 Phase 125 MOD-04）
- 零不必要 migration；不新增持久化模型

</domain>

<decisions>
## Implementation Decisions

### Area 1: Diff 基线锚定 / compare+base_ref / 拒绝条件

- **D-01 — diff 行区间的 base 强制 = `Repository.last_indexed_sha` 同源水位 `last_indexed_commit_sha`**。`git diff` 一律 `last_indexed_commit_sha…head`（`--unified=0`），⛔ 禁止用工作树、远端默认分支 tip、或未 pin 的「当前 HEAD」做行号交叠基线。理由：`Symbol.start_line/end_line` 是索引水位时刻抽取的；基线漂移即行号错位（research Pitfall 5 / DIFF-01 明文）。通路走 `repo_mirror.ensure_mirror_commit` pin 两端 sha，再新增 `diff_mirror` helper（调研 ARCHITECTURE Pattern 3；复用 `_run_git`）。
- **D-02 — `compare`（或 branch）= head；`base_ref` 是 MR 语义参数，不替换索引水位做行号交叠**。MR 场景：`head = compare`；输出声明里同时透出调用方的 `base_ref`（若有）与实际锚定的 `as_of`/`diff_base_sha=last_indexed_commit_sha`，让 agent 看见「MR 目标 ≠ 索引水位」时的可信度。⛔ 不得因调用方传了 `base_ref` 就改用 `base_ref…compare` 去跟 Symbol 求交。
- **D-03 — 硬拒绝（明确 error，不静默错答）**：仓未索引 / `last_indexed_commit_sha` 为空；mirror 无法 fetch 到 base 或 head；ACL 失败（`GraphAccessDenied` / `ensure_repository_readable`）。`GraphError` 子类由壳层翻译（沿用 122 D-03），⛔ 不得 catch 成空「无改动」。
- **D-04 — 索引落后不单独硬拒**：`behind_commits` 再大也先算（若 mirror/对象可得），用 `staleness_payload` 醒目声明 + 建议重索引；agent 自行判断可信度（成功标准 3）。仅当对象不可得（fetch 失败）才走 D-03。可选阈值（如 behind > 200）只加强 declaration 文案，不改变「算出结果 + 声明 stale」的契约。

### Area 2: 符号交叠算法与 rename 处理

- **D-05 — 交叠算法 = unified hunk 行区间 × `Symbol` 行区间求交**。在索引水位对应的 **old/base 侧**行号上匹配（`start_line/end_line` 与 hunk 的删除/上下文区间相交即命中）。查询口径对齐调研：`Symbol` 按 `(repository, branch_name, file_path)` + 行区间过滤；exclusion 经 Phase 121 读取层 / 既有 matcher fail-closed，排除文件不出现在清单。纯新增行（无 old 侧行可交）若无法落到既有 Symbol，记文件级 `added` 摘要条目，⛔ 不伪造符号 uid。
- **D-06 — rename 必须 `git diff -M` / `--find-renames`**（与 indexer 既有 `--find-renames` 一致）。检测到 rename：`changeType=renamed`，按「旧路径符号 → 新路径」映射一条逻辑变更；⛔ 禁止默认 delete+add 双列表（纯 rename PR 验收：不得满屏误报，DIFF-02 / 成功标准 2）。
- **D-07 — 噪声降级 `formatting_only`**：hunk 在 strip 空白后实质相同（含 import 顺序类启发式，细节 Claude's Discretion）→ `changeType=formatting_only`，**不**进入批量 impact 种子集。真实语义改动仍走 modified/added/deleted/renamed。
- **D-08 — 删除文件 / 大改阈值**：整文件 delete → 旧路径符号 `changeType=deleted`，仍可作为 impact 种子（谁依赖被删符号）。单次受影响符号数超过阈值（初值 **100**，可 settings/env 化）时切换为**文件级摘要** + 明确 `truncated`/`not_expanded` 说明，**跳过**逐符号 batch impact（Pitfall 5 噪声压制；防构建风暴）。

### Area 3: 批量 impact 编排

- **D-09 — 批量 impact 必须复用 Phase 122 共享编排 `run_impact`（或其内核 `analyze_impact` + 同一信封约定）**，⛔ 不得在 detect_changes 内重写反向 BFS / 风险分级 / 跨仓一跳。detect_changes 编排层负责：diff → 受影响符号清单 →（阈值内）逐符号或按 uid 调用 impact → 汇总。跨仓 / 风险 / 截断语义全部继承 122（含 D-15/D-16/D-25/D-29）。
- **D-10 — 默认 impact 参数与 `impact_analysis` 工具一致**：`max_depth=3`、`min_confidence=1.0`（默认只走 resolved）、`include_low_confidence=False`、`limit=200`；壳层可透传覆盖。种子一律传 `symbol_id`（交叠已定位到具体 Symbol），避开 122 D-19 重名主路径。
- **D-11 — 同仓 batch 顺序执行（或极小有界并发）**：同一 `(repository, branch)` 共享一张图，single-flight 已防构建风暴；默认**顺序**调用 `run_impact` 最稳。若做并发，上限 ≤3 且不得跨仓扇出风暴；具体并发度 Claude's Discretion，但验收不得因 batch 触发多图并行首建打爆 DB。
- **D-12 — impact 子结果 fail-soft**：单个符号 impact 失败（对端仓 unavailable、超时等）不推翻整个 detect_changes；该符号条目带 `impact_error` / `unavailable_reason`，其余照常。整体仍带 staleness + degradation。`affected_processes` 字段预留为 `[]`（Phase 126）。

### Area 4: 双面接线、staleness / 失败形态、输出契约

- **D-13 — 双面严格照抄 122 D-21**：新增共享编排入口（建议名 `run_detect_changes`，落在 `server/services/code_graph_tools.py` 旁路、与 `run_impact`/`run_trace` 同级）；MCP 壳 `McpToolView`（PAT fail-closed、`RetrievalTrace`、schema snapshot）；对话壳 `agents/tools` `@tool` + schema。⛔ 逻辑不许在壳里分叉。⛔ 不碰 `mcp/` submodule（122 D-27）；SUMMARY 更新 snapshot 漂移计数即可。
- **D-14 — 输出信封复用 122**：`ok` / `error_code` / `error`；成功时必含 `staleness`（`staleness_payload`）+ `degradation`（`degradation_payload`，含数值 `resolution_rate`）。`as_of` = `last_indexed_commit_sha`。另透出 `diff_base_sha` / `diff_head_sha`（及可选 `base_ref`）供 agent 核对锚定。
- **D-15 — 受影响符号最小字段集（GitNexus / research 六字段 + 定位）**：`uid` / `name` / `symbol_type` / `file_path` / `changeType` / `lines_changed`，外加 `file:line`（`start_line` 或命中行）。`changeType` 封闭枚举：`added` | `modified` | `deleted` | `renamed` | `formatting_only`。清单按 **文件分组**；batch impact 结果挂在符号下或并行 `impacts[]`（键含 `symbol_id`），截断 summary 计数必给。
- **D-16 — 模块落点**：交叠/rename/formatting 纯逻辑优先 `server/services/code_graph/detect_changes.py`（或 `change_detect.py`）；`diff_mirror` 在 `server/services/repo_mirror.py`；编排 + staleness 组装在 `code_graph_tools.py`。取图仍只经 `from services.code_graph import get_graph_service` barrel（122 D-02）。观测：`component="code_graph"`；工具入口 `category=caller`，hunk 解析循环 `category=sampling`；事件名静态字面量；凭证/路径日志不泄漏 token。

### Claude's Discretion

- `formatting_only` 启发式的具体实现（空白 strip / import 排序比对）、rename 相似度阈值是否显式传给 `-M`。
- batch impact 是「顺序 for-loop」还是「有界 gather」；文件级摘要在超阈值时的字段命名细节。
- MCP/对话工具参数命名（`compare` vs `head_ref`）与 markdown 渲染措辞，只要双面同源且满足 D-02/D-15。
- 测试组织（内核单测 vs mirror 集成 fixture）；不要求本相位做前端 UI。

</decisions>

<code_context>
## Existing Code Insights

### Reusable Assets

- **Phase 121 图地基**：`server/services/code_graph/`（`get_graph` / `GraphMeta` / exclusion+ACL 收口 / `last_indexed_commit_sha` 进签名）。
- **Phase 122 工具编排**：`server/services/code_graph_tools.py` — `run_impact` / `run_trace` / `staleness_payload` / `degradation_payload` / `fetch_graph_for_tool`；MCP `ImpactAnalysisView` / `TraceCallPathView`；对话 `agents/tools/graph_tools.py`。
- **Symbol 行号**：`server/codegraph/models.py::Symbol` — `start_line` / `end_line` / `file_path` / `branch_name`。
- **Mirror / git**：`server/services/repo_mirror.py` — `ensure_mirror_commit` / `MirrorSnapshot` / `_run_git`（待加 `diff_mirror`）；indexer 侧已有 `--name-status --find-renames` 与 `FileDiff`/`DiffAction.RENAME`（`server/services/indexer.py`）可对照，但 detect_changes 主通路按调研走 mirror + unified hunk，不依赖 MR webhook payload。
- **Freshness**：`repositories.freshness_service.compute_freshness_status` + `Repository.behind_commits`（请求路径不起 git 算距离，沿用 122 D-22）。

### Established Patterns

- **双面薄壳**：内核/编排出结构化 dict；MCP JSON 原样；对话侧渲染；失败语义 `ok=False` + `error_code`（含 `ambiguous_symbol` 成功响应形态）。
- **观测**：`component="code_graph"`；caller vs sampling；best-effort 留痕不反噬。
- **测试**：`server/tests/services/code_graph/` + `server/tests/mcp_tools/` snapshot；双面哨兵（122 已含 impact+trace，本相位加 detect_changes）。

### Integration Points

- NEW：`services/code_graph/detect_changes.py`（交叠内核）+ `repo_mirror.diff_mirror` + `code_graph_tools.run_detect_changes`
- MCP：`mcp_tools/views.py` + `urls.py` + serializers/snapshot
- Agents：`agents/tools/graph_tools.py`（或并列模块）+ schemas + `__init__` / chat 白名单
- ⛔ 不改：`codegraph/services/repo_router_v2.py`；`mcp/` submodule
- Phase 124 将挂：task `knowledge_allowed_tools` 白名单、MR description fail-soft（本相位只保证工具可被 PAT 调用）

</code_context>

<specifics>
## Specific Ideas

- research SUMMARY / PITFALLS 对 detect_changes 的三件套视为**功能正确性**而非优化：① 锚定 `last_indexed_commit_sha`；② `git diff -M`；③ `formatting_only` + 超阈值文件级摘要。本相位第一批必须落地。
- GitNexus 受影响符号六字段最小集可直接照搬形状；批量 impact 形状复用 122 输出，避免第三套方言。
- Phase 122 VERIFICATION 已预留 `affected_processes: []`；本相位同样预留，不实现 EXEC-03。
- 并发会话有其他 WIP：提交 CONTEXT 时**只 stage 本文件**。

</specifics>

<deferred>
## Deferred Ideas

- **DIFF-03 / DIFF-04（Phase 124）** — 容器提交前自查白名单 + prompt；MR 描述 Changes/Affected/Risk/Recommendations 四段自动附带。
- **EXEC-03 / Phase 126** — `affected_processes` 回填（本相位空数组占位）。
- **`detect_impact` 式 MCP 编排 prompt** — REQUIREMENTS Future；等工具面稳定（v2+）。
- **`mcp` npm 包补条目并发版** — 沿用 122 D-27，本相位不改 submodule。
- **formatting / 符号数阈值的生产校准** — 初值 100；上线后可 env 化调参。
- **MR webhook payload 作 diff 来源** — 调研已否决为主通路；若未来需要，同一交叠内核换 diff 输入即可。

</deferred>
