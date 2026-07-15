# Project Research Summary

**Project:** Friday AI — v0.17.0 统一知识库与全链路联动（KNOW / LOOP / AGENT / UNIFY）
**Domain:** brownfield 增量：AI 编码代理平台的统一知识库 / agent memory / 完工沉淀闭环 / 容器代理工具配给
**Researched:** 2026-07-15
**Confidence:** HIGH（四份研究均以本仓真实代码坐标核实；外部生态结论与官方文档/多源交叉验证一致）

## Executive Summary

本里程碑是纯集成型工作：**零新增依赖、不新建存储、不引入新架构**。Friday 既有的 `KnowledgeEntity` + bi-temporal 图边 + Qdrant 混合检索在架构上就是业界头部方案（Zep/Graphiti）的同型，本里程碑要做的不是造新东西，而是把三类"最后一公里"断点接进既有架构：① 漏网数据源（`McpLearningCase`、MCP 三类产物）接入单一摄取入口 `aschedule_ingestion` 与单一检索面 `DeliveryKnowledgeSearchService`；② 完工闭环（飞书回写 + LLM 自动提炼 learning case）在工作流/Chat/MCP 三链路的"MR 结果已知"锚点统一接线；③ 编码容器经进程内 SDK MCP server（`create_sdk_mcp_server` + httpx 转调 `/api/mcp/tools/*`，生产蓝本 `task/core/remote_tools.py`）获得受控知识读能力，skills 物料构建期同源注入。业界对照显示：完工业务回写是 table stakes（Copilot 基线行为），全自动提炼入库则超出 Devin/Cursor 的"建议 + 人工审核"形态，是本里程碑的差异化核心——前提是质量门槛与功能同 phase 落地。

推荐路径：KNOW 块的 learning case 入图（KNOW-1）是全里程碑枢纽——LOOP 沉淀的入库通道、检索切换的底层、编排召回扩容、容器查经验的数据源全部依赖它，必须最先做；LOOP 回写与 KNOW 无依赖可并行；AGENT 容器 MCP 应在 KNOW 检索行为定版后集成（避免对着会变的契约集成两次）；UNIFY 收口放最后。**唯一需要提前到 discuss-phase 的架构决策是容器 MCP 的 PAT 可用性问题**：Chat 链与飞书触发的 workflow 链在派发线程内拿不到 PAT 明文，需在"接受降级（选项 A）"与"派发时铸造短 TTL 任务级 token（选项 B，与历史决策 PATX-04 冲突需显式推翻）"之间做人工确认——这直接决定 AGENT 块的验收口径。

最大风险两类，均有明确预防手段：一是检索底层切换（token→向量）的召回回归——精确路径/symbol 类查询是向量检索的天然弱项，且存量 case 无 backfill 会当天全空；缓解是 golden set 对照测试作为验收门 + normalizer/backfill/读切换同 phase 闭环 + hint 参数走 metadata 过滤不做摆设。二是自动沉淀的噪音污染——业界一手案例（mem0 审计 97.8% 垃圾率）证明"无准入门槛 + 回调重入"必然污染知识库；缓解是幂等键（TaskResult UUID）+ 显式 REJECT 路径 + `call_source` 登记 + 系统级开关，且必须与提炼功能同 PR 落地而非"先跑通后补"。

## Key Findings

### Recommended Stack

三件新能力全部由既有栈覆盖，`task/pyproject.toml`、`server/pyproject.toml`、`skills/package.json` 一律不动。容器内 HTTP 代理型 MCP server 照抄 `task/core/remote_tools.py` 模式（`SdkMcpTool` 直接构造、handler 永不 raise、PAT 只进 header）；skills 注入是纯 stdlib 文件拷贝（`shutil.copytree`），加载通道 `setting_sources=["project"]` 已在 v0.9.0 验证；LLM 提炼在服务端走 `build_chat_model` seam，同构先例 `server/initiatives/services/memory_distill.py` 已把 call_source/ledger/脱敏/fail-soft 全套模式踩通。

**Core technologies:**
- claude-agent-sdk ==0.1.58（双侧 pinned，不升级）：进程内 SDK MCP server；0.1.58 已修复 string prompt + SDK MCP 的 stdin 时序崩溃与 ~70s 超时坑，生产已并存 3 个 SDK MCP server，新增第 4 个走完全相同路径
- httpx（task 侧已有）：MCP handler 内转调服务端；注意知识 MCP 目标是 `/api/mcp/tools/<name>/` 每工具一 URL，与 RemoteTool 统一端点不同，需新建 `task/core/knowledge_tools.py` 而非硬塞进 remote_tools.py
- langchain 栈 + `agents.llm_factory.build_chat_model`（server 侧既有）：learning case 提炼；凭证走 `ProviderConfigService` 不走 env
- 明确不引入：`fastmcp`/显式 `mcp` 依赖、服务端 MCP streamable-HTTP 协议层（`McpHttpServerConfig` 不能指向普通 REST 端点）、task 侧 LLM SDK、skills 运行时 HTTP 拉取

**唯一构建坑**：task 镜像 build context 是 `./task`，仓库根 `skills/skills/` 在 context 外——推荐构建前同步脚本拷进 `task/assets/skills/` + Dockerfile COPY + hash 一致性测试，不要改 build context（改动面大）。

### Expected Features

业界基线（Devin/Cursor/Copilot/Qodo 对照）显示：单一检索入口覆盖全部记忆类型、产物不分入口一律入库、完工自动回写业务方，都是 table stakes——三链路回写不一致在业界属于产品缺陷而非功能选择。

**Must have (table stakes，P1)：**
- KNOW-1/2 learning case 入图 + `search_learning_cases` 切向量检索（token 打分退役，API 契约不变）——统一知识库的定义性交付
- KNOW-3 MCP 产物入图（plan/analysis/trace 各补 normalizer）——消除"走 MCP 就成盲区"的管道断裂
- LOOP-1 公共回写 service 三链路接入——业务侧可见性底线
- LOOP-2 完工自动提炼（质量门槛全套同 phase）——差异化核心
- AGENT-1 容器知识 MCP（7 个只读工具白名单 + 配额/超时）——"知识贫民区"直接解药
- AGENT-3 工作流 prepend `pack_project_context`——复杂度最低、断裂感消除最直接
- UNIFY-2 schema snapshot 补全（`report_project_state` 已核实缺失）

**Should have (P2，机制已有、物料/薄封装为主)：**
- KNOW-4 编排召回扩 `document`/`learning_case` kinds（可配置 + 每 kind 限额守 token 预算）
- KNOW-5 Chat 白名单补 3 个知识读工具
- LOOP-3 平台 Skill 两枚（`pre_coding_research`/`post_coding_capture`，复用 RemoteTool SKILL 多步机制）
- AGENT-2 容器 skills 注入 + hash 一致性测试

**Defer / 降级候选：**
- LOOP-4 PR 后轻量 review 沉淀（依赖最深的增值项，进度紧最先降级）；UNIFY-1 improve/analyze 收敛（内部重构，可排后但建议做）
- 显式不做：chat.CodingPlan 与 McpCodingPlan 合表、review 产品化、会话内 sidecar 记忆提取、consolidation/decay 自动策展

**Anti-features（业界踩过的坑）：** 主模型直接 tool-call 写记忆（产出任务日志而非可泛化知识）、"记住一切"无门槛入库（lesson rot）、给容器开放全部 30 工具、容器直连 Qdrant/DB、learning case 造第二套排序、记忆无条件注入对话开头（context pollution）。

### Architecture Approach

全部集成点已读码核实，无外部生态依赖。核心形态：各域写模型保留（`McpLearningCase` 等），触发点只投 ID（`aschedule_ingestion`），normalizer 后台重读入图；检索一律走 `DeliveryKnowledgeSearchService` 按 `entity_kinds` 过滤；完工闭环挂三链路各自的"MR 结果已知"锚点（不挂容器回调——回调时刻 MR 未建且有重试风暴前科，INGEST-02 既有结论）；容器能力 = 服务端 HTTP 工具面复用 + env 三要素开关（任一为空整体降级不挂，零回归）。

**Major components（新增/修改）：**
1. 4 个新 normalizer（`knowledge/sources/learning_case.py` 等）+ `EntityKind.LEARNING_CASE` 新字面值（走 Phase 79 扩枚举先例，一个 migration 更新 CHECK 约束）——推荐新 kind 而非复用 `document`，否则检索/召回的 kind 过滤无法区分经验案例与项目记忆
2. `CompletionWritebackService`（建议落 `server/delivery/services/coding_completion.py`）：从 `_write_results_back` 抽取中性化参数版；MCP 改薄包装零回归，workflow 挂 `_finalize_and_notify`，chat 挂 `create_pr_or_skip_node`；MCP 专属 retry_state 不进公共层
3. `task/core/knowledge_tools.py` `build_knowledge_mcp_server`：镜像 remote_tools.py 全套约束；配置经 `env_FRIDAY_TASK_*` → runner 透传 → `TaskConfig` 既有链路；`allowed_tools` 排他白名单必须并入 `_BUILTIN_CODING_TOOLS`（WR-02 前科，需收口单一构造函数 + 专项测试）
4. 容器 skills 注入：镜像构建期 COPY + `runner.py` workspace 准备段复制进 `.claude/skills/`（同名跳过不覆盖）；不要走 env 传输（ARG_MAX 压力）
5. `search_learning_cases` 底层切换 + recall_adapter kinds 扩容 + Chat 白名单 + snapshot 补全（均为既有模式的接线）

**⚠️ 唯一悬置架构决策（必须 discuss-phase 解决）**：PAT 明文可用性三链路不一致——MCP 链可捕获但 dispatch 路径未接 ContextVar；Chat 链（cookie-JWT）与飞书/定时触发的 workflow 链线程内没有 PAT 明文。选项 A（最小改动）：接受降级，无 PAT 链路只靠 prepend 上下文兜底；选项 B（研究推荐但需人确认）：派发时铸造短 TTL 任务级 token（明文不落盘不反取，不违反 PAT-02，但与"短 TTL 派生凭证留 v2"的历史决策 PATX-04 冲突，需显式推翻）。

### Critical Pitfalls

1. **检索切换召回回归与契约漂移（P1）**——golden set（30–100 条真实查询含路径/symbol 类）对照测试为验收门；normalizer + backfill + 读切换同 phase 闭环；hint 参数映射 metadata 过滤/rerank 不做摆设；score 语义显式定版进 snapshot；Qdrant 故障 fail-soft 空结果不 500。
2. **自动沉淀噪音污染与成本失控（P2）**——TaskResult UUID 幂等键前置（callback 重入自驱是本仓已知设计）；准入门槛（status 门、字段完整性门、显式 REJECT 路径 + 结构化 rejected 事件）；新 `call_source` 先登记 LOGGING-SPEC §4.1 再写代码；`SystemSetting` 系统级开关可秒关。污染入库后清理成本远高于预防（mem0 案例 97.8% 垃圾率）。
3. **回写开关默认值改变存量行为（P3）**——区分"模板默认开"与"存量 fallback"（config 无该键时：有绑定 work_item 才回写、无绑定静默跳过）；成功标准显式含"存量工作流（未绑定 work_item）行为零变化"用例 + 升级说明。
4. **容器 MCP 四险（P4）**——白名单锁 7 个只读工具 + per-task 配额/超时（配额用尽返回 agent 可理解的明确文案）；PAT 只走进程内存不落任何 workspace 文件，错误信息过 `redact_secrets_in_text`；`allowed_tools` 三方 merge 收口单一构造函数 + 断言 Bash/Edit/Write 在列；容器视角排除回归测试（v0.5 六面加第七面）；QPS/调用数观测与功能同 phase 上线。
5. **实体去重/关联错误（P7）**——入图前先扩 `generate_entity_id` docstring natural key 规则表（locked，漂移需数据迁移）；Chat plan 与 MCP plan 推荐"不同实体 + 边显式关联"（硬去重踩 bridge 拷贝时序坑）；work_item 锚照抄 `mcp_plan.py` 禁止自造；每个 normalizer 带重复摄取幂等测试 + plan→execution→PR 边可达性端到端断言。

另有：skills 双源漂移（hash 一致性 CI 测试 + skill 引用工具名 ∈ snapshot 的 grep 测试）、UNIFY 退役 planning_service 的 stale mock target（本仓 Phase 26 前科，`rg planning_service` 引用清单为第一个 task）、观测欠债（不设独立观测 phase，埋点断言内嵌各功能 phase 验收标准）。

## Implications for Roadmap

基于依赖分析（ARCHITECTURE 构建顺序 + FEATURES 依赖图 + PITFALLS phase 映射），建议 7 个 phase：

### Phase 1: KNOW-基座 — learning case 入图与检索切换
**Rationale:** KNOW-1 是全里程碑枢纽，LOOP 沉淀/召回扩容/容器查经验全部依赖；natural key 规则表决策（P7 前置）也在此落定供后续 normalizer 遵循。
**Delivers:** `EntityKind.LEARNING_CASE` + migration、`learning_case` normalizer（含 work_item/tech_plan 边）、`create_learning_case` 投递、存量 backfill command、`search_learning_cases` 底层切换（契约不变）。
**Addresses:** KNOW-1/2（P1 必达）；验收面 1 的前提。
**Avoids:** Pitfall 1（golden set 对照测试为验收门；normalizer/backfill/读切换同 phase 闭环）、Pitfall 7（规则表先行）。

### Phase 2: KNOW-MCP 产物入图
**Rationale:** 与 Phase 1 无硬依赖可并行（共享 Phase 1 的规则表决策，若并行则规则表决策放先执行者）。
**Delivers:** McpCodingPlan/McpRepositoryAnalysis/McpCodingExecutionTrace 三个 normalizer + 写入点投递 + 与 chat plan 的边关联决策落地。
**Addresses:** KNOW-3（P1）；验收面 2。
**Avoids:** Pitfall 7（幂等测试 + plan→execution→PR 边可达性自动化断言）。

### Phase 3: LOOP-回写 — 公共 write-back service 三链路接入
**Rationale:** 与 KNOW 无依赖，可与 Phase 1/2 并行；同时为 Phase 4 的沉淀提供锚点管线。
**Delivers:** `CompletionWritebackService` 抽取（MCP 薄包装零回归）+ workflow `_finalize_and_notify` / chat `create_pr_or_skip_node` 锚点接线 + 节点开关（模板默认开、存量 fallback 守门）。
**Addresses:** LOOP-1（P1）；验收面 3。
**Avoids:** Pitfall 3（fallback 语义/守门/与 notify_feishu_im 去重界定为设计输入，非收尾补丁）。

### Phase 4: LOOP-沉淀 — 完工自动提炼 learning case
**Rationale:** 依赖 Phase 1（入图通路）+ Phase 3（锚点管线成型）。
**Delivers:** LLM 提炼（outcome/root_cause/solution/trigger_context 结构化字段）+ 幂等键 + 准入门槛（泛化过滤/去重/脱敏/字段校验/REJECT 路径）+ 新 `call_source` 登记 + 系统级开关 + 三锚点接线；`McpLearningCase` FK 放松（如需）。
**Addresses:** LOOP-2（P1，差异化核心）；验收面 4。
**Avoids:** Pitfall 2（质量门与功能同 phase，绝不"先跑通后补"）。

### Phase 5: AGENT — 容器知识 MCP + skills 注入 + 上下文对齐
**Rationale:** 容器白名单调的正是 KNOW 定版后的检索工具，放 KNOW 之后避免对着会变的契约集成两次；**PAT 方案（选项 A/B）需在 discuss-phase 先决策**。AGENT-3（prepend pack_project_context）无硬依赖，是本 phase 内最低风险项。
**Delivers:** `task/core/knowledge_tools.py` + TaskConfig 字段 + 三派发路径 env 注入 + allowed_tools 合并收口测试 + per-task 配额/超时 + 容器视角排除测试 + QPS 观测；镜像 COPY skills + runner 注入 + hash 一致性测试；workflow `_dispatch_wave` 层 prepend `pack_project_context`（按 (project, branch) 解析一次逐仓复用）。
**Addresses:** AGENT-1/2/3（P1/P2）；验收面 5/6/7。
**Avoids:** Pitfall 4（四险全套同 phase）、Pitfall 5（同源测试）。

### Phase 6: KNOW-消费面 + LOOP-Skill 种子
**Rationale:** 依赖 Phase 1（learning_case kind 存在、检索已切向量版）；均为薄接线/物料工作，聚合成一个收敛 phase。
**Delivers:** recall_adapter kinds 扩容（可配置 + 每 kind 限额）、Chat 白名单 3 工具、`pre_coding_research`/`post_coding_capture` 两个 SKILL 种子、friday-memory skills 文档与新检索行为对齐、snapshot 补 `report_project_state`（含"注册工具 == snapshot 键集合"防漏断言）。
**Addresses:** KNOW-4/5、LOOP-3、UNIFY-2（P1/P2）；验收面 9/10。
**Avoids:** Pitfall 5（文档对齐）、召回 token 预算膨胀（Performance Trap）。

### Phase 7: UNIFY 收口 + 端到端验收
**Rationale:** improve/analyze 收敛依赖编排召回扩容先就位（否则收敛后工具质量降级）；退役工作放最后减少 rebase 面冲突。契约决策（同步 vs 会话式）是首个 task。
**Delivers:** improve/analyze 走 `delegate_process_runtime` + 退役 `planning_service` 缝（先 `rg` 引用清单）+ 删 `plan_orchestration/` 空壳 + stale mock target 清扫；四处检索同一 learning case 的端到端验收；LOOP-4 PR 后 review 沉淀（可选增值项，进度紧降级）。
**Addresses:** UNIFY-1、LOOP-4（P3）；验收面 1/8。
**Avoids:** Pitfall 6（契约先定、引用先清、patch target 可 import 断言）。

### Phase Ordering Rationale

- **Phase 1 的 natural key 规则表决策先于一切入图工作**（P1/P7 共享前置）；Phase 1/2/3 三者互无依赖可并行推进。
- **Phase 4 沉淀必须在 Phase 1（入库通道）与 Phase 3（锚点）之后**——沉淀产物要能被统一检索到才有意义。
- **Phase 5 放 KNOW 之后**：容器集成的是定版后的工具契约；PAT 决策是唯一需要人工确认的前置。
- **Phase 7 收口放最后**：UNIFY 是内部重构，早做会与 KNOW/LOOP 的改动面冲突；且 process_runtime 承接 improve/analyze 前需要编排召回先扩容。
- **观测埋点不设独立 phase**：RetrievalTrace/call_source/QPS 断言按 Pitfall 8 的分配内嵌进各 phase success criteria——漏埋直接等于验收不过。

### Research Flags

Phases likely needing deeper research during planning:
- **Phase 5（AGENT）:** PAT 方案选项 A/B 是架构决策，需 discuss-phase 人工确认（选项 B 与历史决策 PATX-04 冲突）；MCP dispatch 路径的 ContextVar 捕获缺口（PROJECT.md 已列 known follow-up）需实现细节确认。
- **Phase 4（LOOP-沉淀）:** 提炼 prompt 的泛化性过滤是成败关键（业界教训集中地），plan-phase 时建议细化 prompt 设计与去重阈值（参考值 cosine > 0.92）。
- **Phase 7（UNIFY）:** improve/analyze 的对外契约（同步 vs 会话式）决策影响 Cursor 侧体验，需在 phase 内首个 task 定版。

Phases with standard patterns (skip research-phase):
- **Phase 1/2（KNOW 入图）:** normalizer 契约、双事件锚模式、幂等翻转全部有既有先例（`coding_plan.py`/`mcp_plan.py`），照抄即可。
- **Phase 3（LOOP-回写）:** 抽取源 `_write_results_back` 依赖面已逐项核实，纯重构。
- **Phase 6（消费面）:** 全部是既有机制的接线（RECALL-02 先例、SKILL steps 执行器、snapshot 纪律）。

## Confidence Assessment

| Area | Confidence | Notes |
|------|------------|-------|
| Stack | HIGH | 版本全部经本仓 uv.lock/pyproject/已安装源码逐行核实；SDK 坑与修复经上游 issue + 本地源码交叉验证 |
| Features | MEDIUM-HIGH | claude-agent-sdk 集成与 memory 生态为 HIGH（官方文档多源一致）；Devin/Cursor 内部机制为 MEDIUM（官方文档 + 工程访谈）；本项目落点坐标为 HIGH |
| Architecture | HIGH | 全部集成点读码核实到文件/函数/行号；无外部生态依赖，纯内部集成 |
| Pitfalls | HIGH | 坑 1–8 均以仓库真实代码坐标 + 外部来源交叉验证；个别缓解手段为 MEDIUM（正文已标注） |

**Overall confidence:** HIGH

### Gaps to Address

- **容器 MCP 的 PAT 三链路可用性（唯一悬置架构决策）**: discuss-phase 必须在选项 A（接受降级）/选项 B（短 TTL 任务级 token，需推翻 PATX-04）间定版——直接决定验收面第 5 条的口径。
- **token 版检索 fallback 开关是否保留一个里程碑周期**: plan-phase 权衡（MEDIUM，Pitfall 1 缓解项）。
- **检索层关联簇去重的具体层次**（Chat plan 与 MCP plan 同簇只出最优一条）: plan-phase 定（MEDIUM，Pitfall 7）。
- **Phase 26 遗留 5 例 stale patch target 是否顺手修**: plan-phase 定（MEDIUM，Pitfall 6）。
- **容器版 skills 是否裁剪（friday-memory 的 setup 向导段对容器无意义）**: 若裁剪则构建脚本生成、仍以 `skills/` 包为唯一输入。
- **CI 产物 PAT 前缀扫描的具体点位**: plan-phase 定（MEDIUM，Security Mistakes）。

## Sources

### Primary (HIGH confidence)
- 本仓一手代码核实 — `server/knowledge/{ingestion,models,retrieval}.py`、`knowledge/sources/`、`server/mcp_tools/*`、`server/workflows/nodes/ai/coding.py`、`server/chat/coding_session_service.py`、`server/subagent/api/callbacks.py`、`task/core/{executor,config,remote_tools,runner}.py`、`task/.venv` 内 claude-agent-sdk 已安装源码（types.py/query.py/版本文件逐行核实）
- 锁文件与配置 — `task/uv.lock`、`server/uv.lock`、双侧 `pyproject.toml`、`docker-compose.build.yaml`、`.github/workflows/release.yaml`
- `.planning/MILESTONE-CONTEXT.md` / `.planning/PROJECT.md` — 里程碑范围、锁定决策、复用坐标、历史前科（WR-02/PAT-02/INGEST-02/Phase 26）
- 官方文档 — code.claude.com Agent SDK（create_sdk_mcp_server/McpServerConfig/allowed_tools/setting_sources/安全部署 proxy 模式）、docs.devin.ai（Knowledge/Skills）、docs.github.com Copilot coding agent、docs.qodo.ai auto best practices
- 学术源 — Reflexion（NeurIPS 2023）、ExpeL（AAAI 2024）：失败经验价值、insight 策展、lesson rot 与显式 retire
- 一手案例 — mem0ai/mem0 issue #4573（10,134 条自动沉淀记忆审计 97.8% 垃圾率）

### Secondary (MEDIUM confidence)
- claude-agent-sdk-python 上游 issue #578/#817、#676/#730/#731 — 与已安装源码交叉验证一致
- Cursor Memories 工程访谈（多源一致）— sidecar vs tool-call、任务日志偏好、激进过滤
- Zep arXiv 2501.13956 / Mem0 blog / 2026 memory 综述 — 记忆分型、bi-temporal、context pollution
- Memory MCP server 生态（Loci/AutoMem 等）— 工具面形态、去重门 cosine>0.92 参考值、fail-soft 协议
- 检索切换回归防护多源（golden set/recall@k/hybrid 补召回）— 行业共识

---
*Research completed: 2026-07-15*
*Ready for roadmap: yes*
