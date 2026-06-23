---
phase: 67
slug: concurrency
status: passed
nyquist_compliant: true
wave_0_complete: true
created: 2026-06-23
---

# Phase 67 — Verification（并发治理：槽位锁池 / provider 限流 / 容器上限）

## Goal-Backward Verification

**Phase Goal:** 按资源分治引入可配置并发治理——索引/图谱用 Procrastinate 原生 `lock` 槽位锁池排队、LLM 按 provider 凭证各自限流、容器复用 runner.concurrent，跨 compose/k8s 多 worker 生效，不设全局总上限。

## Checks

| # | Success Criterion | Status | Evidence |
|---|-------------------|--------|----------|
| 1 | 批量索引同时 doing ≤ CONCURRENCY_INDEX_MAX（默认5），其余 todo 排队；图谱同理(默认3)；同仓不并发两索引（恒定同槽串行） | ✅ | `durable/concurrency.py` stable slot（md5）+ N 从设置读；5 入队点带 `lock=index/graph-slot-{N}`；`test_concurrency_locks`（稳定/范围/分布/clamp/设置读取） |
| 2 | DurableTaskService.defer/backends 支持 lock 透传，index/graph 入队带 lock=index-slot-{hash%N}，N 实时读、改值对新任务生效，不与 KEDA 形成空转环 | ✅ | defer 全链 lock 参数 → Procrastinate `configure_options['lock']`（与 queueing_lock 正交）；`test_procrastinate_backend_passes_lock_into_configure` |
| 3 | 每凭证 max_concurrency(默认50,0=不限)；chat/深度分析/编码 LLM 按凭证 id 限流(Redis 租约+进程内 fallback)，超限排队+超时友好「系统繁忙」，不打 429 | ✅ | `ProviderCredential.max_concurrency`+migration+序列化器；`acquire_llm_slot` Redis 租约/进程内 fallback/LLMBusyError；两 chokepoint 接线；`test_llm_concurrency` 7 例 |
| 4 | 容器并发受 runner.concurrent 约束且设置/文档可见；MCP 不受并发限制 | ✅ | 复用 `Runner.concurrent`（DB + Go scheduler 信号量）；`.env.example` 文档；MCP 无限流（`test_concurrency_governance` 无全局上限键 + runner.concurrent 存在） |
| 5 | 单 worker(compose) 与多 worker(k8s KEDA) 下分类并发上限均生效（跨进程，DB/队列原语非进程内信号量） | ✅ | index/graph 用 Procrastinate lock（DB 队列原语，跨进程）；LLM 配 Redis 时租约信号量跨副本；进程内仅无 Redis 的 fallback |

## Result

**PASSED** — 5/5 success criteria 满足。CONC-01/02/03 三波落地，38 例守护 + durable(71)/agents+provider(191)/chat_config(6) 零回归全绿；migration 0008 `makemigrations --check` 干净。

**Redis 租约信号量跨副本路径** 与 **真实多 worker/KEDA E2E** 需真实 Redis + 集群人工验收（deferred，代码层 must-haves 全过）。
