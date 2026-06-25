---
phase: 81
title: Cursor 回流 + 前端项目工作台
status: passed
verified: 2026-06-26
requirements: [CURSOR-01, CURSOR-02, CURSOR-03, UI-01, UI-02, UI-03]
---

# Phase 81 VERIFICATION — Cursor 回流 + 前端项目工作台

**Verdict:** `passed`（代码层 5 个 Success Criteria 全部满足；真实 Cursor 端 MCP + 真实飞书在线查看为里程碑级 human_needed/deferred）。

## Success Criteria → 证据

### SC-1: MCP 分支→项目反查 + 召回（含 MCP 链 RetrievalTrace）
**PASS（code-level）**
- MCP 工具 `lookup_project_by_branch`（`POST /api/mcp/tools/lookup_project_by_branch/`）：`services/branch_parsing.parse_work_item_id_from_branch`
  解析 `feat/xxxx-m{id}-slug` → `ProjectWorkItemLink` 反查 `Project` → 单命中经 `pack_project_context` 召回。
- **MCP 链 RetrievalTrace 现已覆盖**（补齐 Phase-80 deferred 的 MCP 链）：`test_happy_single_match_recall_and_trace`
  断言 `RetrievalTrace`（payload source=`mcp_lookup_project_by_branch`，含 counts/layer_timing_ms/scores）已写入。
- 多/无命中 fail-soft（`test_parseable_no_project_fail_soft` / `test_multi_match_fail_soft_candidates` /
  `test_unparseable_branch_fail_soft`）；非成员 fail-closed 空 context（`test_non_member_failclosed_empty_context`）。
- 真实 Cursor 客户端经本地 MCP 实跑反查 = **human_needed**（需真实 Cursor + PAT）。

### SC-2: Cursor rules 模板（强制先关联本分支项目、召回再编码）
**PASS（code-level）**
- `initiatives/services/cursor_rules.build_project_cursor_rules` 生成 `.mdc`（`alwaysApply: true` + 强制
  `lookup_project_by_branch` → 召回 → 编码 → `report_project_knowledge`）；`GET /api/projects/<id>/cursor-rules/` 下发。
- 前端概览 Tab 复制/下载（`OverviewTab.vue` `copy-cursor-rules`）+ 文档化双轨。
- 证据：`test_cursor_rules.py`（`test_build_rules_contains_mandatory_flow` / `test_api_returns_rules_for_member` /
  `test_api_forbidden_for_outsider`）。

### SC-3: Cursor 沉淀上报写回（认证 + 归因 + 脱敏 + 质量门槛 → memory）
**PASS（code-level）**
- MCP 工具 `report_project_knowledge`：PAT 认证 → 归因 `request.user`（`test_attribution_records_token_user`）→
  质量门槛 `services/cursor_writeback`（`test_quality_gate_rejects_too_short` / `..._duplicate`）→ 脱敏不可绕过
  （`test_redaction_not_bypassable`）→ `MemoryService.create_draft` **pending（非 active）**（`test_member_report_creates_pending_draft`）；
  非成员 fail-closed 403（`test_non_member_forbidden`）。带 `initiated_by_user_id`；质量阈值经 `SettingKeys.CURSOR_WRITEBACK_CONFIG` 可配。

### SC-4: 前端项目工作台（列表 + 详情）
**PASS（code-level）**
- UI-01 `/projects`：Space/状态/成员/搜索筛选 + 创建（`CreateProjectModal`）+ 卡片 + 骨架/空/错（`projects-list.spec.ts` 4 测）。
- UI-02 `/projects/[id]`：6 懒加载 Tab（概览/成员/工作项/工件在线查看/记忆/关联知识·仓库·项目·MR）+ 状态机切换 + 飞书外链。
- 数据接通 Phase 77~80 REST（projects/members/work-items/artifacts/memory/graph/merge-requests/cursor-rules）。
- 真实飞书 doc/表格在线查看渲染 = **human_needed**（需真实飞书凭证；后端 fail-soft 返回 error 字段，前端已兜底渲染）。

### SC-5: 记忆 LLM 提议确认 UI + 工件类型后台管理页
**PASS（code-level）**
- `MemoryTab.vue` LLM 草稿确认：接受入库（`confirmDraft`）/ 编辑后入库 / 拒绝，二次确认（`MemoryTab.spec.ts` 4 测）。
- `/admin/artifact-types`（`requiresAdmin`）：新增/启停/删除，builtin/有实例 disabled 按钮 + tooltip（`artifact-types.spec.ts` 4 测）。

## 门禁

- 后端全量：**6421 passed**；零新增回归（39 failed = baseline 38 + 已知 flaky `test_webhook_dedup_same_sha`，单跑通过）。
- `makemigrations --check --dry-run`：**干净**（无新增 migration）。
- 前端 `vue-tsc --noEmit`：**绿**；vitest **1109 passed**（2 failed = 既有 `ProviderCredentialForm.spec.ts` PRE-EXISTING，stash 验证）。
- 新增守护测试全绿（后端 30 + 前端 12）。

## 观测合规（rule: observability-logging）

- MCP 反查召回写 `RetrievalTrace`（counts/layer-timing/score）——完成 Phase-80 deferred 的 MCP 链。
- 上报写回外部触发携 `initiated_by_user_id`（令牌用户）+ `redact_secrets_in_text` 不可绕过 + 质量门槛防噪音。
- 新增 MCP 工具经基类 `_record` 自动纳入 RequestMetric（route=`mcp:<tool>`）+ ToolCallRecord。
- 未新增 LLM 调用点（写回为 best-effort draft，无二次提炼 LLM），故无新增 `call_source`。

## Deferred（human_needed，里程碑级）

| 项 | 需要的环境 |
|----|-----------|
| 真实 Cursor 端经本地 MCP 反查 + 上报端到端 | 真实 Cursor 客户端 + Friday PAT 配置 |
| 真实飞书 doc/表格在线查看渲染 | 真实飞书应用凭证 |
