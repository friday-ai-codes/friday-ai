---
phase: 136-process-hybrid-index
plan: 02
status: complete
commit: c65e7022
requirements: [PROC-02, PROC-04, OBS-04]
---

# 136-02 摘要

新增 per-repository 独立 Qdrant collection，写入 dense+sparse named vectors；查询强制
repository/branch/generation/commit 四重过滤并返回 `lane=hybrid`。durable Process worker
显式透传并 re-bind `initiated_by_user_id` 后串联投影重建。
