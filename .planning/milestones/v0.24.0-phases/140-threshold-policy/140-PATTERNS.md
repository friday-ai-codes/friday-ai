# Phase 140: Threshold policy 与整体收口 - Pattern Map

**Mapped:** 2026-08-24  
**Files analyzed:** 19 个预计新增/修改文件  
**Analogs found:** 19 / 19（其中 policy JSON 无同职责现成文件，采用相邻契约模式组合）

## File Classification

| 预计新增/修改文件 | Role | Data Flow | Closest Analog | Match Quality |
|---|---|---|---|---|
| `server/codegraph/benchmark_policies/graph_query_threshold_policy.v1.json` | config / immutable artifact | file-I/O（只读） | `server/contracts/graph-query.v1.json` + `server/tests/fixtures/graph_bench/manifest.json` | partial |
| `server/codegraph/services/graph_bench_compare.py` | service / utility | transform（纯函数） | `server/codegraph/services/graph_bench_eval.py` | exact |
| `server/codegraph/services/graph_bench_eval.py` | service / model | transform（纯函数） | 本文件既有 `CaseOutcome`、`bucket_metrics()`、`build_report()` | exact |
| `server/codegraph/management/commands/evaluate_graph_bench.py` | management command | batch + file-I/O + request-response | 本文件既有 command | exact |
| `server/codegraph/management/commands/compare_graph_bench.py` | management command | file-I/O + transform | `server/codegraph/management/commands/evaluate_graph_bench.py` | exact |
| `server/services/code_graph/query_service.py` | service | async request-response | 本文件既有 `GraphQueryService.query()` | exact |
| `server/codegraph/resolver/symbol_resolver.py` | service | batch + CRUD + event-driven | 本文件既有 `SymbolResolver.backfill()` | exact |
| `server/services/code_graph/process_trace.py` | service | batch + CRUD | 本文件既有 `rebuild_processes()` | exact |
| `server/services/code_graph/process_index.py` | service | batch + external index I/O | 本文件既有 `rebuild_process_index()` / `search_process_index()` | exact |
| `server/services/code_graph/impact.py` | utility / service | graph transform | 本文件既有 `_log_impact_analyzed()` | exact |
| `server/services/retrieval/rag_search.py` | service | async request-response | 本文件既有 `search_rag()`，但日志模式需纠正 | role-match |
| `server/services/retrieval/hybrid_search.py` | service | async staged/batch | 本文件既有 wave 生命周期，日志模式需纠正 | role-match |
| `server/tests/codegraph/test_graph_bench_policy.py` | test | transform + static guard | `server/tests/codegraph/test_graph_bench_gold_schema.py` | exact |
| `server/tests/codegraph/test_graph_bench_compare.py` | test | transform | `server/tests/codegraph/test_graph_bench_eval.py` | exact |
| `server/tests/codegraph/test_graph_bench_resolver_metrics.py` | test | transform | `server/tests/codegraph/test_graph_bench_eval.py` + resolver language tests | exact |
| `server/tests/codegraph/test_compare_graph_bench_command.py` | test | file-I/O + command integration | `server/tests/codegraph/test_evaluate_graph_bench_command.py` | exact |
| `server/tests/codegraph/test_graph_bench_closure.py` | test | cross-contract regression | `server/tests/codegraph/test_graph_bench_integration.py` + `test_query_contract_conformance.py` | role-match |
| `server/tests/services/code_graph/test_query_observability.py` | test | async request-response + log capture | `server/tests/code_relations/test_graph_builder.py` 的 `capture_logs()` 测法 + `test_query_service.py` fixture | role-match |
| `server/tests/services/code_graph/test_graph_query_sampling.py`、`test_access.py` | test / static guard | AST transform + async log capture | `server/tests/services/code_graph/test_access.py::test_observability_contract` | exact |

## Pattern Assignments

### `server/codegraph/benchmark_policies/graph_query_threshold_policy.v1.json`

**Analogs:** `server/contracts/graph-query.v1.json`（版本化 repo-owned JSON）与 `server/tests/fixtures/graph_bench/manifest.json`（冻结身份）。

**配套 loader/hash analog:** `server/services/code_graph/query_manifest.py:11-24`

```python
_MANIFEST_PATH = (
    Path(__file__).resolve().parents[2] / "contracts" / "graph-query.v1.json"
)

@lru_cache(maxsize=1)
def graph_query_manifest() -> dict[str, Any]:
    return json.loads(_MANIFEST_PATH.read_text(encoding="utf-8"))

@lru_cache(maxsize=1)
def graph_query_manifest_hash() -> str:
    return hashlib.sha256(_MANIFEST_PATH.read_bytes()).hexdigest()
```

**应复制的模式**
- JSON 是仓库内独立静态输入；loader 返回解析后的新对象，不暴露可写共享对象。
- policy hash 对**原始文件 bytes**做 SHA-256，policy 内不写自身 hash。
- schema/version、每个 gate 的 `direction`、`allowed_abs_regression`、`required`、`protected` 均显式必填；未知键值、占位值和非 64 位 hex hash fail-closed。
- baseline report/manifest hash、comparison identity、baseline system identity、candidate expectation 分开 pin；不可错误要求 baseline/candidate 的 Friday revision 相同。

**注意事项**
- 当前 `server/tests/fixtures/graph_bench/manifest.json:2-11` 仍含 `REPLACE_WITH_*`，正式 policy 数值没有合法来源。planner 必须把真实 baseline 设为前置 checkpoint；不可根据 seed fixture 或 candidate 填阈值。
- policy 不得提供 `--update`、snapshot accept 或测试写回路径；candidate/holdout 不参与阈值推导。

---

### `server/codegraph/services/graph_bench_compare.py`

**Analog:** `server/codegraph/services/graph_bench_eval.py`

**纯函数边界** (`graph_bench_eval.py:1-20`)：

```python
本模块**只做算术、零 I/O**：不触碰 ORM / 向量库 / 网络，不读文件。
```

**显式 marker 与四态基础** (`graph_bench_eval.py:316-325`)：

```python
NO_GOLD = "NO_GOLD"
NOT_APPLICABLE = "N/A"
SEED_MISSING = "SEED_MISSING"
INSUFFICIENT_DATA = "INSUFFICIENT_DATA"
BUCKET_OK = "OK"
MIN_BUCKET_SAMPLES = 3
```

**身份 fail-closed analog** (`graph_bench_eval.py:134-154`)：

```python
if not (index_built_at_sha and gold_annotated_at_sha and source_checkout_sha):
    return "INVALID"
if len({index_built_at_sha, gold_annotated_at_sha, source_checkout_sha}) != 1:
    return "INVALID"
```

**应复制的模式**
- `dataclass` 表示 policy、gate、comparison result；`to_dict()` 只产 JSON-safe 值。
- 先完整验证 schema/hash/identity/case-set/evaluator/ranking，再计算 gate；任何 invalidity 直接总 verdict `INVALID`。
- 按 `case_id` 严格配对，拒绝 missing/extra/duplicate；再按 bucket/cell key 严格配对。
- direction-aware 比较必须显式分支；marker 原样传播，绝不转为 0/1。
- verdict 优先级固定 `INVALID > FAIL > INSUFFICIENT_DATA > PASS`；required 缺失/稀疏为 `FAIL`，仅 optional 稀疏为 `INSUFFICIENT_DATA`。
- comparator 消费 `graph_bench_eval` 的报告，不复制 Recall/P/R/trace scorer。

**canonical JSON analog:** `server/delivery/services/artifact_service.py:43-45`

```python
canonical = json.dumps(content, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
return hashlib.sha256(canonical.encode("utf-8")).hexdigest()
```

**注意事项**
- report hash 若定义为文件 hash，应对 bytes；case-set/evaluator 内容 hash 才使用 canonical JSON/source bytes。两者字段名要区分，避免同名不同口径。
- output 必须保留 policy/baseline/candidate 三 hash、两份 reproducible command、两类 identity、per-case/per-bucket diff 和最终 verdict。

---

### `server/codegraph/services/graph_bench_eval.py`（resolver metrics 扩展）

**Analog symbols:** `CaseOutcome`、`evaluate_case()`、`bucket_metrics()`、`aggregate_report()`。

**现有 case 折算** (`graph_bench_eval.py:492-541`)：

```python
@dataclass
class CaseOutcome:
    case_id: str
    split: str
    language: str
    framework: str
    entry_type: str
    protected: bool = False
    # ... quality/timing fields ...

    def to_dict(self) -> dict[str, Any]:
        return {"case_id": self.case_id, "language": self.language, ...}
```

**现有确定性分桶** (`graph_bench_eval.py:650-682`)：

```python
groups: dict[tuple[str, str, str], list[CaseOutcome]] = {}
for case in cases:
    key = (case.language, case.framework, case.entry_type)
    groups.setdefault(key, []).append(case)
for (language, framework, entry_type), members in sorted(groups.items()):
    ...
```

**resolver 事实源 analog:** `server/codegraph/resolver/base.py:39-51`

```python
@dataclass
class ResolveResult:
    callee_symbol_id: str | None
    callee_file: str | None
    is_cross_file: bool
    status: str = "unresolved"
    language: str = "unknown"
    call_shape: str = "direct"
    strategy: str = "none"
```

**应复制/扩展的模式**
- 在 outcome 保留 edge-level `status/language/framework/call_shape/correct`，再按 `language × framework × call_shape` 排序聚合。
- cell 输出 `gold_count/resolved_count/ambiguous_count/unresolved_count/correct_resolved_count/incorrect_resolved_count/precision/recall/status`。
- 强制 invariant：三态计数和等于 `gold_count`，否则报告 `INVALID`，不能从 nullable `callee_symbol_id` 推断 ambiguous/unresolved。
- taxonomy 必须与 resolver 当前产出对齐：除现有 `direct/member/import_alias/receiver/from_import`，还要审查 `re_export`（`symbol_resolver.py:563-579`）与 `component`（`:358-365`）；baseline 冻结前变更需 bump `gold_version`。

**注意事项**
- `score_edge_pr()` (`graph_bench_eval.py:383-397`) 仍可保留 aggregate edge P/R，但 EDGE-06 不可从该二元组 aggregate 反推 resolver 三态。
- callsite 定位先审计 `branch + caller_file + line_number` 是否唯一；同一行多调用时需在 baseline 冻结前扩 gold locator。

---

### `server/codegraph/management/commands/evaluate_graph_bench.py`

**Analog:** 本文件现有「纯函数 + 薄 I/O command」。

**参数/schema fail-closed** (`evaluate_graph_bench.py:223-270`)：

```python
class Command(BaseCommand):
    def add_arguments(self, parser: argparse.ArgumentParser) -> None:
        parser.add_argument("--repo", required=True, ...)
        parser.add_argument("--commit-sha", required=True, ...)

    def handle(self, *args: Any, **options: Any) -> None:
        manifest, cases = _load_gold(gold_dir, split)
        try:
            dataset = validate_gold_dataset(manifest, cases)
        except ValueError as exc:
            raise CommandError(...) from exc
        asyncio.run(self._arun(options, dataset, manifest))
```

**水位先闸后运行** (`evaluate_graph_bench.py:297-353`)：先算 `invalid_reasons`、写 INVALID manifest、发 best-effort event、抛 `CommandError`；只有 OK 才进入 `_run_all_cases()`。

**产物与复现命令** (`evaluate_graph_bench.py:396-426,603-655`)：`build_report()` 后 command 才附 `run_id/duration_ms/reproducible_command` 并负责 JSON 落盘。

**应扩展**
- manifest 增加 comparison identity：`case_set_sha256/evaluator_version/evaluator_sha256/min_bucket_samples`。
- system identity 单列：`release_label/friday_revision/ranking_version/response_version/manifest_hash/index_generation`。
- `_run_case()` 目前 `tokens=0` (`:560-581`)；真实计量链未闭合前必须输出显式 unavailable/insufficient marker，不得以 0 通过 token gate。
- resolver 指标应直接捕获 `ResolveResult`；当前 `_load_predicted_edges()` (`:199-220`) 只读 resolved FK，会丢 ambiguous/unresolved。
- 默认 split 继续不读 holdout；最终验收需要显式、可审计开箱参数，普通 pytest 断言不会加载 holdout。

---

### `server/codegraph/management/commands/compare_graph_bench.py`

**Analog:** `evaluate_graph_bench.py:48-85,88-115,223-270,603-655`。

**应复制的 command 外壳**
- stdlib `argparse/json/pathlib` + `BaseCommand/CommandError`；所有 JSON 读取错误转成明确 `CommandError`。
- command 只负责读取三份 artifact、计算 raw byte hashes、调用纯 comparator、写一份新 compare report、按 verdict 设置非零退出。
- caller 生命周期沿用 `_LOG_KV`：`category="caller"`, `component="codegraph"`, `initiated_by_user_id="system"`；failed error 走 `redact_secrets_in_text`，所有日志单独 `try/except`。
- reproducible command 明确列出 baseline/candidate/policy/output 参数。

**注意事项**
- 不应从 command 内重跑 scorer、改 baseline、改 policy 或接受快照。
- `INVALID`、`FAIL`、`INSUFFICIENT_DATA` 的 CLI 退出语义要显式测试；不得打印 PASS 后再附 invalid warning。

---

### `server/services/code_graph/query_service.py`（OBS-01 与 lane sampling）

**Analog:** `GraphQueryService.query()` 本身。

**唯一 caller 生命周期** (`query_service.py:145-157,462-492`)：

```python
try:
    logger.info(
        "code_graph_query_started",
        repository_id=repository_id,
        branch_name=branch_name,
        initiated_by_user_id=initiated_by_user_id,
        category="caller",
        component="code_graph",
    )
except Exception:
    pass
```

completed/failed 同样单独 best-effort，带 `duration_ms`；failed 使用
`error=redact_secrets_in_text(str(exc))`。

**应保留/扩展**
- 不再增加第二组 caller 事件；五消费面共享这里的三事件。
- started 不伪造 `duration_ms=0`；completed/failed 必须 `duration_ms >= 0`。
- user/repository/branch/response version 显式字段保留；`request_id/trace_id/source` 由 contextvars processor 注入。
- Symbol、Process、impact lane 在各 lane try/except 周围记录一次 debug/sampling summary：闭集 `lane/status`、returned、duration、可选 top_score；禁止 query/query hash/路径正文。
- partial/degradation 继续由 response 的 `capabilities` 和 `warnings` 表达；观测失败不能改变这些业务语义。

**权限 analog:** `query_service.py:159-170` 每次都走 `get_graph_service().get_graph(..., user=user)`；benchmark 运行也不得绕开权限/exclusion 闸。

---

### resolver、Process、retrieval lane、impact sampling

#### `server/codegraph/resolver/symbol_resolver.py`

**Analog:** `SymbolResolver.backfill()` (`symbol_resolver.py:630-730`)。

- 保留 batch caller started/completed；逐 edge exception 已是 `logger.debug(... category="sampling")` (`:671-685`)。
- 新增一次 batch sampling summary，按 `language/call_shape/status` 聚合计数和分层耗时；不要在 `for edge in edges` 内发 INFO。
- 现有 component 是 `codegraph`，与 query service 的 `code_graph` 不同；按 LOGGING-SPEC 的解析侧 component 继续使用 `codegraph`，不要机械改成 query component。
- 当前 completed 只带全局 `resolved/ambiguous/unresolved` (`:709-727`)；分 cell 统计应由 `ResolveResult` 累积，而不是从落库结果回读。

#### `server/services/code_graph/process_trace.py`

**Analog:** `rebuild_processes()` (`process_trace.py:547-656`)。

```python
logger.info(
    "code_graph_process_rebuild_completed",
    category="sampling",
    component="code_graph",
    processes_total=len(rows),
    processes_written=written,
    unresolved_endpoints=degradation.get("unresolved_endpoints"),
    duration_ms=duration_ms,
)
```

- 生命周期已有 started/completed/failed、脱敏与 best-effort；补 `initiated_by_user_id` 参数/传播时沿用 process index 的 re-bind 模式。
- 若此 rebuild 在高频 caller 下触发，日志应降 debug 或采样，不能把每个 endpoint/BFS step 打 INFO。

#### `server/services/code_graph/process_index.py`

**Analog:** `rebuild_process_index()` (`process_index.py:134-261`)。

```python
user_id = initiated_by_user_id or "system"
with bind_task_context(user_id=user_id, source="process_index"):
    logger.info(... initiated_by_user_id=user_id, category="caller", component="code_graph")
```

- caller rebuild 保留；dense/sparse encode、upsert、search 的分层观测只发 debug/sampling summary。
- 内部 summary 应带 generation、count、duration，不带 query 或文档 content。

#### `server/services/code_graph/impact.py`

**Analog:** `_log_impact_analyzed()` (`impact.py:179-209`)。

```python
logger.debug(
    _EVENT_IMPACT_ANALYZED,
    component="code_graph",
    category="sampling",
    depth=depth,
    returned=returned,
    total_found=total_found,
    duration_ms=duration_ms,
)
```

- 这是高频 sampling 的首选模板：一次调用恰一条、循环内零日志、只记计数与耗时、best-effort。
- 事件名必须在调用点可被 AST 静态解析为字面量或模块级字面量常量；不要抽成 `_emit(event, **fields)`。

#### `server/services/retrieval/rag_search.py` / `hybrid_search.py`

**现状 anti-analog**
- `rag_search.py:263` 的 `query=query[:100]`、`hybrid_search.py:481-485,627-631` 的截断 query 仍是正文泄漏，必须删除。
- `hybrid_search.py:338-370,537-548` 的 wave INFO 对高频内部步骤过重；GraphQueryService 链路应改 debug/sampling 或仅由顶层 lane summary 表达。
- error 字段当前多处直接 `str(exc)`，应在改动范围内统一 `redact_secrets_in_text`；观测调用单独 best-effort，不能包住业务主体。

## Test Pattern Assignments

### `test_graph_bench_policy.py`

**Analog:** `test_graph_bench_gold_schema.py:18-125`。

- 用 `_valid_policy()` fixture + `pytest.mark.parametrize` 删除必填键/注入未知 enum。
- 断言缺 schema/version/pin/direction/tolerance、非法 hash、占位字符串、duplicate gate 均 raise。
- 静态读取源码/command 参数，断言不存在 update/accept/write-back；测试只读 policy，不创建或覆盖正式 policy。

### `test_graph_bench_compare.py`

**Analog:** `test_graph_bench_eval.py:41-51,339-517`。

- helper 构造最小 dataclass/report；class 按行为分组。
- table-driven 覆盖 higher/lower、边界等号、required/optional sparse、marker、protected gate。
- 覆盖 identity/hash/evaluator/ranking/case set mismatch 全部 `INVALID`，以及 missing/extra/duplicate case。
- 断言逐 case、逐 bucket/cell diff 和三 hash均保留；禁止只断言最终 verdict。

### `test_graph_bench_resolver_metrics.py`

**Analogs:** `test_graph_bench_eval.py::TestScoreEdgePr/TestBucketMetrics` 与
`server/codegraph/resolver/tests/test_ts_js_resolution.py`、`test_python_resolution.py`。

- 直接构造 `ResolveResult` 覆盖 resolved/ambiguous/unresolved 与 canonical call shapes。
- 断言 cell 分母 invariant、precision 无 resolved 为 `N/A`、recall 无 gold 为 `NO_GOLD`。
- TS/JS 与 Python 分开 required，Go report-only；`re_export/component` taxonomy 必须有用例。

### `test_compare_graph_bench_command.py`

**Analog:** `test_evaluate_graph_bench_command.py:33-72,88-161`。

- `tmp_path` 写最小输入 artifacts，`call_command()` 驱动真实 command 外壳。
- invalid 输入用 `pytest.raises(CommandError)`；读取输出 report 断言 verdict、hash、identity、commands。
- patch comparator/文件写入验证 INVALID 前不进入 gate 计算；验证 command 不修改三份输入。
- 如 command 内 async/ORM，沿用 `django_db(transaction=True)`；纯 compare command 不应为测试方便引入 ORM。

### `test_query_observability.py`

**业务 fixture analog:** `test_query_service.py:13-100` 的 `_GraphService/_facts/_install`。

**日志捕获 analog:** `server/tests/code_relations/test_graph_builder.py:337-393` 的
`structlog.testing.capture_logs()`。

- 成功捕获 started/completed，失败捕获 started/failed；断言 event、category、component、user、repo/branch、duration。
- sentinel query 和 token-shaped string 序列化全部 captured logs 后断言不存在。
- monkeypatch module logger 的 `info/warning` 抛异常，业务成功仍返回相同 response，业务失败仍抛原异常。
- blank query 当前在 `query_service.py:142-143` 于 started 之前拒绝；测试应明确 no-query 路径是否零事件，避免误写成 started/failed。

### `test_graph_query_sampling.py` 与 `test_access.py`

**Analog:** `test_access.py:333-504`。

```python
for source_path in sorted(package_dir.glob("*.py")) + siblings:
    tree = ast.parse(source_path.read_text(encoding="utf-8"))
    for call in _iter_logger_calls(tree):
        # 静态事件名、prefix、component、category、error redaction
```

- 扩 `_CALLER_ENTRY_MODULES` 只能登记真正入口；纯内核只能 `sampling`。
- 增加静态 guard：禁止 logger kwargs 名为 `query`/`query_text`/`prompt`，禁止 `query[:N]`，禁止 resolver/BFS/row loop 内 INFO。
- 行为测试捕获 resolver batch、Process rebuild/index、Symbol/Process lane、impact 的 summary，断言闭集字段与 `duration_ms`。
- `test_access.py` 当前只扫描 `services/code_graph/*.py` 与两个显式 sibling；`services/retrieval/*.py` 需要新增明确扫描面，不能误以为现有 glob 已覆盖。

### `test_graph_bench_closure.py`

**Analogs**
- 真仓 artifact 关联：`test_graph_bench_integration.py:26-54`。
- canonical contract/hash：`test_query_contract_conformance.py:25-83`。
- 权限/exclusion：`test_access.py:53-205`。
- partial/degradation：`test_query_service.py:143-206,305-321`。

**应组合而非复制**
- 默认单测验证 schema/hash/version/same-watermark/权限/exclusion/partial 语义。
- 真实 baseline/candidate gate 保持 external integration，缺环境时 phase 标 blocked/human-needed；不能用默认 skip 当验收成功。
- holdout 只在 final acceptance 显式开启；MCP/task/npm conformance 继续调用现有 suites，不把跨语言契约复制进 Python fixture。

## Shared Patterns

### 纯函数与薄 I/O

**Source:** `graph_bench_eval.py:1-20` + `evaluate_graph_bench.py:1-31`。  
policy validation、hash identity、paired compare 和 resolver cell aggregation 都在纯函数层；文件读取、CLI、落盘、退出码仅在 command。

### Fail-closed 顺序

**Source:** `evaluate_graph_bench.py:297-353`。  
先 schema/hash/identity/watermark 验证并产 `INVALID` 证据，再允许执行或 gate；不可在 invalid 输入上计算“部分 PASS”。

### 结构化观测

**Source:** `query_service.py:145-157,462-492`、`impact.py:188-209`。  
caller 入口用 started/completed/failed，内部高频用 debug/sampling summary；每条有显式 `category/component`，异常脱敏，日志单独 best-effort。

### 触发用户传播

**Source:** `process_index.py:134-160`。  
后台入口接收 `initiated_by_user_id`，缺省 `system`，worker 入口用 `bind_task_context` 重绑，并在事件字段显式保留。

### 不变量与 marker

**Source:** `graph_bench_eval.py:313-325,632-647`。  
marker 原样保留，数值聚合仅接受 float；稀疏状态显式，不把缺证据记满分。Phase 140 comparator 在此基础上增加 required/optional gate 语义。

## No Exact Analog Found

| File | Reason | Planner Guidance |
|---|---|---|
| `server/codegraph/benchmark_policies/graph_query_threshold_policy.v1.json` | 仓内没有 benchmark threshold policy | 组合 `contracts/graph-query.v1.json` 的静态版本化契约与 `graph_bench manifest` 的冻结身份；正式值必须等待真实 baseline |
| `server/codegraph/services/graph_bench_compare.py` 的四态 verdict | 现有 evaluator 刻意无 threshold/compare | 复用 evaluator 的纯函数、marker、dataclass、排序模式；四态语义按 CONTEXT/RESEARCH 新建，不复制 scorer |

## Metadata

**Analog search scope:** `server/codegraph/`, `server/services/code_graph/`, `server/services/retrieval/`, `server/tests/codegraph/`, `server/tests/services/code_graph/`, `server/tests/code_relations/`  
**Primary files read:** 18  
**Pattern extraction date:** 2026-08-24  
**Hard blocker recorded:** 当前无真实 v0.22 baseline artifact，fixture manifest 仍为占位，不能合法生成正式 threshold 数值。
