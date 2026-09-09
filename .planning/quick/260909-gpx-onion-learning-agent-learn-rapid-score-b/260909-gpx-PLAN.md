---
quick_id: 260909-gpx
status: in_progress
---

# 示例功能专项 V2 路径合并

1. 在 `frontend/onion-learning` 的 Agent 分支中，将新增应用完整迁移为
   `learn-rapid-score-boost-v2`，合并最新 `develop` 并保留原 V1 实现。
2. 在 `frontend/study-app` 的 Agent 分支中，将 Agent 新增入口跳转改为 V2，
   合并最新 `develop` 并保留原 V1 入口逻辑。
3. 执行相关 lint、类型检查和单元测试，推送两个分支，并将对应 MR 合入
   `develop`；回读 GitLab 合并状态。
