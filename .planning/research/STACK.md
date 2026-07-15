# Stack Research — v0.17.0 统一知识库与全链路联动

**Domain:** brownfield 增量（容器内 HTTP 代理型 MCP server / skills 物料注入 / LLM 自动提炼 learning case）
**Researched:** 2026-07-15
**Confidence:** HIGH（版本信息全部经本仓 `uv.lock` / `pyproject.toml` / 已安装 site-packages 源码核实；SDK 行为经生产代码既有用法佐证）

## 结论先行（TL;DR）

**三件事全部零新增依赖。** 既有栈完整覆盖：

1. **容器内 HTTP 代理型进程内 MCP server** → 完全复用 `claude-agent-sdk==0.1.58` 的 `create_sdk_mcp_server` + `SdkMcpTool` + `httpx`，蓝本就是 `task/core/remote_tools.py`（生产已验证的同构实现）。
2. **skills 物料注入容器 `.claude/skills/`** → 纯文件拷贝（stdlib `shutil`），加载机制 `setting_sources=["project"]` 已在 v0.9.0 openspec 特性中验证。唯一坑在**构建上下文**（见下）。
3. **LLM 自动提炼 learning case** → 服务端复用 `agents.llm_factory.build_chat_model` seam（langchain 栈已锁定），参考实现 `server/initiatives/services/memory_distill.py` 是同构先例。

## Recommended Stack（既有版本，全部已锁定，无需变更）

### Core Technologies

| Technology | Version | Purpose | 核实来源 |
|------------|---------|---------|---------|
| claude-agent-sdk | **==0.1.58**（pinned） | 容器内编码代理 + 进程内 SDK MCP server | `task/pyproject.toml:12`、`task/uv.lock:79`、`server/uv.lock:473`；bundled CLI **2.1.97**（`_cli_version.py`） |
| httpx | >=0.27.0 | MCP handler 内转调服务端 `/api/mcp/tools/*` | `task/pyproject.toml:7`（task 侧已有，remote_tools.py 已在用） |
| mcp（transitive） | 经 claude-agent-sdk 带入 | SDK MCP server 底层协议实现 | `task/uv.lock:83`（`claude-agent-sdk` 的 dependencies 含 `mcp`，**不需要也不应显式声明**） |
| structlog | >=24.1.0 (task) / >=25.5.0 (server) | 观测埋点（RetrievalTrace/事件） | 两侧 pyproject 均已有 |
| langchain + langchain-anthropic 等 | langchain>=1.2.15、langchain-anthropic>=1.3.5 | 服务端 LLM 提炼 learning case | `server/pyproject.toml:69-75`，经 `build_chat_model` 统一 seam |

### 无需任何 `pip install` / 依赖文件改动

```bash
# task/pyproject.toml — 不动
# server/pyproject.toml — 不动
# skills/package.json — 不动（物料同源引用，非运行时依赖）
```

## 关键问题逐一回答

### Q1: claude-agent-sdk 0.1.x 的 McpServerConfig 支持哪些形态？

**四种形态全部支持**（经已安装 `claude_agent_sdk/types.py:549-584` 逐行核实）：

| 形态 | TypedDict | 关键字段 | 本里程碑是否使用 |
|------|-----------|---------|-----------------|
| 进程内 SDK server | `McpSdkServerConfig` | `type:"sdk"`, `name`, `instance:McpServer` | ✅ **用这个**（`create_sdk_mcp_server` 产出） |
| stdio 子进程 | `McpStdioServerConfig` | `command`, `args`, `env`（type 可省略，向后兼容） | ❌ 不用 |
| SSE 远程 | `McpSSEServerConfig` | `type:"sse"`, `url`, `headers` | ❌ 不用（见 Q3 陷阱） |
| Streamable HTTP 远程 | `McpHttpServerConfig` | `type:"http"`, `url`, `headers` | ❌ 不用（见 Q3 陷阱） |

`create_sdk_mcp_server(name, version="1.0.0", tools: list[SdkMcpTool])` 返回 `McpSdkServerConfig`，传入 `ClaudeAgentOptions.mcp_servers`（`dict[str, McpServerConfig]`，`types.py:1181`）。工具可用 `@tool` 装饰器**或直接构造 `SdkMcpTool`**——本仓惯例是后者（`remote_tools.py:174-181`、executor.py repo-summary 均直接构造），新代码保持一致。

### Q2: 容器内"HTTP 代理型进程内 MCP server"怎么做？

**照抄 `task/core/remote_tools.py` 的模式**（该文件就是生产验证的"进程内 SDK MCP server + httpx 转调服务端"实现）：

- 每个白名单工具 → 一个 `SdkMcpTool(name, description, input_schema, handler)`；
- handler 内 `httpx.AsyncClient` POST 服务端端点，PAT 走 `Authorization: Bearer`（只进 header，绝不进日志——RTOOL-03 约定沿用）；
- handler **永不 raise**，401/403/非 200/传输错误/坏 JSON 一律 return `{"content":[{"type":"text","text":...}], "is_error": True}`（RTOOL-04 约定沿用）；
- 挂载走 `executor.py:_execute_claude` 既有 `extra_mcp_servers` / `extra_allowed_tools` 参数（Phase 47 ask_user 同机制）；
- `allowed_tools` 命名格式 `mcp__{server_name}__{tool_name}`。

**与 RemoteTool 的一个差异要注意**：RemoteTool 打统一端点 `/api/tools/execute/`（body 带 `{name, arguments}`）；而知识 MCP 目标是 `/api/mcp/tools/<tool_name>/` **每工具一个 URL**（`server/mcp_tools/urls.py:39+`），响应体 schema 也不同。新建 `task/core/knowledge_tools.py`（或等价文件）实现 `build_knowledge_mcp_server`，不要硬塞进 remote_tools.py 的统一端点假设里。

**配置下发**：复用 `TaskConfig` 的 `FRIDAY_TASK_*` env 映射机制（pydantic-settings `env_prefix`，`task/core/config.py:23`）——新增如 `FRIDAY_TASK_KNOWLEDGE_TOOLS_ENDPOINT` / 白名单开关字段即可；PAT 复用既有 `user_token`（server→runner→task 直传链路已在，`server/workflows/nodes/ai/coding.py` 是派发侧注入点）。

### Q3: 版本约束与已知坑

| 坑 | 影响版本 | 0.1.58 状态 | 证据 |
|----|---------|------------|------|
| `query()` string prompt + SDK MCP server 崩 `CLIConnectionError: ProcessTransport is not ready for writing`（stdin 在 MCP handshake 前被关） | < 0.1.53 | ✅ 已修复。`wait_for_result_and_end_input()` 在有 sdk_mcp_servers/hooks 时等首个 result 再关 stdin | 已安装源码 `_internal/query.py:689-707`；上游 issue #578/#817（修复于 0.1.53, PR #780） |
| SDK MCP 工具调用 ~60-70s 后 `Stream closed`（stdin 关闭超时） | 0.1.47 前后若干版本 | ✅ 已修复。0.1.58 的实现**无超时**（docstring 明确 "no timeout is applied"） | `_internal/query.py:694-696`；上游 issue #676/#730（PR #731 移除超时） |
| `allowed_tools` 是**排他白名单**：一旦非空，未列入的内建工具（Bash/Edit/Write）全被禁 | 所有版本（设计如此） | ⚠️ 必须把 `_BUILTIN_CODING_TOOLS` 与新 MCP 工具一并列入 | 本仓 WR-02 教训，`executor.py:50-54` 注释 + 去重逻辑已内置 |
| 工具 handler 返回值 shape 必须是 `{"content":[...], "is_error": bool}`，raise 会崩容器 | 所有版本 | ⚠️ 沿用 remote_tools 的"永不 raise"纪律 | `remote_tools.py` RTOOL-04 |
| `McpHttpServerConfig`/`McpSSEServerConfig` 期望对端是 **MCP streamable-HTTP/SSE 协议 server** | — | ❌ **不能**直接指向 `/api/mcp/tools/*`——那是普通 REST 每工具端点，不是 MCP 协议端点。若用 type:"http" 需服务端另实现 MCP streamable-HTTP 协议层，纯属多余 | `types.py:558-571` + `server/mcp_tools/urls.py`（DRF View，非 MCP 协议） |

**升级风险**：不要为本里程碑升级 claude-agent-sdk。0.1.58 双侧（server/task）锁定一致，生产已用 `query()` + string prompt + 最多 3 个并存 SDK MCP server（remote-tools / ask_user / repo-summary），新增第 4 个（knowledge）走完全相同路径，无新风险面。`>=0.1.58,<0.2` 的 server 侧约束保持不动。

### Q4: skills 物料注入 `.claude/skills/`

**加载机制零改动**：`executor.py:597` 已设 `setting_sources=["project"]`，agent 会原生加载 workspace 下 `.claude/skills/`（v0.9.0 openspec 特性已验证该路径生效）。注入 = 在 clone 完成后、agent 启动前把 `friday-code` / `friday-memory` 物料（`SKILL.md` + `references/`）拷进 `<workspace>/.claude/skills/<name>/`——纯 stdlib（`shutil.copytree`），**不需要新依赖**。注入点建议放 `task/git_ops/operations.py` clone 后处理链（与 exclude prune 同段）或 runner.py 准备阶段。

**唯一真实的坑：Docker 构建上下文**。task 镜像 build context 是 `./task`（`docker-compose.build.yaml:43`、`.github/workflows/release.yaml:34`），仓库根 `skills/skills/` 在 context 之外，`COPY ../skills` 不可行。可选方案：

- **推荐**：构建前同步脚本把 `skills/skills/{friday-code,friday-memory}` 复制进 `task/assets/skills/`（Makefile `build-task` 与 CI release job 各加一步），Dockerfile 加一行 COPY；配套**hash 一致性测试**（容器物料 == 包内文件，对应 MILESTONE-CONTEXT 风险 4），防两套漂移。
- 备选：改 CI/compose 的 build context 为仓库根 —— 改动面大（缓存/`.dockerignore`/三处构建入口），不值得。
- 不推荐：运行时从服务端 HTTP 拉取物料 —— 引入启动时网络依赖与失败面，物料是静态小文件，没必要。

注意与仓库自带 `.claude/skills/` **共存不覆盖**（目标目录已存在同名 skill 时跳过，MILESTONE-CONTEXT 已定此约束）。

### Q5: LLM 自动提炼 learning case

**服务端实现，零新增依赖**，且有同构先例可整段参考——`server/initiatives/services/memory_distill.py`（MEM-04，LLM 提炼记忆草稿）已把该模式全部踩通：

- LLM 调用经 `agents.llm_factory.build_chat_model` 统一 seam（langchain `ChatAnthropic` 等，凭证走 `ProviderConfigService`，**不走 env**）；
- `call_source` 经 `agents.call_source.CallSource` + `use_call_source` 上下文注入 —— 需新增枚举值（如 `learning_case_distill`）并登记 LOGGING-SPEC §4.1；
- usage 上报经 `interactions.ledger.arecord_llm_usage`（请求/token/TTFT/上游错误码，best-effort）；
- 输出脱敏经 `common.logging.redact_secrets_in_text`；
- 整体 fail-soft：缺凭证/异常返回 None，不阻断编码回调主流程。

触发点挂 `server/subagent/api/callbacks.py`（编码完成回调），入库走 `create_learning_case` 既有单一入口 + `knowledge/sources/` 新 normalizer 投递 `IngestionRequest`（均为既有机制扩展，非新依赖）。

## What NOT to Add（明确不要引入）

| 不要引入 | 原因 | 用什么替代 |
|---------|------|-----------|
| `fastmcp` / 独立 `mcp` 显式依赖 | `mcp` 已是 claude-agent-sdk 的传递依赖；进程内 server 由 SDK 封装，直接用协议库是绕过既有抽象 | `create_sdk_mcp_server` + `SdkMcpTool` |
| 服务端 MCP streamable-HTTP 协议层（如 `mcp.server.fastapi` 挂 ASGI） | 容器走"进程内 sdk server 转调 REST"即可，权限/排除/脱敏在既有 DRF View 层天然继承；另起协议层是平行入口，违反单一工具面 | 既有 `/api/mcp/tools/*` DRF 端点 |
| task 侧 `anthropic` / `langchain` SDK | learning case 提炼在**服务端**做（回调触发），容器只产 TaskResult；task 侧加 LLM 依赖徒增镜像体积与凭证面 | server 侧 `build_chat_model` |
| `requests` / `aiohttp` | task 侧 HTTP 统一 httpx（已有），别混第二个 HTTP 客户端 | `httpx.AsyncClient` |
| claude-agent-sdk 升级（0.1.7x / 0.2.x） | 0.1.58 双侧锁定、生产验证；升级需重新回归 3 个既有 SDK MCP server + resume/session 链路，与本里程碑无关 | 维持 `==0.1.58` |
| npm 侧新依赖（skills 包） | 容器物料是构建期文件同步，非运行时 npm 依赖 | 构建脚本 + hash 一致性测试 |

## Version Compatibility

| Package | Compatible With | Notes |
|---------|-----------------|-------|
| claude-agent-sdk 0.1.58 | Python 3.14（本仓 pinned） | wheel 自带 bundled CLI 2.1.97，无外部 node/claude CLI 依赖 |
| claude-agent-sdk 0.1.58 | `query()` string prompt + 多个 SDK MCP server | ≥0.1.53 才安全（stdin/handshake 修复）；0.1.58 已含且无 60s 超时坑 |
| httpx >=0.27 | claude-agent-sdk handler 内 async 调用 | 已在 remote_tools.py 生产使用，无冲突 |
| langchain >=1.2.15 栈 | `build_chat_model` seam | server 侧既有，memory_distill.py 同构验证 |

## Sources

- 本仓已安装源码（HIGH）：`task/.venv/.../claude_agent_sdk/types.py:549-584`（四种 McpServerConfig）、`__init__.py:275-315`（`create_sdk_mcp_server` 签名）、`_internal/query.py:689-707` + `_internal/client.py:141-152`（stdin 关闭时序修复，无超时）、`_version.py`/`_cli_version.py`（0.1.58 / CLI 2.1.97）。
- 锁文件（HIGH）：`task/uv.lock:78-84`（0.1.58 + mcp 传递依赖）、`server/uv.lock:472-474`、`task/pyproject.toml`、`server/pyproject.toml`。
- 生产先例（HIGH）：`task/core/remote_tools.py`（HTTP 代理型进程内 MCP server 蓝本）、`task/core/executor.py`（`extra_mcp_servers`/`allowed_tools` 挂载 + WR-02）、`server/initiatives/services/memory_distill.py`（LLM 提炼 + call_source + ledger 全套模式）。
- 上游 issue（MEDIUM，与已安装源码交叉验证一致）：anthropics/claude-agent-sdk-python #578/#817（string prompt + SDK MCP 崩溃，0.1.53 修复）、#676/#730/#731（~70s Stream closed，移除超时修复）。
- 官方文档（HIGH）：code.claude.com/docs/en/agent-sdk/python（`create_sdk_mcp_server` / `McpServerConfig` 四形态，与本地源码一致）。

---
*Stack research for: v0.17.0 统一知识库与全链路联动（AGENT/LOOP 技术选型）*
*Researched: 2026-07-15*
