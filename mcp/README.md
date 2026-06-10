# @friday-ai/mcp

[Friday AI](https://github.com/friday-ai-codes/friday-ai) 的 MCP（Model Context Protocol）server。把 Friday 的代码索引、Graph RAG、编码计划与 PR / MR 工具暴露给 Cursor / Claude Code / Codex 等 AI 编码助手。

## 配置

在 Friday Web 控制台「个人资料 → 访问令牌」创建 PAT（明文只显示一次），然后：

```bash
npx -y @friday-ai/mcp init --base-url https://friday.example.com --token <你的访问令牌>
```

配置写入 `~/.friday/config.json`（权限 0600）。也可以用环境变量 `FRIDAY_BASE_URL` / `FRIDAY_ACCESS_TOKEN` 覆盖。

## 注册到 IDE

Claude Code：

```bash
claude mcp add friday -- npx -y @friday-ai/mcp
```

Cursor（`.cursor/mcp.json` 或 `~/.cursor/mcp.json`）：

```json
{
  "mcpServers": {
    "friday": { "command": "npx", "args": ["-y", "@friday-ai/mcp"] }
  }
}
```

Codex（`~/.codex/config.toml`）：

```toml
[mcp_servers.friday]
command = "npx"
args = ["-y", "@friday-ai/mcp"]
```

## 命令

| 命令 | 作用 |
| --- | --- |
| `friday-mcp`（无参数） | 启动 stdio MCP server |
| `friday-mcp init --base-url <url> --token <pat>` | 写入配置并校验连通性 |
| `friday-mcp doctor` | 检查当前配置与连通性（不回显令牌） |

## 工具集

19 个工具，对应 Friday `/api/mcp/tools/*` 端点：仓库发现（`route_repositories`）、Graph RAG 检索（`search_rag_chunks`、`find_related_chunks`）、仓库浏览（`get_repository` / `list_repository_files` / `get_repository_file`）、分析与计划（`analyze_repository` / `create_coding_plan` / `improve_coding_plan`）、执行与 MR（`execute_coding_plan` / `get_coding_execution` / `summarize_branch` / `create_merge_request`）、飞书工作项（`get_feishu_work_item_context` / `create_feishu_technical_plan` / `create_work_item_repo_tasks` / `execute_work_item_repo_tasks`）、学习案例（`create_learning_case` / `search_learning_cases`）。

配合 [friday-codebase-agent skill](https://github.com/friday-ai-codes/friday-ai/tree/main/skills/friday-codebase-agent) 使用效果最佳：

```bash
npx skills add friday-ai-codes/friday-ai --skill friday-codebase-agent
```

## License

MIT
