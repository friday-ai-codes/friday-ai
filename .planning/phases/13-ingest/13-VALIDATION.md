---
phase: 13
slug: ingest
status: ready
nyquist_compliant: true
wave_0_complete: false
created: 2026-06-11
updated: 2026-06-11
---

# Phase 13 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest >=9.0.2 + pytest-django + pytest-asyncio（`asyncio_mode=auto`）+ pytest-socket |
| **Config file** | `server/pyproject.toml [tool.pytest.ini_options]`（`--disable-socket`） |
| **Quick run command** | `cd server && uv run pytest tests/knowledge/ -x` |
| **Full suite command** | `cd server && uv run pytest tests/knowledge/ tests/test_coding_tools.py tests/mcp_tools/ -x` |
| **Estimated runtime** | quick ~20s / full ~90s |

---

## Sampling Rate

- **After every task commit:** Run `cd server && uv run pytest tests/knowledge/ -x`
- **After every plan wave:** Run `cd server && uv run pytest tests/knowledge/ tests/test_coding_tools.py tests/mcp_tools/ -x`（触发点宿主测试零回归）
- **Before `/gsd-verify-work`:** knowledge + 宿主套件 green + `uv run python manage.py makemigrations --check --dry-run` 干净
- **Max feedback latency:** 120 seconds

---

## Per-Task Verification Map

| Task ID | Plan | Wave | Requirement | Threat Ref | Secure Behavior | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|------------|-----------------|-----------|-------------------|-------------|--------|
| 13-01 Task 1 | 13-01 | 1 | INGEST-08 | — | vector_synced 字段 + 迁移完整；mock_embedding fixture 就位 | unit | `cd server && uv run python manage.py makemigrations --check --dry-run && uv run pytest tests/knowledge/ -x` | ❌ 本任务创建 | ⬜ pending |
| 13-01 Task 2 | 13-01 | 1 | INGEST-08 | — | chunk 确定性（同输入同 chunk 同 point id）；point id 派生格式锁定 | unit | `cd server && uv run pytest tests/knowledge/test_chunking.py -x` | ❌ 本任务创建 | ⬜ pending |
| 13-01 Task 3 | 13-01 | 1 | INGEST-08, INGEST-06 | T-13-02, T-13-03 | payload 键集合 ⊇ schema 常量（含权限维度）；hybrid dict 含 dense+sparse；upsert False → raise；按 point id 删（无 filter 删） | unit | `cd server && uv run pytest tests/knowledge/test_vector_ops.py tests/knowledge/ -x` | ❌ 本任务创建 | ⬜ pending |
| 13-02 Task 1 | 13-02 | 2 | INGEST-07 | T-13-03 | A1 首验：autocommit 立即投递 / rollback 不投递 / aschedule 异常不上抛 | unit | `cd server && uv run pytest tests/knowledge/test_ingestion.py -k "schedule or rollback" -x` | ❌ 本任务创建 | ⬜ pending |
| 13-02 Task 2 | 13-02 | 2 | INGEST-06, INGEST-07, INGEST-08 | T-13-03, T-13-02, T-13-04 | 同事件 3 连发单实体单版本；重摄取版本翻转（v1 invalid_at + tombstone/删点序）；chaos 注入下 is_latest 翻转仍生效；hash 相同 + vector_synced=False 重触发零新版本（crash 恢复幂等）+ 预短路零 embedding 调用；embedding None 整体 abort；payload 键集合断言 | unit | `cd server && uv run pytest tests/knowledge/test_ingestion.py -x` | ❌ 本任务创建 | ⬜ pending |
| 13-03 Task 1 | 13-03 | 3 | INGEST-03, INGEST-05 | T-13-01 | normalizer 取材边界：chat content 仅 title+tech_plan（特征串断言）；mcp 双事件 + HAS_PLAN EdgeSpec | unit | `cd server && uv run pytest tests/knowledge/test_triggers.py -k "normalize" -x` | ❌ 本任务创建 | ⬜ pending |
| 13-03 Task 2 | 13-03 | 3 | INGEST-03, INGEST-05 | T-13-03 | 5 锚点只接线（≤5 行/处）；宿主套件零回归 | unit + regression | `cd server && uv run pytest tests/knowledge/ tests/test_coding_tools.py tests/mcp_tools/ -x` | ✅ 宿主既有 | ⬜ pending |
| 13-03 Task 3 | 13-03 | 3 | INGEST-03, INGEST-05 | T-13-01, T-13-03 | chat/mcp 触发各投递断言（`-k chat` / `-k mcp`）；ingestion 抛错主流程仍成功 | unit | `cd server && uv run pytest tests/knowledge/test_triggers.py -x` | ✅ Task 1 创建（本任务扩展） | ⬜ pending |
| 13-04 Task 1 | 13-04 | 3 | INGEST-07, INGEST-06 | T-13-03 | reconcile 六检查项（含 missing_edges 边一致性）dry-run 零写；单点异常 skip 不崩 | unit + command | `cd server && uv run pytest tests/knowledge/test_reconcile.py -k "detect or skip" -x` | ❌ 本任务创建 | ⬜ pending |
| 13-04 Task 2 | 13-04 | 3 | INGEST-06 | T-13-03 | rebuild --yes 删建后全量重嵌入 latest（旧版本不进检索面） | unit | `cd server && uv run pytest tests/knowledge/test_reconcile.py -k rebuild -x` | ✅ Task 1 创建（本任务追加） | ⬜ pending |
| 13-04 Task 3 | 13-04 | 3 | INGEST-07 | T-13-03, T-13-02 | --fix 三类修复 + 检查项 6 边补建调用参数级断言；Pitfall 2（hash 短路 + 向量缺失）闭环 | unit + command | `cd server && uv run pytest tests/knowledge/test_reconcile.py -x` | ✅ Task 1/2 创建（本任务扩展） | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

**特别测试（防线固化）：**
- A1 假设首验：async 上下文经 `sync_to_async` 注册 `transaction.on_commit`（`django_capture_on_commit_callbacks`）——Wave 0 第一条测试
- 对话原文不入图：normalizer 单测断言 content 不含 conversation 消息（T-13-01）
- payload 权限字段：键集合回归测试 import `collection.py` schema 常量（T-13-02，P6 防线）
- 既有 grep 审计测试自动守护：新增代码不得绕过 GraphStore 写边表 raw SQL

---

## Wave 0 Requirements

> 规划定案：测试文件随实现任务同 plan 交付（Phase 12 同款节奏），无独立 Wave 0 执行批——每个 task 的 `<verify>` 在 task 内闭环。归属如下：

- [ ] `server/tests/knowledge/conftest.py` 扩展 `mock_embedding` fixture（dense AsyncMock + sparse sync）— **13-01 Task 1**
- [ ] `server/tests/knowledge/test_chunking.py` — INGEST-08 确定性 — **13-01 Task 2**
- [ ] `server/tests/knowledge/test_vector_ops.py` — payload 键集合锁定 + 失败响亮（规划新增文件）— **13-01 Task 3**
- [ ] `server/tests/knowledge/test_ingestion.py` — INGEST-06/07/08 核心 + on_commit 边界（A1 最先验证，调度层用例）— **13-02 Task 1/2**
- [ ] `server/tests/knowledge/test_triggers.py` — INGEST-03/05 normalizer 取材 + 接线 — **13-03 Task 1 创建（Task 3 扩展）**
- [ ] `server/tests/knowledge/test_reconcile.py` — INGEST-07 对账 — **13-04 Task 1 创建（Task 2/3 扩展）**
- 框架零安装（全部已就位）

> 注：A1（async on_commit 组合）验证用例位于 test_ingestion.py 调度层用例组（13-02 Task 1），而非 test_triggers.py——aschedule_ingestion 是核心层符号，触发点测试只断言接线投递。

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| 真实 Qdrant 端到端摄取（hybrid 写入 + tombstone + 删点） | INGEST-06/08 | 测试全 mock（--disable-socket）；真实 named vectors 行为需实例 | compose 启 qdrant 后在 dev 环境触发一次 CodingPlan 摄取，检查 delivery_knowledge 点位与 payload |

---

## Validation Sign-Off

- [x] All tasks have `<automated>` verify or Wave 0 dependencies（11/11 task 均有 `<automated>` 命令）
- [x] Sampling continuity: no 3 consecutive tasks without automated verify
- [x] Wave 0 covers all MISSING references（6 个测试文件全部有归属 task）
- [x] No watch-mode flags
- [x] Feedback latency < 120s
- [x] `nyquist_compliant: true` set in frontmatter

**Approval:** pending
