---
status: awaiting_human_verify
trigger: "额度已经恢复；升级 Multica 技术方案 Agent 使用的 Friday MCP，并完整修复此前审计发现的运行时工具缺失、调研失败、状态失同步、孤儿蓝图、skill 冲突与端到端验收缺口。"
created: 2026-08-28
updated: 2026-08-28T17:10:00+08:00
---

# Debug Session: multica-friday-agent-e2e

## Symptoms

- Expected behavior: Multica「技术方案生成」Agent 使用 Friday MCP 0.6.0/51 tools，按 canonical blueprint 协议完成幂等创建、项目身份核验、逐仓调研、真人澄清、原样方案展示、版本/hash 终审，并且只有 confirmed envelope 才能进入 Coding。
- Actual behavior: vision 运行时仍指向 MCP 0.5.0/37 tools；缺少创建幂等/项目绑定参数、蓝图批准/退回、stage sandbox 与代码图谱工具。历史 artifact 已从 researching 推进到 needs_clarification，但 10/10 仓库调研失败、Multica Issue metadata 仍为 researching，父子 Issue 已 cancelled。
- Error messages: 历史逐仓容器先后出现模型网关 403 额度失败和 401 API key 无效；runner 重连还曾因 active assignment 守卫产生假恢复。用户确认额度现已恢复。
- Timeline: 2026-08-19 旧 feature-list 流程开始暴露人工续跑和服务超时问题；2026-08-26 canonical canary 暴露 MCP schema 与逐仓调研问题；2026-08-27 修复 runner 假恢复；2026-08-28 要求升级并完成真实 canary。
- Reproduction: 在 vision Multica workspace 中把正式 Canary 技术方案 Issue 分配给「技术方案生成」Agent；Agent 的 mcp_config 启动 `~/Projects/open-source/friday-ai/mcp/dist/cli.js serve`，随后按 artifact/create 流程取件或发起逐仓调研。

## Current Focus

- hypothesis: all controllable Friday and Multica technical-plan defects reproduced in this session are fixed and validated end to end through the first mandatory human gate.
- test: await a real human answer to AGE-47 thread 16fdd366; then verify clarification replay, pending_review verbatim Markdown, version/hash CAS approval, and confirmed Coding envelope without answering or approving on the user's behalf.
- expecting: AGE-47 stays blocked with artifact c3ae7a71 and 10/10 deep-research evidence until a human answers; no automatic approval or Coding dispatch occurs.
- next_action: hand the valid repository-confirmation question to the user and keep the debug session unarchived until that human-gated continuation is explicitly requested.
- reasoning_checkpoint:
    hypothesis: "Four missing authority bridges independently caused the parent-validation failures: confirm_gate publishes snapshots without validating direct evidence; periodic recovery only redrives sessions and never reconciles terminal runner facts or elapsed task deadlines; durable resume has no reference back to the MCP reservation; and work-item context labels a projects.Space UUID as project_id without returning the resolved initiatives.Project UUID."
    confirming_evidence:
      - "Four confirmation variants (failed, empty responsibility, empty reasons, empty current_state_summary) all returned awaiting_confirmation and opened a repo_confirmation thread."
      - "The recovery module has no research-task reconciliation entry point although RunnerEvent persists task_completed and SubAgentSession persists started_at."
      - "The reservation regression cannot import any reconciliation service, and live df2d4a9f remains idempotency_pending after its session produced artifact c3ae7a71."
      - "get_feishu_work_item_context returned no explicit space_id/blueprint_project_id; its implementation assigns a projects.Space row to variable project and emits that UUID under project_id."
    falsification_test: "If adding each bridge leaves its focused RED regression failing, or if identity validation accepts a Space UUID as an initiatives.Project UUID, the corresponding mechanism is incomplete."
    fix_rationale: "Validate before opening the human gate and retry through ResearchService; reconcile persisted runner/deadline facts before periodic redrive; finalize only a validated reservation↔session↔artifact tuple through a service; expose both identity types explicitly while retaining the legacy alias."
    blind_spots: "Live RunnerEvent detail shape and AGE-47's historical session lack the new automatic reservation reference, so live recovery must use the explicit validated reconciliation parameter once and then verify idempotent reuse."
- tdd_checkpoint:
    test_files:
      - "server/tests/services/process_runtime/test_blueprint_confirm_gate.py"
      - "server/tests/services/process_runtime/test_blueprint_session_recovery.py"
      - "server/tests/mcp_tools/test_create_feishu_technical_plan_delegate.py"
      - "server/tests/mcp_tools/test_feishu_work_item_context.py"
    failure_output: "awaiting_confirmation != research_required; reconciliation functions absent; context response missing space_id"
    status: "green"
- reasoning_checkpoint:
    hypothesis: "`asyncio.CancelledError` bypasses the delegate's `except Exception`, so the persisted route session loses its request driver and the caller never reaches reservation finalization."
    confirming_evidence:
      - "AGE-47 persisted a running route session with no lease immediately after CancelledError, while the idempotency reservation remained pending."
      - "The focused regression raises CancelledError at the driver boundary and fails from orchestration_delegate.py:312 without invoking the existing resume service."
      - "drive_lease releases in a finally block, explaining the empty lease without implying lease corruption."
    falsification_test: "If an explicit CancelledError branch handing the exact session to the durable resume service still lets the focused test escape cancellation or leaves the reservation pending, this boundary is not sufficient."
    fix_rationale: "Converting cancellation to a resumable partial handoff preserves the persisted session identity, uses the existing durable driver, and lets the enclosing technical-plan service finalize the same idempotency record rather than creating a duplicate."
    blind_spots: "The focused RED test proves the delegate boundary only; green verification must also exercise service-level reservation finalization and the live AGE-47 recovery path."
- tdd_checkpoint:
    test_file: "server/tests/mcp_tools/test_create_feishu_technical_plan_delegate.py"
    test_name: "test_delegate_cancellation_hands_exact_blueprint_session_to_durable_resume"
    status: "green"
    failure_output: "asyncio.exceptions.CancelledError at mcp_tools/orchestration_delegate.py:312"
- reasoning_checkpoint:
-  hypothesis: under-specified orphan wording causes status resurrection because the Agent treats blocked as a non-progress terminal safety action.
-  confirming_evidence:
-    - Run 1a88329c observed cancelled correctly and immediately executed `multica issue status ... blocked --no-start`.
-    - Local SKILL.md only says "停止自动推进" and fallback only says "对账/停止自动推进"; neither says Issue status is read-only or forbids blocked/in_progress/done.
-    - The new exact-invariant regression fails on all ten required read-only/prohibited-action fragments in both documents.
-  falsification_test: if the strengthened skill and formal instructions are deployed yet a fresh cancelled-Issue run still issues any status or Friday mutation, semantic ambiguity was not the sole cause.
-  fix_rationale: making both state surfaces immutable and enumerating prohibited tools removes the model's latitude to interpret blocked as a safe stop, while allowing only policy-approved metadata/comment reconciliation.
-  blind_spots: Multica may inject higher-priority generic instructions that require blocked status; only tool-message inspection in a real rerun can validate precedence.
- reasoning_checkpoint:
-  hypothesis: Agent 76859b8a is pinned to a deleted runtime, causing every new execution to remain queued because no daemon can claim runtime_id 0681b657.
-  confirming_evidence:
-    - Agent get reports runtime_bound=true and runtime_id=0681b657-8aa0-4852-926c-ba376afa43ff.
-    - Runtime list contains no 0681b657 entry, while the authorized vision daemon reports active Opencode runtime 53de76ee-f994-41cb-bb07-41b0327778a1.
-    - Controlled run f3774e7a stayed queued for more than five minutes with dispatched_at/start_at null and the stale runtime ID.
-  falsification_test: if rebinding to 53de76ee still leaves a new run undispatched, stale runtime binding is not the dispatch root cause.
-  fix_rationale: replacing the dead foreign-key-like runtime selection with the currently registered vision Opencode runtime lets the daemon claim executions while preserving the Agent, skills, instructions, and MCP config.
-  blind_spots: Multica server may allow rerun on cancelled Issues and the Agent may still ignore the deployed orphan text; the post-rebind canary must verify behavior and artifact immutability.
- reasoning_checkpoint:
-  hypothesis: legacy 三段 skill 文档导致 Agent 采用错误控制协议，因为它明确宣称三工具完整且省略 canonical review/CAS 工具。
-  confirming_evidence:
-    - friday-solution/SKILL.md 第 14-24 行把 create/confirm/get 声明为不可跳过的完整三段链。
-    - references/http-fallback.md 第 3-20 行明确说只有三个工具且共享响应形状，未出现 approve/request changes/version/hash。
-  falsification_test: 若加入 canonical 工具与版本/hash/coding gate 断言后当前文档测试仍通过，则该漂移判断错误。
-  fix_rationale: 让主文和 fallback 都以 canonical blueprint 为权威，并用语义快照阻止未来退回 legacy 三工具。
-  blind_spots: Multica 服务端可能缓存已导入 skill；本地修复后仍需通过其管理 API 重新导入并跑真实任务。
- tdd_checkpoint:

## Evidence

- timestamp: 2026-08-28T11:38:00+08:00
  observation: vision Agent mcp_config 指向本机 friday-ai/mcp；该 checkout 为 d5f2a40、package 0.5.0、37 tools，而本地已提交 c324e10、package 0.6.0、51 tools。
- timestamp: 2026-08-28T11:38:00+08:00
  observation: artifact 807fd066-300a-4a48-a6cf-92cb11e33a3a 当前 needs_clarification，10 个候选仓 task_status 全为 failed，职责和现状摘要为空。
- timestamp: 2026-08-28T11:38:00+08:00
  observation: Multica AGE-39 已 cancelled，metadata friday_current_status 仍为 researching；AGE-38 也已 cancelled，形成非终态 Friday artifact 与已取消 Issue 的状态分裂。
- timestamp: 2026-08-28T11:38:00+08:00
  observation: friday-solution 主文要求 canonical blueprint，但导入的 references/http-fallback.md 仍只描述旧 create_feature_tech_plan/confirm/get 三工具。
- timestamp: 2026-08-28T11:45:00+08:00
  checked: git baseline and branch context
  found: main is ahead of origin/main by two existing commits; only this debug file is untracked. Friday branch lookup matched an unrelated project solely through generic main.
  implication: Preserve the two commits and do not use recalled project requirements as implementation truth; local/runtime evidence must drive this debug session.
- timestamp: 2026-08-28T11:45:00+08:00
  checked: debug knowledge base
  found: repo-plan-poisoned-resume overlaps failed research and durable wake-up symptoms; prior fix added retry callbacks, explicit degraded plans, and event-specific wait states.
  implication: Treat regression in those paths as a first hypothesis, while independently testing Issue/artifact dual-source synchronization.
- timestamp: 2026-08-28T11:49:00+08:00
  checked: local repository and submodules
  found: mcp submodule is c324e108 with the existing 0.6.0/51-tool implementation; skills is 80f4016. Existing ahead commits already contain runner stale-assignment recovery plus two regression tests.
  implication: Do not rewrite or recommit those fixes. Compare vision runtime directly against these exact revisions and preserve all current work.
- timestamp: 2026-08-28T11:49:00+08:00
  checked: local status-sync search
  found: friday_current_status exists only in this debug file; no Multica Issue model or status reconciler exists in the Friday repository.
  implication: Issue/artifact reconciliation must be inspected and fixed in the authorized Multica deployment/config/skill surface, while Friday durable continuation remains locally testable.
- timestamp: 2026-08-28T11:54:00+08:00
  checked: vision deployment
  found: friday-ai parent is 0c61f90 with unrelated modified skills and one untracked route result; mcp checkout is d5f2a407/package 0.5.0. Local desired mcp is c324e108/package 0.6.0.
  implication: Upgrade only the mcp submodule checkout/build in place and avoid touching the unrelated parent/skills changes until their provenance is understood.
- timestamp: 2026-08-28T11:54:00+08:00
  checked: local MCP tests
  found: mcp 0.6.0 package tests pass 28/28.
  implication: c324e108 is a test-backed deployment candidate for vision.
- timestamp: 2026-08-28T11:54:00+08:00
  checked: friday-solution HTTP fallback
  found: fallback explicitly says only three legacy feature-plan tools and treats repeated get calls as the driver; it omits canonical get/answer/rework/approve version-hash protocol.
  implication: This imported reference can steer an Agent away from the canonical blueprint flow and needs a regression-guarded skill fix.
- timestamp: 2026-08-28T12:02:00+08:00
  checked: existing skill snapshot guard
  found: guard only checks backticked tool names are present in the server snapshot; it does not assert canonical flow semantics. Its prefix self-check also omits approve_ and request_, despite those tools now being in the snapshot.
  implication: Add protocol-specific assertions and repair the guard prefix coverage before changing the skill text.
- timestamp: 2026-08-28T12:02:00+08:00
  checked: durable regression suite
  found: runner recovery, blueprint context redispatch, and MCP package alignment all pass (17/17).
  implication: Existing local durable wake-up and 51-tool alignment fixes are green; remaining work is deployment, skill semantics, and real canary behavior.
- timestamp: 2026-08-28T12:06:00+08:00
  checked: canonical skill regression before fix
  found: new semantic test failed on both SKILL.md and http-fallback.md, while the guard self-check also exposed five previously uncovered tool prefixes.
  implication: The regression directly reproduces the skill drift and confirms the old generic token-subset guard was insufficient.
- timestamp: 2026-08-28T12:09:00+08:00
  checked: canonical skill regression after fix
  found: skill/schema suite passes 6/6, ruff passes, and IDE diagnostics are clean.
  implication: Local skill protocol drift is fixed with regression coverage; deployment import/cache still requires real verification.
- timestamp: 2026-08-28T12:13:00+08:00
  checked: vision MCP upgrade fetch
  found: origin rejected c324e108 as not our ref; local mcp HEAD has that commit but origin has not published it. Vision mcp remained clean at d5f2a407.
  implication: Runtime can be upgraded without violating no-push by transferring the existing local commit object over the authorized SSH channel.
- timestamp: 2026-08-28T12:18:00+08:00
  checked: vision MCP deployment
  found: c324e108 transferred via temporary git bundle, package 0.6.0 built successfully, package tests passed 28/28, and a real stdio MCP client observed exactly 51 tools including approval, rework, context, graph, and repo-research tools.
  implication: Runtime/tool availability defect is fixed on vision without pushing or changing the parent main branch.
- timestamp: 2026-08-28T12:22:00+08:00
  checked: Multica technical-plan Agent and imported skill
  found: Agent 76859b8a uses the upgraded local dist path and its instructions prohibit legacy fallback. Imported skill root has review/CAS terms but lacks idempotency_key, blueprint_project_id, orphan, and cancelled; its fallback file lacks canonical tools.
  implication: Update the assigned skill in place while preserving its ID and agent assignments; include fresh-create and orphan handling in regression coverage.
- timestamp: 2026-08-28T12:26:00+08:00
  checked: expanded skill regression
  found: test failed before the fix on idempotency_key, blueprint_project_id, and cancelled in both documents; after edits the full guard passes 4/4 with ruff and IDE diagnostics clean.
  implication: Fresh-create and orphan semantics now have local regression protection.
- timestamp: 2026-08-28T12:28:00+08:00
  checked: deployed Multica skill
  found: assigned skill ID was updated in place; both root and fallback now contain all required create, clarify, rework, CAS approval, confirmed Coding gate, and cancelled-orphan terms. Agent assignments were preserved.
  implication: New Multica tasks will receive the corrected controller contract without recreating the skill.
- timestamp: 2026-08-28T12:32:00+08:00
  checked: historical artifact authority
  found: artifact 807fd066 remains needs_clarification in project 75248ff9; all 10 repo options are failed with empty responsibility, fitness citations, and current_state_summary.
  implication: AGE-39 metadata researching is stale and the cancelled issue is an orphan; it must not be resumed or approved.
- timestamp: 2026-08-28T12:36:00+08:00
  checked: fresh direct repository-research canary
  found: session c54ec92e dispatched one direct study-user-status task, but it immediately reached failed/container_failed with no research payload.
  implication: Quota recovery has not yet produced a successful research result; inspect the current execution failure before attempting a full canonical blueprint.
- timestamp: 2026-08-28T12:40:00+08:00
  checked: Persisted RepoResearchTask, SubAgentSession, RunnerEvent, and append-only SubAgentRuntimeLog records for task 432c108b-ac56-4331-819d-7e8a30ae01a0.
  found: Runner spider-dev accepted and started the task, and the container initialized successfully. It then received an upstream HTTP 403 stating that the remaining balance was about USD 0.035 while the required preauthorization was about USD 0.179, emitted zero model cost, and exited 1. The configured opus/sonnet/haiku/default task model aliases all resolve to claude-opus-4-8.
  implication: Runner dispatch, task image startup, provider credential delivery, and callback persistence all worked. The current canary failure is a definitive upstream quota/entitlement blocker, not the previously suspected local/runtime defect; restored model quota is disproven for the credential actually used by repository research.
- timestamp: 2026-08-28T12:45:00+08:00
  checked: Authoritative Multica AGE-39 Issue, execution history, and timeline.
  found: AGE-39 is cancelled since 2026-08-27T06:56:42Z, metadata still says friday_current_status=researching, and no execution occurred after cancellation. Its last execution completed while the Issue was active and observed the linked artifact as researching. The linked Friday artifact later became needs_clarification, but no Multica wake-up or metadata reconciliation followed.
  implication: Cancellation currently prevents passive continuation, but bidirectional state synchronization is absent: Friday does not know the Issue is cancelled and Multica does not learn the artifact's later terminal human-gate state. A controlled rerun is needed to prove the deployed orphan guard executes rather than merely existing in prose.
- timestamp: 2026-08-28T13:02:00+08:00
  checked: Controlled AGE-39 rerun f3774e7a and the technical-plan Agent/runtime registry.
  found: Multica allowed rerun on a cancelled Issue, but the run remained queued for more than five minutes with no dispatch/start. The Agent is bound to runtime 0681b657, which is absent from the current runtime registry; the authorized vision daemon has active owner-local Opencode runtime 53de76ee. The stuck canary was explicitly cancelled before it could execute later.
  implication: The deployed Agent has a stale runtime binding that prevents all fresh work, independently of Friday MCP correctness. Rebinding is required before any runtime orphan or durable-continuation contract can be tested.
- timestamp: 2026-08-28T13:05:00+08:00
  checked: Post-rebind canary 3bb4f94a on active vision Opencode runtime 53de76ee.
  found: The run dispatched and started within two seconds, proving stale binding was the queue root cause, but failed before Agent execution because the current Opencode default model requires explicit China-hosting opt-in.
  implication: Vision runtime routing is repaired, but Opencode has a separate provider/account gate. Use another already-online runtime on the same authorized daemon to test the Friday Agent contract without changing account consent.
- timestamp: 2026-08-28T13:08:00+08:00
  checked: Canary 16f51e19 on vision Codex runtime 91162644.
  found: The run dispatched immediately but failed before Agent execution because the workspace default gpt-5.6-sol requires a newer Codex CLI than the installed 0.141 runtime.
  implication: Multica dispatch and stale-binding repair are confirmed. Codex is independently incompatible with its selected default model, so use the already-online vision Claude runtime for the semantic contract canary.
- timestamp: 2026-08-28T13:10:00+08:00
  checked: Canary 1f6105df on vision Claude runtime 53c3c9ea.
  found: The run dispatched immediately but failed before Agent execution with a definitive weekly model usage-limit denial; no Friday tools ran.
  implication: Claude is also externally quota-blocked. Test the final owner-local vision runtime (Cursor) before declaring Multica semantic canary blocked.
- timestamp: 2026-08-28T13:13:00+08:00
  checked: Canary a5b66055 on vision Cursor runtime 52212ad3 and published Codex CLI version.
  found: Cursor failed before emitting any event because the runtime is not authenticated. The npm registry reports Codex CLI 0.150.1 while vision Codex is 0.141 and failed only because gpt-5.6-sol requires a newer CLI.
  implication: Upgrade the authorized vision Codex runtime as the least invasive path to a functioning Multica execution runtime; no account consent or credential mutation is required.
- timestamp: 2026-08-28T13:16:00+08:00
  checked: Multica-managed Codex update and vision Opencode model catalog.
  found: Runtime update to Codex 0.150.1 was rejected because the CLI is managed by Multica Desktop and requires a Desktop app update. Vision Opencode lists non-latest models including opencode-go/kimi-k2.7-code.
  implication: Avoid an unrelated Desktop upgrade; pin the technical-plan Agent to an available older Opencode model to bypass the latest-model hosting-consent gate.
- timestamp: 2026-08-28T13:19:00+08:00
  checked: Canary 0b56af58 on vision Opencode with explicit model opencode-go/kimi-k2.7-code.
  found: The hosting-consent error was eliminated, but the run still failed before Agent execution with a definitive insufficient-balance denial.
  implication: Every owner-local vision runtime is blocked before Friday MCP invocation (Opencode balance, Claude weekly quota, Codex version managed by Desktop, Cursor unauthenticated). Keep the repaired active binding and explicit model, reconcile the known orphan metadata, and stop attempting model-backed canaries until quota/account state changes.
- timestamp: 2026-08-28T13:23:00+08:00
  checked: AGE-39 metadata reconciliation and linked Friday artifact immutability.
  found: Cancelled AGE-39 now records friday_current_status=needs_clarification, friday_orphan=true, and friday_orphan_reason=issue_cancelled. A fresh get_technical_blueprint read confirms artifact 807fd066 remains needs_clarification at version 2, artifact_version_id 77fa7155, and the same content hash; no clarification was answered and no approval or Coding transition occurred.
  implication: The known orphan is now explicitly quarantined and synchronized at the metadata level without mutating the production blueprint. Automatic bidirectional reconciliation remains absent and cannot be semantically exercised until a Multica model runtime can start.
- timestamp: 2026-08-28T13:31:00+08:00
  checked: Final local regression suite, diagnostics, and project knowledge writeback.
  found: 21 targeted tests passed across runner recovery, blueprint context redispatch, skill contract, and MCP package alignment; the edited regression file has no IDE lint diagnostics. The verified findings were written to Friday project memory. No API surface changed, so report_project_state correctly had no non-empty API payload to submit.
  implication: Local changes are regression-protected and the session is resumable from durable project memory; only external quota/runtime access prevents the final successful model-backed canaries.
- timestamp: 2026-08-28T13:35:00+08:00
  checked: Human-provided live orphan canary run 1a88329c on previously successful spider Opencode runtime 663f8d2d.
  found: The Agent correctly detected AGE-39 status=cancelled but then executed `multica issue status ... blocked --no-start`, resurrecting the cancelled Issue. The run was cancelled and AGE-39 was restored to cancelled.
  implication: Runtime access is sufficient to reproduce a semantic policy defect. "Stop automatic progression" is not strong enough: cancelled/orphan handling must explicitly make Issue status and Friday artifact read-only and enumerate prohibited state-changing actions.
- timestamp: 2026-08-28T13:39:00+08:00
  checked: Exact cancelled/orphan read-only regression before the fix.
  found: `test_friday_solution_cancelled_orphan_is_strictly_read_only` failed as expected; both SKILL.md and HTTP fallback lack every asserted immutable-state and prohibited-action fragment.
  implication: The semantic defect is reproduced locally under test and is ready for a minimal contract fix.
- timestamp: 2026-08-28T13:44:00+08:00
  checked: Local skill fix, regression, and deployed formal Agent instruction baseline.
  found: Both local documents now declare Issue/artifact read-only, prohibit cancelled→blocked/in_progress/done and every canonical mutation/research/Coding action, and allow only policy-approved metadata/comment reconciliation. The skill guard passes 5/5 and ruff is clean. Deployed Agent instructions contained none of the eight core invariant fragments before update.
  implication: Local fix is verified; the same invariant must be deployed to both Multica skill surfaces and the higher-priority formal Agent instructions before canarying.
- timestamp: 2026-08-28T13:49:00+08:00
  checked: In-place Multica deployment verification.
  found: Existing skill ID 3bf4035a root and fallback and Agent ID 76859b8a formal instructions all contain the complete eight-part read-only/prohibited-action invariant. Agent remains assigned to the same skill and runtime 663f8d2d.
  implication: Deployment/cache and precedence surfaces are aligned; a live rerun can now falsify or confirm the semantic fix.
- timestamp: 2026-08-28T14:15:00+08:00
  checked: Controlled orphan canary f4eed36a on runtime 663f8d2d with active forbidden-action monitoring.
  found: The run completed successfully in 36 seconds. All six tool uses were read-only Issue/parent/comment inspection or local no-op reporting; there was no `issue status`, Friday create/answer/approve/request-changes/research call, Coding dispatch, or comment write. The final result explicitly reported the cancelled/orphan read-only exit.
  implication: The original resurrection reproduction no longer occurs under the same runtime; no emergency cancellation/correction was required.
- timestamp: 2026-08-28T14:16:00+08:00
  checked: Post-canary AGE-39 and linked Friday artifact fingerprints.
  found: AGE-39 remains cancelled with the same orphan metadata, artifact version ID 77fa7155, and content hash 4f439b8e. The Issue revision advanced from 15 to 16 only as execution activity completed, with no Agent status/comment mutation. Independent `get_technical_blueprint` confirms needs_clarification, version 2, the same artifact_version_id, and the same content_hash.
  implication: Both authoritative state machines remained immutable as required.
- timestamp: 2026-08-28T14:18:00+08:00
  checked: Final targeted regression suite and diagnostics.
  found: 38 tests passed across runner recovery, blueprint context redispatch/waiting, skill contracts, and MCP package alignment; ruff and IDE diagnostics are clean. Repository research was not retried and no billing/preauthorization bypass was attempted.
  implication: All controllable fixes are regression-protected; the unrelated repository-research canary remains correctly blocked on external quota.
- timestamp: 2026-08-28T15:20:00+08:00
  checked: Human-provided AGE-47 live reproduction and durable session state.
  found: Issue 3181a337 run 285b0331 created technical plan df2d4a9f with idempotency key gaosan-formal-canary-20260828-02; ConvergenceSession 63bd443c is still running at route with zero research tasks, no error, no lease, and no update after an asyncio CancelledError in a shielded future.
  implication: A newly reproduced cancellation path can orphan the canonical blueprint before route persistence, while MCP retries remain pinned to the same idempotency reservation.
- timestamp: 2026-08-28T15:20:00+08:00
  checked: Git working state and Friday branch-context recall.
  found: main is ahead of origin by nine commits and has existing changes in the skill submodule, snapshot guard, debug file, and an unrelated untracked phase plan. Branch lookup matched an unrelated project through generic main, although its memory contains this debug history.
  implication: Preserve every existing change, use local/live evidence rather than the unrelated project requirement, and do not commit or push.
- timestamp: 2026-08-28T15:34:00+08:00
  checked: MCP create call path, process engine, drive lease, and blueprint recovery services.
  found: `ProcessEngine` and `delegate_process_runtime` catch `Exception`, but Python cancellation is `BaseException`; the lease correctly releases in `finally`, leaving the persisted session unchanged at route. The technical-plan reservation is only finalized after the delegate returns, while existing `aresume_after_gate_action`/`arun_blueprint_resume` can durably resume an exact session.
  implication: The observed empty lease is correct cleanup, not the cause. The missing cancellation boundary in the MCP delegate is the divergence point: it must convert cancellation into a resumable partial handoff so the caller can finalize the same idempotency reservation.
- timestamp: 2026-08-28T15:38:00+08:00
  checked: Focused TDD cancellation regression before production fix.
  found: The new test fails exactly at `session = await adrive(engine, session)` with uncaught `asyncio.exceptions.CancelledError`; the captured durable-resume entry point is never called.
  implication: The live orphan mechanism is reproduced deterministically and the regression is RED.
- timestamp: 2026-08-28T15:47:00+08:00
  checked: Minimal cancellation handoff and focused GREEN regression.
  found: `delegate_process_runtime` now catches cancellation only for persisted technical_blueprint sessions, logs a structured lifecycle, hands the exact session to `aresume_after_gate_action`, and returns partial so the enclosing technical-plan service can finalize the same reservation. The focused test passes 1/1.
  implication: The deterministic orphan reproduction is fixed at its divergence boundary; adjacent durable and idempotency behavior still requires verification before live recovery.
- timestamp: 2026-08-28T15:50:00+08:00
  checked: Adjacent regressions, lint, and live recovery preflight.
  found: Delegate, blueprint session recovery, drive lease, and context redispatch suites pass 45/45; ruff passes. Live DB identity check finds exactly session 63bd443c at running/route, artifact c3ae7a71 researching version_label 1, zero research tasks, and existing plan df2d4a9f partial with `failed_stage=idempotency_pending`; lease fields are empty.
  implication: The fix does not regress adjacent durable paths, and the requested live object identities are confirmed before any recovery mutation.
- timestamp: 2026-08-28T16:15:00+08:00
  checked: Exact-session resume and repository-research fan-out.
  found: `arun_blueprint_resume` returned resolved=true for session 63bd443c at waiting_event/repo_research after deepseek route completed and dispatched 10 research tasks on the same artifact. Eight tasks reached done. Two remained running over 43 minutes despite a configured 30-minute timeout: study-plan emitted repeated runner `task_completed` events at 07:33-07:36Z but never delivered a structured business callback; study-user-status emitted no terminal runner event and its last persisted tool result was 07:31Z.
  implication: The original route cancellation orphan is recovered. Live completion is now blocked by two truthful downstream terminal conditions whose business callback/status reconciliation was missed; raw status must not be edited, but existing task/session domain services can safely record the observed completion-without-result and timeout before re-entering the existing barrier.
- timestamp: 2026-08-28T16:18:00+08:00
  checked: Downstream terminal reconciliation and final AGE-47 gate.
  found: Existing domain methods recorded study-plan as completed-without-structured-result and study-user-status as timed out; `ResearchService.mark_failed` preserved both truthful reasons and made the 10-task fan-out terminal (8 done, 2 failed). Re-entering through `arun_blueprint_resume` advanced the same session/artifact to waiting_clarification/repo_confirmation and opened blocking thread ffa8163a; no duplicate session/artifact/plan, clarification answer, approval, Coding dispatch, or raw session-status update occurred.
  implication: AGE-47 reached the required valid human gate. The pre-fix McpWorkItemTechnicalPlan reservation df2d4a9f still truthfully exposes `idempotency_pending` and blank blueprint_artifact_id because no supported reconciliation service links a historically cancelled reservation back to its session; it was intentionally not raw-mutated.
- timestamp: 2026-08-28T16:32:00+08:00
  checked: Four parent-validation RED regressions and live identity/role evidence.
  found: Confirmation opened for failed/empty direct evidence; recovery had no persisted RunnerEvent/deadline reconciliation; no reservation reconciliation service existed; context output omitted explicit Space/Project identities. Live routing marked all 10 candidates direct, while the confirmation snapshot silently downgraded three to indirect; both failed repositories remained routed-direct and lacked responsibility, fitness reasons, and current-state summary. Artifact project c8feeca8 is an initiatives.Project UUID; 2f6ae28d is the McpWorkItemContext projects.Space UUID.
  implication: The parent corrections are confirmed. Gate eligibility must use routed-direct authority even when research suggests a role downgrade, and Agent identity comparison must use explicit blueprint_project_id rather than the legacy Space alias.
- timestamp: 2026-08-28T16:34:00+08:00
  checked: Focused GREEN regressions and adjacent suite.
  found: All focused behavior assertions pass and ruff/IDE diagnostics are clean. The first 135-test adjacent run had only two expected contract updates; after fixing them, a concurrent second pytest process corrupted the shared test DB and produced teardown deadlocks/duplicate-permission errors, so the test database must be recreated once with no competing pytest process before final evidence.
  implication: Production behavior is ready for supported live reconciliation; final adjacent verification remains pending on a clean test DB recreation, not a code failure.
- timestamp: 2026-08-28T16:38:00+08:00
  checked: Parent revalidation of the automatically reopened repo_confirmation.
  found: The previous retry had converted routed-direct study-plan and study-user-status into service-generated light partials (`research_summary` explicitly said 未起独立调研容器/轻量合成) and downgraded both to indirect, so their field completeness alone still opened thread 5627dd61 without repository evidence.
  implication: Field validation was necessary but insufficient. Routed-direct authority must also reject light provenance, and no-runner handling must wait rather than synthesize route/charter evidence.
- timestamp: 2026-08-28T16:39:00+08:00
  checked: Lightweight-fallback RED/GREEN regressions and supported live quarantine.
  found: New regressions require no online runner to leave direct tasks pending with no PartialPlan and require confirm_gate to reject a routed-direct `research_depth=light` partial. Production now records explicit light provenance, detects legacy `轻量合成` summaries, dismisses the invalid thread, and requeues the two repositories. The exact live call returned `research_required` for both IDs and moved the same session to waiting_event/repo_research without an open thread.
  implication: A routed-direct repository can no longer reach a human gate through deterministic routing synthesis, including historical light partials created before the provenance field existed.
- timestamp: 2026-08-28T16:48:00+08:00
  checked: Live deepseek retry through research adapter and stranded-dispatch recovery.
  found: study-user-status completed real deep research first. study-plan's durable dispatch was stranded while the runner heartbeat flapped; the existing `arecover_stranded_dispatch_sessions` service requeued the persisted dispatch snapshot, and the online spider-dev runner accepted it with `deepseek-v4-flash`. Both structured callbacks completed without any raw record mutation.
  implication: The original two abnormal repositories now have repository-derived evidence. Existing durable recovery handled the transient runner assignment loss while preserving the same RepoResearchTask identities.
- timestamp: 2026-08-28T16:53:00+08:00
  checked: Final focused suite, lint, reservation/identity reconciliation, and AGE-47 gate integrity.
  found: 12 focused regressions passed sequentially (fail-closed variants, light provenance, no-runner waiting, missed callback, timeout, reservation reuse, identity output, stale-error clearing); ruff passed all modified Python files. All 10 live tasks are done with empty current errors, non-empty responsibilities and fitness reasons, 5-13 findings and 17-41 repository citations each. Session 63bd443c is waiting_clarification/repo_confirmation with only blocking thread 16fdd366; plan df2d4a9f is partial and linked to artifact c3ae7a71. Context alias `project_id`/`space_id` is Space 2f6ae28d while artifact `blueprint_project_id` is Project c8feeca8.
  implication: Direct evidence is complete and AGE-47 is now at a genuinely valid human gate. The original reservation is finalized/reusable and the identity contract compares equivalent Project identities without breaking the legacy Space alias.
- timestamp: 2026-08-28T17:01:00+08:00
  checked: Final Multica controller rerun b37d6f4f on AGE-47 after deploying the identity and evidence contracts.
  found: The Agent retried the same idempotency key, reused artifact c3ae7a71, corrected legacy Space metadata to blueprint Project c8feeca8, verified 10/10 complete evidence, posted the human-readable repository confirmation, set AGE-47 to blocked, and exited without answering, approving, or dispatching Coding.
  implication: The deployed Agent can now recover a timed-out create, distinguish Space from Project, enforce the research evidence gate, and stop at the intended human boundary.
- timestamp: 2026-08-28T17:10:00+08:00
  checked: Clean-database adjacent regression suite and production model-config restoration.
  found: A single-process `pytest --create-db` run passed 144/144 tests across MCP create/context/schema/skill, research service, confirm gate, research adapter, session recovery, and context redispatch; ruff passed all modified Python files. The temporary deepseek-v4-flash Claude Code mapping was restored to the original ops credential and claude-opus-4-8 tiers.
  implication: The complete change set is regression-protected without relying on the previously corrupted shared test database, and the temporary canary model configuration did not remain in production.

## Eliminated

- hypothesis: Fresh direct research failed because MCP 0.6.0 tools, runner dispatch, task image startup, clone, or callback persistence were broken.
  evidence: Task 432c108b was accepted, initialized, streamed logs, and persisted its terminal callback; the sole failure was the upstream preauthorization 403.
  timestamp: 2026-08-28T12:40:00+08:00
- hypothesis: Rebinding the technical-plan Agent to any currently online vision runtime was sufficient for semantic execution.
  evidence: Opencode requires hosting consent or sufficient balance, Claude has exhausted weekly quota, Codex 0.141 is incompatible with the selected model and Desktop blocks in-place CLI update, and Cursor is unauthenticated.
  timestamp: 2026-08-28T13:19:00+08:00
## Resolution

- root_cause: AGE-47 的取消孤儿来自 `CancelledError` 越过 `except Exception`；父级复核又揭示四个独立缺口：确认门不校验 routed-direct 的失败/空字段/轻量来源，恢复扫描不对账丢失 callback 与超时，续驱产物不反向收口 MCP reservation，context 把 Space UUID 以 legacy `project_id` 暴露后被误当成 blueprint Project UUID。无 runner 时把 direct 降级为 light 还会绕过仅做字段完整性的 fail-closed 校验。
- fix: 保留取消 durable handoff；确认门以 routing direct IDs 为权威校验任务、必填证据和真实深调研来源，失败可重试且耗尽后 stage failed；恢复扫描自动核对 RunnerEvent/SubAgentSession 终态和 deadline；续驱通过校验项目归属的 reconciliation service 绑定原 reservation/artifact；context 同时返回 `space_id` 与 `blueprint_project_id` 并更新 skill 契约；无 runner 时 direct 保持 pending，不再轻量合成；ResearchService 在新 attempt/done 时清除旧 error。
- verification: 所有新增回归均经历 RED 后转 GREEN；最终全新测试库顺序执行 144 个相邻用例全部通过，ruff 全绿。live AGE-47 的两次伪确认线程均已 dismissed；两个异常仓经 deepseek-v4-flash 真实深调研完成。10/10 任务当前 done/error={}，均有责任、适配理由、现状与仓库引用；最终 Multica run b37d6f4f 通过同一幂等键复用 artifact、纠正 Space/Project metadata、发布 thread 16fdd366 的人类可读确认，并严格停在 blocked，未作答、批准或派发 Coding。临时模型映射已恢复为原 ops/claude-opus-4-8 配置。
- files_changed: `server/mcp_tools/orchestration_delegate.py`、`server/mcp_tools/technical_plan_service.py`、`server/mcp_tools/work_item_context_service.py`、`server/mcp_tools/serializers.py`、`server/services/process_runtime/entrypoint.py`、`server/services/process_runtime/blueprint_confirm_gate.py`、`server/services/process_runtime/blueprint_research_adapter.py`、`server/services/process_runtime/builtin_processes.py`、`server/services/process_runtime/blueprint_resume.py`、`server/delivery/services/research_service.py`、对应 process_runtime/MCP/delivery 回归测试与 schema/skill snapshots、`skills/skills/friday-solution/SKILL.md`、`skills/skills/friday-solution/references/http-fallback.md`
