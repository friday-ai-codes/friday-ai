# Friday Feishu Agent UAT
## Trace
- All tool calls in the workflow share one `run_id`.
- Each step sends `X-Friday-Skill-Step`.
- Final report includes `context_id`, `technical_plan_id`, task IDs, execution IDs, branches, commits, PR/MR URLs, `learning_case_id`, and recovery state.
## Scenarios
| Scenario | Required Checks |
| --- | --- |
| Requirement, single repo | Context read succeeds; technical plan includes one repo task; execution produces branch/MR; LearningCase created. |
| Bug, single repo | Root cause and fix summary are captured in LearningCase; tests are recorded. |
| Requirement, multi repo | Multiple repo tasks are created with independent status and branch names. |
| Feishu doc no permission | Work item context is `partial`; inaccessible doc is structured; plan can continue only with enough evidence. |
| Missing document folder | Technical plan is created; Feishu doc writeback is `partial` with retry state. |
| MR partial failure | Successful repo keeps MR URL; failed repo keeps branch/commit/error/recovery state. |
| Similar case recall | `search_learning_cases` returns a previous case and new technical plan includes it as evidence. |
## Acceptance
- No token or secret appears in response bodies, comments, documents, or logs.
- Partial statuses preserve created artifacts.
- LearningCase source links can trace back to work item context, technical plan, repo task, execution trace, and MR.
- Full auto can be replayed from Interaction Ledger using the final `run_id`.
