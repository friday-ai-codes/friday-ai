# Phase 133: 同仓同 commit 基准与 v0.22 baseline - Research

**Researched:** 2026-08-24
**Domain:** brownfield 增量 — 可复现评测 harness 与冻结数据集（单仓 graph-aware query 的 v0.22 原始基线）
**Confidence:** HIGH（评测 harness 模式、被测能力入口、水位元数据、观测约束均核对于本仓源码；阈值/数值目标按约束刻意不定）

> **范围纪律：** 本阶段只交付 baseline 与评测地基，**不锁定任何回归阈值**（阈值属 Phase 140 / BENCH-06/07）。运行时零新增生产依赖是硬约束。被测能力（`services/code_graph/*`、`retrieval/*`、`codegraph/resolver/*`）逻辑**不修改**，harness 只做调用、计时、记录。

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions

**评测身份与水位一致性（BENCH-01）**
- 每次 benchmark run 绑定唯一评测身份 `(repository, branch, commit_sha, index_key, gold_version)`，全部证据（Symbol、Process、调用边、`file:line`、impact）强制来自同一 commit SHA。
- run 前做水位校验：索引 `built_at_sha`、gold 标注 sha、源码 checkout sha 三者不一致即标 `INVALID` 并中止，不产出部分结论。
- 评测身份与校验结果写入 run manifest（结构化 JSON），供 Phase 140 同条件对比复用。

**数据集切分与 gold 来源（BENCH-02）**
- gold 数据落地为仓库内可版本化的冻结数据集（`.planning` 之外，独立于被测图），按 dev / locked test / holdout 三切分；baseline 只用 dev + locked test，holdout 留给最终验收。
- resolved edge gold 来自独立 callsite 抽样人工/规则标注，**禁止**从被测 codegraph 反向导出（防循环论证）。
- 每条 gold 记录语言、框架、入口类型、call shape 等分桶维度，供 BENCH-05 分桶。

**原始 baseline 产出（BENCH-03）**
- 直接调用既有 v0.22 能力（`services/code_graph/*`、`retrieval/*`、`codegraph/resolver/*`）在冻结数据集上跑 baseline，不修改其逻辑。
- 产物为逐 case 原始记录 + 逐桶聚合，**不含任何预填/推断的回归目标值**；阈值字段留空待 Phase 140。

**指标、分母与空结果规则（BENCH-04、BENCH-05）**
- 指标集：NL→Symbol Recall@5、NL→Process Recall@3、resolved edge precision/recall、impact precision、trace 成功率/错误路径率、冷/热延迟、token；每个指标锁定固定分母与空结果规则（空结果如何计入显式定义）。
- 全部质量指标按 语言 × 框架 × 入口类型 分桶；样本不足桶标 `INSUFFICIENT_DATA`；受保护桶单列，不被 overall 提升抵消。
- 评测模式只读，不写生产索引；冷/热延迟区分首次（冷）与重复（热）运行。

### Claude's Discretion
- harness 的具体模块布局、gold 数据 schema 细节、报告渲染格式由 Claude 依据现有 `repo_router_eval.py` / `repo_route_recall_eval.py` / `gaosan_eval.py` 评测模式决定，保持与既有 eval harness 同构。

### Deferred Ideas (OUT OF SCOPE)
- 阈值锁定与同条件对比 → Phase 140（BENCH-06/07）。
- 真实 `CrossRepoApiCall` 跨仓样本验证 → FUTURE-01，不在本阶段。
</user_constraints>

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| BENCH-01 | 固定 repository/branch/commit SHA；Symbol/Process/调用边/`file:line`/impact/gold 同 commit；水位不一致 run 标 INVALID | 水位元数据已存在（`Repository.last_indexed_commit_sha`、`ProcessTrace/SymbolCommunity.built_at_sha`、`head_sha`），见「水位与评测身份」。run manifest + 三方校验 + INVALID 短路为新增 harness 逻辑。 |
| BENCH-02 | 独立标注 query/gold，dev/locked test/holdout 切分；resolved edge gold 来自独立 callsite 抽样 | 冻结数据集落 `server/tests/fixtures/graph_bench/`（沿袭现有 fixtures 约定），gold schema 含分桶维度与 `gold_version`、`annotated_at_sha`，见「冻结数据集与 gold schema」。 |
| BENCH-03 | 未修改 v0.22 能力在冻结数据集上产逐 case/逐桶原始 baseline，不填阈值 | 被测能力均为可直接调用的纯函数/服务（`analyze_impact`/`trace_path`/`resolve_symbol_in_graph`/`hybrid_search.search`），见「v0.22 被测能力入口」。报告**不含** `compare_to_baseline`/阈值字段。 |
| BENCH-04 | 输出 Recall@5/@3、edge P/R、impact precision、trace 成功率/错误路径率、冷/热延迟、token，锁定分母与空结果规则 | 指标分母/空结果规则表见「指标集与空结果规则」。冷/热由 `GraphService.invalidate` + LRU cache 区分；token 复用 `ModelUsageRecord` 口径。 |
| BENCH-05 | 质量指标按语言×框架×入口类型分桶；稀疏桶 `INSUFFICIENT_DATA`；受保护桶不被 overall 抵消 | 分桶维度可从 `Symbol.file_path`（语言）、`Endpoint`/入口上下文（框架/入口类型）、gold `call_shape` 派生，见「分桶与 INSUFFICIENT_DATA」。宏观聚合用 macro（按 case 平均）防 overall 掩盖，沿袭 `aggregate_report`。 |
</phase_requirements>

## Summary

本阶段在既有 Django + Qdrant + NetworkX 栈上，新增一个**只读、可复现、无阈值**的评测 harness 与一个**可版本化的冻结 gold 数据集**，对未修改的 v0.22 图查询能力产出逐 case、逐桶原始 baseline。仓里已有两条互补的评测范式可直接复刻：(1) **纯函数指标模块 + 薄 management command**（`repo_route_recall_eval.py` 零 I/O 做算术，`evaluate_repo_route_recall.py` 做真跑与落盘）；(2) **golden gate + 逐例 diff**（`repo_router_eval.py` + 版本化 baseline JSON）。本阶段采前者为骨架、借后者的 per-case/per-bucket 报告形态，但**砍掉 compare/gate**——baseline 只产原始分布，阈值与比对逻辑留 Phase 140。

三个硬契约支撑全部需求：**评测身份五元组 + 三方水位校验 → INVALID 短路**（BENCH-01）；**独立标注、三切分的冻结 gold**（BENCH-02）；**锁定分母与空结果规则的逐桶原始指标，稀疏桶 `INSUFFICIENT_DATA`，受保护桶不被 overall 抵消**（BENCH-04/05）。被测能力全部是现成可调用入口，harness 不复制其管线逻辑（沿袭「走生产 route，不复刻」的反漂移原则）。

**Primary recommendation:** 新建 `server/codegraph/services/graph_bench_eval.py`（纯函数指标/分桶/水位校验，零 I/O）+ `server/codegraph/management/commands/evaluate_graph_bench.py`（薄 command 做真跑、计时、写 run manifest 与 baseline JSON），gold 数据集落 `server/tests/fixtures/graph_bench/{dev,locked_test,holdout}.json`。复用既有水位字段与观测埋点，运行时零新增依赖。

## Architectural Responsibility Map

| Capability | Primary Tier | Secondary Tier | Rationale |
|------------|-------------|----------------|-----------|
| 水位校验（built_at_sha / gold sha / checkout sha 一致性） | API / Backend (service) | — | 纯读 ORM 元数据，零网络；须 fail-closed 且 deterministic，放纯函数模块便于单测。 |
| gold 数据集加载与 schema 校验 | API / Backend (service) | — | 从仓内 fixtures 读 JSON，Pydantic/dataclass 校验，不进 DB。 |
| Symbol/Process 检索（被测） | API / Backend (service) | Database / Storage (Qdrant) | 调既有 `hybrid_search.search` / `search_rag`，harness 不重建。 |
| impact / trace（被测） | API / Backend (service) | Database / Storage (Django ORM→NetworkX) | 调既有 `analyze_impact` / `trace_path`（纯函数作用于冻结图）。 |
| 图装配与冷/热控制 | API / Backend (`GraphService`) | — | `get_graph` 唯一取图入口；`invalidate` 强制冷路径。权限闸 fail-closed 已内置。 |
| 指标聚合与分桶 | API / Backend (service，纯函数) | — | 确定性算术，零 I/O，沿袭 `aggregate_report` macro 模式。 |
| run manifest / baseline 落盘 | API / Backend (management command) | — | 写版本化 JSON 到 fixtures 目录；命令层负责 I/O 与退出码。 |
| 观测埋点 | API / Backend (service) | Database (ModelUsageRecord/RetrievalTrace) | best-effort，失败不反噬评测；CLI 触发标 `system`。 |

**Tier 判定要点：** 本阶段**无 Browser / Frontend Server / CDN 层**——全部能力是后端 service + 既有存储的只读编排。权限/exclusion 防线在 `GraphService.get_graph` 内已 fail-closed，harness 复用而不绕过。

## Standard Stack

### Core
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| pytest | `>=9.0.2`（锁 9.0.2） | 纯函数指标/水位/分桶单测 | 本仓既有测试框架，`asyncio_mode=auto`，`--disable-socket` 默认 |
| stdlib `statistics` / `time` / `json` / `dataclasses` | py3.14 | 聚合、冷/热计时、run manifest | 研究明确**不为 benchmark 引入 NumPy/SciPy/pandas/`ir_measures`** |
| structlog | 既有 | 生命周期 + sampling 埋点 | observability 强约束，复用 `common.logging` |
| NetworkX | 锁 3.6.1 | 被测 impact/trace 作用的冻结图 | 不更换图库；harness 只读 |

### Supporting
| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| Django ORM | `>=5.1` | 读 `Repository.last_indexed_commit_sha`、`built_at_sha`、`Symbol`/`Endpoint`/`ProcessTrace` | 水位校验与 gold 维度派生；async 走 `sync_to_async` |
| Pydantic | `>=2.6` | gold schema / run manifest 校验 | 可选；dataclass + 手写校验亦可（沿袭 `repo_route_recall_eval` 用 dataclass） |

### Alternatives Considered
| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| 自写逐桶聚合（stdlib） | `ir_measures` / pandas | 引入新生产依赖，违反「运行时零新增」硬约束；stdlib 足够算 Recall/P/R/macro 平均 |
| 薄 management command | 独立 CLI 脚本 / durable task | command 是本仓 eval 既定范式（`evaluate_repo_route_recall`），复现命令清晰、无需调度基础设施；评测只读不需要 durable |

**Installation:**
```bash
# 无新增依赖 —— 运行时零新增是硬约束（REQUIREMENTS Out of Scope 已钉死）。
# 全部复用 server/ 既有锁文件（server/uv.lock）。
```

**Version verification:** 无新增包需要核验。被测能力与观测依赖（`qdrant-client` 1.16.2、`fastembed` 0.7.4、NetworkX 3.6.1、pytest 9.0.2）均为 `server/uv.lock` 已锁版本，harness 只调用不新增。

## Package Legitimacy Audit

> 本阶段**不安装任何外部包**（运行时零新增生产依赖为硬约束，REQUIREMENTS.md Out of Scope 明确「不新增生产 Python 依赖」）。因此无需运行 Package Legitimacy Gate。

| Package | Registry | Age | Downloads | Source Repo | Verdict | Disposition |
|---------|----------|-----|-----------|-------------|---------|-------------|
| （无新增包） | — | — | — | — | — | — |

**Packages removed due to [SLOP] verdict:** none
**Packages flagged as suspicious [SUS]:** none

*本阶段全部复用 `server/uv.lock` 已锁依赖，不引入任何新包，故无 legitimacy 风险面。*

## Architecture Patterns

### System Architecture Diagram

```
┌─────────────────────────────────────────────────────────────────────┐
│ evaluate_graph_bench (management command, 薄壳 / 唯一 I/O 层)         │
│  --repo --branch --commit-sha --split dev|locked_test               │
│  --output-manifest --output-json [--cold-only]                      │
└──────┬──────────────────────────────────────────────────────────────┘
       │ 1. 读 gold fixtures + 读 ORM 水位
       ▼
┌─────────────────────────────────────────────────────────────────────┐
│ graph_bench_eval (纯函数, 零 I/O, 可单测)                            │
│  build_run_identity() → 五元组 (repo,branch,commit,index_key,gold_v) │
│  validate_watermark() → OK | INVALID (三方 sha 一致性, fail-closed)  │
│  ── INVALID → 短路, 不跑任何 case, manifest 记 invalid_reason ──     │
│  evaluate_case_*()  score_symbol_recall / process_recall /          │
│                     edge_pr / impact_precision / trace_success      │
│  bucket_metrics()   按 language×framework×entry_type 分桶           │
│  mark_insufficient() n<MIN_BUCKET → INSUFFICIENT_DATA               │
│  aggregate_report() macro 平均 (按 case, 防 overall 掩盖)           │
└──────┬──────────────────────────────────────────────────────────────┘
       │ 2. 逐 case 调被测能力 (不复制管线逻辑)
       ▼
┌──────────────────────┬──────────────────────┬───────────────────────┐
│ Symbol/Process lane  │ impact / trace       │ 冷/热控制             │
│ hybrid_search.search │ analyze_impact       │ GraphService.get_graph│
│ search_rag           │ trace_path           │ GraphService.invalidate│
│ (retrieval/)         │ (code_graph/)        │ (code_graph/cache)    │
└──────┬───────────────┴──────┬───────────────┴──────┬────────────────┘
       │ 只读                 │ 只读冻结图            │ invalidate→cold
       ▼                      ▼                      ▼
┌─────────────────────────────────────────────────────────────────────┐
│ Canonical Django models (只读)                                       │
│ Repository.last_indexed_commit_sha / head_sha                        │
│ Symbol / Endpoint / CallEdge / ProcessTrace.built_at_sha             │
└─────────────────────────────────────────────────────────────────────┘
       │ 3. best-effort 观测
       ▼
  structlog (caller/sampling) + ModelUsageRecord + RetrievalTrace (可选)
```

数据流主线：`gold case → 水位校验 → 调被测能力 → 计时 → 折算 CaseOutcome → 分桶聚合 → run manifest + baseline JSON`。INVALID 时在第 2 步前短路。

### Recommended Project Structure
```
server/
├── codegraph/
│   ├── services/
│   │   └── graph_bench_eval.py          # NEW：纯函数 — 身份/水位/指标/分桶/聚合（零 I/O）
│   └── management/
│       └── commands/
│           └── evaluate_graph_bench.py  # NEW：薄 command — 真跑、计时、写 manifest/baseline
└── tests/
    ├── fixtures/
    │   └── graph_bench/                 # NEW：冻结 gold 数据集（版本化，独立于被测图）
    │       ├── manifest.json            #   数据集 gold_version + annotated_at_sha + split 清单
    │       ├── dev.json                 #   baseline 用
    │       ├── locked_test.json         #   baseline 用
    │       ├── holdout.json             #   留最终验收（Phase 140），baseline 不读
    │       └── README.md                #   标注口径、分桶维度、防反导声明
    └── codegraph/
        └── test_graph_bench_eval.py     # NEW：纯函数单测（默认套件，--disable-socket 下跑）
```

### Pattern 1: 纯函数指标模块 + 薄 command（复刻 recall eval）
**What:** 把所有算术（身份构造、水位判定、指标折算、分桶、聚合）放进零 I/O 模块；command 只做 fixtures 加载、真跑被测能力、计时、落盘。
**When to use:** 本阶段默认。这是 `repo_route_recall_eval.py`（纯）+ `evaluate_repo_route_recall.py`（壳）的既定分工，让指标逻辑在 `--disable-socket` 默认套件下可测，command 因打真实 Qdrant/embedding 而标记排除。
**Example:**
```python
# Source: 复刻 server/codegraph/services/repo_route_recall_eval.py 的分层模式
# 纯模块只做算术，不 import ORM/Qdrant；由 command 注入实际到达集合。
def validate_watermark(
    *, index_built_at_sha: str, gold_annotated_at_sha: str, source_checkout_sha: str
) -> str:
    """三方水位一致性。任一为空或不一致 → INVALID（fail-closed，不出部分结论）。"""
    if not (index_built_at_sha and gold_annotated_at_sha and source_checkout_sha):
        return "INVALID"
    if len({index_built_at_sha, gold_annotated_at_sha, source_checkout_sha}) != 1:
        return "INVALID"
    return "OK"
```

### Pattern 2: run identity 五元组 + manifest（BENCH-01）
**What:** 每次 run 构造 `(repository, branch, commit_sha, index_key, gold_version)` 写入结构化 manifest，供 Phase 140 同条件复用。
**When to use:** 每个 run 必做，且在任何 case 执行前完成校验。
**关键映射（来自本仓源码核验）：**
- `commit_sha` / `index_key`：本仓**没有现成 `index_key` 概念**；索引水位用 `Repository.last_indexed_commit_sha`（`repositories/models.py:233`）表示，`ProcessTrace.built_at_sha` / `SymbolCommunity.built_at_sha`（`codegraph/models.py:370,427`）对齐它。建议 `index_key = last_indexed_commit_sha`（单仓单分支下水位即索引键），并在 manifest 显式记录 `index_key_source="last_indexed_commit_sha"` 以便 Phase 140 演进为复合键。
- `commit_sha`（源码 checkout）：用 `Repository.head_sha`（`repositories/models.py:745`）或评测者显式 `--commit-sha` 传入并以 `head_sha` 校验。
- `gold_version`：gold 数据集 `manifest.json` 顶层字段，随数据演进递增。

### Pattern 3: macro 聚合防 overall 掩盖（BENCH-05）
**What:** 逐桶指标用「按 case 取平均」（macro）而非「按样本合并」（micro），稀疏桶标 `INSUFFICIENT_DATA` 且不计入 overall，受保护桶单列。
**When to use:** 所有质量指标。
**Example:**
```python
# Source: 复刻 repo_route_recall_eval.aggregate_report 的 macro 理由注释
# case 之间 expected 数量差异大 → micro 会让"样本多的桶"主导，掩盖小桶整体失败。
MIN_BUCKET_SAMPLES = 3  # 可配置；< 此值的桶标 INSUFFICIENT_DATA，不进 overall

def bucket_status(n: int) -> str:
    return "OK" if n >= MIN_BUCKET_SAMPLES else "INSUFFICIENT_DATA"
```

### Anti-Patterns to Avoid
- **复刻被测管线逻辑：** harness 内重写 symbol 检索或 impact 计算。后果：评测与生产漂移（recall eval 模块 docstring 明确「走生产 route，不复刻任何管线逻辑」）。改法：只调 `hybrid_search.search` / `analyze_impact` / `trace_path`。
- **从被测 codegraph 反导 resolved edge gold：** 用 `CallEdge.callee_symbol` 当 ground truth。后果：循环论证、自我打分（CONTEXT 硬禁）。改法：gold 来自独立 callsite 抽样标注，存 fixtures。
- **baseline 内嵌阈值/compare：** 复制 `compare_to_baseline` 进报告。后果：违反「产物不含预填/推断阈值」。改法：报告只有原始值 + `INSUFFICIENT_DATA` 标记，阈值字段留空，比对逻辑属 Phase 140。
- **混水位拼接证据：** index sha 与 gold sha 不同仍硬跑。后果：`file:line` 成伪证据。改法：水位不一致即 INVALID 短路。
- **空 gold 记 Recall=1 / 无预测记 precision=1：** 掩盖真实退化。改法：空结果规则显式定义（见下表）。
- **micro 聚合：** 按样本合并。后果：overall 掩盖受保护桶退化。改法：macro + 受保护桶单列。

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| 符号/语义检索 | 自写检索或重排 | `services/retrieval/hybrid_search.py::search` / `rag_search.py::search_rag` | 既有 hybrid 已处理 dense+sparse/RRF；重写即漂移 |
| 影响面 | 自写 BFS/反向展开 | `services/code_graph/impact.py::analyze_impact` | 已处理 min_confidence 扩散单调性、bare_name 闸、跨仓标记 |
| 调用路径 | 自写最短路 | `services/code_graph/trace.py::trace_path` | 已处理方向语义、`node_not_in_graph`/`no_path`/`found` 三态 |
| 符号消歧 | 自写图内解析 | `services/code_graph/symbol_resolve.py::resolve_symbol_in_graph` | 已处理 in_graph/歧义候选 |
| 图装配/缓存/权限 | 自写取图或绕过 ACL | `services/code_graph/cache.py::GraphService.get_graph` / `.invalidate` | 唯一取图入口，`ensure_repository_readable` fail-closed 内置；invalidate 提供冷路径 |
| 指标统计 | NumPy/pandas/`ir_measures` | stdlib `statistics` + 复刻 `aggregate_report` | 零新增依赖硬约束；macro/CI 模式已有先例 |
| 凭证/异常脱敏 | 自写正则 | `common.logging.redact_secrets_in_text` / `interactions.redaction.redact_for_ledger` | 观测强约束指定入口 |

**Key insight:** 本阶段的价值不在「会算指标」，而在「指标口径可复现、水位可核验、阈值零污染」。所有领域复杂问题（检索、图分析、消歧、脱敏）都已被既有 v0.22 能力解决——hand-roll 任何一项都会引入与生产的口径漂移，直接摧毁 baseline 的可比性。

## Runtime State Inventory

> 本阶段为**纯新增**（新 harness + 新 gold 数据集），不改名/不重构既有符号，故多数类别为空。显式标注如下。

| Category | Items Found | Action Required |
|----------|-------------|------------------|
| Stored data | None — 评测只读，不写 `ProcessTrace`/`Symbol`/`CallEdge`/生产索引（CONTEXT 明确「不写生产索引」） | 无数据迁移 |
| Live service config | None — 不改 n8n/Qdrant collection/Datadog 等外部配置 | 无 |
| OS-registered state | None | 无 |
| Secrets/env vars | None — 不新增凭证；复用既有 provider 凭证解析（embedding 走 `embed_query` 既有链） | 无 |
| Build artifacts | 新增 `server/tests/fixtures/graph_bench/*.json` 与两份 py 模块 | 版本化提交；baseline JSON 为生成物，刷新方式写入 README |

**Nothing found in category:** Stored data / Live service config / OS-registered state / Secrets — 均经上文核验为空（只读评测，零写生产状态）。

## 水位与评测身份（BENCH-01 核心）

**三方水位来源（已核对于源码）：**

| 水位 | 字段 | 位置 |
|------|------|------|
| 索引水位 | `Repository.last_indexed_commit_sha`（CharField, max_length=40） | `server/repositories/models.py:233` |
| Process/Community 派生水位 | `ProcessTrace.built_at_sha` / `SymbolCommunity.built_at_sha`（对齐 `last_indexed_commit_sha`） | `server/codegraph/models.py:370,427` |
| 源码 checkout 水位 | `Repository.head_sha`（RepositoryBranchIndex 亦有 `head_sha`） | `server/repositories/models.py:745,299` |
| gold 标注水位 | gold `manifest.json.annotated_at_sha`（新增，随数据集版本化） | `server/tests/fixtures/graph_bench/manifest.json` |

**校验规则：** `index_built_at_sha == gold_annotated_at_sha == source_checkout_sha`，三者均非空且相等 → `OK`；否则 → `INVALID` 短路，run 不产出任何可比较结论。`ProcessTrace.built_at_sha` 与该值不一致时同样判 INVALID（防投影漂移）。

**注意（已知缺口，须在计划处理）：** `_resolve_built_at_sha`（`process_trace.py:380` / `community.py:252`）当前**只按 `repository_id` 取值，不带 `branch_name`**——多分支场景下水位可能读到 base 分支。评测身份五元组含 `branch`，harness 校验时必须按 `(repository_id, branch)` 取水位，不能只按仓。这与 ARCHITECTURE.md 记录的「`backfill_symbol_resolution`/`SymbolResolver.backfill` 只按 `repository_id` 查询、必须把 `branch_name` 贯穿」是同一类 branch 缺口，但本阶段**只读校验**，需在 harness 侧用 `branch` 过滤，不修改被测写入逻辑。

## v0.22 被测能力入口（BENCH-03 直接调用，不修改）

| 能力 | 入口 | 位置 | 形态 |
|------|------|------|------|
| 取图（含权限/缓存/冷热） | `GraphService.get_graph(repository_id, branch, user=...)` / `.invalidate(repository_id)` | `services/code_graph/cache.py:674,615` | async；`ensure_repository_readable` fail-closed；LRU 缓存；invalidate 强制冷 |
| 符号消歧 | `resolve_symbol_in_graph(graph.graph, symbol_id=...)` | `services/code_graph/symbol_resolve.py:175` | 纯函数，作用于冻结图 |
| 影响面 | `analyze_impact(graph, seed_symbol_id, max_depth=..., min_confidence=..., ...)` | `services/code_graph/impact.py:483` | 纯函数，返回结构化 dict，`seed_in_graph=False` 区分「不存在」vs「无影响」 |
| 调用路径 | `trace_path(graph, source_symbol_id, target_symbol_id, ...)` | `services/code_graph/trace.py:228` | 纯函数，`found`/`reason`（`node_not_in_graph`/`no_path`）三态，非空数组 |
| Symbol 检索 lane | `HybridSearch.search(...)` | `services/retrieval/hybrid_search.py:256` | async，dense+sparse hybrid |
| RAG 检索 | `search_rag(...)` | `services/retrieval/rag_search.py:87` | async |
| Process 事实源 | `ProcessTrace`（`steps`/`entry_endpoint`/`built_at_sha`） | `codegraph/models.py:~405` | ORM 只读 |
| resolved edge 事实源 | `CallEdge.callee_symbol`/`callee_file`/`callee_qualifier` | `codegraph/models.py:97` | ORM 只读；**仅作预测侧，不作 gold** |

**嵌入 query：** 复用 `services.query_embedding.embed_query`（recall command 已用），沿用既有 provider 凭证解析，不读 env。

## 指标集与空结果规则（BENCH-04）

| 指标 | 固定分母 | 空结果规则 | 被测入口 |
|------|----------|-----------|----------|
| NL→Symbol Recall@5 | 该 case gold symbol 数（`len(expected_symbols)`） | gold 为空 → 该 case 不计入此指标（分母 0，标 `NO_GOLD`，非 Recall=1）；预测为空且 gold 非空 → Recall=0 | `hybrid_search.search` |
| NL→Process Recall@3 | 该 case gold process 数 | 同上；**禁止名称模糊命中**——命中以 gold `process_key`/UID 精确匹配计 | `ProcessTrace` + 检索 lane |
| resolved edge precision | 该 case 预测 resolved 边数 | 无预测 → precision=`N/A`（不计入平均，非 1.0） | `CallEdge`（预测）vs 独立 callsite gold |
| resolved edge recall | 该 case gold 调用边数 | gold 空 → `NO_GOLD`，不计入 | 同上 |
| impact precision | 预测受影响 symbol 数 | 无预测 → `N/A`；`seed_in_graph=False` → 该 case 标 `SEED_MISSING` 单列，不计 precision | `analyze_impact` |
| trace 成功率 | 该 case gold 路径查询数 | `found=True` 计成功；`reason=no_path` 计失败路径；`node_not_in_graph` 单列（不计入成功率分母） | `trace_path` |
| trace 错误路径率 | 同上分母 | `found=True` 但路径与 gold 不一致 / 走错向 → 计错误路径 | `trace_path` |
| 冷延迟 | 每 case 首次 run（invalidate 后） | 仅记录，不参与质量门 | `invalidate`→`get_graph`+能力 |
| 热延迟 | 每 case 重复 run（缓存命中） | 仅记录 | `get_graph`（LRU 命中）+能力 |
| token | 该 case 全部 LLM/embedding 调用 token 和 | 复用 `ModelUsageRecord` 口径；无 LLM 调用（纯检索/图）记 0 | 观测埋点 |

**统一原则（沿袭 PITFALLS B0）：** 空 gold ≠ 满分；无预测 ≠ 满分；`found=False` ≠ 空数组；`seed_in_graph=False` 与「无影响」必须分开。所有 `N/A`/`NO_GOLD`/`SEED_MISSING`/`node_not_in_graph` 在报告中显式单列，绝不静默并入分母或记 1.0。

## 分桶与 INSUFFICIENT_DATA（BENCH-05）

**分桶维度派生（本仓字段已核验）：**

| 维度 | 派生来源 | 说明 |
|------|----------|------|
| 语言 | `Symbol.file_path` 扩展名（`.py`/`.ts`/`.tsx`/`.js`/`.go`…） | Symbol 无独立 `language` 字段，从路径派生；gold 记录显式 `language` 以免派生歧义 |
| 框架 | 入口上下文（`Endpoint` 存在 + handler 特征 / 路径约定） | 无显式 `framework` 字段；gold 记录显式 `framework`（如 `django`/`vue`/`gin`），由标注者填写 |
| 入口类型 | 是否 `Endpoint` handler / `ProcessTrace` entry / 普通 symbol | gold 记录显式 `entry_type`（`http_endpoint`/`process_entry`/`plain_symbol`） |
| call shape | 调用形态闭集（`direct`/`member`/`import_alias`/`receiver`/`from_import`…） | 仅 resolved edge gold 需要；gold 记录显式 `call_shape` |

**结论：** 因 `Symbol`/`Endpoint` 模型缺显式 `language`/`framework` 字段，**gold schema 必须把四个分桶维度作为必填标注字段**（语言/框架/入口类型/call shape），不从被测图派生——这既保证 BENCH-05 分桶稳定，也强化「gold 独立于被测图」的防反导约束。

**稀疏桶：** `n < MIN_BUCKET_SAMPLES`（建议默认 3，可配置）→ 该桶标 `INSUFFICIENT_DATA`，单列展示且**不计入 overall**。受保护桶（标注 `protected=true`）单独列出，其退化不得被 overall 提升抵消（macro 聚合 + 单列）。

## 冻结数据集与 gold schema（BENCH-02）

**落地：** `server/tests/fixtures/graph_bench/`（沿袭 `repo_route_recall/`、`layered_search_golden/`、`blueprint_golden/`、`semgrep/` 的版本化 fixtures 约定）。三切分为独立文件：`dev.json`、`locked_test.json`（baseline 用）、`holdout.json`（Phase 140 最终验收，baseline 不读）。

**manifest.json（数据集级）：**
```json
{
  "gold_version": "1",
  "annotated_at_sha": "<冻结 commit SHA>",
  "repository": "<repo 标识>",
  "branch": "<branch>",
  "splits": {"dev": "dev.json", "locked_test": "locked_test.json", "holdout": "holdout.json"},
  "_doc": "gold 来自独立标注，禁止从被测 codegraph 反向导出；resolved edge gold 来自独立 callsite 抽样。"
}
```

**case schema（每条，分桶维度必填）：**
```json
{
  "case_id": "dev-0001",
  "split": "dev",
  "query": "<自然语言 query>",
  "language": "python|typescript|javascript|go",
  "framework": "django|vue|gin|none",
  "entry_type": "http_endpoint|process_entry|plain_symbol",
  "expected_symbols": [{"uid": "...", "file_path": "...", "start_line": 0, "name": "..."}],
  "expected_processes": [{"process_key": "...", "name": "..."}],
  "edge_golds": [{"caller_uid": "...", "callee_uid": "...", "call_shape": "direct|member|import_alias|receiver|from_import", "evidence_file_line": "..."}],
  "trace_golds": [{"source_uid": "...", "target_uid": "..."}],
  "impact_golds": [{"seed_uid": "...", "expected_affected_uids": ["..."]}],
  "protected": false
}
```

**防循环论证：** `edge_golds` 的 `callee_uid` 来自独立 callsite 抽样人工/规则标注，`evidence_file_line` 记录人工核验锚点；**禁止**用 `CallEdge.callee_symbol` 现值回填 gold。README 显式声明此约束。

## Common Pitfalls

### Pitfall 1: 「同仓」却不同 commit
**What goes wrong:** index sha、gold sha、checkout sha 不一致仍跑，`file:line` 指向错误代码。
**Why it happens:** 多分支/重建后水位字段未对齐；`_resolve_built_at_sha` 只按仓不按分支取值。
**How to avoid:** run 前三方校验，任一不一致/为空即 INVALID 短路；校验按 `(repository_id, branch)` 取水位。
**Warning signs:** 同一 case 重复跑结果漂移；`built_at_sha` 与 `head_sha` 不同。

### Pitfall 2: 分母/命中规则未锁
**What goes wrong:** 空 gold 记 Recall=1；无预测记 precision=1；Process 名称模糊命中计为命中。
**Why it happens:** 沿用「expected 空记 1.0」的旧直觉（recall eval `_recall` 正是这么写的，但那是 routing 场景、不适用于本阶段质量指标）。
**How to avoid:** 空结果规则表（见上）显式定义 `NO_GOLD`/`N/A`/`SEED_MISSING` 并单列；Process 命中以 `process_key`/UID 精确匹配。
**Warning signs:** 某指标 100% 但人工抽查大量漏召。

### Pitfall 3: overall 掩盖分桶退化
**What goes wrong:** 某语言/入口桶大幅退化，但 overall 因大桶提升而显示「无回归」。
**Why it happens:** micro 聚合让样本多的桶主导；稀疏桶未隔离。
**How to avoid:** macro（按 case 平均）+ 按 语言×框架×入口类型 分桶 + `INSUFFICIENT_DATA` 隔离 + 受保护桶单列。
**Warning signs:** overall 升但单桶 P/R 降。

### Pitfall 4: 先调算法再补 baseline / baseline 内嵌阈值
**What goes wrong:** 在冻结 baseline 前改 resolver/权重，或把阈值写进报告。
**Why it happens:** 沿用 recall eval 的 `compare_to_baseline` + tolerance 范式。
**How to avoid:** 本阶段 harness **不含 compare/gate**，报告只产原始值；阈值字段留空待 Phase 140 独立 review；禁止测试失败自动刷新 baseline。
**Warning signs:** baseline JSON 出现 `tolerance`/阈值字段。

### Pitfall 5: 从被测图反导 gold（循环论证）
**What goes wrong:** 用 `CallEdge` 现值当 resolved edge gold，等于让被测系统给自己打分。
**How to avoid:** gold 独立 callsite 标注，存 fixtures，README 声明禁反导。
**Warning signs:** edge recall 恒为 1.0。

### Pitfall 6: 观测反噬 / 高频 INFO 刷屏
**What goes wrong:** 逐 case 逐边 INFO 日志；观测异常中断评测。
**How to avoid:** 生命周期事件 `category=caller`（每 run 一次），逐 case/逐边计数与分层耗时 `category=sampling`；只记长度/hash/计数/闭集枚举，**不记 query 正文**；异常走 `redact_secrets_in_text`；观测 best-effort（recall command 的 `try/except pass` 模式）。

## Code Examples

### 水位校验（纯函数，可单测）
```python
# Source: 复刻 repo_route_recall_eval 纯函数风格；规则见 PITFALLS B0
def validate_watermark(
    *, index_built_at_sha: str, gold_annotated_at_sha: str, source_checkout_sha: str
) -> str:
    if not (index_built_at_sha and gold_annotated_at_sha and source_checkout_sha):
        return "INVALID"
    return "OK" if len({index_built_at_sha, gold_annotated_at_sha, source_checkout_sha}) == 1 else "INVALID"
```

### Recall（固定分母 + 空 gold 不得满分）
```python
# Source: 改造 repo_route_recall_eval._recall（原实现 expected 空记 1.0，本阶段改为 NO_GOLD）
def recall_at_k(expected: list[str], predicted_top_k: list[str]) -> float | str:
    if not expected:
        return "NO_GOLD"  # 不计入平均，非 1.0
    got = set(predicted_top_k)
    return sum(1 for e in expected if e in got) / len(expected)
```

### 冷/热延迟采集（command 侧）
```python
# Source: 复用 GraphService.invalidate + get_graph（cache.py:615,674）
from services.code_graph.cache import GraphService
svc = GraphService(...)
await sync_to_async(svc.invalidate)(repository_id)   # 强制冷
t0 = time.perf_counter(); graph = await svc.get_graph(repository_id, branch, user=None)
cold_ms = (time.perf_counter() - t0) * 1000
t0 = time.perf_counter(); graph = await svc.get_graph(repository_id, branch, user=None)  # LRU 命中
warm_ms = (time.perf_counter() - t0) * 1000
```

### 观测埋点（生命周期 caller + 逐 case sampling）
```python
# Source: 复刻 evaluate_repo_route_recall._LOG_KV 与 gaosan_eval 的 sampling 模式
logger.info("graph_bench_run_completed", category="caller", component="codegraph",
            initiated_by_user_id="system", repository=repo, branch=branch,
            commit_sha=sha, gold_version=gv, total_cases=n, duration_ms=ms)
logger.info("graph_bench_case_scored", category="sampling", component="codegraph",
            initiated_by_user_id="system", case_id=cid, language=lang,
            symbol_recall=r, duration_ms=ms)  # 不记 query 正文
```

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| 离线 golden（内联 node_hits，零 I/O） | 端到端 Recall + 分层归因（纯模块 + 薄 command） | recall eval 引入（2026-08 前） | 召回层天花板可见；本阶段复刻其分工 |
| baseline 内嵌 compare + tolerance | **原始 baseline 无阈值**（本阶段） | Phase 133 | 阈值决策权移交 Phase 140 独立 review，防旧缺陷固化 |
| 单 overall 指标 | 逐桶 + macro + `INSUFFICIENT_DATA` + 受保护桶单列 | 本阶段（PITFALLS B0） | overall 不再掩盖语言/入口退化 |

**Deprecated/outdated:**
- `compare_to_baseline` 用于本阶段报告：阈值语义属 Phase 140，本阶段产物**禁止**包含。
- routing 场景 `_recall` 的「expected 空记 1.0」：不适用于本阶段质量指标（空 gold 应 `NO_GOLD`）。

## Project Constraints (from CLAUDE.md)

- **沿用既有栈：** Django 5.1+/Python 3.14，async ORM 走 `sync_to_async`；不引入新框架/服务。
- **Convention:** 不绕过既有 service 层与权限；harness 调被测能力走生产入口（`GraphService.get_graph` 含 fail-closed 权限闸），不直连 ORM 绕 ACL。
- **运行时零新增生产依赖**（REQUIREMENTS Out of Scope 钉死）：不为 benchmark 引入 NumPy/pandas/`ir_measures`/新搜索服务。
- **可观测性强约束（强制）：** structlog `get_logger(__name__)`；事件 snake_case；关键生命周期带 `duration_ms`；每事件设 `category`（`caller`/`sampling`）与 `component`；CLI/后台触发标 `initiated_by_user_id="system"`；脱敏走 `redact_credentials`/`redact_secrets_in_text`，入库走 `redact_for_ledger`；指标与留痕分离（指标→`RequestMetric`/`ModelUsageRecord`，召回内容→`RetrievalTrace`）；观测 best-effort 不反噬业务；高频循环禁 INFO 刷屏。
- **注释/文档字符串可用中文（zh-CN）**，符合后端惯例。

## Assumptions Log

| # | Claim | Section | Risk if Wrong |
|---|-------|---------|---------------|
| A1 | `index_key` 以 `last_indexed_commit_sha` 充当（单仓单分支下水位即索引键），manifest 记 `index_key_source` 待 Phase 140 演进复合键 | Pattern 2 / 水位 | 若 Phase 140 需区分「同 sha 不同索引代际」，需扩展 `index_key`；但 manifest 已留 `index_key_source` 字段，可平滑升级 |
| A2 | `MIN_BUCKET_SAMPLES` 默认 3（可配置） | 分桶 / Pattern 3 | 阈值偏小会让稀疏桶误标 OK；但这是报告分桶口径而非回归门，调整不影响 baseline 原始数据 |
| A3 | 框架维度由标注者显式填写（`Symbol`/`Endpoint` 无显式 `framework` 字段） | 分桶 / gold schema | 若框架可从路径/依赖可靠派生，可减少标注成本；但显式标注更稳且强化防反导 |
| A4 | 冷/热以 `invalidate` 后首跑 vs 缓存命中复跑区分 | 指标集 / Code Examples | per-worker LRU 意味着跨进程不共享缓存；评测单进程串行执行（沿袭 recall command 串行理由：并发撞限流且延迟失真），故此口径成立 |

**说明：** A1–A4 均为口径默认值，不涉及被测能力逻辑或阈值；`_resolve_built_at_sha` 的 branch 缺口已在「水位」节作为**已核验事实**（非假设）记录。

## Open Questions

1. **gold 数据集的初始标注规模与来源**
   - What we know: 需要 dev/locked_test/holdout 三切分，覆盖 语言×框架×入口类型 分桶；resolved edge gold 需独立 callsite 抽样。
   - What's unclear: 目标仓选定（评测用哪个已索引 repo + 冻结哪个 commit SHA）、各 split 的 case 数量下限、由谁/如何完成独立 callsite 标注。
   - Recommendation: 计划阶段定一个最小可行规模（每保护桶 ≥ MIN_BUCKET_SAMPLES），先用一个已索引仓 + 其 `last_indexed_commit_sha` 冻结；标注可作为 plan 内独立 task。holdout 可先建空壳/schema，留 Phase 140 填充。

2. **token 指标对「纯检索/图 case」的口径**
   - What we know: `ModelUsageRecord` 已有 token 留痕；但本阶段多数能力（hybrid 检索、impact、trace）不走 LLM。
   - What's unclear: embedding 调用的 token 是否计入、如何与 `ModelUsageRecord` 关联到具体 benchmark run。
   - Recommendation: 报告中 token 以「该 case 全部 embedding+LLM 调用 token 和」计，纯图 case 记 0；关联键用 run_id。复用现有 `embed_query` 链的计量，不为评测新增计量通道。

3. **`ProcessTrace.built_at_sha` 的 branch 精度**
   - What we know: `_resolve_built_at_sha` 只按 `repository_id` 取值，不带 branch（已核验）。
   - What's unclear: 评测目标若是非 base 分支，水位校验是否会把 base 分支 sha 误判为一致。
   - Recommendation: harness 校验按 `(repository_id, branch)` 取 `last_indexed_commit_sha`（RepositoryBranchIndex 有 per-branch `last_indexed_commit_sha`/`head_sha`，见 `repositories/models.py:745-747`），避免依赖 `built_at_sha` 的仓级取值；必要时把 branch 精度修正列为后续相位的写入侧任务（本阶段只读不改）。

## Environment Availability

| Dependency | Required By | Available | Version | Fallback |
|------------|------------|-----------|---------|----------|
| Python | harness + 被测能力 | ✓ | 3.14.6 | — |
| uv | 依赖/运行 | ✓ | 0.11.8 | — |
| pytest | 纯函数单测 | ✓ | 9.0.2（锁） | — |
| Django ORM + 已索引仓 | 水位/gold 维度/被测能力 | 运行时依赖 | — | 无（须先有已索引目标仓） |
| Qdrant + embedding provider | Symbol/Process 检索 lane | 离线 CI 不可达（本次探测 localhost:6333 无响应） | — | 检索 lane case 标记 `integration`/`perf`，默认套件排除；纯函数指标逻辑不依赖 |
| NetworkX | impact/trace | ✓（锁 3.6.1） | 3.6.1 | — |

**Missing dependencies with no fallback:**
- 已索引的目标仓（含 `last_indexed_commit_sha`）：baseline 必须有真实冻结仓 + commit。这是数据前置条件而非工具缺失；计划须含「选定并冻结目标仓」任务。

**Missing dependencies with fallback:**
- Qdrant/embedding（离线不可达）：检索 lane 的端到端 case 标记 `integration`/`perf`（默认 `--disable-socket` + `-m 'not perf and not integration ...'` 排除，沿袭 `evaluate_repo_route_recall` 不进默认套件的既定做法）；指标/分桶/水位等纯逻辑在默认套件可测。

## Validation Architecture

> `workflow.nyquist_validation` 在 `.planning/config.json` 为 `true`（已核验），故本节必填。

### Test Framework
| Property | Value |
|----------|-------|
| Framework | pytest 9.0.2（`asyncio_mode=auto`，`pytest-asyncio`，`--disable-socket` 默认） |
| Config file | `server/pyproject.toml`（`[tool.pytest.ini_options]`，addopts 排除 `perf`/`integration`/`slow`/`postgres_queue`） |
| Quick run command | `cd server && uv run pytest tests/codegraph/test_graph_bench_eval.py -x` |
| Full suite command | `cd server && uv run pytest tests/codegraph/test_graph_bench_eval.py tests/codegraph/test_graph_bench_watermark.py -v`（端到端检索 case 另走 `-m integration`） |

### Phase Requirements → Test Map
| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| BENCH-01 | 三方水位一致→OK；任一不一致/空→INVALID 短路；manifest 含五元组 | unit（纯函数） | `pytest tests/codegraph/test_graph_bench_watermark.py -x` | ❌ Wave 0 |
| BENCH-02 | gold schema 校验（分桶维度必填、gold_version/annotated_at_sha 存在）；三切分加载 | unit（纯函数，读 fixtures 不走网络） | `pytest tests/codegraph/test_graph_bench_gold_schema.py -x` | ❌ Wave 0 |
| BENCH-03 | 报告只含原始值，无 `tolerance`/阈值字段；逐 case + 逐桶结构齐全 | unit（纯函数，断言报告 schema） | `pytest tests/codegraph/test_graph_bench_eval.py -x` | ❌ Wave 0 |
| BENCH-04 | Recall@5/@3、edge P/R、impact precision、trace 三态、空结果规则（NO_GOLD/N/A/SEED_MISSING）正确 | unit（纯函数） | `pytest tests/codegraph/test_graph_bench_eval.py -x` | ❌ Wave 0 |
| BENCH-05 | 分桶正确；n<阈值→`INSUFFICIENT_DATA` 且不进 overall；macro 聚合；受保护桶单列 | unit（纯函数） | `pytest tests/codegraph/test_graph_bench_eval.py -x` | ❌ Wave 0 |
| BENCH-01/03 (e2e) | 真跑已索引仓：水位校验→调被测能力→产 manifest+baseline（打真实 Qdrant/embedding） | integration（默认排除） | `pytest tests/codegraph/test_graph_bench_integration.py -m integration` | ❌ Wave 0（可选手动） |

### Sampling Rate
- **Per task commit:** `cd server && uv run pytest tests/codegraph/test_graph_bench_eval.py tests/codegraph/test_graph_bench_watermark.py -x`
- **Per wave merge:** `cd server && uv run pytest tests/codegraph/ -k graph_bench -v`
- **Phase gate:** 上述全绿 + `uv run ruff check codegraph/services/graph_bench_eval.py codegraph/management/commands/evaluate_graph_bench.py` + `uv run mypy` 通过后，再 `/gsd-verify-work`。

### Wave 0 Gaps
- [ ] `server/tests/codegraph/test_graph_bench_eval.py` — 覆盖 BENCH-03/04/05（指标、空结果规则、分桶、INSUFFICIENT_DATA、无阈值断言）
- [ ] `server/tests/codegraph/test_graph_bench_watermark.py` — 覆盖 BENCH-01（三方水位一致/不一致/空 → OK/INVALID；五元组 manifest）
- [ ] `server/tests/codegraph/test_graph_bench_gold_schema.py` — 覆盖 BENCH-02（gold schema 校验、分桶维度必填、三切分加载）
- [ ] `server/tests/fixtures/graph_bench/{manifest,dev,locked_test,holdout}.json` + `README.md` — gold 数据集骨架（schema 先行，case 填充可为计划 task）
- [ ] （可选）`server/tests/codegraph/test_graph_bench_integration.py` — `-m integration` 端到端真跑，默认套件排除
- [ ] Framework install: 无 — pytest 已就位

## Security Domain

> `security_enforcement` 在 `.planning/config.json` 为 `true`（已核验）。本阶段为只读评测 harness，攻击面小，但仍有以下适用项。

### Applicable ASVS Categories

| ASVS Category | Applies | Standard Control |
|---------------|---------|------------------|
| V2 Authentication | no | CLI/后台触发，无用户登录面；触发标 `system` |
| V3 Session Management | no | 无会话 |
| V4 Access Control | **yes** | 复用 `GraphService.get_graph` 内 `ensure_repository_readable` + exclusion fail-closed；harness 不绕过、不直连 ORM 取图 |
| V5 Input Validation | **yes** | gold fixtures 与 `--commit-sha`/`--repo` 等 CLI 输入经 schema/格式校验；gold JSON 用 Pydantic/dataclass 校验后使用 |
| V6 Cryptography | no | 不处理凭证；embedding 复用既有 provider 凭证解析（不读 env、不打印） |

### Known Threat Patterns for Django 只读评测 harness

| Pattern | STRIDE | Standard Mitigation |
|---------|--------|---------------------|
| 跨仓/越权读图（串图） | Elevation of Privilege | `ensure_repository_readable` fail-closed 已内置于 `get_graph`；harness 复用不绕过（T-121 已登记） |
| gold 数据被被测图污染（循环论证） | Tampering | gold 独立标注、版本化、禁反导；水位不一致 INVALID |
| query 正文/凭证写入日志 | Information Disclosure | 只记长度/hash/计数/闭集枚举；异常走 `redact_secrets_in_text`，ledger 走 `redact_for_ledger` |
| 观测异常反噬评测 | Denial of Service | 观测 best-effort（`try/except`），失败不中断 run |
| CLI 输入注入（repo/sha 拼接） | Tampering | 输入校验 + 参数化 ORM 查询，不拼 SQL/shell |

## Sources

### Primary (HIGH confidence)
- `server/codegraph/services/repo_route_recall_eval.py` — 纯函数指标模块范式（macro 聚合理由、`_recall`、分层归因、`compare_to_baseline`/tolerance 语义）
- `server/codegraph/management/commands/evaluate_repo_route_recall.py` — 薄 command 范式（fixtures 加载、串行真跑、structlog `_LOG_KV`、baseline 写/比对、不打默认套件）
- `server/codegraph/services/repo_router_eval.py` — golden gate + per-case diff + baseline JSON 形态
- `server/services/process_runtime/gaosan_eval.py` — sampling 埋点 + alias 归一 + 门槛评分范式
- `server/services/code_graph/{cache,impact,trace,symbol_resolve,process_trace}.py` — 被测能力入口签名、权限 fail-closed、冷/热控制、`_resolve_built_at_sha` branch 缺口
- `server/services/retrieval/{hybrid_search,rag_search}.py` — 检索 lane 入口
- `server/codegraph/models.py` / `server/repositories/models.py` — `built_at_sha`/`last_indexed_commit_sha`/`head_sha`/`Symbol`/`Endpoint`/`CallEdge`/`ProcessTrace` 字段（水位与分桶维度核验）
- `server/interactions/models.py` / `server/system/models.py` / `server/common/logging.py` / `server/common/log_context.py` / `server/interactions/redaction.py` — `RetrievalTrace`/`ModelUsageRecord`/`RequestMetric`/脱敏/上下文绑定
- `server/pyproject.toml` / `.planning/config.json` — pytest markers、`asyncio_mode`、`nyquist_validation=true`、`security_enforcement=true`
- `.planning/research/{SUMMARY,ARCHITECTURE,FEATURES}.md` + `133-CONTEXT.md` + `.planning/REQUIREMENTS.md` — 阶段边界、锁定决策、PITFALLS B0

### Secondary (MEDIUM confidence)
- `server/tests/fixtures/{repo_route_recall,layered_search_golden,blueprint_golden,semgrep}/` — fixtures 版本化目录约定（gold 数据集落地位置推断依据）

### Tertiary (LOW confidence)
- 无（排序权重/回归阈值按约束刻意不定；A1–A4 口径默认值已入 Assumptions Log）

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH — 全为本仓已锁依赖与既有入口，零新增，逐一核对于源码与锁文件
- Architecture: HIGH — 评测 harness 范式（纯模块+薄 command+golden 报告）直接复刻本仓 recall/golden eval；水位字段逐字段核对
- Pitfalls: HIGH — PITFALLS B0 与本仓 `_recall`/`compare_to_baseline`/`_resolve_built_at_sha` 实际实现交叉验证

**Research date:** 2026-08-24
**Valid until:** 2026-09-23（30 天 — 评测模式与水位字段为稳定内部接口，但 `_resolve_built_at_sha` branch 缺口若在后续相位被修正，水位校验节需同步）
