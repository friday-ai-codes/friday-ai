# Phase 67: 并发治理（槽位锁池 / provider 限流 / 容器上限） - Context

**Gathered:** 2026-06-23
**Status:** Ready for planning
**Mode:** Smart discuss (autonomous — 按 STATE.md CONC 已锁决策实现)

> 目录名 `67-concurrency`（scaffold 默认 slug 偏移，内容以本文件为准）。

<domain>
## Phase Boundary

按资源分治引入可配置并发治理，**不设全局总上限**：
- **CONC-01 索引/图谱**：Procrastinate 原生 `lock` 槽位锁池排队（`lock=index-slot-{stable_hash(repo_id)%N}` / `graph-slot-...`，N 从 SystemSetting 实时读，默认索引 5/图谱 3）；超限原生留 todo 排队、worker 自动跳过、零空转、不与 KEDA 形成扩容反馈环；同仓恒定同槽天然串行防重复索引。
- **CONC-02 LLM**：每个 `ProviderCredential.max_concurrency`（默认 50，0=不限）；chat/深度分析/编码 LLM 调用按凭证 id 限流（Redis 租约信号量 + 进程内 fallback），超限排队 + 超时友好「系统繁忙」，不打 provider 429。
- **CONC-03 容器/MCP**：容器复用 `runner.concurrent`（已有 Go scheduler + server dispatcher）；MCP 不限；不设全局总上限。跨 compose 单 worker / k8s 多 worker 经 DB/队列原语生效。
</domain>

<decisions>
## Implementation Decisions

### CONC-01 槽位锁池
- `DurableBackend.defer` 协议 + `ProcrastinateBackend.defer`（`configure_options["lock"]`）+ `InProcessBackend.defer`（接受但忽略，dev 串行）+ `DurableTaskService.defer` 全链增 `lock` 参数；与 `queueing_lock`（=idempotency_key，todo 去重）正交并存。
- 新模块 `durable/concurrency.py`：稳定 slot 用 `hashlib.md5`（非内置 `hash()`，避免 PYTHONHASHSEED 逐进程漂移破坏「同仓同槽」），N<=0 clamp 到 1；async/sync 双读 SystemSetting helper。
- 5 处 index/graph defer 入队点（index_views/views/index_trigger_tasks/codegraph.views/resumable.handlers）全部带 `lock`。
- SettingKeys 新增 `CONCURRENCY_INDEX_MAX`（默认 5）/ `CONCURRENCY_GRAPH_MAX`（默认 3）。

### CONC-02 凭证级 LLM 限流
- `ProviderCredential.max_concurrency` 字段（默认 50，0=不限）+ migration 0008；读/写序列化器暴露（可配）。
- `ResolvedProviderConfig.max_concurrency` 透传（解析时从凭证取）；两条 LLM chokepoint（`LangChainAgentRunner.stream` + `ChatAnthropicRunner.astream`）发起前 `acquire_llm_slot(credential_id, max_concurrency)`。
- `agents/llm_concurrency.py`：Redis 租约信号量（sorted-set + Lua 原子 acquire + TTL 自愈 + 持有期续租）跨副本精确；无 Redis → 进程内 asyncio.Semaphore fallback；Redis 故障 fail-soft 降级进程内（绝不阻断 LLM）；超时抛 `LLMBusyError`（友好「系统繁忙」）。
- settings：`LLM_CONCURRENCY_REDIS_URL`（默认仅在启用 channel-layer redis 时复用）/ `LLM_CONCURRENCY_ACQUIRE_TIMEOUT_SECONDS`（60）/ `LLM_CONCURRENCY_LEASE_TTL_SECONDS`（900）。

### CONC-03 容器 / MCP / 无全局上限
- 容器并发复用既有 `Runner.concurrent`（DB 持久化 + Go scheduler `chan struct{}` 信号量）；MCP 不加任何限流；明确不建全局总并发上限设置项。
- 文档：`.env.example` 并发治理段（含索引/图谱/LLM/容器/MCP 说明 + 不设全局上限）。

### Claude's Discretion
- Redis 租约 Lua / 续租周期、轮询间隔等实现细节取最简正确者。
- 进程内信号量按凭证 id keyed，容量变化时按新容量重建。
</decisions>

<code_context>
## Existing Code Insights

### Reusable Assets
- `durable/service.py` `DurableTaskService.defer`、`durable/backends.py`（`configure_options` 唯一 configure 点）、`durable/queues.py`。
- `services/provider_config.py` `ResolvedProviderConfig`（带 credential_id）+ `aresolve_or_error` 单一构造点（覆盖 langchain + chat 两路径）。
- `agents/langchain_runner.py` `stream()` astream + `agents/chat_runner.py` `astream`（两 LLM chokepoint）。
- `system/models.py` `ProviderCredential` / `SettingKeys` / `SystemSetting`；`runners/models.py` `Runner.concurrent` + `runner/internal/scheduler` 信号量。

### Established Patterns
- durable 门面局部 import（避免循环依赖）；env.bool/env.int settings；SystemSetting async/sync 读。

### Integration Points
- 5 处 index/graph defer 入队点；两条 LLM stream chokepoint；ProviderCredential 序列化器。
</code_context>

<specifics>
## Specific Ideas
- 否决自造「DB 计数准入 + 延迟重投」——用 Procrastinate 原生 lock。
- LLM 上限挂每个凭证（各家限制不同，不共用一个数）。
</specifics>

<deferred>
## Deferred Ideas
- chat 超并发硬 429 / 全局总并发硬上限（明确非目标）。
- 图谱逐文件串行抽取异步解耦（GRAPHX-01）。
</deferred>
