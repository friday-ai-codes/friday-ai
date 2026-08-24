---
phase: 133-commit-v0-22-baseline
status: human_needed
verified: 2026-08-24
score: 4/4
---

# Phase 133 验证

## 结论

四项 must-have 均有源码与自动化测试证据，阶段实现完整。真仓 OK 路径依赖外部已索引仓、
Qdrant 和同 commit 水位，当前未执行，状态按规则记 `human_needed` 并继续。

## 证据

1. 固定 run identity 与水位 fail-closed：默认套件覆盖 INVALID manifest、非零退出和
   `get_graph` 零调用。
2. 冻结 gold：manifest 与 dev/locked_test/holdout 均通过 schema 权威校验，holdout
   在 baseline command 中拒读。
3. 无阈值报告：纯函数 scorer、空结果规则、macro 聚合和运行时桶下限均有单测。
4. 薄 command：逐 case 编排 resolve/RAG/Process/edge/impact/trace，记录冷/热延迟并
   产 manifest 与 baseline JSON。

## 自动化结果

- `pytest ...graph_bench... --reuse-db`: 72 passed。
- review 修复后目标子集：44 passed。
- integration collect：1 collected。
- Ruff：通过。
- 只读/阈值禁词静态检查：通过。

## 人工验证债

使用满足三方水位的真实已索引仓执行
`test_graph_bench_real_repository_ok_path`，核验 Qdrant 召回、真实冷/热延迟和输出文件。
该债务不构成安全、数据损坏、构建或迁移 blocker。
