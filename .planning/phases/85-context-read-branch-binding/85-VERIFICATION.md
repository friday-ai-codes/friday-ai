---
status: passed
phase: 85
verified: 2026-06-26
must_haves_verified: 4
must_haves_total: 4
---

# Phase 85 Verification — 项目上下文可读 + 分支绑定

## Status: PASSED

4/4 需求（CTX-01/02, BIND-01/02）实现，4 plan（3 wave）全绿。Phase gate `tests/mcp_tools + tests/initiatives + tests/knowledge` = **689 passed**，零回归。额外修复 2 项（WS-02 stale 测试对齐 + CTX-01 DOCUMENT 召回）。

## Requirement Coverage

| Req | 实现 | 提交 |
|-----|------|------|
| CTX-01 | 项目上下文（5 文件/记忆/工件）物化进 delivery_knowledge（DOCUMENT 实体）+ 写时增量钩子 + 兜底全量重建；读侧 RAG（含 DOCUMENT 召回）/grep/file-read 三 MCP 工具，任意来源可读 | 73f4f1ce, 43a10e0c, 20a2d50a |
| CTX-02 | 沉淀进交付知识图谱（KnowledgeEntity/Edge）可索引 + 关联；search 定位上下文所属仓库/项目；新增召回写 RetrievalTrace（MCP + AI 对话两链） | 73f4f1ce, 43a10e0c |
| BIND-01 | ProjectBranch 多绑定模型（migration 0008，unique(project,repository,branch_name)，source manual/plan/coding）+ ProjectBranchService 写收口（INV-6）+ 绑定 REST + branch↔board | f724ccf1 |
| BIND-02 | lookup_project_by_branch 叠加显式多绑定反查 + 两源合并去重 + 可选 repository_id 收窄；多/无命中 fail-soft 返回候选，绝不抛/阻断编码 | beafbb11 |

## 关键决策落地确认

- 独立项目上下文：逻辑隔离（新 source_kind）复用 delivery_knowledge 向量空间 + visibility 范围召回（非复用代码 RAG collection）✓
- 写时增量物化 + 兜底定时全量重建（rebuild_project_context 命令 + apscheduler daily job）✓
- members_only 零泄漏安全门：实测非成员无法经新 MCP 工具读 members_only 上下文（真 PASS 测试，非 xfail）✓
- 新增召回写 RetrievalTrace（counts/layered-latency/score），MCP + AI 对话两链覆盖 ✓
- 写入收口 service（INV-6）；async ORM sync_to_async ✓

## 额外修复（本期权限翻转引发 + CTX-01 完整性）

- **WS-02 对齐**：v0.15.0 遗留 stale 测试 `test_non_member_failclosed_empty_context` 原用默认（现 public_org）项目断言非成员 fail-closed，与 WS-02「public_org 全员可读」冲突 → 拆为 members_only(fail-closed) + public_org(可读) 两例，未弱化真 fail-closed。
- **CTX-01 RAG 完整性**：recall 原仅 WORK_ITEM/TECH_PLAN/CODE_CHANGE → 新增 include_document_kind 开关，仅项目上下文读路径纳入 DOCUMENT 召回，权限仍由 visibility 收口、不回归全局代码检索。

## Deferred（不阻断，标注交接）

- source=coding 的 git push 自动绑定 + source=plan 流水线写入 → Phase 89（现 git webhook 仅 MR、无 push；service seam 已留）。
- 前端分支绑定交互页（后端 ProjectBranch REST 已就绪）→ 可并入 Phase 84 后续或独立轻量页。
