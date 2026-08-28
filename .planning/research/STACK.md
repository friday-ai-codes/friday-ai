# Stack Research

**Domain:** Cursor / Claude Code 会话知识回写（brownfield Friday AI）
**Researched:** 2026-08-28
**Confidence:** HIGH（复用既有栈）；MEDIUM（Cursor `afterAgentResponse` 与 Claude Code `last_assistant_message` 为答案采集点，官方契约已核，端到端配对需相位内验证）

本文件只回答 **v0.25.0 要加/改哪些栈**，不重研已验证的 RAG / MCP 鉴权 / 项目记忆。结论：**不引入新运行时库**；新增一张 Capture 操作态表 + 一个 MCP 工具 + skills/hooks 适配；评估与向量化走既有 LLM / `delivery_knowledge` 管线。

## Recommended Stack

### Core Technologies

| Technology | Version | Purpose | Why Recommended |
|------------|---------|---------|-----------------|
| Django ORM + migration | Django `>=5.1` / Python `3.14` | 新 `SessionCapture`（或同名）操作态表 | 与仓内所有写模型一致；仓库 FK + 可选项目 FK 无法塞进现有 `ProjectMemory`（后者 `project` 必填 CASCADE） |
| DRF Serializer + `McpToolView` | `djangorestframework>=3.15` + 现有 `adrf` | 新 MCP 工具 HTTP 面 | 鉴权 / `InteractionRun` / `_record` / 脱敏已由基类承担；禁止另开 REST 资源绕过 MCP |
| `@friday-ai-codes/mcp` | 现包 `0.6.0`，`@modelcontextprotocol/sdk ^1.29.0`，Node `>=18` | stdio → `POST /api/mcp/tools/{name}/` | 客户端不直打业务表；工具名必须与 `TOOL_SCHEMA_SNAPSHOT` + `mcp/src/tools.ts` 三方对齐（v0.20 已有漂移债） |
| `@friday-ai-codes/skills` | 现包 `0.7.0`，Node `>=20`，零 HTTP 库 | hooks / skill 正文 / 安装器 | 安装器已是 Node `fs` + `@clack/prompts`；Claude 插件经 `.claude-plugin/plugin.json` 挂 `hooks/hooks.json` |
| 既有 LLM 解析栈 | `provider_config` + `anthropic`/`openai`/`google-genai` 现版本 | Friday 侧 high/medium/low 评估 | 不新增评测框架；新 `CallSource` 枚举值（建议 `session_capture_eval`），对标 `ide_hook_distill` / `memory_distill` |
| 既有知识摄取 | `knowledge.ingestion.aschedule_ingestion` + Qdrant `delivery_knowledge` | 中高价值向量化 | v0.17 已锁「统一 collection、新 `source_kind`」；禁止新建向量库 |

### Supporting Libraries

| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| `structlog`（已有 `>=25.5.0`） | 现依赖 | `xxx_started/completed/failed` + `category`/`component`/`duration_ms` | Capture 写入、评估、摄取全生命周期 |
| `common.logging.redact_secrets_in_text` / `redact_for_ledger` | 现模块 | 问答精华入库前脱敏；Ledger 请求快照 | 不可绕过；客户端已抽精华仍要服务端再 redact |
| `DurableTaskService` | 现 v0.12 适配层 | 评估 + 中高摄取异步 | MCP 入口同步只落 Capture（200/201），评估 fail-soft 进队列，不阻塞 IDE hook |
| `jsonschema`（已有 `>=4.23.0`） | 现依赖 | 可选：评估输出 `{grade, distilled}` 校验 | 仅当 LLM JSON 不稳时用；不要为 Capture 请求再引入第二套校验（DRF 已是真源） |
| Node 内置 `fs` / `urllib` / `python3` | 运行时已有 | hooks 脚本、安装器 merge `hooks.json` | **不要**给 skills 加 `axios`/`zod`/`node-fetch` |
| `httpx`（已有 `>=0.27`） | 现依赖 | 仅服务端测与内部调用 | hooks 继续用 stdlib `urllib.request`，与现 `stop` / `user-prompt-submit` 一致 |

### Development Tools

| Tool | Purpose | Notes |
|------|---------|-------|
| `server/tests/mcp_tools/test_schema_snapshot.py` | `TOOL_SCHEMA_SNAPSHOT` 键集 | 新工具必须同时改 serializer、snapshot、本测试 |
| `test_mcp_package_alignment.py` | `mcp/src/tools.ts` 名集 == snapshot | 漏 npm 客户端则工具对 Cursor 不可达（v0.20/v0.22 已知债） |
| `test_skills_snapshot_guard.py` | SKILL.md 引用 ⊆ snapshot | 新工具名写进 `friday-dev` / `friday-memory` 时必过 |
| Cursor 官方 Hooks 文档 | `beforeSubmitPrompt` / `stop` / `afterAgentResponse` / `sessionStart` | 答案采集不要押在 Cursor `stop` 入参上（官方只有 `status`/`loop_count`） |
| Claude Code Hooks 文档 | `UserPromptSubmit` / `Stop` | 用 `last_assistant_message`，不要读可能滞后的 `transcript_path` |

## Installation

```bash
# 不新增 npm / Python 包。发版节奏：
# 1) 服务端：Django migration + 新 MCP 工具（随 friday-ai 镜像）
# 2) 客户端：bump @friday-ai-codes/mcp 与 @friday-ai-codes/skills 补丁版

# 开发者本机（已有）
# Python：沿用 server/ uv + Django 5.1+
# MCP 包：mcp/ 内现有 @modelcontextprotocol/sdk，勿升级 major
# Skills：npx @friday-ai-codes/skills install --agent cursor|--agent claude-code

# 禁止
# npm install mem0 zod langchain axios
# pip install chromadb llama-index-new-memory
```

无新 `npm install` 行。skills 安装器扩展为 **merge** Cursor `~/.cursor/hooks.json` 与项目 `.cursor/hooks.json`（`version: 1`），用现有 `readFileSync`/`writeFileSync`，不要依赖 jq。

## Alternatives Considered

| Recommended | Alternative | When to Use Alternative |
|-------------|-------------|-------------------------|
| **新 Capture 表**（仓库 FK 可空 + `git_url`/`branch` 标量；`project` 可选） | 扩 `ProjectMemory` | 永不：`ProjectMemory.project` 必填，与「仓库为主、无项目也先收」冲突；MEM-04 语义是成员共享记忆，不是问答账本 |
| **新 MCP 工具**（建议名 `report_session_knowledge`） | 扩 `report_project_knowledge` | 仅当产品改口「无项目就丢」——当前锁定禁止。现工具在 `branch_unresolved` 时 `accepted=false` 且不落库 |
| Cursor：`beforeSubmitPrompt` 缓存问题 + `afterAgentResponse` 配对答案 | Cursor `stop` 抽答案 | Cursor 官方 `stop` 无助手正文；`followup_message` 会再提交一轮，污染会话，禁止用于回写 |
| Claude Code：`UserPromptSubmit` 记问题 + `Stop.last_assistant_message` | 解析 `transcript_path` JSONL | 官方写明 transcript 异步滞后；Stop 应用 `last_assistant_message` |
| 中高价值 → 现 `aschedule_ingestion` + 新 `source_kind` | 新建 Qdrant collection | 违反 v0.17「统一知识库」；召回已走 `DeliveryKnowledgeSearchService` + `repository_ids` |
| MCP 同步落 Capture，评估异步 | 在 hook 里等 LLM 打分 | hook 超时会拖 IDE；评估必须 Durable 队列 |
| 安装器 merge Cursor `hooks.json` | 做 Cursor 专用插件 / VS Code extension | v0.15 已否决专用插件（PROJX-04）；hooks.json 是官方一等配置 |

## What NOT to Use

| Avoid | Why | Use Instead |
|-------|-----|-------------|
| 把 Interaction Ledger / `raw_request` 当 RAG 正文 | 锁定三层分离；Ledger 是审计与用量，`redact_for_ledger` 后也不该进向量 | `McpToolView._begin/_record` 照常记本次工具调用；知识只进 Capture →（中高）KnowledgeEntity |
| `ProjectMemory` / `MemoryService.append` 作为 Capture 唯一落点 | 强制项目；`branch_unresolved` 静默丢；active 直写是 Phase 86 对「git 改动摘要」的 deviation，不是零散问答 | 新表 + `CaptureService`（INV-6 单一写入） |
| 扩 `report_project_knowledge` 的 `content` 自由文本扛 Q&A | 无 `question`/`answer`/`response_model`/`session`；snapshot 已与 serializer 漂移（snapshot 仍是 `project_id, content, source_conversation_id`） | 新工具 + **完整** snapshot（请求/响应键一次写对） |
| 新 npm 依赖（Mem0、LangChain memory、zod、axios） | 质量门禁止；MCP/skills 已能 HTTP + JSON Schema | 现 `@modelcontextprotocol/sdk` + DRF |
| 新向量库 / 新 `llama-index` 存储 | 重复索引、权限过滤要重做 | `delivery_knowledge` + 新 `source_kind=session_capture`（名可微调，逻辑隔离同 `project_memory`） |
| Cursor `afterAgentThought` 落库 | 锁定「不存隐藏 CoT」；官方入参即完整 thinking 文本 | 忽略该 hook；客户端只抽精华 |
| 客户端猜 `response_model` | 拿不到记 `unknown` | 字段可选，默认 `unknown` |
| 为 Capture 新建 Django app / 新微服务 | 过重；FK 指向 `repositories.Repository` / `initiatives.Project` 即可 | 放 `knowledge` app（靠近摄取）或 `initiatives` 但 **project 必须 null=True** |
| Cursor `beforeSubmitPrompt` 注入 `additionalContext` | 官方输出仅 `continue` / `user_message`；社区仍在要注入能力。Phase 86 结论仍成立 | 读路径继续 always-on rule + MCP；Cursor **会话级**注入可用 `sessionStart.additional_context`（与 per-prompt 无关） |
| Stop hook 在「无 git diff」时 `fail_soft` 跳过 | 现 `skills/hooks/stop` 无改动即 exit 0，直接违反 MCP-02/SKILL-01 | 改 Stop：无 diff 仍回写本轮 Q&A；git 摘要可继续调旧 `report_project_knowledge`（有项目时） |
| 升级 `@modelcontextprotocol/sdk` major / `mcp` Python 到 2.x | 服务端刻意 pin `mcp>=1.25.0,<2`（SDK 装饰器） | 保持现 pin |

## Stack Patterns by Variant

**如果宿主是 Claude Code：**
- 用插件 `hooks/hooks.json`：`UserPromptSubmit`（stdin 有 `prompt` + `session_id`）缓存本轮问题精华；`Stop` 读 `last_assistant_message` 抽答案精华，调新 MCP 工具。
- 现 Stop 的 git `--stat` 上报保留为 **附加** 项目记忆路径，不得再当唯一写路径。
- 凭证顺序不变：`FRIDAY_BASE_URL`/`FRIDAY_ACCESS_TOKEN` → `FRIDAY_API_URL`/`FRIDAY_PAT` → `~/.friday/config.json`。

**如果宿主是 Cursor：**
- `beforeSubmitPrompt`：只记录 `prompt`（可 `continue: true`），**不拦截**；问题缓存到 `~/.cache/friday-skills/`（与现 ctx/stop marker 同目录）。
- `afterAgentResponse`：官方入参 `{ text }`，配对缓存问题后 MCP 回写。这是 Cursor 侧答案的唯一可靠钩子。
- `stop`：不要用来抽答案；可继续做 git 改动摘要（现 ide-hook-assets 写路径）。
- `sessionStart`：可注入仓库级提示，**不能**替代 per-turn 问答采集。
- 安装器必须 merge `.cursor/hooks.json`；今日 `skills/lib/installer.mjs` **只装 skills + friday.mdc，不装 Cursor hooks**——这是本里程碑必改集成点。

**如果仓库解析失败 / 无 `repository_id`：**
- 客户端仍提交 `git remote`/`branch`/`session` 标量；服务端解析 `Repository.git_url` **best-effort**。
- 解析失败：**照样 INSERT Capture**（`repository_id=NULL`），`reason` 可标 `repo_unresolved`，**禁止**映射成现网的 `branch_unresolved` 丢弃语义。
- 项目解析继续可选增强，失败不影响 Capture。

**如果价值评估为 low：**
- 行留在 Capture 表（评测回放）；**不**调用 `aschedule_ingestion`；不进 Qdrant。
- 质量门槛（过短/低信息）可拒收向量化，但与「low 仍落账本」分开：门槛过严会违反「零散提问也收集」——建议门槛只挡空串/密钥，价值分给 LLM。

## Version Compatibility

| Package A | Compatible With | Notes |
|-----------|-----------------|-------|
| Django `>=5.1` / Python `3.14` | 现 `sync_to_async` ORM 纪律 | Capture 写路径必须 `CaptureService`，异步 view 不直接 `.save()` |
| `djangorestframework>=3.15` | `McpToolView` PAT/JWT | 新 serializer `required`: `question`,`answer`；其余可选 |
| `@friday-ai-codes/mcp@0.6.x` + `@modelcontextprotocol/sdk ^1.29.0` | 服务端 `TOOL_SCHEMA_SNAPSHOT` | 发 npm 前跑 `test_mcp_package_alignment`；不同步则 Cursor 调不到新工具 |
| `@friday-ai-codes/skills@0.7.x` | Claude Code 插件 hooks + Cursor `hooks.json` v1 | 插件根 `hooks/hooks.json` 已有 UserPromptSubmit/Stop；Cursor 侧是缺口 |
| 服务端 `mcp>=1.25.0,<2` | `claude-agent-sdk` | 勿为会话回写放开 mcp 2 |
| Cursor Hooks `version: 1` | `beforeSubmitPrompt` 无 additional_context | 以 [cursor.com/docs/hooks](https://cursor.com/docs/hooks.md) 为准，不以论坛猜测为准 |
| Claude Code Stop | `last_assistant_message` | [code.claude.com/docs/en/hooks](https://code.claude.com/docs/en/hooks) 2026 文档 |

## Integration map（本里程碑改哪些面）

| 层 | 动作 | 不改 |
|----|------|------|
| `knowledge` 新模型 + `CaptureService` + migration | **新增** | 不改 `ProjectMemory` 必填 FK |
| `mcp_tools/serializers.py` + `views.py` + `urls.py` + `TOOL_SCHEMA_SNAPSHOT` | **新增工具** | 保留 `report_project_knowledge` 给「有项目的记忆沉淀」 |
| `mcp/src/tools.ts` + `TOOL_ANNOTATIONS` | **同步** | 不改 MCP SDK |
| `knowledge/sources/` 新 normalizer | 中高才跑 | 不把 Ledger payload hydrate 进图 |
| `CallSource` + `LOGGING-SPEC.md` §4.1 | 加 1 个枚举 | 评估 LLM 必须打点 |
| `skills/hooks/stop` + `user-prompt-submit` | 改采集逻辑 | 凭证解析/fail-soft/exit 0 模式保留 |
| `skills/lib/installer.mjs` | merge Cursor hooks | 不引入新依赖 |
| `server/initiatives/services/ide_hook_assets.py` | 资产脚本对齐新工具 | Cursor 读路径仍不押 `beforeSubmitPrompt` 注入 |
| Vue 控制台 | **本里程碑可不做大前端**（PROJECT 小版本惯例） | 回放可后续 REST；先 MCP + 表 |

## MCP 契约（栈层，非产品文案）

建议请求键（DRF 为真源，snapshot 必须抄全）：

- 必填：`question`, `answer`（客户端已抽精华，长度上限对齐现 `content` 量级，建议各 `<=20000`）
- 可选：`response_model`（默认 `unknown`）, `repository_id`, `git_url`, `branch_name`, `session_id`, `project_id`, `client`（`cursor`/`claude_code`）
- 禁止必填 `project_id`；禁止「无项目 → 400」

建议响应键：`accepted`, `capture_id`, `repository_id`, `project_id`, `reason`, `run_id`（`reason` 可含 `repo_unresolved` 但仍 `accepted=true`）

`idempotentHint: true` 可按 `(token_user, session_id, question_hash)` 幂等，避免 Stop 重试双写。

现网债：`TOOL_SCHEMA_SNAPSHOT["report_project_knowledge"]` **小于**真实 serializer（缺 `branch_name`/`repository_id`/`writeback_mode`/`target`/`distill`）。本里程碑 **不要顺手「修一半」旧 snapshot** 除非单独立项；新工具必须一次对齐，避免再制造第三份漂移。

## Observability（强制，无新库）

- 入口：`category=caller`, `component=mcp_tools`（或 `knowledge`）
- 评估 LLM：`call_source=session_capture_eval`（需写入 `CallSource` 与 LOGGING-SPEC）
- 摄取：复用 knowledge normalizer 的 `sampling` 事件
- Ledger：工具调用走既有 `begin_interaction_run`；**不要**把问答全文当 RAG 源从 Ledger 回灌

## Sources

- 仓库：`server/mcp_tools/views.py`（`_resolve_report_project_id` / `branch_unresolved` 丢弃）、`serializers.py` `ReportProjectKnowledgeRequestSerializer`、`initiatives/models/memory.py`、`interactions/models.py`、`knowledge/sources/project_memory.py`、`skills/hooks/{stop,user-prompt-submit}`、`skills/hooks/hooks.json`、`skills/lib/installer.mjs`、`mcp/package.json` `0.6.0`、`skills/package.json` `0.7.0` — **HIGH**
- Cursor 官方 Hooks：[https://cursor.com/docs/hooks.md](https://cursor.com/docs/hooks.md) — `beforeSubmitPrompt` 仅 `continue`/`user_message`；`afterAgentResponse` 入参 `text`；`stop` 无助手正文；`sessionStart` 可 `additional_context` — **HIGH**
- Claude Code 官方 Hooks：[https://code.claude.com/docs/en/hooks](https://code.claude.com/docs/en/hooks) — `UserPromptSubmit` 用 `hookSpecificOutput.additionalContext` 注入；Stop 用 `last_assistant_message` — **HIGH**
- 社区 Cursor `beforeSubmitPrompt` 注入请求：[forum.cursor.com/t/150707](https://forum.cursor.com/t/hooks-allow-beforesubmitprompt-hook-to-inject-additional-context/150707) — 与官方输出 schema 一致，**不能**当已交付能力 — **MEDIUM**（仅作「不要押注入」佐证）
- v0.16 Phase 86 / `ide_hook_assets.py`：Cursor 读路径不押注入 — 与 2026 官方文档仍一致 — **HIGH**

---
*Stack research for: Friday AI v0.25.0 IDE session knowledge writeback*
*Researched: 2026-08-28*
