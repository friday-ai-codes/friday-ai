---
phase: 12
slug: kmod
status: approved
nyquist_compliant: true
wave_0_complete: false
created: 2026-06-11
---

# Phase 12 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest >=9.0.2 + pytest-django + pytest-asyncio（`asyncio_mode=auto`） |
| **Config file** | `server/pyproject.toml [tool.pytest.ini_options]`（`testpaths=["tests"]`，`--disable-socket`） |
| **Quick run command** | `cd server && uv run pytest tests/knowledge/ -x` |
| **Full suite command** | `cd server && uv run pytest` |
| **Estimated runtime** | quick ~10s / full ~120s |

---

## Sampling Rate

- **After every task commit:** Run `cd server && uv run pytest tests/knowledge/ -x`
- **After every plan wave:** Run `cd server && uv run pytest`
- **Before `/gsd-verify-work`:** Full suite must be green + `uv run python manage.py makemigrations --check --dry-run`
- **Max feedback latency:** 120 seconds

---

## Per-Task Verification Map

| Task ID | Plan | Wave | Requirement | Threat Ref | Secure Behavior | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|------------|-----------------|-----------|-------------------|-------------|--------|
| 12-01-01 | 01 | 1 | KMOD-01, KMOD-02, KMOD-03 | T-12-02 | 三模型 + natural key 唯一约束 + kind/origin 枚举 DB 兜底 + 四时间戳/时间次序约束 | unit | `uv run pytest tests/knowledge/test_models.py -x` | ❌ W0 | ⬜ pending |
| 12-01-02 | 01 | 1 | KMOD-01 | — | 测试基建（conftest fixtures + Qdrant seam）+ admin 最小注册 | unit | `uv run pytest tests/knowledge/ -x` | ❌ W0 | ⬜ pending |
| 12-01-03 | 01 | 1 | KMOD-01, KMOD-03 | T-12-02 | 约束/枚举兜底/版本链回溯全套测试；one-latest 部分唯一约束 | unit | `uv run pytest tests/knowledge/test_models.py -k version -x` | ❌ W0 | ⬜ pending |
| 12-02-01 | 02 | 2 | KMOD-04, KMOD-02 | T-12-04 | GraphStore 接口 + 写路径 + 级联失效原语（置位不删除） | unit | `uv run pytest tests/knowledge/test_graph_store.py -x` | ❌ W0 | ⬜ pending |
| 12-02-02 | 02 | 2 | KMOD-04 | T-12-01 / T-12-03 | 递归 CTE 遍历参数化 SQL（SQLite/PG 双后端）；环终止；深度 clamp | unit | `uv run pytest tests/knowledge/test_graph_store.py -x` | ❌ W0 | ⬜ pending |
| 12-02-03 | 02 | 2 | KMOD-04, KMOD-02 | T-12-01 / T-12-03 | 失效边默认不可见、as_of 历史可见；raw SQL 收口 grep 审计 | unit | `uv run pytest tests/knowledge/test_graph_store.py -k "invalid or as_of" -x` | ❌ W0 | ⬜ pending |
| 12-03-01 | 03 | 2 | KMOD-01 (SC#5) | T-12-02 / T-12-04 | payload schema 8 字段定型（含权限维度）；mismatch raise 不删库 | unit (Qdrant mock) | `uv run pytest tests/knowledge/test_collection.py -x` | ❌ W0 | ⬜ pending |
| 12-03-02 | 03 | 2 | KMOD-01 (SC#5) | T-12-04 | `rebuild_delivery_knowledge` 显式重建命令需 `--yes`，structlog 留痕 | unit (Qdrant mock) | `uv run pytest tests/knowledge/test_collection.py -k command -x` | ❌ W0 | ⬜ pending |
| 12-03-03 | 03 | 2 | KMOD-01 (SC#5) | T-12-04 | 生命周期/维度校验/命令流程测试（`delete_collection.assert_not_called()`） | unit (Qdrant mock) | `uv run pytest tests/knowledge/test_collection.py -x` | ❌ W0 | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

**特别测试（PITFALLS 防线固化）：**
- grep 审计测试：`WITH RECURSIVE` 与边表表名的 raw SQL 出现处 ⊆ {`knowledge/graph_store.py`}（读源码的 pytest 用例）
- 双后端一致性：所有 GraphStore 测试在 SQLite 下跑（CI 默认）；UUID `get_db_prep_value` 路径有专测
- 环用例（A→B→C→A）、深度用例（4 跳链只回 3 跳）、失效边用例（多跳路径中段失效 → 下游不可达）

---

## Wave 0 Requirements

- [ ] `server/tests/knowledge/__init__.py` + `test_models.py` + `test_graph_store.py` + `test_collection.py` — stubs for KMOD-01..04 + SC#5
- [ ] `server/tests/knowledge/conftest.py` — entity/edge/version factory fixtures（factory-boy）
- [ ] Qdrant seam fixture — autouse monkeypatch stub（照 `tests/test_git_diff_index.py` 模式）
- 框架零安装（pytest 基建齐备）

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| PG 后端递归 CTE 实跑 | KMOD-04 | CI 默认 SQLite，PG 方言路径需真实 PG 验证 | docker compose 启 postgres，`DATABASE_URL` 指向后跑 `tests/knowledge/test_graph_store.py` |

---

## Validation Sign-Off

- [x] All tasks have `<automated>` verify or Wave 0 dependencies
- [x] Sampling continuity: no 3 consecutive tasks without automated verify
- [x] Wave 0 covers all MISSING references
- [x] No watch-mode flags
- [x] Feedback latency < 120s
- [x] `nyquist_compliant: true` set in frontmatter

**Approval:** approved 2026-06-11（plan-checker 复检通过）
