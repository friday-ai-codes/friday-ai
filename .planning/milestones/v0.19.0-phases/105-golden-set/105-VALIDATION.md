---
phase: 105
slug: golden-set
# status lifecycle: draft (seeded by plan-phase) → validated (set by validate-phase §6)
# audit-milestone §5.5 distinguishes NOT-VALIDATED (draft) from PARTIAL (validated + nyquist_compliant: false) (#2117)
status: draft
nyquist_compliant: false
wave_0_complete: false
created: 2026-07-29
---

# Phase 105 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest 9.x（server/，uv 管理）+ vitest 4（web/） |
| **Config file** | server/pyproject.toml（[tool.pytest.ini_options]）；web/vitest 由 vite 配置 |
| **Quick run command** | `cd server && uv run pytest tests/codegraph tests/services -x -q -k router` |
| **Full suite command** | `cd server && uv run pytest -q`（前端改动另跑 `cd web && pnpm vitest run <spec>`） |
| **Estimated runtime** | 快跑 ~30s；全量分钟级 |

---

## Sampling Rate

- **After every task commit:** Run quick run command（受改测试目录定向跑）
- **After every plan wave:** Run 受影响模块全量（router/delivery/process_runtime 相关测试）
- **Before `/gsd-verify-work`:** Full suite must be green
- **Max feedback latency:** 60 seconds

---

## Per-Task Verification Map

| Task ID | Plan | Wave | Requirement | Threat Ref | Secure Behavior | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|------------|-----------------|-----------|-------------------|-------------|--------|
| 105-01-T1 打分核心模块 + θ settings 外置 | 105-01 | 1 | RELY-04/ROUTE-07/ROUTE-09 | T-105-01 | facets JSON 解析容错、rrf_max<=0 防除零、repo_name 缺失回退 repo_id | unit（import + 行为断言） | `cd server && uv run python -c "from codegraph.services.repo_router_scoring import ...; assert derive_confidence(...)=='high'; assert apply_llm_adjustment('low','high')=='low'"` | 新建模块（无前置测试依赖） | ⬜ pending |
| 105-01-T2 不变量与确定性性质测试 | 105-01 | 1 | ROUTE-07/ROUTE-09 | — | 只降不升穷举断言 | unit（性质） | `cd server && uv run pytest tests/codegraph/test_repo_router_scoring.py -x -q` | ❌ W0（本 task 创建） | ⬜ pending |
| 105-02-T1 measure_repo_index_stats 命令 | 105-02 | 1 | ROUTE-08（SC-5） | T-105-04 | 单仓 count 异常 warning 跳过不中断 | unit（内存 Qdrant） | `cd server && uv run pytest tests/codegraph/test_measure_repo_index_stats.py -x -q` | ❌ W0（本 task 创建） | ⬜ pending |
| 105-02-T2 105-MEASUREMENTS.md 撰写 | 105-02 | 1 | ROUTE-08（SC-5） | T-105-05 | 输出仅仓名/计数，无敏感串 | doc check + 人工（生产实测 deferred） | `test -f .planning/phases/105-golden-set/105-MEASUREMENTS.md && rg -q "O-3" ... && rg -q "measure_repo_index_stats" ...` | 新建文档 | ⬜ pending |
| 105-03-T1 router 接线打分核心（去截断/breakdown/degraded/snapshot） | 105-03 | 2 | RELY-04/ROUTE-07/ROUTE-09 | T-105-06/T-105-07 | repo_id 白名单保留；auto_selected 仅确定性 margin 驱动 | regression（消费方 stub） | `cd server && uv run pytest tests/services/test_repo_router_adapter.py tests/knowledge/test_artifact_repo_routing.py tests/initiatives/test_repo_association_service.py -q` | ✅ 既有测试 | ⬜ pending |
| 105-03-T2 三种失联情形行为测试 | 105-03 | 2 | RELY-04 | T-105-07 | low→high 升级被拒断言 | unit（tdd） | `cd server && uv run pytest tests/codegraph/test_repo_router_v2_degraded.py -x -q` | ❌ W0（本 task 创建） | ⬜ pending |
| 105-03-T3 clarify policy 集成测试（含强制确认不无差别触发回归） | 105-03 | 2 | RELY-04（SC-1） | — | ClarifyAdapter.run 行为级断言（不建轮/不 emit） | integration | `cd server && uv run pytest tests/services/test_engine_clarify.py -x -q` | ✅ 既有文件，补 3 用例 | ⬜ pending |
| 105-04-T1 评估 harness 纯函数模块 | 105-04 | 2 | ROUTE-08 | — | 零 Django/网络依赖 | unit（import + CI 幂等断言） | `cd server && uv run python -c "from codegraph.services.repo_router_eval import ...; bootstrap_ci 同 seed 相等断言"` | 新建模块 | ⬜ pending |
| 105-04-T2 golden set fixture（主集/hold-out/baseline） | 105-04 | 2 | ROUTE-08 | — | hold-out 封存（opened_count） | data check | `cd server && uv run python -c "json 加载三 fixture + 条数/cross_group/label_source 断言"` | 新建 fixture | ⬜ pending |
| 105-04-T3 golden 门禁测试进默认 suite | 105-04 | 2 | ROUTE-08（SC-4） | T-105-08/T-105-09 | baseline 绑定 weight_set_version；<10s 硬断言 | golden gate | `cd server && GENERATE_GOLDEN=1 uv run pytest tests/codegraph/test_repo_router_golden.py -q && uv run pytest tests/codegraph/test_repo_router_golden.py -x -q` | ❌ W0（本 task 创建） | ⬜ pending |
| 105-05-T1 build_chat_model decode 参数透传 | 105-05 | 3 | ROUTE-09 | — | 默认 None 零回归面 | unit | `cd server && uv run pytest tests/test_llm_factory.py -q` | ✅ 既有文件，补透传用例 | ⬜ pending |
| 105-05-T2 Stage 1 重写（排列输出/缓存/call_source/snapshot） | 105-05 | 3 | ROUTE-09/RELY-04 | T-105-10/T-105-11/T-105-12 | prompt/response 经 redact_for_ledger；缓存 key sha256 全输入绑定；TTL 兜底 | regression | `cd server && uv run pytest tests/codegraph/test_repo_router_v2_degraded.py -q` | ✅ 105-03 产物 | ⬜ pending |
| 105-05-T3 幂等行为测试 | 105-05 | 3 | ROUTE-09（SC-3） | T-105-11 | 缓存异常 best-effort 不反噬断言 | unit（tdd） | `cd server && uv run pytest tests/codegraph/test_repo_router_stage1_idempotency.py -x -q` | ❌ W0（本 task 创建） | ⬜ pending |
| 105-06-T1 后端 breakdown 透传（schema + v2 路径） | 105-06 | 3 | ROUTE-07 | — | score ge=0/le=1 约束天然满足 | unit | `cd server && uv run pytest tests/agents/test_repository_relevance_tool.py -x -q` | ✅ 既有文件，补用例 | ⬜ pending |
| 105-06-T2 前端分数分解展开区 + Tooltip | 105-06 | 3 | ROUTE-07（SC-2） | T-105-13 | 模板插值自动转义、无 v-html | typecheck | `cd web && pnpm exec vue-tsc --noEmit` | ✅ 既有组件改造 | ⬜ pending |
| 105-06-T3 组件测试补用例 | 105-06 | 3 | ROUTE-07（SC-2） | — | 缺 breakdown 静默降级断言 | component unit（tdd） | `cd web && pnpm exec vitest run src/components/chat/__tests__/RoutingDecisionPanel.test.ts` | ✅ 既有文件，补 3 用例 | ⬜ pending |
| 105-07-T1 adapter degraded/snapshot 透传 + _h_route 快照落盘 | 105-07 | 4 | ROUTE-09 | T-105-15/T-105-17 | payload 整体 redact_for_ledger；只经 _emit_event 单入口 | integration | `cd server && uv run pytest tests/services/test_repo_router_adapter.py -x -q` | ✅ 既有文件，补断言 | ⬜ pending |
| 105-07-T2 离线 replay 模块 + 守护测试 | 105-07 | 4 | ROUTE-09（SC-3） | T-105-15/T-105-16 | sk- 模式脱敏断言 + 64KB 上限；repo_name 缺失容错 | unit（tdd，零网络） | `cd server && uv run pytest tests/codegraph/test_repo_router_replay.py -x -q` | ❌ W0（本 task 创建） | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

---

## Wave 0 Requirements

- [ ] golden set fixture 与离线 harness 测试文件 stub（REQ ROUTE-08）
- [ ] 现有 `server/tests/services/test_repo_router_adapter.py` 等 router 触点测试保持绿（回归基线）

*Existing infrastructure (pytest + pytest-socket + respx + factory-boy) covers all phase requirements; new test files are additive.*

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| 前端展开分数分解的视觉观感 | ROUTE-07 | 视觉判断 | 打开对话路由结果面板，展开候选查看分解列表与合计行 |

---

## Validation Sign-Off

- [ ] All tasks have `<automated>` verify or Wave 0 dependencies
- [ ] Sampling continuity: no 3 consecutive tasks without automated verify
- [ ] Wave 0 covers all MISSING references
- [ ] No watch-mode flags
- [ ] Feedback latency < 60s
- [ ] `nyquist_compliant: true` set in frontmatter

**Approval:** pending
