---
slug: repo-association-signal-fusion
date: 2026-08-10
status: in-progress
---

# 项目选仓接入「章程 + 历史」三分量融合

来源：Cursor「Warehouse routing preferences」会话产出的未提交改动，本会话整理提交 + 复跑评测 + 诊断 study-course 召回。

## 任务

1. 提交工作区已完成的融合改动：
   - `server/initiatives/services/repo_association_service.py` — `propose` 接 `_fuse_extended_signals`（router_base + charter + history 按 brownfield 权重融合，best-effort 回退纯 router）
   - `server/services/process_runtime/blueprint_route_history.py` — `ascore_history_match` 增 `acting_user` 参数（fail-closed）
   - `server/tests/initiatives/test_repo_association_service.py` — 新增融合用例 + 留痕 `signal_fusion=charter+history`
2. 复跑仓库路由评测（高三提分专项，4 目标仓）
3. 诊断 study-course 为何进不了候选（Stage 0 召回天花板 vs GitLab master 实际内容）

## 验证

- `pytest tests/initiatives/test_repo_association_service.py` 全绿（已验证 7 passed）
