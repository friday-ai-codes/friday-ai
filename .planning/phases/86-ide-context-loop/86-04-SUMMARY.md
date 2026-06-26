---
phase: 86-ide-context-loop
plan: 04
type: summary
requirements: [HOOK-03]
status: done
---

# 86-04 SUMMARY —— HOOK-03 STATE 结构化回写（report_project_state MCP 工具）

## 目标达成

会话结束把新增/改动的 API 以**结构化清单**（method/path/params/status）经新 MCP 工具
`report_project_state` **直接写入** `ProjectStateApi`（source=HOOK，不经 draft），跨会话/跨角色
（前后端）即时可读，幂等 + 审计可回滚 + 逐条 fail-soft。写入收口于既有
`ProjectDocService.upsert_state_api`/`update_state_api`/`remove_state_api`（INV-6，未直写
`ProjectStateApi`）。

## 改动文件

- `server/mcp_tools/serializers.py`：新增 `ReportProjectStateRequestSerializer`
  （`project_id` UUID + `apis` ListField，宽松 DictField 子项、`allow_empty=False`、`max_length=200`）。
  **刻意宽松**：不在序列化层强校验每项字段，避免单条非法整批 400，逐条 fail-soft 在 view 内做。
- `server/mcp_tools/views.py`：
  - 新增 `_assert_project_member`（写权限成员判定，fail-closed，与 MemoryService/ProjectDocService 同口径）。
  - 新增 `ReportProjectStateView(McpToolView)`（`tool_name="report_project_state"`）：
    `_begin`(认证/归因) → `_validate` → 成员校验静默跳过 → 逐条 `upsert_state_api`
    （`source=ApiSource.HOOK`，既有行再经 `update_state_api` 更新 params/status）→ `_record`。
    全路径 + 逐条 fail-soft。
- `server/mcp_tools/urls.py`：注册 `tools/report_project_state/`（name `mcp-tool-report-project-state`）。
- `server/tests/mcp_tools/test_report_project_state.py`：新增 7 个守护测试。

## 行为契约（LOCKED 落实）

- **STATE 直写（非 draft）**：apis 清单经 service 幂等 upsert 直写 `ProjectStateApi`，`source=hook`。
- **幂等**：按 `(project, method, path)` 唯一约束，重复回写不产生重复行；既有行更新 params/status
  （`action="updated"`），新行 `action="created"`。method 规范化大写、path 去空白。
- **审计可回滚**：新建产 `project.state_api_added`；`remove_state_api` 产 `project.state_api_removed`
  且删行（撤销链完整）。归因 actor = 令牌所属用户（未映射记 system）。
- **逐条 fail-soft**：批量内缺 method/path 或非 dict 项 → 标 `skipped`/`failed`，合法项照写；
  单条 service 异常吞掉记 `report_project_state_item_failed`（warning），不影响其余。
- **静默跳过**：非成员 / 未认证 → `applied=false` + reason，HTTP 200，不写、不抛、不阻断编码。
- **全路径 fail-soft**：任何异常 → 200 + `applied=false`，绝不 5xx。
- **脱敏**：params 经 AuditService 入口强制脱敏（复用既有审计收口）。

## 观测

- 复用 `McpToolView._record`：每次调用写 `ToolCallRecord`（tool_name=report_project_state）+
  `RequestMetric`（source=mcp，labels.call_source=report_project_state）。无召回 → traces=[]。
- 逐条失败 warning 事件 `report_project_state_item_failed`（component=mcp_tools, category=caller,
  带 initiated_by_user_id）。
- 无新增 LLM 调用，不涉 §4.1 call_source 新值。

## 测试结果

- `tests/mcp_tools/test_report_project_state.py`：**7 passed**
  （结构化 upsert/跨会话可读、幂等无重复行、审计回滚链、逐条 fail-soft、非成员静默跳过、
  归因、观测 ToolCallRecord）。
- `tests/mcp_tools`：**134 passed**（含既有 schema 快照——未改 `TOOL_SCHEMA_SNAPSHOT`，
  与 86-01 同样选择不把新工具纳入快照，避免触发严格相等守护测试）。
- `tests/initiatives -k "inv6 or state_api or doc"`：**116 passed**（INV-6 grep 守护通过，
  确认未旁路直写 `ProjectStateApi`）。
- `ruff check`（4 文件）：All checks passed。

## 复用（不重造）

- `ProjectDocService.upsert_state_api`/`update_state_api`/`remove_state_api`（INV-6 + 审计可回滚，Phase 82/84）。
- `ProjectStateApi` / `ApiSource.HOOK` / `ApiStatus`（Phase 82）。
- `McpToolView` 基类（_begin/_validate/_record，PAT 认证 + 归因 + 观测）。

## 偏差 / 说明

- `update_state_api`（既有 service）对「更新既有行」只发结构化 `logger.info project_state_api_updated`
  事件、**不产 AuditEvent**（既有设计，本 plan 未改 service）。因此审计可回滚链以
  `state_api_added` → `state_api_removed` 验证（写入 + 撤销两端均有审计行，回滚闭环完整）。
- 未修改 `TOOL_SCHEMA_SNAPSHOT` 与 `test_schema_snapshot.py`（plan files_modified 未列；
  且无 url↔snapshot 完整性守护，沿用 86-01 同样取舍）。

## Deferred / Blockers

- 无 blocker。STATE 回写读侧渲染（STATE 文件「已完成 API 清单」段派生）由既有
  doc 渲染链覆盖，不在本 plan 范围。
