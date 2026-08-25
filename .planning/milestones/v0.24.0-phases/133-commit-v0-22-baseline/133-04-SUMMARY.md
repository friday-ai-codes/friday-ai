---
phase: 133-commit-v0-22-baseline
plan: 04
status: complete
completed: 2026-08-24
requirements: [BENCH-01, BENCH-03]
commits: [d8461762, 795f7cb5]
---

# 133-04 执行摘要

交付 `evaluate_graph_bench` 只读 management command，将冻结 gold、三方水位闸、
v0.22 图能力和无阈值报告连接为可复现运行链路。

## 已完成

- 水位任一缺失或不一致时写 `INVALID` manifest、非零退出，并保证不调用图能力。
- OK 路径串行执行冷/热 `get_graph`、Symbol resolve、RAG、Process 候选、resolved
  CallEdge、impact 与 trace；单 case 异常脱敏后降级，不中断整轮。
- 输出 run identity、三方水位、可复现命令、逐 case/逐桶/overall 原始数据。
- `--min-bucket-samples` 实际参与桶状态和 overall 聚合。
- caller 生命周期与 sampling 事件满足 `duration_ms`、`component=codegraph`、
  `initiated_by_user_id=system` 和 best-effort 约束。
- 新增默认 fail-closed 套件与可选真仓 integration scaffold。

## 验证

- graph benchmark 套件：`72 passed`（最终增补后相关子集 `44 passed`）。
- integration：`1 test collected`；需真实已索引仓和 Qdrant 才能运行。
- Ruff：通过。
- 只读与无门禁字段静态守卫：通过。
- mypy：被 Python 3.14 + django-stubs 内部错误阻断；全仓另有 3 个既存文件的 5 项错误，
  未发现本计划文件的可定位类型错误。

## 偏差与债务

- 当前环境没有满足同 commit 三方水位的已索引验收仓，因此真仓 OK 路径记为人工验证债；
  按 autonomous 路由规则继续。
- token 继续复用既有 embedding/`ModelUsageRecord` 计量，CaseOutcome 当前记录 `0`；
  不新增平行计量通道。
