---
status: human_needed
---
# 验证记录

代码验证通过：284项（readiness/确定性投影/review/reconcile/schema/RepoPlan/HTTP取件/确认事务），76项（merge+生命周期），MCP 30项+类型检查+构建。使用隔离SQLite与内存cache，不运行生产迁移。

新规则的反例包括提供方任务缺失、schema缺失/变化、字段来源漏项、建设任务缺失、延期裁决缺失、legacy不能正式就绪、丢失任务投影。确认事务与HTTP取件分别验证拒绝未就绪新版合同。MCP仅匹配四坐标/confirmed/任务数后落盘。

尚待：GitHub CI、源码合并/服务部署及完整真实业务验收。高三固定Mock只验证交接与下游，不声称已验证真实蓝图生成全链。

既有snapshot中primary_team/project_id与现有生产接口不一致，本次按源代码修订独立预期，不删除字段断言。
