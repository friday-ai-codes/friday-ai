---
phase: 67-concurrency
plan: 03
subsystem: concurrency-docs
tags: [runner-concurrent, mcp, no-global-cap, env-docs, design-contract]
requires:
  - phase: "67-01"
  - phase: "67-02"
provides:
  - "并发治理 .env.example 文档段"
  - "并发治理设计契约守护测试"
affects: [部署文档, 设计契约]
tech-stack:
  added: []
  patterns:
    - "按资源分治、不设全局总上限：索引/图谱(槽位锁池) + LLM(凭证级) + 容器(runner.concurrent) + MCP(不限)"
key-files:
  created:
    - server/tests/durable/test_concurrency_governance.py
  modified:
    - .env.example
status: complete
---

# Phase 67 Plan 03 Summary — CONC-03 容器/MCP/无全局上限

- 容器并发复用既有 `Runner.concurrent`（DB 持久化 + Go scheduler `chan struct{}` 信号量约束，零新增）；MCP 工具调用不加任何限流；明确不建全局总并发上限设置项。
- `.env.example` 新增「并发治理」段：索引/图谱槽位锁池上限（`concurrency_index_max`/`concurrency_graph_max`）、LLM 凭证级限流三参（`LLM_CONCURRENCY_*`）、容器 `FRIDAY_RUNNER_CONCURRENT`、MCP 不限、不设全局上限说明；跨 compose 单 worker / k8s 多 worker 经 DB/队列原语生效。
- `tests/durable/test_concurrency_governance.py` 设计契约守护：defer 全链含 lock 参数 / 索引图谱设置键存在 / 凭证 max_concurrency 默认 50 / Runner.concurrent 存在 / 无全局总并发上限设置键。

验收：`test_concurrency_governance.py` 5 例 + 整 phase 38 例全绿。
