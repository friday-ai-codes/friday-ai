# Phase 62-01 Deferred / Out-of-Scope Items

执行 62-01 时发现、但**不属于本 plan 范围**（SCOPE BOUNDARY：仅修复本任务改动直接引发的问题）的预存问题，记录待后续处理：

## 1. `test_plan_session_inv6_guard.py::test_inv6_no_bypass_plan_session_write` 预存失败（误报）
- status: acknowledged


- **状态**：执行 62-01 前即失败（与本 plan 改动无关，非本 plan 触改文件）。
- **根因**：INV-6 守护正则 `\bPlanSession\s*\(`（`tests/delivery/test_plan_session_inv6_guard.py`）误命中**中文注释**——`server/chat/conversation_service.py:1922`：
  `# SDD spec 反查：conversation → PlanSession(软引用会话) 且其 current_plan_version`。
  该行为注释（非实例化/写表），属守护正则的 false-positive；`chat/conversation_service.py` 为已提交基线代码（工作树无 diff），与 62-01 无关。
- **建议修复（后续）**：守护扫描跳过注释行（行内 `#` 之后内容剥离后再匹配），或正则要求 `PlanSession(` 后紧跟可构造实参/赋值上下文，避免命中纯注释；属测试守护质量问题，不影响运行时 INV-6 约束。
