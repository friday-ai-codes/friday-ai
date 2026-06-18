"""可恢复任务基础设施。

为索引/图谱构建、工作流、AI 对话等长任务提供统一的"可恢复任务"真相源：
以 DB（Postgres/SQLite）为 checkpoint 权威源，进程或 Pod 重启后由
``RecoveryScheduler`` 从 DB 自动续跑（断电不丢）；Redis 仅在多副本部署时
做分布式锁 / 任务领取去重，不作为状态真相源。
"""
