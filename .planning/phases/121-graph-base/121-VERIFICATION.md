---
phase: 121-graph-base
verified: 2026-08-09T12:50:00Z
status: passed
score: 3.5/4 success criteria verified (SC-4 partial)
re_verification:
  previous_status: null
  note: initial verification — no prior 121-VERIFICATION.md existed
requirements:
  GRAPH-01: satisfied
  GRAPH-02: satisfied
  GRAPH-03: satisfied
  GRAPH-04: partial
gaps:
  - truth: "SC-4 — 被排除文件与无权限仓库在图读取层统一拦截（fail-closed），任何上层图分析工具的输出中均不可见"
    status: partial
    reason: >-
      运行期 fail-closed 成立且有回归覆盖；但把「上层工具天然继承」这件事变成硬约束的
      那道机械防线（ME-01 的修复用例 test_no_upper_layer_imports_internal_submodules）
      只匹配 `services.code_graph.<submodule>` 形式的模块路径，漏掉了
      `from services.code_graph import loader` —— 而这恰是本仓自身的惯用写法
      （test_cache.py 内 20+ 处、cache.py 对 access/signature 亦然）。已实证：在
      server/ 下植入一个 `from services.code_graph import cache, loader` 的探针文件后，
      该守护用例依然 PASS。Phase 122+ 的消费方可以用最自然的拼写绕过 GraphService
      的三道闸而 CI 全绿。
    artifacts:
      - path: "server/tests/services/code_graph/test_access.py:591-597"
        issue: "`len(parts) > 2` 使 ImportFrom 的 alias 名（`from pkg import loader`）永不进入判定"
    missing:
      - "AST 守护需同时检查 `ast.ImportFrom` 且 `node.module == 'services.code_graph'` 时的 `node.names[*].name` 是否落在 _INTERNAL_SUBMODULES"
      - "同理需覆盖 `import services.code_graph as cg` 后的 `cg.loader` 属性访问（可选，成本高、优先级低于上一条）"
deferred:
  - truth: "SC-1/SC-4 的端到端形态「Agent/工具查询」与「任何上层图分析工具的输出中不可见」"
    addressed_in: "Phase 122"
    evidence: "Phase 122 Success Criteria 5：'impact/trace 经 MCP 工具（PAT fail-closed + schema snapshot）与 agents 对话工具双面可调' —— 本相位无任何上层消费方，端到端只能由 122 兑现"
human_verification:
  - test: "生产多 worker 下的实际常驻内存与逐出频率"
    expected: "worker RSS 稳定在预期区间，code_graph_cache_evicted 不高频触发；据此复核 CODE_GRAPH_CACHE_MAX_BYTES=512MB / CODE_GRAPH_MAX_GRAPH_BYTES=256MB 默认值"
    why_human: "需真实部署与真实大仓，单测环境无法复现；121-VALIDATION.md 已登记为唯一 Manual-Only 项，属默认值调优而非功能正确性，不阻塞相位完成"
---

# Phase 121: 内存图服务基座 Verification Report

**Phase Goal:** Agent/工具查询任一已索引仓库时能拿到该 `(repository, branch)` 的内存符号图——缓存命中、水位一致、内存有界、权限与 exclusion 天然 fail-closed，为一切上层图工具提供共同地基。

**Verified:** 2026-08-09T12:50:00Z
**Status:** gaps_found（1 项 partial，无 BLOCKER）
**Re-verification:** No — initial verification

---

## 总体判断

这是一个**扎实的相位**。四条成功标准里三条完全成立且有非空洞的机械回归，第四条的运行期行为成立、但其「让上层天然继承」的强制手段有一处可实证的漏洞。

关键的方法论说明：**本相位没有任何上层消费方**（全仓 `code_graph` 的包外引用只有 `services/graph_builder.py:524` 与 `code_relations/tasks.py:233` 两处失效钩子，且都从包根导入）。因此 SC-1 与 SC-4 的「Agent/工具查询」「上层工具输出中不可见」只能在**服务层**证明，端到端要等 Phase 122。下文逐条标注了「测试已证」与「结构上合理但未被上层压过」的分界。

---

## Goal Achievement — 逐条成功标准

| # | Success Criterion | Status | Evidence |
|---|---|---|---|
| 1 | 首次查询触发建图，同键再查命中缓存不重复装配 | ✓ VERIFIED | `test_cache_hit_no_rebuild`：`load_graph` spy `call_count == 1` 跨两次 `get_graph`，且 `second is first`（同一对象）。同一用例还锁死了两条旁路——`acl_spy.call_count == 2`（命中不跳权限）、`inflight_spy.call_count == 2`（命中不跳闸门）。观测面由 `code_graph_stale_watermark` 事件断言覆盖（component/category/reason/签名截断 12 位） |
| 2 | 水位或边构建代数变化 ⇒ 旧缓存失效重建；取图时校验水位，绝不返回半新图 | ✓ VERIFIED（本相位最强的一条） | 见下节「SC-2 深查」 |
| 3 | 字节预算 LRU 逐出 + single-flight；超预算大仓降级，进程不 OOM | ✓ VERIFIED（一处语义需上层知悉） | 见下节「SC-3 深查」 |
| 4 | 排除文件与无权限仓库在图读取层统一拦截（fail-closed），上层输出中不可见 | ⚠️ PARTIAL | 运行期成立（见下节「SC-4 深查」）；机械防线有实证漏洞，已登记为 gap |

**Score:** 3.5/4

---

### SC-2 深查 —— 相位最硬的一条（三个焦点逐一核对）

**① 闸门确实在命中返回之前。** `cache.py::_get_graph_sync` 的步骤顺序被写成契约：

```785:816:server/services/code_graph/cache.py
        # ⑤ 🚨 in-flight 闸门**必须**在命中返回之前跑，位置不可调整。
        in_flight, in_flight_reason = signature.detect_edge_build_in_flight(
            repository_id, branch
        )

        if not seed_symbol_ids:
            with self._lock:
                entry = self._cache.get(key)
                if entry is not None:
                    if entry.built_signature != current_sig:
                        # ⑦ 签名不一致：条目已被证伪，移除并扣账后重建。
                    elif not in_flight:
                        # ⑥ 命中：签名一致 **且** 不在途。
                        return entry.graph
```

在途时走 `elif` 的落空分支——**只绕过、不驱逐**，条目未被证伪，边构建完成后签名自然推进触发正常替换。

**② 回归用例是真的，不是打桩出来的。** `test_partial_edges_rejects_cache_even_when_signature_matches` 用了一个精巧且正确的杠杆：轨 A 的签名分量 `ihA:` **刻意不含 `started_at`**，而轨 A 的在途判据第三条正是 `started_at >= cutoff`。于是单改 `started_at` 能翻转 in-flight 而签名逐字节不变。用例把这个前提**显式断言**了出来（`assert recomputed == cached_signature`）而不是假设它，然后才断言 `partial_edges is True`。用例注释明令不得打桩 `compute_signature` / `detect_edge_build_in_flight`——检查代码确认确实没打。**若闸门被挪到命中之后，这条用例必然失败。** 这是我能要求的最好的机械证据。

**③ D-03 的 PENDING 陷阱确实避开了。** `signature.py:375-381` 用三条件合取：`graph_build_status ∈ {PENDING, RUNNING}` **且** `history_status ∈ {PENDING, RUNNING}` **且** `started_at >= cutoff`。`test_pending_not_inflight` 五段覆盖，其中第 ④⑤ 段是**有效反证**——把整个函数改成 `return False, ""` 也能让前三段通过，第 ④⑤ 段能拦下这种静默失效。轨 B 的孤儿超时由 `test_orphan_running_not_inflight` 覆盖，超时阈值复用既有 `GRAPH_BUILD_ORPHAN_TIMEOUT_MINUTES`（不新增配置项，避免两处漂移导致长鸣）。

**④ 签名确实跨两条边构建轨（D-02）。** `compute_signature` 的七个分量：`wm:`（水位，分支索引行优先、回落 `Repository`）、`ihA:`（轨 A / ChunkEdge / `IndexHistory` 六字段）、`ghB:`（轨 B / Symbol·CallEdge·Endpoint / `GraphBuildHistory` 五字段）、`repoG:`（轨 B 老仓兜底，无条件追加）、`nsym:` / `ncall:`（计数，捕捉绕过 lifecycle 的裸写入）、`excl:`（exclusion 规则指纹）。**不是只看 `IndexHistory`** ——轨 B 有独立的两个分量，而 `CallEdge` 正是本相位图的主边源。

---

### SC-3 深查

| 子项 | Status | Evidence |
|---|---|---|
| 字节估算为纯函数 | ✓ | `test_estimate_bytes_is_pure` / `test_byte_constants_document_calibration` |
| LRU 按字节逐出 | ✓ | `test_evict_lru_until_within_budget` / `test_evict_loop_drops_multiple_entries` / `test_get_entry_moves_to_end_on_hit`；记账四条扣账路径（`_put` 先减旧、`_evict`、`invalidate`、步骤 ⑦）由 `test_put_overwrite_does_not_double_count` 守最易漏的那条 |
| single-flight 只建一次 | ✓ | `test_single_flight_builds_once`：4 线程 barrier 同发，`build_count == 1`，4 个返回值全同一对象，`_inflight` 收尾清空。全内存假 builder，不碰 DB |
| 失败不毒化 | ✓ | `test_build_failure_not_cached`：`finally` 无条件弹占位，异常路径不触及 `_cache`，下次可重试成功 |
| 等待者超时 | ✓ | `test_single_flight_waiter_times_out`；默认上界经 ME-08 从 120s 收到 30s |
| 装配前准入（不 OOM） | ✓ 结构成立 | `test_degraded_on_demand_subgraph` 断言 `load_spy.call_count == 0` ——证明是「先 COUNT 估算再决定装不装」，而非「先全量装配再看多大」。⚠️ 这是**结构性**证明：没有真实 OOM 压测，字节常数是标定估算值 |
| 并发原语正确性 | ✓ | 全 `threading`（D-04），`test_lock_discipline_documented_and_no_await` 的 AST 断言（唯一 `async def`、全部 `Await` 落在外壳内、`sync_to_async(` 恰一次、未 import `asyncio`）比 grep 强——grep 在这里会命中禁令散文自身 |

⚠️ **一处需要 Phase 122 知悉的语义**（不是缺陷，是刻意设计，但与标准字面表述有出入）：「超预算大仓走降级路径」**不是自动的**。`cache.py:970-981` 在「超预算 **且** 无种子」时**显式抛 `GraphError`** 并把出路写进消息，而不是自动降级：

```970:981:server/services/code_graph/cache.py
        if over_budget and not seed_symbol_ids:
            # ⛔ 不返回空图、也不返回截断的全量图：两者都会被上层读成「影响面就这么大」，
            # 而真相是「这仓大到装不下」。显式抛错并把出路写进消息里。
            raise GraphError(
                "本仓超出单图内存预算，请改用带 seed_symbol_ids 的按需子图查询",
```

这个选择是对的（宁可显式失败也不给会被误读的半成品），但它意味着**降级路径需要调用方主动传 `seed_symbol_ids` 才会走到**。Phase 122 的 impact/trace 必须处理这个异常分支，否则大仓上会直接报错而不是降级。

---

### SC-4 深查 —— 运行期成立，机械防线不成立

**运行期这一侧是干净的，逐条核过：**

| 闸 | 落点 | 证据 |
|---|---|---|
| 可读性校验 | `get_graph` async 外壳里**无条件**执行，不因缓存命中而跳过 | `access.py::ensure_repository_readable` 四道判定（UUID 合法性 / 存在性与软删合并出口不泄漏存在性差异 / `index_status != INDEXED` 抛 `GraphNotIndexed` **不返回空图** / ACL 扩展点）；`test_not_indexed_raises` / `test_deleted_repo_denied` / `test_invalid_repository_id_is_rejected`；命中不跳过由 `acl_spy.call_count == 2` 锁死 |
| exclusion 在**装配阶段** | `loader.py:401` 命中即 `continue`，节点不进集，邻接边随之消失 | `test_exclusion_hides_symbols_and_edges` / `test_exclusion_covers_unnormalizable_paths` / `test_subgraph_does_not_expand_through_excluded_symbols`（ME-05 修复） |
| matcher 失败 fail-closed | `access.py:244-262` 抛 `GraphAccessDenied` **整仓拒绝**，且不写 memo、不返回上一轮旧 matcher | `test_fail_closed_on_matcher_build_error` |
| 规则变更失效 | 规则指纹进签名第七分量 `excl:` | `test_fingerprint_changes_when_rules_change`；口径对**有效规则集**直接哈希，覆盖 per-repo 规则 + `SystemSetting` 全局 JSON + `BUILTIN_GLOBAL_DEFAULTS` 代码变更三个来源 |

**机械防线这一侧有一处实证漏洞（本报告的唯一 gap）。**

Code review 的 ME-01 正确识别了「barrel 只是约定不是防线」，并选了方案 2 加了 `test_no_upper_layer_imports_internal_submodules` 做全仓 AST 扫描。但该守护的匹配条件不完整：

```591:597:server/tests/services/code_graph/test_access.py
        for lineno, module in modules:
            parts = module.split(".")
            if parts[:2] == ["services", "code_graph"] and len(parts) > 2:
                if parts[2] in _INTERNAL_SUBMODULES:
```

`ast.ImportFrom` 只贡献 `node.module`，`node.names[*].name` 从未参与判定。于是 `from services.code_graph import loader` 解析出的 `module` 是 `"services.code_graph"`（`len(parts) == 2`），**直接落空**。

实测三种拼写：

| 拼写 | 守护结论 |
|---|---|
| `from services.code_graph.loader import load_graph` | CAUGHT |
| `import services.code_graph.loader` | CAUGHT |
| `from services.code_graph import loader` | **BYPASS** |
| `from services.code_graph import cache as c` | **BYPASS** |

并做了端到端实证：在 `server/` 下植入探针文件 `_tmp_guard_probe.py`（内容 `from services.code_graph import cache, loader`），运行 `pytest tests/services/code_graph/test_access.py -k upper_layer` → **1 passed**。探针已删除，`git status` 确认无残留。

**为什么这条重要而非吹毛求疵：** 漏掉的恰恰是**本仓自己的惯用写法**——`cache.py` 对 `access` / `signature` 用的就是这个形式，`test_cache.py` 里有 20+ 处。Phase 122 的作者照着包内既有风格写 `from services.code_graph import loader`，就能自造一个 matcher 传进 `load_graph`，三道闸一次全过，而 CI 全绿。防线在**最可能被踩中的那条路径**上是敞开的。

判为 `partial` 而非 `failed` 的理由：当前包外零违规（两处失效钩子均从包根导入并附了注释说明理由），运行期没有任何实际泄漏；`__init__.py` 的 docstring 也如实写明了「光靠不导出挡不住」。缺的只是守护用例少覆盖一个分支——修复约 3 行。

---

## Requirements Coverage

| Requirement | 描述（REQUIREMENTS.md） | REQUIREMENTS.md 现状 | 本次独立判定 | 依据 |
|---|---|---|---|---|
| GRAPH-01 | 提供 `(repository, branch)` 内存符号图装配，首次构建后命中缓存不重复建图 | Complete | ✓ SATISFIED | SC-1；四类数据装配（`Symbol`/`CallEdge`/`ChunkEdge` 旁挂证据面/`CrossRepoApiCall`）+ `MultiDiGraph`（D-01）+ 四档置信度 + overlay 去重（D-06）均有覆盖 |
| GRAPH-02 | 水位/边构建代数变化后失效重建；取图时校验，不返回半新图 | Complete | ✓ SATISFIED | SC-2；相位内证据最强的一条，三个焦点全部经代码核对而非采信 SUMMARY |
| GRAPH-03 | 字节预算 LRU + single-flight + 降级路径，进程不 OOM | Complete | ✓ SATISFIED | SC-3；「不 OOM」为装配前准入的结构性保证，无真实压测（已登记为 human_verification） |
| GRAPH-04 | 读取层统一收口权限与 exclusion（fail-closed），排除文件在所有图工具输出中不可见 | Complete | ⚠️ PARTIAL | SC-4；运行期收口成立，前半句满足。后半句「在**所有**图分析工具输出中不可见」依赖 barrel 不可绕，而该强制手段有实证漏洞，且本相位尚无上层工具可供检验 |

**对 REQUIREMENTS.md 现状的独立意见：** GRAPH-01/02/03 标 Complete 是**站得住**的。GRAPH-04 标 Complete **略微超前**——建议要么补上那 3 行守护修复后再维持 Complete，要么在 Phase 122 首个消费方接入并验证「排除文件确实不可见」之后回填确认。二者取其一即可，不必两者都做。

无 ORPHANED 需求：REQUIREMENTS.md 映射给 Phase 121 的恰是 GRAPH-01~04，与各 PLAN 的 `requirements` 声明一致。

---

## Anti-Patterns Scan

对 `server/services/code_graph/` 五个源文件扫描 `TBD` / `FIXME` / `XXX` / `HACK` / `PLACEHOLDER` / 空实现 / `console.log` 等价物：

| 结果 | 说明 |
|---|---|
| 无 `TBD` / `FIXME` / `XXX` | 债务标记闸通过，完成度可审计 |
| `_check_user_acl` 恒 `return None` | **不是 stub**——这是 121-CONTEXT Area 4 明示的「不发明 ACL 模型，只收口校验点并预留扩展位」，docstring 写明了落地时的出口约定，`test_user_acl_extension_point_is_empty` 显式锁住当前语义。当前仓库层权限本就只有「认证 + 存在性」两道 |
| `except Exception: pass` 多处 | 全部是观测 best-effort 包裹，带 `# noqa: BLE001` 与「不是安全降级分支」的注释；符合 `.cursor/rules/observability-logging.mdc`「观测代码永不反噬业务」 |

**观测规范符合性：** `component="code_graph"` 已按 D-07 登记进 `LOGGING-SPEC.md:148`，并在 `:150` 附了与既有 `codegraph`（无下划线，索引/抽取侧 app）并存的理由。包内每个 structlog 调用带 `component` + `category="sampling"` + `code_graph_` 前缀，由 `test_observability_contract` 的 AST 扫描机械守住（含 `error=` 必过 `redact_secrets_in_text`）。关键生命周期带 `duration_ms`。缓存命中走 DEBUG、建图完成走 INFO，未在热路径刷屏。

---

## Behavioral Spot-Checks

| 检查 | 命令 | 结果 | Status |
|---|---|---|---|
| barrel 导出面恰 17 项 + AST 越界守护 + 观测契约 | `pytest tests/services/code_graph/test_access.py -k "barrel or upper_layer or observability"` | 3 passed | ✓ PASS |
| AST 守护对 `from services.code_graph import loader` 的拦截力 | 植入探针文件后跑 `-k upper_layer` | **1 passed（未拦下）** | ✗ FAIL → 已登记为 gap |
| AST 匹配逻辑离线复算（5 种拼写） | 独立 `ast.parse` 复算 | 3 CAUGHT / 2 BYPASS | ✗ FAIL（同上，同一根因） |
| 包外零违规现状 | 全仓 grep `code_graph` 的包外引用 | 仅 `graph_builder.py:524` 与 `code_relations/tasks.py:233`，均从**包根**导入 | ✓ PASS |

**沿用已收集证据（未重跑）：** `pytest tests/services/code_graph` → 96 passed / 0 skipped；`pytest -m perf` → 2 passed（已由 ME-09 修复门禁到 `FRIDAY_PERF_ALLOW_PRODUCTION_DB=1` 显式授权，安全默认值是**不连**生产库）；`makemigrations --check --dry-run` → No changes（零迁移约束成立，与「本相位零新表」的锁定约束一致）；`ruff` 干净 / `mypy services/code_graph` 0 错；全量 10 failed / 10128 passed，10 条已用两个 worktree 归因为与本相位无关（6 条 pre-phase baseline 既有，4 条为并发会话未提交改动所致）。

---

## Deferred / Unproven —— 明确清单

### 一、本相位无上层消费方（结构性，非缺陷）

SC-1 的「Agent/工具查询」与 SC-4 的「任何上层图分析工具的输出中均不可见」在本相位**只能在服务层证明**。全仓包外引用仅两处失效钩子。端到端由 Phase 122 Success Criteria 5（MCP + 对话双面暴露）兑现。这不影响相位判定——地基相位本就如此——但它意味着以下几点属于「结构上合理、尚未被真实上层压过」：

- 四档置信度契约（`resolved` / `bare_name` / `cross_repo` / `chunk_level`）对上层是否够用
- `partial_edges` / `degraded` / `low_resolution` / `cross_repo_unresolved_count` 四个降级标记的上层透出路径
- `REDACTED_REPOSITORY` 折叠语义（本相位只定义契约，Phase 122 跨仓 impact 才会真正使用）
- 超预算大仓的 `GraphError` 分支必须被 Phase 122 显式处理（见 SC-3 深查）

### 二、Code review 明示未做的 5 条（全部 LOW / 已登记）

来自 `121-REVIEW.md`（20 findings：1 BLOCKER + 1 HIGH + 10 MEDIUM + 8 LOW；BLOCKER 与 HIGH 已清零，15 fixed / 1 documented / 4 deferred）：

| # | 内容 | 处置 |
|---|---|---|
| ME-10 | 降级路径两处全仓扫描 | 📝 登记在案，未修 |
| LO-02 | 未校验 `max_graph_bytes <= max_bytes` | ⏭️ 未做 |
| LO-03 | `_MATCHER_FP_CACHE` 无上界 | ⏭️ 未做 |
| LO-04 | 读 matcher 私有属性（`_repository_id`） | ⏭️ 未做 |
| LO-05 | 若干事件缺 `initiated_by_user_id`（contextvars 已兜底） | ⏭️ 未做 |

这些不阻塞相位目标，但 LO-03 在长生命周期 worker 上是缓慢内存增长的种子，建议与本报告的 gap 一并处理。

### 三、只有默认值、没有生产实测的部分

- `CODE_GRAPH_CACHE_MAX_BYTES=512MB` / `CODE_GRAPH_MAX_GRAPH_BYTES=256MB` / `CODE_GRAPH_BUILD_WAIT_TIMEOUT_SECONDS=30` 三个默认值来自本仓最大仓的单机标定，未经多 worker 生产验证（见 frontmatter `human_verification`）
- 字节估算常数 `NODE_COST_BYTES` / `EDGE_COST_BYTES` 按 `MultiDiGraph` 标定，随 networkx 版本可能漂移
- `_wait_for_inflight` 在非请求路径（channels consumer / `background_runner` / durable worker）会占住进程唯一一条 `SyncToAsync.single_thread_executor` 线程最长 30s。这是**已知且已在代码里如实记录**的头阻塞（ME-08），不是死锁，但生产上值得盯

---

## Gaps Summary

**一条 partial，无 BLOCKER，不建议因此回退相位。**

Phase 121 交付的是一个质量明显高于平均水平的地基：SC-2 的闸门位置回归用例（用 `ihA:` 不含 `started_at` 这个性质造出「签名逐字节相同但 in-flight 翻转」的场景，并把签名相等**断言**出来而非假设）是我在验证中见过的最有说服力的一类机械证据；D-03 的反证段、single-flight 的零 DB 并发用例、`nx.freeze` 的只读契约、AST 而非 grep 的规范守护，都体现出对「用例可能是空洞的」这件事本身的警惕。

唯一的 gap 出在一处**修复本身不完整**：ME-01 正确诊断了「barrel 只是约定」，也正确选择了「真正机械化」的方案，但新增的 AST 守护漏掉了 `from services.code_graph import loader` 这条最自然、且是本仓自身惯用的拼写。我用探针文件实证了绕过。修复约 3 行——在现有循环里追加对 `ast.ImportFrom` 的 `node.names[*].name` 的判定。

**为什么现在修而不是留给 Phase 122：** 这条红线的价值全在「第一条违规写进来的那一刻就红」。目前包外违规数为 0，是建防线成本最低的时刻；一旦 Phase 122 落地几十处调用，再补守护就要先清历史违规，性质就从「防线」变成「技术债清理」了。守护用例自己的注释也是这么写的。

---

_Verified: 2026-08-09T12:50:00Z_
_Verifier: Claude (gsd-verifier) — goal-backward，不采信 SUMMARY 声明_

## 缺口闭环（2026-08-09，验证后补）

验证判定的唯一缺口（criterion 4 / GRAPH-04 的 AST import 守护漏判）已闭合。

**问题**：`test_no_upper_layer_imports_internal_submodules` 只检查 `ast.ImportFrom.module`，
而 `from services.code_graph import loader` 这种写法的 `module` 正是包根 `services.code_graph`，
违规藏在 `names` 里 —— 恰恰是包内部自己惯用、上层最容易照抄的那种拼法。

**修复**：`ImportFrom` 且 `module == "services.code_graph"` 时，额外把每个 `alias.name`
拼成 `services.code_graph.<name>` 一并送去判定。

**证据**：在 `server/` 下放一个 `from services.code_graph import loader, cache` 的探针文件，
守护用例如期变红并同时点名两个子模块（`probe_bypass_tmp.py:1 services.code_graph.loader`
与 `…cache`）；删除探针后 `tests/services/code_graph` 恢复 **96 passed / 0 skipped**，
`ruff check tests/services/code_graph` 通过。全仓当前违规数仍为 0。

判定由 `gaps_found` 改为 **`passed`**：四条成功标准全部成立，GRAPH-01~04 全部达成。

⚠️ 仍然成立的、非缺口的如实声明：本相位是纯地基，**尚无任何上层消费者**，
置信度分档契约、四个降级标记与 `REDACTED_REPOSITORY` 语义要到 Phase 122 才真正承压；
「进程不 OOM」是准入判据的保证，不是压测结论。五条主动递延的 review findings
（ME-10 + 四条 LOW）清单见 `121-REVIEW.md`。
