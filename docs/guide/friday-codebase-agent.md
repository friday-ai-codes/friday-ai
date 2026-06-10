---
title: Friday Codebase Agent
---
# Friday Codebase Agent

Friday Codebase Agent 指的是一组 [Agent Skills](/integrations/skills)（`friday-discover` / `friday-analyze` / `friday-plan` / `friday-execute` / `friday-auto`），配合 `@friday-ai-codes/mcp` MCP server，让 Cursor / Claude Code / Codex 等本地 AI 编码助手直接使用 Friday 的代码索引、Graph RAG、编码计划、远程执行和 MR 创建能力。

接入只需要三步，之后就能在 IDE 里完整跑通编码 workflow：

<FlowPipeline :steps="['安装 Skill', '配置访问令牌', '注册 MCP server', 'IDE 里直接使用']" />

## 安装

```bash
npx @friday-ai-codes/skills
```

这条命令安装全部 12 个 Friday skill 到自动检测的 agent（Claude Code、Cursor、Codex 等均支持）。更多安装方式（指定 agent、装到项目、Claude Code 插件形式）见 [Agent Skills](/integrations/skills#安装)。

## 配置令牌

1. 登录 Friday Web 控制台 → 右上角头像 → 个人资料 → **访问令牌** → 创建令牌（明文只显示一次，立即复制）。
2. 写入本地配置并校验连通性：

```bash
npx -y @friday-ai-codes/mcp init --base-url https://friday.example.com --token <你的访问令牌>
```

配置保存在 `~/.friday/config.json`（权限 0600），也可以用环境变量 `FRIDAY_BASE_URL` / `FRIDAY_ACCESS_TOKEN` 覆盖。检查配置状态：

```bash
npx -y @friday-ai-codes/mcp doctor
```

实际上这一步也可以跳过手动操作——装好 skill 后直接在 IDE 里说"配置 Friday"，agent 会按 skill 指引向你索要地址和令牌并完成配置。

## 注册 MCP server

| 宿主 | 操作 |
| --- | --- |
| Claude Code | `claude mcp add friday -- npx -y @friday-ai-codes/mcp` |
| Cursor | `.cursor/mcp.json` 加入 `"friday": {"command": "npx", "args": ["-y", "@friday-ai-codes/mcp"]}` |
| Codex | `~/.codex/config.toml` 加入 `[mcp_servers.friday]`，`command = "npx"`，`args = ["-y", "@friday-ai-codes/mcp"]` |

内网无法访问 npm registry 时，可从源码构建后把 MCP 配置指向 `mcp/dist/cli.js`（详见 skill 内的 `references/setup.md`）。

## Workflows

每个阶段对应一个 skill，agent 会按任务自动触发；也可以用 `friday-auto` 一次跑完整条链路：

| Skill | 用途 |
| --- | --- |
| `friday-discover` | 把需求路由到候选仓库并检查索引健康度。 |
| `friday-analyze` | 用 Graph RAG 证据做架构 / 风险 / 调用链分析。 |
| `friday-plan` | 从需求与代码证据生成结构化编码计划，并支持按反馈修订版本。 |
| `friday-execute` | 执行已确认的计划、轮询状态、总结分支、创建 MR。 |
| `friday-auto` | 编码需求端到端（full_auto）：发现 → 分析 → 计划 → 确认 → 执行 → MR。 |

飞书工作项链路（工作项 → 技术方案 → 多仓执行 → 回写）由 `friday-feishu-*` 系列 skill 承担，见 [Agent Skills](/integrations/skills#内置-skill)。

`execute_coding_plan` / `execute_work_item_repo_tasks` 会真实改代码、推分支、建 MR，skill 内置了"执行前必须人工确认"的硬性规则。

## 工具集

19 个工具，对应 `POST {FRIDAY_BASE_URL}/api/mcp/tools/{tool_name}/`：

- 读取类：`route_repositories`、`search_rag_chunks`、`get_repository`、`list_repository_files`、`get_repository_file`、`find_related_chunks`
- 计划类：`analyze_repository`、`create_coding_plan`、`improve_coding_plan`
- 执行与 MR：`execute_coding_plan`、`get_coding_execution`、`summarize_branch`、`create_merge_request`
- 飞书工作项与学习：`get_feishu_work_item_context`、`create_feishu_technical_plan`、`create_work_item_repo_tasks`、`execute_work_item_repo_tasks`、`create_learning_case`、`search_learning_cases`

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
- 401 / 403：令牌失效，重建 PAT 后重跑 `npx -y @friday-ai-codes/mcp init`。

## 审计

用最终 `run_id` 可以查到 `InteractionRun`、`InteractionEvent`、`ToolCallRecord`、`RetrievalTrace`、模型用量、执行轨迹与 MR 结果记录。workflow 应呈现 `skill_step` 事件以及同一 `run_id` 下的全部 MCP 工具调用。

## 下一步

<LinkCards>
  <LinkCard icon="🛠️" title="Agent Skills" desc="全部内置 Skill 与安装方式" link="/integrations/skills" />
  <LinkCard icon="🔌" title="MCP Server" desc="19 个工具的注册与 HTTP 直调" link="/integrations/mcp" />
  <LinkCard icon="🧠" title="代码智能层" desc="Graph RAG 检索背后的实现" link="/internals/code-intelligence" />
</LinkCards>
