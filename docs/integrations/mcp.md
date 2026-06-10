---
title: MCP Server
---

# MCP Server

[`@friday-ai-codes/mcp`](https://www.npmjs.com/package/@friday-ai-codes/mcp) 是 Friday 的 MCP（Model Context Protocol）server，把 Friday 的代码索引、Graph RAG、编码计划与 PR / MR 工具暴露给 Cursor / Claude Code / Codex 等 AI 编码助手。

源码位于仓库 [`mcp/`](https://github.com/friday-ai-codes/friday-ai/tree/main/mcp) 目录（TypeScript，stdio 传输）。

## 初始化配置

先在 Friday Web 控制台「个人资料 → 访问令牌」创建 PAT（明文只显示一次），然后：

```bash
npx -y @friday-ai-codes/mcp init --base-url https://friday.example.com --token <你的访问令牌>
```

配置写入 `~/.friday/config.json`（权限 `0600`），也可以用环境变量 `FRIDAY_BASE_URL` / `FRIDAY_ACCESS_TOKEN` 覆盖。

检查配置与连通性（不回显令牌）：

```bash
npx -y @friday-ai-codes/mcp doctor
```

## 注册到 IDE

::: code-group

```bash [Claude Code]
claude mcp add friday -- npx -y @friday-ai-codes/mcp
```

```json [Cursor]
// .cursor/mcp.json 或 ~/.cursor/mcp.json
{
  "mcpServers": {
    "friday": { "command": "npx", "args": ["-y", "@friday-ai-codes/mcp"] }
  }
}
```

```toml [Codex]
# ~/.codex/config.toml
[mcp_servers.friday]
command = "npx"
args = ["-y", "@friday-ai-codes/mcp"]
```

:::

内网无法访问 npm registry 时，可从源码构建后把 MCP 配置指向 `mcp/dist/cli.js`。

## CLI 命令

| 命令 | 作用 |
| --- | --- |
| `friday-mcp`（无参数） | 启动 stdio MCP server |
| `friday-mcp init --base-url <url> --token <pat>` | 写入配置并校验连通性 |
| `friday-mcp doctor` | 检查当前配置与连通性（不回显令牌） |

## 工具集（19 个）

每个工具对应 Friday 的 `POST {FRIDAY_BASE_URL}/api/mcp/tools/{tool_name}/` 端点：

| 分类 | 工具 | 用途 |
| --- | --- | --- |
| 仓库发现 | `route_repositories` | 把需求路由到候选仓库并检查索引健康度 |
| Graph RAG 检索 | `search_rag_chunks` | 混合检索代码 chunk（语义 + 关键词 + 图谱扩散） |
| | `find_related_chunks` | 沿代码图谱找相关 chunk |
| 仓库浏览 | `get_repository` | 仓库元信息与索引状态 |
| | `list_repository_files` | 列出仓库文件 |
| | `get_repository_file` | 读取文件内容 |
| 分析与计划 | `analyze_repository` | 基于 Graph RAG 证据的架构 / 风险 / 调用链分析 |
| | `create_coding_plan` | 从需求与代码证据生成结构化编码计划 |
| | `improve_coding_plan` | 按反馈修订计划生成新版本 |
| 执行与 MR | `execute_coding_plan` | 执行已确认的计划（真实改代码） |
| | `get_coding_execution` | 查询执行状态、`runner_logs`、`last_diff`、`recovery_state` |
| | `summarize_branch` | 生成分支变更摘要 |
| | `create_merge_request` | 创建 PR / MR |
| 飞书工作项 | `get_feishu_work_item_context` | 聚合工作项、关系、评论和文档 |
| | `create_feishu_technical_plan` | 结合代码证据生成并写回技术方案 |
| | `create_work_item_repo_tasks` | 拆解工作项为仓库任务矩阵 |
| | `execute_work_item_repo_tasks` | 执行仓库任务矩阵 |
| 学习案例 | `create_learning_case` | 沉淀可检索的执行经验 |
| | `search_learning_cases` | 检索历史案例 |

此外，代码智能层还提供 `find_api_handler` / `find_api_callers` / `list_endpoints` 等图谱查询工具，见[代码智能层](/internals/code-intelligence#mcp-tools-agent-使用)。

## HTTP 直调（降级方案）

MCP 不可用时可以直接调 HTTP：

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

这样整条 workflow 会在 Interaction Ledger 中聚合为同一条审计轨迹（MCP 模式由 server 自动处理 `run_id` 透传）。

## 配合 Skill 使用

单独注册 MCP 已经可用，但配合 [friday-codebase-agent skill](/guide/friday-codebase-agent) 使用效果最佳 —— skill 提供了 workflow 编排、人工确认规则与故障恢复指引：

```bash
npx skills add friday-ai-codes/skills --skill friday-codebase-agent
```
