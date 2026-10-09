# HTTP 兜底 — 记忆层工具

`friday` MCP server 不可用时，每个工具都是普通 HTTP 端点：

```text
POST {FRIDAY_BASE_URL}/api/mcp/tools/{tool_name}/
Authorization: Bearer {FRIDAY_ACCESS_TOKEN}
Content-Type: application/json
X-Friday-Run-ID: {工作流首个调用返回的 run_id，首个调用可省略}
```

## 工具契约

### 会话采集与项目记忆

| 工具 | 路径 | 请求字段 | 响应（关键字段） |
| --- | --- | --- | --- |
| `report_session_knowledge` | `/api/mcp/tools/report_session_knowledge/` | `question`*, `answer`*, `repository_id`, `git_url`, `branch_name`, `project_id`, `session_id`, `response_model`, `provider`, `input_tokens`, `output_tokens`, `client` | `accepted`, `capture_id`, `deduplicated`, `link_reason`, `repository_id`, `project_id`, `run_id` |
| `report_project_knowledge` | `/api/mcp/tools/report_project_knowledge/` | `content`*, `branch_name`/`project_id`, `repository_id`, `writeback_mode`, `target`, `distill` | `accepted`, `draft_id`, `reason`, `run_id` |

`report_session_knowledge` 的 12 个请求字段中，只有 `question` 与 `answer` 必填；常规客户端可选传 `git_url`、`branch_name`、`session_id`、`response_model`、`provider`、`input_tokens`、`output_tokens`、`client`。`repository_id` 与 `project_id` 是服务端开放的可选挂钩字段，但客户端不得根据默认分支猜测或主动拼装 `project_id`。即使工作区是 **clean tree**（无 git 改动），每轮问答仍应提交；`answer` 只取用户可见的最终答案，禁止上传 transcript、隐藏思维链、凭证 / 密钥 / token 或个人敏感信息。

两条写入路径职责独立：`report_session_knowledge` 记录 SessionCapture 原始问答；`report_project_knowledge` 只在存在 git 交付变更时记录 ProjectMemory 交付总结，并保留 diff 门闩与质量门槛。不得把二者合并为一个笼统的“记忆写回”。

### 经验记忆（LearningCase）

| 工具 | 路径 | 请求字段 | 响应（关键字段） |
| --- | --- | --- | --- |
| `create_learning_case` | `/api/mcp/tools/create_learning_case/` | `technical_plan_id`, `outcome`, `root_cause`, `solution_notes`, `tests` | `learning_case_id`, `run_id` |
| `search_learning_cases` | `/api/mcp/tools/search_learning_cases/` | `query`, `work_item_type`, `repo_hints`, `file_hints`, `symbol_hints`, `limit` | `results`, `total`, `run_id` |

### 交付知识（Knowledge）

| 工具 | 路径 | 请求字段 | 响应（关键字段） |
| --- | --- | --- | --- |
| `search_delivery_knowledge` | `/api/mcp/tools/search_delivery_knowledge/` | `query`, `top_k`, `project_ids`, `repository_ids`, `entity_kinds`, `as_of`, `include_superseded` | `query`, `results`, `total`, `as_of`, `run_id` |
| `get_entity_timeline` | `/api/mcp/tools/get_entity_timeline/` | `entity_id`, `include_superseded`, `as_of` | `entity_id`, `nodes`, `total`, `run_id` |
| `get_related_entities` | `/api/mcp/tools/get_related_entities/` | `entity_id`, `direction`, `max_hops`, `as_of` | `entity_id`, `related`, `total`, `as_of`, `run_id` |

## 请求示例

```bash
curl -sS -X POST "${FRIDAY_BASE_URL}/api/mcp/tools/search_delivery_knowledge/" \
  -H "Authorization: Bearer ${FRIDAY_ACCESS_TOKEN}" \
  -H "Content-Type: application/json" \
  -H "X-Friday-Run-ID: ${RUN_ID}" \
  -d '{"query":"登录优化","top_k":5,"as_of":"2026-05-31T23:59:59+08:00"}'
```

## 错误

错误格式为 `{ "error_code": "...", "detail": "..." }`。`authentication_failed` 表示 Access Token 无效——引导用户运行 `npx -y @friday-ai-codes/mcp setup`。
