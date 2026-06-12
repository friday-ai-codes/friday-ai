---
title: Friday Codebase Agent
---
# Friday Codebase Agent

Friday Codebase Agent 指的是 [`friday-code` Agent Skill](/integrations/skills)，配合 `@friday-ai-codes/mcp` MCP server，让 Cursor / Claude Code / Codex 等本地 AI 编码助手直接使用 Friday 的代码索引、Graph RAG、编码计划、远程执行和 MR 创建能力。

接入只需要三步，之后就能在 IDE 里完整跑通编码 workflow：

<FlowPipeline :steps="['创建访问令牌', 'mcp setup 配置连接', '安装 Skill', 'IDE 里直接使用']" />

## 配置连接

1. 登录 Friday Web 控制台 → 右上角头像 → 个人资料 → **访问令牌** → 创建令牌（明文只显示一次，立即复制）。
2. 运行交互式配置向导（凭证问答 → 自动注册进 Cursor / Claude Code / Codex → 连通性测速 → 能力演示）：

```bash
npx -y @friday-ai-codes/mcp setup
```

配置保存在 `~/.friday/config.json`（权限 0600），也可以用环境变量 `FRIDAY_BASE_URL` / `FRIDAY_ACCESS_TOKEN` 覆盖。脚本场景用命令式 `init --base-url <地址> --token <令牌>`；诊断用 `doctor`。手动注册 MCP 的等价配置见 [MCP Server](/integrations/mcp#注册到-ide)。

内网无法访问 npm registry 时，可从源码构建后把 MCP 配置指向 `mcp/dist/cli.js`。

## 安装 Skill

```bash
npx @friday-ai-codes/skills
```

交互式中文向导：自动嗅探本机 agent（Claude Code、Cursor、Codex 等均支持），把全部 4 个 Friday skill 装进各 agent 原生技能目录。更多安装方式（指定 agent、装到项目、Claude Code 插件形式）见 [Agent Skills](/integrations/skills#安装顺序)。

## Workflows

`friday-code` 内部按阶段分节，agent 按用户意图自动决定跑到哪个阶段；给出完整编码需求时会一条龙跑到 MR：

| 阶段 | 用途 |
| --- | --- |
| 找仓库 | 把需求路由到候选仓库并检查索引健康度。 |
| 分析 | 用 Graph RAG 证据做架构 / 风险 / 调用链分析。 |
| 计划 | 从需求与代码证据生成结构化编码计划，并支持按反馈修订版本。 |
| 执行与 MR | 执行已确认的计划、轮询状态、总结分支、创建 MR。 |
| 一条龙 | 编码需求端到端：发现 → 分析 → 计划 → 确认 → 执行 → MR。 |

飞书工作项链路（工作项 → 技术方案 → 多仓执行 → 回写）由 `friday-feishu` skill 承担，见 [Agent Skills](/integrations/skills#内置-skill)。

`execute_coding_plan` / `execute_work_item_repo_tasks` 会真实改代码、推分支、建 MR，skill 内置了"执行前必须人工确认"的硬性规则。

## 工具集

23 个工具，对应 `POST {FRIDAY_BASE_URL}/api/mcp/tools/{tool_name}/`：

- 读取类：`route_repositories`、`search_rag_chunks`、`grep_repository`、`get_repository`、`list_repository_files`、`get_repository_file`、`find_related_chunks`
- 计划类：`analyze_repository`、`create_coding_plan`、`improve_coding_plan`
- 执行与 MR：`execute_coding_plan`、`get_coding_execution`、`summarize_branch`、`create_merge_request`
- 飞书工作项与学习：`get_feishu_work_item_context`、`create_feishu_technical_plan`、`create_work_item_repo_tasks`、`execute_work_item_repo_tasks`、`create_learning_case`、`search_learning_cases`
- 交付知识：`search_delivery_knowledge`、`get_entity_timeline`、`get_related_entities`

MCP 不可用时可降级 HTTP 直调：

```text
POST {FRIDAY_BASE_URL}/api/mcp/tools/{tool_name}/
Authorization: Bearer {FRIDAY_ACCESS_TOKEN}
Content-Type: application/json
```

多步 Skill workflow 需保留首个响应的 `run_id` 并在后续调用带上：

```text
X-Friday-Run-ID: {run_id}
X-Friday-Skill-Step: full_auto.plan
```

这样整条 workflow 会在 Interaction Ledger 中聚合为同一条轨迹（MCP 模式由 server 自动处理 run_id 透传）。

## 故障恢复

- 仓库路由不明确：用更具体的需求描述重跑 `discover`。
- 仓库未索引：先在 Friday Web 仓库页建立索引，再做 Graph RAG / 计划 / 执行。
- 执行失败：用 `get_coding_execution` 查看 `runner_logs`、`last_diff` 与 `recovery_state`。
- 执行 `partial`：代码已推送但后续步骤失败，优先重试 `summarize_branch` / `create_merge_request`，不要重跑代码。
- MR 创建失败：分支、目标分支、commit sha 与 `mr_error` 均已持久化，修复平台权限或既有 MR 状态后重试。
- 401 / 403：令牌失效，重建 PAT 后重跑 `npx -y @friday-ai-codes/mcp setup`。

## 审计

用最终 `run_id` 可以查到 `InteractionRun`、`InteractionEvent`、`ToolCallRecord`、`RetrievalTrace`、模型用量、执行轨迹与 MR 结果记录。workflow 应呈现 `skill_step` 事件以及同一 `run_id` 下的全部 MCP 工具调用。

## 下一步

<LinkCards>
  <LinkCard icon="🛠️" title="Agent Skills" desc="全部内置 Skill 与安装方式" link="/integrations/skills" />
  <LinkCard icon="🔌" title="MCP Server" desc="23 个工具的注册与 HTTP 直调" link="/integrations/mcp" />
  <LinkCard icon="🧠" title="代码智能层" desc="Graph RAG 检索背后的实现" link="/internals/code-intelligence" />
</LinkCards>
