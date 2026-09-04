---
title: Agent Skills
---

# Agent Skills

Friday 提供与 agent 无关的 Agent Skills，可以安装到 Cursor、Claude Code、Codex、Gemini CLI、OpenCode 等宿主，让本地 AI 助手直接驱动 Friday 的代码索引、Graph RAG 与执行能力。

Skill 仓库：[friday-ai-codes/skills](https://github.com/friday-ai-codes/skills)，npm 包：[`@friday-ai-codes/skills`](https://www.npmjs.com/package/@friday-ai-codes/skills)。

## 内置 Skill

7 个职责清晰的 skill（全中文编写），名字全部 `friday` 开头、一个词收尾。agent 会根据任务自动触发对应的 skill；流水线阶段以小节形式收在 skill 内部，用户只要某一阶段就停在那一阶段：

| Skill | 用途 |
| --- | --- |
| `friday` | 总入口：技能路由表 + 轨迹纪律，也可直接把任意需求交给它一条龙跑完（安装器 hook / Cursor rule 自动注入） |
| `friday-dev` | 本地开发上下文面：在本地分支上问「开发到哪一步了 / 继续开发 / 现在有什么问题 / PRD·feature list·技术方案」时，按当前 git 分支召回 Friday 项目上下文；编码开工先召回、收工沉淀回写 |
| `friday-routing` | 由 feature list / PRD 出仓库路由与落点判定矩阵：目标仓库（含 monorepo 子应用）→ 落点文件 → 新增 / 改造 → 证据 → 置信度；判不准主动带选项批量问，不猜 |
| `friday-solution` | 由 feature list 出技术方案：判定功能点新增 / 改造 → 确认关联仓库 → 分仓 + 整体方案（含落点文件与伪代码）。关联仓库必须经用户确认 |
| `friday-code` | 远端已索引仓库的全部操作：找仓库 → 分析 → 计划 → 执行/MR，可分阶段也可一条龙 |
| `friday-feishu` | 飞书工作项闭环：读上下文 → 技术方案 → 多仓执行 → 结果回写，可分阶段也可一条龙 |
| `friday-memory` | Friday 的记忆层：记录 / 检索 LearningCase 经验 + 交付知识检索（相似需求、版本时间线、关联链、`as_of` 历史时点） |

更细粒度的能力（33 个工具）全部由 [MCP Server](/integrations/mcp) 提供，skill 负责编排与护栏。仓库编码链路（发现 → 分析 → 计划 → 执行）详见 [Codebase Agent 指南](/guide/friday-codebase-agent)。

## 安装顺序

**先配 MCP 连接，再装 Skills**——skill 依赖 `friday` MCP server 的工具，连接没配好装了也跑不起来：

<FlowPipeline :steps="['mcp setup 配置连接', '安装 Skills', '把任务交给 agent']" />

### 第一步 — 配置 Friday 连接

```bash
npx -y @friday-ai-codes/mcp setup
```

交互式中文向导：凭证问答（服务地址 + 访问令牌）→ 自动注册进当前项目的 agent 配置 → 连通性测速 → 能力演示。访问令牌在 Friday Web 控制台「个人资料 → 访问令牌」创建。详见 [MCP Server](/integrations/mcp)。

### 第二步 — 安装 Skills

::: code-group

```bash [交互式向导（推荐）]
npx @friday-ai-codes/skills
```

```bash [非交互（脚本 / CI）]
# 自动嗅探本机 agent，安装到当前项目
npx @friday-ai-codes/skills install -y

# 当前项目，仅 Cursor
npx @friday-ai-codes/skills install --agent cursor

# 指定 agent（可重复，仍为当前项目）
npx @friday-ai-codes/skills install --agent claude-code --agent codex

# 只有明确需要时才安装到用户全局
npx @friday-ai-codes/skills install --agent claude-code --global

# 只装技能，不注入各 agent 指令文件
npx @friday-ai-codes/skills install -y --no-bootstrap

# 查看内置 skill
npx @friday-ai-codes/skills list
```

```bash [Claude Code 插件（推荐）]
# 插件形式额外提供三样：
# 1. SessionStart hook：自动注入 friday 入口技能
# 2. UserPromptSubmit / Stop hooks：每条消息前按当前 git 分支自动召回
#    Friday 项目上下文注入对话，轮次结束把改动摘要静默沉淀回项目记忆
# 3. 捆绑的 MCP server 声明
claude plugin add friday-ai-codes/skills
```

```bash [开放 skills CLI]
# 也兼容社区 skills CLI（注意：此路径不会引导后续 MCP 配置，
# 请务必先完成第一步）
npx skills add friday-ai-codes/skills --skill '*' -g -y
```

:::

安装器自带安装能力：渐变 banner、中文向导、自动嗅探本机已装的 Cursor / Claude Code / Codex / Gemini CLI / OpenCode，默认把技能直接拷进当前项目的原生技能目录（如 `.claude/skills/`、`.cursor/skills/`、`.agents/skills/`）。只有显式传入 `--global`（或 `-g`）才写用户级目录。交互模式下装完技能还会检测 MCP 配置，未配置时直接接力拉起 `mcp setup`。

安装器还会默认把一段精简的 `friday` 入口引导注入各 agent 的原生指令文件（marker 幂等，`--no-bootstrap` 可关闭）：Cursor → `.cursor/rules/friday.mdc`（`alwaysApply`），Claude Code → `CLAUDE.md`，Codex / OpenCode → `AGENTS.md`（共用自动去重），Gemini CLI → `GEMINI.md`；全局安装则写各家的用户级文件（`~/.claude/CLAUDE.md`、`~/.codex/AGENTS.md`、`~/.gemini/GEMINI.md`、`~/.config/opencode/AGENTS.md`）。项目级注入用相对路径，文件进 git 后队友机器同样生效。

## 安装之后

直接把任务交给 agent：`friday` 入口技能会按任务类型路由——在本地分支上问项目进度 /「继续开发」走 `friday-dev`（按当前分支召回项目上下文），给一份 feature list / PRD 只要落点矩阵走 `friday-routing`，要完整技术方案走 `friday-solution`，仓库编码走 `friday-code`（可分阶段，也可一条龙到 MR），飞书工作项走 `friday-feishu`，查历史经验 / 交付知识走 `friday-memory`。

在 Friday 项目关联的分支上（分支名含 `-m{工作项id}` 段、控制台显式绑定过、或仓库已做业务关联），直接问「我们现在项目开发到哪一步了」「继续开发」「现在有什么问题」即可触发按分支召回——feature list 进度、PRD / 需求、项目记忆会作为回答与续做的事实依据；Claude Code 插件形态下这一步由 hooks 全自动完成。

环境出问题（看不到 `friday` 工具、调用 401/403）时，agent 会按 `friday` 技能的「环境未就绪」一节引导你重跑 `npx -y @friday-ai-codes/mcp setup`。

::: warning 执行类操作需要人工确认
`execute_coding_plan` / `execute_work_item_repo_tasks` 会真实改代码、推分支、建 MR。skill 内置了「执行前必须人工确认」的硬性规则。
:::

## 相关文档

- [MCP Server](/integrations/mcp) —— 30 个工具的注册与使用
- [Friday Codebase Agent](/guide/friday-codebase-agent) —— workflow、故障恢复与审计
