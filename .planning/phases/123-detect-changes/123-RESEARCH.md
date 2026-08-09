# Phase 123: detect_changes 工具本体 - Research

**Researched:** 2026-08-10
**Domain:** 代码智能图分析 / git diff × Symbol 交叠 / MCP+对话双面工具
**Confidence:** HIGH

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions

#### Area 1: Diff 基线锚定 / compare+base_ref / 拒绝条件

- **D-01 — diff 行区间的 base 强制 = `Repository.last_indexed_sha` 同源水位 `last_indexed_commit_sha`**。`git diff` 一律 `last_indexed_commit_sha…head`（`--unified=0`），⛔ 禁止用工作树、远端默认分支 tip、或未 pin 的「当前 HEAD」做行号交叠基线。理由：`Symbol.start_line/end_line` 是索引水位时刻抽取的；基线漂移即行号错位（research Pitfall 5 / DIFF-01 明文）。通路走 `repo_mirror.ensure_mirror_commit` pin 两端 sha，再新增 `diff_mirror` helper（调研 ARCHITECTURE Pattern 3；复用 `_run_git`）。
- **D-02 — `compare`（或 branch）= head；`base_ref` 是 MR 语义参数，不替换索引水位做行号交叠**。MR 场景：`head = compare`；输出声明里同时透出调用方的 `base_ref`（若有）与实际锚定的 `as_of`/`diff_base_sha=last_indexed_commit_sha`，让 agent 看见「MR 目标 ≠ 索引水位」时的可信度。⛔ 不得因调用方传了 `base_ref` 就改用 `base_ref…compare` 去跟 Symbol 求交。
- **D-03 — 硬拒绝（明确 error，不静默错答）**：仓未索引 / `last_indexed_commit_sha` 为空；mirror 无法 fetch 到 base 或 head；ACL 失败（`GraphAccessDenied` / `ensure_repository_readable`）。`GraphError` 子类由壳层翻译（沿用 122 D-03），⛔ 不得 catch 成空「无改动」。
- **D-04 — 索引落后不单独硬拒**：`behind_commits` 再大也先算（若 mirror/对象可得），用 `staleness_payload` 醒目声明 + 建议重索引；agent 自行判断可信度（成功标准 3）。仅当对象不可得（fetch 失败）才走 D-03。可选阈值（如 behind > 200）只加强 declaration 文案，不改变「算出结果 + 声明 stale」的契约。

#### Area 2: 符号交叠算法与 rename 处理

- **D-05 — 交叠算法 = unified hunk 行区间 × `Symbol` 行区间求交**。在索引水位对应的 **old/base 侧**行号上匹配（`start_line/end_line` 与 hunk 的删除/上下文区间相交即命中）。查询口径对齐调研：`Symbol` 按 `(repository, branch_name, file_path)` + 行区间过滤；exclusion 经 Phase 121 读取层 / 既有 matcher fail-closed，排除文件不出现在清单。纯新增行（无 old 侧行可交）若无法落到既有 Symbol，记文件级 `added` 摘要条目，⛔ 不伪造符号 uid。
- **D-06 — rename 必须 `git diff -M` / `--find-renames`**（与 indexer 既有 `--find-renames` 一致）。检测到 rename：`changeType=renamed`，按「旧路径符号 → 新路径」映射一条逻辑变更；⛔ 禁止默认 delete+add 双列表（纯 rename PR 验收：不得满屏误报，DIFF-02 / 成功标准 2）。
- **D-07 — 噪声降级 `formatting_only`**：hunk 在 strip 空白后实质相同（含 import 顺序类启发式，细节 Claude's Discretion）→ `changeType=formatting_only`，**不**进入批量 impact 种子集。真实语义改动仍走 modified/added/deleted/renamed。
- **D-08 — 删除文件 / 大改阈值**：整文件 delete → 旧路径符号 `changeType=deleted`，仍可作为 impact 种子（谁依赖被删符号）。单次受影响符号数超过阈值（初值 **100**，可 settings/env 化）时切换为**文件级摘要** + 明确 `truncated`/`not_expanded` 说明，**跳过**逐符号 batch impact（Pitfall 5 噪声压制；防构建风暴）。

#### Area 3: 批量 impact 编排

- **D-09 — 批量 impact 必须复用 Phase 122 共享编排 `run_impact`（或其内核 `analyze_impact` + 同一信封约定）**，⛔ 不得在 detect_changes 内重写反向 BFS / 风险分级 / 跨仓一跳。detect_changes 编排层负责：diff → 受影响符号清单 →（阈值内）逐符号或按 uid 调用 impact → 汇总。跨仓 / 风险 / 截断语义全部继承 122（含 D-15/D-16/D-25/D-29）。
- **D-10 — 默认 impact 参数与 `impact_analysis` 工具一致**：`max_depth=3`、`min_confidence=1.0`（默认只走 resolved）、`include_low_confidence=False`、`limit=200`；壳层可透传覆盖。种子一律传 `symbol_id`（交叠已定位到具体 Symbol），避开 122 D-19 重名主路径。
- **D-11 — 同仓 batch 顺序执行（或极小有界并发）**：同一 `(repository, branch)` 共享一张图，single-flight 已防构建风暴；默认**顺序**调用 `run_impact` 最稳。若做并发，上限 ≤3 且不得跨仓扇出风暴；具体并发度 Claude's Discretion，但验收不得因 batch 触发多图并行首建打爆 DB。
- **D-12 — impact 子结果 fail-soft**：单个符号 impact 失败（对端仓 unavailable、超时等）不推翻整个 detect_changes；该符号条目带 `impact_error` / `unavailable_reason`，其余照常。整体仍带 staleness + degradation。`affected_processes` 字段预留为 `[]`（Phase 126）。

#### Area 4: 双面接线、staleness / 失败形态、输出契约

- **D-13 — 双面严格照抄 122 D-21**：新增共享编排入口（建议名 `run_detect_changes`，落在 `server/services/code_graph_tools.py` 旁路、与 `run_impact`/`run_trace` 同级）；MCP 壳 `McpToolView`（PAT fail-closed、`RetrievalTrace`、schema snapshot）；对话壳 `agents/tools` `@tool` + schema。⛔ 逻辑不许在壳里分叉。⛔ 不碰 `mcp/` submodule（122 D-27）；SUMMARY 更新 snapshot 漂移计数即可。
- **D-14 — 输出信封复用 122**：`ok` / `error_code` / `error`；成功时必含 `staleness`（`staleness_payload`）+ `degradation`（`degradation_payload`，含数值 `resolution_rate`）。`as_of` = `last_indexed_commit_sha`。另透出 `diff_base_sha` / `diff_head_sha`（及可选 `base_ref`）供 agent 核对锚定。
- **D-15 — 受影响符号最小字段集（GitNexus / research 六字段 + 定位）**：`uid` / `name` / `symbol_type` / `file_path` / `changeType` / `lines_changed`，外加 `file:line`（`start_line` 或命中行）。`changeType` 封闭枚举：`added` | `modified` | `deleted` | `renamed` | `formatting_only`。清单按 **文件分组**；batch impact 结果挂在符号下或并行 `impacts[]`（键含 `symbol_id`），截断 summary 计数必给。
- **D-16 — 模块落点**：交叠/rename/formatting 纯逻辑优先 `server/services/code_graph/detect_changes.py`（或 `change_detect.py`）；`diff_mirror` 在 `server/services/repo_mirror.py`；编排 + staleness 组装在 `code_graph_tools.py`。取图仍只经 `from services.code_graph import get_graph_service` barrel（122 D-02）。观测：`component="code_graph"`；工具入口 `category=caller`，hunk 解析循环 `category=sampling`；事件名静态字面量；凭证/路径日志不泄漏 token。

### Claude's Discretion

- `formatting_only` 启发式的具体实现（空白 strip / import 排序比对）、rename 相似度阈值是否显式传给 `-M`。
- batch impact 是「顺序 for-loop」还是「有界 gather」；文件级摘要在超阈值时的字段命名细节。
- MCP/对话工具参数命名（`compare` vs `head_ref`）与 markdown 渲染措辞，只要双面同源且满足 D-02/D-15。
- 测试组织（内核单测 vs mirror 集成 fixture）；不要求本相位做前端 UI。

### Deferred Ideas (OUT OF SCOPE)

- **DIFF-03 / DIFF-04（Phase 124）** — 容器提交前自查白名单 + prompt；MR 描述 Changes/Affected/Risk/Recommendations 四段自动附带。
- **EXEC-03 / Phase 126** — `affected_processes` 回填（本相位空数组占位）。
- **`detect_impact` 式 MCP 编排 prompt** — REQUIREMENTS Future；等工具面稳定（v2+）。
- **`mcp` npm 包补条目并发版** — 沿用 122 D-27，本相位不改 submodule。
- **formatting / 符号数阈值的生产校准** — 初值 100；上线后可 env 化调参。
- **MR webhook payload 作 diff 来源** — 调研已否决为主通路；若未来需要，同一交叠内核换 diff 输入即可。
</user_constraints>

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| DIFF-01 | 对分支 diff（base 锚定 `last_indexed_commit_sha`）执行 detect_changes，获得受影响符号清单（changeType / 行数 / file:line）与批量 impact | Pattern 3 `diff_mirror` + 交叠内核 + `run_detect_changes` 调 `run_impact`；见 Architecture Patterns / Code Examples |
| DIFF-02 | 支持 compare + base_ref（MR diff）；`git diff -M` 识别 rename，纯 rename 不误报 | D-02/D-06；indexer `_parse_git_diff_output` R* 对照；纯 rename 验收用例 |
</phase_requirements>

## Summary

Phase 123 在 Phase 121 图地基与 Phase 122 `run_impact` / 双面薄壳之上，交付 **detect_changes**：用 mirror 上的 **tree-to-tree** `git diff --unified=0 --find-renames <last_indexed_commit_sha> <head>` 解析 hunk，与 **base 分支** `Symbol` 行区间求交，产出受影响符号清单，再（阈值内）顺序复用 `run_impact` 做批量影响面。零新 Python 依赖；不改 `mcp/` submodule、不碰 `repo_router_v2.py`、无 migration。

本相位最容易写错的三件事已在 CONTEXT 锁定，研究进一步核实了实现细节：① **diff 必须 two-dot 树对树**（左端 = 索引水位），不能用三-dot merge-base 偷偷换左端；② **交叠坐标是 base `Symbol`（`branch_name=""`）**，feature overlay 的行号是另一棵树，不能拿来跟 old-side hunk 求交；③ **rename / formatting_only / >100 截断**是功能正确性，不是优化。

**Primary recommendation:** 按三层落地——`repo_mirror.diff_mirror`（git）→ `code_graph/detect_changes.py`（纯交叠）→ `code_graph_tools.run_detect_changes`（ORM + batch `run_impact` + 信封）→ MCP/对话双面薄壳照抄 122；v1 图与交叠一律走 base 水位坐标。

## Architectural Responsibility Map

| Capability | Primary Tier | Secondary Tier | Rationale |
|------------|-------------|----------------|-----------|
| Diff 获取（pin sha + `git diff -M -U0`） | API / Backend (`repo_mirror`) | — | 已有 bare mirror + `_run_git`；禁止依赖 MR webhook |
| Hunk 解析 / rename / formatting_only / 行区间交叠 | API / Backend (`code_graph/detect_changes.py`) | — | 纯函数可单测；不碰 ORM |
| Symbol ORM 批量取数 + exclusion | API / Backend (`code_graph_tools`) | Database | 121 D-01：包内仅 loader 持 ORM；编排层查 Symbol |
| 批量 impact | API / Backend (`run_impact`) | — | D-09 禁止重写 BFS |
| Staleness / degradation 信封 | API / Backend (`staleness_payload` / `degradation_payload`) | — | 122 已定型；请求路径不起 git |
| MCP 工具壳 | API / Backend (`McpToolView`) | — | PAT + RetrievalTrace + snapshot |
| 对话工具壳 | API / Backend (`agents/tools`) | Browser（消费） | `@tool` + 会话 owner；data 段零加工 |
| 持久化模型 / migration | — | — | 本相位明确不做 |

## Project Constraints (from .cursor/rules/)

来自 `observability-logging.mdc`（强制）：

- `structlog.get_logger(__name__)`；事件名 snake_case + kv；生命周期 `started/completed/failed` + `duration_ms`
- 每事件设 `category`（`caller`/`sampling`）与 `component`；本相位内核/编排用 `component="code_graph"`（与索引侧 `codegraph` 并存，LOGGING-SPEC §已登记）
- 绑定触发用户；后台无用户记 `system`
- 凭证/路径/异常文本脱敏；观测 best-effort 不反噬
- 高频 hunk 循环禁止 INFO 刷屏 → `sampling` 或 DEBUG
- 新增工具入口纳入 QPS/错误率（`McpToolView._record` 已含 `RequestMetric`）；召回留痕走汇总 `RetrievalTrace`（只计数，不落符号名/路径正文——对齐 122 `tool_trace_payload`）

项目 skills（`.agents/skills/`）均为 GSD 工作流包装，对本相位实现栈无额外约束。

## Standard Stack

### Core

| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| git CLI via `repo_mirror._run_git` | system git 2.x（本机 2.54.0） | `diff --unified=0 --find-renames` | [VERIFIED: codebase `repo_mirror.py`] 与 ARCHITECTURE Pattern 3；token 只进 fetch URL |
| Django ORM `Symbol` | 既有 | `start_line`/`end_line`/`file_path`/`branch_name` | [VERIFIED: `codegraph/models.py`] |
| `services.code_graph_tools.run_impact` | Phase 122 | 批量影响面 | [VERIFIED: `code_graph_tools.py:739`] |
| `staleness_payload` / `degradation_payload` | Phase 122 | 可信度信封 | [VERIFIED: `code_graph_tools.py:308+`] |
| `McpToolView` + `@tool` | 既有 | 双面薄壳 | [VERIFIED: `mcp_tools/views.py` / `agents/tools/graph_tools.py`] |
| networkx | 3.6.1（已在 uv.lock） | 仅经 `run_impact` 间接使用 | [VERIFIED: `uv run` + lock] |

### Supporting

| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| GitPython | 3.1.46（已在依赖） | **本相位默认不用** | 已有依赖，但 detect_changes 主通路锁定 `_run_git`（与 mirror 一致、易测、无额外对象模型） |
| `services.exclusion.build_matcher_for_repo` | 既有 | 交叠结果 exclusion | 与 `resolve_symbol_candidates` 同口径 fail-closed |
| pytest / pytest-django / pytest-asyncio | 既有 | 单测 + 双面哨兵 | 照抄 `test_impact_trace_tools.py` |

### Alternatives Considered

| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| `_run_git` diff | GitPython `DiffIndex` | 多一层抽象；与 mirror 错误/超时/脱敏路径分叉 — **不用** |
| unified hunk 交叠 | 仅 `--name-status` 文件级 | 丢行级精度，不满足 DIFF-01 file:line — **不够** |
| MR webhook diff | mirror diff | webhook 截断且覆盖不了提交前自查 — CONTEXT 已否决 |
| 三-dot `A...B` | two-dot `A B` | 三-dot 把左端换成 merge-base，破坏与 `last_indexed` Symbol 同源 — **禁止** |

**Installation:** 无新包。

```bash
# 无 npm/pip 新增。验证既有：
cd server && uv run python -c "import networkx; print(networkx.__version__)"
git --version
```

**Version verification:** networkx 3.6.1 [VERIFIED: uv.lock / runtime]；GitPython 3.1.46 [VERIFIED: uv.lock]（本相位不新增调用）；git 2.54.0 [VERIFIED: local `git --version`]。

## Package Legitimacy Audit

> 本相位 **零新增外部包**。slopcheck 未安装；无待审包。

| Package | Registry | Age | Downloads | Source Repo | slopcheck | Disposition |
|---------|----------|-----|-----------|-------------|-----------|-------------|
| — | — | — | — | — | n/a | 无新增 |

**Packages removed due to slopcheck [SLOP] verdict:** none  
**Packages flagged as suspicious [SUS]:** none  

## Architecture Patterns

### System Architecture Diagram

```text
Agent / MCP client
        │
        ├─ POST /api/mcp/tools/detect_changes/     (McpToolView 薄壳)
        └─ @tool detect_changes                    (agents/tools 薄壳)
                    │
                    ▼
         run_detect_changes  (code_graph_tools.py)     ← 唯一编排入口 (D-13)
                    │
        ┌───────────┼──────────────────────────────────────┐
        ▼           ▼                                      ▼
 ensure_mirror   Symbol ORM (base, branch_name="")    staleness_payload
 + diff_mirror   + exclusion matcher                  degradation_payload
        │           │
        ▼           ▼
 parse unified   interval overlap                     ┌── threshold?
  -M -U0         (detect_changes.py 纯函数)            │
        │           │                                 ▼
        └────► affected symbols[] ─── ≤100 ──► for sid in seeds:
                                              sequential run_impact(symbol_id=sid)
                                                      │
                                              >100 ──► file-level summary,
                                                       skip batch impact
                                                      │
                                                      ▼
                              envelope: ok, files[], impacts[],
                              diff_base_sha, diff_head_sha, base_ref?,
                              staleness, graph, affected_processes=[],
                              summary{truncated,not_expanded,...}
```

### Recommended Project Structure

```
server/services/
├── repo_mirror.py              # + diff_mirror() / 可选 ensure_mirror_sha
├── code_graph/
│   ├── detect_changes.py       # NEW：纯解析+交叠+formatting/rename 分类（零 ORM）
│   ├── impact.py               # 复用（经 run_impact）
│   └── __init__.py             # ⛔ 不把 detect_changes 强行塞进 17 项 barrel（对齐 impact/trace）
├── code_graph_tools.py         # + run_detect_changes
mcp_tools/
├── views.py                    # + DetectChangesView
├── serializers.py              # + DetectChangesRequestSerializer + TOOL_SCHEMAS
└── urls.py                     # + tools/detect_changes/
agents/tools/
├── graph_tools.py              # + detect_changes @tool
├── schemas/graph_tools.py      # + DetectChangesParams
└── __init__.py                 # 注册导出
agents/chat_runner.py           # 白名单加 detect_changes
server/tests/
├── services/code_graph/
│   ├── test_detect_changes.py           # 交叠/rename/formatting/阈值 纯单测
│   └── test_detect_changes_orchestrator.py
├── services/test_diff_mirror.py         # mirror helper（临时 bare repo fixture）
└── mcp_tools/test_detect_changes_tools.py  # MCP + 双面哨兵
```

### Pattern 1: Diff 锚定 + `diff_mirror`（D-01/D-02）

**What:** 先 `ensure_mirror_commit(repo_id)` 拿 **pin 到 `last_indexed_commit_sha`** 的 base 快照；再 `ensure_mirror_commit(repo_id, branch=compare)` 拿 head；同一 `repo_dir` 上：

```bash
git diff --unified=0 --find-renames <base_sha> <head_sha>
```

**When to use:** 一切 detect_changes 调用；`base_ref` 只写入输出声明。

**关键语义（已核实）：**

1. CONTEXT 的 `A…B` 在实现上必须是 **two-dot 树对树** `git diff A B`，左端固定为索引水位。三-dot `A...B` 会把左端换成 merge-base，破坏 Symbol 同源。[VERIFIED: ARCHITECTURE Pattern 3 明文 `git diff --unified=0 <base_sha> <head_sha>`]
2. `ensure_mirror_commit` 在 `ref == base_branch` 时**强制 pin** 索引 sha（`repo_mirror.py:245`）。因此 `compare` **必须是 feature 分支名（或可 fetch 的非 base ref / sha）**，不能指望对 base 分支名两次调用分别得到「索引水位」与「远端 tip」。
3. 40 位 sha 作 `compare`：现有 fetch 路径走 `refs/heads/{ref}`，对纯 sha **会失败**。规划应在 `diff_mirror` 旁增加 `ensure_mirror_sha(repo_id, sha)`（复用 pin fetch：`+{sha}:refs/friday/pin-…`），或 v1 文档约定 `compare` 仅为分支名并硬拒非法 sha。[ASSUMED 推荐：加 `ensure_mirror_sha`，约 20–40 行，与 pin 路径同构]

### Pattern 2: 纯交叠内核 vs ORM 编排（对齐 121 D-01 / 122）

**What:** `detect_changes.py` **只吃**「已解析的 file/hunk 结构 + 内存中的 symbol records」，输出 affected 列表。`run_detect_changes` 负责：ACL → 校验 `last_indexed_commit_sha` → mirror diff → 按触及的 `file_path` **批量**查 `Symbol`（`branch_name=""`）→ exclusion → 调纯内核 → 阈值闸 → batch `run_impact` → 信封。

**Why:** loader docstring 与 121 红线写明包内除 loader 外零 ORM；`impact.py`/`trace.py` 已是纯内核先例。把 ORM 塞进 `detect_changes.py` 会让交叠单测拖起 Django，并诱惑绕过 exclusion。

**Base Symbol 坐标（规划必写进任务）：** feature overlay 的 `Symbol` 行号来自**分支索引树**，不是 `Repository.last_indexed_commit_sha` 树（loader「分支语义是 overlay」）。old-side hunk 行号属于 diff 左端（索引水位）。因此：

- 交叠查询 **固定** `branch_name=""`（base 全量符号）
- batch `run_impact` 的 `graph_branch` **固定 `None`（base 图）**，保证种子 `symbol_id` 落在图内
- 工具参数里的 `compare`/`base_ref` 描述的是 **git 语义**，不是图 overlay 分支；可选的 `branch` 若与 122 同名出现，v1 **忽略或仅用于声明**，不得拿去换交叠坐标（否则行号错位 / seed 不在图）

[VERIFIED: loader.py 分支 overlay 语义 + D-01 水位锚定；坐标裁决为研究推荐，落在 Claude's Discretion 的参数命名区]

### Pattern 3: 双面薄壳（D-13 / 122 D-21）

**What:** 壳内零算法：`_begin` → validate → `_get_indexed_repo` / `_resolve_tool_repo` → `run_detect_changes` → 原样透出 + `run_id`（仅 MCP）→ 一条汇总 `RetrievalTrace` + `caller` 事件。`ok=False` → HTTP 200（与 impact 一致）。`GraphError` → `_graph_error_response`。`MirrorError`：**推荐在编排层折成 `ok=False` + `error_code=<MirrorError.code>`**，保证双面信封同形；⛔ 不得折成空 affected。

**When to use:** 每个新图工具；已有哨兵 `test_two_surfaces_same_payload`。

### Anti-Patterns to Avoid

- **用工作树 / 默认分支 tip / `base_ref` 做交叠基线** — Pitfall 5；never
- **默认 `git diff` 无 `-M`** — rename = delete+add 满屏误报
- **feature `branch_name` Symbol 跟 old-side hunk 求交** — 两棵树行号
- **detect_changes 内重写 impact BFS** — D-09
- **壳层分叉逻辑 / 改 `mcp/` submodule** — D-13 / D-27
- **改 `repo_router_v2.py`** — 冻结至 Phase 125
- **catch GraphError/MirrorError 成「无改动」** — D-03
- **hunk 循环打 INFO** — 日志放大
- **超阈值仍逐符号 `run_impact`** — 构建风暴（Pitfall 2×5）

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| git fetch/pin/脱敏 | 自建 clone | `ensure_mirror_commit` + `_run_git` | 凭证 URL、TTL、失败缓存已完备 |
| 反向 BFS / 风险级 / 跨仓 | 新 impact | `run_impact` | D-09；122 已含 D-25/D-29/D-30 |
| Staleness 现算 git distance | 请求路径 `rev-list` | `staleness_payload` | D-22；behind 是库字段 |
| Exclusion glob | 自写 fnmatch | `build_matcher_for_repo` | ReDoS/fail-closed 四层语义 |
| MCP PAT / metrics / trace | 自建 view | `McpToolView` | 40+ 工具同构 |
| Rename 相似度引擎 | 自研 | `git diff --find-renames` | indexer 已验证 R* 解析 |

**Key insight:** 本相位的「新」仅三块——mirror diff、行区间交叠、batch 编排；其余全部是接线。

## Common Pitfalls

### Pitfall 1: 行号错位（快照 / overlay）
**What goes wrong:** 报告的符号对不上真实改动。  
**Why:** 左端不是 `last_indexed_commit_sha`，或用了 feature overlay Symbol。  
**How to avoid:** two-dot + base Symbol + 输出透出 `diff_base_sha`/`as_of`。  
**Warning signs:** 集成测试里故意在索引后追加无关 commit 仍「命中」错误符号。

### Pitfall 2: 纯 rename 双列表
**What goes wrong:** 旧路径全 deleted、新路径无符号。  
**Why:** 未开 `-M` / 把 R 拆成 D+A。  
**How to avoid:** `--find-renames`；`changeType=renamed` 单条逻辑映射；对照 indexer：`R100`→RENAME，内容变更 rename 仍应一笔 renamed（可附 `lines_changed`），⛔ 不双报。  
**Warning signs:** 验收「纯 rename PR」出现大量 deleted。

### Pitfall 3: format 风暴
**What goes wrong:** 一次 prettier 触发上百次 `run_impact`。  
**Why:** 未做 `formatting_only` / 未截断。  
**How to avoid:** D-07 + D-08；默认顺序 batch。  
**Warning signs:** `RequestMetric` 尖峰。

### Pitfall 4: 空结果伪装成功
**What goes wrong:** 未索引仓返回 `affected: []`，agent 以为「改动安全」。  
**Why:** catch 过度。  
**How to avoid:** D-03；与 `graph_error_to_tool_error` 同纪律。

### Pitfall 5: 双面漂移
**What goes wrong:** MCP 与对话结果不一致。  
**Why:** 壳内各自拼装。  
**How to avoid:** 只调 `run_detect_changes`；加 `test_two_surfaces_same_payload` 变体（成功 + 硬错误态）。

### Pitfall 6: base 分支 tip 无法作 compare
**What goes wrong:** `compare=main` 时 head 被 pin 成索引 sha，diff 恒空。  
**Why:** `ensure_mirror_commit` 对 base_ref 强制 pin。  
**How to avoid:** 文档/校验：`compare` 应为 feature 分支或显式 sha（经 `ensure_mirror_sha`）；若 `compare` 解析后 sha == `diff_base_sha`，返回明确 `error_code`（如 `empty_diff_range`）或成功空清单 + 声明，⛔ 不要静默当成「无改动且可信」。

## Code Examples

### 1) `diff_mirror` 形状（推荐）

```python
# 落点: server/services/repo_mirror.py
# Source: 本仓 ARCHITECTURE Pattern 3 + 既有 _run_git

@dataclass(frozen=True)
class DiffMirrorResult:
    base_sha: str
    head_sha: str
    unified_diff: str  # --unified=0 --find-renames 文本

async def diff_mirror(
    base: MirrorSnapshot,
    head: MirrorSnapshot,
    *,
    timeout: float = 120.0,
) -> DiffMirrorResult:
    if base.repo_dir != head.repo_dir:
        raise MirrorError("invalid_params", "diff_mirror 要求同一 bare 镜像目录")
    if base.repository_id != head.repository_id:
        raise MirrorError("invalid_params", "diff_mirror 禁止跨仓")
    rc, out, stderr = await _run_git(
        [
            "diff",
            "--unified=0",
            "--find-renames",
            base.commit_sha,
            head.commit_sha,
        ],
        cwd=base.repo_dir,
        timeout=timeout,
        max_output_bytes=16 * 1024 * 1024,  # 防 format 大 diff OOM；超限明确报错
    )
    if rc not in (0, 1):  # git diff: 1 = 有差异
        raise MirrorError(
            "mirror_fetch_failed",
            f"git diff 失败: {_scrub(stderr.decode(errors='replace'))[:300]}",
        )
    return DiffMirrorResult(
        base_sha=base.commit_sha,
        head_sha=head.commit_sha,
        unified_diff=out.decode(errors="replace"),
    )
```

### 2) 行区间交叠（纯函数）

```python
# 落点: server/services/code_graph/detect_changes.py
# Source: CONTEXT D-05；标准闭区间相交

def ranges_overlap(a0: int, a1: int, b0: int, b1: int) -> bool:
    return a0 <= b1 and b0 <= a1

def symbols_hit_by_old_hunk(
    symbols: list[tuple[str, int, int]],  # (uid, start_line, end_line)
    hunk_old_start: int,
    hunk_old_count: int,
) -> list[str]:
    """hunk 头 @@ -start,count +... @@；count=0 表示纯插入（旧侧无行）。"""
    if hunk_old_count <= 0:
        return []
    old_end = hunk_old_start + hunk_old_count - 1
    return [
        uid
        for uid, s, e in symbols
        if ranges_overlap(s, e, hunk_old_start, old_end)
    ]
```

### 3) `formatting_only` 启发式（Discretion 推荐初值）

```python
# Source: PITFALLS Pitfall 5；[ASSUMED] 实现细节

def is_formatting_only(old_lines: list[str], new_lines: list[str]) -> bool:
    def norm(lines: list[str]) -> list[str]:
        # strip 每行空白；丢掉空行；import 行排序后再比
        body = [ln.strip() for ln in lines if ln.strip()]
        imports = sorted(x for x in body if x.startswith(("import ", "from ")))
        rest = [x for x in body if not x.startswith(("import ", "from "))]
        return imports + rest
    return norm(old_lines) == norm(new_lines)
```

语言特化（JS/Go）可后续加；v1 用空白+import 启发式足够通过「format commit 不进 impact 种子」验收。

### 4) 编排伪代码

```python
# 落点: code_graph_tools.run_detect_changes
async def run_detect_changes(...):
    await ensure_repository_readable(user, repository_id)
    if not repo.last_indexed_commit_sha:
        return {"ok": False, "error_code": "repository_not_indexed", ...}
    base = await ensure_mirror_commit(repository_id)  # pin index
    head = await ensure_mirror_commit(repository_id, branch=compare)
    diff = await diff_mirror(base, head)
    # parse → touch files → load base Symbols → exclude → overlap
    affected = detect_affected_symbols(...)
    staleness = await staleness_payload(repo)
    # D-04: behind 大时加强 declaration（不硬拒）
    if len(impact_seeds) > THRESHOLD:  # 100
        return ok_envelope(file_summary=True, impacts=[], not_expanded=True, ...)
    impacts = []
    for sid in impact_seeds:  # D-11 顺序
        try:
            one = await run_impact(
                repository_id=repository_id, repo=repo, graph_branch=None,
                user=user, symbol_id=sid, max_depth=3, min_confidence=1.0,
                include_low_confidence=False, limit=200,
            )
            impacts.append({"symbol_id": sid, "impact": one})
        except GraphError as exc:
            code, msg = graph_error_to_tool_error(exc)
            impacts.append({"symbol_id": sid, "impact_error": code, "unavailable_reason": msg})
    return {
        "ok": True,
        "tool": "detect_changes",
        "diff_base_sha": diff.base_sha,
        "diff_head_sha": diff.head_sha,
        "base_ref": base_ref,
        "files": grouped_affected,
        "impacts": impacts,
        "affected_processes": [],
        "staleness": staleness,
        "graph": degradation_payload(...),  # 若未取图：用首个成功 impact 的 graph，或一次轻量 fetch
        ...
    }
```

**degradation / graph meta：** 若跳过 batch impact（截断），仍需可信度声明——推荐对第一个种子或任意 touched symbol 做一次 `fetch_graph_for_tool`（depth=1）只取 `GraphMeta`，或在截断路径上用 `resolution_rate` 库统计短路；规划任务须显式二选一，避免截断路径缺 `graph.resolution_rate`（D-14）。

### 5) MCP 壳对照（ImpactAnalysisView）

```python
# Source: server/mcp_tools/views.py:1286-1392 [VERIFIED]
# DetectChangesView 同构：validate → _get_indexed_repo → run_detect_changes
# → output_data = {**result, "run_id"} → _record + RetrievalTrace → HTTP 200
```

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| GitNexus 本地 detect_changes | Friday 服务端 mirror + 多用户 ACL | v0.22.0 | 需 PAT/会话闸 + staleness |
| MR webhook diff | mirror tree-to-tree | 调研 2026-08-09 | 覆盖提交前自查 |
| 文件级 name-status only | hunk × Symbol 行交叠 | DIFF-01 | 行级行动指南 |
| 无双面哨兵 | 122-10 逐字节哨兵 | Phase 122 | 123 必须扩到 detect_changes |

**Deprecated/outdated:**

- 用工作树 diff 做符号交叠 — never（PITFALLS 技术债表）
- 在 detect_changes 内自研 impact — D-09

## Runtime State Inventory

> 本相位非 rename/rebrand；**无**运行时字符串迁移。显式确认：

| Category | Items Found | Action Required |
|----------|-------------|------------------|
| Stored data | None — verified：不改模型/字段名 | none |
| Live service config | None — verified：不改外部仪表 | none |
| OS-registered state | None | none |
| Secrets/env vars | 可选后续 `DETECT_CHANGES_SYMBOL_THRESHOLD`（初值 100 可先常量） | 代码常量即可；env 化非必须 |
| Build artifacts | None | none |

## Assumptions Log

| # | Claim | Section | Risk if Wrong |
|---|-------|---------|---------------|
| A1 | `formatting_only` = strip 空白 + import 行排序比对 | Code Examples | 漏报真实改动进/出 impact 种子；可用单测夹具校准 |
| A2 | v1 交叠与 batch impact 固定 base 图（`graph_branch=None`） | Pattern 2 | 若产品要「feature overlay 图上的 impact」，需另定坐标变换——当前与 D-01 冲突 |
| A3 | 应新增 `ensure_mirror_sha` 以支持 sha 型 compare | Pattern 1 | 若只允许分支名，MR 场景仍可用，容器 detached HEAD 需 Phase 124 再补 |
| A4 | git diff rc∈{0,1} 均成功 | Code Examples | 少数 git 版本行为差异；集成测锁死 |
| A5 | 截断路径用一次轻量 `fetch_graph_for_tool` 填 `graph` | Code Examples | 多一次取图成本；替代是截断时 `graph: null`+声明——弱于 D-14 |

**若需用户确认：** A2（图分支坐标）影响 API 语义最大；其余可按推荐直接规划。

## Open Questions

1. **截断路径的 `graph` / `degradation` 如何填？**
   - What we know: D-14 成功时必含 `degradation_payload`（含数值 `resolution_rate`）
   - What's unclear: 跳过 batch 时没有自然的 `run_impact` 返回
   - Recommendation: 对任意一个非 formatting 种子（或文件内第一符号）`fetch_graph_for_tool(depth=1)` 只取 meta；无种子则 `graph` 带 `resolution_rate` 自 `GraphMeta` 空仓定义或显式 `degraded: "not_expanded"`

2. **`compare` 与历史工具参数 `branch` 是否并存？**
   - What we know: 122 工具用 `branch` 表示图分支；123 的 `compare` 是 diff head
   - Recommendation: 请求字段用 `compare`（必填）+ `base_ref`（可选）；**不要**复用 `branch` 以免与图 overlay 混淆；对话 description 写清

## Environment Availability

| Dependency | Required By | Available | Version | Fallback |
|------------|-------------|-----------|---------|----------|
| git CLI | `diff_mirror` | ✓ | 2.54.0 | — |
| Python 3.14 + uv | 测试/实现 | ✓ | 项目钉扎 | — |
| networkx | 经 `run_impact` | ✓ | 3.6.1 | — |
| REPO_MIRROR / clone dir | mirror | 配置项 | settings | MirrorError 硬拒（D-03） |
| Qdrant | 本相位不直接依赖 | n/a | — | — |
| slopcheck | 包审计 | ✗ | — | 无新包，可忽略 |

**Missing dependencies with no fallback:** none  
**Missing dependencies with fallback:** slopcheck（无新包）

Step 2.6: 外部依赖均为既有栈；无阻塞项。

## Validation Architecture

### Test Framework

| Property | Value |
|----------|-------|
| Framework | pytest + pytest-django + pytest-asyncio（server/pyproject.toml） |
| Config file | `server/pyproject.toml` `[tool.pytest.ini_options]` |
| Quick run command | `cd server && uv run pytest tests/services/code_graph/test_detect_changes.py tests/services/test_diff_mirror.py -q` |
| Full suite command | `cd server && uv run pytest tests/services/code_graph/ tests/mcp_tools/test_detect_changes_tools.py tests/mcp_tools/test_impact_trace_tools.py -q` |

### Phase Requirements → Test Map

| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| DIFF-01 | hunk×Symbol 交叠命中 / file:line / changeType | unit | `pytest tests/services/code_graph/test_detect_changes.py -k overlap -x` | ❌ Wave 0 |
| DIFF-01 | base 强制 `last_indexed_commit_sha`（mock mirror 断言 argv） | unit | `pytest ... -k diff_base_pinned -x` | ❌ Wave 0 |
| DIFF-01 | 批量 impact 调用 `run_impact(symbol_id=…)` 且默认参数 | unit | `pytest ... -k batch_impact -x` | ❌ Wave 0 |
| DIFF-01 | 空索引 sha / MirrorError → ok=False 非空清单 | unit | `pytest ... -k hard_reject -x` | ❌ Wave 0 |
| DIFF-01 | staleness 信封含 `as_of`；behind 大仍 ok=True | unit | `pytest ... -k staleness -x` | ❌ Wave 0 |
| DIFF-02 | `git diff -M`：纯 rename → 仅 `renamed`，无 deleted+added 双列表 | unit+git fixture | `pytest tests/services/test_diff_mirror.py -k rename -x` | ❌ Wave 0 |
| DIFF-02 | `base_ref` 不改变 diff argv 左端 | unit | `pytest ... -k base_ref_declarative -x` | ❌ Wave 0 |
| DIFF-01/02 | `formatting_only` 不进 impact 种子 | unit | `pytest ... -k formatting_only -x` | ❌ Wave 0 |
| DIFF-01 | >100 符号 → 文件级摘要 + `not_expanded` + 零次 `run_impact` | unit | `pytest ... -k threshold -x` | ❌ Wave 0 |
| IMPACT-06 延续 | MCP↔对话 data 逐字节同源（去 `run_id`） | integration | `pytest tests/mcp_tools/test_detect_changes_tools.py -k two_surfaces -x` | ❌ Wave 0 |
| GRAPH-04 延续 | 排除文件不出现在 affected | unit | `pytest ... -k exclusion -x` | ❌ Wave 0 |

### Sampling Rate

- **Per task commit:** quick 命令（交叠 + diff_mirror）
- **Per wave merge:** full 上表命令 + 既有 `test_impact_trace_tools` 无回归
- **Phase gate:** 上表全绿；`test_mcp_package_tools_match_server_snapshot` 允许继续红（漂移 7→8，D-27 白名单）

### Wave 0 Gaps

- [ ] `server/tests/services/code_graph/test_detect_changes.py` — 交叠 / formatting / 阈值 / rename 分类（纯字符串 fixture，不需真实 git）
- [ ] `server/tests/services/test_diff_mirror.py` — 临时 bare repo：`git init` + 两 commit + rename + format
- [ ] `server/tests/services/code_graph/test_detect_changes_orchestrator.py` — `run_detect_changes` mock mirror / spy `run_impact`
- [ ] `server/tests/mcp_tools/test_detect_changes_tools.py` — MCP 200 + 双面哨兵
- [ ] serializers `TOOL_SCHEMAS["detect_changes"]` + snapshot 断言更新（接受 mcp 包漂移 +1）

## Security Domain

### Applicable ASVS Categories

| ASVS Category | Applies | Standard Control |
|---------------|---------|-----------------|
| V2 Authentication | yes（MCP PAT / 会话） | `McpToolView` / conversation owner（122 同款） |
| V3 Session Management | yes（对话） | 既有 chat 会话闸 |
| V4 Access Control | yes | `ensure_repository_readable`；exclusion fail-closed |
| V5 Input Validation | yes | DRF serializer + `_SAFE_REF_RE`；diff 输出字节上限 |
| V6 Cryptography | no | 无新密钥；沿用 mirror token-in-URL 脱敏 |

### Known Threat Patterns for detect_changes

| Pattern | STRIDE | Standard Mitigation |
|---------|--------|---------------------|
| 未授权仓符号/路径经 affected 回流 | Information Disclosure | ACL 在 ORM/输出前；与 122 同 |
| 排除文件（`.env`）出现在清单 | Information Disclosure | matcher 过滤；出现即测失败 |
| git 凭证进日志/错误 | Information Disclosure | `_scrub` / `redact_secrets_in_text` |
| 超大 diff / 批量 impact DoS | Denial of Service | 输出字节上限 + 符号阈值 100 + 顺序 batch |
| `base_ref` 被误当成交叠基线导致错答 | Tampering / Spoofing | D-02：声明透出但 argv 左端锁定索引 sha |
| RetrievalTrace 落入符号名/源码 | Information Disclosure | 汇总计数 only（扩 `tool_trace_payload`） |

## Sources

### Primary (HIGH confidence)

- [VERIFIED: codebase] `server/services/code_graph_tools.py` — `run_impact` / `staleness_payload` / `degradation_payload` / `tool_trace_payload`
- [VERIFIED: codebase] `server/services/repo_mirror.py` — `ensure_mirror_commit` pin 语义、`_run_git`、`MirrorError`
- [VERIFIED: codebase] `server/mcp_tools/views.py` — `ImpactAnalysisView` / `TraceCallPathView` / `_mirror_error_response`
- [VERIFIED: codebase] `server/agents/tools/graph_tools.py` — 对话壳 D-21
- [VERIFIED: codebase] `server/codegraph/models.py` — `Symbol` 行号字段
- [VERIFIED: codebase] `server/services/indexer.py` — `--find-renames` / `DiffAction.RENAME` / `_parse_git_diff_output`
- [VERIFIED: codebase] `server/services/code_graph/loader.py` — overlay 分支语义
- [VERIFIED: codebase] `server/tests/mcp_tools/test_impact_trace_tools.py` — 双面哨兵范式
- [CITED: .planning/research/ARCHITECTURE.md] Pattern 3 detect_changes diff 通路
- [CITED: .planning/research/PITFALLS.md] Pitfall 5
- [CITED: .planning/research/SUMMARY.md] Phase 3 P-detect
- [CITED: .planning/phases/123-detect-changes/123-CONTEXT.md] D-01..D-16
- [CITED: .planning/observability/LOGGING-SPEC.md] `component=code_graph`

### Secondary (MEDIUM confidence)

- Git rename / unified diff 行为 — 与本仓 indexer 测试 `tests/test_git_diff_index.py` 交叉验证
- graphify：disabled，未注入图关系

### Tertiary (LOW confidence)

- `formatting_only` import 排序启发式在多语言仓库的召回/精确率 — 待单测夹具与上线后校准（A1）

## Metadata

**Confidence breakdown:**

- Standard stack: HIGH — 零新依赖，路径均在本仓核实
- Architecture: HIGH — 122 双面模式 + ARCHITECTURE Pattern 3 + overlay 坐标陷阱已标明
- Pitfalls: HIGH — PITFALLS Pitfall 5 与代码 pin 语义交叉验证

**Research date:** 2026-08-10  
**Valid until:** 2026-09-09（30 天；栈稳定）

---

## Planner Quick Reference（非模板强制，供拆 plan）

建议 Wave 切分（供 gsd-planner 参考，非锁定）：

1. **W0** — 测试骨架（上表 Wave 0 Gaps）
2. **W1** — `diff_mirror` (+ `ensure_mirror_sha`) + 纯 `detect_changes.py` + 单测
3. **W2** — `run_detect_changes` 编排（交叠 ORM、阈值、batch `run_impact`、信封）
4. **W3** — MCP serializer/view/url + TOOL_SCHEMAS
5. **W4** — 对话 `@tool` + schemas + `__init__` + `chat_runner` 白名单
6. **W5** — 双面哨兵 + 观测契约扩展 + D-27 漂移计数记账

推荐常量：

- `DETECT_CHANGES_MAX_SYMBOLS_FOR_IMPACT = 100`
- `DETECT_CHANGES_MAX_DIFF_BYTES = 16_1024_1024`
- 事件名（静态字面量）：`code_graph_detect_changes_started|completed|failed`，`code_graph_diff_parsed`（sampling）
