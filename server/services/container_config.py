"""容器配置常量 — 超时阈值、健康检查间隔等。
Phase 引入，支持不同任务类型的差异化超时配置。
"""
# 任务超时配置（秒）- 用户决策：coding 30min / explore 10min / ask 5min / plan 10min
TASK_TIMEOUTS = {
 "coding": 1800, # 30min - 代码任务需要更多时间
 "explore": 600, # 10min - 探索仓库
 "ask": 300, # 5min - 问答任务
 "plan": 600, # 10min - 计划生成
}
# 僵尸容器判定 - 120s 无心跳（用户决策）
ZOMBIE_HEARTBEAT_SECONDS = 120
# 健康检查频率 - 每 30s
HEALTH_CHECK_INTERVAL_SECONDS = 30
# 超时强制检查频率 - 每 60s
TIMEOUT_ENFORCE_INTERVAL_SECONDS = 60
