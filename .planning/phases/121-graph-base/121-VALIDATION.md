---
phase: 121
slug: graph-base
status: planned
nyquist_compliant: true
wave_0_complete: false
created: 2026-08-09
mapped: 2026-08-09
---

# Phase 121 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.
> Source: `121-RESEARCH.md` §Validation Architecture（已核实本仓 pytest 配置与既有并发测试范式）。

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | `pytest>=9.0.2` + `pytest-django>=4.8` + `pytest-asyncio`（`asyncio_mode = "auto"`） |
| **Config file** | `server/pyproject.toml` `[tool.pytest.ini_options]` |
| **Quick run command** | `cd server && uv run pytest tests/services/code_graph -x -q` |
| **Full suite command** | `cd server && uv run pytest` |
| **Estimated runtime** | quick ~10s（新包用例全内存）；full suite 数分钟 |

**会影响用例写法的既有约束：**

- `addopts` 含 `--disable-socket --allow-unix-socket` — 网络默认禁用（本相位无外呼，无影响）。
- `addopts` 含 `-m 'not perf and not integration and not slow and not postgres_queue'` — `perf` 标记默认跳过，正好承载「最大仓内存实测 + 解析率统计」这两个一次性诊断交付物。
- `asyncio_mode = "auto"` — `async def test_*` 无需 marker。
- 测试库是 **SQLite 文件库**（`tests/conftest.py::django_db_modify_db_settings`）。**多线程并发写 DB 的测试仍然危险** —— single-flight 用例必须用内存假 builder，全程不碰 DB。

---

## Sampling Rate

- **After every task commit:** `cd server && uv run pytest tests/services/code_graph -x -q`
- **After every plan wave:** `cd server && uv run pytest tests/services/code_graph tests/codegraph tests/code_relations -q`（含既有图相关套件，验证零回归）
- **Before `/gsd-verify-work`:** `cd server && uv run pytest` 全绿 + `uv run ruff check .` + `uv run mypy .`
- **Max feedback latency:** 15 秒（quick run）

---

## Per-Task Verification Map

> **填表责任在 gsd-planner** —— 计划生成后每个 task 必须在此表有一行。下表的 Requirement / Test Type / Automated Command 列已由调研预先确定，planner 补 Task ID / Plan / Wave / Threat Ref 三列。

| Task ID | Plan | Wave | Requirement | Threat Ref | Secure Behavior | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|------------|-----------------|-----------|-------------------|-------------|--------|
| 121-05-T1 | 121-05 | 3 | GRAPH-01 | T-121-覆盖丢边 | 四类数据装配成 `MultiDiGraph`，节点/边计数与档位正确 | unit | `uv run pytest tests/services/code_graph/test_loader.py -x` | ❌ W0 | ⬜ pending |
| 121-08-T1 | 121-08 | 6 | GRAPH-01 | T-121-串图 | 首次查询 build 一次、同键再查命中缓存（builder 调用计数 == 1） | unit | `uv run pytest tests/services/code_graph/test_cache.py -k hit -x` | ❌ W0 | ⬜ pending |
| 121-06-T1 | 121-06 | 4 | GRAPH-01 | T-121-虚假节点 | `CrossRepoApiCall` 按 file+name 解析到符号；解析不上丢弃并计数上报 | unit | `uv run pytest tests/services/code_graph/test_loader.py -k cross_repo -x` | ❌ W0 | ⬜ pending |
| 121-05-T1 | 121-05 | 3 | GRAPH-01 | — | feature 分支 overlay（base ∪ feature），同文件 feature 覆盖 base | unit | `uv run pytest tests/services/code_graph/test_loader.py -k overlay -x` | ❌ W0 | ⬜ pending |
| 121-04-T1 | 121-04 | 2 | GRAPH-02 | T-121-半新图 | 签名对 `last_indexed_commit_sha` 变化敏感 | unit | `uv run pytest tests/services/code_graph/test_signature.py -k watermark -x` | ❌ W0 | ⬜ pending |
| 121-04-T2 | 121-04 | 2 | GRAPH-02 | T-121-半新图 | 签名对**两条**边构建轨各自变化都敏感（D-06-2） | unit | `uv run pytest tests/services/code_graph/test_signature.py -k generation -x` | ❌ W0 | ⬜ pending |
| 121-04-T1 | 121-04 | 2 | GRAPH-02 | — | 无变更时签名稳定（连算两次相等） | unit | `uv run pytest tests/services/code_graph/test_signature.py -k stable -x` | ❌ W0 | ⬜ pending |
| 121-08-T2 | 121-08 | 6 | GRAPH-02 | T-121-半新图 | 水位推进 + 边构建 RUNNING ⇒ 拒用缓存 + `partial_edges=True` | unit | `uv run pytest tests/services/code_graph/test_cache.py -k partial -x` | ❌ W0 | ⬜ pending |
| 121-04-T3 | 121-04 | 2 | GRAPH-02 | T-121-长鸣 | **`graph_build_status=PENDING` 但已终态 ⇒ 不判在途**（D-06-3 回归） | unit | `uv run pytest tests/services/code_graph/test_cache.py -k pending_not_inflight -x` | ❌ W0 | ⬜ pending |
| 121-04-T3 | 121-04 | 2 | GRAPH-02 | T-121-孤儿 | 超时的 `RUNNING` 孤儿行 ⇒ 不判在途 | unit | `uv run pytest tests/services/code_graph/test_cache.py -k orphan -x` | ❌ W0 | ⬜ pending |
| 121-07-T1 | 121-07 | 5 | GRAPH-03 | T-121-OOM | 字节估算为纯函数，给定 n/e 返回确定值 | unit | `uv run pytest tests/services/code_graph/test_cache.py -k estimate -x` | ❌ W0 | ⬜ pending |
| 121-07-T2 | 121-07 | 5 | GRAPH-03 | T-121-OOM | 超预算时按 LRU 顺序逐出至 ≤ 预算，发 `code_graph_cache_evicted` | unit | `uv run pytest tests/services/code_graph/test_cache.py -k evict -x` | ❌ W0 | ⬜ pending |
| 121-08-T3 | 121-08 | 6 | GRAPH-03 | T-121-风暴 | N 个并发请求同一 key ⇒ builder 只被调用一次（内存假 builder，不碰 DB） | unit | `uv run pytest tests/services/code_graph/test_cache.py -k single_flight -x` | ❌ W0 | ⬜ pending |
| 121-08-T3 | 121-08 | 6 | GRAPH-03 | T-121-毒化 | 构建失败 ⇒ 所有等待者各自抛，且失败不进缓存（不毒化） | unit | `uv run pytest tests/services/code_graph/test_cache.py -k build_failure -x` | ❌ W0 | ⬜ pending |
| 121-08-T2 | 121-08 | 6 | GRAPH-03 | T-121-OOM | 单图估算 > `MAX_GRAPH_BYTES` ⇒ 不进缓存 + `degraded="on_demand_subgraph"` | unit | `uv run pytest tests/services/code_graph/test_cache.py -k degraded -x` | ❌ W0 | ⬜ pending |
| 121-05-T2 | 121-05 | 3 | GRAPH-04 | T-121-泄漏 | 命中 exclusion 的符号不在节点集，其邻接边一并消失 | unit | `uv run pytest tests/services/code_graph/test_access.py -k exclusion -x` | ❌ W0 | ⬜ pending |
| 121-03-T2 | 121-03 | 2 | GRAPH-04 | T-121-降级放行 | matcher 构造失败 ⇒ 抛 `GraphAccessDenied`，**不返回未过滤的图** | unit | `uv run pytest tests/services/code_graph/test_access.py -k fail_closed -x` | ❌ W0 | ⬜ pending |
| 121-03-T1 | 121-03 | 2 | GRAPH-04 | T-121-空图误读 | `index_status != INDEXED` ⇒ 显式抛错，**不返回空图** | unit | `uv run pytest tests/services/code_graph/test_access.py -k not_indexed -x` | ❌ W0 | ⬜ pending |
| 121-03-T1 | 121-03 | 2 | GRAPH-04 | T-121-软删 | `is_deleted=True` 的仓库 ⇒ 拒绝 | unit | `uv run pytest tests/services/code_graph/test_access.py -k deleted -x` | ❌ W0 | ⬜ pending |
| 121-04-T1 | 121-04 | 2 | GRAPH-04 | T-121-陈旧规则 | exclusion 规则变更 ⇒ 指纹变 ⇒ 签名变 ⇒ 旧图失效 | unit | `uv run pytest tests/services/code_graph/test_signature.py -k exclusion -x` | ❌ W0 | ⬜ pending |
| 121-10-T1 / 121-10-T2 | 121-10 | 8 | 诊断交付物 | T-121-OOM | 最大仓内存实测 + `callee_symbol` 解析率统计 | perf（默认跳过） | `uv run pytest -m perf tests/services/code_graph/` | ❌ W0 | ⬜ pending |

### 计划外补充的自动化验证（不在原 21 行内，由 planner 追加）

| Task ID | Plan | Wave | Requirement | Threat Ref | Secure Behavior | Automated Command |
|---------|------|------|-------------|------------|-----------------|-------------------|
| 121-01-T1 | 121-01 | 0 | 全部 | T-121-SC | networkx 直接依赖 + 三个 `CODE_GRAPH_*` settings + LOGGING-SPEC §5 登记 `code_graph`（D-06-7） | 见 121-01-PLAN.md Task 1 的 grep 链 |
| 121-02-T1 | 121-02 | 1 | GRAPH-01 | T-121-静默降级 | 四档置信度枚举与数值映射；`reason` 现推不存（D-06-8） | `uv run pytest tests/services/code_graph/test_model.py -x` |
| 121-03-T3 | 121-03 | 2 | 全部 | T-121-规范漏筛 | 观测契约守护：包内每个 structlog 调用带 `component="code_graph"` + `category="sampling"` + `code_graph_` 前缀 | `uv run pytest tests/services/code_graph/test_access.py -k observability -x` |
| 121-06-T2 | 121-06 | 4 | GRAPH-01 | T-121-笛卡尔爆炸 | `ChunkEdge` 走旁挂证据面，绝不进 `MultiDiGraph` 边集 | `uv run pytest tests/services/code_graph/test_loader.py -k chunk_evidence -x` |
| 121-06-T3 | 121-06 | 4 | GRAPH-03 | T-121-OOM | 按需子图 SQL 侧多跳收敛，查询次数不随仓库规模增长 | `uv run pytest tests/services/code_graph/test_loader.py -k subgraph -x` |
| 121-07-T3 | 121-07 | 5 | GRAPH-03 | T-121-用例污染 | 模块级单例 lazy 实例化 + `_reset_for_tests()` 用例间隔离 | `uv run pytest tests/services/code_graph/test_cache.py -x` |
| 121-09-T1 | 121-09 | 7 | GRAPH-04 | T-121-绕闸 | barrel 只导出 `GraphService` + 契约类型，loader/cache 不可从包顶层取得 | `uv run pytest tests/services/code_graph/test_access.py -k barrel -x` |
| 121-09-T2 | 121-09 | 7 | GRAPH-02 | T-121-陈旧图 | 两处构建完成钩子主动驱逐；异常吞掉不反噬主流程 | `uv run pytest tests/services/code_graph/test_cache.py -k invalidate -x` |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

---

## Wave 0 Requirements

> 全部由 **Plan 121-01（Wave 0）** 交付：Task 2 建测试包与 fixture，Task 3 建五个用例桩，Task 1 落依赖/配置/规范登记。

- [ ] `server/tests/services/code_graph/__init__.py`
- [ ] `server/tests/services/code_graph/conftest.py` — **必须自建**。`server/tests/codegraph/conftest.py` 跨目录不可见；且其 `graph_repo` 的 `index_status` 是 `NOT_INDEXED`，会被 `ensure_repository_readable` 直接拒掉。至少需要：`indexed_repo`（`index_status=INDEXED`）、`branch_index`、`symbols_factory`、`call_edges_factory`、`exclusion_rule_factory`
- [ ] `server/tests/services/code_graph/test_model.py` / `test_loader.py` / `test_signature.py` / `test_cache.py` / `test_access.py` — 用例桩
- [ ] `GraphService` 的**测试重置钩子** —— 模块级单例必须能在用例间清空，否则用例互相污染。先例：`server/services/background_runner.py::_reset_for_tests()`、`server/services/exclusion.py::invalidate_matcher_cache()`。在本目录 conftest 里配 `@pytest.fixture(autouse=True)` 自动重置
- [ ] 框架安装：**无需** —— pytest 全套已在依赖树

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| 生产多 worker 下的实际常驻内存 | GRAPH-03 | 需真实部署与真实大仓，单测环境无法复现 | 部署后观察 worker RSS 与 `code_graph_cache_evicted` 事件频率，据此复核 `CODE_GRAPH_CACHE_MAX_BYTES` 默认值 |

> 除上表一项外，本相位所有行为均有自动化验证。该项属于「默认值调优」而非「功能是否正确」，不阻塞相位完成。

---

## Validation Sign-Off

- [x] All tasks have `<automated>` verify or Wave 0 dependencies — 10 个 plan / 28 个 task 全部带 `<automated>`；Wave 0（Plan 121-01）先建用例桩，使每个 `-k` 选择器从第一个 task 起就能解析
- [x] Sampling continuity: no 3 consecutive tasks without automated verify — 每个 task 均有自动化验证，无连续缺口
- [x] Wave 0 covers all MISSING references — `__init__.py` / `conftest.py` / 五个 `test_*.py` / 单例重置钩子（钩子本体由 121-07-T3 交付并回填 conftest）
- [x] No watch-mode flags — 全部命令为一次性 `pytest ... -x -q`
- [x] Feedback latency < 15s — quick run `uv run pytest tests/services/code_graph -x -q` 为全内存用例（perf 诊断默认跳过）
- [x] `nyquist_compliant: true` set in frontmatter

**Approval:** planner 已填表（2026-08-09）；待 `/gsd-execute-phase 121` 执行时逐行更新 Status。
