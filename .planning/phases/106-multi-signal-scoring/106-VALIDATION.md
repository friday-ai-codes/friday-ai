---
phase: 106
slug: multi-signal-scoring
status: planned
nyquist_compliant: true
wave_0_complete: false
created: 2026-07-29
---

# Phase 106 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest 9.x（server/，uv 管理）+ vitest 4（web/，前端标签映射与设置区） |
| **Config file** | server/pyproject.toml |
| **Quick run command** | `cd server && uv run pytest tests/codegraph -q` |
| **Full suite command** | `cd server && uv run pytest -q` |
| **Estimated runtime** | 快跑 ~30s；全量 ~10min |

---

## Sampling Rate

- **After every task commit:** 受改模块定向跑（codegraph / system / repositories / web vitest）
- **After every plan wave:** `tests/codegraph + golden 门禁 + tests/services/test_repo_router_adapter.py`
- **Before `/gsd-verify-work`:** Full suite must be green
- **Max feedback latency:** 60 seconds

---

## Per-Task Verification Map

| Task ID | Plan | Wave | Requirement | Threat Ref | Secure Behavior | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|------------|-----------------|-----------|-------------------|-------------|--------|
| 106-01-T1 六信号打分核心 | 106-01 | 1 | ROUTE-03/04/05 | T-106-01/02 | 异常输入不抛、防除零 | unit | `uv run pytest tests/codegraph/test_repo_router_scoring.py tests/codegraph/test_repo_router_golden.py -q` | ✅ 既有扩展 | ⬜ pending |
| 106-01-T2 INV-R1~R4 性质测试 | 106-01 | 1 | ROUTE-03/04/05 | — | 机制断言锁定 | unit (tdd) | `uv run pytest tests/codegraph/test_repo_router_scoring.py -q` | ✅ 既有扩展 | ⬜ pending |
| 106-02-T1 SettingKeys + config loader | 106-02 | 2 | ROUTE-06 | T-106-04 | 非法配置回退默认 + warning | unit (tdd) | `uv run pytest tests/codegraph/test_repo_router_config.py -q` | ❌ 新建 | ⬜ pending |
| 106-02-T2 权重专用端点 | 106-02 | 2 | ROUTE-06 | T-106-03/05 | superuser 门禁 + 网格/INV-R2 强校验 | integration | `uv run pytest tests/system/test_repo_router_weight_config.py -q` | ❌ 新建 | ⬜ pending |
| 106-03-T1 T1 别名词典/解析 | 106-03 | 2 | ROUTE-04 | T-106-06/08 | 超长值拒配、未分类→缺失 | unit (tdd) | `uv run pytest tests/codegraph/test_repo_router_metadata.py -q` | ❌ 新建 | ⬜ pending |
| 106-03-T2 T2 校准余弦 + 缓存 | 106-03 | 2 | ROUTE-04 | T-106-06/07 | embedding 失败静默降级、日志截断 | unit (tdd) | `uv run pytest tests/codegraph/test_repo_router_metadata.py -q` | ❌ 新建 | ⬜ pending |
| 106-04-T1 O-5 统计 + N_r 快照写入 | 106-04 | 3 | ROUTE-03/05 | T-106-09 | 空库拒写、写读契约闭环 | integration | `uv run pytest tests/codegraph/test_measure_repo_index_stats.py -q` | ✅ 既有扩展 | ⬜ pending |
| 106-04-T2 O-2 校准 command | 106-04 | 3 | ROUTE-04 | T-106-10/11 | redact_secrets_in_text、结构性降级 | integration | `uv run pytest tests/codegraph/test_calibrate_repo_router_metadata.py -q` | ❌ 新建 | ⬜ pending |
| 106-05-T1 权重设置区 UI | 106-05 | 3 | ROUTE-06 | T-106-12 | 走专用校验端点、不走通用 PUT | type-check + lint | `pnpm vue-tsc --noEmit && pnpm eslint <files>` | ❌ 新建 | ⬜ pending |
| 106-05-T2 SIGNAL_LABELS 新键 | 106-05 | 3 | ROUTE-04 | — | 未知 key 回退兼容 | unit (vitest) | `pnpm vitest run src/components/chat/__tests__/RoutingDecisionPanel.test.ts` | ✅ 既有扩展 | ⬜ pending |
| 106-06-T1 dense 查询 + repo_meta 组装 | 106-06 | 3 | ROUTE-03/04/05 | T-106-14/16 | 降级分支 + 免 N+1 | integration | `uv run pytest tests/codegraph -q` | ✅ 既有回归 | ⬜ pending |
| 106-06-T2 打分注入 + 快照扩展 | 106-06 | 3 | ROUTE-03/04/05/06 | T-106-15 | redact_for_ledger 覆盖新字段、版本换真 | integration | `uv run pytest tests/codegraph tests/services/test_repo_router_adapter.py -q` | ✅ 既有回归 | ⬜ pending |
| 106-06-T3 降级矩阵/生效语义测试 | 106-06 | 3 | ROUTE-03/04/05/06 | T-106-14 | 四降级 + 整体回退 legacy | integration (tdd) | `uv run pytest tests/codegraph/test_repo_router_v2_meta.py -q` | ❌ 新建 | ⬜ pending |
| 106-07-T1 回放守护用例 (RED) | 106-07 | 4 | ROUTE-06 | T-106-17/18 | 篡改拦截 + 旧快照标注 | unit (tdd RED) | `uv run pytest tests/codegraph/test_repo_router_replay.py -q`（预期失败） | ✅ 既有扩展 | ⬜ pending |
| 106-07-T2 双版本 replay (GREEN) | 106-07 | 4 | ROUTE-06 | T-106-17/18 | import 纯度、64KB 复核 | unit | `uv run pytest tests/codegraph/test_repo_router_replay.py -q` | ✅ 既有扩展 | ⬜ pending |
| 106-08-T1 fixture 扩展 + eval 透传 | 106-08 | 4 | ROUTE-03/04/05 | T-106-20 | hold-out 封存零引用 | unit + 结构断言 | Task 内 python 断言 + `uv run pytest tests/codegraph/test_repo_router_scoring.py -q` | ✅ 既有扩展 | ⬜ pending |
| 106-08-T2 版本 bump + 机制断言 + baseline 重建 | 106-08 | 4 | ROUTE-03 | T-106-19 | GENERATE_GOLDEN 生成 + 逐例 diff review | golden gate | `uv run pytest tests/codegraph/test_repo_router_golden.py -q` + baseline 四字段断言 | ✅ 既有扩展 | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

---

## Wave 0 Requirements

- [x] 打分核心新签名的不变量测试扩展（INV-R1~R4 覆盖新信号）→ 106-01-T2（wave 1，与实现同 plan 紧随其后）
- [x] golden fixture 结构扩展（facets/repo_meta/scored_at）+ 重建路径守护 → 106-08-T1（版本 bump 前置任务，先扩数据再翻转）
- [x] resolver / 权重 view / 校准 command 的新测试文件 → 106-02-T1/T2、106-03-T1/T2、106-04-T2、106-06-T3（各自 plan 内 tdd 任务）

*Existing infrastructure covers all phase requirements; new test files are additive.*

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| O-2 生产余弦校准 / O-5 生产覆盖率 / O-1 N_r 分布 | ROUTE-04/05/03 | 需生产数据（deferred 挂账） | 生产实例执行 `measure_repo_index_stats --activity --write-snapshot` 与 `calibrate_repo_router_metadata`，回填 106-MEASUREMENTS.md |
| 系统设置权重编辑面观感 | ROUTE-06 | 视觉判断 | 管理页「仓库路由权重」区调整权重并保存，复跑路由观察 breakdown 变化与快照 weight_set_version |

---

## Validation Sign-Off

- [x] All tasks have `<automated>` verify or Wave 0 dependencies
- [x] Sampling continuity: no 3 consecutive tasks without automated verify
- [x] Wave 0 covers all MISSING references
- [x] No watch-mode flags
- [x] Feedback latency < 60s
- [x] `nyquist_compliant: true` set in frontmatter

**Approval:** planned（planner 106 填充；执行期逐任务更新 Status）
