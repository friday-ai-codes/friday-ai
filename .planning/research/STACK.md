# Stack Research

**Domain:** Public MCP 全链路开放与长任务稳定性（Friday AI brownfield，v0.26.0）
**Researched:** 2026-09-14
**Confidence:** HIGH（锁文件与现有集成点）；MEDIUM（MCP Tasks / elicitation 在 Cursor·Claude Code 宿主上的覆盖——官方规范存在，但公共代理不得依赖宿主实现）

本文件只回答 **v0.26.0 要加/改哪些协议、库与配置**，不重研 RAG、runner、编码容器或前端栈。结论：**不引入新运行时依赖**；契约从「三份手写白名单」收成「服务端生成 + npm 消费」；长任务走既有 `process_runtime` + `DurableTaskService` 的 **应用层 job/轮询/幂等**，不要把稳定性押在 MCP Tasks 扩展或把 stdio `fetch` 超时拉到调研墙钟。

## Recommended Stack

### Core Technologies

| Technology | Version（锁文件） | Purpose | Why Recommended |
|------------|-------------------|---------|-----------------|
| Django + adrf MCP HTTP | Django `>=5.1`（`uv.lock` **6.0.1**）、`djangorestframework>=3.15`、`adrf>=0.1.12` | 公开工具面仍是 `POST /api/mcp/tools/{name}/`，PAT fail-closed | 外部 Agent 与容器 RemoteTool 已走此边界；新 HITL/诊断工具只加 view+serializer，不换传输层 |
| `@friday-ai-codes/mcp` stdio 代理 | 包 `0.6.0`；`@modelcontextprotocol/sdk` **1.29.0**（`mcp/pnpm-lock.yaml`）；Node `>=18` | Cursor / Claude Code / Codex 的公开 MCP | 宿主期望 stdio；现实现 `Server` + `StdioServerTransport` + `ListTools`/`CallTool`。保持 SDK **1.x**，与仓库 `mcp` Python **`<2`** 同代 |
| Python `mcp`（容器内 SDK MCP，非公开面） | `>=1.25.0,<2`；`uv.lock` **1.26.0** | `claude-agent-sdk==0.1.58` 的 `create_sdk_mcp_server` | **禁止升 2.x**：注释已写明 2.0 去掉 `@server.list_tools()`。公开 npm 包不要改成 Python FastMCP |
| `TOOL_SCHEMA_SNAPSHOT` + DRF Serializer | `jsonschema` **4.26.0**（`>=4.23.0`） | 工具名与请求/响应键的单一事实源 | 今日漂移根因是 `mcp/src/tools.ts` 静态 `FRIDAY_TOOLS`（测试仍断言 43 个）与 snapshot 手抄。v0.26 应用 **生成物** 替换手写 `inputSchema`，snapshot 仍作 CI 金标 |
| `services.process_runtime` | 现包，无新库 | spec / route / research / repo plan / merge / HITL 续驱 | 编排状态已可持久化恢复；MCP 只做入口与诊断投影，不在代理进程里跑蓝图 |
| `DurableTaskService` + Procrastinate | `procrastinate[django]>=3.8.1,<3.9`；锁 **3.8.1** | 长任务入队、rescue、诊断快照 | v0.12 已锁 at-least-once + 幂等；业务禁止 `import procrastinate`。MCP 发起调研/分仓计划后立刻返回 `session_id`/`job_id`，worker/runner 续跑 |
| PAT + `AccessTokenAuthentication` | 现 `friday_pat_` | 公开 MCP 与 HTTP 同一身份 | 不新增 OAuth MCP remote 授权服务器；令牌不进日志/stdio 错误文本（现 `server.ts` 已遵守） |

### Supporting Libraries

| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| `@modelcontextprotocol/sdk` `Server` + `StdioServerTransport` | **1.29.0** | JSON-RPC tools 原语 | 继续用现有 `setRequestHandler(ListToolsRequestSchema / CallToolRequestSchema)`。**不要**为了 `McpServer.registerTool` / `registerToolTask` 大迁 API——Tasks 宿主覆盖不可作为 v0.26 验收 |
| Node 内置 `fetch` + `AbortSignal.timeout` | 运行时 | HTTP 透传 | 拆超时：同步读工具短超时；**发起/轮询** 更短。现状全局 **120_000 ms** 会把「等调研」伪装成网络失败 |
| `jsonschema` | **4.26.0** | 生成 JSON Schema 与 snapshot 对拍 | 生成器跑在 Django 测试/管理命令里；npm 包 **不**加 zod 作为契约真源（SDK 已传递 zod 4.4.3，仅作 SDK 内部） |
| `structlog` | `>=25.5.0` | MCP caller 事件 + `duration_ms` | 新工具 `xxx_started/completed/failed`；`category=caller`；`component` 用现有 mcp 清单。观测 fail-soft |
| `tenacity` | 现依赖 | 仅服务端对 Git/飞书的既有重试 | **不要**在 npm 代理里加重试库：超时重试会对非幂等写工具双提交；幂等靠 `idempotency_key` + 服务端 CAS |
| `django-apscheduler` | `>=0.7.0` / **0.7.0** | 澄清过期、blueprint recovery 保险丝 | 与 durable rescue 分工保持现状；MCP 诊断面读这些状态，不新调度器 |
| `httpx` | `>=0.27` | 服务端出站 | 代理继续用 Node `fetch`，与现 `callFridayTool` 一致 |

### Development Tools

| Tool | Purpose | Notes |
|------|---------|-------|
| `test_schema_snapshot.py` | snapshot 键集 = 已发布契约 | 新 HITL/诊断/轮询工具必须同 PR 改 serializer + snapshot |
| `test_mcp_package_alignment.py` | `tools.ts` 名集 == snapshot | 生成后改为「生成物 vs snapshot」；禁止再手改 `FRIDAY_TOOLS` 过测试 |
| `test_skills_snapshot_guard.py` | SKILL.md ⊆ snapshot | 公开工具名进文档时必过 |
| `mcp` vitest + `tsdown` | 包测与构建 | `vitest@^4.1.8`、`tsdown@^0.22.2`、`typescript~5.9.3`；生成文件纳入 `src/` 并被 typecheck |
| MCP 规范（tools / progress） | 协议对齐参考 | [Tools](https://modelcontextprotocol.io/specification/2026-07-28/server/tools)、[Progress](https://modelcontextprotocol.io/specification/2026-07-28/basic/utilities/progress) |

## Installation

```bash
# 不新增运行时包。保持现有安装：
# server
#   mcp>=1.25.0,<2          # uv.lock: 1.26.0
#   procrastinate[django]>=3.8.1,<3.9   # uv.lock: 3.8.1
#   jsonschema>=4.23.0      # uv.lock: 4.26.0
# mcp npm
#   @modelcontextprotocol/sdk@1.29.0
#   不要 npm install 新依赖
```

契约生成（实现期，零新依赖）建议形态：

```bash
# 服务端：从 Serializer + TOOL_SCHEMA_SNAPSHOT 写出 JSON Catalog
cd server && uv run python manage.py export_mcp_tool_catalog --out ../mcp/src/generated/catalog.json

# npm：ListTools 优先 GET {baseUrl}/api/mcp/tools/catalog/（PAT），失败回落 bundled catalog.json
```

## Alternatives Considered

| Recommended | Alternative | When to Use Alternative |
|-------------|-------------|-------------------------|
| 应用层 `status=accepted\|running\|waiting_hitl\|completed\|failed` + 专用 get/retry 工具 | MCP Tasks（`execution.taskSupport` / `tasks/get` / SEP-2663） | 仅当 **Cursor 与 Claude Code 均**声明 Tasks 扩展且 canary 证明 `resultType: "task"` 不被当成错误。2026-07-28 规范仍在演进，SDK 1.29 的 task 路径与宿主覆盖 **不足以** 作为公开稳定性底座 |
| stdio npm 代理 + Django HTTP | 服务端 Streamable HTTP / SSE MCP（Python `mcp` FastMCP） | 将来做「无 Node 的远程 MCP」产品时再开里程碑；会撞 `mcp<2` 钉死、PAT 前缀闸门、以及 Cursor 默认 stdio 配置 |
| 生成 catalog + 运行时 `tools/list` 拉服务器 | 继续三处手写（serializer / snapshot / `FRIDAY_TOOLS`） | 仅热修单个字段的紧急 patch；v0.20–v0.22 已证明手写会漏工具 |
| Friday HITL 工具（answer / confirm / approve / dismiss finding） | MCP elicitation（`elicitation/create`） | 宿主未实现 elicitation 时流程卡死。蓝图确认门必须落 Friday 状态机，不能停在 JSON-RPC 中间请求 |
| `DurableTaskService` 既有队列 | Celery / RQ / Temporal / 新 Postgres LISTEN | 无：v0.12 明确适配层隔离；SQLite dev fallback 必须保留 |
| 同步工具保持 30–60s HTTP | 把 `REQUEST_TIMEOUT_MS` 提到 30–45min 等容器 | 超时会制造「未知结果」：代理报错但 runner 仍在跑。长工作必须先返回句柄 |

## What NOT to Use

| Avoid | Why | Use Instead |
|-------|-----|-------------|
| `mcp` Python **2.x** | 去掉 `claude-agent-sdk` 依赖的 `list_tools` 装饰器 | 钉死 `>=1.25.0,<2`（1.26.0） |
| `@modelcontextprotocol/sdk` **2.x / 2026-07-28 强制升级** | 未验证与 Cursor stdio 客户端兼容；Tasks/subscriptions 握手 fragile（SEP-2663 原文） | 锁 **1.29.0**；协议能力继续只声明 `{ tools: {} }` |
| FastMCP / 第二套 MCP 服务器 | 双面契约再漂移；鉴权绕过 `McpToolView` | 单一 HTTP 工具面 + npm 透传 |
| Celery、Dramatiq、Temporal、自定义 Redis 队列 | 与 Procrastinate 三套并存；业务会直接依赖实现 | `DurableTaskService.defer` + process_runtime resume |
| 在 npm 包加 `axios` / `zod` 契约 / `node-fetch` | 最小依赖；zod 若当 inputSchema 真源会与 DRF 再分裂 | 内置 `fetch`；schema 由服务端生成 |
| MCP `notifications/progress` 作为唯一进度面 | stdio 代理当前不转发 progressToken；宿主可能丢弃 | 轮询工具返回阶段枚举 + `poll_after_ms`；可选：代理若见到 `_meta.progressToken` 再 best-effort 转发（非验收门） |
| WebSocket MCP / GraphQL 工具网关 | 超出公开 MCP 与现有 ASGI 边界 | REST MCP + 既有 channels 仅服务 SPA |
| 为 catalog 引入 OpenAPI 代码生成器（openapi-typescript 等） | 又一层 schema 方言 | DRF 字段 → JSON Schema draft 的 **仓内小生成器** + `jsonschema` 校验 |
| 把 HITL 做成「模型在 tool result 里改蓝图正文」 | 违反 v0.20「AI 不覆盖人工 / finding 不走作答通道」 | 只暴露 `answer_*` / `approve_*` / `request_*_changes` / finding `resolve\|dismiss` |

## Stack Patterns by Variant

**If 工具是只读且 <10s（grep / rag / get_file / graph_query）：**
- 保持同步 `tools/call` → HTTP 200 JSON
- 代理超时可维持 ~60–120s
- Because 用户期望一次往返拿到证据

**If 工具会派容器 / durable worker / 飞书往返（research、repo plan、merge、execute）：**
- HTTP **必须**在秒级返回 `accepted`/`partial` + 稳定 id + `poll_after_ms` + 幂等键
- 配套 `get_*` / `retry_*` / 诊断工具；禁止在 view 内 `await` 调研墙钟
- Because `AbortSignal.timeout(120000)` 与 gunicorn/proxy idle 都会把结果变成未知态

**If 工具是 HITL 门（仓库确认、review finding、终审、退回）：**
- 写工具必须幂等（同一 artifact_version_id + content_hash 重复批准 = 同一结果）
- 状态只经既有 lifecycle/service（INV-6），MCP view 薄封装
- Because 门是领域状态机，不是 MCP elicitation 会话

**If 需要「工具列表随服务器版本变」：**
- `tools/list` 拉 catalog（带短 TTL 缓存）；bundled `catalog.json` 作离线回落
- **不要**宣称 `tools.listChanged: true` 除非代理真能在 stdio 上发 `notifications/tools/list_changed` 且宿主会重拉——Cursor 会话通常只在连接时 list 一次
- Because 规范允许动态 list，但 stdio 热更新对 IDE 宿主不可靠；生成物 + 对齐测试才是防漂移

**If 诊断/恢复：**
- 只读投影：blueprint stage、逐仓 task、callback、durable job、retry/recovery 枚举
- 写恢复：调用既有 `adrive_*` / `DurableTaskService.retry_stalled` 包装工具，带 `initiated_by_user_id`
- Because 恢复语义已在 process_runtime / durable，MCP 不要复制状态机

## Version Compatibility

| Package A | Compatible With | Notes |
|-----------|-----------------|-------|
| `@modelcontextprotocol/sdk@1.29.0` | Cursor / Claude Code stdio clients expecting MCP 2024–2025 tools 原语 | 锁文件已解析；`^1.29.0` 允许 1.x patch，**禁止无评估的 2.x** |
| `mcp==1.26.0` | `claude-agent-sdk==0.1.58` | 上下界 `<2` 是硬约束；server 与 task 两份 `pyproject.toml` 必须同钉 |
| `procrastinate==3.8.1` | Django **6.0.1**、`psycopg[binary]>=3.3`、Python 3.14 | 生产强制 Postgres；SQLite 走 in-process fallback，MCP 长任务在 dev 可能丢 job——诊断面须暴露 backend |
| `jsonschema==4.26.0` | 生成的 JSON Schema draft-07 风格 object | MCP tools `inputSchema` 必须是 JSON Schema object；不要输出 Zod |
| `adrf` async views | ASGI（uvicorn/daphne）；ORM 经 `sync_to_async` | 新 catalog GET 与工具 POST 保持 async；禁止在事件循环直接 ORM |
| npm `zod@4.4.3`（SDK 传递） | 仅 SDK 内部 | **不要**在 `mcp/package.json` 提升为直接依赖来写工具 schema |

## Integration Points（实现接线，非新库）

| 点 | 现状 | v0.26 栈动作 |
|----|------|----------------|
| `server/mcp_tools/serializers.py` `TOOL_SCHEMA_SNAPSHOT` | 手写请求/响应键 | 保持金标；生成 catalog 的输入 |
| `server/mcp_tools/views.py` | 每工具一个 `APIView` | 新 HITL/诊断/轮询 view；可选 `GET tools/catalog/` |
| `mcp/src/tools.ts` `FRIDAY_TOOLS` | 静态 43 工具，未知名直接拒绝 | 改为 bundled catalog ± 运行时拉取；**去掉「未知即拒绝」对服务器新工具的永久封死**（至少：服务器 404 才算未知） |
| `mcp/src/server.ts` `REQUEST_TIMEOUT_MS = 120_000` | 全局超时 | 按工具类拆分；长任务工具禁止同步等待 |
| `callFridayTool` + `X-Friday-Run-ID` | 会话级 ledger 串联 | 保留；轮询同一 `run_id` |
| `get_confirmed_blueprint_handoff` 落临时文件 | 大 payload 不进模型上下文 | 保留；新交接工具沿用「摘要 JSON + 本地文件」 |
| `process_runtime` 蓝图 11 态 / 确认门 | 领域真源 | MCP 控制面只调 service |
| `DurableTaskService` | 索引/摄取/部分 blueprint 恢复 | 长 MCP 作业的 enqueue/retry/诊断读模型，不新表引擎 |
| 可观测 | `begin_interaction_run` / `_record` | 新入口纳入 QPS；LLM 赋既有 `call_source` 枚举，不新框架 |

## Protocol / Config Changes（相对「加库」）

| 变更 | 建议 | 不要做 |
|------|------|--------|
| MCP capabilities | 维持 `{ tools: {} }` | 不要广告 `listChanged`/`tasks`/`elicitation` 直到宿主 canary 通过 |
| 异步契约字段 | 稳定：`job_id` 或既有 `session_id`、`status` 闭集、`poll_after_ms`、`idempotency_key`、`error_code` | 不要用 HTTP 504 表示「还在跑」 |
| npm 配置 | 现有 `FRIDAY_BASE_URL` / `FRIDAY_ACCESS_TOKEN` / `~/.friday/config.json` | 不要为 catalog 再发明第二套凭证 |
| 可选配置 | `FRIDAY_MCP_CATALOG_TTL_MS`、同步/轮询分超时 | 不要把调研超时写进代理 |
| 服务端超时 | 容器超时仍在 `blueprint_research_adapter`（30/45 min）等 | 不要让 MCP HTTP 对齐这些墙钟 |
| 幂等 | 扩展 `create_feishu_technical_plan` 已有 `idempotency_key` 模式到 start/retry | 不要客户端超时自动重放非幂等 execute |

## Sources

- `mcp/package.json` + `mcp/pnpm-lock.yaml` — `@modelcontextprotocol/sdk@1.29.0`，zod 传递 4.4.3 — **HIGH**
- `server/pyproject.toml` + `server/uv.lock` — `mcp==1.26.0`、`procrastinate==3.8.1`、`jsonschema==4.26.0`、`django==6.0.1`、`claude-agent-sdk==0.1.58` — **HIGH**
- `mcp/src/server.ts` — 120s `AbortSignal`、静态 `FRIDAY_TOOLS` 未知拒绝、stdio 透传 — **HIGH**
- `server/tests/mcp_tools/test_mcp_package_alignment.py` — 三面对齐守卫与历史漂移 — **HIGH**
- [MCP Tools spec 2026-07-28](https://modelcontextprotocol.io/specification/2026-07-28/server/tools) — `tools/list`、`listChanged` 需订阅流 — **HIGH**
- [MCP Progress](https://modelcontextprotocol.io/specification/2026-07-28/basic/utilities/progress) — `progressToken` 可选，完成后必须停发 — **HIGH**
- [MCP Tasks 2025-11-25](https://modelcontextprotocol.io/specification/2025-11-25/basic/utilities/tasks) 与 [SEP-2663](https://modelcontextprotocol.io/seps/2663-tasks-extension) — taskSupport 握手脆弱、扩展仍在改 — **MEDIUM**（故不作为 v0.26 底座）
- TypeScript SDK `McpServer` task 路径（`registerToolTask` / `taskSupport`）— 存在于当前 SDK 源码 — **MEDIUM**（公开代理未使用 `McpServer`）

---
*Stack research for: Friday AI v0.26.0 public MCP capability and stability*
*Researched: 2026-09-14*
