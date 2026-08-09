# Phase 127: Semgrep 门禁 + LSP 基准 - Research

**Researched:** 2026-08-10
**Domain:** Semgrep CLI 安全门禁（diff-aware / advisory）+ LSP 镜像运行时与抽取基准（volar/gopls）
**Confidence:** HIGH

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions

#### Area 1: Semgrep CLI/venv 打包 + subprocess 契约 + 超时/fail-open

- **D-01 — Semgrep 独立于 server Python 依赖树（TAINT-01 硬约束）**：在 `server/Dockerfile`（runtime 阶段）安装 Semgrep **独立** 形态——推荐 `uv tool install` / 独立 venv（如 `/opt/semgrep`）或官方二进制，**禁止**写入 `server/pyproject.toml` / `uv.lock`。版本钉 **≥ 1.172.0**（research：更低版本有 baseline 扫描误报 bug）。server 代码只持绝对路径配置（settings/env，如 `SEMGREP_BIN`），经 `subprocess` 调用；永不 `import semgrep`。
- **D-02 — 执行位置 = server 容器内 durable 异步任务 + `repo_mirror` worktree**：新增 `services/code_graph/semgrep_scan.py`（或同级模块）封装 CLI；扫描物化 worktree（复用 `repo_mirror` `_ensure_worktree` / 等价 API）。任务挂 durable（优先新 `QUEUE_SCAN`，或先落 `QUEUE_MAINTENANCE` 若规划认为拆队列成本偏高——Claude's Discretion），`ConcurrencyWindow` **限 1–2 并发**。⛔ 不走 runner/task 独立容器分发（research 已否决：组件面不成比例）。
- **D-03 — diff-aware 契约：`--baseline-commit` = merge-base，只报增量**：对 MR source/target 算 merge-base，传入 Semgrep baseline；必要时 `--include` 收窄到 diff 文件集。⛔ 禁止以 target HEAD 当 baseline（别人先合入的会算到本 MR）。⛔ 禁止默认同步全仓 full scan。
- **D-04 — 超时 fail-open，永不阻断建 MR（死亡螺旋四件套之一）**：显式 `SEMGREP_TIMEOUT`（单规则）+ 任务墙钟预算（settings/env）；超时 / CLI 崩溃 / mirror 失败 → **fail-open**：MR 照常创建/更新，安全扫描段写显式 stub（对齐 124 D-09/D-11），观测记 `error_code=timeout|unavailable|…`。⛔ 扫描不得挂在建 MR 的同步关键路径上阻塞创建（可 fire-and-forget defer，结果异步回填描述/评论；若首版只能「创建前尽最大努力」，硬墙钟到点必须放弃并标 stub）。
- **D-05 — 落库 `SecurityFinding`（软引用、脱敏）**：新模型（`codegraph` app 或研究建议的扫描落点），字段至少覆盖 repository/branch/mr 关联键、rule_id、severity、file_path、line、message、fingerprint、scan_sha、status（open 起步即可）。snippet/message 入库前过 `redact_secrets_in_text`。软引用不 FK Symbol（增量索引删建会牵连）。完整 triage 状态机 / 跨分支台账 **本相位不做**（research defer）。

#### Area 2: MR advisory 挂载 + nosemgrep + 诚实文案 + Pro token opt-in

- **D-06 — MR 挂点照抄 Phase 124 `impact_report` 范式**：新增共享 helper（建议 `security_scan_report.py` 或与 `semgrep_scan` 同模块的 `build_security_scan_section` / `append_security_scan`），顶层标记头统一 **`## 安全扫描`**；幂等 append（已含标记头不重复）；**workflow**（`AICodingNode` / `_create_mr_for_repo` 等建 MR 缝）与 **MCP**（`merge_request_service`）双链路同一入口。失败 stub 文案稳定短码，禁止堆栈/绝对路径/凭证进 MR。可与 `## 影响面` 并存，互不覆盖。
- **D-07 — 默认全程 advisory（TAINT-02）**：finding 带 severity 分级展示（ERROR/WARNING/INFO 或 Semgrep 等价映射），但本里程碑 **不** 阻断 merge、**不** 让扫描失败导致建 MR 失败、**不** 引入 blocking 规则白名单硬门禁。提级留作门禁跑量后的运营相位（对齐 research Pitfall 6 + Phase 114「超界待人审」哲学）。
- **D-08 — 诚实 CE 边界文案 + `nosemgrep` 通道（TAINT-03）**：`## 安全扫描` 段固定 disclaimer：当前为 Semgrep **CE**，taint **仅函数内**，不承诺跨函数/跨文件追踪；若 Pro token 已配置则另行列出「Pro 能力已启用」但不得夸大未验证能力。`nosemgrep` 走 Semgrep 原生抑制语义，文档/段内一句说明误报可标注；本相位不自建平行 suppress 表。
- **D-09 — Pro opt-in = 加密存储的 `SEMGREP_APP_TOKEN`**：用既有 **`SystemSetting` + `SettingKeys.SEMGREP_APP_TOKEN` + `is_encrypted=True`**（Fernet）承载；空/未配置 = CE。扫描子进程仅在有值时注入 `SEMGREP_APP_TOKEN` 环境变量；**永不**打进日志、MR、ledger 明文。⛔ 不把 token 塞进 `ProviderCredential` 的 LLM `provider_type` 选择器（当前 choices 仅 anthropic/openai/gemini/ollama，形状不合）。运维 env 直注可作为 escape hatch（Claude's Discretion），但仍不得入日志。
- **D-10 — 规则集起步纪律**：用官方 registry 精选 pack（如 p/python、p/django 等与本仓栈相关），不在本相位维护庞大自研规则集；自定义规则若有，必须带 owner 与误报出口说明。具体 pack 列表 Claude's Discretion，但须可配置/可文档化。

#### Area 3: LSP 镜像运行时 + 探测/fail-soft + 孤儿清扫

- **D-11 — Dockerfile 补齐 Node + Go + 语言服（LSP-01 前置）**：`server/Dockerfile` runtime 安装 **Node 22 LTS**、`@vue/language-server` 3.x（及 tsdk 发现所需 typescript）、**Go 工具链 + gopls（目标 v0.23.x 量级）**。镜像体积 +400–550MB 须进发布说明。与 D-01 Semgrep 安装同镜像、可同层或相邻层，注意非 root `friday` 用户 PATH 可达。
- **D-12 — 本里程碑不盲翻默认 kill-switch**：保持 `VOLAR_BACKEND_ENABLED` / `GOPLS_BACKEND_ENABLED` **默认 False**（Phase 66 现状）；镜像与探测落地后，运维/基准环境可通过 env=`true` 开启。`EXTRACTOR_BACKENDS` 声明表可按「重开目标」对齐 volar/gopls（与 kill-switch 正交），但 **全局默认开启** 只在 Area 4 基准门禁通过后才能改——本相位计划须把「是否翻默认」写成**数据驱动决策**，禁止顺手改 True。
- **D-13 — 可用性探测 + fail-soft（复用/扩展既有 `node_check`）**：沿用 `codegraph/lsp/node_check.py`（Node + vue-language-server + tsdk）；对称补齐 Go/gopls 探测（`go version` / `gopls version` 或等价）。探测失败 → `LspUnhealthyError` → 既有 TreeSitterBackend 回落（registry 集成测试已锁）；索引详情/日志透出「LSP 未启用：缺 X 运行时」，**不**把整条索引管线打成硬失败。
- **D-14 — 孤儿进程清扫**：LSP 子进程绑定索引任务生命周期（context manager / `finally` kill）；索引异常退出后不得留下无主 `gopls` / `vue-language-server`。启动或任务收尾增加孤儿收割（进程组/命令行匹配 + 计数事件如 `lsp_process_reaped`）。观测 `component` 走 codegraph/lsp 既有风格；best-effort 不反噬索引主路径。

#### Area 4: 基准报告方法 + 默认翻转门禁 + IMPACT-03 回访范围

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

### Deferred Ideas (OUT OF SCOPE)

- Semgrep blocking 规则白名单提级（观察期后的运营相位）
- 主干 full scan + finding 台账状态机 + 跨分支 triage（research v2+）
- LSP 常驻 daemon / 跨索引 session 复用以摊销冷启动（开启默认的可能前置）
- `mcp/` npm 包为任何新工具补条目（122 D-27 延续；本相位预计无新 MCP 工具名，若有只记账）
- Galaxy / 前端执行流或安全扫描可视化
</user_constraints>

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| TAINT-01 | MR 流程可触发 Semgrep diff-aware 扫描（`--baseline-commit` 取 merge-base），只报本次 MR 新增 finding；Semgrep 以独立 CLI/venv 形态集成，不进 server Python 依赖树 | D-01..D-04；Dockerfile `/opt/semgrep`；`semgrep scan --baseline-commit` + `ensure_mirror_*` worktree；durable 异步任务 |
| TAINT-02 | finding 带 severity 分级进 MR 描述/评论；门禁默认报告不阻断（advisory 起步）；`nosemgrep` 误报通道生效 | D-06/D-07/D-08；`## 安全扫描` helper 对标 `impact_report`；CE 原生 `nosemgrep` |
| TAINT-03 | 门禁文案如实声明 CE 版函数内 taint 边界；Pro 能力经 `SEMGREP_APP_TOKEN` opt-in | D-08/D-09；官方 CE = single-function taint；`SystemSetting` Fernet |
| LSP-01 | server 镜像补齐 Node/Go 运行时前提，volar/gopls 带可用性探测 + fail-soft 降级 + 孤儿进程清扫；产出开启前后基准报告，默认值翻转由基准数据决定 | D-11..D-16；既有 `node_check`/`go_check`；kill-switch 保持 False；`measure_*` 管理命令范式 |
</phase_requirements>

## Summary

Phase 127 收口 v0.22.0 两条与内存图**零耦合**的轨道。Semgrep 侧按「死亡螺旋四件套」落地：独立 CLI（钉 ≥1.172.0，不进 `uv.lock`）、merge-base baseline 的 diff-aware 扫描、advisory MR 段、超时/失败 fail-open。本仓已有 Phase 124 `impact_report` 幂等挂点与 GitHub/GitLab MR 描述回写范式，可原样复制到 `## 安全扫描`。LSP 侧真正阻塞是 `server/Dockerfile` 仍为 `python:3.14-slim`（无 Node/Go）；探测层 `node_check.py` / `go_check.py` 与 `LspUnhealthyError → TreeSitter` 回落**已存在**，本相位重点是镜像安装 + 孤儿收割 + 可复跑基准，**禁止盲翻** `VOLAR_BACKEND_ENABLED` / `GOPLS_BACKEND_ENABLED`。

**Primary recommendation:** 在 Dockerfile runtime（`USER friday` 之前）安装 `/opt/semgrep`（`uv tool install semgrep==1.172.0`）+ Node 22 + `@vue/language-server`/typescript + Go/gopls v0.23.x；新增 `QUEUE_SCAN` + slot lock 并发 2；`SecurityFinding` 落 `codegraph` 软引用模型；MR 双链路只挂 description 段（首版不写评论）；LSP 默认保持 False，基准与 IMPACT-03 复验/诚实延期写入 SUMMARY。

## Architectural Responsibility Map

| Capability | Primary Tier | Secondary Tier | Rationale |
|------------|-------------|----------------|-----------|
| Semgrep CLI 安装与 PATH | CDN / Static（镜像构建） | API / Backend | Dockerfile runtime 层交付二进制；server 只读 `SEMGREP_BIN` |
| Diff-aware 扫描编排 | API / Backend | Database / Storage | durable worker 在 server 进程内 subprocess；finding 落库 |
| MR `## 安全扫描` 段 | API / Backend | — | workflow + MCP 双链路共享 helper，与影响面段并存 |
| `SEMGREP_APP_TOKEN` 加密存储 | Database / Storage | API / Backend | `SystemSetting` Fernet；子进程 env 注入 |
| LSP 运行时（Node/Go/volar/gopls） | CDN / Static（镜像） | API / Backend | 镜像缺运行时则探测 fail-soft，kill-switch 正交 |
| LSP 探测 / 孤儿收割 | API / Backend | — | `codegraph/lsp/*`；索引生命周期绑定 |
| 抽取质量/耗时基准报告 | API / Backend | — | management command + 相位产物文件 |
| IMPACT-03 真实样本复验 | API / Backend | Database / Storage | 依赖重建后的 `CrossRepoApiCall` 行；无样本则诚实延期 |

## Project Constraints (from .cursor/rules/)

来自 `observability-logging.mdc`（强制，规划任务须写入验收）：

- `structlog.get_logger(__name__)`；事件 snake_case（`*_started` / `*_completed` / `*_failed`）+ `duration_ms`。
- 每事件设 `category`（`caller` / `sampling`）与 `component`。
- 后台 durable 任务必须携带并 re-bind `initiated_by_user_id`；无用户记 `system`。
- 凭证/token/`SEMGREP_APP_TOKEN` / finding snippet：`redact_secrets_in_text` / 禁止明文进日志·MR·ledger。
- 观测 best-effort，`except: pass`，永不反噬建 MR / 索引主路径。
- 高频循环（逐 finding）禁止 INFO 刷屏 → `sampling` + debug。
- 新增队列任务：积压可被快照采集；任务带发起用户。

## Standard Stack

### Core

| Library / Tool | Version | Purpose | Why Standard |
|----------------|---------|---------|--------------|
| Semgrep CE CLI | **1.172.0**（钉 ≥1.172.0）[VERIFIED: PyPI] | Diff-aware SAST / taint | 官方 CE；独立 venv；本仓 research 要求避开 <1.172 baseline bug |
| `semgrep scan --baseline-commit` / `SEMGREP_BASELINE_COMMIT` | CLI 现网文档 [CITED: docs.semgrep.dev/cli-reference] | 只报相对 baseline 的新增 finding | 官方明确：PR 理想值 = merge-base |
| `SEMGREP_TIMEOUT` / `--timeout` | 默认 5s/规则·文件 [CITED: docs.semgrep.dev] | 单规则超时 | 墙钟另加任务级预算 |
| Node.js | **22 LTS**（探测下界已是 ≥18） | volar 运行时 | `node_check._MIN_NODE_MAJOR=18`；CONTEXT 钉 22 LTS |
| `@vue/language-server` | **3.3.9** [VERIFIED: npm registry] | Vue/TS LSP | settings `vue-language-server --stdio` |
| `typescript` (tsdk) | **7.0.2**（构建时钉与语言服兼容的 5.x/7.x）[VERIFIED: npm] | `discover_tsdk()` | node_check 三探针依赖 |
| gopls | **v0.23.0** [VERIFIED: proxy.golang.org] | Go LSP | CONTEXT / research 目标量级；与本地 Go 1.26 兼容 |
| Go toolchain | 与 gopls 匹配的稳定版（镜像装官方 tarball） | `go list` 供 gopls | `go_check` 要求 go ≥1.20 |
| Django / durable / Procrastinate | 项目既有 | 异步扫描任务 | `QUEUE_*` + slot `lock` |
| `psutil` | 已在 `server/pyproject.toml`（≥5.9.0） | 孤儿进程收割 | 勿新增依赖 |

### Supporting

| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| `common.encryption.encrypt_value` / `decrypt_value` | 项目既有 | Fernet 存 `SEMGREP_APP_TOKEN` | 对齐 `FEISHU_APP_SECRET` |
| `redact_secrets_in_text` | 项目既有 | finding / stub 脱敏 | 入库与 MR 段 |
| `uv` | 镜像构建可用 | `uv tool install semgrep` 到 `/opt/semgrep` | Dockerfile 独立工具链 |
| 既有 `measure_gopls_init_time` / `measure_repo_index_stats` | 项目既有 | 基准命令模板 | LSP before/after 报告 |

### Alternatives Considered

| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| `/opt/semgrep` via `uv tool install` | 官方 Semgrep Docker 多阶段 COPY 二进制 | 多阶段更重；`uv tool` 与本仓 uv 工具链一致，推荐前者 |
| 新 `QUEUE_SCAN` | 复用 `QUEUE_MAINTENANCE` | Maintenance 混 ping/rescue；Semgrep CPU 重，独立队列更易观测/限流 → **推荐 QUEUE_SCAN** |
| MR description 段 | 首版同时写 MR comment | Comment 多平台差异大；description 已有三处挂点 → **首版仅 description** |
| `SecurityFinding` in `codegraph` | 新 `scanning` app | 新 app 迁移/注册成本高；125/126 软引用先例均在 codegraph → **推荐 codegraph** |

**Installation（镜像，非 server venv）:**

```dockerfile
# runtime stage, BEFORE `USER friday`
# 1) Semgrep isolated tool
RUN pip install --no-cache-dir uv \
 && uv tool install --default-index https://pypi.org/simple semgrep==1.172.0 \
      --install-dir /opt/semgrep
ENV PATH="/opt/semgrep/bin:${PATH}"
ENV SEMGREP_BIN=/opt/semgrep/bin/semgrep

# 2) Node 22 + vue-language-server + typescript (global, friday-readable)
# 3) Go toolchain + gopls@v0.23.0 into /usr/local
```

**Version verification (2026-08-10):**

| Package | Registry | Verified version |
|---------|----------|------------------|
| semgrep | PyPI | 1.172.0（`pip index versions`） |
| @vue/language-server | npm | 3.3.9 |
| typescript | npm | 7.0.2 |
| gopls | proxy.golang.org | v0.23.0 |
| Node | CONTEXT 钉 22 LTS | 镜像安装目标 |

## Package Legitimacy Audit

> 本相位**不**向 `server/pyproject.toml` / `uv.lock` 增加 Python 依赖。下列为 Dockerfile / 运行时安装物。

| Package | Registry | Age | Downloads / Signal | Source Repo | slopcheck | Disposition |
|---------|----------|-----|-------------------|-------------|-----------|-------------|
| semgrep==1.172.0 | PyPI | 多年成熟 SAST | 官方 Semgrep Inc | github.com/semgrep/semgrep | 工具误走 npm 通道；以官方 docs+PyPI 为准 → **Approved** | Approved — **禁止** `import semgrep` / 进 uv.lock |
| @vue/language-server@3.x | npm | since 2023-05 | Vue 官方 language-tools | github.com/vuejs/language-tools | N/A（镜像 npm i -g） | Approved |
| typescript | npm | 长期 | Microsoft | github.com/microsoft/TypeScript | N/A | Approved（仅 tsdk） |
| gopls v0.23.0 | Go module | Go 官方工具链 | golang.org/x/tools/gopls | go.googlesource.com/tools | N/A | Approved |
| Node 22 LTS | nodejs.org | LTS | 官方 | — | N/A | Approved |

**Packages removed due to slopcheck [SLOP] verdict:** none  
**Packages flagged as suspicious [SUS]:** none  
**Note:** 勿将 npm 上的同名 `semgrep` 包装进镜像作为 CLI 替代品——本相位 CLI 必须来自 **PyPI `semgrep`** 官方发行。

## Architecture Patterns

### System Architecture Diagram

```text
[Workflow/MCP create MR]
        |
        v
[append stub "## 安全扫描"] ---- never blocks MR create (fail-open)
        |
        v
[enqueue durable_semgrep_scan on QUEUE_SCAN, lock=scan-slot-N]
        |
        v
[ensure_mirror_sha + worktree] --> [git merge-base = baseline]
        |
        v
[SEMGREP_BIN scan --baseline-commit --json --config packs]
        |
        +--> SecurityFinding (redacted)
        +--> build_security_scan_section
        +--> async patch MR body (pr_cross_reference pattern)

LSP track (independent):
Dockerfile(Node/Go/volar/gopls) --> node_check/go_check --> kill-switch env
  --> LspSupervisor lifecycle + orphan reap --> measure_* baseline report
  --> IMPACT-03 real-sample revisit OR honest defer in SUMMARY
```

### Recommended Project Structure

```text
server/
├── Dockerfile                         # Semgrep + Node/Go/volar/gopls（USER friday 前）
├── friday/settings.py                 # SEMGREP_* / 并发；kill-switch 默认保持 False
├── system/models.py                   # SettingKeys.SEMGREP_APP_TOKEN
├── codegraph/
│   ├── models.py                      # SecurityFinding（软引用）
│   ├── migrations/00xx_securityfinding.py
│   ├── lsp/
│   │   ├── node_check.py              # 已有 — 复用
│   │   ├── go_check.py                # 已有 — 复用/微调
│   │   ├── orphan_reap.py             # NEW — psutil 收割
│   │   └── supervisor.py              # 确保 finally stop
│   └── management/commands/
│       ├── measure_lsp_baseline.py    # NEW — before/after 报告
│       └── revisit_impact03_samples.py # NEW — 真实样本或诚实延期
├── services/
│   ├── repo_mirror.py                 # 导出/包装 ensure_worktree_for_scan
│   └── code_graph/
│       ├── semgrep_scan.py            # NEW — CLI 封装 + 落库
│       ├── security_scan_report.py    # NEW — ## 安全扫描 helper
│       └── semgrep_enqueue.py         # NEW — durable 入队
├── durable/
│   ├── queues.py                      # QUEUE_SCAN
│   ├── concurrency.py                 # scan_slot_lock
│   ├── tasks.py / tasks_impl.py / handlers.py
└── tests/
    ├── services/code_graph/test_semgrep_*.py
    ├── services/code_graph/test_security_scan_report.py
    └── codegraph/lsp/test_orphan_reap.py
```

### Pattern 1: MR 段挂点（照抄 impact_report）

**What:** 标记头 + 幂等 append + 永不 raise + stub 短码。  
**When to use:** 所有建 MR 缝。  
**Example:**

```python
# Source: server/services/code_graph/impact_report.py (Phase 124)
SECURITY_SECTION_MARKER: Final[str] = "## 安全扫描"

def append_security_scan(description: str, section: str) -> str:
    if not section:
        return description or ""
    if SECURITY_SECTION_MARKER in (description or ""):
        return description
    base = (description or "").rstrip()
    return f"{base}\n\n{section}" if base else section
```

挂点文件（均已调用 `append_impact_report`）[VERIFIED: codebase]：

1. `server/workflows/nodes/ai/coding.py`（`_create_mr_for_repo`）
2. `server/workflows/services/mr_service.py`
3. `server/mcp_tools/merge_request_service.py`

### Pattern 2: Diff-aware Semgrep CLI

**What:** `semgrep scan`（非 `semgrep ci` 默认 exit-on-findings）+ `--baseline-commit=<merge-base>` + `--json` + `--config` packs。  
**When to use:** 每个 MR 扫描任务。  

```bash
# Source: https://docs.semgrep.dev/cli-reference
# Source: https://docs.semgrep.dev/semgrep-ci/ci-environment-variables/
git merge-base "$TARGET_SHA" "$SOURCE_SHA"   # → BASELINE
"$SEMGREP_BIN" scan \
  --baseline-commit "$BASELINE" \
  --config p/python --config p/django \
  --config p/javascript --config p/typescript --config p/golang \
  --json --quiet \
  --timeout "${SEMGREP_RULE_TIMEOUT:-5}" \
  --include 'path/from/diff...'   # optional narrow
```

**CE honesty** [CITED: docs.semgrep.dev/semgrep-pro-vs-oss]：CE = **single function taint**；跨函数/跨文件需 Pro Engine（`--pro` / App token）。

### Pattern 3: Durable 入队 + slot 并发

**What:** 新 `QUEUE_SCAN`；`lock=scan-slot-{stable_hash(repo)%N}`，N=2；`idempotency_key=semgrep:{repo}:{mr_key}`。  
**When to use:** 建 MR 后 fire-and-forget。  
**Why QUEUE_SCAN:** `run_worker` 默认 `",".join(ALL_QUEUES)` [VERIFIED: `durable/management/commands/run_worker.py`]，加入 `ALL_QUEUES` 即被消费；与 index/graph CPU 隔离优于塞进 `QUEUE_MAINTENANCE`。

### Pattern 4: 加密 SettingKeys

**What:** 对齐 `FEISHU_APP_SECRET`：`encrypt_value` + `is_encrypted=True`；读时 `decrypt_value`，仅注入子进程 env。  
**When to use:** Pro opt-in。

### Pattern 5: LSP 探测（已存在，勿重造）

**What:** `check_node_runtime()` / `check_go_runtime()` 进程级缓存；失败不 raise。  
**When to use:** 后端注册前 / 索引前。  
`go_check.py` 已要求 gopls ≥0.14 + go ≥1.20 [VERIFIED: codebase]——镜像装 v0.23.x 即可满足。

### Anti-Patterns to Avoid

- **把 Semgrep 写进 `pyproject.toml`：** 污染 server venv、拖慢构建、违反 D-01。
- **baseline = target HEAD：** 把别人先合入的 finding 算到本 MR [CITED: PITFALLS + Semgrep docs]。
- **同步阻塞建 MR：** 死亡螺旋；必须异步或硬墙钟 fail-open。
- **盲翻 VOLAR/GOPLS 默认 True：** D-12/D-16；镜像就绪 ≠ 质量/延迟可接受。
- **改 `repo_router_v2.py` 或 `mcp/`：** D-18 冻结。
- **扫描挂进 GraphService 热路径：** 零耦合纪律。
- **finding 明文凭证进 MR/日志：** LOGGING-SPEC 强制脱敏。

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Taint / 数据流分析 | 自研污点引擎 | Semgrep CE CLI | 行业「买不是造」；CE 边界诚实声明即可 |
| Diff-aware 过滤 | 自算行级 diff 再滤 finding | `--baseline-commit` | 官方语义；含移动/上下文 |
| 误报 suppress 表 | 自建 DB suppress | 原生 `nosemgrep` | D-08；少一套状态机 |
| MR 段幂等/stub | 新方言 | 复制 `impact_report` | 124 已锁双链路 |
| LSP 协议客户端 | 新协议栈 | 既有 `LspSupervisor` / volar/gopls backend | Phase 已有完整栈 |
| 加密 token 存储 | 新凭证表 | `SystemSetting` + Fernet | 与飞书 secret 同路 |
| 并发限流 | 自研信号量 | Procrastinate `lock` slot 池 | `durable/concurrency.py` 先例 |

**Key insight:** 本相位风险在集成契约（超时、baseline、脱敏、默认开关），不在发明扫描器或 LSP。

## Common Pitfalls

### Pitfall 1: Semgrep 死亡螺旋（四件套拆开）
**What goes wrong:** 全仓扫描 + 硬阻断 + 同步等待 → 两周内被关。  
**Why:** 误报疲劳与 MR 延迟。  
**How to avoid:** diff-aware + advisory + 异步 + fail-open **同相位**。  
**Warning signs:** MR 评论条数中位数 >5；批量无理由 `nosemgrep`。

### Pitfall 2: baseline 取错 / shallow clone 缺对象
**What goes wrong:** merge-base 或 baseline SHA 不在 mirror → CLI abort。  
**Why:** bare mirror 未 fetch 双端；shallow history。  
**How to avoid:** 扫描前 `ensure_mirror_sha` 两端 + merge-base；失败 → stub `unavailable`，不抛到建 MR。  
**Warning signs:** 日志 `baseline hash doesn't exist` / git cat-file 失败。

### Pitfall 3: worktree API 私有
**What goes wrong:** 直接依赖 `_ensure_worktree` 被重构打断。  
**Why:** 函数以下划线私有 [VERIFIED: `repo_mirror.py`]。  
**How to avoid:** 本相位在 `repo_mirror` 增加薄公共包装（如 `ensure_worktree_for_scan`），或经同模块已有公开路径扩展；禁止从业务层 monkey-patch 私有函数作为长期契约。

### Pitfall 4: Dockerfile USER friday PATH
**What goes wrong:** root 装到 `/usr/local` 或 `/root/.local`，`friday` 用户 `which` 失败 → 全量 tree-sitter 回落。  
**Why:** Dockerfile 末尾 `USER friday`。  
**How to avoid:** 工具装到 `/opt/...` 或 `/usr/local`，`ENV PATH` 对所有用户生效；构建末探针 `su friday -c 'semgrep --version && node -v && gopls version'`。

### Pitfall 5: LSP 孤儿进程
**What goes wrong:** 索引异常退出后残留 `gopls`/`vue-language-server`，内存爬升。  
**Why:** 子进程未绑生命周期。  
**How to avoid:** supervisor `finally: stop()` + `psutil` 按 cmdline 收割 + `lsp_process_reaped` 计数。  
**Warning signs:** 容器 `ps` 多条无主 LSP。

### Pitfall 6: 把合成 IMPACT-03 绿测当成真实验证
**What goes wrong:** 宣称跨仓已验证。  
**Why:** `test_cross_repo_hop.py` 全合成；生产曾 0 行 [VERIFIED: test docstring + ROADMAP]。  
**How to avoid:** D-17 二选一：真实样本复验 **或** SUMMARY 诚实延期。

### Pitfall 7: Semgrep `ci` vs `scan` exit code
**What goes wrong:** `semgrep ci` 默认 finding 非零退出被误当成任务失败。  
**Why:** CI 命令面向门禁。  
**How to avoid:** 用 `semgrep scan`；解析 `--json`；进程非零仅表示 CLI 错误，finding 条数不驱动 fail-closed。

## Code Examples

### SecurityFinding 软引用模型（对齐 SymbolCommunity）

```python
# Pattern source: server/codegraph/models.py SymbolCommunity / ProcessTrace
class SecurityFinding(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    repository = models.ForeignKey("repositories.Repository", on_delete=models.CASCADE)
    branch_name = models.CharField(max_length=200, default="", blank=True)
    mr_key = models.CharField(max_length=128, blank=True, default="")  # platform iid/number
    rule_id = models.CharField(max_length=256)
    severity = models.CharField(max_length=32)  # ERROR|WARNING|INFO|…
    file_path = models.TextField()
    line = models.PositiveIntegerField(null=True)
    message = models.TextField()  # pre-redacted
    fingerprint = models.CharField(max_length=128, blank=True, default="")
    scan_sha = models.CharField(max_length=64, blank=True, default="")
    status = models.CharField(max_length=32, default="open")
    # ⛔ 不对 Symbol FK
```

### 加密 token 注入子进程

```python
# Pattern source: services/feishu_im.py + common.encryption
env = os.environ.copy()
row = await SystemSetting.objects.filter(key=SettingKeys.SEMGREP_APP_TOKEN).afirst()
if row and row.value:
    token = decrypt_value(row.value) if row.is_encrypted else row.value
    if token:
        env["SEMGREP_APP_TOKEN"] = token  # never log
# optional escape hatch: settings.SEMGREP_APP_TOKEN from env if SystemSetting empty
```

### 异步回填 MR 描述

```python
# Pattern source: workflows/services/pr_cross_reference.py
# GitHub: pr.edit(body=new_body) / GitLab: mr.description=...; mr.save()
# 幂等：若已有完整 ## 安全扫描且非 stub，可 skip；stub→完整结果时需替换策略
# 推荐：标记头后首次写入；更新时若段内含 `_未能生成` stub 则整段替换
```

### LSP 孤儿收割（推荐）

```python
# psutil already depended
import psutil
TARGETS = ("gopls", "vue-language-server", "typescript-language-server")
reaped = 0
for proc in psutil.process_iter(["pid", "name", "cmdline", "ppid"]):
    # match orphan: parent gone or cmdline match + not in live supervisor set
    ...
logger.info("lsp_process_reaped", category="sampling", component="codegraph.lsp", count=reaped)
```

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| 自研污点 / CodeQL 重路线 | 外购 Semgrep CE + 诚实边界 | v0.22 research | 集成面可控 |
| Semgrep 进 server venv | 独立 `/opt/semgrep` CLI | Phase 127 | 依赖隔离 |
| LSP 默认开 → Phase 66 双关 | 镜像补齐 + 探测 + 基准后再决定 | Phase 66 → 127 | 避免冷启动拖垮索引 |
| IMPACT-03 合成绿测 | LSP 后真实样本或诚实延期 | Phase 122 → 127 D-17 | 关闭「样本为零」账本 |

**Deprecated/outdated:**

- 将 target HEAD 当 Semgrep baseline（官方与 PITFALLS 均反对）。
- 无条件 `VOLAR_BACKEND_ENABLED=True` 作为「完成 LSP-01」的判据。

## Discretion Recommendations (for planner)

| Topic | Recommendation | Confidence |
|-------|----------------|------------|
| Queue | **`QUEUE_SCAN = "scan"`** 加入 `ALL_QUEUES` | HIGH |
| Concurrency | **N=2** `scan-slot-*`；settings `CONCURRENCY_SCAN_MAX` / env | HIGH |
| Rule timeout | `SEMGREP_TIMEOUT=5`（官方默认）；任务墙钟 **180s** | MEDIUM |
| Packs | `p/python,p/django,p/javascript,p/typescript,p/golang`；`SEMGREP_CONFIGS` 可配 CSV | HIGH |
| SecurityFinding app | **`codegraph`** | HIGH |
| MR surface | **description 段 only**（首版）；不写 comment | HIGH |
| Token escape hatch | env `SEMGREP_APP_TOKEN` 仅当 SystemSetting 空时回退 | MEDIUM |
| Orphan reap | **psutil** cmdline 匹配 + supervisor live-set 排除 | HIGH |
| Baseline cmd | `measure_lsp_baseline` → JSON under `.planning/phases/127-semgrep-lsp/` | HIGH |
| IMPACT-03 | management command：`count>0` 跑四分支抽样；`count==0` 写诚实延期段落到 SUMMARY | HIGH |
| EXTRACTOR_BACKENDS | 可将 `go` 声明改回 `gopls` 作为「重开目标」**仅当**文档写明仍受 kill-switch 约束；**默认 kill-switch 仍 False** | MEDIUM |

## Assumptions Log

| # | Claim | Section | Risk if Wrong |
|---|-------|---------|---------------|
| A1 | 任务墙钟 180s 对精选 pack + `--include` 足够 | Discretion | 大 MR 频繁 stub → 调高或收窄 pack |
| A2 | 首版仅 description、不写 MR comment 满足 TAINT-02「描述/评论」 | Discretion | 产品坚持评论时需二期加平台 adapter |
| A3 | Pro token 注入 env 即可启用跨函数能力，无需额外 `--pro` 旗标组合 | Pro opt-in | 需在实现时用官方 CLI help 再核一次；失败则 CE disclaimer 仍成立 |
| A4 | study-course / 既有夹具仓足以做 Vue+Go 基准 | D-15 | 需另选真实内仓 |

**A3 note:** Pro 能力激活路径以实现期 `semgrep scan --help` + 官方 Pro docs 为准；文案侧即使 Pro 启用也不得夸大未实测的跨文件覆盖率（D-08）。

## Open Questions

1. **异步回填 vs 创建前尽力**
   - What we know: D-04 允许 fire-and-forget；`pr_cross_reference` 已有 MR 编辑范式。
   - What's unclear: 首版是否必须「创建时带完整结果」。
   - Recommendation: **创建时写 stub 或空安全段 → 任务完成后替换/填充**；墙钟内能完成则创建前也可同步跑，超时仍 stub。

2. **`EXTRACTOR_BACKENDS["go"]` 是否改回 `gopls`**
   - What we know: 现为 `tree_sitter` 注释「默认禁用 gopls」；声明表与 kill-switch 正交。
   - Recommendation: 可改声明以匹配「重开目标」，但 **不得** 改 kill-switch 默认。

## Environment Availability

| Dependency | Required By | Available (dev host) | Version | Fallback |
|------------|------------|----------------------|---------|----------|
| Python | server | ✓ | 3.14.6 | — |
| uv | Semgrep 镜像安装 | ✓ | 0.11.8 | pip venv at `/opt/semgrep` |
| Node | LSP volar | ✓ (host) | v24.14.1 | 镜像钉 22 LTS |
| Go | gopls | ✓ (host) | 1.26.2 | 镜像装官方 toolchain |
| gopls | LSP | ✗ on host PATH at probe time | — | 镜像 `go install`；`go_check` fail-soft |
| semgrep | TAINT | ✗ on host | PyPI 1.172.0 | 镜像 `/opt/semgrep`；测试 mock subprocess |
| Docker build | 镜像验收 | 视 CI | — | 本地 `docker build` 探针层 |
| Postgres durable | QUEUE_SCAN | 视部署 | — | in-process backend 仍可单测入队逻辑 |

**Missing dependencies with no fallback:** 无（扫描/LSP 均 fail-open / fail-soft）。  
**Missing dependencies with fallback:** host 无 semgrep/gopls → 单测 mock；生产靠镜像。

Step 2.6: 外部依赖已审计（上表）。

## Validation Architecture

### Test Framework

| Property | Value |
|----------|-------|
| Framework | pytest + pytest-django（server） |
| Config file | `server/pyproject.toml` `[tool.pytest.ini_options]` |
| Quick run command | `cd server && uv run pytest tests/services/code_graph/test_security_scan_report.py tests/services/code_graph/test_semgrep_scan.py tests/codegraph/lsp/test_orphan_reap.py -q` |
| Full suite command | `cd server && uv run pytest -q`（注意 addopts 排除 `perf/integration/slow/postgres_queue`） |

### Phase Requirements → Test Map

| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| TAINT-01 | CLI argv 含 `--baseline-commit=<merge-base>`；不 import semgrep；bin 来自 settings | unit | `pytest tests/services/code_graph/test_semgrep_scan.py -q` | ❌ Wave 0 |
| TAINT-01 | mirror/CLI 失败不阻断；error_code 稳定 | unit | 同上 | ❌ Wave 0 |
| TAINT-02 | severity 映射进 `## 安全扫描`；advisory（无 raise） | unit | `pytest tests/services/code_graph/test_security_scan_report.py -q` | ❌ Wave 0 |
| TAINT-02 | `nosemgrep`：mock JSON 无被抑 finding / 文档句存在 | unit | 同上 | ❌ Wave 0 |
| TAINT-02 | workflow + MCP 双链路均 append 段 | unit | 扩展 `test_coding_impact_report` / `test_mr_impact_report` 模式 | ❌ Wave 0 |
| TAINT-03 | 段内含 CE 函数内 taint disclaimer | unit | `test_security_scan_report` | ❌ Wave 0 |
| TAINT-03 | token 不出现在日志/MR 字符串 | unit | assert 日志/section 无 token | ❌ Wave 0 |
| TAINT-03 | 空 token = CE 文案；有 token =「Pro 已配置」句且不夸大 | unit | 同上 | ❌ Wave 0 |
| LSP-01 | Dockerfile 含 node/go/semgrep 安装指令（静态断言或 build smoke） | smoke | 文件断言 / CI image probe | ❌ Wave 0 |
| LSP-01 | 缺二进制时 check_* available=False（既有测试） | unit | `pytest codegraph/lsp/tests/test_node_check.py test_go_check.py -q` | ✅ |
| LSP-01 | 孤儿收割计数 / finally stop | unit | `test_orphan_reap.py` | ❌ Wave 0 |
| LSP-01 | settings 默认 VOLAR/GOPLS False | unit | assert settings defaults | ❌ Wave 0 |
| LSP-01 | 基准命令可 skip-on-missing | unit/cmd | `measure_lsp_baseline --skip-on-missing-binary` | ❌ Wave 0 |
| D-17 | 样本 0 → 诚实延期路径；样本 >0 → 四分支调用 | unit | `test_revisit_impact03.py` | ❌ Wave 0 |

### Sampling Rate

- **Per task commit:** 上表 quick run（相关新文件）
- **Per wave merge:** `cd server && uv run pytest tests/services/code_graph/ tests/workflows/test_coding_impact_report.py tests/mcp_tools/test_mr_impact_report.py codegraph/lsp/tests/ -q`
- **Phase gate:** Full default suite green；已知 `mcp` snapshot 漂移仍白名单（D-18）

### Wave 0 Gaps

- [ ] `server/tests/services/code_graph/test_semgrep_scan.py` — TAINT-01 CLI 契约 / fail-open
- [ ] `server/tests/services/code_graph/test_security_scan_report.py` — TAINT-02/03 段文案与幂等
- [ ] `server/tests/services/code_graph/test_semgrep_enqueue.py` — QUEUE_SCAN / lock / idempotency
- [ ] `server/tests/codegraph/test_security_finding_model.py` — 模型字段 / 无 Symbol FK
- [ ] `server/codegraph/lsp/tests/test_orphan_reap.py` — 孤儿收割
- [ ] `server/tests/codegraph/test_lsp_defaults_unchanged.py` — kill-switch 默认 False
- [ ] Fixture：假 semgrep JSON stdout（含 severity / fingerprint / 被 nosemgrep 忽略的形态）
- [ ] （可选）Dockerfile 静态 grep 测试：断言 `semgrep`/`nodejs`/`gopls` 安装层存在

## Security Domain

### Applicable ASVS Categories

| ASVS Category | Applies | Standard Control |
|---------------|---------|-----------------|
| V2 Authentication | no（本相位不改认证） | — |
| V3 Session Management | no | — |
| V4 Access Control | yes（弱） | 扫描任务须带 repo 权限上下文；MR 回写用既有 git token 解析 |
| V5 Input Validation | yes | subprocess argv 白名单；path `--include` 校验；超时 bound |
| V6 Cryptography | yes | `SEMGREP_APP_TOKEN` → Fernet `encrypt_value`；禁止明文日志 |

### Known Threat Patterns for Semgrep + LSP

| Pattern | STRIDE | Standard Mitigation |
|---------|--------|---------------------|
| Token / finding 片段泄露到 MR/日志 | Information Disclosure | `redact_secrets_in_text`；token 仅 env；日志禁打印 env |
| 恶意 repo 内容借 Semgrep/LSP 打满 CPU | Denial of Service | 墙钟 + 并发 slot=2 + fail-open |
| subprocess 命令注入 | Tampering | 固定 `SEMGREP_BIN` 绝对路径；argv 列表传递；SHA/路径校验 |
| 孤儿 LSP 耗尽内存 | Denial of Service | finally kill + psutil reap |
| 伪造成「已阻断」的安全感 | Spoofing / Elevation of expectation | 文案标明 advisory + CE 边界 |

## Sources

### Primary (HIGH confidence)

- [VERIFIED: codebase] `server/Dockerfile`, `server/services/code_graph/impact_report.py`, `server/codegraph/lsp/{node_check,go_check,supervisor}.py`, `server/durable/{queues,concurrency,tasks}.py`, `server/services/repo_mirror.py`, `server/friday/settings.py` (VOLAR/GOPLS defaults), `server/tests/services/code_graph/test_cross_repo_hop.py`
- [CITED: docs.semgrep.dev/cli-reference] `--baseline-commit`, `--json`, `--timeout`
- [CITED: docs.semgrep.dev/semgrep-ci/ci-environment-variables] merge-base 作为 `SEMGREP_BASELINE_COMMIT` 理想值；`SEMGREP_TIMEOUT`
- [CITED: docs.semgrep.dev/semgrep-pro-vs-oss] CE = single-function taint；Pro = cross-function/file
- [CITED: docs.semgrep.dev/writing-rules/data-flow/taint-mode/overview] interprocedural = Pro
- [VERIFIED: PyPI] semgrep 1.172.0
- [VERIFIED: proxy.golang.org] gopls v0.23.0
- [VERIFIED: npm] @vue/language-server 3.3.9
- `.planning/research/{SUMMARY,ARCHITECTURE,PITFALLS}.md` — 死亡螺旋与 LSP 风险面

### Secondary (MEDIUM confidence)

- 镜像体积 +400–550MB — 来自里程碑 research 估算，实现期以实际 `docker images` 为准
- Pro token 仅设 env 是否足够启用跨函数 — 实现期 CLI 复核（Assumptions A3）

### Tertiary (LOW confidence)

- 无

## Metadata

**Confidence breakdown:**

- Standard stack: **HIGH** — 版本与官方 CLI 契约已核对；本仓挂点/探测代码已读
- Architecture: **HIGH** — 对标 Phase 124/125 durable + impact_report；队列/worktree 缝清晰
- Pitfalls: **HIGH** — 与 PITFALLS.md + Semgrep 官方 baseline/timeout 文档交叉验证

**Research date:** 2026-08-10  
**Valid until:** 2026-09-10（Semgrep/gopls 发版较快，钉版本后 30 天内有效）
