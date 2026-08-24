# Phase 140: Threshold policy 与整体收口 - Context

**Gathered:** 2026-08-24
**Status:** Ready for planning
**Mode:** Autonomous smart discuss（所有 grey area 按 Recommended 自动采纳）

<domain>
## Phase Boundary

在 Phase 133 冻结的同仓、同 branch、同 commit、同 query/gold、同 evaluator 基准上，独立锁定可审查且不可被测试自动改写的 threshold policy；用同一 harness 比较 v0.22 baseline 与 v0.24 candidate，保留运行身份、命令、配置、排序版本和逐例 diff。overall、受保护桶、TS/JS、Python、Process、impact、trace、冷/热延迟与 token 各自过门，禁止聚合提升抵消局部退化。同时补齐 graph query caller 生命周期和 resolver、Process、检索 lane、impact sampling 观测，完成权限、排除、脱敏、触发用户、partial/degradation、契约 hash 与同水位的整体回归。

本阶段不深化 Go resolver，不宣称真实跨仓 impact 可用，不翻转 LSP 默认值，不新增前端或生产依赖。

</domain>

<decisions>
## Implementation Decisions

### Threshold policy 的来源与不可变性
- policy 作为独立、版本化、仓库内可审查的静态 JSON 产物存在，不嵌入 baseline 报告，也不由测试运行时生成。
- 阈值只读取 Phase 133 已冻结 baseline 的分布和明确的方向性规则；candidate 结果、失败测试和 holdout 结果均不得反向刷新 policy。
- policy 写明 schema/version、baseline identity/hash、适用 split、指标方向、允许退化量、受保护桶和样本不足规则；加载时 fail-closed 校验。
- baseline、policy、candidate 三者任一身份/hash/排序版本不匹配即比较结果 `INVALID`，不得输出通过结论。

### 同条件比较与证据产物
- 复用 `graph_bench_eval` 的 scorer、空结果规则与五元 run identity，增加独立 compare 层，不复制 evaluator 算法。
- v0.22 baseline 与 v0.24 candidate 必须使用完全相同的 repository、branch、commit SHA、gold version、split、case 集和 evaluator version。
- 比较报告同时保留 baseline/candidate manifest hash、policy hash、ranking version、可复现命令、逐 case diff、逐桶 diff 与最终 gate verdict。
- holdout 只在最终验收路径显式启用；默认开发回归仍用 locked test，避免日常运行泄漏或调参污染 holdout。

### 门禁粒度与稀疏桶
- overall 是必要但不充分条件；所有 policy 标记的受保护桶、TS/JS、Python、Process、impact、trace、冷/热延迟与 token gate 必须分别通过。
- 指标按既有方向比较：质量/成功率越高越好，错误路径率/延迟/token 越低越好；每项容差在 policy 中显式声明，禁止隐式默认。
- `INSUFFICIENT_DATA` 不伪装为通过：保持显式状态并记技术债；若 policy 要求的受保护桶样本充足却缺失，则 fail-closed。
- Go 仅报告现状，不作为阻塞门；FUTURE-01/02/03 保持 Future，不用合成绿替代真实生产证据。

### 可观测性与整体回归
- `GraphQueryService` 唯一 caller 生命周期保留 `code_graph_query_started/completed/failed`，带 `duration_ms`、`category=caller`、`component=code_graph`、用户和关联键；不记录 query 正文或凭证。
- resolver、Process 构建、Symbol/Process 检索 lane 与 impact 内部步骤统一用 `category=sampling`，高频事件用 debug/采样，不在循环中 INFO 刷屏。
- 异常文本经 `redact_secrets_in_text`，ledger 经 `redact_for_ledger`；所有观测 best-effort，失败不得改变业务响应。
- 整体回归必须覆盖权限/exclusion fail-closed、`initiated_by_user_id` 传播、partial/degradation、manifest hash、响应版本和同水位；不得通过 skip/delete 测试规避。

### Claude's Discretion
- policy 的具体阈值数值由 planner 根据冻结 baseline 原始分布、样本量和现有指标方向推导并在 RESEARCH/PLAN 中给出可审查理由。
- compare 模块、management command 与 fixture 的具体文件布局可沿用 Phase 133 的「纯函数 + 薄 I/O command」模式。

</decisions>

<code_context>
## Existing Code Insights

### Reusable Assets
- `server/codegraph/services/graph_bench_eval.py` 已锁定 run identity、水位校验、指标分母、空结果规则、分桶与无阈值 baseline 报告。
- `server/codegraph/management/commands/evaluate_graph_bench.py` 已提供只读评测、冷/热计时、run manifest、可复现命令及 caller/sampling 日志骨架。
- `server/tests/fixtures/graph_bench/` 已冻结 manifest、dev、locked_test、holdout 数据。
- `server/services/code_graph/query_service.py` 已有 graph query started/completed/failed caller 生命周期。
- resolver、`process_trace.py`、Qdrant/retrieval 与 impact 现有结构化事件可用于统一 sampling 口径。

### Established Patterns
- 评测采用纯函数 scorer + management command 薄 I/O，默认 pytest 网络隔离。
- 观测统一 `structlog.get_logger(__name__)`、snake_case 事件、kv 字段、`category`/`component`，异常和 ledger 分入口脱敏。
- 受保护桶与 `INSUFFICIENT_DATA` 已在 baseline 报告中单列，overall 不吸收它们。

### Integration Points
- 在 `codegraph.services.graph_bench_eval` 旁新增 policy/compare 纯函数层，并扩展或新增 management command 读取 baseline、candidate 与 policy。
- 回归测试放入 `server/tests/codegraph/`；observability 守护沿用 `server/tests/services/code_graph/test_access.py` 的静态事件契约检查。
- 完整收口测试覆盖 Phase 133–139 的 benchmark、resolver、Process、query service、MCP/Chat/task/npm conformance。

</code_context>

<specifics>
## Specific Ideas

- threshold policy 必须是人可审查、机器 fail-closed 的独立静态产物；测试只能读取，不能写回。
- 比较报告首先证明“条件相同”，其次才谈“candidate 更好”。
- 受保护桶和语言专项门不能被 overall 掩盖；稀疏数据如实标债。
- 所有 graph query 日志只记录身份、计数、状态、耗时和闭集元数据，不记录自然语言 query。

</specifics>

<deferred>
## Deferred Ideas

- 真实 `CrossRepoApiCall` / `ApiCallSite` 样本验证跨仓 impact → FUTURE-01。
- volar/gopls 默认翻转 → FUTURE-02。
- Go selector/interface receiver resolver 深化 → FUTURE-03。
- query cursor、`task_context`/`goal` 排序增强 → FUTURE-04/05。

</deferred>
