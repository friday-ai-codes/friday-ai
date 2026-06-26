# 87-04 SUMMARY — 复用/建群 + bot 入群 + CardKit 流式拆分卡片 + 多轮重拆回调（BOARD-02）

**Status:** ✅ Done · **Wave:** 3 · **Requirements:** BOARD-02 · **Tests:** 15 new pass / 31 regression pass

## 交付物（files）

新增：
- `server/initiatives/migrations/0009_project_feishu_chat_id.py` —— 纯 AddField `Project.feishu_chat_id`。
- `server/feishu/cards/board_split_card.py` —— `build_board_split_card`（schema 2.0 流式卡：可流式 `split_md` 元素 + 「开始创建」`board_split_start` + 输入框 + 「发送并重拆」`board_split_refine`）、`build_board_split_done_card`、`render_proposal_markdown`。
- `server/workflows/nodes/integrations/board_split_review.py` —— `BoardSplitReviewNode`（`node_type=board_split_review`, `is_blocking`, server_local）：拉群 + 流式发卡 + `waiting_event` + 持久化提案/轮次。
- `server/feishu/callbacks/board_split_callback.py` —— `@register_card_callback("board_split_")`：`board_split_start`（建看板 + 恢复）/ `board_split_refine`（多轮重拆 + 重发 + 保持等待）。
- 测试：`tests/initiatives/test_project_group_resolve.py`、`tests/workflows/test_board_split_review_node.py`、`tests/feishu/test_board_split_callback.py`。

修改：
- `server/initiatives/models/project.py` —— `feishu_chat_id` CharField(128, blank, default "")。
- `server/initiatives/services/project_service.py` —— `resolve_or_create_group`（复用命中 `feishu_chat_id`；否则 `create_chat` 建群 + `ensure_bot_in_chat` + `_writeback_chat_id_locked`（select_for_update 防并发双建）+ `AuditService.aemit`；建群异常 fail-soft 返回 ""）。
- `server/initiatives/services/board_split_service.py` + `feature_list_extractor.py` —— `propose_split`/`extract_structure`/`_aextract_chunk`/`_acall_llm` 新增 `extra_instruction` 透传（多轮重拆指令追加进系统提示，不污染正文）。
- `server/feishu/urls.py` —— import 注册 `board_split_callback`。

## 交互回路

复用项目群（`Project.feishu_chat_id` 命中即复用）→ 无群则 `create_chat` 建群 + bot 入群 + writeback（INV-6 经 ProjectService）→ 拆分提案以 CardKit 流式卡片下发（`create_card_entity → send_card_entity → stream_card_content(seq=1) → settle_card_stream(seq=2)`，流式失败 fail-soft 降级普通 `send_card`）→ 节点 `waiting_event` + 持久化 `{proposal, sources, work_item_type, chat_id, card_id, round, member_ids}`。回调：点「开始创建」→ 后台 `create_boards` + 发 done 卡 + `approve_node` 恢复；输入信息 → 后台 `propose_split(extra_instruction=输入)` + `round+1` + 重发流式卡 + 保持等待（不 approve）。

## 可观测 / 安全

- structlog 事件：`board_group_resolved`(caller, +duration_ms, reused/created)、`board_split_card_sent`、`board_split_card_action`(action/round, failed 分支)、`board_split_refine`(round)、`board_split_card_create_done`(created_count)。
- 回调重活 `_run_in_thread` 后台 `bind_task_context` re-bind `initiated_by_user_id`（触发飞书用户 open_id / system）。
- 脱敏：action_value 仅携 `execution_id/node_id/round/action`（不含 feature 原文）；异常文本经 `redact_secrets_in_text`。
- fail-soft：建群失败、流式失败、发卡失败、回调异常均吞掉不反噬主流程/飞书 3s 响应。

## [ASSUMED] / deferred（须 live-Feishu 校验）

- **schema 2.0 按钮/输入框/回调结构**：`build_board_split_card` 用 `behaviors:[{type:callback,value:{...}}]` + `form`/`input(name=refine_input)`，回调侧依赖 `CardCallbackView` 把 `action.value` + `form_value` 合并。真实 CardKit 2.0 交互元素 schema 与回调 payload 未真机验证 —— 经 respx-mock + 单测覆盖逻辑，live 抓包后回填 87-UAT.md。
- **多轮重拆重发**：跨轮 `sequence` 状态不持久化，重拆采用「新建卡片实体」而非续灌同一 `card_id`（规避 sequence 丢失），符合「或新发卡」分支。
- **写关系 relation_type 取值**：沿用 87-03 [ASSUMED] A-REL（1=项目跟踪，2=父子），未变。

## 验证命令

```
cd server && uv run pytest tests/initiatives/test_project_group_resolve.py tests/workflows/test_board_split_review_node.py tests/feishu/test_board_split_callback.py -q   # 15 passed
cd server && uv run python manage.py makemigrations initiatives --check --dry-run                                                                                      # No changes detected
```
