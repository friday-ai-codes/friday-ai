# Phase 24: 敏感文件 AI 识别建议名单 - Context

**Gathered:** 2026-06-14
**Status:** Ready for planning
**Mode:** Smart discuss (autonomous, auto-accepted recommendations)

<domain>
## Phase Boundary

本阶段在索引/描述生成阶段**识别敏感文件**（密钥 / env / 敏感信息），产出**建议名单**供用户确认/增删，**不静默删除**（EXCL-03）。建议被用户接受后，接入 Phase 22 的 `RepoExclusionRule(source="ai_suggested")` 成为生效排除规则，并可触发 Phase 23 的清理。

本阶段做：
- 敏感文件检测器：混合策略——文件名/路径启发式（复用 Phase 22 `BUILTIN_GLOBAL_DEFAULTS` 密钥/env 模式）+ 内容级密钥扫描（私钥块、AWS/GCP/Slack/token 等已知格式、高熵字符串）+ **可选 LLM 辅助分类**（对配置类模糊文件判定"是否可能含敏感信息"）。LLM 不可用时退化为确定性启发式+内容扫描，不阻断。
- 建议名单模型 + 在索引/描述生成阶段产出建议（后台、不阻断索引）。
- "建议 + 提醒 + 用户确认"工作流：UI 展示建议名单，用户可接受（→ 建 `RepoExclusionRule(source=ai_suggested)`）/忽略；真密钥（命中实际密钥值）高优先级告警。
- 检测产物**绝不**明文记录/泄漏实际密钥值（脱敏存储 reason，只存命中类型/位置，不存密钥本体）。

本阶段**不做**：
- 排除规则的过滤/清理本身（Phase 22/23 已完成；本阶段只产出建议并复用其模型）。
- commit 历史 / 多仓（Phase 25/26）。
- 全自动删除（明确：只建议 + 用户确认，绝不静默删）。

</domain>

<decisions>
## Implementation Decisions

### D-01 检测策略（混合，确定性为主 + LLM 增强）
- **路径/文件名启发式**：复用 Phase 22 `services/exclusion.py` 的 `BUILTIN_GLOBAL_DEFAULTS`（`.env`、`*.pem`、`id_rsa` 等）作为敏感文件名基线。
- **内容级密钥扫描**：对候选文件正文做正则/熵检测——私钥头（`-----BEGIN ... PRIVATE KEY-----`）、AWS Access Key（`AKIA...`）、Slack/GitHub token、通用 `KEY=`/`SECRET=`/`PASSWORD=` 赋值、高熵 base64/hex 串。命中实际密钥值 → severity=`real_secret`（高优先级）。
- **可选 LLM 分类**：对启发式未覆盖但可疑的配置/文档类文件，调既有 provider（复用 `ProviderCredential`/`provider_config`）做"是否可能含敏感信息"二分类，输出 severity=`likely_sensitive`。provider 未配置/调用失败 → 跳过 LLM 段，仅用确定性结果（graceful，不阻断索引）。
- 检测器单一入口（如 `services/sensitive_detect.py::detect_sensitive_files(repo, files)`），返回结构化建议（path、severity、detector、reason 脱敏）。

### D-02 建议名单模型
- 新增 `SensitiveFileSuggestion`（repo FK、`path`、`severity`[real_secret|likely_sensitive|config_review]、`detector`[heuristic|content|llm]、`reason`（脱敏描述，**不含密钥本体**）、`status`[pending|accepted|dismissed]、`detected_at`、`updated_at`，唯一约束 (repo, path)）。
- upsert 语义：重复检测同一 path 更新而非重复插入；用户已 dismissed 的不反复打扰（除非升级为 real_secret）。

### D-03 工作流（建议 + 确认，不静默删）
- 检测在**索引/描述生成阶段**触发（`run_full_index` 后台流程末尾），best-effort、不阻断索引。
- UI：在仓库的排除规则区（复用 Phase 22 `ExclusionRulesPanel` 旁/同页）展示"AI 建议敏感文件"列表，按 severity 排序；real_secret 高优先级告警样式。
- 用户操作：**接受** → 创建 `RepoExclusionRule(source="ai_suggested", pattern=path, rule_type=dir/glob)` 并把 suggestion 标 accepted（接受后可一键触发 Phase 23 清理）；**忽略** → 标 dismissed。绝不自动建规则/删除。
- REST API：列出建议 / 接受（建规则）/ 忽略。

### D-04 安全与隐私
- **绝不**把实际密钥值写入 `reason`/日志/DB；reason 只描述类型与位置（如"检测到 RSA 私钥块，行 12"）。
- LLM 分类只传文件名 + 必要的最小化特征（或截断/脱敏内容），避免把密钥送给外部 provider；real_secret（强命中）不送 LLM。
- 检测异常 fail-safe：不阻断索引、不误标；埋审计点 `sensitive.detected`（计数/severity，无密钥本体）。

### Claude's Discretion
- `SensitiveFileSuggestion` 表名/字段细节、检测器落点、内容扫描正则库的精确集合、LLM prompt 与最小化特征构造、前端组件落点与告警样式，由 planner/executor 依既有约定决定。
- LLM 段是否默认开启（建议默认关或仅对少量可疑文件开，控成本），由 planner 依 provider 配置与成本权衡设定，确定性段始终启用。
</decisions>

<code_context>
## Existing Code Insights

### Reusable Assets（待 planner 核实）
- Phase 22 `server/services/exclusion.py` — `BUILTIN_GLOBAL_DEFAULTS`（敏感文件名基线）、`RepoExclusionRule`（含 `source="ai_suggested"` 取值，接受建议时复用）、`build_matcher_for_repo`。
- `server/services/indexer.py` — `run_full_index`（检测触发点）、描述生成流程。
- `server/services/provider_config.py` / `ProviderCredential` — LLM provider 解析（可选 LLM 分类复用）。
- Phase 22/23 前端 `ExclusionRulesPanel.vue` / `ReconcilePanel.vue` + `web/src/api/exclusions.ts` — 建议名单 UI 与接受→建规则→清理的衔接。
- `server/services/background_runner.py` — 后台执行。

### Established Patterns
- service 层无状态域逻辑；异步 ORM 经 `sync_to_async`；凭证 DB 加密；前端类型化 client + reka-ui + vue-i18n（默认中文）。
- LLM 调用复用既有 langchain/provider 适配层（research 既有 agent/provider 调用方式）。

### Integration Points
- 检测接入 `run_full_index` 后台；建议 API 注册进 `/api/repositories/<id>/...`；前端建议面板接 Phase 22 排除面板。
- 接受建议 → 复用 Phase 22 规则创建路径（serializer/视图）+ 缓存失效。
</code_context>

<specifics>
## Specific Ideas

- 守护测试：放置 `.env`（含 `AWS_SECRET_ACCESS_KEY=...`）、`id_rsa`（私钥块）、普通 `config.yaml`，断言前两者被识别（real_secret 高优先级）、产出建议且 reason 不含密钥本体。
- 断言"不静默删除"：检测只产出 `SensitiveFileSuggestion(status=pending)`，不自动建 RepoExclusionRule、不删任何数据。
- 断言 LLM 不可用时确定性检测仍工作（graceful 退化）。
- 接受建议 → 生成 `RepoExclusionRule(source=ai_suggested)` 并可衔接 Phase 23 清理的端到端守护。
</specifics>

<deferred>
## Deferred Ideas

- 全自动删除/隔离 → 不做（产品决策：只建议 + 确认）。
- commit 历史中的密钥扫描 → 关联 Phase 25 / backlog。
- 组织级敏感策略中心 / 全量审计 → v0.10。
</deferred>

---
*Phase: 24-sensitive-ai-detect*
*Context gathered: 2026-06-14 via smart discuss (autonomous)*
