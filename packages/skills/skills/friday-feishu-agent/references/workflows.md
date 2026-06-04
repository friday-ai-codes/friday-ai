# Friday Feishu Agent Workflows
## `fetch_context`
1. Call `get_feishu_work_item_context`.
2. Store `run_id`, `context_id`, work item source URL, document statuses, and relation summary.
3. If document status is `partial`, continue only if the missing docs are non-blocking; otherwise report the missing permission/configuration.
## `plan`
1. Optionally call `search_learning_cases` with work item title/description, repo hints, and file hints.
2. Optionally call codebase tools for repository routing and GraphRAG chunks.
3. Call `create_feishu_technical_plan` with `context_id`, repository evidence, and similar cases.
4. Store `technical_plan_id`, document URL, repo task matrix, status, and retry state.
5. If document writeback fails but plan status is `partial`, continue with execution only when the repo matrix is valid.
## `execute`
1. Call `create_work_item_repo_tasks` if tasks were not already created.
2. Call `execute_work_item_repo_tasks`.
3. For running tasks, poll related `execution_id` with `get_coding_execution`.
4. If execution completed but MR failed, retry `summarize_branch` or `create_merge_request` using persisted branch and commit.
5. Preserve every repo task status separately.
## `learn`
1. After execution is completed or partially completed, call `create_learning_case`.
2. Include outcome, root cause, solution notes, and verified tests.
3. Use `search_learning_cases` before future planning to provide similar-case evidence.
## `full_auto`
1. `get_feishu_work_item_context`
2. `search_learning_cases`
3. repository routing / GraphRAG evidence when needed
4. `create_feishu_technical_plan`
5. `create_work_item_repo_tasks`
6. `execute_work_item_repo_tasks`
7. poll execution or retry MR when needed
8. `create_learning_case`
All tool calls in `full_auto` must share one `run_id`.
## Recovery Rules
- Missing Feishu doc permissions: continue only if the core work item and enough docs are readable.
- Missing repository matrix: rerun `plan` with explicit `repository_ids`.
- Dispatch failed: task is recoverable from `execution_id`, branch, and `recovery_state`.
- MR failed after push: do not rerun coding by default; retry MR creation.
- LearningCase creation failed: execution output remains valid; retry `learn` after fixing the issue.
