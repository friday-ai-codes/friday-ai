---
phase: 85
slug: context-read-branch-binding
status: draft
nyquist_compliant: true
wave_0_complete: false
created: 2026-06-27
---

# Phase 85 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution. 源自 85-RESEARCH.md「Validation Architecture」+ Nyquist 覆盖矩阵。本 phase 几乎全为「组合既有地基」（normalizer + 钩子 + 模型 + 叠加查询），最大风险是 **A3 召回口径（members_only 零泄漏）** 与 **命名遗留陷阱（KnowledgeEntity.space 承载 project 维度）**——二者均有专门自动化守护（85-02 Task 1 零泄漏门 + 对称矩阵）。所有材料化/召回观测代码 best-effort，绝不反噬业务写。

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest 9.x（pytest-asyncio + pytest-django + respx + pytest-socket 网络隔离） |
| **Config file** | `server/pyproject.toml`（`[tool.pytest.ini_options]`）；`server/tests/conftest.py`（adrf monkeypatch 必须在 Django 加载前） |
| **Quick run command** | `cd server && uv run pytest tests/knowledge/ tests/initiatives/ tests/mcp_tools/ -x -q` |
| **Full suite command** | `cd server && uv run pytest -q` |
| **Estimated runtime** | ~60–90 秒（分模块快跑 ~25 秒） |

---

## Sampling Rate

- **After every task commit:** `cd server && uv run pytest tests/<改动模块> -x -q`（如 `tests/knowledge/test_project_doc_source.py`、`tests/mcp_tools/test_project_context_tools.py`）
- **After every plan wave:** `cd server && uv run pytest tests/initiatives/ tests/knowledge/ tests/mcp_tools/ tests/services/ -q`
- **Before `$gsd-verify-work`:** `cd server && uv run pytest -q` 全绿 + `uv run ruff check` + `uv run mypy`（项目惯例）
- **Max feedback latency:** < 90 秒

---

## Requirement → Test Map

| Req ID | Behavior | Plan/Task | Test Type | Automated Command | File Exists |
|--------|----------|-----------|-----------|-------------------|-------------|
| CTX-01 | 项目 5 文件/记忆物化进 delivery_knowledge（写半，RAG 可召回） | 85-01 T1/T2 | unit | `uv run pytest tests/knowledge/test_project_doc_source.py tests/knowledge/test_project_memory_source.py -x` | ❌ Wave 0 |
| CTX-01 | search_project_context（RAG 任意来源召回） | 85-02 T2 | unit | `uv run pytest tests/mcp_tools/test_project_context_tools.py -k search_project_context -x` | ❌ Wave 0 |
| CTX-01 | grep_project 命中 ProjectDoc 正文 + 记忆正文（可 grep） | 85-02 T3 | unit | `uv run pytest tests/mcp_tools/test_project_context_tools.py tests/initiatives/test_project_search_service.py -x` | ❌ Wave 0 |
| CTX-01 | read_project_doc（file-read 单文档渲染 + block 分区） | 85-02 T3 | unit | `uv run pytest tests/mcp_tools/test_project_context_tools.py -k read_project_doc -x` | ❌ Wave 0 |
| CTX-02 | normalizer 产 DOCUMENT 实体 + REFERENCES→项目节点边 | 85-01 T1 | unit | `uv run pytest tests/knowledge/test_project_doc_source.py tests/knowledge/test_project_memory_source.py -x` | ❌ Wave 0 |
| CTX-02 | 写时增量钩子调 aschedule_ingestion + 归因透传 + fail-soft 不反噬 | 85-01 T2 | unit | `uv run pytest tests/initiatives/ -k "materialize or memory_service or project_doc or doc_sync" -x` | ❌ Wave 0 |
| CTX-02 | 兜底全量重建幂等（content_hash 短路、不删其他来源） | 85-01 T3 | unit | `uv run pytest tests/knowledge/test_rebuild_project_context.py -x` | ❌ Wave 0 |
| CTX-02 | RetrievalTrace 两链覆盖（MCP + AI 对话）+ duration_ms | 85-02 T2/T3 | unit | `uv run pytest tests/mcp_tools/test_project_context_tools.py tests/services/test_project_context_packer.py -x` | ⚠️ 扩充 |
| CTX-02（安全） | members_only 项目内容对非成员**零召回零泄漏**（A3 口径 PASS，非 xfail） | 85-02 T1 | unit | `uv run pytest tests/knowledge/test_access_scope.py tests/services/test_project_context_packer.py tests/mcp_tools/test_project_context_tools.py -k "leak or visibility or members_only or scope" -x` | ⚠️ 扩充 |
| BIND-01 | ProjectBranch 模型 + 唯一约束 (project,repository,branch_name) | 85-03 T1 | unit | `uv run pytest tests/initiatives/test_project_branch_model.py -x` | ❌ Wave 0 |
| BIND-01 | 写收口 service（bind/unbind 幂等 + 成员闸）+ INV-6 grep 守护 | 85-03 T2 | unit | `uv run pytest tests/initiatives/test_project_branch_service.py tests/initiatives/test_project_branch_inv6_guard.py -x` | ❌ Wave 0 |
| BIND-01 | 前端绑定 REST（增/删/查，写仅成员） | 85-03 T3 | unit | `uv run pytest tests/initiatives/test_project_branch_api.py -x` | ❌ Wave 0 |
| BIND-02 | lookup 叠加显式绑定 + 合并去重 + 可选 repository_id 收窄 | 85-04 T1 | unit | `uv run pytest tests/mcp_tools/test_lookup_project_by_branch.py -x` | ⚠️ 扩充 |
| BIND-02 | 多/无命中 fail-soft 候选（绝不抛、绝不阻断编码） | 85-04 T2 | unit | `uv run pytest tests/mcp_tools/test_lookup_project_by_branch.py -x` | ⚠️ 扩充 |

*File Exists: ✅ 已存在 · ⚠️ 扩充既有 · ❌ Wave 0 新建*

---

## Wave 0 Requirements

- [ ] `server/tests/knowledge/test_project_doc_source.py` — project_doc normalizer（DOCUMENT 实体 + space_id=项目 Space + REFERENCES 边 + 脱敏 + 源缺失返回 []）
- [ ] `server/tests/knowledge/test_project_memory_source.py` — project_memory normalizer（同上 + 非 active 返回 []）
- [ ] `server/tests/knowledge/test_rebuild_project_context.py` — 兜底重建幂等 + 不删整库
- [ ] 材料化钩子触发断言（在 memory/doc/sync service 测试中 mock `aschedule_ingestion`，断言被调 + 归因透传 + 抛错不反噬）
- [ ] `server/tests/mcp_tools/test_project_context_tools.py` — search/grep/read 三工具 + RetrievalTrace(含 duration_ms) + **members_only 非成员零泄漏（PASS，非 xfail）** + public_org 非成员可读 + grep ProjectDoc/记忆正文命中
- [ ] `server/tests/knowledge/test_access_scope.py` — 扩充：召回 scope 按 `initiatives.Project.visibility` 过滤（A3 修复后口径，若需修复）
- [ ] `server/tests/initiatives/test_project_search_service.py` — grep `_keyword_search` 覆盖 ProjectDoc 正文
- [ ] `server/tests/initiatives/test_project_branch_model.py` + `test_project_branch_service.py` + `test_project_branch_inv6_guard.py` + `test_project_branch_api.py` — BIND-01 模型/写收口/INV-6/REST
- [ ] `server/tests/mcp_tools/test_lookup_project_by_branch.py` — 扩充：显式绑定 + 合并去重 + repository_id 收窄 + 多/无命中 fail-soft

*现有测试基础设施（`tests/initiatives/conftest.py`、respx 飞书 mock、`test_retrieval_trace`、`test_project_context_packer`、既有 `test_lookup_project_by_branch`、`test_access_scope`）覆盖大部分 seam；Wave 0 主要补新 source/model/service/MCP 工具测试。*

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| 真实 Qdrant + 真实嵌入下的端到端项目上下文召回观感（语义相关度/排序质量） | CTX-01/02 | 需真实 Qdrant + 真实 EmbeddingProvider 凭证；语义相关度为主观质量 | 配置 Qdrant + 嵌入 Provider，写入若干项目记忆/文件，经 search_project_context / 前端 RAG 搜索确认相关内容被召回且 locator 指向正确 repo/project |
| 兜底定时全量重建在真实 apscheduler 下按时触发 | CTX-02 | 需运行 runapscheduler 进程 + 等待 cron 触发 | 启动 `runapscheduler`，确认 `rebuild_project_context` job 注册（DjangoJobStore），手动 `call_command` 或等待触发后日志 `rebuild_project_context_completed` |

*其余 phase 行为（normalizer 投影、钩子触发、归因、零泄漏 scope、模型唯一约束、INV-6、lookup fail-soft、grep 正文命中、RetrievalTrace 两链）均有自动化验证。*

---

## Validation Sign-Off

- [ ] All tasks have automated verify or Wave 0 dependencies
- [ ] Sampling continuity: no 3 consecutive tasks without automated verify
- [ ] Wave 0 covers all MISSING references
- [ ] No watch-mode flags
- [ ] Feedback latency < 90s
- [ ] members_only 零泄漏由 PASS 测试证明（非 xfail）——security_block_on:high 前置门
- [ ] `nyquist_compliant: true` set in frontmatter

**Approval:** pending
