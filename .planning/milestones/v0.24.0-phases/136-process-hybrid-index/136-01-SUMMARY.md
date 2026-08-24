---
phase: 136-process-hybrid-index
plan: 01
status: complete
commit: c65e7022
requirements: [PROC-01, PROC-03, PROC-05]
---

# 136-01 摘要

ProcessTrace 可确定性生成入口、终点、模块、业务关键词和完整有序 steps 文档；steps 补齐
1-based `start_line/end_line`。generation 绑定 repository/branch/commit/schema version，
point id 稳定，重跑幂等。
