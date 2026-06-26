# 88-04 SUMMARY — CardKit 仓库关联四态卡 + RepoAssociationNode + associate_repos 工具

**Plan:** 88-04（Phase 88 智能业务关联仓库，milestone v0.16.0）
**Requirements:** REPO-01 / REPO-02
**Status:** ✅ Done

## 交付物

### 1. CardKit 四态卡片 — `server/feishu/cards/repo_association_card.py`（NEW）
镜像 `board_split_card.py`（schema 2.0 流式卡 + action_value 仅携路由 ID 范式）：
- `build_repo_assoc_card`：**候选卡**（schema 2.0，`streaming_mode=True`，含可流式 `repo_md` 元素 +「确认这些仓库」按钮[携选中 `repo_ids`]/「补充澄清」输入框）。
- `build_repo_assoc_verifying_card`：**验证进行中卡**（grey，逐仓深验中）。
- `build_repo_assoc_mismatch_card`：**不符回退卡**（mismatch 仓 + `repo_assoc_accept_mismatch`/`repo_assoc_reconfirm` 两动作）。
- `build_repo_assoc_done_card`：**最终确认终态卡**（green，verified 仓 + verdict 摘要）。
- `render_candidates_markdown` / `render_verdicts_markdown`：流式正文渲染。
- action_value 绝不携 feature 正文 / verdict 全文，仅 `execution_id/node_id/round/action`（+ confirm 携 `repo_ids` 路由 ID 列表），T-88-04-INFO 脱敏。

### 2. RepoAssociationNode — `server/workflows/nodes/integrations/repo_association.py`（NEW）
`node_type="repo_association"`，`is_blocking`，INTEGRATION，@register_node 自动注册；outputs=`verified/reconfirm/timeout/error`。三分支（据 `node_execution.output_data` 标记）：
- **① 首发**（无标记）：resolve_space/project/initiator → `resolve_or_create_group` → `RepoAssociationService.propose` → CardKit 流式候选卡 → `WorkflowEventSubscription(event_type="RepoAssocCallback")` 超时兜底 → `waiting_event`（output_data: proposal/sources/chat_id/round=1/stage="clarify"），逐字镜像 `BoardSplitReviewNode`。
- **② 确认派发**（`output_data._confirmed_repo_ids`）：`confirm_repos` → `dispatch_verify`（透传本节点 `node_execution_id` 使容器完成回调经 `_schedule_workflow_resume` 续驱本节点）→ 验证进行中卡 → `waiting_event`(stage="verifying")。**满足 LOCKED「verify dispatch」**。
- **③ 续驱聚合**（`output_data._resume_from_callback`，容器深验完成重入）：`collect_verdicts` → 有 mismatch 发回退卡 + 保持 `waiting_event`(stage="reconfirm")；全 fit/可接受发终态卡 → `completed` 走 `verified` handle。整段 fail-soft（异常 swallow+warning，不回 5xx，mirror AICodingNode._resume_wave）。
- 观测：`initiated_by_user_id` 取 `triggered_by_id`（缺 system）透传 service/dispatch；事件 `repo_association_card_sent` / `repo_association_confirm_dispatched` / `repo_association_resume`(+duration_ms) / `repo_association_stream_fallback`；发卡 best-effort。

### 3. associate_repos 工具 — `server/agents/tools/repo_association_tools.py`（NEW）
`@tool(category=PROJECT)` 薄委托 `RepoAssociationService`（与节点**共用同一 service**，无第二套选仓实现）：有 `extra_instruction` 走 `refine`，否则 `propose`；`space_id` 由 MCP 适配层注入（LLM 不可见，mirror `split_feature_list_to_boards`）；归因透传。已在 `agents/tools/__init__.py` 注册导出。

### 测试（NEW）
- `server/tests/feishu/test_repo_association_card.py`（8）：四态卡结构 + action_value 仅携路由 ID（断言不含命中理由长串）+ confirm 携 repo_ids + mismatch 两动作。
- `server/tests/workflows/test_repo_association_node.py`（12）：自动注册 + 端口；首发 waiting_event/stage=clarify + 建 `WorkflowEventSubscription`；无输入/无群 fail；确认派发 dispatch_verify（透传 node_execution_id）；续驱 mismatch→reconfirm/全 fit→completed verified；发卡失败 fail-soft；续驱异常 fail-soft；工具注册 + 共用 service。

## 测试结果
- `tests/workflows/test_repo_association_node.py tests/feishu/test_repo_association_card.py`：**20 passed**。
- `tests/initiatives/test_repo_association_inv6_guard.py`：**2 passed**（修正工具 docstring `RepoAssociation(` 字面量触发 INV-6 grep）。
- `tests/agents`：**146 passed**（工具新增导入无回退）。
- `tests/workflows tests/feishu`：629 passed，2 failed — `test_execution_concurrency.py`（`test_pending_execution_blocks_new_start` / `test_concurrent_starts_allow_only_one`），**与本plan无关**（隔离运行同样失败，SQLite 测试库下 WorkflowEngine start-locking 既有环境失败）。

## [ASSUMED] / Deferred
- **确认回调（confirm callback）**未在本 plan 文件清单内（88-04 `files_modified` 无 callback）。节点已实现并直测「确认派发」分支（读 `output_data._confirmed_repo_ids` 触发 dispatch_verify），写入该标记并重入节点的卡片回调留待后续（88-05）接线。
- **「置 status=verified（经 service）」**：per-repo `verified` 在容器回调 `record_verdict`（RepoAssociationService，INV-6 唯一写口）时已落地；续驱节点只读 `collect_verdicts` 聚合并发终态卡，不旁路写状态（守 INV-6，且 `repo_association_service.py` 不在本 plan 改动范围）。

## Blockers
无。
