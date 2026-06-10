---
name: friday-codebase-agent
description: 通过 Friday AI 平台的代码索引、Graph RAG 与远程执行工具操作已索引仓库。当用户提到 Friday、friday-mcp，或需要跨仓代码分析、仓库发现（"哪个仓库和这个需求相关"）、调用链与影响面分析、生成或修订编码计划、远程执行编码任务、自动创建 PR/MR、读取飞书工作项上下文并生成技术方案时使用。也在用户首次要求"配置 Friday""连接 Friday"时使用（本 skill 含完整的令牌配置与 MCP 注册流程）。不适用于：与 Friday 实例无关的本地纯文件编辑、当前工作区内的常规编码任务。
---

# Friday Codebase Agent

Friday 是部署在用户团队内的 AI 开发自动化平台。它持有已索引仓库的代码图谱与 Graph RAG，能远程执行编码计划并创建 PR / MR。本 skill 教你通过 `friday` MCP server（或降级 HTTP）使用这些能力。

## 第零步：每次触发先做前置检查

按顺序检查，命中即停：

1. **MCP 工具可用？** 工具列表里存在 `mcp__friday__*`（如 `mcp__friday__route_repositories`）→ 配置就绪，直接进入下方「Workflow 路由」。
2. **环境变量可用？** `FRIDAY_BASE_URL` 与 `FRIDAY_ACCESS_TOKEN` 都非空 → 配置存在但 MCP 未注册，执行「首次配置」第 3 步注册 MCP，或直接用「降级 HTTP 调用」。
3. **配置文件可用？** `~/.friday/config.json` 存在且含 `baseUrl` / `accessToken` → 同上，只缺 MCP 注册。
4. **都没有** → 进入「首次配置」完整流程。

## 首次配置（缺 key 时引导用户）

### 1. 向用户索要两样东西

- **Friday 实例地址**：内网部署的 Web 地址，如 `http://10.0.0.5:10240` 或 `https://friday.example.com`
- **访问令牌（PAT）**：告诉用户创建路径——*登录 Friday Web 控制台 → 右上角头像 → 个人资料 → 「访问令牌」→ 创建令牌*。提醒：**明文只显示一次**，创建后立即复制。

不要猜测地址；不要让用户把令牌粘贴到代码或提交历史里。

### 2. 写入配置并验证

```bash
npx -y @friday-ai/mcp init --base-url <实例地址> --token <访问令牌>
```

该命令把配置写入 `~/.friday/config.json`（权限 0600）并调 `/health` 验证连通。若提示连通性异常，让用户确认内网 / VPN / 端口可达后重试。

### 3. 注册 MCP server（按宿主选择）

| 宿主 | 操作 |
| --- | --- |
| Claude Code | 运行 `claude mcp add friday -- npx -y @friday-ai/mcp` |
| Cursor | 在项目 `.cursor/mcp.json`（或全局 `~/.cursor/mcp.json`）的 `mcpServers` 里加入 `"friday": {"command": "npx", "args": ["-y", "@friday-ai/mcp"]}` |
| Codex | 在 `~/.codex/config.toml` 加入 `[mcp_servers.friday]` 段，`command = "npx"`，`args = ["-y", "@friday-ai/mcp"]` |

注册后提示用户重载窗口 / 重启会话使 MCP 生效。完整排障见 [references/setup.md](references/setup.md)。

## Workflow 路由

根据用户意图选择 workflow，未明确时从 discover 开始：

| 用户在问什么 | Workflow | 工具调用顺序 |
| --- | --- | --- |
| "这个需求和哪个仓库相关？" | **discover** | `route_repositories` → `get_repository` |
| "X 的调用链 / 影响面 / 现状是什么？" | **analyze** | `search_rag_chunks` → `find_related_chunks` → 必要时 `get_repository_file` / `analyze_repository` |
| "给这个需求出个改造方案" | **plan** | discover → `search_rag_chunks` → `create_coding_plan` → 呈现给用户 |
| "按我的反馈改方案" | **improve** | `improve_coding_plan`（带 plan_id 与反馈原文） |
| "执行这个方案 / 提个 MR" | **execute** | `execute_coding_plan` → 轮询 `get_coding_execution` → `summarize_branch` → `create_merge_request` |
| "从这个飞书需求一路跑到 MR" | **full_auto** | `get_feishu_work_item_context` → `search_learning_cases` → `create_feishu_technical_plan` → `create_work_item_repo_tasks` → 确认后 `execute_work_item_repo_tasks` |

每个 workflow 的逐步细节、参数选择与示例对话见 [references/workflows.md](references/workflows.md)；全部 19 个工具的参数与返回结构见 [references/tools.md](references/tools.md)。

## 硬性规则

1. **执行前必须人工确认。** `execute_coding_plan` 与 `execute_work_item_repo_tasks` 会真实改代码、推分支、建 MR。调用前必须把计划内容（步骤、改动文件、风险）呈现给用户并获得明确同意。这是不可跳过的闸门。
2. **优先 MCP 原生工具。** `mcp__friday__*` 可用时不要用 curl。MCP 不可用且 env / 配置文件存在时才降级 HTTP（见下节）。
3. **令牌脱敏。** 访问令牌绝不出现在回复文本、代码、日志或提交里。引用配置时只说"已配置"。
4. **长任务要管理预期。** `execute_coding_plan` 默认超时 1 小时。发起后告诉用户在跑什么，用 `get_coding_execution` 轮询（建议间隔 30-60 秒），不要静默等待。
5. **先索引后分析。** 工具报"仓库未索引"时，引导用户先在 Friday Web 的仓库页建立索引，不要对未索引仓库强行分析。

## 降级 HTTP 调用（MCP 不可用时）

所有工具等价于：

```bash
curl -sS -X POST "${FRIDAY_BASE_URL}/api/mcp/tools/<tool_name>/" \
  -H "Authorization: Bearer ${FRIDAY_ACCESS_TOKEN}" \
  -H "Content-Type: application/json" \
  -d '<JSON 参数>'
```

多步流程必须保留首个响应的 `run_id`，后续请求加头 `X-Friday-Run-ID: <run_id>`，使整条链路在 Friday 审计里聚合为同一条轨迹（MCP 模式下 server 自动处理，无需手动）。

## 错误恢复速查

| 症状 | 处理 |
| --- | --- |
| 401 / 403 | 令牌失效。引导用户重建 PAT 并重跑 `npx -y @friday-ai/mcp init` |
| 仓库未索引 / 检索空结果 | 先在 Friday Web 建索引；或放宽检索词重试 |
| 仓库路由不明确 | 用更具体的需求描述重跑 `route_repositories`，或让用户指定仓库 |
| 执行 `failed` | `get_coding_execution` 查 `runner_logs`、`last_diff`、`recovery_state` 定位，修正计划后用 `retry_of_execution_id` 重试 |
| 执行 `partial` | 代码已推送但后续步骤失败。**不要重跑执行**，直接重试 `summarize_branch` / `create_merge_request` |
| MR 创建失败 | 分支与 commit 已持久化。检查 `mr_error`（平台权限 / 已有同名 MR），修复后仅重试 `create_merge_request` |

更多排障细节见 [references/setup.md](references/setup.md)。
