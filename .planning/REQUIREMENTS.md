# Requirements: Friday AI v0.25.0

**Defined:** 2026-08-28
**Milestone:** v0.25.0 Cursor / Claude Code 会话知识回写
**Core Value:** 让团队开箱即用、安全地把需求变成代码——本里程碑补上「IDE 里问过的坑和决策能沉淀、能按仓召回」，不阻断编码。

## v0.25.0 Requirements

### Capture 账本（STORE）

- [x] **STORE-01**: 用户经 MCP 提交的结构化问答会落入独立 Capture 账本（问题、可见答案精华、回答模型、仓库、分支、会话、可选项目），不写入 `ProjectMemory` 或 Interaction Ledger 正文
- [x] **STORE-02**: Capture 的 `project_id` 与 `repository_id` 均可空；缺少项目不得拒绝落库
- [x] **STORE-03**: 所有 Capture 写入只经 INV-6 `CaptureService`（脱敏、`initiated_by_user_id`、禁止旁路 `objects.create`）
- [x] **STORE-04**: git remote / `git_url` 归一化后尽量挂钩已有 `Repository`；解析失败仍落库并记录显式 `reason`（如 `repo_unresolved`）
- [x] **STORE-05**: 拿不到的模型名、provider、token 计数字段记为 `unknown`，服务端不得猜测补全

### MCP 工具契约（MCP）

- [ ] **MCP-01**: 用户可通过新工具 `report_session_knowledge` 提交结构化会话回写（必填 `question`/`answer`；可选仓库、分支、会话、项目、`response_model`、`client`）
- [ ] **MCP-02**: 无 `project_id`、仓解析失败或默认分支无法唯一定位项目时，工具仍返回 200 且 `accepted=true` 并产生 Capture 行；`branch_unresolved` 不得表示未收
- [ ] **MCP-03**: 服务端 serializer、`TOOL_SCHEMA_SNAPSHOT` 与 npm `mcp/src/tools.ts` 对 `report_session_knowledge` 三面对齐；缺任一面对齐测试失败
- [ ] **MCP-04**: 既有 `report_project_knowledge` 的项目门闩与 git-diff 记忆路径保持零回归，本里程碑不把它扩成 Capture 入口

### 价值评估与入图（EVAL）

- [ ] **EVAL-01**: Friday 对每条已落库 Capture 异步评估 `high`/`medium`/`low` 并提炼可检索精华；评估失败保留原文 Capture，不得删除
- [ ] **EVAL-02**: 价值等级不得复用 `evaluate_writeback_quality` 或仓库路由 `confidence`；评估 LLM 使用新 `call_source=session_capture_eval` 并上报用量
- [ ] **EVAL-03**: `medium`/`high` 经既有 `aschedule_ingestion` 进入 `delivery_knowledge`（`EntityKind.DOCUMENT` + `source_kind=session_capture`）；`low` 不向量化，仍可作评测回放
- [ ] **EVAL-04**: 入图投递必须 persist-first 且可重试（durable/outbox + Capture 状态机）；禁止把进程内 `background_runner` 当作唯一投递
- [ ] **EVAL-05**: 评估与入图不得调用 `MemoryService.append` / `record_hook_writeback` 把会话 Capture 写成 active 项目记忆

### 召回与回放（RECALL）

- [ ] **RECALL-01**: 用户可按 `repository_id` 检索已入图的会话知识；有项目时也可按 `project_id` 检索
- [ ] **RECALL-02**: `pack_project_context` / 交付知识检索白名单显式包含 `session_capture`，避免入图后 IDE 召不回
- [ ] **RECALL-03**: 授权用户可按 Capture id 回放原始结构化问答（只读），不扫描 Ledger payload 当正文
- [ ] **RECALL-04**: 默认分支名 `main`/`master`/`develop` 不得单独把 Capture 写到错误项目；`lookup_project_by_branch` 第三源在默认分支上不得 `matched=true`

### Skills 与宿主采集（SKILL）

- [ ] **SKILL-01**: Cursor 与 Claude Code 的 Friday skills/hooks 抽取本轮问题与可见答案精华并调用 `report_session_knowledge`
- [ ] **SKILL-02**: 工作区无 git 改动（干净树 / 无 `diff --stat`）时仍回写问答 Capture
- [ ] **SKILL-03**: Claude Code 用 `UserPromptSubmit` 缓存问题 + `Stop.last_assistant_message` 抽答案；Cursor 用 `beforeSubmitPrompt` 只缓存问题 + `afterAgentResponse` 配对，禁止把 Claude 注入脚本拷到 Cursor `stop`
- [ ] **SKILL-04**: 客户端不上报隐藏思维链；skills / HTTP fallback / `ide_hook_assets` 与 snapshot 守卫同一验收
- [ ] **SKILL-05**: 安装器能 merge Cursor `hooks.json`（`version: 1`），无 PAT / 接口失败时 fail-soft 不阻断编码

### 可观测与安全（OBS）

- [x] **OBS-01**: Capture 持久化生命周期记 `category=caller` 的 started/completed/failed，含 `duration_ms` 与触发用户；评估/入图步骤用 `sampling`
- [x] **OBS-02**: 入库前强制脱敏；凭证、token、密钥不得出现在 Capture、Ledger、日志
- [ ] **OBS-03**: MCP 与对话召回链 best-effort 写 `RetrievalTrace`；观测失败不得改变回写或检索业务结果
- [ ] **OBS-04**: 后台评估/入图任务携带并 re-bind `initiated_by_user_id`；无触发用户记 `system`

## Future Requirements

- **FUTURE-01**: 控制台价值纠偏 UI 与人工改档
- **FUTURE-02**: SessionStart 按仓注入摘要（有 token 预算）
- **FUTURE-03**: Capture 与 `report_project_knowledge` 改动摘要去重合并
- **FUTURE-04**: 编码容器 MCP 白名单开放会话回写
- **FUTURE-05**: Capture 经确认写入 `ProjectMemory` draft/active
- **FUTURE-06**: 专用 IDE 采集插件（PROJX-04）

## Out of Scope

| Feature | Reason |
|---------|--------|
| 扩 `report_project_knowledge` 当 Capture 入口 | 项目记忆语义与无项目永不丢冲突；旧门闩保持零回归 |
| Interaction Ledger 当 RAG 正文 | v0.17 锁定 Ledger 不反哺检索 |
| 全文 transcript / 隐藏 CoT 入账本或向量 | 隐私、体积、召回污染 |
| 新建 Qdrant collection 或新 `EntityKind` | uuid5 漂移；统一走 `DOCUMENT` + `source_kind` |
| 新运行时 npm/Python 库 | brownfield 复用 Django/MCP/skills |
| 自动把 Capture 写成 active `ProjectMemory` | 保持 MEM-04；仓级 RAG 与项目长期记忆拆开 |
| Vue 大页回放工作台 | 小版本不做大前端；只读 API 足够验收 |
| 容器内编码代理写 Capture | 默认 Out of Scope，避免白名单漂移 |
| 用路由 confidence 或长度门槛当价值档 | 那是选仓把握/噪音门，不是知识价值 |

## Traceability

Which phases cover which requirements. Updated during roadmap creation.

| Requirement | Phase | Status |
|-------------|-------|--------|
| STORE-01 | Phase 141 | Complete |
| STORE-02 | Phase 141 | Complete |
| STORE-03 | Phase 141 | Complete |
| STORE-04 | Phase 141 | Complete |
| STORE-05 | Phase 141 | Complete |
| MCP-01 | Phase 142 | Pending |
| MCP-02 | Phase 142 | Pending |
| MCP-03 | Phase 142 | Pending |
| MCP-04 | Phase 142 | Pending |
| EVAL-01 | Phase 143 | Pending |
| EVAL-02 | Phase 143 | Pending |
| EVAL-03 | Phase 143 | Pending |
| EVAL-04 | Phase 143 | Pending |
| EVAL-05 | Phase 143 | Pending |
| RECALL-01 | Phase 144 | Pending |
| RECALL-02 | Phase 144 | Pending |
| RECALL-03 | Phase 144 | Pending |
| RECALL-04 | Phase 144 | Pending |
| SKILL-01 | Phase 145 | Pending |
| SKILL-02 | Phase 145 | Pending |
| SKILL-03 | Phase 145 | Pending |
| SKILL-04 | Phase 145 | Pending |
| SKILL-05 | Phase 145 | Pending |
| OBS-01 | Phase 141 | Complete |
| OBS-02 | Phase 141 | Complete |
| OBS-03 | Phase 144 | Pending |
| OBS-04 | Phase 143 | Pending |

**Coverage:**

- v1 requirements: 27 total
- Mapped to phases: 27
- Unmapped: 0
- Duplicate mappings: 0

---
*Requirements defined: 2026-08-28*
*Last updated: 2026-08-28 after creating v0.25.0 roadmap*
