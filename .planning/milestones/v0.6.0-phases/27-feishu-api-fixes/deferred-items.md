# Phase 27 — Deferred / Out-of-Scope Discoveries

## Pre-existing test failure (NOT caused by 27-01)
- status: acknowledged


- **Test:** `tests/knowledge/test_triggers.py::TestCodingTriggers::test_coding_chat_pr_created_branch_delivers_once`
- **Error:** `django.core.exceptions.ValidationError: ['"[]"不是一个有效的UUID']`（在一条 coding-trigger 的关联查询里，`[]` 被当成 UUID 传入 FK lookup）。
- **验证：** 在父提交 `dccb2f54`（27-01 任何改动之前）以独立 worktree 复跑，**同样失败** → 确认与本 plan 无关（本 plan 仅新增 Django-free 解析模块 + 把 `KeyFields` 常量改为反向 import，字符串值字节不变）。
- **处置：** 超出 27-01 范围（SCOPE BOUNDARY），不在此修复。属 coding trigger 路径既有缺陷，留待相关 phase/quick task 处理。
