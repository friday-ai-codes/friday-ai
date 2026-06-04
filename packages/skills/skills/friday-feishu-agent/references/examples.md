# Friday Feishu Agent Examples
## Fetch Context
```json
{
 "tool": "get_feishu_work_item_context",
 "body": {
 "project_key": "FRIDAY",
 "work_item_type": "bug",
 "work_item_id": 12345,
 "include_comments": true
 }
}
```
## Generate Technical Plan
```json
{
 "tool": "create_feishu_technical_plan",
 "body": {
 "context_id": "context-uuid",
 "repository_ids": ["repo-uuid"],
 "context_chunks": [
 {
 "repository_id": "repo-uuid",
 "file_path": "server/auth/session.py",
 "content": "session validation code"
 }
 ],
 "create_document": true,
 "write_comment": true
 }
}
```
## Execute Repo Tasks
```json
{
 "tool": "execute_work_item_repo_tasks",
 "body": {
 "technical_plan_id": "technical-plan-uuid",
 "create_missing": true,
 "dispatch": true,
 "create_merge_requests": true,
 "write_back": true
 }
}
```
## Create LearningCase
```json
{
 "tool": "create_learning_case",
 "body": {
 "technical_plan_id": "technical-plan-uuid",
 "outcome": "merged",
 "root_cause": "session token expiry branch missed the refresh path",
 "solution_notes": "Normalize refresh before displaying timeout errors.",
 "tests": ["pytest tests/auth/test_session.py -q"]
 }
}
```
## User Prompts
- "帮我处理这个飞书 Bug，生成方案、执行并把 MR 回写。"
- "读取这个工作项和关联文档，先只产出技术方案。"
- "这个需求像不像之前处理过的？先召回相似案例。"
- "多仓执行时一个仓库失败也继续跑其他仓库，最后给我 partial 报告。"
