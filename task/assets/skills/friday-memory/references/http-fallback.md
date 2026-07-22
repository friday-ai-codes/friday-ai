# HTTP 兜底 — 记忆层工具

`friday` MCP server 不可用时，每个工具都是普通 HTTP 端点：

```text
POST {FRIDAY_BASE_URL}/api/mcp/tools/{tool_name}/
Authorization: Bearer {FRIDAY_ACCESS_TOKEN}
Content-Type: application/json
X-Friday-Run-ID: {工作流首个调用返回的 run_id，首个调用可省略}
```

## 工具契约

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
