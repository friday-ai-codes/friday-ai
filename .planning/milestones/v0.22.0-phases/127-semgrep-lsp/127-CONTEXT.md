# Phase 127: Semgrep 门禁 + LSP 基准 - Context

**Gathered:** 2026-08-10
**Status:** Ready for planning
**Mode:** Smart discuss（autonomous，用户授权全量采纳推荐答案；跳过 Sub-step 4 交互）

<domain>
## Phase Boundary

本相位是 v0.22.0 **最后一相**，交付两条与内存图**零耦合**的独立轨道：

1. **Semgrep taint 门禁（TAINT-01/02/03）**：MR 流程触发 diff-aware 扫描（`--baseline-commit` = merge-base），只报本 MR 新增 finding；Semgrep 以独立 CLI/venv 集成（**不进** server Python 依赖树）；finding 带 severity 进 MR 描述/评论；默认 **advisory 不阻断**；`nosemgrep` 生效；超时 **fail-open** 且显式标注；文案如实声明 CE 仅函数内 taint；Pro 经加密存储的 `SEMGREP_APP_TOKEN` opt-in。
2. **LSP 开启门槛 + 基准（LSP-01）**：server 镜像补齐 Node/Go 运行时与 volar/gopls；可用性探测 + fail-soft 降级 + 孤儿进程清扫；产出开启前后抽取质量/耗时基准报告；**默认值翻转由基准数据决定（本里程碑不盲翻）**。

**跨相位回访（D-26 / IMPACT-03）：** LSP 落地并重建索引后，必须用真实 `CrossRepoApiCall` 样本复验 IMPACT-03 四分支，并测量 `(file_path, name)` 二次解析命中率；若样本仍为零则诚实记账并决定是否另开 follow-up。

**明确不在本相位：**
- 内存图 / impact / detect_changes / community / Process 功能本身（121–126 已交付）
- Semgrep 硬阻断白名单提级、主干 full-scan 台账化与跨分支 triage（research defer → 门禁用量验证后）
- 全局无条件翻 `VOLAR_BACKEND_ENABLED` / `GOPLS_BACKEND_ENABLED` 默认（须基准数据）
- ⛔ 不改 `server/codegraph/services/repo_router_v2.py`（本相位 LSP-01 不需要）
- ⛔ 不改 `mcp/` git submodule（沿用 122 D-27）
- Galaxy / 前端可视化；并发 WIP 文件勿碰

</domain>

<decisions>
## Implementation Decisions

### Area 1: Semgrep CLI/venv 打包 + subprocess 契约 + 超时/fail-open

- **D-01 — Semgrep 独立于 server Python 依赖树（TAINT-01 硬约束）**：在 `server/Dockerfile`（runtime 阶段）安装 Semgrep **独立** 形态——推荐 `uv tool install` / 独立 venv（如 `/opt/semgrep`）或官方二进制，**禁止**写入 `server/pyproject.toml` / `uv.lock`。版本钉 **≥ 1.172.0**（research：更低版本有 baseline 扫描误报 bug）。server 代码只持绝对路径配置（settings/env，如 `SEMGREP_BIN`），经 `subprocess` 调用；永不 `import semgrep`。
- **D-02 — 执行位置 = server 容器内 durable 异步任务 + `repo_mirror` worktree**：新增 `services/code_graph/semgrep_scan.py`（或同级模块）封装 CLI；扫描物化 worktree（复用 `repo_mirror` `_ensure_worktree` / 等价 API）。任务挂 durable（优先新 `QUEUE_SCAN`，或先落 `QUEUE_MAINTENANCE` 若规划认为拆队列成本偏高——Claude's Discretion），`ConcurrencyWindow` **限 1–2 并发**。⛔ 不走 runner/task 独立容器分发（research 已否决：组件面不成比例）。
- **D-03 — diff-aware 契约：`--baseline-commit` = merge-base，只报增量**：对 MR source/target 算 merge-base，传入 Semgrep baseline；必要时 `--include` 收窄到 diff 文件集。⛔ 禁止以 target HEAD 当 baseline（别人先合入的会算到本 MR）。⛔ 禁止默认同步全仓 full scan。
- **D-04 — 超时 fail-open，永不阻断建 MR（死亡螺旋四件套之一）**：显式 `SEMGREP_TIMEOUT`（单规则）+ 任务墙钟预算（settings/env）；超时 / CLI 崩溃 / mirror 失败 → **fail-open**：MR 照常创建/更新，安全扫描段写显式 stub（对齐 124 D-09/D-11），观测记 `error_code=timeout|unavailable|…`。⛔ 扫描不得挂在建 MR 的同步关键路径上阻塞创建（可 fire-and-forget defer，结果异步回填描述/评论；若首版只能「创建前尽最大努力」，硬墙钟到点必须放弃并标 stub）。
- **D-05 — 落库 `SecurityFinding`（软引用、脱敏）**：新模型（`codegraph` app 或研究建议的扫描落点），字段至少覆盖 repository/branch/mr 关联键、rule_id、severity、file_path、line、message、fingerprint、scan_sha、status（open 起步即可）。snippet/message 入库前过 `redact_secrets_in_text`。软引用不 FK Symbol（增量索引删建会牵连）。完整 triage 状态机 / 跨分支台账 **本相位不做**（research defer）。

### Area 2: MR advisory 挂载 + nosemgrep + 诚实文案 + Pro token opt-in

- **D-06 — MR 挂点照抄 Phase 124 `impact_report` 范式**：新增共享 helper（建议 `security_scan_report.py` 或与 `semgrep_scan` 同模块的 `build_security_scan_section` / `append_security_scan`），顶层标记头统一 **`## 安全扫描`**；幂等 append（已含标记头不重复）；**workflow**（`AICodingNode` / `_create_mr_for_repo` 等建 MR 缝）与 **MCP**（`merge_request_service`）双链路同一入口。失败 stub 文案稳定短码，禁止堆栈/绝对路径/凭证进 MR。可与 `## 影响面` 并存，互不覆盖。
- **D-07 — 默认全程 advisory（TAINT-02）**：finding 带 severity 分级展示（ERROR/WARNING/INFO 或 Semgrep 等价映射），但本里程碑 **不** 阻断 merge、**不** 让扫描失败导致建 MR 失败、**不** 引入 blocking 规则白名单硬门禁。提级留作门禁跑量后的运营相位（对齐 research Pitfall 6 + Phase 114「超界待人审」哲学）。
- **D-08 — 诚实 CE 边界文案 + `nosemgrep` 通道（TAINT-03）**：`## 安全扫描` 段固定 disclaimer：当前为 Semgrep **CE**，taint **仅函数内**，不承诺跨函数/跨文件追踪；若 Pro token 已配置则另行列出「Pro 能力已启用」但不得夸大未验证能力。`nosemgrep` 走 Semgrep 原生抑制语义，文档/段内一句说明误报可标注；本相位不自建平行 suppress 表。
- **D-09 — Pro opt-in = 加密存储的 `SEMGREP_APP_TOKEN`**：用既有 **`SystemSetting` + `SettingKeys.SEMGREP_APP_TOKEN` + `is_encrypted=True`**（Fernet）承载；空/未配置 = CE。扫描子进程仅在有值时注入 `SEMGREP_APP_TOKEN` 环境变量；**永不**打进日志、MR、ledger 明文。⛔ 不把 token 塞进 `ProviderCredential` 的 LLM `provider_type` 选择器（当前 choices 仅 anthropic/openai/gemini/ollama，形状不合）。运维 env 直注可作为 escape hatch（Claude's Discretion），但仍不得入日志。
- **D-10 — 规则集起步纪律**：用官方 registry 精选 pack（如 p/python、p/django 等与本仓栈相关），不在本相位维护庞大自研规则集；自定义规则若有，必须带 owner 与误报出口说明。具体 pack 列表 Claude's Discretion，但须可配置/可文档化。

### Area 3: LSP 镜像运行时 + 探测/fail-soft + 孤儿清扫

- **D-11 — Dockerfile 补齐 Node + Go + 语言服（LSP-01 前置）**：`server/Dockerfile` runtime 安装 **Node 22 LTS**、`@vue/language-server` 3.x（及 tsdk 发现所需 typescript）、**Go 工具链 + gopls（目标 v0.23.x 量级）**。镜像体积 +400–550MB 须进发布说明。与 D-01 Semgrep 安装同镜像、可同层或相邻层，注意非 root `friday` 用户 PATH 可达。
- **D-12 — 本里程碑不盲翻默认 kill-switch**：保持 `VOLAR_BACKEND_ENABLED` / `GOPLS_BACKEND_ENABLED` **默认 False**（Phase 66 现状）；镜像与探测落地后，运维/基准环境可通过 env=`true` 开启。`EXTRACTOR_BACKENDS` 声明表可按「重开目标」对齐 volar/gopls（与 kill-switch 正交），但 **全局默认开启** 只在 Area 4 基准门禁通过后才能改——本相位计划须把「是否翻默认」写成**数据驱动决策**，禁止顺手改 True。
- **D-13 — 可用性探测 + fail-soft（复用/扩展既有 `node_check`）**：沿用 `codegraph/lsp/node_check.py`（Node + vue-language-server + tsdk）；对称补齐 Go/gopls 探测（`go version` / `gopls version` 或等价）。探测失败 → `LspUnhealthyError` → 既有 TreeSitterBackend 回落（registry 集成测试已锁）；索引详情/日志透出「LSP 未启用：缺 X 运行时」，**不**把整条索引管线打成硬失败。
- **D-14 — 孤儿进程清扫**：LSP 子进程绑定索引任务生命周期（context manager / `finally` kill）；索引异常退出后不得留下无主 `gopls` / `vue-language-server`。启动或任务收尾增加孤儿收割（进程组/命令行匹配 + 计数事件如 `lsp_process_reaped`）。观测 `component` 走 codegraph/lsp 既有风格；best-effort 不反噬索引主路径。

### Area 4: 基准报告方法 + 默认翻转门禁 + IMPACT-03 回访范围

- **D-15 — 基准报告方法（开启前后对比）**：在代表性仓库上（至少 **1× Vue/TS** + **1× Go**；可用既有 study-course / 集成夹具仓）产出 before/after 报告，指标至少包括：
  1. 抽取质量：Symbol / Endpoint / CallEdge（及与跨仓相关的 ApiWrapper/ApiCallSite/CrossRepoApiCall 若可得）计数与关键字段差分；
  2. 已知方言：记录 gopls vs tree-sitter 已知差异（如 gin 路由 endpoint 路径，`test_go_extractor` 已提示）；
  3. 耗时：索引墙钟（冷/热）、LSP 冷启动、相对 tree-sitter 增量；
  4. 稳定性：探测失败回落次数、孤儿收割计数、OOM/超时。
  报告落 `.planning/phases/127-semgrep-lsp/`（或 `server` 管理命令 stdout + 相位 SUMMARY 引用），须可复跑。
- **D-16 — 默认翻转门禁（数据驱动，禁止盲翻）**：仅当基准表明 **(a)** 质量无灾难性回归（或对约定指标有净收益）**且** **(b)** 延迟/内存在运维可接受预算内时，才在本相位 SUMMARY/ROADMAP 记录「建议翻默认」并可改 settings 默认；否则 **保持 False**，只交付「降低开启门槛 + 报告」。⛔ 不得以「镜像已装好」为唯一理由翻默认。
- **D-17 — IMPACT-03 回访（D-26）范围与诚实退出**：LSP 可启用并完成至少一轮能产生跨仓边的索引重建后：
  1. 用**真实** `CrossRepoApiCall` 样本复验 Phase 122 四分支（成功 / 对端无权限折叠 / 对端未索引 fail-soft / 跳数超限）；
  2. 测量 `(file_path, name)` 二次解析真实命中率并写入本相位 SUMMARY。
  若启用 LSP + 重建后样本**仍为 0**：在 ROADMAP/SUMMARY **诚实记账**「仍为零 / 不可测」，并标明是否需要 **follow-up 相位**（产出器缺口 vs 仅缺运行时）——**本相位内完成复验或完成诚实延期记账，二选一必须落地**；⛔ 不得宣称跨仓 impact 已验证。
- **D-18 — 冻结面与并发纪律**：⛔ 不改 `repo_router_v2.py`；⛔ 不改 `mcp/` submodule（snapshot 漂移只记账）；提交本 CONTEXT / 相位文档时 **只 stage 本相位意图内文件**，不动并发 WIP。Semgrep / LSP 与内存图零耦合，禁止为「方便」把扫描挂进 `GraphService` 热路径。

### Claude's Discretion

- durable 队列名（`QUEUE_SCAN` vs 复用 `QUEUE_MAINTENANCE`）、并发窗口精确值、墙钟/单规则超时初值。
- `SecurityFinding` 所属 app、字段微调、是否首版写 MR comment 或仅 description 段。
- Semgrep pack 具体列表、severity 展示映射文案。
- Go/gopls 探测模块文件名；孤儿收割实现（psutil vs 进程组）细节。
- 基准仓选择与报告文件名；默认翻转的具体数值阈值表（若需要）。
- IMPACT-03 复验是管理命令 / pytest marker / 手工 runbook 的形态。

</decisions>

<code_context>
## Existing Code Insights

### Reusable Assets

- **MR 段挂点范式（Phase 124）**：`server/services/code_graph/impact_report.py` — `IMPACT_SECTION_MARKER` / `append_impact_report` / `build_impact_report_section`；fail-soft stub、双链路、观测事件名静态字面量。Semgrep 段应对标复制，不重新发明。
- **建 MR 缝**：`server/workflows/nodes/ai/coding.py`（`_create_mr_for_repo`）、`server/mcp_tools/merge_request_service.py`、`server/workflows/services/mr_service.py`。
- **repo_mirror worktree**：`server/services/repo_mirror.py`（research Pattern 6：`_worktree_root` / `_ensure_worktree`）——Semgrep 需要真实文件树。
- **LSP 探测与池**：`server/codegraph/lsp/node_check.py`、`volar_pool.py`、`volar_backend.py`、`gopls_backend.py`；`LspUnhealthyError` → TreeSitter 回落已有集成测。
- **Kill-switch**：`settings.VOLAR_BACKEND_ENABLED` / `GOPLS_BACKEND_ENABLED` 默认 False；`EXTRACTOR_BACKENDS` 声明表；`codegraph/apps.py` ready() 注册。
- **加密设置**：`SystemSetting` + `SettingKeys` + `is_encrypted` / `encrypt_value`（`common.encryption`）；`ProviderCredential` 仅 LLM provider_type choices。
- **Durable**：`server/durable/queues.py` / `tasks.py` / `tasks_impl.py`；`ConcurrencyWindow` 模式可参考其他重任务。
- **脱敏**：`redact_secrets_in_text` / `redact_for_ledger`（LOGGING-SPEC 强制）。

### Established Patterns

- **死亡螺旋规避（research SUMMARY / PITFALLS）**：diff-aware + advisory + 异步不阻塞 + 超时 fail-open — 四项同相位不可拆。
- **双链路同一 helper**：122 D-21 / 124 D-14 — 逻辑不许在壳里分叉。
- **软引用新模型**：`SymbolCommunity` / `ProcessTrace` 先例 — `SecurityFinding` 同纪律。
- **观测**：`structlog` snake_case 事件；`category` caller/sampling；`duration_ms`；后台带 `initiated_by_user_id`；best-effort。

### Integration Points

- MODIFY：`server/Dockerfile`（Semgrep CLI + Node/Go/volar/gopls）
- MODIFY：`server/friday/settings.py`（Semgrep 路径/超时/并发；LSP 相关仅增探测/基准所需，默认 kill-switch 不盲翻）
- NEW：`semgrep_scan` + security scan MR section helper；`SecurityFinding` model + migration
- MODIFY：durable 任务注册；MR 双链路 append `## 安全扫描`
- MODIFY/EXTEND：`codegraph/lsp/*` 探测、生命周期、孤儿清扫
- NEW：基准报告产物 + IMPACT-03 真实样本复验（或诚实延期记账）
- ⛔ 不改：`repo_router_v2.py`；`mcp/` submodule

</code_context>

<specifics>
## Specific Ideas

- Research 明文：Semgrep「买不是造」；CE 承诺按单函数内 taint 收敛；Pro 仅 opt-in。
- Phase 124 已把「## 安全扫描」留给本相位；挂点必须复用 impact_report 的 hang-point，而不是另开第三条 MR 描述方言。
- LSP 真正前置是 Dockerfile——kill-switch 打开而镜像无 Node/Go 时会全量回落 tree-sitter（现状）。
- D-26：生产 `CrossRepoApiCall`/`ApiCallSite`/`ApiWrapper` 曾为 0 行；121-10「样本不足」实为「样本为零」——本相位必须闭合复验或诚实延期。
- 并发会话有其他 WIP：CONTEXT 提交只 stage 本文件。

</specifics>

<deferred>
## Deferred Ideas

- Semgrep blocking 规则白名单提级（观察期后的运营相位）
- 主干 full scan + finding 台账状态机 + 跨分支 triage（research v2+）
- LSP 常驻 daemon / 跨索引 session 复用以摊销冷启动（开启默认的可能前置）
- `mcp/` npm 包为任何新工具补条目（122 D-27 延续；本相位预计无新 MCP 工具名，若有只记账）
- Galaxy / 前端执行流或安全扫描可视化

</deferred>
