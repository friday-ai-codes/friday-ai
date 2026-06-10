---
title: Agent Skills
---

# Agent Skills

Friday 提供与 agent 无关的 [Agent Skills](https://github.com/vercel-labs/skills)，可以安装到 Claude Code、Codex、Cursor 等 70+ 种 agent 宿主，让本地 AI 助手直接驱动 Friday 的代码索引、Graph RAG 与执行能力。

Skill 仓库：[friday-ai-codes/skills](https://github.com/friday-ai-codes/skills)，npm 包：[`@friday-ai-codes/skills`](https://www.npmjs.com/package/@friday-ai-codes/skills)。

## 内置 Skill

| Skill | 用途 |
| --- | --- |
| `friday-ai` | Friday 配置、连通性检查与 workflow 路由，**从这里开始** |
| `friday-codebase-agent` | 仓库编码 workflow：发现、分析、计划、执行、分支总结、创建 MR（详见 [Codebase Agent 指南](/guide/friday-codebase-agent)） |
| `friday-feishu-agent` | 飞书工作项 → 技术方案 → 多仓执行 → PR/MR 回写 → 可检索的 LearningCase 记忆 |

## 前置条件

Skill 通过 MCP HTTP 工具调用运行中的 Friday server，只装 skill 文件是不够的，每个用户还需要：

- `FRIDAY_BASE_URL` —— Friday server 地址，如 `https://friday.example.com`；
- `FRIDAY_ACCESS_TOKEN` —— 在 Friday 个人资料页创建的访问令牌；
- 仓库 / 飞书凭据已在 server 侧配置（仅执行、建 MR 或飞书 workflow 需要）。

每次工具调用都是 `POST {FRIDAY_BASE_URL}/api/mcp/tools/{tool_name}/`，携带 `Authorization: Bearer {FRIDAY_ACCESS_TOKEN}`。

## 安装

::: code-group

```bash [skills CLI（推荐）]
# 安装全部 Friday skill（自动检测已安装的 agent）
npx skills add friday-ai-codes/skills

# 只装一个 skill 到指定 agent
npx skills add friday-ai-codes/skills --skill friday-codebase-agent -a claude-code

# 全部 skill 装到多个 agent，全局、非交互
npx skills add friday-ai-codes/skills --skill '*' -a claude-code -a codex -a cursor -g -y

# 先看列表不安装
npx skills add friday-ai-codes/skills --list
```

```bash [npm 包装器]
# 安装全部 skill 到自动检测的 agent（全局）
npx @friday-ai-codes/skills

# 装到当前项目而非全局
npx @friday-ai-codes/skills install --project

# 指定 agent / 指定 skill
npx @friday-ai-codes/skills install --agent claude-code
npx @friday-ai-codes/skills install --skill friday-feishu-agent

# 查看内置 skill
npx @friday-ai-codes/skills list
```

:::

agent 目标包括 `claude-code`、`codex`、`cursor`、`opencode`、`windsurf` 等，完整列表见 [supported agents](https://github.com/vercel-labs/skills#supported-agents)。

## 安装之后

<FlowPipeline :steps="['设置地址与令牌', 'friday-ai 校验并路由', '驱动对应 workflow skill']" />

1. 在 agent 运行的环境中设置 `FRIDAY_BASE_URL` 与 `FRIDAY_ACCESS_TOKEN`（或用 [`@friday-ai-codes/mcp init`](/integrations/mcp#初始化配置) 写入 `~/.friday/config.json`）；
2. 让 agent 先使用 `friday-ai` skill —— 它会校验连通性并路由到正确的 workflow skill；
3. 然后驱动 `friday-codebase-agent`（仓库编码）或 `friday-feishu-agent`（飞书工作项）。

也可以装完 skill 后直接在 IDE 里说「配置 Friday」，agent 会按 skill 指引向你索要地址和令牌并自动完成配置与 MCP 注册。

::: warning 执行类操作需要人工确认
`execute_coding_plan` / `execute_work_item_repo_tasks` 会真实改代码、推分支、建 MR。skill 内置了「执行前必须人工确认」的硬性规则。
:::

## 相关文档

- [MCP Server](/integrations/mcp) —— 19 个工具的注册与使用
- [Friday Codebase Agent](/guide/friday-codebase-agent) —— workflow、故障恢复与审计
