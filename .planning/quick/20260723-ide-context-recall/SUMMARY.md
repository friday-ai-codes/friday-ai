---
slug: ide-context-recall
status: complete
completed: 2026-07-23
---

# Summary: IDE 本地上下文回流适配

## 交付内容

**mcp 子模块（`@friday-ai-codes/mcp` 0.2.0 → 0.3.0，commit 7863160）**

- `src/tools.ts` 补 `reverse_lookup_requirements`（代码位置→关联需求/文档/追溯路径）+ query 类 annotation——30 个工具与服务端 `TOOL_SCHEMA_SNAPSHOT` 全量对齐。
- 修复上游遗留：0.2.0 引入项目上下文工具后测试仍断言 23 个（CI 红），断言更新至 30。
- vitest 28 passed；push 后 npm Trusted Publishing 自动发包。

**skills 子模块（`@friday-ai-codes/skills` 0.3.0 → 0.4.0，commits f5d0e70 / dd72287 / eefb741）**

- 新增 `friday-dev` skill：本地开发上下文面——「开发到哪一步了 / 继续开发 / 现在有什么问题 / PRD·feature list」按当前分支召回（lookup → 模式判定 → 深挖 read_project_doc/search_project_context/grep_project → 收工沉淀），带 HTTP 兜底契约。
- `friday` 入口决策门翻转：第 1 问改为「问的是不是项目状态」，本地分支场景不再被反向边界排除；路由表/直通模式/description 收录 friday-dev。
- Claude Code 插件新增两个通用 hooks（不写死项目、凭证读 env 或 `~/.friday/config.json`、全程 fail-soft）：
  - `UserPromptSubmit`：每条消息前按当前 git 分支调 lookup_project_by_branch 注入项目上下文，(session, branch) 级 10 分钟缓存防重复注入/拖慢；
  - `Stop`：轮次结束把改动摘要经 report_project_knowledge(branch_name=…) active 直写项目记忆，本地内容指纹去重 + 300s 最小间隔。
- 安装器 bootstrap（Cursor rule / CLAUDE.md / AGENTS.md 注入文案）决策门首条改为本地分支场景；README 5 skills + hooks 说明；plugin.json 版本漂移修复（0.2.1→0.4.0 对齐）。
- mock 服务端验证：注入 JSON 正确、缓存/去重生效、无凭证静默跳过。

**server 主仓（commits adff8e67 / 5a3f1691）**

- `lookup_project_by_branch` 第三兜底源：分支两源（work_item 解析 + ProjectBranch 绑定）无命中且传 repository_id 时，经 `RepoAssociation`（confirmed/verifying/verified）仓库反查项目——人工命名分支（`feat/login-page` 类）也能召回；分支源命中时兜底不介入；`binding_source` 扩展 `repo_association`。
- 新增 `test_mcp_package_alignment.py`：`mcp/src/tools.ts` 工具名集合 == `TOOL_SCHEMA_SNAPSHOT` 键集双向守卫（补上既有 skills 守卫拦不住的「服务端有、npm 包没有」漂移——正是本次 `reverse_lookup_requirements` 漂移的成因）。
- lookup 测试 +4（兜底单命中/多候选/proposed 不计/分支源优先）；`tests/mcp_tools/` 全量 200 passed。
- docs：`integrations/mcp.md` 30 工具全量收录（新增项目上下文环路分组），`integrations/skills.md` 5 skills + 插件 hooks + 触发示例。

## 发布

- `@friday-ai-codes/mcp@0.3.0`、`@friday-ai-codes/skills@0.4.0` 经 push 触发 GitHub Actions npm Trusted Publishing 自动发布。
- 主仓提交子模块指针 + server/docs 改动。

## 验收链（三句话）

装 Claude Code 插件（`claude plugin add friday-ai-codes/skills`）+ `mcp setup` 后，在关联分支上：

1. 「我们现在项目开发到哪一步了」→ UserPromptSubmit hook 已把 feature list/需求/记忆注入，直接按上下文回答（无 hook 场景由 friday-dev skill 路由触发 lookup）。
2. 「继续开发」→ 注入的 STATE/未完成功能点 + friday-dev 续做流程。
3. 「现在有什么问题」→ 记忆层 + search_project_context 深挖。

## 已知边界

- Codex 无 hook 能力：靠 AGENTS.md bootstrap 规则 + MCP 驱动（规则已含分支环路强制流程）。
- Cursor `beforeSubmitPrompt` 不能注入：靠 alwaysApply rule + MCP；Cursor 插件形态 session-start 可注入入口技能。
- PAT 目前无 scope（全权限）；hook 常驻场景建议后续支持只读 scope 令牌（已在评审中记录）。
