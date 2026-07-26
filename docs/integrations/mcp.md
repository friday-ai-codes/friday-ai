---
title: MCP Server
---

# MCP Server

[`@friday-ai-codes/mcp`](https://www.npmjs.com/package/@friday-ai-codes/mcp) 是 Friday 的 MCP（Model Context Protocol）server，把 Friday 的代码索引、Graph RAG、编码计划与 PR / MR 工具暴露给 Cursor / Claude Code / Codex 等 AI 编码助手。

源码位于仓库 [`mcp/`](https://github.com/friday-ai-codes/friday-ai/tree/main/mcp) 目录（TypeScript，stdio 传输）。

接入流程：

<FlowPipeline :steps="['创建访问令牌', 'setup 交互式配置', '注册到 IDE', '连通性测速', '调用 33 个工具']" />

## 一条命令配好（推荐）

先在 Friday Web 控制台「个人资料 → 访问令牌」创建 PAT（明文只显示一次），然后：

```bash
npx -y @friday-ai-codes/mcp setup
```

交互式中文向导会依次完成：凭证问答（服务地址 + 令牌）→ 自动注册进 Cursor / Claude Code / Codex → 连通性测速（延迟毫秒数高亮）→ 能力演示（随机介绍一个已索引仓库）。

## 初始化配置（命令式）

脚本 / CI 场景用命令式 `init`：

```bash
npx -y @friday-ai-codes/mcp init --base-url https://friday.example.com --token <你的访问令牌>
```

不带参数在终端运行 `init` 同样会进入交互式问答。配置写入 `~/.friday/config.json`（权限 `0600`），也可以用环境变量 `FRIDAY_BASE_URL` / `FRIDAY_ACCESS_TOKEN` 覆盖。

检查配置、注册状态与连通性（含延迟测速，不回显令牌）：

```bash
npx -y @friday-ai-codes/mcp doctor
```

## 注册到 IDE

`setup` 已包含注册；也可以单独运行（自动探测本机 agent，幂等）：

```bash
npx -y @friday-ai-codes/mcp register
```

手动注册的等价配置：

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
| `friday-mcp setup` | 交互式中文向导：凭证 → 注册 → 测速 → 能力演示 |
| `friday-mcp init` | 写入配置（带 `--base-url` / `--token` 为命令式，否则交互式问答） |
| `friday-mcp register [--agent <name>] [--project]` | 幂等注册进 Cursor / Claude Code / Codex |
| `friday-mcp doctor` | 检查配置、注册状态与连通性测速（不回显令牌） |

## 工具集（33 个）

每个工具对应 Friday 的 `POST {FRIDAY_BASE_URL}/api/mcp/tools/{tool_name}/` 端点：

| 分类 | 工具 | 用途 |
| --- | --- | --- |
| 仓库发现 | `route_repositories` | 把需求路由到候选仓库并检查索引健康度 |
| Graph RAG 检索 | `search_rag_chunks` | 混合检索代码 chunk（语义 + 关键词 + 图谱扩散） |
| | `find_related_chunks` | 沿代码图谱找相关 chunk |
| | `reverse_lookup_requirements` | 代码位置反查关联需求 / 文档 / 追溯路径（「这段代码是为哪个需求改的」） |
| 精确检索 | `grep_repository` | 本地 git 镜像快照上的 grep 语义全量检索（ripgrep 优先，回退 git grep）：字面量 / 正则 / glob 过滤、可配置上下文行、`content` / `files_only` / `count` 输出模式、token 预算；默认单仓，`repository_ids` / `all_repositories` 显式跨仓，「穷举所有出现位置」类问题用这个 |
| 仓库浏览 | `get_repository` | 仓库元信息与索引状态 |
| | `list_repository_files` | 列出仓库文件 |
| | `get_repository_file` | 读取文件内容（优先 git 镜像全量读取，回退索引 chunk） |
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
| 交付知识 | `search_delivery_knowledge` | 检索相似历史需求 / 方案 / 代码变更（支持 `as_of` 历史时点） |
| | `get_entity_timeline` | 知识实体的版本迭代时间线 |
| | `get_related_entities` | 需求 → 方案 → MR 关联链图遍历 |
| 项目上下文环路 | `lookup_project_by_branch` | 用当前 git 分支名反查所属项目并召回需求 / 工件 / 记忆（三源：分支名 work_item 解析 → `ProjectBranch` 显式绑定 → 仓库关联兜底） |
| | `search_project_context` | 项目交付上下文语义召回 |
| | `grep_project` | 项目上下文关键词精确匹配 |
| | `read_project_doc` | 读取项目工作区文档（MEMORY / STATE / 里程碑 / 调研 / 预检） |
| | `report_project_knowledge` | 把会话沉淀写回项目记忆（按 `branch_name` 自动定位项目，服务端质量门槛 + 脱敏 + 审计兜底） |
| | `report_project_state` | 把新增 / 改动 API 结构化清单回写项目 STATE |
| feature list 技术方案 | `create_feature_tech_plan` | 由 feature list 发起技术方案：判定功能点新增 / 改造 + 给出关联仓库建议，返回**待确认项**（不返回方案） |
| | `confirm_feature_tech_plan` | 提交用户对关联仓库与分类的确认，继续编排 |
| | `get_feature_tech_plan` | 查询状态并推进编排；`status=completed` 时 `markdown` 为完整方案（整体 + 分仓 + 落点 + 伪代码） |

::: warning feature list 技术方案是两段式的
`create_feature_tech_plan` **单次调用拿不到方案**——它只跑到「强制确认」就停下，必须把返回的
`questions` 给用户过目、拿到答复后调 `confirm_feature_tech_plan` 才会继续。即便仓库路由是高置信度
也一定会问一次，这是产品约束而非缺陷。

调研阶段是异步的：`confirm` 可能返回 `status="researching"`，此时需轮询 `get_feature_tech_plan`
直到 `completed`。该工具每次调用都会推进一步编排，不调它方案不会往前走。
:::

每个工具都带 MCP 标准 `annotations`（中文 `title` 按「阶段 · 动作」分组，外加 `readOnlyHint` / `idempotentHint` / `openWorldHint` 行为提示），agent 可据此判断工具是否只读、是否触达外部系统。

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

单独注册 MCP 已经可用，但配合 [Friday Agent Skills](/integrations/skills) 使用效果最佳 —— skill 提供了 workflow 编排、人工确认规则与故障恢复指引：

```bash
npx @friday-ai-codes/skills
```
