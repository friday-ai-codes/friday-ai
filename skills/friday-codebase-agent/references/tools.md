# Friday 工具完整参考

19 个工具，HTTP 等价端点均为 `POST {baseUrl}/api/mcp/tools/{tool_name}/`。所有响应都含 `run_id`（审计轨迹 ID，多步流程需透传 `X-Friday-Run-ID`；MCP 模式自动处理）。

标注约定：`*` 为必填；类型后括号内是默认值。

## 目录

- [仓库发现与浏览](#仓库发现与浏览)：route_repositories / get_repository / list_repository_files / get_repository_file
- [Graph RAG 检索](#graph-rag-检索)：search_rag_chunks / find_related_chunks
- [分析与计划](#分析与计划)：analyze_repository / create_coding_plan / improve_coding_plan
- [执行与 MR](#执行与-mr)：execute_coding_plan / get_coding_execution / summarize_branch / create_merge_request
- [飞书工作项](#飞书工作项)：get_feishu_work_item_context / create_feishu_technical_plan / create_work_item_repo_tasks / execute_work_item_repo_tasks
- [学习案例](#学习案例)：create_learning_case / search_learning_cases

## 仓库发现与浏览

### route_repositories

需求 → 候选仓库排序。仓库未知时的第一步。

| 参数 | 类型 | 说明 |
| --- | --- | --- |
| `query`* | string(<=1000) | 需求 / 问题描述，写得越具体路由越准 |
| `top_k` | int 1-10 (3) | 候选数 |

响应：`query`、`ranked_repos`（含 repository_id、得分与索引健康度）、`total`、`run_id`。

### get_repository

| 参数 | 类型 | 说明 |
| --- | --- | --- |
| `repository_id`* | uuid | 仓库 ID |

响应：`repository`（元数据、默认分支、索引状态）、`run_id`。

### list_repository_files

| 参数 | 类型 | 说明 |
| --- | --- | --- |
| `repository_id`* | uuid | |
| `branch` | string (默认分支) | |
| `path` | string ("") | 起始目录 |
| `recursive` | bool (false) | |
| `page` / `page_size` | int (1 / 50, size<=200) | |

响应：`items`、`total`、`page`、`page_size`、`run_id`。

### get_repository_file

| 参数 | 类型 | 说明 |
| --- | --- | --- |
| `repository_id`* | uuid | |
| `file_path`* | string(<=1000) | 相对仓库根 |
| `branch` | string (默认分支) | |
| `start_line` / `end_line` | int >=1 | 行范围（start 不得大于 end） |
| `max_lines` | int 1-2000 (500) | |

响应：`content`、`truncated`、`returned_lines`、`run_id`。

## Graph RAG 检索

### search_rag_chunks

语义 + 关键词混合召回，附带图谱关系边。收集代码证据的主力。

| 参数 | 类型 | 说明 |
| --- | --- | --- |
| `repository_id`* | uuid | |
| `query`* | string(<=1000) | |
| `branch` | string (默认分支) | |
| `top_k` | int 1-50 (30) | |
| `max_tokens` | int 1-32000 (8000) | 返回内容预算 |

响应：`results`（chunk 列表，含 chunk_id / file_path / 内容）、`related_edges`、`total_tokens`、`run_id`。

`results` 中的条目可作为 `context_chunks` 直接传给 analyze_repository / create_coding_plan / create_feishu_technical_plan。

### find_related_chunks

沿代码图谱扩散（调用 / 导入等关系）。`chunk_id`、`file_path`、`symbol_name` **必须且只能提供一个**作为起点。

| 参数 | 类型 | 说明 |
| --- | --- | --- |
| `repository_id`* | uuid | |
| `chunk_id` / `file_path` / `symbol_name` | 三选一 | 起点 |
| `branch` | string (默认分支) | |
| `relation_types` | string[] ([]) | 如 `calls` / `imports`，空为全部 |
| `hops` | int 0-2 (1) | 扩散跳数 |
| `direction` | `downstream` / `upstream` / `both` (both) | upstream=谁依赖我的依赖方向 |
| `limit` | int 1-50 (20) | |

响应：`source`、`related_chunks`、`run_id`。

## 分析与计划

### analyze_repository

结构化分析（架构 / 风险 / 测试建议）。`analysis_id` 可被 create_coding_plan 复用以共享证据。

| 参数 | 类型 | 说明 |
| --- | --- | --- |
| `repository_id`* | uuid | |
| `branch` | string (默认分支) | |
| `focus` | string(<=1000) ("") | 聚焦主题 |
| `context_chunks` | object[] (<=20) | 来自 search_rag_chunks 的证据 |
| `max_files` | int 1-200 (80) | |

响应：`analysis_id`、`analysis`、`evidence`、`run_id`。

### create_coding_plan

| 参数 | 类型 | 说明 |
| --- | --- | --- |
| `repository_id`* | uuid | |
| `requirement`* | string(<=8000) | 需求全文 |
| `branch` | string (默认分支) | |
| `analysis_id` | uuid | 复用 analyze_repository 证据 |
| `context_chunks` | object[] (<=20) | |
| `max_steps` | int 1-20 (8) | |

响应：`plan_id`、`version_id`、`version`、`plan`（步骤 / 文件 / 风险 / 测试）、`evidence`、`run_id`。

### improve_coding_plan

| 参数 | 类型 | 说明 |
| --- | --- | --- |
| `plan_id`* | uuid | |
| `feedback`* | string(<=8000) | 用户反馈原文 |
| `context_chunks` | object[] (<=20) | |
| `max_steps` | int 1-30 (10) | |

响应：新 `version_id`、`plan`、`change_summary`、`risk_delta`、`run_id`。

## 执行与 MR

### execute_coding_plan

**真实执行：改代码、跑测试、推分支。调用前必须经用户确认计划。** 耗时长，立即返回 execution_id 后需轮询。

| 参数 | 类型 | 说明 |
| --- | --- | --- |
| `plan_id`* | uuid | |
| `version_id` | uuid (最新版) | |
| `branch_name` | string(<=255) (自动生成) | |
| `target_branch` | string(<=255) (默认分支) | |
| `retry_of_execution_id` | uuid | 失败重试时关联上次执行 |
| `timeout_seconds` | int 60-21600 (3600) | |

响应（与 get_coding_execution 相同）：`execution_id`、`status`、`branch_name`、`commit_sha`、`file_changes`、`test_results`、`push_result`、`last_diff`、`runner_logs`、`recovery_state`、`error`、`run_id` 等。

### get_coding_execution

| 参数 | 类型 | 说明 |
| --- | --- | --- |
| `execution_id`* | uuid | |

`status` 语义：`running` 继续轮询（30-60 秒间隔）；`failed` 看 `runner_logs` / `recovery_state` 定位；`partial` 表示代码已推送但后续失败——不要重跑执行，直接走 summarize_branch / create_merge_request。

### summarize_branch

| 参数 | 类型 | 说明 |
| --- | --- | --- |
| `execution_id` | uuid | 二选一：提供它 |
| `repository_id` + `source_branch` + `target_branch` | | 或同时提供这三个 |
| `max_files` | int 1-200 (50) | |

响应：`summary`、`mr_draft`（可直接喂给 create_merge_request）、`run_id`。

### create_merge_request

| 参数 | 类型 | 说明 |
| --- | --- | --- |
| `execution_id` | uuid | 二选一（同 summarize_branch） |
| `repository_id` + `source_branch` + `target_branch` | | |
| `title` | string(<=200) ("") | 省略时复用草稿 |
| `description` | string(<=20000) ("") | |
| `reviewer_usernames` | string[] (<=20) | |
| `remove_source_branch` | bool (true) | |

响应：`mr`（URL / IID）、`execution_status`、`run_id`。

## 飞书工作项

### get_feishu_work_item_context

聚合工作项字段、关系、关联文档与评论。`project_id` 与 `project_key` **至少提供一个**。

| 参数 | 类型 | 说明 |
| --- | --- | --- |
| `work_item_id`* | int >=1 | 飞书工作项 ID |
| `project_id` / `project_key` | uuid / string | 二选一 |
| `work_item_type` | string ("story") | |
| `fields` | string[] (<=80) | 空为默认字段集 |
| `include_comments` | bool (false) | |

响应：`context_id`（喂给 create_feishu_technical_plan）、`work_item`、`relations`、`documents`、`comments`、`status`、`run_id`。

### create_feishu_technical_plan

| 参数 | 类型 | 说明 |
| --- | --- | --- |
| `context_id`* | uuid | |
| `repository_ids` | uuid[] (<=10) | 限定仓库 |
| `repo_hints` | string[] (<=20) | 路由提示词 |
| `context_chunks` | object[] (<=30) | 代码证据 |
| `similar_cases` | object[] (<=20) | 来自 search_learning_cases |
| `title` | string(<=240) ("") | |
| `folder_token` | string ("") | 飞书文档目录 |
| `create_document` | bool (true) | |
| `write_comment` | bool (true) | |

响应：`technical_plan_id`、`plan`、`markdown`、`repository_tasks`、`feishu_document`、`status`、`retry_state`、`run_id`。

### create_work_item_repo_tasks

| 参数 | 类型 | 说明 |
| --- | --- | --- |
| `technical_plan_id`* | uuid | |

响应：`tasks`（按仓库拆分的任务矩阵）、`total`、`run_id`。

### execute_work_item_repo_tasks

**批量真实执行 + 建 MR + 回写飞书。调用前必须经用户确认。** `technical_plan_id` 与 `task_ids` 至少提供一个。

| 参数 | 类型 | 说明 |
| --- | --- | --- |
| `technical_plan_id` | uuid | 二选一 |
| `task_ids` | uuid[] (<=20) | 二选一 |
| `create_missing` | bool (true) | 缺任务自动补建 |
| `dispatch` | bool (true) | false 则只建任务不执行 |
| `create_merge_requests` | bool (true) | |
| `write_back` | bool (true) | 结果回写飞书 |
| `timeout_seconds` | int 60-21600 (3600) | |
| `reviewer_usernames` | string[] (<=20) | |

响应：`tasks`、`summary`、`document_update`、`comment`、`status`、`run_id`。

## 学习案例

### create_learning_case

| 参数 | 类型 | 说明 |
| --- | --- | --- |
| `technical_plan_id`* | uuid | |
| `outcome` | string ("unknown") | success / failed 等 |
| `root_cause` | string(<=5000) ("") | |
| `solution_notes` | string(<=10000) ("") | |
| `tests` | string[] (<=50) | |

响应：`learning_case_id`、`case`、`run_id`。

### search_learning_cases

| 参数 | 类型 | 说明 |
| --- | --- | --- |
| `query` | string(<=2000) ("") | |
| `work_item_type` | string ("") | |
| `repo_hints` | string[] (<=20) | |
| `file_hints` | string[] (<=50) | |
| `symbol_hints` | string[] (<=50) | |
| `limit` | int 1-20 (5) | |

响应：`results`、`total`、`run_id`。
