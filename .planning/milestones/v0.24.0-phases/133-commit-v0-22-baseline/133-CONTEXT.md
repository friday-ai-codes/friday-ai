# Phase 133: 同仓同 commit 基准与 v0.22 baseline - Context

**Gathered:** 2026-08-24
**Status:** Ready for planning
**Mode:** Autonomous smart discuss（所有 grey area 按 Recommended 自动采纳）

<domain>
## Phase Boundary

建立可复现、无阈值污染的 v0.22 原始基线。交付一个评测 harness：评测者用固定 repository、branch、commit SHA 运行 benchmark；当索引、gold 或源码水位不一致时把 run 标为 `INVALID`，绝不产出可比较结论。数据集有独立 dev / locked test / holdout 切分，resolved edge gold 来自独立 callsite 标注而非被测图反导。未修改的 v0.22 能力在冻结数据集上输出逐 case、逐语言/框架/入口桶的原始 baseline，产物中不出现预填或推断的回归阈值。报告同时给出 Symbol/Process recall、resolved edge、impact、trace、冷/热延迟与 token 的固定分母与空结果规则；稀疏桶显示 `INSUFFICIENT_DATA`，受保护桶不被 overall 掩盖。

本阶段只产出 baseline 与评测地基，**不锁定任何回归阈值**（阈值属 Phase 140，BENCH-06/07）。

</domain>

<decisions>
## Implementation Decisions

### 评测身份与水位一致性（BENCH-01）
- 每次 benchmark run 绑定唯一评测身份 `(repository, branch, commit_sha, index_key, gold_version)`，全部证据（Symbol、Process、调用边、`file:line`、impact）强制来自同一 commit SHA。
- run 前做水位校验：索引 `built_at_sha`、gold 标注 sha、源码 checkout sha 三者不一致即标 `INVALID` 并中止，不产出部分结论。
- 评测身份与校验结果写入 run manifest（结构化 JSON），供 Phase 140 同条件对比复用。

### 数据集切分与 gold 来源（BENCH-02）
- gold 数据落地为仓库内可版本化的冻结数据集（`.planning` 之外，独立于被测图），按 dev / locked test / holdout 三切分；baseline 只用 dev + locked test，holdout 留给最终验收。
- resolved edge gold 来自独立 callsite 抽样人工/规则标注，**禁止**从被测 codegraph 反向导出（防循环论证）。
- 每条 gold 记录语言、框架、入口类型、call shape 等分桶维度，供 BENCH-05 分桶。

### 原始 baseline 产出（BENCH-03）
- 直接调用既有 v0.22 能力（`services/code_graph/*`、`retrieval/*`、`codegraph/resolver/*`）在冻结数据集上跑 baseline，不修改其逻辑。
- 产物为逐 case 原始记录 + 逐桶聚合，**不含任何预填/推断的回归目标值**；阈值字段留空待 Phase 140。

### 指标、分母与空结果规则（BENCH-04、BENCH-05）
- 指标集：NL→Symbol Recall@5、NL→Process Recall@3、resolved edge precision/recall、impact precision、trace 成功率/错误路径率、冷/热延迟、token；每个指标锁定固定分母与空结果规则（空结果如何计入显式定义）。
- 全部质量指标按 语言 × 框架 × 入口类型 分桶；样本不足桶标 `INSUFFICIENT_DATA`；受保护桶单列，不被 overall 提升抵消。
- 评测模式只读，不写生产索引；冷/热延迟区分首次（冷）与重复（热）运行。

### Claude's Discretion
- harness 的具体模块布局、gold 数据 schema 细节、报告渲染格式由 Claude 依据现有 `repo_router_eval.py` / `repo_route_recall_eval.py` / `gaosan_eval.py` 评测模式决定，保持与既有 eval harness 同构。

</decisions>

<code_context>
## Existing Code Insights

### Reusable Assets
- `server/codegraph/services/repo_router_eval.py`、`repo_route_recall_eval.py`、`repo_router_replay.py` — 既有评测/replay harness 模式（逐 case、逐桶、可复现命令）。
- `server/services/process_runtime/gaosan_eval.py` — 最近的评测脚本样例。
- `server/services/code_graph/`（impact、trace、community、process_trace、symbol_resolve）与 `server/codegraph/resolver/`（base、python_import、frontend_import、symbol_resolver）— v0.22 被测能力。
- `server/services/retrieval/hybrid_search.py`、`rag_search.py` — Symbol/检索 lane。

### Established Patterns
- 评测走 management command / service 层脚本，结构化 JSON 报告，可复现命令记录（见 routing eval 系列）。
- structlog 事件 + `category`/`component` 字段（observability 强约束）。

### Integration Points
- 新增 benchmark harness 挂到 `server/codegraph/services/` 或 `server/services/code_graph/`，复用既有索引/commit 水位元数据；报告落 `.planning` 之外的可版本化目录或 artifacts 目录。

</code_context>

<specifics>
## Specific Ideas

- 评测身份五元组与 `INVALID` 短路是硬契约；水位不一致绝不产出结论。
- resolved edge gold 独立标注，杜绝从被测图反导。
- baseline 产物禁止出现任何阈值数字。

</specifics>

<deferred>
## Deferred Ideas

- 阈值锁定与同条件对比 → Phase 140（BENCH-06/07）。
- 真实 `CrossRepoApiCall` 跨仓样本验证 → FUTURE-01，不在本阶段。

</deferred>
