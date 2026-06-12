---
phase: 18
slug: engine
status: draft
nyquist_compliant: false
wave_0_complete: false
created: 2026-06-13
---

# Phase 18 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest>=9.0.2 + pytest-django + pytest-asyncio（既有） |
| **Config file** | `server/pyproject.toml`（[tool.pytest]） |
| **Quick run command** | `cd server && uv run pytest tests/workflows/test_engine_routing.py -x` |
| **Full suite command** | `cd server && uv run pytest tests/workflows/ -x`（368+ 例）；阶段门禁全量 `uv run pytest` |
| **Estimated runtime** | ~30 seconds (quick) / ~数分钟 (full) |

---

## Sampling Rate

- **After every task commit:** Run `cd server && uv run pytest tests/workflows/test_engine_routing.py tests/workflows/test_engine_waiting.py -x`（纯函数 + run_sync，<30s）
- **After every plan wave:** Run `cd server && uv run pytest tests/workflows/ -x`
- **Before `/gsd-verify-work`:** Full suite must be green（`cd server && uv run pytest`）
- **Max feedback latency:** 60 seconds

---

## Per-Task Verification Map

| Task ID | Plan | Wave | Requirement | Threat Ref | Secure Behavior | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|------------|-----------------|-----------|-------------------|-------------|--------|
| TBD | TBD | TBD | ENG-01 | — | 末端/带下游 waiting_event ⇒ suspended（绝不 completed）；execution_suspended hook 触发；回调续跑语义一致；waiting_approval 不热循环 | integration | `cd server && uv run pytest tests/workflows/test_engine_waiting.py -x` | ❌ W0 | ⬜ pending |
| TBD | TBD | TBD | ENG-02 | — | 条件分支仅选中支执行；未选中支级联 skipped（含菱形汇合）；主循环与回调续跑同结果 | unit + integration | `cd server && uv run pytest tests/workflows/test_engine_routing.py -x` | ❌ W0 | ⬜ pending |
| TBD | TBD | TBD | ENG-03 | — | manual/API/feishu 触发下 {{trigger.source}}/{{trigger.raw_payload.*}} 可解析；resume_from_node 继承 trigger_data | integration | `cd server && uv run pytest tests/workflows/test_engine_trigger_data.py -x` | ❌ W0 | ⬜ pending |
| TBD | TBD | TBD | ENG-04 | — | 人造死锁 DAG ⇒ failed + error_message 末行 json.loads 含 pending/waiting_on/short_id/handle | unit + integration | `cd server && uv run pytest tests/workflows/test_engine_deadlock.py -x` | ❌ W0 | ⬜ pending |
| TBD | TBD | TBD | ENG-05 | — | target_handle 归集（coding_result 命中主路径、plan 不双重嵌套）；四类路径回归集合全绿 | unit + integration | `cd server && uv run pytest tests/workflows/test_engine_inputs.py tests/workflows/ -x` | ❌ W0 | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

---

## Wave 0 Requirements

- [ ] `server/tests/workflows/test_engine_waiting.py` — ENG-01（含"复现容器回调断裂"的红测先行，坐实 A1）
- [ ] `server/tests/workflows/test_engine_routing.py` — ENG-02 路由/级联纯函数 + 双路径一致性
- [ ] `server/tests/workflows/test_engine_trigger_data.py` — ENG-03
- [ ] `server/tests/workflows/test_engine_deadlock.py` — ENG-04
- [ ] `server/tests/workflows/test_engine_inputs.py` — ENG-05 归集规则 + 两条真实节点链 characterization
- [ ] `server/tests/workflows/conftest.py` — 增加"条件分支工作流/等待工作流/死锁工作流"工厂夹具（范式照抄 test_engine.py 局部 fixture；用 code 节点或注册测试节点制造任意 next_handle/waiting 行为，规避真实 AI/飞书依赖）
- 框架安装：无需（既有 pytest 基础设施覆盖）

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| 真实容器回调续跑（runner→server HTTP 回调） | ENG-01 | 需要真实 Docker runner 与任务容器 | 部署后跑一条含 AI 编码节点的工作流，确认等待节点 suspended、回调后续跑完成 |

---

## Validation Sign-Off

- [ ] All tasks have `<automated>` verify or Wave 0 dependencies
- [ ] Sampling continuity: no 3 consecutive tasks without automated verify
- [ ] Wave 0 covers all MISSING references
- [ ] No watch-mode flags
- [ ] Feedback latency < 60s
- [ ] `nyquist_compliant: true` set in frontmatter

**Approval:** pending
