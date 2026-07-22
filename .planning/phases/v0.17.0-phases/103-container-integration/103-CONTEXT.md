# Phase 103: 编码容器集成（短 TTL token + 容器知识 MCP + skills 注入 + 上下文对齐） - Context

**Gathered:** 2026-07-15
**Status:** Ready for planning
**Mode:** Smart discuss（autonomous — 推荐值自动采纳）

<domain>
## Phase Boundary

编码容器不再是"知识贫民区"：三条派发链路（workflow / chat / MCP）统一铸造任务级短 TTL token；容器内代理经进程内 SDK MCP server 主动查 Friday 知识（服务端 HTTP 工具面复用，权限/排除/脱敏天然继承）；friday-code/friday-memory skills 同源注入容器；工作流派发对齐 `pack_project_context`。需求：AGENT-01~04。短 TTL token 决策已定版（推翻 PATX-04 搁置，PAT-02 底线不破：明文不落盘、不从 DB 反取）。

</domain>

<decisions>
## Implementation Decisions

### AGENT-01 任务级短 TTL token
- **复用 `AccessToken` 模型**（不建新表）：migration 加 `kind` 字段（choices：`personal` 默认 / `task`）+ `session_id` 字段（nullable, indexed，任务 token 关联 subagent session）。认证类 `AccessTokenAuthentication` **零改动**（同 `friday_pat_` 前缀、同 sha256 查表、`is_valid` 天然管过期/吊销）。
- 统一铸造入口：`server/access_tokens/services.py`（新）`mint_task_token(user, session_id, timeout_seconds) -> str`：`generate_pat()` 明文只在内存返回、DB 存 `hash_token`、`expires_at = now + timeout + 余量（10 分钟）`、`kind="task"`、`name` 带 session 标识；结构化事件 `task_token_minted`（不含明文）。
- 接入点：
  - chat + MCP：`chat/coding_session_service.py` `dispatch_coding_task`（L391–412 区间）——initiating user 从 coding_session/conversation 解析；MCP 链经 `dispatch_execution` 复用同函数天然覆盖。
  - workflow：`workflows/nodes/ai/coding.py` `_run_repo_coding`（L1588–1647 env 装配处）——user 从 `triggered_by` 解析；**替换**现有 `context.user_pat_plaintext` 机会性透传（有 user 就 mint，不再依赖请求头明文）。
- env 注入沿用 `env_FRIDAY_TASK_USER_TOKEN`（TaskConfig.user_token 零改动）；user 不可解析时不注入（降级，AGENT-02 三要素守门兜底）。
- 吊销：`server/subagent/api/callbacks.py` 终态处理（`_handle_completed` ~L856 / `_handle_failed` ~L934）按 `session_id` 吊销（`revoked_at=now`，幂等 best-effort）；TIMEOUT/CANCELLED 的状态写入路径（planner 落点核实）同样挂吊销。事件 `task_token_revoked`。
- 泄漏防线：容器产物（diff/PR 描述/日志）无 `friday_pat_` 前缀——task 侧日志纪律沿用 remote_tools（PAT 只进 header）+ 服务端新增专项断言测试。
- 存量行为：`server/tests/test_remote_tool_dispatch.py` 既有 PAT-02 断言（不查 AccessToken 反取明文）语义保持——mint 是"新造"不是"反取"，测试更新说明写清。

### AGENT-02 容器知识 MCP
- 新建 `task/core/knowledge_tools.py`，镜像 `remote_tools.py` 全套约束：`build_knowledge_mcp_server(endpoint_base, user_token, quota)`；server 名 `friday-knowledge`；每工具 `SdkMcpTool`，handler `httpx.AsyncClient.post` 到 `{base}/api/mcp/tools/{name}/`、`Authorization: Bearer`、timeout 60s、return-not-raise、错误文本过脱敏（不回显 token/上游原文）。
- 白名单 7 工具（task 侧硬编码常量 + schema）：`search_rag_chunks` / `grep_repository` / `get_repository_file` / `search_delivery_knowledge` / `search_learning_cases` / `search_project_context` / `lookup_project_by_branch`。
- env 三要素：`FRIDAY_TASK_KNOWLEDGE_ENDPOINT`（新，TaskConfig 加字段）+ `FRIDAY_TASK_USER_TOKEN`（复用）+ 白名单内建（endpoint 或 token 任一空 → 整体降级返回 None 不挂，存量任务零回归）。
- per-task 配额：task 侧调用计数（默认 200 次/任务，env `FRIDAY_TASK_KNOWLEDGE_QUOTA` 可配）；用尽后 handler 返回 agent 可理解文案（"知识工具调用配额已用尽，请基于已有上下文继续"）。
- 关联键：请求带 `X-Friday-Session-Id` 头；服务端 `McpToolView` 读取并入 run metadata / RetrievalTrace payload（run/task 可关联查询）。
- 观测：调用走 `/api/mcp/tools/*` 天然进 `McpToolView._record`（RequestMetric source=mcp + RetrievalTrace）——QPS/错误率/时长零新建；task 侧结构化日志记 tool/status/耗时（不记入参明文）。
- 挂载：executor `_execute_claude` 与 remote_tools 同点位挂 `mcp_servers["friday-knowledge"]`；**allowed_tools 合并收口单一构造函数**（builtin + remote + knowledge + ask_user 全在一处合并），专项测试断言 Bash/Edit/Write/MultiEdit 在列（WR-02 第七面）。
- 排除文件回归（v0.5 第七面）：服务端集成测试——被排除文件经容器白名单工具（get_repository_file/grep/search_rag_chunks）不可见（fail-closed 继承断言）。

### AGENT-03 skills 同源注入
- 构建前同步：`task/scripts/sync_skills.py`（或 shell，planner 定）把 `skills/skills/{friday-code,friday-memory}` 拷入 `task/assets/skills/`（.gitignore 该目录？**否**——提交入库保证可重现构建 + hash 测试可跑；同步脚本幂等）。
- `task/Dockerfile` COPY `assets/skills/` 到镜像固定路径（如 `/opt/friday/skills/`）。
- 运行时注入：`task/core/runner.py` `run()` 在 `git_ops.setup()` 之后、ClaudeRunner 之前，把镜像 skills 拷入 `{workspace}/.claude/skills/`（`shutil.copytree` 逐目录，**同名跳过不覆盖**仓库自带）；`setting_sources=["project"]` 既有通道加载，零 executor 改动。
- hash 一致性测试：task/tests 内测试断言 `task/assets/skills/` 与仓库根 `skills/skills/` 对应目录逐文件 hash 一致（防双源漂移）；CI 可跑（相对路径向上找仓库根，找不到则 skip 并说明）。
- 不裁剪 skills 内容（setup 向导段对容器无害；裁剪引入生成逻辑得不偿失）。

### AGENT-04 工作流上下文对齐
- `_prepend_project_context` + 项目上下文解析 helper 上提至 `server/services/project_context_packer.py`（chat 改引用，workflow 直接用——避免 workflow import chat）。
- `workflows/nodes/ai/coding.py` `_dispatch_wave`：派发前按 `(project, branch)` 解析一次 `pack_project_context`（项目定位：ProjectBranch 反查 + work_item 关联 fallback；user=triggered_by），结果逐仓复用传入 `_run_repo_coding`，prompt prepend + `env_FRIDAY_TASK_PROJECT_CONTEXT` 与 chat 路径一致。
- 解析失败/无项目 → 空字符串 no-op（chat 既有 fail-soft 语义）。

### Claude's Discretion
- token 余量数值（建议 10 分钟）、配额默认值
- sync 脚本语言与 Dockerfile 层组织
- `X-Friday-Session-Id` 头名与 run metadata 字段名
- 测试组织

</decisions>

<code_context>
## Existing Code Insights

### Reusable Assets
- `server/access_tokens/models.py` L21–26 PAT_PREFIX/generate_pat、L40 token_hash、L54–57 expires/revoked、L76–78 is_valid；`authentication.py` L52–103（前缀闸门 + sha256 查表）；`views.py` L46–90 创建先例
- `server/runners/models.py` L16–18 hash_token
- `server/chat/coding_session_service.py` L130–215 build_dispatch_metadata、L238–291 `_resolve_project_context_for_dispatch`、L294–301 `_prepend_project_context`、L356–468 dispatch_coding_task（L401–408 chat prepend 先例）
- `server/workflows/nodes/ai/coding.py` L526–638 `_dispatch_wave`、L1508–1692 `_run_repo_coding`（L1588–1647 env 装配）、L1488–1506 `_resolve_user_pat`（被替换对象）
- `server/mcp_tools/execution_service.py` L125–202 dispatch_execution（MCP 链复用 dispatch_coding_task）
- `server/runners/dispatcher.py` L20–33 DispatchTask；`runner/internal/exec/env.go` L17–64 BuildContainerEnv（env_ 前缀透传）
- `task/core/remote_tools.py` 全文（AGENT-02 蓝本：降级 L147–149、端点校验 L33–48、handler L51–127、allowed L191–203）
- `task/core/config.py` L86–97 user_token/tools_endpoint/remote_tools 字段（env_prefix FRIDAY_TASK_）
- `task/core/executor.py` L55–67 `_BUILTIN_CODING_TOOLS`、L582–630 `_execute_claude` 装配（merge 收口点）、L597 setting_sources
- `task/core/runner.py` L86–140 run()（skills 注入点 ~L118–125）；`task/git_ops/operations.py` L57–119 setup()
- `task/Dockerfile`（无 assets/skills，build context ./task）；`docker-compose.build.yaml` L43–44
- `server/subagent/api/callbacks.py` L46–51 终态集、`_handle_completed`/`_handle_failed`（吊销钩子）
- `server/common/request_metrics.py` L151–194、`mcp_tools/views.py` `_record` L292–299（QPS 观测复用）
- `server/services/project_context_packer.py` L85–93 pack_project_context 签名
- 测试先例：`task/tests/test_remote_tools.py`、`task/tests/test_claude_sdk_integration.py` L167–301（WR-02）、`server/tests/test_remote_tool_dispatch.py`（PAT-02）、`server/tests/chat/test_coding_dispatch_context.py`

### 关键事实
- 现状仅 workflow 机会性注入 USER_TOKEN（依赖请求头 PAT 明文 ContextVar）；chat/MCP 派发不带任何 token
- knowledge_tools.py / task/assets 不存在；Dockerfile 无 skills
- 三链汇聚：chat 与 MCP 共用 dispatch_coding_task，workflow 独立 `_run_repo_coding`——两处接 mint 即全覆盖
- MCP 工具端点已挂 AccessTokenAuthentication + CookieJWT（views.py L235）

</code_context>

<specifics>
## Specific Ideas

- 核心思路"优雅好用"：token 复用既有模型与认证零改动；观测复用 McpToolView 零新建；skills 注入零 executor 改动（setting_sources 既有通道）。
- 四险（白名单/配额/PAT 内存化/allowed_tools 合并）+ 观测全套必须同 phase 落地，不留"先跑通后补"。

</specifics>

<deferred>
## Deferred Ideas

- friday-feishu / friday 总技能注入容器（先 code+memory 两个，够用再扩）
- 服务端按 token kind 的调用配额（先 task 侧配额，服务端限流走既有 provider 限流体系）
- MCP dispatch 路径 ContextVar 捕获缺口（mint 方案替代后不再需要）

</deferred>
