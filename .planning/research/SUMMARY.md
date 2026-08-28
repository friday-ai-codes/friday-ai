# Project Research Summary

**Project:** Friday AI v0.25.0 Cursor / Claude Code 会话知识回写
**Domain:** IDE 会话采集 → Capture 账本 → 价值评估 → 仓/项目 RAG（brownfield，落在 Django MCP + knowledge，不碰 runner/task）
**Researched:** 2026-08-28
**Confidence:** HIGH（仓内接缝与锁定决策）；MEDIUM（Cursor `afterAgentResponse` 配对、git remote 归一化、入图 durable 投递需相位内钉死）

> 本文件覆盖 **v0.25.0 会话知识回写** 研究结论，供 roadmapper 排期。不保留 v0.24.0 图查询内容。

## Executive Summary

v0.25.0 要补的不是再造一套记忆，而是把现闭环从「必须绑到唯一项目 + 有 git diff 才写 + 长度/去重门槛」升级为「仓库为主挂钩、项目可选、零散问答也收、永不静默丢 Capture、中高价值才进 `delivery_knowledge`」。产业成熟做法与 Mem0 / Claude Code hooks 一致：**hook 抽精华（非全文、非 CoT）→ 账本持久化（≠ 向量）→ 重要性分档 → 按仓/项目 on-demand 召回**。Friday 现网最大缺口是：`report_project_knowledge` 在 `_resolve_report_project_id` 失败时 200 + `accepted=false` + `branch_unresolved` **不落库**；`skills/hooks/stop` 在无 `git diff --stat` 时直接 `fail_soft()` 丢掉纯对话。

推荐路径（已锁定）：**新 Capture 表 + INV-6 `CaptureService` + 新 MCP 工具**（建议名 `report_session_knowledge`，相位钉死），**禁止**扩 `report_project_knowledge` / 把 `ProjectMemory` 当账本 / 把 Interaction Ledger 当 RAG。MCP 同步只 INSERT Capture（无项目、仓解析失败仍 `accepted=true`）；评估 LLM 异步（Durable / `on_commit` 后台），`call_source` 新枚举；仅 medium/high 走既有 `aschedule_ingestion` + 新 `source_kind`，复用 `DOCUMENT` kind，**不**新建 Qdrant collection、**不**新 EntityKind、**不**引入运行时库。`ProjectMemory` 仍 draft 门控；中高仓级 RAG **自动摄取**（可 supersede/回滚）。客户端只抽问题/可见答案精华；拿不到的模型字段记 `unknown`。

主风险三条：① 复制旧 skip 语义导致「工具通了、库是空的」——新工具把挂钩与项目拆开，`branch_unresolved` 不得表示未收。② Cursor 与 Claude Code hook 模型不对称——Claude 用 `UserPromptSubmit` + `Stop.last_assistant_message`；Cursor 用 `beforeSubmitPrompt` 缓存问题 + `afterAgentResponse` 配对，**不要**押 `stop` 抽答案，也**不要**把 Claude 注入 hook 拷进 Cursor。③ 评估/入图若内联 MCP 或只走进程内 `background_runner`——hook 超时或重启丢向量；必须 persist-first + 可重试投递。npm `mcp` / snapshot / skills 三面必须同里程碑对齐，否则 Cursor 调不到新工具（v0.20/v0.22 已知债）。

## Key Findings

### Recommended Stack

详见 [STACK.md](./STACK.md)。**不引入新 npm/Python 运行时库。** 发版是服务端 migration + MCP 工具，再 bump `@friday-ai-codes/mcp`（现 `0.6.0`）与 `@friday-ai-codes/skills`（现 `0.7.0`）补丁版。MCP SDK 保持 `@modelcontextprotocol/sdk ^1.29.0`；服务端 `mcp>=1.25.0,<2` 勿放开。评估与向量化走既有 `provider_config` + `aschedule_ingestion` + Qdrant `delivery_knowledge`。

**Core technologies:**
- Django ORM + migration（Python 3.14 / Django ≥5.1）：新 `SessionCapture`（或同名）操作态表，仓库 FK 可空 + `git_url`/`branch` 标量，`project` 可选 —— `ProjectMemory.project` 必填 CASCADE，塞不进去
- DRF + 现有 `McpToolView`：新工具 HTTP 面；鉴权 / `InteractionRun` / `_record` / 脱敏由基类承担；禁止另开 REST 绕过 MCP
- `@friday-ai-codes/mcp` + `@friday-ai-codes/skills`：stdio → `POST /api/mcp/tools/{name}/`；安装器 **merge** Cursor `hooks.json`（`version: 1`），用现有 `fs`，不加 axios/zod
- 既有 LLM 栈 + 新 `CallSource`（建议 `session_capture_eval` / `ide_session_eval`，规划时钉死一个）：high/medium/low；对标 `ide_hook_distill` 但**不要复用**该枚举
- 既有知识摄取：新 `source_kind`（建议 `session_capture` 或 `ide_session_knowledge`）进统一 collection；禁止新建向量库

**契约要点（栈层）：** 请求必填 `question`,`answer`；可选 `response_model`（默认 `unknown`）、`repository_id`、`git_url`、`branch_name`、`session_id`、`project_id`、`client`。禁止必填 `project_id`。响应：`accepted`/`capture_id`/`reason`（`repo_unresolved` 仍可 `accepted=true`）。幂等建议 `(token_user, session_id, question_hash)`。旧工具 snapshot 已漂移——**本里程碑不要顺手修一半** `report_project_knowledge`。

### Expected Features

详见 [FEATURES.md](./FEATURES.md)。验收锚点：用户感觉「回写发生了」且下次能搜到中高价值决策/坑。

**Must have (table stakes):**
- 新 MCP 结构化回写（问题 / 答案 / 回答模型 / 仓库 / 分支 / 会话）；缺字段记 `unknown`，不猜
- 仓库为主、项目可选；无 `project_id` 仍接受 Capture；解析失败仍落账本
- 禁止把 `branch_unresolved` 静默丢数据当成成功
- 零散问答 / 无 git 改动也采集（必须改 stop 闸）
- Skills + Cursor / Claude Code hooks 抽精华并触发回写；禁止完整隐藏 CoT
- Capture 账本（原始结构化问答）；**不是** Ledger，**不是** `ProjectMemory`
- 三层分离：Capture ≠ 提炼知识 ≠ Ledger（Ledger 禁止反哺检索）
- 价值评估 high/medium/low + 提炼；**不是** `evaluate_writeback_quality`，**不是**路由 `confidence`
- 中高进仓/可选项目 RAG；low 留评测样本不进 Qdrant
- 按仓/按项目可检索；Capture 可回放；PAT / 脱敏 / fail-soft / RetrievalTrace

**Should have (competitive):**
- 团队共享、自托管、权限不比代码 RAG 更松
- 仓图谱 + 可选项目 `REFERENCES`；与 `friday-dev` 召回环合流
- Capture 回放作 golden set；离散三档比 Mem0 连续 importance 更好测
- 不依赖专用 IDE 插件（PROJX-04 仍 backlog）

**Defer (v0.25.x / v2+):**
- 控制台价值纠偏、SessionStart 按仓注入摘要预算、与 `report_project_knowledge` 去重 —— v0.25.x
- 专用插件、记忆矛盾消解、Capture 自动变 `ProjectMemory` active、多模态会话 —— v2+
- 全文 transcript 入向量 —— **不做**

**产品张力（已有推荐默认）：** Capture **无确认永不丢**；评估自动 fail-soft；**仓级 RAG 对 medium/high 自动摄取**；写入 `ProjectMemory` **仍默认 draft**。若中高也要人审才进 RAG，必须另做积压队列，否则「可召回」验收会系统性失败。

### Architecture Approach

详见 [ARCHITECTURE.md](./ARCHITECTURE.md)。**不要把 v0.25 塞进 `ReportProjectKnowledgeView` + `MemoryService`。** 模式是「MCP 同步收、异步炼」：对照 learning case / PR review 的 `on_commit` + `run_in_background`/`DurableTaskService`，**不要**对照 `_maybe_distill`（请求内 LLM 会拖死 hook）。入图复用 `EntityKind.DOCUMENT` + 新 `source_kind`；`IngestionEvent.content` 只放提炼正文。skills 优先改 `friday-memory`，不要新开 `friday-capture` skill。Vue 控制台本里程碑可不做大前端。

**Major components:**
1. IDE skills / hooks — 抽精华、无 diff 也 POST；Cursor 与 Claude 分模型接线
2. npm MCP 客户端 — `mcp/src/tools.ts` 白名单与 snapshot 双向对齐
3. 新 `McpToolView` — PAT、校验、同步 `CaptureService.persist`、Ledger `_record`
4. `CaptureService`（INV-6）— 唯一写入、脱敏、归因；grep 守卫
5. Distill/Eval worker — 新 call_source；low 停、中高 `aschedule_ingestion`
6. `knowledge/sources/<kind>.py` + `DeliveryKnowledgeSearchService` — 仓/项目召回
7. `MemoryService` / `report_project_knowledge` — **零回归保留**；与 Capture 无写入边

**解析顺序（意见）：** 显式 `repository_id` → 归一化 `git_url` 匹配 `Repository.git_url` → `project_id` 可选（非成员不拒绝 Capture）→ `branch_name` 仅元数据。默认分支 `main`/`master`/`develop` **禁止**当唯一项目信号（PITFALLS：lookup 第三源假命中）。

### Critical Pitfalls

详见 [PITFALLS.md](./PITFALLS.md)。Roadmap 必须显式防住：

1. **`branch_unresolved` 当成功跳过** — 新工具拆开仓挂钩与项目；无仓仍落库并给显式 `reason`；禁止 `if resolved_pid is None: return 200 accepted=false`
2. **Stop 把无 git diff 当成无知识** — Q&A 与 diff 解耦；去重键 `(session_id, question_hash, answer_hash)`；300s 节流只套 diff 摘要
3. **Cursor `beforeSubmitPrompt` 注入幻觉** — 采集主链是 MCP；Cursor 用 `afterAgentResponse` + 规则/skill；资产树禁止 Claude `UserPromptSubmit` 注入脚本
4. **`lookup_project_by_branch` 在 `main` 上假命中** — 默认分支第三源不 `matched`；Capture 不以 lookup 项目当主键
5. **Ledger / `writeback_mode=active` / 新 EntityKind / 进程内 ingest 当唯一投递** — 三层分离 + MEM-04 不扩大例外 + `source_kind` 分流 + Capture 状态机 + durable/outbox
6. **服务端有工具、npm/skills 没有** — serializer + snapshot + `tools.ts` + SKILL.md 同一验收；容器写路径要么显式加白要么标明 Out of Scope

## Implications for Roadmap

四份研究对**依赖序**一致：**先账本，再 MCP 契约，再评估入图，再召回，最后客户端**（客户端不能早于契约冻结）。PITFALLS 文中的 P1→P2 指「契约字段必须先于 hook 接线」，不是「先做 hook 再建模」。建议 **5 个交付相位**（GSD 相位号由 roadmapper 续号，此处为逻辑序）。

### Phase 1: Capture 账本 + 仓库解析（STORE-01）
**Rationale:** 架构硬约束「无此步禁止接 MCP」；INV-6 与三层分离必须焊在表结构上，避免 P4 再迁一次状态机。
**Delivers:** Capture 模型（问答、`response_model`、`repository_id` 可空、`git_url_raw`、`branch`、`project_id` 可空、`session_id`、hash、status、tier、distilled、`initiated_by_user_id`）；`CaptureService.create`（`redact_secrets_in_text`）；旁路 `objects.create` grep 守卫；git URL 归一化 helper（复用 `ssh_git_url_to_https`）；状态字段预留 `pending_eval` / `ingest_pending`。
**Addresses:** STORE-01；三层分离；永不因无项目丢数（存储面）
**Avoids:** Pitfall 5（Ledger 当 RAG）、6（MEM-04 / active 记忆）、Capture 直接 ORM 写
**Uses:** Django migration；无新库

### Phase 2: 新 MCP 工具面（MCP-01 / MCP-02）
**Rationale:** IDE 打桩联调依赖冻结契约；旧工具门闩保持零回归。
**Delivers:** 新 serializer（必填问答、禁止必填 `project_id`）、`McpToolView`、url、**完整** `TOOL_SCHEMA_SNAPSHOT`、`mcp/src/tools.ts` + `test_mcp_package_alignment`；行为：无项目 / `repo_unresolved` 仍 200 `accepted=true` 且有行；Ledger `_record`；评估可先 no-op 调度。
**Addresses:** MCP-01/02
**Avoids:** Pitfall 1（静默 skip）、10（三面漂移）、4（用 lookup 第三源当写主键）
**Implements:** MCP 同步收；`report_project_knowledge` 不改门闩

### Phase 3: 价值评估 + 中高入图（EVAL-01）
**Rationale:** 先有 Capture 行再评；LLM 不可内联 hook；入图登记表必须与 worker 同批否则 `get_normalizer` KeyError。
**Delivers:** 新评估模块 + 新 `CallSource` + LOGGING-SPEC §4.1；`use_call_source`；fail-soft `eval_failed` 保留原文；仅 medium/high `aschedule_ingestion`；normalizer（`DOCUMENT` + `repository_id` + 可选项目 `REFERENCES`）；**不**调用 `MemoryService.append`；生产路径 durable/outbox + `ingest_pending` 对账（禁止把唯一投递交给 `background_runner`）。
**Addresses:** EVAL-01；中高 RAG；low 评测样本
**Avoids:** Pitfall 7（新 EntityKind）、8（重启丢向量）、9（无 call_source / 混 `llm_grader`）
**Uses:** 既有 LLM / DurableTaskService / ingestion 六步序（不改算法）

### Phase 4: 召回、回放与观测收口
**Rationale:** 「入了库但 IDE 召不回」是 hollow 高发点；packer kind 白名单必须显式打开。
**Delivers:** `search_delivery_knowledge` / `pack_project_context` 纳入新 `source_kind`；RetrievalTrace（MCP + 对话链）；Capture 只读回放（MCP 或薄 REST，不扫 Ledger）；`main` + 唯一 RepoAssociation 回归：lookup 不注入、Capture 不写错项目；观测：persist=`caller`，eval 步=`sampling`。
**Addresses:** 按仓/按项目检索 + Capture 可回放
**Avoids:** Pitfall 4 回归；Ledger import 守卫
**Note:** 大前端回放 UI **本里程碑非必须**（小版本惯例）

### Phase 5: 双宿主采集（SKILL-01）
**Rationale:** 必须在 Phase 2 契约冻结之后，否则技能文档与 snapshot 互搏；现 stop 闸不改则零散问答无法验收。
**Delivers:** Claude Code：`UserPromptSubmit` 缓存问题 + `Stop.last_assistant_message` 抽答案，无 diff 仍 POST 新工具；git `--stat` 可继续附加走旧 `report_project_knowledge`（有项目时）。Cursor：`beforeSubmitPrompt` 只缓存、不拦截；`afterAgentResponse` 配对后 MCP；`stop` 不抽答案。安装器 merge Cursor `hooks.json`；`friday-memory` + `http-fallback` + `ide_hook_assets`；`test_skills_snapshot_guard`；容器 `KNOWLEDGE_TOOL_SCHEMAS` 要么加白要么明确不做容器写。npm publish 可 Deferred，**源码必须绿**。
**Addresses:** SKILL-01
**Avoids:** Pitfall 2（diff 门）、3（Cursor 注入）、10（skill 仍教旧工具）
**Uses:** Node 内置 fs/urllib；凭证顺序不变

### Phase Ordering Rationale

- STORE → MCP → EVAL → 召回 → Skills：与 ARCHITECTURE Suggested Build Order 一致；Skills 不能先于 MCP；入图不能先于账本 `source_id`。
- 评估 call_source 必须先于首次 LLM，否则用量落入 `unknown`。
- MCP 与 npm snapshot 同相位，避免「服务端绿、Cursor 不可达」。
- 观测与旧工具回归可并入 Phase 4 尾或每相位门禁，不必单独第六相位。
- 分组依据：写模型边界（P1）/ 信任边界（P2）/ LLM+图（P3）/ 读路径（P4）/ 宿主差异（P5）。

### Research Flags

Phases likely needing deeper research during planning:
- **Phase 3:** Capture 入图投递：`aschedule_ingestion` + durable/outbox 与现 learning_case 窗口如何对齐；状态机字段一次定稿
- **Phase 5:** Cursor `afterAgentResponse` 与 `beforeSubmitPrompt` 缓存的端到端配对（官方契约已核，本机配对未证）；安装器 merge `hooks.json` 与项目/用户级冲突
- **Phase 1–2：** git remote 多命中/零命中策略与 `repo_unresolved` 文案

Phases with standard patterns (skip research-phase):
- **Phase 1 模型/INV-6：** 对照 `McpLearningCase` + `test_memory_inv6_guard`
- **Phase 2 `McpToolView`：** 现成基类 + alignment 测试
- **Phase 4 RetrievalTrace / structlog：** LOGGING-SPEC 已有清单

## Confidence Assessment

| Area | Confidence | Notes |
|------|------------|-------|
| Stack | HIGH | 复用既有 Django/MCP/skills/Qdrant；MEDIUM 仅宿主 hook 配对与枚举命名 |
| Features | HIGH | 仓内缺口与 PROJECT 目标一一对应；竞品 Mem0/CC hooks 官方文档交叉 |
| Architecture | HIGH | 接缝均对照源码；MEDIUM：价值分级提示词与 git 归一化实现细节 |
| Pitfalls | HIGH | 陷阱均有现行代码/测试/debug 会话证据 |

**Overall confidence:** HIGH

### Gaps to Address

规划相位必须钉死以下命名（研究文件用了两套近义词，roadmapper 选一写入 REQUIREMENTS）：

- **工具名：** `report_session_knowledge` vs `capture_ide_session` — 推荐 `report_session_knowledge`（与现 `report_*` 并列、skills 更好教）
- **`source_kind`：** `session_capture` vs `ide_session_knowledge` — 选一个写入 `generate_entity_id` docstring 规则表
- **`CallSource`：** `session_capture_eval` vs `ide_session_eval` — 单轮 LLM 用一个值；两轮再拆 distill/value
- **响应字段：** `accepted` vs 拆 `stored`/`accepted` — 推荐 Capture：`accepted=true` 表示已落账本；RAG 是否入图看 `value_tier`，不要再用 `accepted=false` 表示「没进记忆」
- **Cursor 采集：** STACK 主张官方 `afterAgentResponse`；PITFALLS 强调 MCP 主链、hooks 只增强。规划按「MCP 必达 + Cursor hooks 作自动触发」合并，验收必须含 Cursor 干净工作树
- **lookup 默认分支：** 是否在本里程碑改 `lookup_project_by_branch` 第三源，还是仅 Capture 写路径避开。推荐 **Capture 不调用第三源**；lookup 读路径修默认分支作为 P4 回归或小修补，避免读写继续分叉
- **容器 MCP 写路径：** 默认 Out of Scope，除非产品要「编码容器也能沉淀会话」
- **控制台回放：** 只读 API 可进 Phase 4；Vue 大页延后

## Locked Decisions（写入 roadmap 不得推翻）

- 仓库为主、项目可选；**永不丢 Capture**
- Capture ≠ 提炼知识 ≠ Interaction Ledger（Ledger 不是 RAG）
- **新 MCP 工具**，不是扩 `report_project_knowledge`
- **无新运行时库**
- medium/high → 仓级 RAG；`ProjectMemory` 保持 draft 门控
- 客户端抽精华；未知模型字段保持 `unknown`

## Sources

### Primary (HIGH confidence)
- 本仓：`server/mcp_tools/views.py`、`serializers.py`、`initiatives/models/memory.py`、`memory_service.py`、`ide_hook_assets.py`、`knowledge/ingestion.py`、`knowledge/sources/project_memory.py`、`skills/hooks/{stop,user-prompt-submit,hooks.json}`、`skills/lib/installer.mjs`、`mcp/src/tools.ts`、alignment/skills snapshot 测试、`.planning/PROJECT.md` v0.25.0
- Cursor Hooks 官方：https://cursor.com/docs/hooks.md — `afterAgentResponse` 有 `text`；`stop` 无助手正文；`beforeSubmitPrompt` 仅 continue/user_message
- Claude Code Hooks 官方：https://code.claude.com/docs/en/hooks — `last_assistant_message`；transcript 异步滞后
- Mem0 How it works：https://docs.mem0.ai/core-concepts/how-it-works — 提炼事实 vs transcript
- v0.15 MEM-04 / v0.16 Phase 86 active 直写 deviation / v0.17 Ledger ≠ RAG

### Secondary (MEDIUM confidence)
- Cursor 论坛注入请求（证明官方尚未交付 per-prompt 注入）
- 社区 Claude Code 插件（Stop 增量、fail-open exit 0）
- `.planning/debug/multica-friday-agent-e2e.md` — `main` 假命中无关项目

### Tertiary (LOW confidence)
- Cursor 本机 Memory MCP 教程 — 个人 JSON，不能替代团队知识库

---
*Research completed: 2026-08-28*
*Ready for roadmap: yes*
