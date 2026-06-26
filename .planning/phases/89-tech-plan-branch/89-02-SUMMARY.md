# 89-02 SUMMARY — 方案修订回路（调研问题发现卡 + 补充修订 supersedes + 仓库关联同步）

**Plan:** 89-02 (Phase 89 技术方案深化，milestone v0.16.0，PLAN-02)
**Status:** ✅ Done — 20/20 新单测绿；feishu + plan_deepen 全量 82 绿；ruff + mypy 通过。

## 交付物（files）

### EXTEND
- `server/initiatives/services/plan_deepen_service.py`
  - `detect_revision(*, observed_change_text, session_or_plan=None, initiated_by_user_id="system") -> dict`：
    经 `use_call_source(CallSource.PLAN_REVISION)`（89-01 已注册，未触碰 `call_source.py`）LLM 研判
    执行中观测要改/增/删哪些仓 + `plan_delta_summary`；观测文本入 prompt 前 `redact_secrets_in_text`
    脱敏 + 截断（4000 char 预算）；LLM 用量经 `arecord_llm_usage(call_source=plan_revision)` 留痕。
    全段 best-effort——空观测 / provider 缺省 / 调用 / 解析任一失败 → 空结构，绝不反噬主链。
  - `apply_supplement_revision(*, plan, revision, project=None, actor=None, initiated_by_user_id) -> PlanVersion`：
    ① 取 canonical `current_version.content`，把 `plan_delta_summary` 折进 `summary` →
    经 **`TechnicalPlanService.add_version`** 加 `PlanVersion(supersedes=current)`（delta 为空则
    content 不变 → content_hash 相等 service 幂等不翻版本，复用 v0.7 版本链，**绝不**新建
    `PlanRevision` 模型）；② 调 `_sync_repo_associations` 经 88 service 同步关联。
  - `_sync_repo_associations`：add → `confirm_repos`、remove → `reopen_candidates`（逐 assoc）、
    change → `dispatch_verify`，全经 **`RepoAssociationService`** 写收口（INV-6）；无 project 跳过；
    任一失败 fail-soft 吞为 warning，不反噬补充修订版本。
  - 辅助：`_aget_plan_content` / `_merge_delta_into_content`（纯函数）/ `_aload_associations`
    （`sync_to_async` 只读）+ 模块级 `_content_to_text` / `_parse_revision_json`（健壮 JSON 解析）。

### NEW
- `server/feishu/cards/plan_revision_card.py`：`build_plan_revision_card`（「调研问题发现」问询卡，
  列改/增/删仓 + 修订要点 + 确认/调整/取消三动作）+ `build_plan_revision_done_card`（补充修订完成/
  取消收尾卡）+ `render_revision_markdown`。`action_value` 仅携 `execution_id`/`node_id`/`round`/
  `action`，绝不携方案正文（T-89-02-INFO）。
- `server/feishu/callbacks/plan_revision_callback.py`：`@register_card_callback("plan_revision_")` FSM：
  - `plan_revision_confirm` → `apply_supplement_revision`（加版本 + 关联同步）→ 终态卡 → `approve_node` 恢复；
  - `plan_revision_adjust` → 把用户调整并进观测重 `detect_revision` → `output_data` round+1 + 新 revision →
    重发「调研问题发现」卡 → **保持 waiting**（不 approve，多轮优雅）；
  - `plan_revision_cancel` → 不修订保持原方案 → 取消卡 → `approve_node` 恢复。
  - 同步轻 ack（3s 内）+ `_run_in_thread` + `bind_task_context(callback.user_open_id)`；全段 try/except
    fail-soft（失败记 `plan_revision_*`(failed) 脱敏，不反噬飞书响应）；非 waiting 幂等 no-op；写零旁路。

### EXTEND
- `server/feishu/urls.py`：import `plan_revision_callback`（触发注册，仅本行 hunk）。

### TESTS（NEW）
- `server/tests/initiatives/test_plan_revision_service.py`（8）：detect_revision 经 use_call_source
  (plan_revision)（ainvoke 内 `get_call_source` 命中）+ arecord_llm_usage 被调 + 产物归一化；空观测/
  LLM 失败 → 空结构 fail-soft；apply_supplement_revision 经 `TechnicalPlanService.add_version` 加版本
  （delta 折入 summary）；delta 为空 content 不变（幂等）；add/remove/change 分别触发
  `RepoAssociationService.{confirm_repos,reopen_candidates,dispatch_verify}`；无 project 跳过；同步失败 fail-soft。
- `server/tests/feishu/test_plan_revision_callback.py`（12）：前缀注册唯一；同步入口 confirm/adjust/cancel
  调度 + ack（adjust 缺输入不调度、缺 ids/未知动作 → None）；confirm → apply_supplement_revision 被调 +
  approve_node（非 waiting 幂等、service 抛 → fail-soft 不 approve）；adjust → detect_revision + round+1 +
  保持 waiting；cancel → 不修订 + approve_node。

## 锁定决策落地（LOCKED）
- 修订回路 调研问题发现 card → 补充修订 **`PlanVersion.supersedes`**（v0.7 版本链复用，零新模型）+
  仓库关联同步经 **88 `RepoAssociationService`**（多轮，fail-soft 优雅）。✅
- 检测 LLM 用 **`plan_revision` call_source**（89-01 已注册，本 plan 未触碰 `call_source.py`）。✅
- 卡片 FSM 逐字镜像 87/88（`@register_card_callback` + `_run_in_thread` + `bind_task_context` + 澄清/
  重算保持 waiting、确认/取消 approve_node；action_value 仅路由 ID）。✅
- INV-6 收口（写经 `TechnicalPlanService`/`RepoAssociationService`，回调零旁路写表）+ fail-soft。✅

## 测试结果
- `uv run pytest tests/initiatives/test_plan_revision_service.py tests/feishu/test_plan_revision_callback.py -q` → **20 passed**。
- `uv run pytest tests/initiatives/test_plan_deepen_service.py tests/feishu/ -q` → **82 passed**（无回归）。
- `uv run ruff check <新/改文件>` → All checks passed；`uv run mypy <3 新源文件>` → Success: no issues。

## 偏差 / [ASSUMED]
- **前缀偏差（必要）**：PLAN 写 `plan_revise_`，但 `plan_callback.py` 已注册 `plan_revise`，而
  `CardCallbackView` 用 `action_name.startswith(prefix)` 路由 → `"plan_revise_confirm".startswith("plan_revise")`
  为 True 会被旧 handler 抢路由。为满足 LOCKED「前缀唯一」，改用 **`plan_revision_`**
  （`"plan_revision_*".startswith("plan_revise")` 为 False，二者互不抢路由，已加测试守护）。
- **[ASSUMED] 关联同步语义映射**：add→confirm_repos / remove→reopen_candidates / change→dispatch_verify
  （选用 88 既有写收口方法，best-effort）。精确语义（如 add 新仓需先 propose）留运行时 + 89-UAT 真机验证。
- **[ASSUMED] plan 定位**：回调经 `output_data.plan_id` 解析 canonical `TechnicalPlan`（PlanDeepenNode
  落 plan_id 的契约由 89-01/节点保证）；缺失 → fail-soft 记 failed 不恢复。
- **CardKit 真机**：流式/真实飞书卡片 + 真实 LLM detect E2E 经 respx/seam 覆盖，真机 deferred 记 89-UAT.md（对齐 87/88）。

## Blockers
- 无。89-03（chat/resumable 容器挂起）并行、文件互斥，仅暂存本 plan 6 文件 + 本 SUMMARY，未触碰
  `call_source.py` / `skills` / 89-03 文件。
