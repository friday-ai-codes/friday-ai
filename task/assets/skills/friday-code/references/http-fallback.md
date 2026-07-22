# HTTP 兜底 — 执行与 MR 工具

`friday` MCP server 不可用时，每个工具都是普通 HTTP 端点：

```text
POST {FRIDAY_BASE_URL}/api/mcp/tools/{tool_name}/
Authorization: Bearer {FRIDAY_ACCESS_TOKEN}
Content-Type: application/json
X-Friday-Run-ID: {工作流首个调用返回的 run_id，首个调用可省略}
X-Friday-Skill-Step: {workflow.step，可选}
```

## 工具契约

| 工具 | 请求 | 响应（关键字段） |
| --- | --- | --- |
| `execute_coding_plan` | `plan_id`, `version_id`, `branch_name`, `target_branch`, `retry_of_execution_id`, `timeout_seconds` | `execution_id`, `status`, `branch_name`, `target_branch`, `commit_sha`, `file_changes`, `test_results`, `push_result`, `last_diff`, `runner_logs`, `recovery_state`, `error`, `run_id` |
| `get_coding_execution` | `execution_id` | 与 `execute_coding_plan` 相同 |
| `summarize_branch` | `execution_id`, `repository_id`, `source_branch`, `target_branch`, `max_files` | `summary`, `mr_draft`, `run_id` |
| `create_merge_request` | `execution_id`, `repository_id`, `source_branch`, `target_branch`, `title`, `description`, `reviewer_usernames`, `remove_source_branch` | `mr`, `execution_status`, `run_id` |

## MR 重试规则

- 推送成功后 MR 失败：保留 `source_branch`、`target_branch`、`commit_sha`、`mr_error`。平台问题解决后只重试 `create_merge_request`，绝不为 MR 失败重跑 `execute_coding_plan`。
- `git_platform_error`：检查 Friday 中的 Git 凭证、分支是否存在、权限，或同分支是否已有打开的 MR。

## 错误

错误格式为 `{ "error_code": "...", "detail": "..." }`。`authentication_failed` / `authentication_required` 表示 Access Token 需要创建或轮换——引导用户运行 `npx -y @friday-ai-codes/mcp setup`。
