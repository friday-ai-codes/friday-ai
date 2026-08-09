# Phase 126: process-rename-skills - Research

**Researched:** 2026-08-10
**Domain:** Endpoint 正向执行流持久化（ProcessTrace）+ affected_processes 回填 + 只读 rename_preview + skills 同源分发
**Confidence:** HIGH

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions

#### Area 1: Process BFS 持久化 / 刷新 / 模型 schema（EXEC-01/02）

- **D-01 — 独立模型名锁定为 `ProcessTrace`（research ARCHITECTURE），落点 `server/codegraph/models.py`，纯加表、零改既有表。** ⛔ 不得命名为 `Process`（与 `services.process_runtime.ProcessEngine` / `ProcessDefinition` / delivery `process_type` 撞名）。字段最小集：`repository` FK、`branch_name`（`""`=基线，对齐 Symbol/Endpoint/SymbolCommunity）、`process_key`（稳定键）、`name`（展示名）、`entry_endpoint` JSON 快照（`{http_method,url_path,handler_name,file_path,line_number}`，⛔ 不对 `Endpoint` 建 FK——索引删建会牵连）、`steps` JSON（主干有序摘要，见 D-04）、`community_class`（封闭枚举 `intra_community` | `cross_community`）、`step_count`、`built_at_sha`（对齐 `last_indexed_commit_sha`）、时间戳。`unique_together = (repository, branch_name, process_key)`。
- **D-02 — 入口与 BFS 纪律硬锁 ROADMAP / GitNexus 同款数值，不作相位内再议。** 入口 = 该仓该分支已落库的 `Endpoint` 行映射到图上的 handler 符号（确定性，不做多因子入口打分）。遍历：正向 BFS；`maxDepth=10`；`maxBranching=4`；`minSteps=3`（滤掉平凡两步流）；只走置信度 ≥0.5 的边；visited 去重；同 entry→terminal 端点去重留最长 + 子集去重（短 trace 是长 trace 子串则删）。`maxProcesses` 初值按仓规模动态 `max(20, min(300, symbolCount/10))`（可 settings/env，Claude's Discretion 微调但不改成功标准四个硬闸）。环：检测后标 `cycle: true`（或等价字段），⛔ 不静默跳过。async 断链：识别已知派发模式（`sync_to_async` / durable `defer` / `.delay(` / channel `group_send` / workflow dispatch 等，词表 Claude's Discretion 扩展）在链路末端标 `boundary: async_dispatch`，v1 **不跨过**边界。
- **D-03 — 刷新语义照抄 Phase 125 社区：全仓全删全建，投 durable `QUEUE_GRAPH`，不在索引钩子内联跑。** 触发点 = 社区检测落库完成之后（Process 分类依赖 `SymbolCommunity`；若社区任务失败/空，Process 仍可建但 `community_class` 降级声明，见 D-05）。`queueing_lock=f"process:{repo_id}:{branch}"` 去重防抖；`initiated_by_user_id` 透传（无则 `system`）。任务内经 barrel `get_graph_service` 取图，⛔ 不直连 loader/cache，⛔ 不进 `repo_router_v2`。`built_at_sha` 落水位，查询方可判 stale。
- **D-04 — 落库存「入口 + 主干路径 + 统计」，不存全展开节点集（Pitfall 4）。** `steps[]` 每项至少 `{symbol_id?, name, file_path, line?, depth, community_key?}`——`symbol_id` 为 UUID 字符串软引用（对齐 125 D-02）。单行 JSON 体积纪律：主干截断 + summary 计数；超限标 `truncated`。`process_key` / `name` 启发式：优先 `METHOD path` 或 handler 名派生，须稳定可复现（细节 Claude's Discretion）。

#### Area 2: MCP 查询 + `affected_processes` 回填进 impact_report（EXEC-02/03）

- **D-05 — 社区分类：路径上符号对账 `SymbolCommunity.members` 软引用。** 路径成员（可解析到的）落在同一 `community_key` → `intra_community`；跨越 ≥2 个社区 → `cross_community`（架构上更重要，查询默认可按此类优先排序）。无法对账（社区未建 / 成员孤儿）→ 仍落库 Process，但输出带 `community_class_unknown` / degradation 声明，⛔ 不编造社区。
- **D-06 — 双面查询照抄 122 D-21：共享编排 + MCP/对话薄壳，逻辑不许在壳里分叉。** 新增编排入口（建议 `run_list_processes` / `run_get_process`，落 `server/services/code_graph_tools.py` 旁路，与 `run_impact`/`run_detect_changes` 同级）；内核纯函数优先 `server/services/code_graph/process_trace.py`。MCP：`McpToolView` + PAT fail-closed + schema snapshot + `RetrievalTrace`；对话：`agents/tools` `@tool`。查询参数最小集：`repository_id` + 可选 `branch_name` / `community_class` / `symbol_id`（命中含该步的流程）/ `limit`。信封复用 122：`ok`/`error_code`/`error` + `staleness` + `degradation`；`as_of`=`built_at_sha` 或索引水位。⛔ 不碰 `mcp/` submodule（122 D-27）；SUMMARY 更新 snapshot 漂移计数即可。
- **D-07 — `affected_processes` 回填点 = `run_detect_changes` 与 `run_impact` 已预留的空数组字段（123 D-12 / 122 VERIFICATION），单一组装 helper，禁止第三套方言。** 匹配：变更/impact 命中符号的软 id（或 `file_path:name` 回退键）∩ `ProcessTrace.steps` → 产出 `{name, process_key, affected_steps[], total_steps, community_class, step?}`。无 Process 行 / 无交集 → `[]`（合法，fail-soft）。批量 detect_changes 路径：在 batch impact 汇总后一次查仓内 Process 集再对账，避免 N 次扫表（具体索引 Claude's Discretion）。
- **D-08 — MR `## 影响面` 消费：在 Affected 小节增值「受影响执行流」清单（名称 + 可选 step/totalSteps），由 `build_impact_report_section` 单一入口渲染。** 有数据则替换 Phase 124 占位句「执行流叙事待 Phase 126…」；仍为空则保留短声明「暂无匹配执行流 / 未构建 Process」，⛔ 不编造。体积纪律继承 124 D-08（top-N + truncated）。双链路（workflow coding MR + MCP create_merge_request）继续共用同一 formatter（124 D-14）。

#### Area 3: rename_preview 双源合并 / 置信度 / 只读安全（RENAME-01）

- **D-09 — 只读预览工具，双源合并：图解析引用为主 + `grep_mirror` 文本兜底；按文件分组输出清单，`applied` 恒为 `false`。** 内核建议 `server/services/code_graph/rename_preview.py`；编排 `run_rename_preview` 进 `code_graph_tools.py`；MCP + 对话双面薄壳同 D-06。⛔ 本相位不提供 apply/rewrite API、不改工作树、不写 mirror。输入：目标符号（uid 优先，重名走 122 D-19 消歧）+ 新名；输出 edits 列表供编码代理自行改。
- **D-10 — 逐条置信标签二值：`graph` | `text_search`（RENAME-01 / GitNexus 同款），附 `context` 片段；同 `file:line` 双源命中时保留一条并以 `graph` 为准（或 `sources: ["graph","text_search"]` 但展示置信取 graph）。** summary 计数：`total_edits` / `files_affected` / `graph_edits` / `text_search_edits`。⛔ 不发明第三档「maybe」数值分掩盖不确定性。
- **D-11 — 安全与 exclusion：grep 半边必须走既有已拦截路径（`grep_mirror` + MCP grep 同款 exclusion fail-closed），禁止另起裸 grep（Pitfall）。** 输出头部/信封显式声明动态引用覆盖限制（字符串模板、反射、`getattr`、配置拼路径等 v1 不保证命中）。`include_content` 默认只给短 context，不灌全文。ACL / 未索引 / 消歧失败语义对齐 122/123（硬拒或 `ok=False`，不静默空清单假装「零引用」——空清单仅当双源都真实零命中且声明完整）。
- **D-12 — 容器白名单：`rename_preview` 可进 `task/core/knowledge_tools.py` 白名单（与 detect_changes 同路），skill 指引编码代理「先 preview 再自行编辑」；失败不阻断交付。** prompt 长文案放 skill 正文，不在 runner 硬编码改写逻辑。

#### Area 4: Skills 打包 / hash / 容器分发（SKILL-01）

- **D-13 — 两个新 skill 落 `@friday-ai-codes/skills` 子模块源目录 `skills/skills/`，命名对齐既有 `friday-*` 惯例：`friday-impact`（impact-analysis 工作流）与 `friday-refactoring`（refactoring + rename_preview 工作流）。** 正文 zh-CN；内容 = 触发条件 + 工具调用顺序 checklist（先 context/staleness → detect_changes/impact/list_processes → rename_preview），不复制工具实现。更新 `skills/README.md` 技能表与安装器枚举面（照抄 friday-routing 接入先例）。⛔ 不在主仓手写第二份 skill 正文。
- **D-14 — 编码容器同源：扩展 `task/scripts/sync_skills.py` 与 `task/tests/test_skills_injection.py` 的 `SKILL_NAMES`，纳入 `friday-impact` / `friday-refactoring`（二者均为编码期工作流，与 friday-routing「仅 IDE」分流不同）。** 改源后必须重跑 `python task/scripts/sync_skills.py`；`TestSkillsHashConsistency` 逐文件 sha256 守卫防双源漂移。镜像 COPY 路径沿用 `task/assets/skills/`（v0.17.0 AGENT-03）。
- **D-15 — 分发契约：子模块内提交 skill 源 + 主仓提交子模块指针 + `task/assets/skills/` 同步结果 + 文档；npm 发版 `@friday-ai-codes/skills` 为运维 follow-up（可记 Deferred，不阻断相位验收——验收以源目录存在 + hash 绿 + 容器注入测为准）。** 外部 agent 经既有 `npx @friday-ai-codes/skills install` 路径获得；不另造安装器。
- **D-16 — 冻结与并发纪律延续：** ⛔ 不改 `repo_router_v2.py`；⛔ 不改 `mcp/` submodule。本相位若新增 server MCP 工具名，SUMMARY 记账 npm 客户端漂移即可。并发 WIP：提交本 CONTEXT / 后续相位文档时**只 stage 显式路径**，禁止 `git add -A`。

### Claude's Discretion

- `process_key` / `name` 启发式具体字符串；`maxProcesses` 与 settings 键名；async 断链词表扩写。
- Process durable 任务是独立 task name 还是挂在 community 完成回调链式 enqueue（须仍走 `QUEUE_GRAPH` + 独立 queueing_lock）。
- `steps` JSON 是否额外存边 reason；查询工具是 list+get 两个还是一个带 detail flag。
- rename_preview 参数命名（`old_name`/`new_name` vs `symbol_id`+`new_name`）、context 行窗大小、双源合并字段是单 `confidence` 还是 `confidence`+`sources[]`。
- skill 正文长度与是否附 `references/` 小抄；npm version bump 时机。
- 测试组织：BFS 合成图单测、社区分类、affected_processes 对账、rename 双源 fixture、skills hash、impact_report 快照。

### Deferred Ideas (OUT OF SCOPE)

- `mcp/` npm 客户端为新 MCP 工具名补条目并发版（沿用 122 D-27）
- `@friday-ai-codes/skills` npm 正式 bump 发布时机（相位验收不阻塞）
- Galaxy / 前端执行流与社区着色可视化
- rename apply / 工作树自动改写；动态引用（反射/模板）增强命中
- Process 跨 async 边界的二段追踪；跨仓 Process（v1 本仓 Endpoint 入口）
- Semgrep「## 安全扫描」段 / LSP 基准（Phase 127）
- Runner/CI 硬门禁（HIGH/CRITICAL 阻断 commit）— 124 已明确 v2+
- `detect_impact` 式 MCP 编排 prompt（REQUIREMENTS Future）
</user_constraints>

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| EXEC-01 | Endpoint 入口正向 BFS 执行流，硬闸 depth/branching/minSteps/conf≥0.5 + 去重，存 Process 模型 | `ProcessTrace` 模型 + `process_trace.py` 正向 BFS（复用 impact 边打分/`successors`）；durable 全删全建 |
| EXEC-02 | intra/cross_community 分类 + MCP 可查询 | 对账 `SymbolCommunity.members`；`run_list_processes`/`run_get_process` + MCP/对话薄壳 |
| EXEC-03 | detect_changes/impact 回填 `affected_processes`，进 MR 影响面段 | 单一 helper 填空数组；`impact_report._render_affected` / Recommendations 占位句替换 |
| RENAME-01 | 只读双源 rename_preview（graph + text_search），按文件分组，声明动态引用限制，不改写 | `rename_preview.py` + `grep_mirror`+exclusion；`applied=false` |
| SKILL-01 | friday-impact / friday-refactoring 进 skills 子模块 + sync/hash 容器同源 | 扩展 `SKILL_NAMES`；照抄 friday-routing README/installer 接入 |
</phase_requirements>

## Summary

Phase 126 把 121–125 已落地的内存图、社区、detect_changes、impact_report 收成三条可验收链路：**（1）Endpoint→正向 BFS→`ProcessTrace` 落库并可查询；（2）impact/detect_changes 信封与 MR「影响面」消费 `affected_processes`；（3）只读 `rename_preview` + 两个编码期 skill 同源分发**。代码标识符必须是 `ProcessTrace`，对外口语「Process / 执行流」；绝不与 `ProcessEngine` 混名。 [VERIFIED: codebase `codegraph/models.py` SymbolCommunity；CONTEXT D-01]

现有集成点已预留到位：`run_impact` / `run_detect_changes` 均返回 `affected_processes: []`；`impact_report` Recommendations 有 Phase 126 占位句；社区重建走 `QUEUE_GRAPH` + `idempotency_key=community:{repo}:{branch}`；skills 管线 `sync_skills.py` + sha256 守卫已在 friday-code/friday-memory 上验证。本相位应**照抄接线范式、钉死 BFS/只读硬闸测试、链式 enqueue Process 重建**，而不是另造方言。 [VERIFIED: `code_graph_tools.py` L903/L1427；`impact_report.py` L285–286；`community_enqueue.py`；`task/scripts/sync_skills.py`]

**Primary recommendation:** 独立模型 `ProcessTrace` + 内核 `process_trace.py` / `rename_preview.py` + 共享编排 `run_*` + MCP/对话薄壳；社区任务完成后 enqueue `durable_process_rebuild`（独立 `queueing_lock=process:{repo}:{branch}`）；单一 `assemble_affected_processes` helper 回填两条编排；skills 只改子模块源并 sync 进 `task/assets/skills/`。

## Architectural Responsibility Map

| Capability | Primary Tier | Secondary Tier | Rationale |
|------------|-------------|----------------|-----------|
| ProcessTrace 持久化 / migration | Database / Storage | API / Backend | 独立加表；软引用 JSON，免索引删建牵连 |
| Endpoint→handler 映射 + 正向 BFS | API / Backend | Database / Storage | 纯算法内核 + durable 重建；读 Endpoint/SymbolCommunity |
| 社区分类 intra/cross | API / Backend | Database / Storage | 消费已落库 SymbolCommunity，不重跑 Louvain |
| MCP/对话查询 Process | API / Backend | Browser / Client | 薄壳无算法；agent/IDE 只消费信封 |
| affected_processes 回填 | API / Backend | — | 编排层单一 helper，禁止第三套方言 |
| MR「受影响执行流」段 | API / Backend | — | `build_impact_report_section` 单一 formatter，双链路共用 |
| rename_preview 双源清单 | API / Backend | Database / Storage | 图边 + mirror grep；绝不写工作树 |
| 容器白名单 rename_preview | Task executor | API / Backend | `knowledge_tools` 白名单调 server MCP |
| friday-impact / friday-refactoring | CDN / Static（skills 包） | Task executor | 子模块事实源 + assets 镜像 + 容器注入 |
| 冻结面守卫 | API / Backend | — | AST/git 测试钉死不碰 repo_router_v2 / mcp submodule |

## Project Constraints (from .cursor/rules/)

| Directive | Implication for Phase 126 |
|-----------|---------------------------|
| Observability: `structlog` + snake_case events + `category`/`component` + `duration_ms` | Process rebuild / MCP tools / rename_preview / enqueue 均需 started/completed/failed；BFS 循环内禁止 INFO |
| Bind initiator: durable 必须 `initiated_by_user_id`（无则 `system`） | `durable_process_rebuild` + enqueue helper 透传 |
| Never break business with observability | 观测 `except: pass`；MR/impact fail-soft 不变 |
| Redact credentials / upstream text | rename context / grep 命中文本走既有脱敏；勿记 PAT |
| RetrievalTrace on MCP + chat tools | list/get process、rename_preview 与 impact 同构记 trace |
| Explicit path commits only（CONTEXT D-16） | 计划与提交只 stage 相位相关路径，禁止 `git add -A` |

## Current State

| Area | State | Evidence |
|------|-------|----------|
| Endpoint 入口 | ✅ 落库可用 | `codegraph.models.Endpoint`：method/path/handler/file/line + `branch_name` |
| 内存图 + 正向边 | ✅ CallEdge 方向 caller→callee；impact 用 `predecessors` 反向 | `impact.py` BFS；Process 须用 `successors` |
| Endpoint→符号解析 | ✅ loader 用 `(file_path, handler_name)` → `by_file_and_name` | `loader.py` L720–825 |
| SymbolCommunity | ✅ Phase 125 加表 + QUEUE_GRAPH 重建 | `models.py` L341+；`community_enqueue.py` |
| affected_processes 占位 | ✅ 空数组已在信封 | `run_impact` / `run_detect_changes` |
| impact_report 占位句 | ✅ Recommendations 明确留给 126 | `impact_report.py` L285–286 |
| grep_mirror + exclusion | ✅ MCP Grep 已拦截 | `repo_mirror.grep_mirror`；`views._filter_grep_result` |
| Skills 同源 | ✅ 2/7 进容器；installer 动态扫目录 | `SKILL_NAMES=("friday-code","friday-memory")`；`bundledSkills()` |
| ProcessTrace / rename_preview | ❌ 未实现 | 无对应 py 模块 |
| mcp/ / repo_router_v2 | ⛔ 冻结 | D-16；照抄 `test_frozen_surface_125.py` |

**Graphify:** disabled in config — semantic graph queries unavailable this session; relationships taken from codebase + `.planning/research/*` + CONTEXT. [VERIFIED: gsd-tools graphify status]

## Discretionary Defaults (auto-accepted)

| Topic | Decision | Rationale |
|-------|----------|-----------|
| `process_key` | `{METHOD.upper()}:{normalize(url_path)}`；normalize 去尾 `/`（root `/` 保留） | 稳定、可复现、跨重建幂等 |
| `name` | `{METHOD.upper()} {url_path}`；path 空则回退 `handler_name` | 展示友好且与 key 同源 |
| maxProcesses | `max(CODE_GRAPH_PROCESS_MIN, min(CODE_GRAPH_PROCESS_MAX_CAP, symbol_count // 10))`；defaults MIN=20 CAP=300 | 锁定公式；settings 可调上下界 |
| Process durable | **独立** task `durable_process_rebuild`；在 `run_community_rebuild` **成功返回前** best-effort `enqueue_process_rebuild`（社区空/降级仍 enqueue） | 独立 `queueing_lock=process:{repo}:{branch}`；社区失败 raise 则不链式（避免无图空转），另保留手动/重试入口 |
| steps 边 reason | v1 **不存** per-step reason（体积）；过程级 `flags: {cycle, async_boundary, truncated}` | D-04 摘要纪律 |
| 查询工具 | **两个**：`list_processes` + `get_process` | 与 list/get 资源惯例一致；薄壳清晰 |
| rename 参数 | `symbol_id` 优先 + `new_name` 必填；可选 `symbol`/`file_path`/`symbol_type` 消歧（122 D-19） | 对齐 impact 输入 |
| 合并字段 | `confidence: "graph"|"text_search"` + `sources: string[]` | 展示取 graph；审计保留双源 |
| context 窗 | 默认 `context_lines=2`；上限 5 | 短片段；不灌全文 |
| async 词表 | 见 Code Examples | 本仓真实派发面；可 settings 追加 |
| skill 形态 | 中等长度 zh-CN checklist + 可选 `references/tool-order.md`；**不** npm bump | D-15 验收不阻塞发版 |
| 测试组织 | 分文件：model / BFS / community_class / affected / rename / report / skills / frozen | 便于 wave 并行 |

## Standard Stack

### Core

| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| Django ORM | ≥5.1（repo pin） | `ProcessTrace` 加表 | 既有 codegraph 模型栈 [VERIFIED: server/pyproject.toml] |
| networkx MultiDiGraph | 已在依赖树 | 正向 BFS `successors` | Phase 121–122 图契约；勿引入 rustworkx [VERIFIED: research SUMMARY + impact.py] |
| structlog | ≥25.5 | 结构化日志 | 项目强制 [VERIFIED: observability-logging.mdc] |
| DurableTaskService / QUEUE_GRAPH | 既有 | Process 重建异步 | 与 community 同队列 [VERIFIED: durable/tasks.py] |
| grep_mirror + exclusion | 既有 | rename 文本半边 | 禁止裸 grep [VERIFIED: repo_mirror.py / mcp Grep] |

### Supporting

| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| pytest / pytest-django / pytest-asyncio | ≥9 / ≥4.8 / ≥1.3 | 单测 | Wave 0+ 验证 [VERIFIED: pyproject.toml] |
| McpToolView + PAT | 既有 | MCP 薄壳 | list/get/rename |
| agents `@tool` | 既有 | 对话薄壳 | 同编排入口 |
| skills submodule + sync_skills | `@friday-ai-codes/skills@0.5.0` | skill 分发 | SKILL-01 [VERIFIED: skills/package.json] |

### Alternatives Considered

| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| `ProcessTrace` 新表 | 挂在 Endpoint / Symbol 字段 | 索引删建丢标注；⛔ CONTEXT 否决 |
| 独立 Process 队列 | 与 community 同 QUEUE_GRAPH | 同队列即可；独立 lock 防抖即可 |
| rename apply API | 只读 preview | 服务端写仓危险；Deferred |
| 单工具 `processes(detail=)` | list+get | detail flag 易膨胀；两工具更清晰 |

**Installation:** 本相位 **不新增** PyPI/npm 运行时依赖。skills 源在 git submodule 内编辑；容器侧跑 `python task/scripts/sync_skills.py`。

**Version verification:** Python 3.14.x / uv / ripgrep 15.x 本机可用；无新包需 `pip index` / `npm view` 安装门禁。 [VERIFIED: local env probe 2026-08-10]

## Package Legitimacy Audit

> 本相位不安装外部包。

| Package | Registry | Age | Downloads | Source Repo | slopcheck | Disposition |
|---------|----------|-----|-----------|-------------|-----------|-------------|
| — | — | — | — | — | n/a | N/A — no new installs |

**Packages removed due to slopcheck [SLOP] verdict:** none
**Packages flagged as suspicious [SUS]:** none

*slopcheck 未跑（无可安装候选）。*

## Architecture Patterns

### System Architecture Diagram

```text
[Index / Edge build complete]
        │
        ▼
 enqueue_community_rebuild ──QUEUE_GRAPH──► durable_community_rebuild
        │                                         │
        │                                         ▼
        │                               rebuild_communities (+ summaries)
        │                                         │
        │                                         ▼
        │                         enqueue_process_rebuild (best-effort)
        │                                         │
        │                                         ▼
        │                         durable_process_rebuild
        │                         get_graph_service → process_trace.rebuild
        │                         Endpoint rows → resolve handler → forward BFS
        │                         classify vs SymbolCommunity → bulk replace ProcessTrace
        │
[Agent / MCP / Chat]
        │
        ├─ list_processes / get_process ──► run_list/get_process ──► ProcessTrace ORM
        ├─ impact_analysis / detect_changes ──► assemble_affected_processes ──► envelope.affected_processes
        │         └─► build_impact_report_section ──► MR ## 影响面 / Affected 执行流
        └─ rename_preview ──► graph refs + grep_mirror(+exclusion) ──► files[] edits, applied=false
```

### Recommended Project Structure

```
server/codegraph/
  models.py                    # + ProcessTrace
  migrations/0012_processtrace.py
server/services/code_graph/
  process_trace.py             # BFS + classify + rebuild/persist (pure-ish)
  rename_preview.py            # dual-source merge (pure-ish)
  impact_report.py             # Affected 执行流段 + 去占位句
server/services/
  process_enqueue.py           # QUEUE_GRAPH defer helper（照 community_enqueue）
  code_graph_tools.py          # run_list/get_process, run_rename_preview, assemble_affected_processes
server/durable/
  tasks.py / tasks_impl.py     # durable_process_rebuild + community 链式 enqueue
server/mcp_tools/
  views.py / urls.py / serializers.py  # 薄壳 only
server/agents/tools/
  graph_tools.py + schemas/    # 对话薄壳
task/core/knowledge_tools.py   # rename_preview 白名单
task/scripts/sync_skills.py    # SKILL_NAMES += impact/refactoring
skills/skills/friday-impact/
skills/skills/friday-refactoring/
task/assets/skills/…           # sync 产物，勿手改
```

### Pattern 1: Soft-ref 独立模型（照抄 SymbolCommunity）

**What:** 纯加表；`steps[].symbol_id` / `entry_endpoint` 快照 JSON；`unique_together (repository, branch_name, process_key)`；`built_at_sha` 水位。
**When to use:** 任何依赖索引删建实体的派生标注。
**Example:** 见 Current State / research ARCHITECTURE Pattern 4。 [CITED: .planning/research/ARCHITECTURE.md]

### Pattern 2: 内核纯函数 + 共享编排 + 双面薄壳（122 D-21）

**What:** `process_trace.py` / `rename_preview.py` 无 MCP/ORM 分叉逻辑；`code_graph_tools.run_*` 唯一编排；MCP View 与 `@tool` 只做校验/ACL/trace。
**When to use:** 所有新图工具。

### Pattern 3: Durable 全删全建 + queueing_lock

**What:** `DurableTaskService.defer(..., queue=QUEUE_GRAPH, idempotency_key=f"process:{repo}:{branch}")`；`idempotency_key` ≡ `queueing_lock`。 [VERIFIED: durable/service.py]
**When to use:** 社区完成后链式 Process；不在索引钩子内联 BFS。

### Pattern 4: 正向 BFS（与 impact 镜像，方向相反）

**What:** 复用 `_edge_score` / `EdgeConfidence` / MultiDiGraph 多边遍历纪律；用 `graph.successors` + 每层 fanout≤`maxBranching`；depth≤10；边分≥0.5；visited 去重；环标 `cycle`；async 末端标 `boundary` 且不跨越。
**When to use:** Process 重建内核。
**Anti-pattern:** `list(nx.bfs_layers(...))[:d]` 物化全分量（model.py 纪律 ②）。 [VERIFIED: code_graph/model.py L26–31]

### Pattern 5: Skills 单一事实源

**What:** 只改 `skills/skills/<name>/`；跑 sync；hash 测试守卫；installer `bundledSkills()` 动态枚举目录（README/引导文案需手改 7→9）。 [VERIFIED: installer.mjs L36–49]

### Anti-Patterns to Avoid

- **命名 `Process` ORM：** 与 `ProcessEngine` 撞名 — 用 `ProcessTrace`。
- **对 Endpoint FK：** 索引删建牵连 — 用 JSON 快照。
- **存全展开节点集：** 单行 MB JSON — 只存主干 steps。
- **裸 grep / 绕过 exclusion：** 安全回归 — 必须 `grep_mirror` + matcher。
- **壳内分叉算法 / 第三套 affected 方言。**
- **改 `repo_router_v2.py` 或 `mcp/` submodule。**
- **手改 `task/assets/skills/` 副本。**
- **`git add -A` 卷入并发 WIP。**

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| 边置信度数值 | 新常量表 | `confidence_score` / impact `_edge_score` | cross_repo 必须原值 |
| 符号消歧 | 静默取第一个 | `resolve_symbol_in_graph` | 19.3% 重名主路径 |
| 文本检索 | 自写 walk+re | `grep_mirror` | 引擎/路径校验/与 MCP 一致 |
| Exclusion | 自写 ignore | `build_matcher_for_repo` | fail-closed 契约 |
| 图加载 | import loader/cache | `get_graph_service()` | 分层 + 单测守卫 |
| Durable 去重 | 自管锁 | `idempotency_key`/`queueing_lock` | 已与 community 同模式 |
| Skill 安装器 | 新 CLI | 既有 `npx @friday-ai-codes/skills` | D-15 |
| MR 报告格式 | 第二 formatter | `build_impact_report_section` | 双链路共用 |

**Key insight:** 本相位价值在接线与纪律测试，不在新基础设施。

## Runtime State Inventory

> 本相位以**新模型/新工具**为主，但存在跨域命名碰撞与 skills 子模块指针，故完整填写。

| Category | Items Found | Action Required |
|----------|-------------|------------------|
| Stored data | 尚无 `ProcessTrace` 行；已有 `SymbolCommunity` / `Endpoint` / 图边 | 新 migration 加表；全删全建写入；**无**既有 Process 数据迁移 |
| Live service config | 无外部 UI 配置依赖 Process 名 | none |
| OS-registered state | None — verified by scope（无 systemd/pm2 名依赖） | none |
| Secrets/env vars | 可选新增 `CODE_GRAPH_PROCESS_*` settings（非密钥） | code edit only；文档 `.env.example` 可选 |
| Build artifacts | `task/assets/skills/` 镜像；skills submodule git pointer；`@friday-ai-codes/skills` npm（发版 Deferred） | sync 脚本更新 assets；主仓提交 submodule pointer；**不**要求本相位 npm publish |
| Naming collision | `ProcessEngine` / `ProcessDefinition` / delivery `process_type` 已占用 `Process` | **代码标识只用 `ProcessTrace`**；文档口语可称执行流 |

## Common Pitfalls

### Pitfall 1: 遍历爆炸 / 环 / async 假完整
**What goes wrong:** 扇出工具函数拖垮；环死循环；async 断链被当成链路结束误导用户。
**Why:** 正向调用图天然高扇出；静态图看不到队列消费者。
**How to avoid:** 硬闸 depth/branching/minSteps/conf；环显式标注；async 词表末端 `boundary: async_dispatch` 且不跨越。
**Warning signs:** 单条 steps 巨大；重建任务超时；用户反馈「明明发了任务但流里没有」。

### Pitfall 2: Endpoint handler 解析失败被静默跳过
**What goes wrong:** Endpoint 很多但 Process 很少。
**Why:** handler 名与 Symbol.name 不一致 / 路径归一失败（同 loader 跨仓坑）。
**How to avoid:** 复用 loader `_resolve_by_file_and_name` 语义；计数 `unresolved_endpoints` 进 degradation；勿造虚拟节点。

### Pitfall 3: 社区未就绪却编造 community_class
**What goes wrong:** 假 intra/cross。
**How to avoid:** 无法对账 → 仍落库 + `community_class_unknown` / degradation；查询可滤。

### Pitfall 4: affected_processes N+1 扫表
**What goes wrong:** batch detect_changes 每种子查一次 Process。
**How to avoid:** 一次加载仓分支全部 ProcessTrace，内存倒排 `symbol_id → processes` / `file:name → processes`。

### Pitfall 5: rename 空清单伪装「零引用」
**What goes wrong:** ACL/未索引/消歧失败返回空 edits。
**How to avoid:** `ok=False` + error_code；仅双源真实零命中才 `ok=True` 且 `applied=false` + 限制声明。

### Pitfall 6: skills 双源漂移
**What goes wrong:** 改 assets 或忘 sync。
**How to avoid:** 只改 submodule 源 → sync → hash 测试红即停。

### Pitfall 7: 冻结面误触
**What goes wrong:** 改 router / mcp submodule。
**How to avoid:** 扩展 `test_frozen_surface_125` → 126 文件列表。

## Code Examples

### Forward BFS skeleton (Process)

```python
# Pattern adapted from server/services/code_graph/impact.py reverse BFS
# Direction: successors (caller → callee). Caps: D-02.
from collections import deque

MAX_DEPTH = 10
MAX_BRANCHING = 4
MIN_STEPS = 3
MIN_CONF = 0.5

ASYNC_NAME_MARKERS = (
    "sync_to_async",
    "defer",
    "delay",
    "apply_async",
    "group_send",
    "create_task",
    "background_runner",
)

def is_async_boundary(node_attrs: dict, edge_attrs: dict) -> bool:
    name = (node_attrs.get("name") or "").lower()
    return any(m in name for m in ASYNC_NAME_MARKERS)
```

### Assemble affected_processes (single helper)

```python
# Insert into run_impact / run_detect_changes — never a third dialect
def assemble_affected_processes(
    *,
    hit_symbol_ids: set[str],
    hit_file_name_keys: set[str],
    processes: list[ProcessTrace],
) -> list[dict]:
    out = []
    for p in processes:
        steps = p.steps or []
        affected = []
        for i, step in enumerate(steps):
            sid = str(step.get("symbol_id") or "")
            key = f"{step.get('file_path')}:{step.get('name')}"
            if sid in hit_symbol_ids or key in hit_file_name_keys:
                affected.append(i)
        if not affected:
            continue
        out.append({
            "name": p.name,
            "process_key": p.process_key,
            "affected_steps": affected,
            "total_steps": p.step_count,
            "community_class": p.community_class,
            "step": affected[0],  # first hit for report brevity
        })
    return out
```

### Durable enqueue (mirror community)

```python
# server/services/process_enqueue.py — mirror community_enqueue.py
job_id = await DurableTaskService.defer(
    "durable_process_rebuild",
    {"repository_id": str(repository_id), "branch_name": branch},
    queue=QUEUE_GRAPH,
    idempotency_key=f"process:{repository_id}:{branch}",
    initiated_by_user_id=initiated_by_user_id,
)
```

### rename_preview envelope shape

```json
{
  "ok": true,
  "tool": "rename_preview",
  "applied": false,
  "coverage_limitations": "动态引用/字符串模板/反射/getattr/配置拼路径等 v1 不保证命中",
  "symbol": {"symbol_id": "...", "name": "old", "new_name": "new"},
  "files": [
    {
      "file_path": "a.py",
      "edits": [
        {
          "line": 12,
          "confidence": "graph",
          "sources": ["graph", "text_search"],
          "context": "...",
          "old_text": "foo",
          "new_text": "bar"
        }
      ]
    }
  ],
  "summary": {
    "total_edits": 1,
    "files_affected": 1,
    "graph_edits": 1,
    "text_search_edits": 0
  }
}
```

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| GitNexus 启发式入口打分 | Friday `Endpoint` 确定性入口 | v0.22.0 research | 执行流质量上限更高 |
| affected_processes 空数组 + 占位句 | 真实 ProcessTrace 对账 | Phase 126 | MR 叙事增值 |
| rename apply（本地 CLI） | 只读 preview + agent 自行编辑 | 里程碑裁剪 | 避免服务端写仓 |
| 7 skills | +friday-impact / friday-refactoring → 9 | Phase 126 | 工作流固化 |

**Deprecated/outdated:**
- 口语「Process 模型」作 ORM 类名：实现必须用 `ProcessTrace`。
- Recommendations「待 Phase 126」占位句：本相位删除/替换。

## Assumptions Log

| # | Claim | Section | Risk if Wrong |
|---|-------|---------|---------------|
| A1 | async 断链以符号名子串词表为主即可覆盖本仓主要派发 | Discretionary Defaults | 漏标边界 → 假完整链路；可用 settings 扩词表缓解 |
| A2 | 社区任务 raise 时不链式 Process（避免无图空转）可接受 | Discretionary Defaults | 社区持续失败时 Process 陈旧；需运维重跑或后续补偿任务 |
| A3 | graph rename 半边 = 定义点 + 一跳 incoming callers（predecessors）足够 v1 | Technical Approach | 漏 import/别名引用 → 靠 text_search 兜底 |
| A4 | installer 动态扫目录，但引导文案写死「7 个」须手改 | Skills | 用户文档过时但不阻断 hash 验收 |

## Open Questions

> 以下均已按 Claude's Discretion 给出默认；规划可直接采用，无需再问用户。

1. **Process 与 community 失败时序** — 默认：community 成功返回路径 enqueue；raise 不 enqueue。补偿：同 enqueue helper 可被管理命令/重试调用。
2. **list 默认排序** — `cross_community` 优先，其次 `name`/`process_key`。
3. **npm bump** — Deferred；验收不依赖 publish。

## Environment Availability

| Dependency | Required By | Available | Version | Fallback |
|------------|------------|-----------|---------|----------|
| Python / uv | server tests | ✓ | 3.14.x | — |
| pytest stack | validation | ✓ | pyproject pins | — |
| ripgrep | grep_mirror 优选 | ✓ | 15.1.0 | git grep 回退（已有） |
| skills submodule | SKILL-01 | ✓ | skills/skills/* present | — |
| networkx | BFS | ✓ | in server deps | — |
| Qdrant / LLM | — | n/a | — | 本相位不依赖新 LLM 调用 |
| mcp/ npm publish | 新工具名客户端 | ✗（Deferred） | — | SUMMARY 记账漂移；server HTTP 面可测 |

**Missing dependencies with no fallback:** none for phase execution.

**Missing dependencies with fallback:** npm skills/mcp 发版 — 验收走源码+hash+容器测。

## Technical Approach

### Wave 建议（供 planner）

1. **Wave 0 — 模型 + 冻结守卫 + 测试骨架**  
   `ProcessTrace` + migration；`test_frozen_surface_126`；常量/settings。
2. **Wave 1 — Process BFS + durable 重建（EXEC-01/02 内核）**  
   `process_trace.py`；`process_enqueue.py`；`durable_process_rebuild`；community 链式；合成图单测钉死四硬闸/环/async。
3. **Wave 2 — 查询面 + affected_processes + impact_report（EXEC-02/03）**  
   `run_list_processes` / `run_get_process`；MCP+agents；`assemble_affected_processes`；报告段。
4. **Wave 3 — rename_preview（RENAME-01）**  
   内核+编排+双面壳+knowledge 白名单；exclusion/消歧/applied=false 测试。
5. **Wave 4 — skills（SKILL-01）**  
   子模块两 skill；README/installer 文案；`SKILL_NAMES`；sync；hash/注入测。

### File Touch List

**NEW**
- `server/codegraph/migrations/00xx_processtrace.py`
- `server/services/code_graph/process_trace.py`
- `server/services/code_graph/rename_preview.py`
- `server/services/process_enqueue.py`
- `server/tests/codegraph/test_process_trace_model.py`
- `server/tests/services/code_graph/test_process_trace.py`
- `server/tests/services/code_graph/test_process_enqueue.py`
- `server/tests/services/code_graph/test_rename_preview.py`
- `server/tests/services/code_graph/test_affected_processes.py`
- `server/tests/services/code_graph/test_frozen_surface_126.py`
- `skills/skills/friday-impact/SKILL.md`（+ optional references）
- `skills/skills/friday-refactoring/SKILL.md`（+ optional references）
- `task/assets/skills/friday-impact/**`（via sync）
- `task/assets/skills/friday-refactoring/**`（via sync）

**MODIFY**
- `server/codegraph/models.py`（+ProcessTrace, `__all__`）
- `server/durable/tasks.py` / `tasks_impl.py`（process task + community enqueue chain）
- `server/services/code_graph_tools.py`（run_* + assemble + 填空数组）
- `server/services/code_graph/impact_report.py`（Affected 执行流；去占位句）
- `server/mcp_tools/{views,urls,serializers}.py`
- `server/agents/tools/graph_tools.py` + `schemas/graph_tools.py` + `__init__.py`
- `server/friday/settings.py`（PROCESS_* knobs）
- `server/tests/services/code_graph/test_impact_report.py`
- `server/tests/mcp_tools/test_schema_snapshot.py`（漂移记账）
- `task/core/knowledge_tools.py`（白名单 + 计数断言测试）
- `task/scripts/sync_skills.py` / `task/tests/test_skills_injection.py`
- `skills/README.md` / `skills/lib/installer.mjs` / `skills/.claude-plugin/plugin.json` / `skills/skills/friday/SKILL.md`（路由表 7→9）
- skills submodule pointer（主仓）

**⛔ DO NOT TOUCH**
- `server/codegraph/services/repo_router_v2.py`
- `mcp/` git submodule
- `services/process_runtime` 引擎域（除无关误改）
- 并发无关 WIP 文件

## Validation Architecture

### Test Framework

| Property | Value |
|----------|-------|
| Framework | pytest ≥9 + pytest-django ≥4.8 + pytest-asyncio（server）；vitest 不涉及本相位前端 |
| Config file | `server/pyproject.toml` `[tool.pytest.ini_options]` |
| Quick run command | `cd server && uv run pytest tests/services/code_graph/test_process_trace.py tests/services/code_graph/test_rename_preview.py tests/services/code_graph/test_affected_processes.py -q` |
| Full suite command | `cd server && uv run pytest tests/services/code_graph/ tests/codegraph/test_process_trace_model.py tests/mcp_tools/test_schema_snapshot.py -q` + `cd task &&` 对应 skills/knowledge 测试 |

### Phase Requirements → Test Map

| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| EXEC-01 | BFS 四硬闸 + 环/async 标注 + ProcessTrace 落库 | unit | `uv run pytest tests/services/code_graph/test_process_trace.py -q` | ❌ Wave 0 |
| EXEC-01 | 模型字段 / unique_together / 无 Endpoint FK | unit | `uv run pytest tests/codegraph/test_process_trace_model.py -q` | ❌ Wave 0 |
| EXEC-02 | intra/cross/unknown 分类 | unit | 同上 process_trace 社区用例 | ❌ Wave 0 |
| EXEC-02 | MCP/对话 list+get 走共享编排 | unit/api | schema snapshot + thin shell tests | ❌ Wave 0 |
| EXEC-03 | assemble 回填 impact/detect_changes | unit | `uv run pytest tests/services/code_graph/test_affected_processes.py -q` | ❌ Wave 0 |
| EXEC-03 | impact_report 执行流段 / 无占位句 | unit | `uv run pytest tests/services/code_graph/test_impact_report.py -q` | ✅ 扩展 |
| RENAME-01 | 双源合并、confidence、applied=false、exclusion | unit | `uv run pytest tests/services/code_graph/test_rename_preview.py -q` | ❌ Wave 0 |
| RENAME-01 | knowledge 白名单含 rename_preview | unit | task knowledge_tools 白名单测 | ✅ 扩展 |
| SKILL-01 | SKILL_NAMES + hash 一致 | unit | `cd task &&` `pytest tests/test_skills_injection.py -q` | ✅ 扩展 |
| D-16 | 不 import router / 不碰 mcp submodule | unit | `test_frozen_surface_126.py` | ❌ Wave 0 |

### Sampling Rate

- **Per task commit:** 上表对应 quick 子集
- **Per wave merge:** code_graph + model + schema snapshot + task skills/knowledge
- **Phase gate:** 上列全绿 + `applied is False` 断言存在 + Recommendations 无「待 Phase 126」字样

### Wave 0 Gaps

- [ ] `tests/codegraph/test_process_trace_model.py` — EXEC-01 schema
- [ ] `tests/services/code_graph/test_process_trace.py` — BFS 硬闸
- [ ] `tests/services/code_graph/test_process_enqueue.py` — QUEUE_GRAPH lock
- [ ] `tests/services/code_graph/test_affected_processes.py` — EXEC-03
- [ ] `tests/services/code_graph/test_rename_preview.py` — RENAME-01
- [ ] `tests/services/code_graph/test_frozen_surface_126.py` — D-16
- [ ] 扩展 `test_impact_report.py` / `test_skills_injection.py` / knowledge 白名单计数 / schema snapshot
- [ ] Framework install: none — 已有 pytest

## Security Domain

### Applicable ASVS Categories

| ASVS Category | Applies | Standard Control |
|---------------|---------|-----------------|
| V2 Authentication | yes（MCP/对话工具） | PAT / session via `McpToolView` fail-closed |
| V3 Session Management | no new | 既有 |
| V4 Access Control | yes | `_get_indexed_repo` + repo ACL（对齐 122/123）；exclusion matcher |
| V5 Input Validation | yes | DRF serializers / tool schemas；pathspec 校验 |
| V6 Cryptography | no new | — |

### Known Threat Patterns for code-graph tools

| Pattern | STRIDE | Standard Mitigation |
|---------|--------|---------------------|
| Exclusion bypass via bare grep | Information Disclosure | 强制 `grep_mirror` + `_filter_grep_result` 同款 |
| Rename 伪造成功空清单 | Spoofing | 消歧/未索引 → `ok=False`，禁止静默空 |
| 日志泄漏源码/密钥 | Information Disclosure | context 短窗；`redact_secrets_in_text`；采样级日志 |
| 遍历 DoS | Denial of Service | depth/branching/maxProcesses/JSON 截断 |
| 冻结面误改扩大攻击面 | Tampering | frozen surface 测试 |
| 服务端写仓 | Tampering | `applied=false`；无 apply API |

## Sources

### Primary (HIGH confidence)

- CONTEXT D-01…D-16 — `.planning/phases/126-process-rename-skills/126-CONTEXT.md`
- Codebase: `codegraph/models.py`, `services/code_graph/{impact,trace,community,loader,impact_report,symbol_resolve}.py`, `code_graph_tools.py`, `community_enqueue.py`, `durable/tasks.py`, `mcp_tools/views.py`, `agents/tools/graph_tools.py`, `task/{scripts/sync_skills.py,core/knowledge_tools.py,tests/test_skills_injection.py}`, `skills/{README.md,lib/installer.mjs}`
- Milestone research: `.planning/research/{SUMMARY,ARCHITECTURE,FEATURES,PITFALLS}.md` — ProcessTrace / BFS 参数 / rename 双源 / skills
- Observability: `.cursor/rules/observability-logging.mdc`

### Secondary (MEDIUM confidence)

- GitNexus 工具契约转述于 FEATURES.md（2026-08-09 调研抓取）— BFS 数值与 rename confidence 二分 [CITED: .planning/research/FEATURES.md]
- Async 词表完备性 — 基于本仓常见派发模式枚举 [ASSUMED 扩词表可调]

### Tertiary (LOW confidence)

- 大仓 maxProcesses 经验公式校准 — RESEARCH Flags 已提示需实测；本相位用公式默认即可 [ASSUMED]

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH — 零新依赖，全复用已核实路径
- Architecture: HIGH — CONTEXT + research ARCHITECTURE + 落地社区/impact 先例一致
- Pitfalls: HIGH — PITFALLS.md Pitfall 4 + 本仓 exclusion/消歧已知威胁

**Research date:** 2026-08-10  
**Valid until:** 2026-09-09（30 days；skills npm 生态若变发版流程可提前刷新）
