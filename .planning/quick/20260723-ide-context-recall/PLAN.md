---
slug: ide-context-recall
created: 2026-07-23
type: quick
---

# Quick Task: IDE 本地上下文回流适配（Claude Code 优先 / Codex / Cursor）

## 目标

接入 Friday Skills + MCP 后，用户在本地 feat 分支直接问「我们现在项目开发到哪一步了」「继续开发」「现在有什么问题」，coding agent 能自动触发 Friday 的分支→项目召回（feature list / PRD / STATE / MEMORY / 关联需求），继续上次开发；收工自动沉淀回写。

## 背景（评审结论）

服务端能力已在 v0.16.0/v0.17.0 落地（`lookup_project_by_branch` + `pack_project_context` + `search_project_context`/`grep_project`/`read_project_doc` + `report_project_knowledge`/`report_project_state`），但客户端分发面断裂：

1. mcp npm 包（上游 0.2.0 已补 6 个项目上下文工具）仍缺 `reverse_lookup_requirements`，且测试仍断言 23 个工具（上游 CI 红）。
2. skills 包无「本地开发上下文面」skill；`friday` 入口决策门把本地工作区一刀切排除。
3. Claude Code 插件形态无 UserPromptSubmit / Stop hooks（服务端 per-project 资产版无法规模化，需通用版）。
4. 无「服务端 snapshot ↔ mcp/tools.ts」对齐守卫（现有守卫只查 SKILL.md ⊆ snapshot）。
5. `lookup_project_by_branch` 分支两源（work_item 解析 + ProjectBranch 绑定）无命中时没有 repo→project 兜底，人工命名分支召回率低。

## 任务清单

1. **mcp 子模块（0.2.0 → 0.3.0）**：补 `reverse_lookup_requirements` 工具定义 + annotation；测试 23→30 修复；push 触发 npm Trusted Publishing 自动发包。
2. **skills 子模块（0.3.0 → 0.4.0）**：
   - 新增 `friday-dev` skill（本地分支开发上下文面：召回→回答/续做→沉淀）+ http-fallback reference；
   - `friday` 入口：决策门加「本地分支关联 Friday 项目」命中 + 路由表加 friday-dev + description 更新；
   - Claude Code 插件 hooks：`UserPromptSubmit`（动态分支→lookup→注入，session+branch 级缓存防重复注入）+ `Stop`（改动摘要→report_project_knowledge active 写回），通用版不写死项目，凭证读 env / `~/.friday/config.json`，全程 fail-soft；
   - session-start 提醒文案、installer bootstrap、README 同步。
3. **server 主仓**：
   - 新增守卫测试：`mcp/src/tools.ts` 工具名集合 == `TOOL_SCHEMA_SNAPSHOT` 键集；
   - `lookup_project_by_branch` 第三兜底源：`RepoAssociation`（confirmed/verifying/verified）按 repository_id 反查项目（唯一命中 matched，多命中 candidates）+ 测试；
   - docs/integrations/mcp.md（30 工具 + 本地回流）、skills.md（5 skills + hooks）更新。
4. **发布**：两个子模块 bump version + push（CI 自动发 npm）；主仓提交子模块指针 + server/docs 改动。

## 验收

- `我们现在项目开发到哪一步了` / `继续开发` / `现在有什么问题` 三句话在 Claude Code（装插件）下的触发链完整：hook 注入或 skill 路由 → lookup → context 召回。
- mcp 包 30 工具与服务端对齐且有守卫；skills 引用的工具全部可经 stdio MCP 调用。
- 服务端测试全绿。
