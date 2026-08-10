---
phase: 121-graph-base
reviewed: 2026-08-09T19:24:00Z
depth: deep
diff_base: 85736953
files_reviewed: 14
files_reviewed_list:
  - server/services/code_graph/__init__.py
  - server/services/code_graph/model.py
  - server/services/code_graph/access.py
  - server/services/code_graph/signature.py
  - server/services/code_graph/loader.py
  - server/services/code_graph/cache.py
  - server/tests/services/code_graph/conftest.py
  - server/tests/services/code_graph/test_access.py
  - server/tests/services/code_graph/test_cache.py
  - server/tests/services/code_graph/test_loader.py
  - server/tests/services/code_graph/test_model.py
  - server/tests/services/code_graph/test_signature.py
  - server/tests/services/code_graph/test_perf_diagnostics.py
  - server/friday/settings.py
findings:
  blocker: 1
  high: 1
  medium: 10
  low: 8
  total: 20
status: fixed
fixed_at: 2026-08-09T20:35:00Z
resolution:
  fixed: 15
  documented: 1
  deferred: 4
  outstanding_blocker: 0
  outstanding_high: 0
tests_after: 96 passed / 0 skipped（修复前 86）
---

# Phase 121: Code Review Report

**Reviewed:** 2026-08-09T19:24:00Z
**Depth:** deep（跨模块调用链 + 契约一致性 + 测试有效性）
**Scope:** `85736953..HEAD` 的 source 部分
**Status:** fixed（BLOCKER / HIGH 已清零；详见下方「修复状态」）

---

## 修复状态（2026-08-09T20:35Z）

20 条里 **15 条已修 + 1 条登记在案 + 4 条 LOW 未做**。BLOCKER 与 HIGH 全部清零。
用例数 **86 → 96**（0 skipped），`ruff` 干净、`mypy services/code_graph` 包内 0 错、
`makemigrations --check --dry-run` 无变更。

| # | 结论 | 提交 | 回归用例 |
|---|------|------|----------|
| **BL-01** 缓存键缺 `include_low_confidence` | ✅ 已修 | `664ab7d2` | `test_include_low_confidence_is_part_of_the_cache_key`（污染 / 漏报两个方向）、`test_single_flight_placeholder_keyed_by_include_low_confidence` |
| **HI-01** 跨仓边可被伪造 | ✅ 已修 | `d40247ab` | `test_cross_repo_far_side_never_matched_against_local_index`（两个方向） |
| ME-01 barrel 只是约定 | ✅ 已修（选方案 2） | `e6b89d76` | `test_no_upper_layer_imports_internal_submodules` |
| ME-02 命中返回共享可变图 | ✅ 已修（契约 + `nx.freeze` 硬约束） | `88da3775` | `test_returned_graph_is_frozen_against_in_place_mutation` |
| ME-03 两处 emit 未 best-effort | ✅ 已修 | `87bb7b4f` | 由 `test_observability_contract` 与现有逐出用例覆盖 |
| ME-04 frontier 截断未进 `GraphMeta` | ✅ 已修（`degraded` 第二档） | `87bb7b4f` | `test_on_demand_subgraph_frontier_truncation` |
| ME-05 子图穿过被排除符号扩张 | ✅ 已修 | `3545f54e` | `test_subgraph_does_not_expand_through_excluded_symbols` |
| ME-06 `(file, name)` 撞车静默覆盖 | ✅ 已修（`_AMBIGUOUS` 哨兵） | `0f736fb9` | `test_same_file_same_name_symbols_are_ambiguous_not_silently_overwritten` |
| ME-07 `seed_symbol_ids` 未校验 | ✅ 已修 | `18331db0` | `test_seed_symbol_ids_must_be_valid_uuids` |
| ME-08 等待者占执行器线程 120s | ✅ 已修（文档 + 默认值 120→30） | `88da3775` | 无新增（`test_single_flight_waiter_times_out` 已覆盖超时语义） |
| ME-09 perf 用例会连生产库 | ✅ 已修（`FRIDAY_PERF_ALLOW_PRODUCTION_DB=1` 显式授权） | `106f568f` | `test_production_db_requires_explicit_opt_in`（**不带** `perf` 标记，常规采样即跑） |
| ME-10 降级路径两处全仓扫描 | 📝 登记在案，未修 | `e6b89d76` | — |
| LO-01 `over_budget or …` 前半段不可达 | ✅ 已修 | `18331db0` | — |
| LO-06 子图丢弃 chunk 截断计数 | ✅ 已修 | `87bb7b4f` | `test_on_demand_subgraph_frontier_truncation` |
| LO-08 `depth` 未钳位 | ✅ 已修（`_estimate_admission` 返回值那半条未做） | `18331db0` | `test_depth_is_clamped_instead_of_silently_degrading` |
| LO-02 未校验 `max_graph_bytes <= max_bytes` | ⏭️ 未做 | — | — |
| LO-03 `_MATCHER_FP_CACHE` 无上界 | ⏭️ 未做 | — | — |
| LO-04 读 matcher 私有属性 | ⏭️ 未做 | — | — |
| LO-05 若干事件缺 `initiated_by_user_id` | ⏭️ 未做 | — | — |
| LO-07 perf survey 断言恒真 | ⏭️ 未做 | — | — |

**未做项的理由**（都不是「忘了」）：

- **ME-10**：修法已探明（chunk 侧按 `chunk_to_symbols` 反查收敛，跨仓侧按已装载符号的
  去重文件集加 `__in`），但当前无实测依据说明它真的疼——产出本就有界，痛的只是迭代量，
  而生产最大仓才 3 万符号、根本走不到降级路径。已把这条局限连同修法一起写进
  `load_subgraph` 的 docstring，并注明「查询条数用例数不出扫描行数，别把它的绿色读成
  处处收敛」。等真的观察到大仓降级变慢再做。
- **LO-02**：`max_graph_bytes > max_bytes` 直接抛会打红现有的
  `test_evict_loop_drops_multiple_entries` —— 那条用例**刻意**构造
  `max_bytes < max_graph_bytes` 来验证「一个大条目连逐两个」。要修得连同该用例的构造
  一起改，已超出「低风险自包含」的范围。
- **LO-03 / LO-04 / LO-05 / LO-07**：均为 LOW 且非行为缺陷（分别是：218 仓量级下无碍的
  内存上界、`getattr` 已兜住的耦合、contextvars 已兜底的字段不一致、诊断交付物里的弱
  断言）。按本轮「LOW 仅在 trivially safe 时才动」的口径跳过。
- **LO-08 的后半条**（`_estimate_admission` 丢弃前两个返回值）：`depth` 钳位已做；
  返回值那半条要么改签名要么加埋点字段，两者都会牵动现有的准入接缝用例，未做。

## Summary

这一相位的代码质量整体明显高于平均线：四道横切纪律（in-flight 闸门位置、字节记账口径、fail-closed exclusion、`reason` 现推）都在代码里有机械落点，测试里也确实有对应的反证段（`test_partial_edges_rejects_cache_even_when_signature_matches` 是全套用例里最硬的一条，它靠「轨 A `started_at` 不入签名」这个真实杠杆造出「签名逐字节一致」的前提，不打任何桩）。我逐条核对了任务里点名的 7 个焦点，结论见下面的「焦点核对」。

但缓存键少了一维：**`include_low_confidence` 既不在缓存键里，也不在 single-flight 占位键里**。这直接击穿本相位的验收内核之一（「裸名边默认不参与扩散」，研究 Pitfall 1），且它与执行方自己为 `seed_symbol_ids` 写下的那条推理（「那是错图，不是慢图」）是同一形状——只是没有推广到第二个会改变装配产物的开关上。这是唯一的 BLOCKER。

另有一处 HIGH：跨仓边的**对端**端点用本仓的 `(file_path, name)` 索引解析，而代码取了 `call_site__repository_id` / `endpoint__repository_id` 两列却弃之不用，于是路径与函数名撞车时会凭空造出一条挂在两个本仓符号之间的 `cross_repo` 边。

D-07（`code_graph` 写进 `LOGGING-SPEC §5`）已落地并附了与 `codegraph` 并存的理由，观测契约由 `test_observability_contract` 的 AST 扫描机械守住（component / category / 事件名可静态解析 / `error=` 必过 `redact_secrets_in_text`），这条做得很扎实。

---

## 焦点核对（逐条对代码，不采信 SUMMARY）

| # | 焦点 | 结论 |
|---|---|---|
| 1 | GRAPH-02 闸门位置 | ✅ 成立。`detect_edge_build_in_flight` 在 `cache.py:644`，命中判定在 `cache.py:649` 之后；在途走 `elif not in_flight` 的落空分支，**只绕过不驱逐**（`cache.py:663-669`），驱逐只发生在签名不一致时。D-03 的 PENDING 陷阱在 `signature.py:373-382` 用三条件合取避开，`test_pending_not_inflight` 的第 ④⑤ 段是有效反证 |
| 2 | GRAPH-03 记账 / single-flight | ✅ 记账一致：`_Entry.estimated_bytes` 与 `GraphMeta.estimated_bytes` 同源于 `cache.py:862` 的同一个局部变量。逐出不会欠账（`_put` 先减旧、`_evict` 与 `invalidate` 均同步扣减）。single-flight 无 await-under-lock（AST 用例守住），用 `threading.Event`，失败在 `finally` 无条件弹占位、不写缓存 |
| 3 | GRAPH-04 fail-closed | ⚠️ 部分成立。`get_graph` 路径无法绕过 `ensure_repository_readable` 与 exclusion；matcher 构造失败确实抛 `GraphAccessDenied` 且不写 memo；过滤确在装配阶段（节点不进集 + 端点缺失即整边丢弃）。**但 barrel 不是机械防线**——`from services.code_graph.loader import load_graph` 可直接调用，守护用例只查 `__all__`（见 ME-01） |
| 4 | D-01 / D-08 | ✅ 均成立。`nx.MultiDiGraph()`（`loader.py:1016/1131`），并存多档边有回归；边属性恒 3 个、`cross_repo` 档 4 个为唯一例外，`reason` 不在边属性里、由 `derive_reason` 现推 |
| 5 | 观测规范 | ⚠️ 大体合规（AST 契约守护 + `duration_ms` + 脱敏 + 热路径 DEBUG）。两处 emit 未按本模块自己声明的 best-effort 包 try（ME-03），若干事件缺 `initiated_by_user_id`（LO-05，contextvars 已兜底，故仅 LOW） |
| 6 | 并发 | ⚠️ 无死锁、无跨 loop 隐患（全 `threading`，单例 lazy + 锁保护，TTL memo 有锁）。真实代价是 `_wait_for_inflight` 会阻塞 `thread_sensitive` 执行器线程最长 120s（ME-08） |
| 7 | 测试质量 | ✅ 主体非空洞：AST 断言确实比 grep 更强（它剥掉 docstring 后查代码引用，而 grep 会命中禁令自己）。但 `test_perf_diagnostics.py` 的 survey 段断言基本是恒真的（LO-07），且它会连生产库（ME-09）。**缺一整类覆盖**：没有任何用例覆盖 `include_low_confidence` 与缓存键的交互（BL-01 因此没被拦下） |

---

## BLOCKER

### BL-01: `include_low_confidence` 不在缓存键与 single-flight 键里 —— 裸名边会泄漏给要求安全默认值的调用方

> **✅ 已修（`664ab7d2`）**：`CacheKey` 增加第三维；`GraphMeta` 增加
> `include_low_confidence` 字段（15 → 16，标记类字段 4 → 5），让上层拿到图之后可以自检
> 而不必遍历边集反推。⛔ 未采用「只缓存 `False` 档」的替代方案——两档各自缓存的内存
> 代价是可控的，而让开启档每次冷建会在 Phase 122 打开该开关时变成一次一建。
> 回归：`test_include_low_confidence_is_part_of_the_cache_key` 覆盖污染与漏报两个方向 +
> 「两档各自缓存一份、互不覆盖」；`test_single_flight_placeholder_keyed_by_include_low_confidence`
> 覆盖占位键（等待上界压到 0，占位键一旦退化回两维就**立刻**超时，而不是挂满上界）；
> `test_invalidate_evicts_repo_entries` 补一条开启档条目，钉死按仓驱逐覆盖第三维。

**File:** `server/services/code_graph/cache.py:620`（键构造）、`cache.py:651`（命中查询）、`cache.py:876-886`（写入）、`cache.py:702-711`（占位键）

`include_low_confidence` 会实质改变装配产物——`loader.py:635` 明确对该开关分流，`test_bare_name_edge_not_loaded_by_default` 也断言了 0 条边 vs 1 条边的差异。但缓存键只有 `(repository_id, branch)`：

```python
key: CacheKey = (repository_id, branch)          # cache.py:620
...
entry = self._cache.get(key)                     # cache.py:651 —— 不看 include_low_confidence
...
self._put(key, _Entry(graph=result, ...))        # cache.py:878
```

三个后果，第一个是安全性质的：

1. **污染方向（危险）**：任一调用方先以 `include_low_confidence=True` 建过图，之后**所有**使用安全默认值的调用方都会命中这张含裸名边的图。本相位把「裸名边默认不参与扩散」列为验收内核（CONTEXT Area 3 / 研究 Pitfall 1「裸名边假阳性灾难」）；此路径下 Phase 122 的 impact 会把 `foo → helper` 这种凭名字连出来的边当成真影响面报给 agent，而调用方从未开启过这个开关。
2. **反方向（漏报）**：先建了默认图，随后 `include_low_confidence=True` 的请求会命中它，拿到一张**没有**裸名边的图，却以为自己开启了低置信度扩散。
3. **single-flight 同病**：`_build_single_flight` 用同一个 `key` 建占位（`cache.py:705`），两个 flag 不同的并发请求里，等待者会拿到领头那份 flag 不同的图。这与执行方自己为 `seed_symbol_ids` 写下的注释（`cache.py:687-689`「那是错图，不是慢图」）是**完全同一条推理**，只是没有推广到第二个维度。

`GraphMeta` 里也没有任何字段声明「这张图是否含裸名边」，所以上层拿到图之后**无从自检**。

**Fix:** 把开关并入缓存键与占位键，并在 `GraphMeta` 上如实声明。最小改动：

```python
# cache.py —— 键类型加一维
CacheKey = tuple[str, str, bool]  # (repository_id, branch, include_low_confidence)

# _get_graph_sync
key: CacheKey = (repository_id, branch, include_low_confidence)
```

连带需要改的三处：
- `GraphService.invalidate`：`key[0] == repo_key` 的过滤保持不变（仍是按仓驱逐），无需改。
- `_log_*` 里的 `branch=key[1]` 保持不变。
- `test_invalidate_evicts_repo_entries` / `_make_entry` 等用例的键字面量需补第三维。

并补一条回归用例（当前完全缺失）：

```python
@pytest.mark.django_db(transaction=True)
async def test_include_low_confidence_is_part_of_the_cache_key(
    indexed_repo, symbols_factory, call_edges_factory
) -> None:
    """开了裸名边的图不得被默认请求命中——反之亦然。"""
    caller = symbols_factory("caller", "src/a.py")
    symbols_factory("helper", "src/a.py", start_line=50, end_line=60)
    call_edges_factory(caller, None, callee_name="helper", callee_file="src/a.py")

    svc = cache_module.get_graph_service()
    repo_id = str(indexed_repo.id)

    opened = await svc.get_graph(repo_id, include_low_confidence=True)
    assert opened.graph.number_of_edges() == 1

    closed = await svc.get_graph(repo_id)  # 安全默认值
    assert closed.graph.number_of_edges() == 0, (
        "默认请求命中了含裸名边的缓存条目——include_low_confidence 不在缓存键里"
    )
```

若不愿意为该开关多占一份内存，替代方案是**只缓存 `include_low_confidence=False` 的图**（`cacheable = not in_flight and not include_low_confidence`），并让开启档的请求每次冷建；但仍必须把开关并入 single-flight 占位键，否则等待者拿错图的问题不解。

---

## HIGH

### HI-01: 跨仓边的对端端点被拿去撞本仓符号索引 —— 会造出伪造的 `cross_repo` 边

> **✅ 已修（`d40247ab`）**：按建议实现——每一侧只在 `str(该侧 repository_id) ==
> str(repository_id)` 时才解析，任一侧解析不到即整条丢弃并 `unresolved_count += 1`
> （D-05 不变）。两个下划线前缀已去掉，docstring 里那句「对端侧用同一张索引尝试」也
> 一并改正（它正是这个 bug 的书面来源）。
> 回归：`test_cross_repo_far_side_never_matched_against_local_index` 造两个仓，让 B 仓
> `Endpoint` 的 `(file_path, handler_name)` 与 A 仓某符号**完全同名**，断言两个方向
> （从 A 看、从 B 看）都不建边且各自 `cross_repo_unresolved_count == 1`。
> ⚠️ 顺带：`_make_cross_repo_call` 增加 `endpoint_repository` 参数，此前该辅助函数
> 只造得出「两端同仓」的行——这正是原用例覆盖不到该分支的原因。

**File:** `server/services/code_graph/loader.py:753-774`

查询按 `Q(call_site__repository_id=repo) | Q(endpoint__repository_id=repo)` 取行（`loader.py:733-736`），因此**每一行至少有一侧在本仓、另一侧可能在别的仓**。代码取出了两侧的 repository_id：

```python
for (
    _call_site_repository_id,   # loader.py:754 —— 取了但没用
    caller_file,
    caller_function,
    call_line_number,
    _endpoint_repository_id,    # loader.py:758 —— 取了但没用
    endpoint_file_path,
    handler_name,
    ...
) in rows:
    caller_node = _resolve_by_file_and_name(by_file_and_name, caller_file, caller_function, ...)
    callee_node = _resolve_by_file_and_name(by_file_and_name, endpoint_file_path, handler_name, ...)
```

`by_file_and_name` 只装了**本仓**符号。docstring（`loader.py:716-718`）写的是「对端侧用同一张索引尝试，查不到即整条边丢弃」——问题在于对端侧**可能查得到**：微服务仓之间路径与 handler 命名高度同构（`internal/handler/user.go` + `GetUser`、`src/api/views.py` + `order_create`）。一旦撞上，就会在两个**本仓**符号之间加一条 `kind="cross_repo"` 的边，`match_confidence` 还照抄了那条跨仓匹配的原值。

这条伪造边比裸名边更难被发现：它带着 `match_confidence=1.0` 这种高可信度标签，`cross_repo` 档还是**默认参与扩散**的（CONTEXT Area 3），而 `cross_repo_unresolved_count` 不会 +1（它解析"成功"了），上层没有任何信号可用来打折。

现有用例 `test_cross_repo_edge_resolution` 造的两端都在同一个 `indexed_repo` 里，所以覆盖不到这个分支。

**Fix:** 让每一侧只在「该侧确实属于本仓」时才解析。

```python
    caller_node = (
        _resolve_by_file_and_name(
            by_file_and_name, caller_file, caller_function, normalize_rel_path
        )
        if str(_call_site_repository_id) == str(repository_id)
        else None
    )
    callee_node = (
        _resolve_by_file_and_name(
            by_file_and_name, endpoint_file_path, handler_name, normalize_rel_path
        )
        if str(_endpoint_repository_id) == str(repository_id)
        else None
    )
    if caller_node is None or callee_node is None:
        unresolved_count += 1
        continue
```

改完后两个下划线前缀应去掉（它们现在有用了）。配套用例：造两个仓，让 B 仓的 `Endpoint.file_path` / `handler_name` 与 A 仓某个符号完全同名，断言 A 仓的图里**没有**这条边、且 `cross_repo_unresolved_count == 1`。

---

## MEDIUM

### ME-01: barrel 只是约定，不是「机械防线」—— 子模块可以被直接 import

> **✅ 已修（`e6b89d76`）**：选了方案 2（真正机械化）。新增 `test_no_upper_layer_imports_internal_submodules`，AST 扫全仓（跳过 `.venv` / `node_modules` 等非本仓源码、跳过包自身与其测试目录），包外任何一处直连 `loader` / `cache` / `signature` / `access` 都会红；`model` 不在禁列——它是纯契约层且从包根导出。当前违规数 0，用时 <1s。`__init__.py` 的 docstring 同步改为指向这条用例，不再让「机械防线」的承诺悬空。

**File:** `server/services/code_graph/__init__.py:10-21`、`server/tests/services/code_graph/test_access.py:511-533`

`__init__.py` 的 docstring 自称「本文件就是这条红线的机械防线」，把绕闸「从需要自律降级为需要刻意书写内部模块路径（ASVS V1）」。实际上 `__all__` 只影响 `from ... import *`；`from services.code_graph.loader import load_graph` 与 `from services.code_graph.cache import GraphService` 都能正常工作，而 `loader.__all__ = ["load_graph", "load_subgraph"]` 还把两个装配函数标成了公开面。绕过 `load_graph` 只需传一个自造的 `matcher`（比如测试里的 `_NoopMatcher`），三道闸——可读性、exclusion、水位复校——一次全过。

守护用例 `test_barrel_exports_only_public_surface` 只断言这些名字不在 `code_graph_package.__all__` 里，对 `import services.code_graph.loader` 这条真实通路没有任何约束力。也就是说这条断言守的是「barrel 没有变胖」，不是「没人绕闸」——而 docstring 声称的是后者。

**Fix:** 二选一。
1. 降低承诺：把 docstring 的「机械防线」改成「约定 + review 红线」，避免下一个人以为有硬约束。
2. 真正机械化：加一条包外调用面的守护用例，扫全仓（排除 `services/code_graph/` 与其测试目录）不得出现对内部子模块的 import：

```python
def test_no_upper_layer_imports_internal_submodules() -> None:
    """全仓只准从包根导入；直连 loader/cache/signature/access 即架构违规。"""
    import ast
    from pathlib import Path

    server_root = Path(__file__).resolve().parents[3]
    package_dir = server_root / "services" / "code_graph"
    tests_dir = Path(__file__).resolve().parent
    forbidden = {"loader", "cache", "signature", "access", "model"}
    violations: list[str] = []

    for path in server_root.rglob("*.py"):
        if package_dir in path.parents or tests_dir in path.parents:
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            module = None
            if isinstance(node, ast.ImportFrom) and node.module:
                module = node.module
            elif isinstance(node, ast.Import):
                module = next(
                    (a.name for a in node.names
                     if a.name.startswith("services.code_graph.")),
                    None,
                )
            if module and module.startswith("services.code_graph."):
                if module.split(".")[2] in forbidden:
                    violations.append(f"{path.relative_to(server_root)}:{node.lineno} {module}")

    assert not violations, "上层直连 code_graph 内部子模块：\n" + "\n".join(violations)
```

推荐做 2 —— 这条红线在 Phase 122–127 才真正开始承压，现在建防线成本最低。

### ME-02: 缓存命中返回的是共享的可变 `MultiDiGraph`

> **✅ 已修（`88da3775`）**：两步都做了。① `CodeGraph` docstring 补上「`graph` 是共享对象、绝不就地修改、要改先 `copy()`」的纪律；② 入缓存前 `nx.freeze(graph.graph)` 作为硬约束。⚠️ 对**每一张**出图都冻结（不只入缓存的那些）——让「从 `GraphService` 拿到的图一律只读」成为无例外的契约，比让调用方去分辨手上这张能不能改要可靠。`loader.load_graph` 直调仍返回可变图（`test_loader.py:74` 因此不受影响）。回归：`test_returned_graph_is_frozen_against_in_place_mutation`（三种就地修改都抛 + 只读遍历与 `reverse(copy=False)` 不受影响 + `copy()` 副本可写且不回污）。

**File:** `server/services/code_graph/cache.py:666`；契约见 `server/services/code_graph/model.py:302-330`

`CodeGraph` 是 frozen、`chunk_evidence` 收成了 tuple（model.py 里为此写了明确理由「免得上层拿到后就地 append 污染缓存里的同一张图」），但 `graph` 本身是一个完全可变的 `nx.MultiDiGraph`，命中时按引用返回同一个对象（`test_cache_hit_no_rebuild` 断言 `second is first`）。任何上层工具一次 `add_edge` / `remove_node` / `nx.set_node_attributes` 就会永久污染本 worker 里所有后续命中——而且不会有任何信号。这不是假想：`test_loader.py:74` 自己就对返回的图做了 `graph.add_edge(...)`。

`chunk_evidence` 特意做了不可变而 `graph` 没做，说明这个风险被想到了一半。

**Fix:** 至少把纪律写进契约并让它可被引用；理想做法是命中时返回只读视图。

```python
# model.py —— CodeGraph docstring 补一条
# 🚨 :attr:`graph` 是**共享对象**：缓存命中时所有调用方拿到同一个 MultiDiGraph 实例。
#    ⛔ 绝不就地修改（add_edge / remove_node / set_node_attributes）——那会永久污染
#    本 worker 里所有后续命中。需要改写请先 ``graph.copy()``；只读遍历/反向视图
#    （``g.reverse(copy=False)``）不受影响。
```

若要机械化，可在 `_build_graph` 入缓存前对 `graph` 调 `nx.freeze(graph)`（networkx 自带，冻结后任何修改抛 `nx.NetworkXError`，只读遍历不受影响，零内存代价）。这是本条最省事的硬约束。

### ME-03: 两处观测 emit 未按本模块自己声明的 best-effort 处理

> **✅ 已修（`87bb7b4f`）**：抽成 `_log_cache_hit` / `_log_cache_evicted`，与同模块其余埋点同形（事件名常量仍写在 `logger.*` 的第一个位置实参上，`test_observability_contract` 的静态解析照常通过）。顺带把 `branch` 统一成 `branch or "-"`，与包内其余事件对齐。

**File:** `server/services/code_graph/cache.py:426-435`（`_get_entry`）、`cache.py:464-475`（`_evict_until_within_budget`）

本包其余每一个 emit 点都包了 `try/except: pass` 并注明「观测失败绝不反噬业务」，`.cursor/rules/observability-logging.mdc` 也把这条列为必守原则。唯独这两处是裸调用：

- `_get_entry` 的 `logger.debug(_EVENT_CACHE_HIT, ...)` 位于**缓存命中热路径**上——emit 抛异常会把一次本该零成本的命中变成一次请求失败。
- `_evict_until_within_budget` 的 `logger.info(...)` 在 `_lock` 持锁区间内（经 `_put` 进入），抛出会让 `_build_graph` 整体失败。

本仓的 structlog 链路带 SystemLogEntry 队列化落库处理器，emit 并非纯内存操作，抛出不是纯理论。

**Fix:** 抽成与同模块其余埋点同形的私有函数（注意保持事件名常量写在第一个位置实参上，否则 `test_observability_contract` 的静态解析会失败）：

```python
def _log_cache_hit(
    *, repository_id: str, branch: str, estimated_bytes: int,
    total_bytes: int, cache_size: int,
) -> None:
    try:
        logger.debug(
            _EVENT_CACHE_HIT,
            component="code_graph",
            category="sampling",
            repository_id=repository_id,
            branch=branch or "-",
            estimated_bytes=estimated_bytes,
            total_bytes=total_bytes,
            cache_size=cache_size,
        )
    except Exception:  # noqa: BLE001 — 观测失败绝不反噬业务
        pass
```

`_evict_until_within_budget` 同理抽 `_log_cache_evicted`。

### ME-04: 子图 frontier 截断没有进 `GraphMeta`，只进了日志

> **✅ 已修（`87bb7b4f`）**：按建议复用 `degraded` 承载第二档 `"on_demand_subgraph_truncated"`，未动字段数。`model.py` 的 `degraded` 注释已登记三个字面量及其语义差别。回归：`test_on_demand_subgraph_frontier_truncation` 增断言。

**File:** `server/services/code_graph/loader.py:959-967`（产生）、`loader.py:1059-1087`（未透出）

`_expand_seed_ids` 的注释写得很清楚：「截断是**有损**的：子图会缺一部分邻接。如实置标记，由上层与日志透出。」但返回的 `frontier_truncated` 只喂给了 `_log_degraded_subgraph`，`GraphMeta` 上没有对应字段——上层工具拿到的仅仅是 `degraded == "on_demand_subgraph"`，它无法区分「完整的深度受限子图」与「撞了 5000 上限、缺了一大块邻接的子图」。

这正好踩中 `GraphMeta` docstring 立的规矩（`model.py:250-258`：标记字段刻意必填，「漏透出会在 review 阶段暴露，而不是变成一次静默的错误结论」）。日志不是给 agent 看的。

**Fix:** 复用已有的 `degraded` 字段承载第二档语义，避免动 15 字段契约：

```python
# loader.py:1070
degraded=(
    "on_demand_subgraph_truncated" if frontier_truncated else "on_demand_subgraph"
),
```

并在 `model.py` 的 `degraded` 注释里登记这个新字面量。若倾向显式布尔，则加 `subgraph_frontier_truncated: bool` 字段，同步更新 `test_graph_meta_carries_all_declared_markers` 的 15 → 16。

### ME-05: `_expand_seed_ids` 穿过被排除的符号扩张，子图与全图的可达语义不一致

> **✅ 已修（`3545f54e`）**：按建议把 `is_excluded` 传进 `_expand_seed_ids`，每轮 frontier 先过 exclusion 再进入下一跳；过滤放在**截断之前**，免得上限名额被注定丢弃的节点占掉。种子本身不在这道过滤内（调用方点名要的符号照常进 `visited`，命中 exclusion 时由 `_load_symbol_nodes` 丢弃，与全量路径同口径），已写进 docstring。代价是每跳多一条按主键的 `Symbol` 查询，`test_on_demand_subgraph_query_count_does_not_scale_with_repo` 的上界相应从 `depth+1+4` 放宽到 `2*(depth+1)+4` —— 该用例真正的判别式是「加 200 个无关符号后查询数不变」那句，未受影响。回归：`test_subgraph_does_not_expand_through_excluded_symbols`（`seed → secret/keys.py → downstream`，断言 `downstream` 不在子图里，并与全量路径逐字对齐）。

**File:** `server/services/code_graph/loader.py:935-965`，调用点 `loader.py:1019-1025`

frontier 扩张纯在 `CallEdge` 上做，**完全不看 exclusion**；过滤发生在之后的 `_load_symbol_nodes`。于是 `seed → (被排除的 secret 符号) → X` 这条路径会把 `X` 拉进 `visited`，`X` 最终作为一个孤立节点出现在子图里——而在全量图里 `X` 在该深度**根本不可达**（被排除节点连同邻接边一并消失）。

两个后果：同一个问题在全量路径与降级路径上会给出不同答案；以及一个弱推断通道（`X` 的出现暗示 seed 与 `X` 之间存在一条经由被排除文件的路径）。前者是主要问题。

`test_on_demand_subgraph_applies_exclusion` 恰好覆盖不到：那个用例里被排除的 `secret/keys.py` 是链条末端，没有下游邻居。

**Fix:** 每轮扩张后按 exclusion 过滤 frontier 再进入下一跳。需要把 `is_excluded` 闭包传进 `_expand_seed_ids`，并额外取一次 `(id, file_path)`：

```python
def _expand_seed_ids(*, repository_id, branch, seed_symbol_ids, radius, is_excluded):
    ...
        # 下一轮 frontier 先过 exclusion：被排除的节点不得作为**中继**继续扩张，
        # 否则子图会包含全量图里根本不可达的节点。
        allowed = {
            str(sid)
            for sid, fp in Symbol.objects.filter(
                repository_id=repository_id, id__in=next_frontier
            ).values_list("id", "file_path")
            if not is_excluded(fp)
        }
        next_frontier &= allowed
```

（`is_excluded` 已是按 `file_path` 记忆化的闭包，这一步对热路径几乎零成本。）配套用例：`seed → secret/keys.py → downstream.py`，断言 `downstream` **不在**子图节点集里。

### ME-06: `by_file_and_name` 在 `(file_path, name)` 撞车时静默覆盖

> **✅ 已修（`0f736fb9`）**：按建议用 `_AMBIGUOUS` 哨兵标歧义，`_resolve_by_file_and_name` 见到即返回 `None`。裸名解析改走同一个助手（此前直接 `.get()`，会绕过哨兵）。歧义计数进 `code_graph_assembled` 的排障 kv，不进 `GraphMeta` 契约。回归：`test_same_file_same_name_symbols_are_ambiguous_not_silently_overwritten` 同时覆盖两个消费者（裸名边 + 跨仓边）。

**File:** `server/services/code_graph/loader.py:403`

```python
by_file_and_name[(norm_path, name)] = node_id
```

同一文件里同名符号并不罕见：Go 里不同 receiver 上的同名方法（`func (a *A) Get()` / `func (b *B) Get()`）、Python 的 `@overload` / 条件定义、TS 的重载签名。撞车时后写入者**静默覆盖**先写入者，索引里只留最后一个。

这张索引有两个消费者，都会因此指错符号：裸名边解析（`loader.py:646-650`）与跨仓边二次解析（`loader.py:766-771`）。得到的是一条**指向错误符号**的边——比丢弃这条边更糟，因为它看起来是成功解析。

**Fix:** 撞车时按「宁可不连也不连错」处理（与裸名三道过滤的既定倾向一致），用哨兵值标记歧义：

```python
    key = (norm_path, name)
    if key in by_file_and_name:
        # 同文件同名（Go 不同 receiver 的同名方法 / Python @overload / TS 重载）：
        # 无从判断指向哪一个，标成歧义并让解析方一律放弃——指错符号比丢边更糟。
        by_file_and_name[key] = _AMBIGUOUS
        ambiguous_name_count += 1
    else:
        by_file_and_name[key] = node_id
```

`_resolve_by_file_and_name` 里 `return None if node is _AMBIGUOUS else node`。歧义计数进 `_log_assembled` 的排障 kv（不必进 `GraphMeta` 契约）。

### ME-07: `seed_symbol_ids` 未做 UUID 校验，非法值会以未捕获异常冒出

> **✅ 已修（`18331db0`）**：`_validated_seed_ids` 在 async 外壳里、`ensure_repository_readable` **之后**校验，非法即 `GraphError`。⚠️ 异常消息**不回显原值**（种子来自不可信入参，原样写进消息就是一条反射面），只带 `repository_id`。`depth` 钳位见 LO-08。回归：`test_seed_symbol_ids_must_be_valid_uuids` 覆盖 5 种非法形态并先钉死「合法种子照常放行」。

**File:** `server/services/code_graph/cache.py:552`（入参）、`loader.py:931`、`loader.py:940-944`、`loader.py:340`

`repository_id` 在 `access.py:153` 走了 `uuid.UUID()` 解析并注明 ASVS V5，非法即 `GraphAccessDenied`。`seed_symbol_ids` 没有对应处理：字符串原样进 `visited`，再进 `CallEdge.objects.filter(Q(caller_symbol_id__in=frontier) | ...)` 与 `Symbol.objects.filter(id__in=restrict_symbol_ids)`。非 UUID 值会让 Django 在 UUIDField 上抛 `ValidationError`（Postgres 上还可能是 `DataError`）——既不是 `GraphError` 子类，上层 `except GraphError` 兜不住，最终表现为 500。

`seed_symbol_ids` 在 Phase 122 会来自 MCP 工具入参，属于不可信输入；同一个模块对两个入参用两套标准是不一致的。

**Fix:** 在 `get_graph` 的 async 外壳里与 `ensure_repository_readable` 同处校验：

```python
        if seed_symbol_ids:
            try:
                seeds = tuple(str(uuid.UUID(str(s))) for s in seed_symbol_ids)
            except (ValueError, TypeError, AttributeError):
                raise GraphError(
                    "seed_symbol_ids 含非法 UUID",
                    {"repository_id": str(repository_id)},
                ) from None
        else:
            seeds = ()
```

（`depth` 同样值得夹一下：`depth < 0` 目前会静默退化成「只有种子」，`depth` 极大值则靠图直径收敛——`max(0, min(depth, 10))` 之类的钳位即可，见 LO-08。）

### ME-08: single-flight 等待者会占住 `thread_sensitive` 执行器线程最长 120 秒

> **✅ 已修（`88da3775`）**：两步都做了。① 等待者那一侧的线程占用写进 `get_graph` 的 `.. note::` 与 `_wait_for_inflight` 的 docstring，点名了「非请求路径落在进程唯一一条 `single_thread_executor` 上」这条真正的代价；② 默认值 120 → **30** 秒，settings 注释里写清了「这个值是等待者占住执行器线程的上界，不只是一个超时」。

**File:** `server/services/code_graph/cache.py:745-765`；配置 `friday/settings.py` `CODE_GRAPH_BUILD_WAIT_TIMEOUT_SECONDS=120`

`get_graph` 的 docstring 很坦率地记了 `thread_sensitive=True` 下「一次 2–4 秒的大图装配会阻塞该执行器上排在后面的其他 ORM 工作」，但没有记等待者那一侧：`inflight.event.wait(timeout)` 是纯阻塞，同样跑在 `sync_to_async` 派发的执行器线程上，上界是 **120 秒**（领头被硬杀、`finally` 没跑到时就是这个上界）。

Django 的 ASGI handler 为每个请求开 `ThreadSensitiveContext`，所以请求侧的影响限于该请求自身；但**不经过请求的调用方**（channels consumer、`background_runner`、durable worker）落在全局 `SyncToAsync.single_thread_executor` 上——那是**进程唯一一条**线程，一个等待者卡在那里，本进程所有其他非请求 `sync_to_async` 工作全部排队。

不是死锁（领头永远在 `finally` 里 `set`），但是一次可观的头阻塞，而且当前文档里看不出来。

**Fix:** 两步。① 把这一段写进 `get_graph` 的那条 `.. note::`，让下一个人在调 `CODE_GRAPH_BUILD_WAIT_TIMEOUT_SECONDS` 时知道自己在调什么；② 把默认值从 120 秒降到「够覆盖最坏冷建 + 余量」的量级——settings 注释自己写的是 20 万符号约 4 秒，**30 秒**已有 7 倍余量，而 120 秒的额外收益只在「领头被硬杀」这种本就该快速失败的场景里。

### ME-09: perf 诊断用例会连**生产 PostgreSQL**，并绕过 `--disable-socket`

> **✅ 已修（`106f568f`）**：按建议加 `FRIDAY_PERF_ALLOW_PRODUCTION_DB=1` 显式授权（安全默认值是**不连**，回落到只读 sqlite 快照 / 合成图）。三处复跑说明（文件 docstring、`cache.py` 与 `model.py` 的标定注释）同步带上该变量。⚠️ 守护用例 `test_production_db_requires_explicit_opt_in` **刻意不带** `perf` 标记——它守的正是「perf 用例什么时候会去连生产」这道闸，必须在常规采样里跑到；它自己不连任何库。

**File:** `server/tests/services/code_graph/test_perf_diagnostics.py:445-464`、`test_perf_diagnostics.py:406-424`

`_resolve_source()` 在 `DATABASE_URL` 存在时直接返回 `{"kind": "pg"}`，`_run_child` 用 `subprocess.run([sys.executable, "-c", _DIAGNOSTIC_SCRIPT, ...])` 起子进程，`DATABASE_URL` 由环境继承。于是：

- 本仓 `addopts` 里的 `--disable-socket`（pytest-socket）**只 patch 父进程**的 socket，子进程完全不受约束——网络隔离在这里有一个洞。
- 任何本地 `.env` 指向生产库的开发者跑 `uv run pytest -m perf` 就会真的去查生产库（`server/friday/settings.py` 的 `env.read_env` 已经把它读进 `os.environ` 了）。SUMMARY 里也确认这次标定就是这么跑的。

读是只读、`-m perf` 默认被 `addopts` 排除、且未打印连接串（`_has_production_dsn` 特意只返回 bool），所以不是 BLOCKER。但「跑测试会打生产库」这件事必须是显式选择，不能是环境的副作用。

**Fix:** 加一道显式开关，让连生产成为主动动作而非默认回落：

```python
def _has_production_dsn() -> bool:
    """``DATABASE_URL`` 可用**且**调用方显式授权连生产。

    ⛔ 不能只看 DATABASE_URL：本地 .env 常指向生产库，那会让一次 ``pytest -m perf``
    在开发者毫不知情的情况下去查生产。子进程还绕过了 ``--disable-socket``。
    """
    if os.environ.get("FRIDAY_PERF_ALLOW_PRODUCTION_DB") != "1":
        return False
    return bool(os.environ.get("DATABASE_URL"))
```

并把这个变量写进文件顶部 docstring 的复跑说明里（现在写的是 `uv run pytest -m perf tests/services/code_graph/ -s`，应改成带该变量的形式）。

### ME-10: 降级路径仍对两个数据源做全仓扫描

> **📝 登记在案，未修（`e6b89d76`）**：取了建议里的退路。修法已探明并连同「为什么现在不做」一起写进 `load_subgraph` 的 docstring，包括那句要紧的提醒——`test_on_demand_subgraph_query_count_does_not_scale_with_repo` 数的是**查询条数**而非扫描行数，⛔ 别把它的绿色读成「处处收敛」。不做的理由：产出本就有界，痛的只是迭代量，而生产最大仓才 3 万符号、根本走不到降级路径；没有实测依据就动取数形状属于无依据优化。

**File:** `server/services/code_graph/loader.py:1045-1054`

`load_subgraph` 存在的理由是「超预算大仓不能全量装配」（`loader.py:980-986`）。但它的四个数据源里只有两个真正收敛了：

- `_load_symbol_nodes(restrict_symbol_ids=reachable_ids)` ✅
- `_load_call_edges(restrict_caller_ids=reachable_ids)` ✅
- `_load_cross_repo_edges(repository_id=...)` ❌ 扫该仓**全部** `CrossRepoApiCall`（还带两个 JOIN）
- `_load_chunk_evidence(repository_id=..., branch=...)` ❌ 扫该仓**全部** `ChunkEdge`

产出确实是有界的（跨仓边靠 `by_file_and_name` 过滤，chunk 证据靠 `chunk_to_symbols` 过滤，`iterator()` 也保证了内存），但**迭代量**随仓库规模线性增长——而这条路径的调用前提就是「这个仓大到全量装不下」。`test_on_demand_subgraph_query_count_does_not_scale_with_repo` 只数**查询条数**不随规模变化，数不出这两条查询各自扫了多少行，所以这个洞在用例里是隐形的。

**Fix:** 两处都用已有的索引反向收敛。chunk 证据侧最直接：

```python
    # 只取子图内符号真正挂着的那些 chunk（子图路径下 chunk_to_symbols 已经很小）。
    known_chunks = set(nodes.chunk_to_symbols)
    if not known_chunks:
        return {}, 0
    qs = ChunkEdge.objects.filter(
        repository_id=repository_id, branch_name__in=_branch_filter(branch)
    ).filter(Q(source_chunk_id__in=known_chunks) | Q(target_chunk_id__in=known_chunks))
```

跨仓边侧可加 `call_site__caller_file__in` / `endpoint__file_path__in`（取自 `nodes` 里已装载符号的去重文件集）。若认为工程量不划算，至少把这条已知局限写进 `load_subgraph` 的 docstring，别让下一个人以为降级路径处处收敛。

---

## LOW

### LO-01: `over_budget or seed_symbol_ids` 的前半段不可达

> **✅ 已修（`18331db0`）**：改成 `if seed_symbol_ids:`，并按建议在注释里澄清「本相位交付的是『超预算 ⇒ 显式抛错并要求调用方给种子』，不是自动降级」。

**File:** `server/services/code_graph/cache.py:819-832`

`over_budget and not seed_symbol_ids` 已在上一句抛出，所以走到 `if over_budget or seed_symbol_ids:` 时 `over_budget` 为真必然蕴含 `seed_symbol_ids` 非空——整个条件等价于 `if seed_symbol_ids:`。冗余谓词会让读者以为存在「超预算但无种子」的降级分支，而那条路已经在上面 `raise` 掉了。

**Fix:** 改成 `if seed_symbol_ids:` 并补一行注释说明「超预算无种子已在上方抛错，这里只可能是种子路径」。顺带值得在 CONTEXT Area 2 的记录上澄清：本相位实际交付的是「超预算 ⇒ 显式抛错并要求调用方给种子」，而不是「自动降级」。

### LO-02: 没有校验 `max_graph_bytes <= max_bytes`

> **⏭️ 未做**：`max_graph_bytes > max_bytes` 直接抛会打红 `test_evict_loop_drops_multiple_entries` —— 那条用例**刻意**构造 `max_bytes < max_graph_bytes` 来验证「一个大条目连逐两个」。要修得连同该用例的构造一起改，超出本轮「低风险自包含」的口径。

**File:** `server/services/code_graph/cache.py:398-404`

两个预算各自校验 `> 0`，但没有相对关系约束。若运维把 `CODE_GRAPH_MAX_GRAPH_BYTES` 配得大于 `CODE_GRAPH_CACHE_MAX_BYTES`，准入会放行一张单独就超总预算的图；`_put` 之后 `_evict_until_within_budget` 会把缓存逐空**并把刚写进去的那条也逐掉**（记账依然正确，不泄漏），结果是缓存命中率恒为 0 且每次写入都刷一串 `code_graph_cache_evicted`——`test_graph_service_rejects_non_positive_budgets` 的 docstring 恰好描述了这种「表面在工作、实际失效」的形态。

**Fix:** `__init__` 里加一句 `if max_graph_bytes > max_bytes: raise ValueError(...)`，或退一步在 `get_graph_service()` 里 `logger.warning` 一次。

### LO-03: `_MATCHER_FP_CACHE` 无上界，过期条目从不清理

> **⏭️ 未做**：LOW，且 218 仓量级下无实际影响。登记为已知上界。

**File:** `server/services/code_graph/access.py:79`、`access.py:229-232`

过期判定是 `cached[0] > time.monotonic()`，过期条目只在同一个 key 被再次请求时才被覆盖。仓库数多且访问分散时，字典持有的 `ExclusionMatcher`（内含该仓全部编译好的 glob/regex）会只增不减。当前 218 个仓量级完全无碍，登记为已知上界即可。

**Fix:** 写入时顺手清理，成本 O(n) 但仅发生在未命中路径：

```python
    with _MATCHER_FP_LOCK:
        now = time.monotonic()
        # 顺手清过期项：过期条目只会在同 key 再次请求时被覆盖，否则永久驻留。
        for stale in [k for k, v in _MATCHER_FP_CACHE.items() if v[0] <= now]:
            _MATCHER_FP_CACHE.pop(stale, None)
        _MATCHER_FP_CACHE[key] = (now + _MATCHER_FP_TTL_SECONDS, matcher, fingerprint)
```

### LO-04: 读取 `ExclusionMatcher` 的私有属性 `_repository_id`

> **⏭️ 未做**：LOW，`getattr` 默认值已兜住属性消失的情况。

**File:** `server/services/code_graph/access.py:328`

`repository_id = str(getattr(matcher, "_repository_id", "") or "")` 依赖 `services/exclusion.py` 的实现细节。`getattr` 默认值兜住了属性消失的情况，但届时审计事件的 `repository_id` 会静默变成空串——审计埋点丢了主键而不报错。

**Fix:** 让 `make_path_exclusion_memo` 显式收一个 `repository_id` 关键字参数（两个调用点 `loader.py:1017` / `loader.py:1132` 手上都有），彻底断开这层耦合。

### LO-05: 若干事件缺 `initiated_by_user_id`

> **⏭️ 未做**：LOW，`merge_contextvars` 已注入 `user_id`，请求链路上不缺归因。⚠️ 本轮新增的 `code_graph_subgraph_depth_clamped` 与这 8 条同口径（未带该字段），选择保持一致而不是制造第 9 种写法——要改应当一次性连同判据登记一起改。

**File:** `cache.py:426`(`cache_hit`)、`cache.py:464`(`cache_evicted`)、`cache.py:200`(`stale_watermark`)、`signature.py:86`(`signature_computed`)、`signature.py:100`(`edge_build_in_flight`)、`loader.py:142`(`exclusion_applied`)、`loader.py:170`(`assembled`)、`access.py:246`(`exclusion_matcher_failed`)

同包的 `access_denied` / `build_started` / `build_completed` / `build_failed` / `cache_invalidated` 都显式带了这个字段，上面 8 个没带。规则要求「每条日志都要能回答谁触发的」；`common/logging.py` 的 `merge_contextvars` 会注入 `user_id`，请求链路上实际不缺归因，所以只是不一致而非违规。

**Fix:** 要么给这 8 处补上（`cache.py` 的三处拿得到 `user_id`，`signature.py` / `loader.py` 需要多传一个参数），要么在 `test_observability_contract` 里把这条判据显式登记为「由 contextvars 兜底、不逐点要求」，免得下一个人来回改。

### LO-06: `load_subgraph` 丢弃 chunk 证据截断计数

> **✅ 已修（`87bb7b4f`）**：`_log_degraded_subgraph` 增加 `chunk_evidence_truncated_count` 参数并传入，与全量路径的 `code_graph_assembled` 对齐。

**File:** `server/services/code_graph/loader.py:1050`

`chunk_evidence, _chunk_truncated = _load_chunk_evidence(...)`。全量路径把它喂给了 `_log_assembled`，子图路径直接丢弃，`_log_degraded_subgraph` 里也没有对应 kv。同一个排障信号在两条路径上不对等。

**Fix:** 给 `_log_degraded_subgraph` 加 `chunk_evidence_truncated_count` 参数并传入。

### LO-07: perf survey 的多数断言恒真

> **⏭️ 未做**：LOW，且是诊断交付物而非回归用例（`-m perf` 默认排除）。

**File:** `server/tests/services/code_graph/test_perf_diagnostics.py:798-803`

```python
        assert item["resolved"] + item["bare"] > 0
        assert 0.0 <= item["rate"] <= 1.0
        assert item["rate"] == pytest.approx(...)   # 用同一个公式重算自己
    assert p10 <= p50 <= p90                        # 排序后的百分位必然如此
```

`0 <= rate <= 1` 对一个比值恒真；`p10 <= p50 <= p90` 对排序数组恒真；中间那条用同一个 `_resolution_rate` 重算等于自证。同文件里 `test_largest_repo_memory_calibration` 的 `estimate >= 0.9 * traced`（`:620`）与 `test_callee_symbol_resolution_rate_survey` 开头那条 `meta.resolution_rate == _resolution_rate(3, 7)`（`:710`，用合成数据核对 loader 与 survey 同口径）**是**有效断言。

这些是诊断交付物而非回归用例，`-m perf` 默认排除，因此只是 LOW。

**Fix:** 把恒真的三条换成真正会红的：例如断言 survey 与 `loader.load_graph` 在**同一个仓**上算出的 `resolution_rate` 一致（跨实现交叉校验），以及断言 `LOW_RESOLUTION_THRESHOLD` 的命中率落在 `[0.05, 0.5]` 区间内（阈值一旦漂到长鸣或永不触发就红，正是这条常量的校准目的）。

### LO-08: `depth` 未做钳位；`_estimate_admission` 的两个返回值被丢弃

> **✅ 部分已修（`18331db0`）**：`depth` 钳到 `[0, _MAX_SUBGRAPH_DEPTH=10]`，越界发一次 DEBUG（`code_graph_subgraph_depth_clamped`）。回归：`test_depth_is_clamped_instead_of_silently_degrading`（`depth=-1` 此前会让 `range(depth+1)` 成空循环、子图静默退化成只有种子）。⏭️ `_estimate_admission` 丢弃前两个返回值那半条**未做**：改签名或加埋点字段都会牵动现有的准入接缝用例。

**File:** `server/services/code_graph/cache.py:553`、`cache.py:816`、`cache.py:904`

`depth` 为负时 `range(depth + 1)` 是空循环，子图静默退化成「只有种子」，调用方拿不到任何提示；极大值靠图直径收敛，不会失控但会白跑多轮查询。另外 `_, _, admission_bytes = self._estimate_admission(...)` 丢掉了前两个值，而方法签名与 docstring 都在承诺三元组——目前没有第二个消费者。

**Fix:** `depth` 在 `get_graph` 里钳到 `max(0, min(depth, _MAX_SUBGRAPH_DEPTH))` 并对越界发一次 debug；`_estimate_admission` 要么把 node/edge 计数喂进 `code_graph_build_started`（准入估算值本身就是有用的排障信息），要么收窄成只返回字节数。

---

## 已核验为**不成立**的怀疑项（供后续 review 免于重查）

- **字节记账漂移**：`GraphMeta.estimated_bytes` 与 `_Entry.estimated_bytes` 同源于 `cache.py:862` 的单个局部变量，准入与记账共用 `estimate_graph_bytes`，不存在两份常数。
- **逐出欠账/泄账**：`_put`（先减旧再加新）、`_evict_until_within_budget`、`invalidate`、`_get_graph_sync` 步骤 ⑦ 四条扣账路径全部持锁且配对，`test_put_overwrite_does_not_double_count` 覆盖了最易漏的那条。
- **失败毒化缓存**：`_build_single_flight` 的 `finally` 无条件弹占位、异常路径不触及 `_cache`，`test_build_failure_not_cached` 有完整回归（含「换成成功实现立刻能建出来」）。
- **持锁 await / 跨 loop 原语**：`test_lock_discipline_documented_and_no_await` 的 AST 断言（唯一 `async def`、全部 `Await` 落在外壳内、`sync_to_async(` 恰一次、未 import `asyncio`）确实比 grep 强，且 grep 在这里会命中禁令散文自身——这条替换是加强不是削弱。
- **exclusion 在输出阶段过滤**：确认在装配阶段（`loader.py:380` 节点不进集 + `loader.py:622/629` 端点缺失即整边丢弃），`excluded_file_count` 数的是去重文件数。
- **`_get_graph_sync` 绕过权限**：`ensure_repository_readable` 在 async 外壳里无条件执行，`test_cache_hit_no_rebuild` 用 `acl_spy.call_count == 2` 锁死。
- **D-07 组件登记**：`code_graph` 已写进 `LOGGING-SPEC §5:148`，并附了与既有 `codegraph` 并存的理由。

---

_Reviewed: 2026-08-09T19:24:00Z_
_Reviewer: gsd-code-reviewer_
_Depth: deep_
