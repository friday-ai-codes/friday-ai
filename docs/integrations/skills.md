---
title: Agent Skills
---

# Agent Skills

Friday 提供与 agent 无关的 [Agent Skills](https://github.com/vercel-labs/skills)，可以安装到 Claude Code、Codex、Cursor 等 70+ 种 agent 宿主，让本地 AI 助手直接驱动 Friday 的代码索引、Graph RAG 与执行能力。

Skill 仓库：[friday-ai-codes/skills](https://github.com/friday-ai-codes/skills)，npm 包：[`@friday-ai-codes/skills`](https://www.npmjs.com/package/@friday-ai-codes/skills)。

## 内置 Skill

5 个按用户意图划分的 skill（全中文编写），agent 会根据任务自动触发对应的 skill；流水线阶段以小节形式收在 skill 内部，用户只要某一阶段就停在那一阶段：

| Skill | 用途 |
| --- | --- |
| `using-friday` | 元 skill：skill 路由表与轨迹纪律（Claude Code 插件 hook / Cursor rule 自动注入） |
| `friday-setup` | 安装 / 配置 / 修复 Friday 接入：`doctor` → `init` → `register` → 验证 |
| `friday-code` | 远端已索引仓库的全部操作：找仓库 → 分析 → 计划 → 执行/MR，可分阶段也可一条龙 |
| `friday-feishu` | 飞书工作项闭环：读上下文 → 技术方案 → 多仓执行 → 结果回写，可分阶段也可一条龙 |
| `friday-learn` | 记录 / 检索 LearningCase 记忆 |

仓库编码链路（发现 → 分析 → 计划 → 执行）详见 [Codebase Agent 指南](/guide/friday-codebase-agent)。

## 前置条件

Skill 通过 MCP HTTP 工具调用运行中的 Friday server，只装 skill 文件是不够的，每个用户还需要：

- `FRIDAY_BASE_URL` —— Friday server 地址，如 `https://friday.example.com`；
- `FRIDAY_ACCESS_TOKEN` —— 在 Friday 个人资料页创建的访问令牌；
- 仓库 / 飞书凭据已在 server 侧配置（仅执行、建 MR 或飞书 workflow 需要）。

每次工具调用都是 `POST {FRIDAY_BASE_URL}/api/mcp/tools/{tool_name}/`，携带 `Authorization: Bearer {FRIDAY_ACCESS_TOKEN}`。

## 安装

::: code-group

```bash [npm 包装器（推荐）]
# 安装全部 skill 到自动检测的 agent（全局、非交互）
npx @friday-ai-codes/skills

# 装到当前项目而非全局
npx @friday-ai-codes/skills install --project

# 指定 agent
npx @friday-ai-codes/skills install --agent claude-code

# Codex：附带 AGENTS.md bootstrap（Codex 无 hook 机制）
npx @friday-ai-codes/skills install --agent codex --codex-bootstrap

# 查看内置 skill
npx @friday-ai-codes/skills list
```

```bash [skills CLI]
# 安装全部 Friday skill（自动检测已安装的 agent）
npx skills add friday-ai-codes/skills --skill '*' -g -y

# 只装一个 skill 到指定 agent
npx skills add friday-ai-codes/skills --skill friday-code -a claude-code

# 先看列表不安装
npx skills add friday-ai-codes/skills --list
```

```bash [Claude Code 插件]
# 插件形式额外提供 SessionStart hook（自动注入 using-friday）
# 和捆绑的 MCP server 声明
claude plugin add friday-ai-codes/skills
```

:::

agent 目标包括 `claude-code`、`codex`、`cursor`、`opencode`、`windsurf` 等，完整列表见 [supported agents](https://github.com/vercel-labs/skills#supported-agents)。

## 安装之后

<FlowPipeline :steps="['friday-setup 配置接入', 'using-friday 路由任务', '驱动对应阶段 skill']" />

1. 让 agent「配置 Friday」—— `friday-setup` skill 会引导完成 `npx -y @friday-ai-codes/mcp init`（写入 `~/.friday/config.json`）与 MCP server 注册，也可以手动设置 `FRIDAY_BASE_URL` 与 `FRIDAY_ACCESS_TOKEN`（见 [`@friday-ai-codes/mcp init`](/integrations/mcp#初始化配置)）；
2. 之后直接把任务交给 agent：`using-friday` 元 skill 会按任务类型路由到对应的 skill；
3. 仓库编码走 `friday-code`（可分阶段，也可一条龙到 MR），飞书工作项走 `friday-feishu`。

项目级安装且目标包含 Cursor 时，安装器会额外写入 `.cursor/rules/using-friday.mdc`（`alwaysApply`），确保每次 Cursor 会话都被引导到 `using-friday`——与 Claude Code 的 SessionStart hook 等效。

也可以装完 skill 后直接在 IDE 里说「配置 Friday」，agent 会按 skill 指引向你索要地址和令牌并自动完成配置与 MCP 注册。

::: warning 执行类操作需要人工确认
`execute_coding_plan` / `execute_work_item_repo_tasks` 会真实改代码、推分支、建 MR。skill 内置了「执行前必须人工确认」的硬性规则。
:::

## 相关文档

- [MCP Server](/integrations/mcp) —— 19 个工具的注册与使用
- [Friday Codebase Agent](/guide/friday-codebase-agent) —— workflow、故障恢复与审计
