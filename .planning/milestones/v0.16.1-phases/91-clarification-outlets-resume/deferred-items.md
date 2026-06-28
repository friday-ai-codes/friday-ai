# Phase 91 Deferred Items

Out-of-scope discoveries logged during execution (not fixed — see SCOPE BOUNDARY).

## 91-02：执行期发现的既有失败（与本 plan 无关，war-room 未提交在制品）

`cd server && uv run pytest tests/workflows tests/delivery -q` 出现 10 failed / 1032 passed。
逐一基线回归（`git checkout 6e75293cb -- server/workflows/nodes/ai/plan_research.py server/agents/tools/plan_research_tools.py server/workflows/nodes/integrations/plan_deepen.py server/feishu/cards/chat_question_card.py` 后运行同 10 测 → **改动前已 100% 同样失败**，恢复文件后我的改动无回归）确认与 91-02 无关，源于工作区大量未提交 war-room 变更（`server/chat/`、`server/initiatives/`、`server/services/plan_orchestration/clarification_questions.py`、`web/` 等）：

| 测试 | 失败点 | 归因 |
|------|--------|------|
| `tests/workflows/test_execution_concurrency.py`（2） | pending_execution_blocks_new_start / concurrent_starts_allow_only_one | STATE.md 已记「既有并发测试欠债」 |
| `tests/workflows/test_template_loader.py`（2） | `technical_plan_generation` 模板 `notify_plan` 引用 `generate_plan`(ai_plan_generation) 输出缺 `plan_markdown` 字段 / acreate 校验 | war-room node-definitions / template 债（与本 plan 触碰的 ai_plan_research 无关） |
| `tests/delivery/test_comment_entry_wiring.py`（3） | comment handler 接线 | 90-03 SUMMARY 已记 war-room comment-wiring |
| `tests/delivery/test_entry_wiring.py`（1） | create handler delivery upsert 接线 | war-room |
| `tests/delivery/test_inv6_guard.py::test_inv6_no_bypass_feishu_chat_id_write`（1） | feishu_chat_id INV-6 守护 | war-room（59-01 范围外的未提交改动） |
| `tests/delivery/test_technical_plan_inv6_guard.py::test_inv6_no_bypass_canonical_plan_write`（1） | canonical plan INV-6 守护 | war-room |

**Action:** 不在 91-02 范围内修复；待 war-room 工作落定 / 后续 phase 收编时处理。

## 91-03：执行期复现同两项既有 INV-6 守护失败（与本 plan 无关）

`cd server && uv run pytest tests/delivery -k inv6 -q` → 2 failed / 26 passed。失败为 91-02 已记的同两项：

| 测试 | 旁路写命中文件 | 归因 |
|------|--------------|------|
| `test_inv6_no_bypass_feishu_chat_id_write` | `initiatives/services/project_service.py:365/404`（`project.feishu_chat_id = ...`） | war-room 未提交在制品（`git status` 标 `M server/initiatives/...`） |
| `test_inv6_no_bypass_canonical_plan_write` | `initiatives/services/plan_deepen_service.py:267`（docstring）/ `feishu/callbacks/plan_revision_callback.py:11`（89-02 既有 docstring 字面误判） | war-room + 既有 docstring false-positive |

**确认与 91-03 无关：** 命中文件均非本 plan 新增的 `feishu/callbacks/plan_clarify_callback.py`（该文件无 `.feishu_chat_id =` / 无 TechnicalPlan/PlanVersion 旁路写，守护未 flag）。本 plan 写入只经 `aanswer_round_and_resume` → `ClarificationService.answer_round`（INV-6）。不在 91-03 范围内修复。
