---
status: complete
---

# 示例功能专项 V2 路径合并结果

- `frontend/onion-learning`：Agent 应用迁移为
  `apps/learn-rapid-score-boost-v2`，保留 develop 原 V1 应用；MR
  `!1376` 已合入 develop，合并 SHA `83b0e56d2`。
- `frontend/study-app`：保留 `speedScoreBoostCamp` 原入口，新增
  `speedScoreBoostCampV2`，跳转
  `/onion-learning/learn-rapid-score-boost-v2`；MR `!5386` 已合入
  develop，合并 SHA `8d99c27c3e`。
- 验证：onion-learning V2 lint、41 个单元测试及 build 通过；
  study-app ESLint 与 16 个 V1/V2 共存、鉴权、跳转测试通过。
- onion-learning 仓库级 CI 的 `productmanual` 单测和
  `learn-topic-complete` E2E 存在与本次 V2 无关的 develop 既有失败；
  V2 自身检查通过后，以同一已解决冲突的 commit fast-forward 到 develop。
