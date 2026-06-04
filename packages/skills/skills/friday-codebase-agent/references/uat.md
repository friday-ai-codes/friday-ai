# End-to-End UAT
Use this checklist to validate the full Friday Codebase Agent loop.
## Scenario
Input requirement:
```text
Add a small validation improvement to a repository endpoint, include tests, push a branch, and create an MR.
```
## Steps
1. Ensure `FRIDAY_ACCESS_TOKEN` is valid and the target repository has Git credentials.
2. Run `full_auto` with the requirement.
3. Confirm `route_repositories` returns the intended repository and a `run_id`.
4. Confirm every later tool call uses the same `X-Friday-Run-ID`.
5. Confirm `search_rag_chunks` and `find_related_chunks` return evidence for affected files.
6. Confirm `analyze_repository` returns architecture summary, risks, and test strategy.
7. Confirm `create_coding_plan` returns `plan_id`, `version_id`, implementation steps, affected files, and tests.
8. Confirm `execute_coding_plan` returns `execution_id`, branch, target branch, and dispatch payload.
9. Poll `get_coding_execution` until completed, failed, or partial.
10. Confirm completed execution has commit, push result, file changes, test results, and last diff.
11. Confirm `summarize_branch` returns changed files, risks, test suggestions, and `mr_draft`.
12. Confirm `create_merge_request` returns MR id, MR URL, title, description, source branch, target branch, and success flag.
13. Confirm the Interaction Ledger contains one `InteractionRun` for the workflow run id, multiple `skill_step` events, tool calls, retrieval traces, agent decisions, and MR/execution outputs.
## Acceptance
- Requirement text reaches repository discovery.
- GraphRAG evidence reaches analysis and plan creation.
- Plan reaches execution.
- Execution reaches pushed branch.
- Pushed branch reaches branch summary.
- Branch summary reaches MR creation.
- All tool calls in the workflow share one `run_id`.
- Failure after push produces `partial` execution status with retryable branch/commit recovery metadata.
