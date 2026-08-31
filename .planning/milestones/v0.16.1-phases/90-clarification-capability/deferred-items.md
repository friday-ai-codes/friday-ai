# Deferred Items — Phase 90 Clarification Capability

Out-of-scope discoveries logged during execution (SCOPE BOUNDARY rule). NOT fixed here.

## 90-03 execution（2026-06-27）
- status: acknowledged


运行 `tests/services/plan_orchestration tests/delivery` 时发现 6 个失败，**全部与本 plan（澄清能力）无关**，源于工作树中并发未提交的 project-war-room / initiatives 改动（session 起始 git status 即含 `M server/initiatives/urls.py`、`M server/initiatives/views.py` 等）：

- `tests/delivery/test_comment_entry_wiring.py::test_comment_handler_wires_background_append`
- `tests/delivery/test_comment_entry_wiring.py::test_comment_handler_extracts_comment_id_from_alternate_key`
- `tests/delivery/test_comment_entry_wiring.py::test_comment_handler_missing_comment_id_warns_but_still_delivers`
- `tests/delivery/test_entry_wiring.py::test_create_handler_wires_delivery_upsert_and_keeps_ingestion`
- `tests/delivery/test_inv6_guard.py::test_inv6_no_bypass_feishu_chat_id_write`（指向 `initiatives/services/project_service.py:365,404` 旁路写 feishu_chat_id）
- `tests/delivery/test_technical_plan_inv6_guard.py::test_inv6_no_bypass_canonical_plan_write`

本 plan 仅触及 `clarify_adapter.py` / `resume.py` / `test_engine_clarify.py` / `test_plan_research_e2e.py`，与上述文件（initiatives/comment-wiring/entry-wiring/canonical-plan）无交集，故不在本 plan 修复范围。澄清相关测试全绿：`test_engine_clarify.py`(11) / `test_plan_research_e2e.py`(3) / `test_clarification_service.py`(14)。
