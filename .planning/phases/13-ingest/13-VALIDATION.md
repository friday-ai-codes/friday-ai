---
phase: 13
slug: ingest
status: draft
nyquist_compliant: false
wave_0_complete: false
created: 2026-06-11
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
| TBD（planner 填充） | — | — | INGEST-03 | T-13-01 | CodingPlan 创建/更新/触发编码 → 投递摄取；content 不含对话原文 | unit | `uv run pytest tests/knowledge/test_triggers.py -k chat -x` | ❌ W0 | ⬜ pending |
| TBD | — | — | INGEST-05 | — | MCP 两工具成功路径 → 投递摄取（plan + work_item 锚 + HAS_PLAN 边） | unit | `uv run pytest tests/knowledge/test_triggers.py -k mcp -x` | ❌ W0 | ⬜ pending |
| TBD | — | — | INGEST-06 | T-13-03 | 重摄取 → 新版本 + is_latest 翻转 + 旧边置位 + tombstone/删点序；删除失败注入下翻转仍生效 | unit | `uv run pytest tests/knowledge/test_ingestion.py -k "version or flip or chaos" -x` | ❌ W0 | ⬜ pending |
| TBD | — | — | INGEST-07 | T-13-03 | 同事件 3 连发单实体单版本；rollback 不投递；reconcile 修复注入漂移 | unit + command | `uv run pytest tests/knowledge/test_ingestion.py -k idempotent -x && uv run pytest tests/knowledge/test_reconcile.py -x` | ❌ W0 | ⬜ pending |
| TBD | — | — | INGEST-08 | T-13-02 | chunk 确定性（同输入同 point id）；payload 键集合 ⊇ schema 常量；hybrid dict 含 dense+sparse | unit | `uv run pytest tests/knowledge/test_chunking.py -x` | ❌ W0 | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

**特别测试（防线固化）：**
- A1 假设首验：async 上下文经 `sync_to_async` 注册 `transaction.on_commit`（`django_capture_on_commit_callbacks`）——Wave 0 第一条测试
- 对话原文不入图：normalizer 单测断言 content 不含 conversation 消息（T-13-01）
- payload 权限字段：键集合回归测试 import `collection.py` schema 常量（T-13-02，P6 防线）
- 既有 grep 审计测试自动守护：新增代码不得绕过 GraphStore 写边表 raw SQL

---

## Wave 0 Requirements

- [ ] `server/tests/knowledge/test_ingestion.py` — INGEST-06/07/08 核心 stubs
- [ ] `server/tests/knowledge/test_chunking.py` — INGEST-08 确定性
- [ ] `server/tests/knowledge/test_triggers.py` — INGEST-03/05 接线 + on_commit 边界（A1 最先验证）
- [ ] `server/tests/knowledge/test_reconcile.py` — INGEST-07 对账
- [ ] `server/tests/knowledge/conftest.py` 扩展 `mock_embedding` fixture（dense AsyncMock + sparse sync）
- 框架零安装（全部已就位）

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| 真实 Qdrant 端到端摄取（hybrid 写入 + tombstone + 删点） | INGEST-06/08 | 测试全 mock（--disable-socket）；真实 named vectors 行为需实例 | compose 启 qdrant 后在 dev 环境触发一次 CodingPlan 摄取，检查 delivery_knowledge 点位与 payload |

---

## Validation Sign-Off

- [ ] All tasks have `<automated>` verify or Wave 0 dependencies
- [ ] Sampling continuity: no 3 consecutive tasks without automated verify
- [ ] Wave 0 covers all MISSING references
- [ ] No watch-mode flags
- [ ] Feedback latency < 120s
- [ ] `nyquist_compliant: true` set in frontmatter

**Approval:** pending
