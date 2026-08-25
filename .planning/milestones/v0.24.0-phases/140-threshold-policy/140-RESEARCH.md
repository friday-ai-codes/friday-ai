# Phase 140: Threshold policy 与整体收口 - Research

**Researched:** 2026-08-24  
**Domain:** brownfield 收口——可审查 threshold policy、同条件 paired comparator、resolver 分层质量门与 graph query 可观测性  
**Confidence:** HIGH（架构、现有缺口、测试面均由当前源码与 Phase 133–139 产物核验）；MEDIUM（阈值数值必须等待真实冻结 baseline，当前不存在可合法推导数字的证据）

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions

**Threshold policy 的来源与不可变性**
- policy 作为独立、版本化、仓库内可审查的静态 JSON 产物存在，不嵌入 baseline 报告，也不由测试运行时生成。
- 阈值只读取 Phase 133 已冻结 baseline 的分布和明确的方向性规则；candidate 结果、失败测试和 holdout 结果均不得反向刷新 policy。
- policy 写明 schema/version、baseline identity/hash、适用 split、指标方向、允许退化量、受保护桶和样本不足规则；加载时 fail-closed 校验。
- baseline、policy、candidate 三者任一身份/hash/排序版本不匹配即比较结果 `INVALID`，不得输出通过结论。

**同条件比较与证据产物**
- 复用 `graph_bench_eval` 的 scorer、空结果规则与五元 run identity，增加独立 compare 层，不复制 evaluator 算法。
- v0.22 baseline 与 v0.24 candidate 必须使用完全相同的 repository、branch、commit SHA、gold version、split、case 集和 evaluator version。
- 比较报告同时保留 baseline/candidate manifest hash、policy hash、ranking version、可复现命令、逐 case diff、逐桶 diff 与最终 gate verdict。
- holdout 只在最终验收路径显式启用；默认开发回归仍用 locked test，避免日常运行泄漏或调参污染 holdout。

**门禁粒度与稀疏桶**
- overall 是必要但不充分条件；所有 policy 标记的受保护桶、TS/JS、Python、Process、impact、trace、冷/热延迟与 token gate 必须分别通过。
- 指标按既有方向比较：质量/成功率越高越好，错误路径率/延迟/token 越低越好；每项容差在 policy 中显式声明，禁止隐式默认。
- `INSUFFICIENT_DATA` 不伪装为通过：保持显式状态并记技术债；若 policy 要求的受保护桶样本充足却缺失，则 fail-closed。
- Go 仅报告现状，不作为阻塞门；FUTURE-01/02/03 保持 Future，不用合成绿替代真实生产证据。

**可观测性与整体回归**
- `GraphQueryService` 唯一 caller 生命周期保留 `code_graph_query_started/completed/failed`，带 `duration_ms`、`category=caller`、`component=code_graph`、用户和关联键；不记录 query 正文或凭证。
- resolver、Process 构建、Symbol/Process 检索 lane 与 impact 内部步骤统一用 `category=sampling`，高频事件用 debug/采样，不在循环中 INFO 刷屏。
- 异常文本经 `redact_secrets_in_text`，ledger 经 `redact_for_ledger`；所有观测 best-effort，失败不得改变业务响应。
- 整体回归必须覆盖权限/exclusion fail-closed、`initiated_by_user_id` 传播、partial/degradation、manifest hash、响应版本和同水位；不得通过 skip/delete 测试规避。

### Claude's Discretion
- policy 的具体阈值数值由 planner 根据冻结 baseline 原始分布、样本量和现有指标方向推导并在 RESEARCH/PLAN 中给出可审查理由。
- compare 模块、management command 与 fixture 的具体文件布局可沿用 Phase 133 的「纯函数 + 薄 I/O command」模式。

### Deferred Ideas (OUT OF SCOPE)
- 真实 `CrossRepoApiCall` / `ApiCallSite` 样本验证跨仓 impact → FUTURE-01。
- volar/gopls 默认翻转 → FUTURE-02。
- Go selector/interface receiver resolver 深化 → FUTURE-03。
- query cursor、`task_context`/`goal` 排序增强 → FUTURE-04/05。
</user_constraints>

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| BENCH-06 | baseline 采集完成后，以独立、可审查的 threshold policy 锁定回归门；测试失败不得自动刷新 baseline 或阈值 | 独立只读 JSON、内容 hash、baseline pin、无写回 comparator 与静态守卫；当前真实 baseline 尚缺，必须先设证据前置门。`[VERIFIED: REQUIREMENTS.md; 140-CONTEXT.md; graph_bench fixtures]` |
| BENCH-07 | v0.24 candidate 与 v0.22 baseline 使用同一仓、同一 commit、同一 query/gold 和同一 evaluator 运行，并保留可复现命令、配置、排序版本与逐例 diff | 分离 comparison identity 与 system-under-test identity；逐 case ID 严格配对；三份 artifact hash 与命令进入 compare report。`[VERIFIED: REQUIREMENTS.md; graph_bench_eval.py; evaluate_graph_bench.py]` |
| EDGE-06 | resolver 质量按 language × framework × call shape 分别统计 precision、recall、resolved、ambiguous、unresolved，TS/JS 与 Python 各自通过回归门；Go 深化不阻塞本里程碑 | 新增 edge-level outcome/cell 聚合；当前 `CaseOutcome` 丢失 call shape 与三态，必须补齐后才能设门。`[VERIFIED: REQUIREMENTS.md; graph_bench_eval.py; resolver/base.py; resolver/symbol_resolver.py]` |
| OBS-01 | graph query 生命周期产生 `started`/`completed`/`failed` 结构化事件，含 `duration_ms`、`category=caller`、`component`、触发用户与关联键，且不记录 query 正文或凭证 | 保留 service 唯一 started/completed/failed；补日志捕获测试，断言字段、关联键、best-effort 与 query sentinel 不出现。`[VERIFIED: REQUIREMENTS.md; query_service.py]` |
| OBS-02 | resolver、Process 构建、检索 lane 与 impact 的高频步骤使用 `sampling` 分类并按语言/call shape 记录计数和分层耗时，禁止 INFO 循环刷屏 | 定义内部事件闭集与静态/行为守卫；resolver 现仅全局三态汇总，lane 仍有 query 截断日志，需收口。`[VERIFIED: REQUIREMENTS.md; symbol_resolver.py; process_trace.py; process_index.py; rag_search.py; hybrid_search.py; impact.py]` |
</phase_requirements>

## Summary

Phase 140 不应被规划成“给现有 baseline JSON 加几个阈值字段”。现有 Phase 133 scorer、空结果规则、五元 identity、逐 case/逐桶报告和 INVALID 水位闸可以直接复用；但当前仓内 `manifest.json` 仍是 `REPLACE_WITH_*` 占位，dev/locked_test 各只有 3 条 seed case，holdout 为空，且真仓 OK baseline 从未执行。因此目前没有合法的 baseline 分布可用于填写任何具体阈值。`[VERIFIED: server/tests/fixtures/graph_bench/*; 133-02-SUMMARY.md; 133-04-SUMMARY.md; 133-VERIFICATION.md]`

现有 harness 还缺少 Phase 140 的两个关键维度：一是报告只按 `language×framework×entry_type` 分桶，`CaseOutcome` 不保留 edge 的 `call_shape`、`resolved/ambiguous/unresolved` 或逐 edge 结果；二是 command 的运行编排仍标注并执行 v0.22 测量映射，尚无显式 baseline/candidate system identity 与 paired compare 层。直接比较当前两份 aggregate 会让 EDGE-06 无法验收，也无法证明两次运行使用同一 case 集和 evaluator。`[VERIFIED: graph_bench_eval.py:492-748; evaluate_graph_bench.py:470-601; resolver/base.py:39-51]`

**Primary recommendation:** 先把 Phase 133 的人工债闭合成真实、不可变的 baseline artifact，再以“纯函数 policy loader/comparator + 薄 compare command”实现四态门禁；resolver 采用 edge-level cell 指标，观测采用一个 caller 生命周期加内部 sampling 摘要，最后用分层测试矩阵完成里程碑收口。任何 baseline/policy 证据未齐、身份不匹配、受保护桶缺失或 comparator 输入不完整都只能得到 `INVALID`/`INSUFFICIENT_DATA`，不能得到 `PASS`。`[RECOMMENDATION based on verified codebase constraints]`

## Architectural Responsibility Map

| Capability | Primary Tier | Secondary Tier | Rationale |
|------------|-------------|----------------|-----------|
| threshold policy 静态产物 | API / Backend（repo-owned JSON） | — | 只读输入，不进入 DB，不由测试生成；git diff 即审查面。`[VERIFIED: 140-CONTEXT.md]` |
| policy schema/hash 校验 | API / Backend（纯函数） | — | 确定性、零 I/O、fail-closed，适合默认 pytest 套件。`[RECOMMENDATION based on Phase 133 pattern]` |
| baseline/candidate compare | API / Backend（纯函数） | — | 只消费两份报告与 policy，复用 scorer 输出，不调用检索或 ORM。`[RECOMMENDATION based on graph_bench_eval.py]` |
| artifact 读取、hash 与报告落盘 | API / Backend（management command） | Filesystem | I/O 保持薄壳，与 Phase 133 分层一致。`[VERIFIED: evaluate_graph_bench.py]` |
| resolver edge 三态采集 | API / Backend（benchmark adapter） | Database / Storage（CallEdge） | `ResolveResult` 已含 status/language/call_shape，评测层应逐 edge 捕获而非只读 resolved FK。`[VERIFIED: resolver/base.py; codegraph/models.py]` |
| graph query caller 观测 | API / Backend（GraphQueryService） | SystemLogEntry | service 是五消费面的统一业务入口，现有三事件已在此。`[VERIFIED: query_service.py; Phase 139 summary]` |
| resolver/Process/lane/impact sampling | API / Backend（各内部 service） | Metrics/System logs | 内部步骤只发低基数字段与计数/耗时，不发 query 正文。`[VERIFIED: LOGGING-SPEC.md; observability rule]` |
| 完整回归 | API / Backend tests + task/npm package tests | 外部 Qdrant/已索引仓（最终 gate） | 默认套件验证契约；真实候选质量与延迟必须在同水位环境运行。`[VERIFIED: pyproject.toml; Phase 133/136/139 summaries]` |

## Critical Current-State Findings

### 1. 真实 baseline 是 Phase 140 的硬前置，不是可忽略的人工 UAT

- `manifest.annotated_at_sha` 与 `repository` 仍为占位符；当前文件本身会令真实运行水位校验 `INVALID`。`[VERIFIED: server/tests/fixtures/graph_bench/manifest.json]`
- dev/locked_test 是“最小 seed 集”，README 明确说真实冻结仓完整独立标注尚待完成；每个受保护桶尚未达到默认 `MIN_BUCKET_SAMPLES=3`。`[VERIFIED: graph_bench README; dev.json; locked_test.json]`
- holdout 仍为 `{ "cases": [] }`，因此当前无法执行最终 holdout 验收。`[VERIFIED: holdout.json]`
- Phase 133 verification 只收集了 integration test，未执行真仓 OK 路径。`[VERIFIED: 133-VERIFICATION.md]`

**规划含义：** Wave 0 必须产出并人工审查“目标仓/分支/commit、独立 gold、真实 v0.22 run manifest、baseline report、artifact hashes”。在这些文件存在前，policy 文件只能有 schema 测试，不能提交伪造阈值。`[RECOMMENDATION based on BENCH-06 fail-closed requirement]`

### 2. “同条件”需要分成 comparison identity 与 system identity

repository、branch、目标代码 commit、gold version、split、case-set hash、evaluator version 必须相同；baseline 与 candidate 的 Friday AI 实现 revision 则必须不同，否则根本没有比较对象。policy 应分别 pin `baseline.system_revision` 与 `candidate.expected_system_revision/ranking_version`，而不是错误地要求二者实现 hash 相等。`[RECOMMENDATION resolving 140-CONTEXT identity wording]`

建议 comparison identity 至少包含：

```text
repository
branch
commit_sha                 # 被评测目标仓源码水位
index_key_source
gold_version
split
case_set_sha256            # 排序后的 case_id + gold 内容
evaluator_schema_version
evaluator_sha256           # graph_bench_eval scorer/空结果规则
min_bucket_samples
```

system identity 分别包含：

```text
release_label              # v0.22 / v0.24
friday_revision            # 实际运行 Friday AI commit
ranking_version            # baseline/candidate 各自值
response_version
manifest_hash
index_generation/signature # 允许两系统不同，但各自必须被 policy pin
```

`graph_bench_eval.py` 自 Phase 133 后未发生 scorer 漂移；command 仅因 Phase 139 barrel 收敛把一个 import path 从内部模块改为公开 barrel，故 evaluator hash 应只覆盖 scorer/schema，而 runner revision 单独记录。`[VERIFIED: git log/diff 795f7cb5..HEAD]`

### 3. EDGE-06 不能从现有 aggregate 推导

`ResolveResult` 已提供 `status`、`language`、`call_shape`、`strategy`、候选与证据；现有 backfill 只汇总全局 resolved/ambiguous/unresolved，现有 benchmark 又只读取已落库 resolved `CallEdge`，因此 ambiguous/unresolved 与分 cell 统计已经在测量边界丢失。`[VERIFIED: resolver/base.py; resolver/symbol_resolver.py:630-730; evaluate_graph_bench.py:_load_predicted_edges]`

此外 resolver 实际可产生 `re_export` 和 `component`，而 Phase 133 gold `CALL_SHAPES` 闭集没有这两个值。若不先冻结 canonical call-shape taxonomy，TS/JS re-export/组件调用会被错误折叠或完全漏测。`[VERIFIED: symbol_resolver.py:328-365,562-579; graph_bench_eval.py:71-75]`

**推荐 taxonomy：** policy 与报告使用 resolver 的 canonical 输出闭集：`direct/member/import_alias/receiver/from_import/re_export/component`；Go 允许报告但不阻塞。更新 gold taxonomy 必须递增 `gold_version`，且发生在真实 baseline 首次冻结之前；一旦 baseline 冻结，candidate 失败不得再改 taxonomy。`[RECOMMENDATION based on current resolver outputs]`

每个 `language×framework×call_shape` cell 输出：

- `gold_count`
- `resolved_count`
- `ambiguous_count`
- `unresolved_count`
- `correct_resolved_count`
- `incorrect_resolved_count`
- `precision = correct_resolved / resolved_count`（无 resolved → `N/A`）
- `recall = correct_resolved / gold_count`（无 gold → `NO_GOLD`）
- `status = OK | INSUFFICIENT_DATA`

`resolved+ambiguous+unresolved` 必须等于 `gold_count`，否则报告 `INVALID`。`[RECOMMENDATION; denominator semantics reuse Phase 133]`

## Standard Stack

### Core

| Library / Facility | Version | Purpose | Why Standard |
|--------------------|---------|---------|--------------|
| Python stdlib `json/hashlib/dataclasses/statistics/pathlib` | Python 3.14 | policy schema、SHA-256、paired diff、稳健统计、文件 I/O | 已满足需求，避免新增生产依赖。`[VERIFIED: project stack; requirements out-of-scope]` |
| pytest + pytest-asyncio + pytest-django | pytest 9.0.2 | 纯函数、async service、ORM/integration 测试 | 本仓既有默认框架，`asyncio_mode=auto`。`[VERIFIED: server/pyproject.toml; runtime test output]` |
| structlog | existing lock | caller/sampling 事件与日志捕获 | 项目强制约束。`[VERIFIED: observability-logging.mdc]` |
| Django management command | Django 6.0.1 runtime lock | 读取 artifacts、compare、落报告与退出码 | Phase 133 已采用同一薄 I/O 模式。`[VERIFIED: test runtime; evaluate_graph_bench.py]` |

### Supporting

| Facility | Purpose | When to Use |
|----------|---------|-------------|
| `redact_secrets_in_text` | 异常/上游文本日志脱敏 | 所有 `error=` 字段。`[VERIFIED: LOGGING-SPEC.md]` |
| `redact_for_ledger` | Interaction Ledger payload 脱敏 | 如 Phase 140 新增/修改 ledger 写入。`[VERIFIED: LOGGING-SPEC.md]` |
| `GraphQueryService` | graph query 唯一 caller 生命周期 | 五消费面共享调用，不在每个适配器重复 caller 事件。`[VERIFIED: Phase 139 summary; query_service.py]` |
| `graph_query_manifest_hash()` | canonical contract hash | compare report 与整体回归 pin。`[VERIFIED: query_manifest.py; conformance tests]` |

### Alternatives Considered

| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| 独立 JSON policy | Python 常量 / baseline 内字段 | Python 常量不利独立审查；baseline 内嵌违反锁定决策。`[VERIFIED: 140-CONTEXT.md]` |
| 纯函数 comparator | 在 pytest 中直接 assert aggregate | 测试无法产完整审计报告，也容易写回 fixture；不满足可复现证据。`[RECOMMENDATION]` |
| paired case diff | 只比较 overall | overall 会掩盖受保护桶/语言/shape 退化。`[VERIFIED: BENCH-05/06 requirements]` |
| stdlib 稳健统计 | NumPy/pandas/专用 benchmark 包 | 新依赖被明确排除，且当前指标规模不需要。`[VERIFIED: REQUIREMENTS.md Out of Scope]` |

**Installation:**

```bash
# 无新增依赖；复用 server/、task/ 与 mcp/ 已锁工具链。
```

## Package Legitimacy Audit

本阶段不安装外部 package，因此 Package Legitimacy Gate 不触发。`[VERIFIED: 140-CONTEXT.md; REQUIREMENTS.md]`

| Package | Registry | slopcheck | Disposition |
|---------|----------|-----------|-------------|
| （无新增包） | — | — | Approved |

## Architecture Patterns

### System Architecture Diagram

```text
真实冻结 target repo/branch/commit
              │
              ├── v0.22 system revision ──同一 evaluator──> baseline report + manifest
              │
              └── v0.24 system revision ──同一 evaluator──> candidate report + manifest
                                                         
静态 threshold-policy.v1.json
  ├─ pins baseline report/manifest SHA-256
  ├─ pins comparison identity + expected system identities
  ├─ declares metric direction/tolerance/protected cells
  └─ declares insufficient-data behavior
              │
              ▼
graph_bench_compare.py（纯函数，零 I/O）
  1. schema/hash/identity/case-set/evaluator/ranking 校验
       └─ 任一失败 → INVALID（停止 gate 计算）
  2. case_id 严格配对 → per-case diff
  3. bucket/cell 严格配对 → per-bucket diff
  4. direction-aware gate
       ├─ 缺 required/protected cell → FAIL 或 INVALID
       ├─ 稀疏 optional cell → INSUFFICIENT_DATA
       └─ all required pass + improvement evidence → PASS
              │
              ▼
compare_graph_bench（薄 I/O command）
  └─ compare report: 三 hash + 两命令 + identities + diffs + final verdict
```

### Recommended Project Structure

```text
server/
├── codegraph/
│   ├── benchmark_policies/
│   │   └── graph_query_threshold_policy.v1.json  # 独立静态产物；测试只读
│   ├── services/
│   │   ├── graph_bench_eval.py                   # 既有 scorer；只扩 edge outcome/cell
│   │   └── graph_bench_compare.py                # NEW：policy + compare 纯函数
│   └── management/commands/
│       ├── evaluate_graph_bench.py               # 既有 run；补完整 identity/edge outcomes
│       └── compare_graph_bench.py                 # NEW：薄 I/O compare command
└── tests/
    ├── codegraph/
    │   ├── test_graph_bench_compare.py
    │   ├── test_graph_bench_policy.py
    │   ├── test_graph_bench_resolver_metrics.py
    │   └── test_graph_bench_closure.py
    └── fixtures/graph_bench/
        ├── manifest.json / splits                # 真实冻结后不再自动改
        ├── baselines/v0.22-locked-test.json      # 真实审查产物
        └── candidates/                           # CI artifact；不作 policy 来源
```

### Pattern 1: Policy 是内容寻址的只读输入

policy 自身不写自己的 hash；compare command 对原始 bytes 算 `policy_sha256`。policy pin baseline report/manifest 的 SHA-256，并同时记录人类可读 identity。这样既能防内容替换，也不会形成“文件内含自身 hash”的循环。`[RECOMMENDATION based on hashlib availability and locked immutability]`

建议 schema：

```json
{
  "schema_version": "graph-bench-threshold-policy/v1",
  "policy_version": "1",
  "status": "locked",
  "baseline": {
    "report_sha256": "<64 hex>",
    "manifest_sha256": "<64 hex>",
    "comparison_identity": {
      "repository": "<id>",
      "branch": "main",
      "commit_sha": "<sha>",
      "gold_version": "<version>",
      "split": "locked_test",
      "case_set_sha256": "<64 hex>",
      "evaluator_version": "<version>",
      "evaluator_sha256": "<64 hex>"
    },
    "system_revision": "<phase-133-final-revision>",
    "ranking_version": "<baseline-ranking-version>"
  },
  "candidate_expectation": {
    "release_label": "v0.24",
    "ranking_version": "rrf-v1",
    "response_version": "graph-query/v1",
    "manifest_hash": "<64 hex>"
  },
  "insufficient_data": {
    "min_samples": 3,
    "required_bucket_missing": "FAIL",
    "optional_bucket_sparse": "INSUFFICIENT_DATA"
  },
  "gates": [
    {
      "scope": {"kind": "resolver", "language": "python", "framework": "*", "call_shape": "*"},
      "metric": "precision",
      "direction": "higher_is_better",
      "baseline_value": "<derived-from-frozen-baseline>",
      "allowed_abs_regression": "<reviewed-absolute-tolerance>",
      "required": true,
      "protected": true
    }
  ]
}
```

上例用于说明字段，不是可直接提交的 policy；两个占位字符串在正式 schema 下必须被真实数值替换，否则 loader 应 fail-closed。`[RECOMMENDATION]`

### Pattern 2: 四态 comparator，先有效性后门禁

比较状态使用闭集：

- `INVALID`：artifact/schema/hash/identity/case set/evaluator/policy pin 不一致；不能解释指标。
- `FAIL`：输入有效，但某 required gate 真实越界或 required bucket 缺失。
- `INSUFFICIENT_DATA`：输入有效、optional cell 样本不足；必须显式列债。
- `PASS`：全部 required gates 通过，且满足 policy 声明的 improvement evidence。

优先级必须是 `INVALID > FAIL > INSUFFICIENT_DATA > PASS`；任何 invalidity 发生后不再输出“部分通过”。`[RECOMMENDATION derived from 140-CONTEXT fail-closed semantics]`

### Pattern 3: Direction-aware paired diff

高者优：

```python
passed = candidate >= baseline - allowed_abs_regression
delta = candidate - baseline
```

低者优：

```python
passed = candidate <= baseline + allowed_abs_regression
delta = baseline - candidate
```

每个 gate 必须显式携带 direction 与 tolerance，loader 不提供默认方向/默认容差。baseline/candidate 非数值 marker 不能进入算术：`NO_GOLD/N/A/SEED_MISSING` 保留原状态，required gate 遇到 marker 应 FAIL 或 INVALID（由 policy 明示），不能转成 0/1。`[RECOMMENDATION reusing Phase 133 marker semantics]`

### Pattern 4: 阈值推导规则

当前没有真实 baseline 数字，研究不能诚实填写具体值。planner 应在 Wave 0 baseline 冻结后，把每个 gate 的 `baseline_value` 写成报告中的精确值，并按以下规则生成一次、人工 review 后锁定：`[VERIFIED: baseline absent; RECOMMENDATION for derivation]`

1. **确定性质量指标与受保护桶：** `allowed_abs_regression=0`，即 candidate 不得低于 baseline；错误路径率同理不得高于 baseline。
2. **里程碑“提升”证据：** policy 显式列出 primary metrics，要求至少一项严格改善，同时其余 required metrics 零退化；不能“全部相等”却宣称提升。
3. **延迟：** 不用单次值。对同一 case 重复固定次数，保留 raw trials，policy 基于 baseline paired distribution 锁定 median/P95 允许退化；具体容差只能由实际噪声分布推导并写出理由。
4. **token：** 当前 `CaseOutcome.tokens` 恒为 0，未接真实增量计量；在计量链闭合前该 gate 应 `INSUFFICIENT_DATA`/blocking debt，不能把 0 当成功证明。`[VERIFIED: evaluate_graph_bench.py:560-581; 133-04-SUMMARY.md]`
5. **TS/JS 与 Python resolver：** 两个语言 family 分别 required；Go `required=false`，只报告。
6. **受保护 cell：** required 且样本量低于 policy 下限时 FAIL，不可降成 optional `INSUFFICIENT_DATA`。

### Anti-Patterns to Avoid

- **测试失败时重写 policy/baseline：** 严禁 `--update`、snapshot auto-accept 或 fixture write-back。`[VERIFIED: BENCH-06]`
- **从 candidate 反推容差：** candidate 与 holdout 均不能参与 policy 推导。`[VERIFIED: 140-CONTEXT.md]`
- **只比 aggregate：** case-set 漂移或局部回归会被掩盖。先严格配对 case IDs，再聚合。`[RECOMMENDATION]`
- **把 baseline/candidate system revision 要求相等：** 会消灭比较变量；应各自被 policy pin。`[RECOMMENDATION]`
- **把 marker 转数值：** 会把缺证据伪装为得分。`[VERIFIED: Phase 133 marker contract]`
- **把 query 截断后打日志：** `query[:100]` 仍是正文泄漏，不符合 OBS-01/02。`[VERIFIED: rag_search.py:263; hybrid_search.py:481,627]`
- **逐 edge INFO：** resolver 内循环只能汇总或 debug sampling。`[VERIFIED: observability rule; current resolver per-edge failure is debug]`

## Recommended Planning Decomposition

### Plan 140-01 — 冻结证据与补齐可比身份

**Goal:** 先关闭 Phase 133 `human_needed` 债，再允许任何正式 policy 数值出现。`[RECOMMENDATION]`

- 审计真实目标仓/branch/commit、三方 watermark、独立 gold 与 required/protected cell 样本量。
- 在 baseline/candidate run manifest 中增加 case-set、evaluator、system revision、ranking/response/contract identity。
- 扩 `graph_bench_eval` 的 edge-level outcome 与 resolver cell 聚合，但不改变既有 scorer/空结果语义。
- 在 Phase 133 最终 revision 运行真实 v0.22 locked_test，冻结 report/manifest/raw trials/hash。
- **Checkpoint:** 人工审查 baseline 证据；未满足时 Phase 140 保持 blocked，不生成阈值。`[VERIFIED: current baseline evidence is absent]`

### Plan 140-02 — 锁 policy 并实现 paired comparator

**Goal:** 以一次性审查的静态 JSON 固化 baseline-derived gates。`[RECOMMENDATION]`

- 先写 policy/comparator 测试，再加入 policy schema/loader、canonical hash 与纯函数 compare。
- 逐 case、逐 bucket/cell 严格配对；四态 verdict 与 required/optional sparse 规则 fail-closed。
- 实现薄 `compare_graph_bench` command，只读输入、写新 report，源码中不存在 update/accept/write-back 路径。
- **Checkpoint:** 人工 review 每个 baseline value、方向、容差、protected scope 与推导理由。

### Plan 140-03 — 可观测性收口

**Goal:** 让 OBS-01/02 成为可执行契约，同时消除 graph query 链路的正文泄漏。`[RECOMMENDATION]`

- 保留 `GraphQueryService` 唯一 caller 三事件；补成功/失败/no-query/best-effort 行为测试。
- resolver、Process、Symbol/Process lane 与 impact 补 sampling summary、语言/call-shape 计数和分层耗时。
- 移除 graph query 调用链上的 `query[:N]` 日志；异常统一脱敏。
- 扩 `test_access.py` 静态守卫，防 INFO 循环、非法 category/component/query 字段回归。

### Plan 140-04 — Candidate、门禁与全里程碑 closure

**Goal:** 生成真实 v0.24 candidate、通过 policy，并回归 v0.24 全部不变量。`[RECOMMENDATION]`

- 在同一 comparison identity 上运行 candidate，并验证两 run 的 evaluator/case-set 完全一致。
- compare report 保留三 hash、两 run identities/commands、逐例/逐桶 diff 与最终 verdict。
- 执行 benchmark、resolver、query service、Process、impact、权限/exclusion、partial/degradation、manifest/version、MCP/task/npm 回归。
- 最终验收才显式打开 holdout；任何 required gate、真实依赖或证据缺失都不得宣告 phase complete。

**依赖顺序：** `140-01 → 140-02 → 140-03 → 140-04`；140-03 的测试骨架可与 140-02 并行准备，但正式 closure 必须等待真实 policy。`[RECOMMENDATION]`

## Observability Design

### GraphQueryService caller 生命周期（OBS-01）

当前 service 已有 `code_graph_query_started/completed/failed`，均 best-effort；completed/failed 带 `duration_ms`，三者均带 repository、branch、触发用户、`category=caller`、`component=code_graph`，且未传 query 字段。`[VERIFIED: query_service.py:145-157,462-492]`

Phase 140 应补行为测试而不是重复新增另一组 caller 事件：

- 捕获三条路径，断言 event name、component/category、`initiated_by_user_id`、repository/branch。
- completed/failed 断言 `duration_ms>=0`；started 不伪造 0 时长。
- 注入 sentinel query 与 token-shaped string，序列化所有 captured log，断言 sentinel/credential 不出现。
- monkeypatch logger 抛异常，成功/失败业务语义保持不变。
- 关联键优先依赖 middleware contextvars 的 `request_id/trace_id/source`，service 显式保留 user/repo/branch；不要把 query hash 当关联键。

`query_service.py` 已被 `test_access.py::_CALLER_ENTRY_MODULES` 明确允许 caller，`component` 必须保持 `code_graph`。`[VERIFIED: test_access.py:400-504; LOGGING-SPEC.md §5]`

### 内部 sampling（OBS-02）

| Subsystem | Existing state | Required closure |
|-----------|----------------|------------------|
| resolver | backfill caller 只报全局三态；逐 edge exception 是 debug sampling | 新增一次 batch sampling summary：按 language/call_shape 的 resolved/ambiguous/unresolved 与 duration；不要逐 edge INFO。`[VERIFIED: symbol_resolver.py:645-730]` |
| Process construction | rebuild lifecycle 当前为 INFO + sampling，含总数/耗时 | 保留每次 rebuild 摘要；若在 caller 下会重复高频触发，降 debug 或走采样配置；补 initiated user/context 传播断言。`[VERIFIED: process_trace.py:559-655]` |
| Process index | rebuild 是 caller 且显式 re-bind user | caller 入口保留；dense/sparse encode/upsert/search 分层只发 sampling summary。`[VERIFIED: process_index.py:134-260]` |
| Symbol/Process retrieval lanes | GraphQueryService 仅在响应 capability 中表达 used/degraded；旧 retrieval 模块有多处 INFO wave，且记录 `query[:100]` | 在 query service 周围记录 lane、status、returned、duration_ms、top_score（无正文）；清理 graph query 路径上的 query 正文日志。`[VERIFIED: query_service.py; rag_search.py; hybrid_search.py]` |
| impact | 已有一次 debug sampling，只有 depth/returned/total/duration | 保留；由 query service 添加 lane status，不逐节点记录。`[VERIFIED: impact.py:188-209,576-582]` |

所有异常 `error=` 在埋点处直接调用 `redact_secrets_in_text`；如果新增 ledger 写入，payload 先过 `redact_for_ledger`；任何观测调用都单独 `try/except`，不能包住业务主体。`[VERIFIED: observability-logging.mdc; LOGGING-SPEC.md]`

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| 指标 scorer | 复制 Recall/P/R/trace 算法到 comparator | `graph_bench_eval` 既有输出 | 防 baseline/candidate evaluator 漂移。`[VERIFIED: 140-CONTEXT.md]` |
| 内容 hash | 自定义 checksum | stdlib SHA-256 | canonical、无新依赖。`[RECOMMENDATION]` |
| resolver 三态 | 从 nullable `callee_symbol_id` 猜 ambiguous/unresolved | `ResolveResult.status` | nullable FK 无法区分两态。`[VERIFIED: resolver/base.py]` |
| query 生命周期 | 每个 MCP/Chat 壳再发一套 | `GraphQueryService` 唯一三事件 | 避免一次调用多次 caller 计数。`[VERIFIED: Phase 139 architecture]` |
| 脱敏 | 新正则 | `redact_secrets_in_text` / `redact_for_ledger` | 项目强制入口。`[VERIFIED: observability rule]` |
| 权限/exclusion | benchmark/compare 直读图绕过 service | 运行阶段走 `GraphService.get_graph`；compare 只读已产 artifact | 保持 fail-closed；compare 不需业务数据访问。`[VERIFIED: query_service.py; Phase 133 command]` |
| 合同 hash | 重算另一种 schema hash | `graph_query_manifest_hash()` | 五消费面已有 canonical hash。`[VERIFIED: conformance tests]` |

## Common Pitfalls

### Pitfall 1: 用 seed fixture 生成正式阈值
**What goes wrong:** 6 条虚构 UID case 被误当真实 v0.22 分布。  
**Why it happens:** schema 测试全绿容易被误读为 baseline 已完成。  
**How to avoid:** policy loader 拒绝 `REPLACE_WITH_*` identity；正式 baseline artifact 必须有 OK manifest 与真实 hashes。  
**Warning signs:** baseline 报告不存在，或全部 bucket `INSUFFICIENT_DATA`。`[VERIFIED: current fixtures and verification debt]`

### Pitfall 2: evaluator version 只写字符串不验内容
**What goes wrong:** 同名 `v1` scorer 已改，报告仍被视为可比。  
**How to avoid:** 同时记录 semantic version 与 scorer source/schema SHA-256；两 run 必须相同。`[RECOMMENDATION]`

### Pitfall 3: case 数相同但 case 集不同
**What goes wrong:** aggregate 看似可比，实际替换了难例。  
**How to avoid:** canonical case-set hash + case_id 集合完全相等 + 每 case gold hash 相等。`[RECOMMENDATION]`

### Pitfall 4: required 稀疏桶被当 PASS
**What goes wrong:** TS/Python/受保护 cell 没证据仍出绿。  
**How to avoid:** required missing/under-sampled → FAIL；仅 optional cell 才可 `INSUFFICIENT_DATA`。`[VERIFIED: 140-CONTEXT.md]`

### Pitfall 5: 解析三态只看落库 FK
**What goes wrong:** ambiguous 与 unresolved 都表现为 NULL，EDGE-06 统计失真。  
**How to avoid:** benchmark adapter 直接捕获 `ResolveResult`；用 `evidence_file_line` 定位 `CallEdge`（caller file + line + branch），并断言唯一。`[VERIFIED: CallEdge.line_number; ResolveResult]`

### Pitfall 6: 延迟单次比较
**What goes wrong:** 缓存、机器抖动或 Qdrant/provider 波动导致假红/假绿。  
**How to avoid:** 固定 warmup/trials，保留 raw per-case trials，以 paired median/P95 门禁；baseline 与 candidate 在相同环境配置顺序交错运行。`[ASSUMED]`

### Pitfall 7: query 正文从底层 retrieval 泄漏
**What goes wrong:** 顶层 GraphQueryService 不记 query，但 `rag_search_failed`/`hybrid_search_started` 仍记录截断正文。  
**How to avoid:** graph query 链路移除 query 字段，仅保留长度、lane、计数、闭集状态；新增 sentinel 静态/行为测试覆盖调用链。`[VERIFIED: retrieval source]`

### Pitfall 8: holdout 被日常测试读取
**What goes wrong:** 调参污染最终验收。  
**How to avoid:** default command choices 不含 holdout；只允许显式 final-acceptance flag，并记录 opened audit metadata；普通 pytest 用 monkeypatch 断言 holdout loader 零调用。`[RECOMMENDATION based on locked decision]`

## Code Examples

### Canonical JSON hash

```python
import hashlib
import json
from typing import Any

def canonical_sha256(payload: Any) -> str:
    raw = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()
```

### Required gate fail-closed

```python
def gate_status(*, required: bool, samples: int, minimum: int, passed: bool) -> str:
    if samples < minimum:
        return "FAIL" if required else "INSUFFICIENT_DATA"
    return "PASS" if passed else "FAIL"
```

### Resolver cell invariant

```python
def validate_resolver_cell(cell: dict[str, int]) -> None:
    observed = cell["resolved"] + cell["ambiguous"] + cell["unresolved"]
    if observed != cell["gold_count"]:
        raise ValueError("resolver cell denominator mismatch")
```

以上示例是规划模式，不是已存在源码。`[RECOMMENDATION]`

## State of the Art

| Old / Current Approach | Required Phase 140 Approach | Impact |
|------------------------|-----------------------------|--------|
| Phase 133 原始报告无门禁 | 独立 content-addressed policy + compare report | 阈值可审查且测试不可写回。`[VERIFIED: phase boundary]` |
| overall + language/framework/entry bucket | overall + protected + capability + resolver language/framework/call_shape cells | EDGE-06 与局部退化可独立阻断。`[VERIFIED: current vs requirements]` |
| 单 run artifact、无 pair identity | baseline/candidate strict paired identity + system revisions | BENCH-07 可证明同条件。`[RECOMMENDATION]` |
| query service 有日志但无专门行为测试 | caller lifecycle + no-query sentinel + observability failure test | OBS-01 从静态存在升级为行为保证。`[VERIFIED: current tests lack log assertions]` |
| retrieval 底层仍有 query 截断日志 | graph query 路径只留闭集元数据 | 满足禁止正文日志。`[VERIFIED: current source]` |

## Project Constraints (from `.cursor/rules/` and workspace instructions)

- 使用 `structlog.get_logger(__name__)`，snake_case 事件与 kv 字段；生命周期 completed/failed 带 `duration_ms`。`[VERIFIED: observability-logging.mdc]`
- 每个事件显式 `category` 与 `component`；`codegraph` 是索引/解析侧，`code_graph` 是查询 service 侧，不得混用。`[VERIFIED: LOGGING-SPEC.md §5]`
- graph query caller 全量、内部高频步骤 sampling/debug；循环内禁止 INFO。`[VERIFIED: observability-logging.mdc]`
- 后台任务显式传播并 re-bind `initiated_by_user_id`，无用户为 `system`。`[VERIFIED: observability-logging.mdc]`
- 异常文本与 ledger 分别走 `redact_secrets_in_text` / `redact_for_ledger`；观测 best-effort。`[VERIFIED: observability-logging.mdc]`
- Django async ORM 访问走 `sync_to_async`；不新增前端、生产依赖或外部服务。`[VERIFIED: CLAUDE.md; 140-CONTEXT.md]`
- 文档正文使用中文，代码标识与命令保留英文。`[VERIFIED: workspace doc rule]`

## Assumptions Log

| # | Claim | Section | Risk if Wrong |
|---|-------|---------|---------------|
| A1 | 延迟应采用固定多次 paired trial 的 median/P95，而非单次值。`[ASSUMED]` | Pitfall 6 / Threshold derivation | 会改变 artifact schema 与运行时长；planner 需在真实环境确认 trial 数和噪声预算。 |
| A2 | `evidence_file_line` 可稳定映射到唯一 `CallEdge`（branch + caller_file + line_number）。`[ASSUMED]` | EDGE-06 adapter | 同行多个调用时可能不唯一；届时 gold 必须增加 callee raw name/ordinal 或 edge locator。 |
| A3 | primary quality 至少一项严格改善足以支撑“整体提升”，其余 required 指标零退化。`[ASSUMED]` | Threshold derivation | 产品方可能要求指定某一主指标必须改善；需在 policy review 时确认。 |

## Open Questions

1. **真实冻结目标仓和 v0.22 baseline artifact 在哪里？**
   - What we know: 当前 repo 内没有 baseline JSON，manifest 仍是占位。`[VERIFIED: workspace search]`
   - What's unclear: 目标仓、commit、Phase 133 最终 system revision 的可运行环境与索引快照。
   - Recommendation: planner 把它设为第一道人工 checkpoint；没有 artifact 不进入 policy 数值任务。

2. **resolver callsite locator 是否唯一？**
   - What we know: `CallEdge` 有 branch、caller_file、line_number、callee_name/call_type；gold 只有 `evidence_file_line` 与期望 caller/callee UID。`[VERIFIED: models.py; gold schema]`
   - What's unclear: 同一行多个调用的区分方式。
   - Recommendation: 先对真实 gold 做 uniqueness audit；若冲突，baseline 冻结前给 edge gold 增加稳定 locator 并 bump gold version。

3. **token gate 的真实计量源如何按 run/case 归因？**
   - What we know: command 目前硬编码 `tokens=0`，Phase 133 明确未新增平行计量通道。`[VERIFIED: command; summary]`
   - What's unclear: embedding token 是否有可查询的 per-run delta，以及纯图 case 的口径。
   - Recommendation: 若现有 `ModelUsageRecord` 无稳定 case 关联，Phase 140 如实标技术债，不用 0 gate 冒充完成；或先补 run_id/case_id 关联再锁 policy。

4. **holdout 如何防泄漏并审计开箱？**
   - What we know: 当前为空且 baseline command 拒读。`[VERIFIED: fixtures; command]`
   - What's unclear: 最终验收的授权人与 opened log 位置。
   - Recommendation: final-only command flag + artifact audit metadata；不在普通单测加载正文。

## Environment Availability

| Dependency | Required By | Available | Version / State | Fallback |
|------------|-------------|-----------|-----------------|----------|
| Python | comparator/tests | ✓ | system 3.14.6；`uv run` 3.14.2 | 使用 `uv run` 锁环境。`[VERIFIED: local probes]` |
| uv | server/task tests | ✓ | 0.11.8 | — |
| pytest | validation | ✓ | 9.0.2 | — |
| PostgreSQL test DB | ORM/full regression | 部分可用 | 本次组合测试被并发 session 占用 `test_friday` | 使用 `--reuse-db` 或隔离测试 DB；不能把环境冲突记产品失败。`[VERIFIED: test run output]` |
| 已索引真实目标仓 | baseline/candidate final gate | ✗ 未提供 | Phase 133 human debt | 无；是 BENCH-06/07 blocker。 |
| Qdrant + embedding provider | Symbol/Process lane 与真实性能 | 未在本轮验证 | integration-only | 默认单测用 mock；最终 gate 无 fallback。 |
| npm workspace `mcp/` | 五消费面 conformance | ✓ 源码存在 | package scripts: test/typecheck/build/prepack | 无新增依赖。`[VERIFIED: mcp/package.json]` |

**Missing dependencies with no fallback:**
- 满足同仓同 commit 的真实已索引目标仓、v0.22 baseline artifact 与可比 candidate 运行环境。`[VERIFIED: Phase 133 verification debt]`

**Missing dependencies with fallback:**
- 当前 PostgreSQL test DB 并发占用：可用独立 DB 或 `--reuse-db` 运行回归；纯函数套件已在本轮 `78 passed`。`[VERIFIED: local test runs]`

## Validation Architecture

> `.planning/config.json` 的 `workflow.nyquist_validation=true`，因此本节是硬要求。`[VERIFIED: config.json]`

### Test Framework

| Property | Value |
|----------|-------|
| Framework | pytest 9.0.2 + pytest-asyncio/pytest-django；npm Vitest 4.1.8 |
| Config file | `server/pyproject.toml`、`task/pyproject.toml`、`mcp/package.json` |
| Quick run command | `cd server && uv run pytest tests/codegraph/test_graph_bench_policy.py tests/codegraph/test_graph_bench_compare.py tests/codegraph/test_graph_bench_resolver_metrics.py -x -q` |
| Service run command | `cd server && uv run pytest tests/services/code_graph/test_query_service.py tests/services/code_graph/test_access.py -q --reuse-db` |
| Full phase command | 见“Phase gate”分层命令；真实 benchmark 另行显式执行，不能被默认 marker skip 代替 |

### Phase Requirements → Test Map

| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| BENCH-06 | policy schema/version/hash/pins/direction/tolerance 全显式；只读且无 auto-update | unit + static | `pytest tests/codegraph/test_graph_bench_policy.py -x` | ❌ Wave 0 |
| BENCH-06 | required/protected missing、marker、稀疏桶四态正确 | table-driven unit | `pytest tests/codegraph/test_graph_bench_compare.py -x` | ❌ Wave 0 |
| BENCH-07 | identity/case-set/evaluator/hash mismatch 一律 INVALID；逐 case/桶 diff 完整 | unit + command integration | `pytest tests/codegraph/test_graph_bench_compare.py tests/codegraph/test_compare_graph_bench_command.py -x` | ❌ Wave 0 |
| BENCH-07 | 同条件真实 baseline/candidate 运行并保留两命令与三 hash | external integration | `python manage.py compare_graph_bench ...` | ❌ 需真实 artifacts |
| EDGE-06 | language×framework×call_shape cell P/R + resolved/ambiguous/unresolved；总数 invariant | unit | `pytest tests/codegraph/test_graph_bench_resolver_metrics.py -x` | ❌ Wave 0 |
| EDGE-06 | TS/JS 与 Python required gates 独立，Go report-only | policy/comparator unit | 同上 | ❌ Wave 0 |
| OBS-01 | started/completed/failed 字段、用户/关联键、duration、无 query、best-effort | async unit/log capture | `pytest tests/services/code_graph/test_query_observability.py -x` | ❌ Wave 0 |
| OBS-02 | resolver/Process/lane/impact sampling 字段、分层耗时、无 INFO loop/query body | unit + AST static guard | `pytest tests/services/code_graph/test_graph_query_sampling.py tests/services/code_graph/test_access.py -x` | ❌ Wave 0（guard 已有，需扩） |
| Closure | 权限/exclusion、partial/degradation、manifest hash、版本、同水位 | regression | 既有 service/MCP/conformance suites | ✅，需组合 gate |

### Risk-Proportionate Test Layers

1. **Pure contract tests（每 task）：**
   - policy loader 的缺键、未知 schema、未知 direction、非法 hash、隐式默认、duplicate gate。
   - comparator 的两方向、边界等号、missing/extra case、baseline/policy/candidate hash mismatch。
   - resolver cell denominator/invariant、marker propagation、required vs optional sparse behavior。

2. **Service behavior tests（每 wave）：**
   - `GraphQueryService` 三生命周期、no-query sentinel、logger failure 不反噬。
   - Symbol/Process lane 分层耗时与 used/degraded/unavailable。
   - resolver batch 只发汇总；循环中无 INFO；Process/impact 只发 sampling。

3. **Cross-phase regression（phase gate）：**

```bash
cd server
uv run pytest \
  tests/codegraph/test_graph_bench_*.py \
  codegraph/resolver/tests \
  tests/services/code_graph/test_query_service.py \
  tests/services/code_graph/test_query_contract_conformance.py \
  tests/services/code_graph/test_process_index.py \
  tests/services/code_graph/test_process_trace.py \
  tests/services/code_graph/test_impact.py \
  tests/services/code_graph/test_access.py \
  tests/mcp_tools/test_graph_query_tool.py \
  -q --reuse-db
```

4. **多消费面构建回归：**

```bash
cd task && uv run pytest -q
cd ../mcp && npm test && npm run typecheck && npm run build && npm pack --dry-run
```

5. **真实验收（不可 skip）：**
   - 对真实冻结仓分别运行 v0.22 baseline 与 v0.24 candidate。
   - compare command 返回 `PASS` 才过自动 gate。
   - holdout 只在 final acceptance 显式打开；若环境不可用，阶段状态必须 `human_needed`/blocked，不能用 collect-only 代替。

### Sampling Rate

- **Per task:** 新增的单文件/纯函数 quick tests。
- **Per wave:** benchmark + resolver + query observability 相关集合。
- **Phase gate:** server cross-phase + task + npm 全绿；真实 baseline/candidate/compare artifact 有效；required gates 全过。

### Wave 0 Gaps

- [ ] 真实目标仓、真实独立 gold、非占位 manifest、每个 required/protected cell 的最低样本数。
- [ ] 真实 v0.22 baseline report/run manifest 与 SHA-256。
- [ ] `graph_bench_compare.py` / policy JSON schema / compare command。
- [ ] edge-level outcome 与 language×framework×call_shape 聚合。
- [ ] query caller 行为测试与内部 sampling/no-query 守卫。
- [ ] token 按 run/case 归因，或明确 `INSUFFICIENT_DATA` 技术债处理。
- [ ] holdout 数据与 final-only 开箱纪律。

### Current Verification Evidence

- 本轮纯 benchmark scorer/watermark/gold schema + GraphQueryService 合计 `78 passed`。`[VERIFIED: local pytest run]`
- 更大的组合运行有 `86 passed`，另 14 个 setup error 均因 PostgreSQL `test_friday` 被另一个 session 占用，未出现 assertion failure。`[VERIFIED: local pytest output]`

## Security Domain

### Applicable ASVS Categories

| ASVS Category | Applies | Standard Control |
|---------------|---------|-----------------|
| V2 Authentication | no new auth | 复用现有五消费面认证；compare command 不新增远程入口。`[VERIFIED: phase scope]` |
| V3 Session Management | no | 无新 session。 |
| V4 Access Control | yes | benchmark 运行走 `GraphService.get_graph` 权限/exclusion fail-closed；compare 只读 artifacts。`[VERIFIED: existing architecture]` |
| V5 Input Validation | yes | policy/report JSON schema、闭集 enums、hash、path 与 identity fail-closed。`[RECOMMENDATION]` |
| V6 Cryptography | yes（完整性） | stdlib SHA-256 做 artifact 内容寻址；不用于密码学认证。`[RECOMMENDATION]` |
| V7 Error/Logging | yes | query/credential 禁止日志；异常脱敏；caller/sampling 分类。`[VERIFIED: project rules]` |

### Known Threat Patterns

| Pattern | STRIDE | Standard Mitigation |
|---------|--------|---------------------|
| candidate/测试篡改 baseline 或 policy | Tampering | policy/baseline repo-owned、hash pin、command 无 write-back、静态测试禁 update 路径 |
| 替换简单 case 维持同 case 数 | Tampering | canonical case-set/gold hash + case ID 严格配对 |
| 混仓/混 commit/混 evaluator 后宣称 PASS | Tampering | comparison identity fail-closed → INVALID |
| query/凭证进入日志 | Information Disclosure | no-query sentinel + `redact_secrets_in_text` + ledger redaction |
| 观测失败中断业务 | Denial of Service | logger/metric/ledger 独立 best-effort |
| 越权读取图或 excluded 文件 | Elevation of Privilege | 运行阶段只走已有权限/exclusion service；整体回归保留 fail-closed 测试 |

## Sources

### Primary (HIGH confidence)

- `.planning/phases/140-threshold-policy/140-CONTEXT.md` — 全部锁定决策、边界与 deferred。
- `.planning/REQUIREMENTS.md` / `.planning/ROADMAP.md` / `.planning/STATE.md` — BENCH-06/07、EDGE-06、OBS-01/02 与里程碑状态。
- `.planning/phases/133-commit-v0-22-baseline/{133-CONTEXT,133-RESEARCH,133-01..04-PLAN,133-01..04-SUMMARY,133-VERIFICATION,133-REVIEW}.md` — evaluator 协议、已交付项与真仓债。
- `server/codegraph/services/graph_bench_eval.py` — scorer、marker、identity、分桶与报告。
- `server/codegraph/management/commands/evaluate_graph_bench.py` — 当前运行编排、manifest、token=0 与日志。
- `server/tests/fixtures/graph_bench/*` — seed/占位/holdout 当前事实。
- `server/codegraph/resolver/{base,symbol_resolver}.py` / `server/codegraph/models.py` — resolver 三态、call shapes、CallEdge locator。
- `server/services/code_graph/{query_service,process_trace,process_index,impact}.py` — caller/sampling 当前实现。
- `server/services/retrieval/{rag_search,hybrid_search}.py` — 当前 query 正文日志缺口。
- `.cursor/rules/observability-logging.mdc` / `.planning/observability/LOGGING-SPEC.md` — 强制观测规范。
- `server/tests/services/code_graph/*` / `server/tests/mcp_tools/test_graph_query_tool.py` / `server/pyproject.toml` — 现有回归与测试配置。

### Secondary (MEDIUM confidence)

- Phase 134–139 summaries — 各能力交付与既有测试结果；已用当前源码交叉核验。
- 本轮本地 pytest 与环境探测 — 反映当前机器状态，不代表 CI/生产环境。

### Tertiary (LOW confidence)

- 延迟多 trial 的具体统计方式、callsite locator 唯一性与“至少一个 primary metric 严格改善”规则均列入 Assumptions Log，需 planner/用户确认。

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH — 零新增依赖，全部来自本仓锁定栈。
- Architecture: HIGH — Phase 133 纯函数+薄 command 已验证，当前缺口逐文件核验。
- Threshold values: LOW until real baseline — 当前没有真实 baseline artifact，任何具体数值都会是伪造。
- Observability: HIGH — caller/sampling 现状与违规点均由源码和静态守卫核验。
- Validation: HIGH — 现有测试文件、命令、marker 与本轮运行结果均已确认。

**Research date:** 2026-08-24  
**Valid until:** 2026-09-23；真实 baseline/policy 一旦产出，应立即更新阈值推导与 Environment Availability。
