---
phase: 21
slug: observability
status: complete
nyquist_compliant: true
wave_0_complete: true
created: 2026-06-13
backfilled: 2026-06-14  # frontmatter 收尾：Wave 0 测试实际全绿（tests/workflows/ 479 passed 复核），回写遗漏标记
---

# Phase 21 — Validation Strategy

> 触发模型与执行可观测——后端 pytest + 前端 vitest 双侧验证契约。

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework (backend)** | pytest + pytest-asyncio + pytest-django（server/） |
| **Framework (frontend)** | vitest@^4 + @vue/test-utils + happy-dom（web/） |
| **Config file** | server/pyproject.toml（pytest）; web/vite.config.ts(test) |
| **Quick run (backend)** | `cd server && uv run pytest tests/workflows/test_trigger_sync.py tests/test_trigger_dispatcher.py -x` |
| **Quick run (frontend)** | `pnpm -C web test:unit -- src/config src/stores/__tests__` |
| **Full suite (backend)** | `cd server && uv run pytest tests/ -q` |
| **Full suite (frontend)** | `pnpm -C web test:unit` |
| **Estimated runtime** | trigger 子集 ~15s / 前端相关 ~数十秒 |

---

## Sampling Rate

- **After every task commit:** 受影响单文件快速命令（上表 Quick run 子集）。
- **After every plan wave:** `cd server && uv run pytest tests/workflows tests/test_trigger_dispatcher.py tests/test_trigger_views.py -q` + `pnpm -C web test:unit`。
- **Before `/gsd-verify-work`:** 后端 `uv run pytest tests/ -q` 全绿 + 前端 `pnpm -C web test:unit` 全绿 + `pnpm -C web type-check`。
- **Max feedback latency:** 60 seconds。

---

## Per-Task Verification Map

| Task ID | Plan | Wave | Requirement | Behavior | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|----------|-----------|-------------------|-------------|--------|
| TBD | TBD | 0 | TRIG-01 | 单数 event_type 同步生成 WorkflowTrigger + 复数兜底 + filter_status 数组 + 端到端匹配 | unit/integration | `uv run pytest tests/workflows/test_trigger_sync.py -x` | ❌ W0 | ⬜ pending |
| TBD | TBD | 1 | TRIG-02 | trigger_type choices 不含 schedule + 存量行不报错 + 前端无 schedule 选项 | unit + migration | `uv run pytest tests/workflows/test_trigger_type_choices.py -x` | ❌ W0 | ⬜ pending |
| TBD | TBD | 1 | TRIG-03 | dispatch 异常→TriggerLog.status=失败态 + error_message；无匹配→可查状态 | integration | `uv run pytest tests/test_trigger_dispatcher.py -k fail -x` | ⚠️ 扩展 | ⬜ pending |
| TBD | TBD | 0 | OBS-01 | WS 广播 node_failed 含 error_message/error_code | unit | `uv run pytest tests/workflows/test_hooks.py -k broadcast -x` | ❌ W0 | ⬜ pending |
| TBD | TBD | 1 | OBS-01 | 前端 node_failed 写 NE.error_message + 结构化变量错误 JSON.parse 展示/回退 + error_code | unit(vitest) | `pnpm -C web test:unit -- src/stores/__tests__ src/components/execution` | ❌ W0 | ⬜ pending |
| TBD | TBD | 1 | OBS-02 | WS CLOSED→启动 REST 轮询；重连停止；服务端权威值 | unit(vitest) | `pnpm -C web test:unit -- src/pages/executions/composables` | ❌ W0 | ⬜ pending |
| TBD | TBD | 1 | OBS-03 | 每个 ExecutionStatus 值有非 fallback badge（含 suspended/timeout）；stats 区分 execution(suspended) vs node(waiting_*) | unit(vitest) | `pnpm -C web test:unit -- src/config src/stores/__tests__` | ❌ W0 | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

---

## Wave 0 Requirements

- [ ] `server/tests/workflows/test_trigger_sync.py` — TRIG-01 同步/兜底/filter_config/端到端匹配（含 conftest workflow + feishu_event_trigger node 夹具）。
- [ ] `server/tests/workflows/test_trigger_type_choices.py` — TRIG-02 choices 断言（轻量）。
- [ ] `server/tests/workflows/test_hooks.py` — OBS-01 WebSocketBroadcastHook error_message 广播（mock channel_layer.group_send 断言 message dict）。
- [ ] `web/src/stores/__tests__/useExecutionsStore.spec.ts` — OBS-01/03 node_failed 写 error_message + stats 语义。
- [ ] `web/src/config/__tests__/status.spec.ts` — OBS-03 ExecutionStatus 全覆盖断言。
- [ ] `web/src/pages/executions/composables/__tests__/useExecutionState.spec.ts` — OBS-02 WS 降级状态机。
- [ ] 扩展 `server/tests/test_trigger_dispatcher.py` — TRIG-03 失败持久化断言。
- 框架安装：无需（pytest/vitest 既有）。

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| 保存 feishu_event_trigger 后真实飞书事件触发工作流执行 | TRIG-01 | 需真实飞书事件 + 凭证 | 配置 feishu_event_trigger 保存，发真实飞书工作项事件，确认工作流执行被触发 |
| 详情页节点失败时 error/变量错误实时展示、WS 断线降级轮询、suspended 状态如实显示 | OBS-01/02/03 | 浏览器交互观感 | 跑一条会失败/挂起的工作流，断网模拟 WS 断线，确认 UI 不冻结、状态如实、失败原因可见 |

---

## Validation Sign-Off

- [ ] All tasks have `<automated>` verify or Wave 0 dependencies
- [ ] Sampling continuity: no 3 consecutive tasks without automated verify
- [ ] Wave 0 covers all MISSING references
- [ ] No watch-mode flags
- [ ] Feedback latency < 60s
- [ ] `nyquist_compliant: true` set in frontmatter

**Approval:** pending
