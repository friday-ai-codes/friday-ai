---
phase: 67-concurrency
plan: 02
subsystem: llm-concurrency
tags: [provider-credential, rate-limit, redis-lease, semaphore, llm]
requires:
  - phase: "67-01"
    provides: "并发治理基线（SettingKeys / 设计约束）"
provides:
  - "ProviderCredential.max_concurrency（默认 50）+ 读写序列化器"
  - "agents/llm_concurrency.acquire_llm_slot（Redis 租约 + 进程内 fallback + LLMBusyError）"
  - "ResolvedProviderConfig.max_concurrency 透传 + 两 LLM chokepoint 限流接线"
affects: [chat / 深度分析 / 编码 LLM 调用]
tech-stack:
  added: []
  patterns:
    - "凭证级 LLM 限流：acquire_llm_slot(credential_id, max_concurrency) — Redis 租约信号量(sorted-set+Lua+TTL自愈+续租) 跨副本精确，无 Redis 进程内 asyncio.Semaphore fallback，Redis 故障 fail-soft 降级"
    - "超凭证上限排队等待至超时 → LLMBusyError 友好「系统繁忙」，不打 provider 429"
key-files:
  created:
    - server/agents/llm_concurrency.py
    - server/system/migrations/0008_providercredential_max_concurrency.py
    - server/tests/agents/test_llm_concurrency.py
  modified:
    - server/system/models.py
    - server/system/serializers.py
    - server/services/provider_config.py
    - server/agents/langchain_runner.py
    - server/agents/chat_runner.py
    - server/chat/config.py
    - server/friday/settings.py
status: complete
---

# Phase 67 Plan 02 Summary — CONC-02 凭证级 LLM 限流

- `ProviderCredential.max_concurrency`（`PositiveIntegerField` 默认 50，0=不限）+ migration `0008`；读序列化器 `fields` 暴露 + create（default 50）/update（required=False）序列化器可写。
- `ResolvedProviderConfig.max_concurrency` 字段（默认 0）在解析单一构造点从 `credential.max_concurrency` 透传，覆盖 langchain + chat 两路径。
- `agents/llm_concurrency.py`：`acquire_llm_slot(credential_id, max_concurrency)` async context manager —— max<=0/无 credential 时 no-op；配置 Redis 时用**租约信号量**（sorted-set + Lua 原子 acquire + `ZREMRANGEBYSCORE` TTL 自愈 + 持有期续租 task）跨副本精确；否则进程内 `asyncio.Semaphore` 按凭证 id keyed fallback；Redis 故障 fail-soft 降级进程内（绝不阻断 LLM）；等待超时抛 `LLMBusyError`（友好「系统繁忙」）。
- 两条 LLM chokepoint 接线：`LangChainAgentRunner.stream()` 内 astream 用 `async with acquire_llm_slot(...)`；`ChatAnthropicRunner.astream` 经薄包装生成器 `_astream_with_llm_slot`（避免重缩进庞大消费循环）。`ChatRunnerConfig` 增 `credential_id`/`max_concurrency`，由 `chat/config.py` 从 resolved 透传。
- settings：`LLM_CONCURRENCY_REDIS_URL`（默认仅在启用 channel-layer redis 时复用）/ `LLM_CONCURRENCY_ACQUIRE_TIMEOUT_SECONDS`（60）/ `LLM_CONCURRENCY_LEASE_TTL_SECONDS`（900）。

验收：`tests/agents/test_llm_concurrency.py` 7 例（no-op×2 / 容量限制 / 释放复用 / 容量内并发 / 凭证隔离 / 模型默认 50）；`test_provider_credential_api+model` 21 + `test_chat_config` 6 + `test_llm_factory`/`provider_config_v2` 等 191 零回归。
