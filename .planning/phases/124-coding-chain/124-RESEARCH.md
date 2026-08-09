# Phase 124: 编码链闭环 - Research

**Researched:** 2026-08-10
**Domain:** 编码任务容器知识 MCP 白名单 / system prompt 指引 + 服务端 MR 影响面报告（消费 Phase 123 `run_detect_changes`）
**Confidence:** HIGH

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions

#### Area 1: 容器提交前自查（DIFF-03）— prompt 挂点 / 非阻断语义 / 仓与分支

- **D-01 — prompt 注入点 = `task/core/executor.py::_get_system_prompt`，照抄 `follow_openspec` 条件追加范式**：新增独立静态 helper（建议 `_detect_changes_guidance()`），在编码模式且 knowledge MCP 已挂载时追加「完成文件修改后、结束 turn 前，调用 `detect_changes` 自查受影响符号与风险；根据清单决定是否继续修补；结果仅供决策参考，不要因为工具失败而停止交付」。⛔ 不改 `runner.py` commit/push 路径做硬门禁（research Pattern 3；成功标准 1 明文 v1 提示不阻断）。静态可信文本，无外部输入拼接，无 prompt 注入面。
- **D-02 — 白名单：把 `detect_changes` 加进 `task/core/knowledge_tools.py` 的 `KNOWLEDGE_TOOL_SCHEMAS` + `knowledge_allowed_tools()`**：`input_schema` 对照 server `DetectChangesRequestSerializer`（已有 `/api/mcp/tools/detect_changes/` PAT 面）。工具 description 写清「编码完成后、提交前自查影响面；`compare` 用当前任务分支」。既有知识工具配额/配额耗尽文案沿用，不另造配额体系。
- **D-03 — 自查调用参数约定（写入 prompt，不硬编码 runner）**：`repository_id` = 本任务仓；`compare` = 当前任务功能分支（工作区已在该分支）；`base_ref` 可选透出 MR 目标分支语义，但行号交叠基线仍由 Phase 123 D-01 强制锚定 `last_indexed_commit_sha`——agent 不得也不必传「工作树 tip」当 base。未索引 / mirror 失败时工具返回明确 `ok=False`；prompt 指示「失败则记录原因并继续交付，不重试刷屏」。
- **D-04 — 非阻断语义（硬约束）**：detect_changes 结果（含 HIGH/CRITICAL、`staleness`、工具错误、配额用尽）**一律不**阻止 agent 结束 turn，也**不**改 runner commit 决策。v1 成功标准是「清单进入提交决策（指引）」而非门禁。未来硬门禁另开相位。

#### Area 2: MR 影响面报告 — 共享 formatter / 双链路挂点 / 四段 schema

- **D-05 — 共享编排 + 共享 markdown formatter（单一事实源）**：新增纯函数/小模块（建议落点 `server/services/code_graph/impact_report.py`，或与 `code_graph_tools.py` 同级 helper）提供：
  1. `build_impact_report_section(...)` → 调已有 `run_detect_changes`（同源信封）→ 渲染 markdown 段；
  2. 输入最少：`repository` / `compare`（= source_branch）/ 可选 `base_ref`（= target_branch，仅声明）/ 调用方 `user`（ACL）。
  ⛔ 不得在 workflow 壳与 MCP 壳各写一套渲染；⛔ 不得在壳里重写 impact BFS。报告数据以 **建 MR 时服务端实时调用** `run_detect_changes` 为准（不依赖容器内 agent 是否真的自查过——自查是 DIFF-03 行为指引，报告是 DIFF-04 服务端保证）。
- **D-06 — 双链路挂点（既有缝，零新机制）**：
  - **Workflow**：`server/workflows/nodes/ai/coding.py` 的 `_create_mr_for_repo`（拼 `description`/`body` 处，约 2194–2219）在 `create_merge_request` **之前**追加影响面段；多仓 wave 路径与现有 `pr_cross_reference`「## 关联 PR」fail-soft 同姿态。`workflows/services/mr_service.py::build_mr_description` / `create_mr_for_task` 若仍被调用，同一 helper 挂接，避免第三条方言。
  - **MCP**：`server/mcp_tools/merge_request_service.py`——在 `_draft_from_summary` 与/或 `create_merge_request` 缺省 description 拼接点（`:65-71` / `:143-147`）追加同一段。调用方已显式传入完整 description 时：若尚未含影响面标记头，则 **append**；已含则不重复（幂等）。
- **D-07 — 四段结构（DIFF-04 明文）**：顶层标题统一 `## 影响面`（与 research / 中文 MR 既有段落风格一致）；其下固定四个小节：
  1. `### Changes` — 变更文件/符号摘要（`changeType`、行数、`file:line`；超阈值沿用 123 文件级摘要）
  2. `### Affected` — 批量 impact 受影响面（深度分组 / 关键符号；截断计数必给）
  3. `### Risk` — 确定性风险等级（LOW/MEDIUM/HIGH/CRITICAL）+ 简短可解释依据；透出 `staleness`（索引落后 N commits / as_of）
  4. `### Recommendations` — 行动建议（如「复核 d1 callers」「建议重索引后再信行号」）；`affected_processes` 仍为空占位，本相位不编造 Process 叙事（Phase 126）
  英文章节名保留（需求字面）；正文中文可混排。字段映射全部来自 123 信封，不发明第三套方言。
- **D-08 — 报告体积纪律**：单段 markdown 设软上限（初值建议 ~8–12KB 或符号/文件 top-N，具体 Claude's Discretion），超限截断并注明 `truncated`；⛔ 不把源码正文塞进 MR 描述（沿用 122 D-17 `include_content` 默认关）。

#### Area 3: Fail-soft — 超时 / 错误分类 / 失败时写入内容

- **D-09 — MR 路径 fail-soft 契约（成功标准 3）**：影响面报告路径上任何失败——`run_detect_changes` 抛异常、`ok=False`、超时、ACL、未索引、mirror fetch 失败、渲染异常——**一律吞掉**，不得向上抛到 `create_merge_request` / `_create_mr_for_repo`。MR 仍按原 description 创建。观测 best-effort（见 D-12）。
- **D-10 — 超时预算**：建 MR 路径对 `run_detect_changes` 设显式超时（初值建议 **30s**，可 settings/env 化；Claude's Discretion 微调）。超时视同失败走 D-09。容器内 agent 自查走既有 MCP/知识工具超时与配额，不另加 runner 等待。
- **D-11 — 失败时写入内容**：优先写**短 stub** 而非静默省略，让 reviewer 知道系统尝试过：
  ```markdown
  ## 影响面

  _影响面报告未能生成（`{error_code}`）。MR 已照常创建，请人工复核变更影响。_
  ```
  `error_code` 取信封/异常映射的稳定码（如 `not_indexed` / `timeout` / `unavailable`）；⛔ 禁止把堆栈、token、绝对路径、凭证写入 MR 描述或日志明文。若连 stub 渲染也失败 → 完全省略影响面段（最后兜底，对齐 `pr_cross_reference` 空串语义）。
- **D-12 — 部分成功照常出报告**：`ok=True` 但带 `staleness` / `degradation` / 单符号 `impact_error` 时**仍渲染**完整四段，并在 Risk/Recommendations 醒目声明降级与 stale（继承 123 D-04/D-12）。只有整体失败才走 D-11 stub。

#### Area 4: 观测 / 开关 / 双路径对等 / 冻结面

- **D-13 — 无新业务 kill-switch（v1 默认开）**：编码容器挂 knowledge 工具时白名单+prompt 默认生效；建 MR 路径默认尝试附报告。仅允许运维向超时/体积阈值 settings（若需要），⛔ 不为本相位新增「关闭影响面」产品开关（避免双路径一边开一边关导致漂移）。若未来需要，另开相位。
- **D-14 — 双路径对等**：workflow 与 MCP **必须**调用同一 `build_impact_report_section`（或等价单一入口）；验收含：两边对同一 `(repo, compare)` fixture 产出的 `## 影响面` 正文字节级或规范化后一致；失败 stub 文案一致。照抄 122/123 双面哨兵精神（此处是 MR 双链路，非 MCP+chat）。
- **D-15 — 观测契约**：`component="code_graph"`（报告生成/detect_changes 消费）或挂接点所在组件（`workflows` / `mcp_tools`）按入口记 `category=caller`；事件名静态字面量（如 `impact_report_started` / `impact_report_completed` / `impact_report_failed`），带 `duration_ms`、`repository_id`、`error_code`（失败时）、`section_chars`；高频细节 `category=sampling`。后台/任务路径带 `initiated_by_user_id`（无则 `system`）。观测代码 best-effort，绝不反噬建 MR。凭证/上游异常文本走既有 redact。
- **D-16 — 冻结与欠债延续**：⛔ 不改 `repo_router_v2.py`；⛔ 不改 `mcp/` submodule（122 D-27 / 123 延续；SUMMARY 若触及 snapshot 漂移只更新计数）。task 侧 schema 硬编码在 `knowledge_tools.py` 是合法接线（与 server MCP 面并行，非 npm 包）。并发 WIP：提交本 CONTEXT 时**只 stage 本文件**。

### Claude's Discretion

- `_detect_changes_guidance` 中文措辞细节、是否仅在 `task_mode` 实现路径追加（explore/readonly 不挂）。
- 报告 top-N / 字符软上限具体数字、超时初值微调、settings 键名。
- `impact_report` 模块文件名与是否再抽 `append_impact_report(description) -> str` 小工具。
- 测试组织：task 白名单单测、prompt 段零回归、MR 双链路 fail-soft / 对等哨兵、formatter 快照。
- CreatePRNode（手动 git 节点）是否顺手挂同一 helper——推荐挂以消方言，但不挂不算本相位缺口（wave/`AICodingNode` + MCP 是成功标准覆盖面）。

### Deferred Ideas (OUT OF SCOPE)

- **Runner / CI 硬门禁**（HIGH/CRITICAL 阻断 commit 或 MR）— v2+；本相位明确不做。
- **EXEC-03 / Phase 126** — `affected_processes` 回填进 Recommendations 增值段。
- **`detect_impact` 式 MCP 编排 prompt** — REQUIREMENTS Future；等工具面稳定。
- **`mcp` npm 包补条目** — 沿用 122 D-27，本相位不改 submodule。
- **CreatePRNode 手动节点统一挂 impact report** — 推荐但非成功标准必达；可 backlog。
- **Semgrep「## 安全扫描」段** — research Pattern 6，另相。
- **影响面报告产品级 kill-switch / 灰度** — v1 默认开；若运维需要再开相位。
</user_constraints>

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| DIFF-03 | 编码任务容器在提交前可经既有 MCP PAT 白名单调用 detect_changes 自查（受影响清单进提交决策） | D-01..D-04：`knowledge_tools` 白名单 + `_get_system_prompt` 指引；server `DetectChangesView` 已就绪；v1 非阻断 |
| DIFF-04 | MR 描述自动附影响面报告（Changes / Affected / Risk / Recommendations 四段结构），fail-soft 不阻断建 MR 主流程 | D-05..D-12 / D-14：共享 `build_impact_report_section` 挂 `_create_mr_for_repo` + `merge_request_service`；超时 stub；双路径对等 |
</phase_requirements>

## Summary

Phase 124 **不重做** detect_changes，只把 Phase 123 已交付的 `run_detect_changes`（及既有 MCP PAT 面 `/api/mcp/tools/detect_changes/`）真正挂进「需求→PR」编码链。DIFF-03 是 **容器侧接线**：把工具名加进 `task/core/knowledge_tools.py` 白名单，并在 `executor._get_system_prompt` 按 `follow_openspec` 同款条件追加静态指引——agent 在结束 turn 前自查；**绝不**改 `runner.py` commit/push 做硬门禁。DIFF-04 是 **服务端保证**：在 workflow `AICodingNode._create_mr_for_repo` 与 MCP `merge_request_service` 建 MR 前，调用共享 `build_impact_report_section` 实时跑 `run_detect_changes` 并渲染 `## 影响面` 四段；失败写短 stub、超时 ~30s、观测 best-effort，建 MR 主流程零阻断。

与 GitNexus 硬门禁示例刻意分流：Friday 编码链误报成本更高，v1 成功标准是「清单进入提交决策（指引）」+「MR 描述有报告」，不是阻断。报告以建 MR 时服务端重算为准，避免「agent 忘了自查 → MR 无影响面」。

**Primary recommendation:** 新增 `server/services/code_graph/impact_report.py`（`build_impact_report_section` + `append_impact_report`），双 MR 链路只调这一入口；task 侧仅扩白名单 + prompt helper；零新依赖、零 migration、冻结 `repo_router_v2.py` 与 `mcp/` submodule。

## Project Constraints (from .cursor/rules/)

来自 `.cursor/rules/observability-logging.mdc`（本相位强制适用）：

- `structlog.get_logger(__name__)`；事件名 snake_case 静态字面量（`impact_report_started` / `_completed` / `_failed`）；字段 kv，勿把变量拼进 message。
- 生命周期带 `duration_ms`；设 `category`（`caller` / `sampling`）与 `component`（报告生成用 `code_graph`；挂接点可用 `workflows` / `mcp_tools`）。
- 后台/workflow 路径绑定 `initiated_by_user_id`（无则 `system`）。
- 凭证 / 上游异常文本走 `redact_credentials` / `redact_secrets_in_text`；⛔ 禁止堆栈、token、绝对路径进 MR 描述或日志明文。
- 观测 best-effort（`except: pass`），绝不反噬建 MR。
- 高频细节用 `sampling` + DEBUG，禁止 INFO 刷屏。

GSD workflow：本相位计划/实现须走 GSD 入口；研究阶段已遵守 CONTEXT 锁定决策，不重开 D-01..D-16。

## Architectural Responsibility Map

| Capability | Primary Tier | Secondary Tier | Rationale |
|------------|-------------|----------------|-----------|
| 容器 detect_changes 工具暴露（白名单 + HTTP PAT） | Task executor (`task/`) | API / Backend (`DetectChangesView`) | 容器只挂 schema/handler；算法与 ACL 在 server |
| 提交前自查指引（system prompt） | Task executor | — | 静态文本注入 `_get_system_prompt`；不改 runner 门禁 |
| Runner commit/push | Task executor (`runner.py`) | — | **本相位不改**；保持非阻断 |
| `run_detect_changes` 编排 | API / Backend (`code_graph_tools`) | Database / Storage (Symbol / mirror) | Phase 123 已交付；本相位只消费 |
| MR 影响面报告生成 / 渲染 | API / Backend (`impact_report`) | — | 单一事实源；壳层零算法 |
| Workflow 建 MR 挂点 | API / Backend (`AICodingNode`) | Git platform | `_create_mr_for_repo` 拼 description 前 append |
| MCP 建 MR 挂点 | API / Backend (`merge_request_service`) | Git platform | draft / create 路径 append 同一段 |
| 观测埋点 | API / Backend | — | `component=code_graph` + 入口组件；best-effort |

## Standard Stack

### Core

| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| 既有 `run_detect_changes` | Phase 123（本仓） | 影响面数据源 | CONTEXT D-05；禁止重写 BFS |
| Django 5.1+ / adrf | 本仓 pin | async 视图与 ORM | 项目栈 |
| structlog | 本仓 pin | 结构化观测 | observability-logging.mdc |
| claude-agent-sdk（task） | `task/pyproject.toml` pin | 容器 MCP server / allowed_tools | 既有 knowledge MCP 面 |
| httpx（task） | 本仓 pin | 容器→server MCP HTTP | knowledge_tools 既有 handler |

### Supporting

| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| `asyncio.wait_for` | stdlib | MR 路径 30s 超时 | 包住 `run_detect_changes`（D-10） |
| pytest / pytest-asyncio / pytest-django | server/task pin | 单测与双链路哨兵 | Validation Architecture |
| vitest | web pin | — | **本相位无前端**；跳过 |

### Alternatives Considered

| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| 服务端重算报告 | 复用容器 agent 自查结果写 MR | 否决：agent 可能忘调；D-05 明文服务端保证 |
| runner 硬门禁 | prompt 指引 | 否决：D-04 / 误报卡死编码链 |
| 壳内各写一套 markdown | 共享 `impact_report` | 否决：D-14 对等 |

**Installation:** 无新第三方包。

```bash
# 无 npm/pip 新增依赖
```

**Version verification:** N/A — 本相位不安装外部包。`asyncio` / Django / structlog / httpx / claude-agent-sdk 均为既有栈。 [VERIFIED: codebase `server/pyproject.toml` + `task/pyproject.toml`]

## Package Legitimacy Audit

> 本相位 **不安装** 外部包。slopcheck 已可用（v0.6.1），但对空候选集无需审计。

| Package | Registry | Age | Downloads | Source Repo | slopcheck | Disposition |
|---------|----------|-----|-----------|-------------|-----------|-------------|
| — | — | — | — | — | — | No new packages |

**Packages removed due to slopcheck [SLOP] verdict:** none  
**Packages flagged as suspicious [SUS]:** none

## Discretionary Defaults (auto-completed)

Planner 与 executor **直接采用**下列默认值（来自 CONTEXT Claude's Discretion，本 research 拍板）：

| 项 | 默认 | 理由 |
|----|------|------|
| Prompt 追加条件 | `knowledge_endpoint` 与 `user_token` 均非空 **且** `task_mode in {"plan", "execute"}` | explore / repo_summary 非编码交付路径；对齐 D-01「编码模式且 knowledge 已挂载」 |
| 报告模块路径 | `server/services/code_graph/impact_report.py` | 与 `detect_changes.py` / `impact.py` 同包；编排入口仍经 `run_detect_changes` |
| API 表面 | `async build_impact_report_section(*, repository, user, compare, base_ref=None) -> str` + 纯函数 `append_impact_report(description: str, section: str) -> str` | 幂等标记头 `## 影响面`；壳层只 append |
| 超时 | `CODE_GRAPH_IMPACT_REPORT_TIMEOUT_SECONDS = 30.0`（`django-environ`，与 `CODE_GRAPH_BUILD_WAIT_TIMEOUT_SECONDS` 命名族一致） | D-10 初值 |
| 体积软上限 | `CODE_GRAPH_IMPACT_REPORT_MAX_CHARS = 10240`（~10KB）；渲染时 top files=15、symbols/file=8、impact seeds=10 | D-08 区间中值 |
| Risk 聚合 | 对 `impacts[*].impact.risk_level` 取最严重；无 seed / 空 impacts → `LOW`；`summary.file_level_only` 或 `truncated` → 至少 `MEDIUM` 并写明「未展开」 | 信封无顶层 `risk_level`；展示用 `LOW/MEDIUM/HIGH/CRITICAL` 大写 |
| Stub `error_code` 映射 | 信封码透传（`repository_not_indexed`→`not_indexed` 可规范化为短码表）；`asyncio.TimeoutError`→`timeout`；`GraphAccessDenied` / 其它→`unavailable` | D-11；禁止细节泄漏 |
| CreatePRNode / `coding_graph` 确认 PR 路径 | **本相位不挂**（backlog）；成功标准只覆盖 `AICodingNode` + MCP | CONTEXT deferred + discretion |
| `mr_service.build_mr_description` / `create_mr_for_task` | **挂同一 `append`**（若该路径仍可达） | D-06 消第三条方言 |

## Architecture Patterns

### System Architecture Diagram

```text
[编码容器 agent]
    │  system prompt: _detect_changes_guidance (D-01)
    │  allowed: mcp__friday-knowledge__detect_changes (D-02)
    ▼
[task knowledge_tools HTTP + PAT]
    ▼
[DetectChangesView] ──► run_detect_changes ──► mirror/diff × Symbol × run_impact
    │                                              │
    │  (ok/fail 回容器；不阻断 turn / runner)        │
    ▼                                              │
[runner.py commit/push]  ←── 不读 detect_changes 结果 (D-04)
                                                       │
[建 MR — workflow]                                     │
  AICodingNode._create_mr_for_repo                     │
       │ body 拼装                                      │
       ▼                                               │
  build_impact_report_section ──wait_for(30s)──► run_detect_changes ◄──┘
       │ ok → ## 影响面 四段 / fail → stub
       ▼
  client.create_merge_request(description)

[建 MR — MCP]
  merge_request_service.create_merge_request / _draft_from_summary
       │
       ▼
  同一 build_impact_report_section + append_impact_report（幂等）
       ▼
  client.create_merge_request(description)
```

### Recommended Project Structure

```
task/core/
├── knowledge_tools.py          # MODIFY: +detect_changes schema（第 11 工具）
└── executor.py                 # MODIFY: _detect_changes_guidance + 条件追加

server/services/code_graph/
├── impact_report.py            # NEW: build + append + render + timeout/stub
├── detect_changes.py           # 只读消费（Phase 123）
└── impact.py                   # RiskLevel 枚举可 import 展示

server/services/code_graph_tools.py   # 只读：run_detect_changes
server/workflows/nodes/ai/coding.py   # MODIFY: _create_mr_for_repo
server/workflows/services/mr_service.py  # MODIFY: 消方言（若可达）
server/mcp_tools/merge_request_service.py # MODIFY: draft/create append
server/friday/settings.py             # MODIFY: timeout + max_chars env

task/tests/
├── test_knowledge_tools.py           # 白名单 11 + schema 字段
├── test_detect_changes_prompt.py     # NEW 或扩 test_openspec_prompt
└── test_claude_sdk_integration.py    # allowed_tools 计数

server/tests/services/code_graph/
├── test_impact_report.py             # NEW: formatter + stub + timeout + 体积
server/tests/workflows/
├── test_coding_impact_report.py      # NEW: _create_mr_for_repo fail-soft
server/tests/mcp_tools/
├── test_mr_impact_report.py          # NEW: MCP 路径 + 双链路对等哨兵
```

### Pattern 1: 条件追加 system prompt（照抄 openspec）

**What:** 独立静态 helper 返回可信中文指引；仅在 knowledge 可挂载且编码模式下拼到 base 后。  
**When to use:** DIFF-03。  
**Example:**

```python
# Source: task/core/executor.py::_openspec_guidance / _get_system_prompt（Phase 51）
def _detect_changes_guidance(self) -> str:
    return (
        "影响面自查（编码完成后、结束 turn 前）：\n"
        "- 若已挂载 friday-knowledge，调用 `detect_changes`："
        "`repository_id`=本任务仓 UUID，`compare`=当前功能分支"
        "（可选 `base_ref`=MR 目标分支，仅声明；勿传工作树 tip 当 base）。\n"
        "- 根据返回的受影响符号与风险决定是否继续修补；"
        "结果仅供决策参考。\n"
        "- 工具失败 / 未索引 / 配额用尽：记录原因并继续交付，不要重试刷屏；"
        "不要因为 HIGH/CRITICAL 而停止交付（提交由 Runner 负责）。"
    )

def _get_system_prompt(self) -> str:
    base = """..."""  # 既有
    parts = [base]
    if bool(self.config.follow_openspec):
        parts.append(self._openspec_guidance())
    if (
        self.config.knowledge_endpoint
        and self.config.user_token
        and self.config.task_mode in {"plan", "execute"}
    ):
        parts.append(self._detect_changes_guidance())
    return "\n\n".join(parts)
```

**仓库 UUID 可得性（实现注意）：** `task` 配置目前 **无** `repository_id` 字段；dispatch metadata 有 `repository_id` 但未必进 prompt。指引文案应指示 agent：从任务描述/方案中的仓 UUID 取值，未知时用已有 `lookup_project_by_branch` 解析——**本相位不强制新增 env 注入**（避免扩大 scope）；若执行中发现 agent 频繁缺 ID，可在 follow-up 加 `FRIDAY_TASK_REPOSITORY_ID`（非本相位成功标准）。 [VERIFIED: `task/core/config.py` 无 repository_id；`coding.py` metadata 含 repository_id]

### Pattern 2: 共享报告 + 幂等 append

**What:** 一处生成、两处挂接；标记头防重复。  
**When to use:** DIFF-04 / D-14。  
**Example:**

```python
# Source: 建议 server/services/code_graph/impact_report.py（本相位新增）
IMPACT_SECTION_MARKER = "## 影响面"

async def build_impact_report_section(*, repository, user, compare: str, base_ref: str | None = None) -> str:
    # started log → wait_for(run_detect_changes, timeout) → render or stub → completed/failed
    ...

def append_impact_report(description: str, section: str) -> str:
    if not section:
        return description or ""
    if IMPACT_SECTION_MARKER in (description or ""):
        return description  # 幂等
    base = (description or "").rstrip()
    return f"{base}\n\n{section}" if base else section
```

### Pattern 3: Fail-soft 挂点（对齐 pr_cross_reference）

**What:** 壳层 try/except 吞掉；报告 helper 内部已吞异常时仍返回 stub/空串。  
**When to use:** `_create_mr_for_repo` / `create_merge_request`。  
**Example:**

```python
# Source: workflows/services/pr_cross_reference.py:109-111（先例）
try:
    section = await build_impact_report_section(
        repository=repository,
        user=user,  # workflow: dispatch/initiated user；MCP: request.user
        compare=branch_name,
        base_ref=resolved_target,
    )
    body = append_impact_report(body, section)
except Exception:  # noqa: BLE001
    pass  # helper 内应已处理；此为最后兜底
```

### Anti-Patterns to Avoid

- **在壳层重写 impact / 解析 diff：** 违反 D-05；只调 `run_detect_changes`。
- **改 runner 硬门禁 / 读工具结果决定 commit：** 违反 D-04。
- **workflow 与 MCP 各写一套 markdown：** 违反 D-14；双链路哨兵会抓漂移。
- **失败静默省略（无 stub）：** 违反 D-11；reviewer 不知道系统尝试过。
- **把源码 / 堆栈 / token 写进 MR：** 违反 D-08 / D-11 / 脱敏规范。
- **改 `repo_router_v2.py` 或 `mcp/` submodule：** 违反 D-16。
- **新增产品级 kill-switch：** 违反 D-13。

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| 分支 diff × 符号交叠 × 批量 impact | 新算法 / webhook payload | `run_detect_changes` | Phase 123 已交付；水位锚定与 rename 契约已验 |
| 容器→server 鉴权与配额 | 新 MCP 通道 | 既有 knowledge PAT + 共享配额计数器 | AGENT-02 面已稳定 |
| MR 追加段 fail-soft | 自定义重试/事务 | `pr_cross_reference` 姿态 + stub | 成功标准 3 |
| 风险等级新公式 | 自造阈值 | `impacts[*].impact.risk_level`（`grade_risk`） | 122/123 确定性四级 |
| Prompt 注入动态仓名拼接不可信输入 | 字符串拼接外部文本 | 静态 `_detect_changes_guidance` | D-01 无注入面 |

**Key insight:** 本相位是「接线相位」——价值在挂点与 fail-soft 纪律，不在新算法。

## Common Pitfalls

### Pitfall 1: GraphAccessDenied / 异常冒泡阻断建 MR
**What goes wrong:** `run_detect_changes` 对 ACL 失败 **上抛** `GraphAccessDenied`（不折信封），若未 catch 会炸掉 `_create_mr_for_repo`。 [VERIFIED: `code_graph_tools.py:1140-1141` docstring + ACL 段]  
**Why it happens:** 编排层刻意让壳层翻译 ACL；MR 报告路径必须自己吞。  
**How to avoid:** `build_impact_report_section` 内层 `try/except` 覆盖 `GraphError` / `TimeoutError` / `Exception` → stub；壳层再兜底。  
**Warning signs:** 建 MR 测试出现 5xx / `mr_creation_error` 且堆栈含 `ensure_repository_readable`。

### Pitfall 2: 把 ARCHITECTURE 旧坐标当成挂点
**What goes wrong:** research Pattern 3 写 `_finalize_and_notify`，实际 description 在 `_create_mr_for_repo` 拼装。 [VERIFIED: `coding.py:2194-2219` vs `:1320-1331`]  
**Why it happens:** 收尾循环调用 `_create_mr_for_repo`；挂 finalize 会错过 body 或重复。  
**How to avoid:** 严格按 CONTEXT D-06 挂 `_create_mr_for_repo`（create 前）；保留的 `description` 字段已含影响面，供 cross-ref 回写。  
**Warning signs:** cross-ref 回写后影响面段丢失或重复。

### Pitfall 3: 白名单计数回归
**What goes wrong:** 多处测试硬编码 `len(KNOWLEDGE_TOOL_SCHEMAS) == 10`。 [VERIFIED: `test_blueprint_context_*.py`, `test_claude_sdk_integration.py`]  
**Why it happens:** 历史从 7→10 递增。  
**How to avoid:** 计划任务显式更新所有计数断言到 **11**，并在 `_LEGACY`/`_NEW` 列表模式旁追加 `detect_changes` 名字面量。  
**Warning signs:** task 测试红一片 `assert 10 == 11`。

### Pitfall 4: empty_diff_range / 未索引被当成「无影响」
**What goes wrong:** `ok=False, error_code=empty_diff_range|repository_not_indexed` 若渲染成空 Changes，reviewer 误读为「无影响」。  
**Why it happens:** 成功与失败外形不同。  
**How to avoid:** 整体 `ok=False` → D-11 stub（带 error_code）；仅 `ok=True` 走四段。  
**Warning signs:** MR 出现空的 `### Changes` 且无 Risk。

### Pitfall 5: 超时拖垮建 MR 延迟
**What goes wrong:** 大仓顺序 `run_impact` 可能 >30s。  
**Why it happens:** 123 对 seed 顺序 impact；阈值后虽截断，边缘仓仍慢。  
**How to avoid:** 硬 `asyncio.wait_for`；超时 stub；观测 `error_code=timeout` + `duration_ms`。  
**Warning signs:** MR 创建 P99 飙高、日志无 `impact_report_failed`。

### Pitfall 6: 幂等失败导致双段「## 影响面」
**What goes wrong:** `_draft_from_summary` 已附报告，`create_merge_request` 再附。  
**How to avoid:** 统一经 `append_impact_report` 检查标记头。  
**Warning signs:** MR body 出现两个 `## 影响面`。

## Code Examples

### DetectChangesRequestSerializer 字段（task schema 对照）

```python
# Source: server/mcp_tools/serializers.py:222-238 [VERIFIED]
# required: repository_id (UUID), compare (str)
# optional: base_ref, max_depth(1..3 default 3), min_confidence(0..1 default 1.0),
#           include_low_confidence(default False), limit(1..200 default 200)
# validate: compare/base_ref 禁 ".." 与控制字符；格式 SAFE_COMPARE 或 40-hex SHA
```

### 成功信封 → 四段字段映射

| 小节 | 信封来源 [VERIFIED: `run_detect_changes` 返回 `code_graph_tools.py:1418-1432`] |
|------|------------------------------------------------------------------|
| Changes | `files[]`：`path`、`file_summary.changeType`、`symbols[].changeType/lines_changed/file_line`；`summary.file_level_only` 时只列文件 |
| Affected | `impacts[]`：成功项取 `impact.groups`（深度分组）+ `impact.summary`；失败项列 `impact_error`；`summary.truncated/not_expanded` 计数 |
| Risk | 聚合 `risk_level`；`staleness.as_of` / `behind_commits` / `declaration`；`graph.degraded` |
| Recommendations | 规则化短句（复核 d1、重索引、展开截断）；`affected_processes` 固定空——写「执行流叙事待 Phase 126」或省略编造 |

### 观测事件骨架

```python
# Source: 对齐 code_graph_tools.run_detect_changes 观测姿态 + D-15
initiated_by_user_id = str(user.id) if user is not None and getattr(user, "id", None) is not None else "system"
logger.info(
    "impact_report_started",
    component="code_graph",
    category="caller",
    repository_id=repository_id,
    initiated_by_user_id=initiated_by_user_id,
)
# ...
logger.info(
    "impact_report_completed",
    component="code_graph",
    category="caller",
    repository_id=repository_id,
    initiated_by_user_id=initiated_by_user_id,
    duration_ms=duration_ms,
    section_chars=len(section),
    ok=True,
)
```

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| detect_changes 仅 MCP/对话可调 | + 容器 knowledge 白名单 | Phase 124 | DIFF-03 |
| MR 描述无图影响面 | 建 MR 时服务端四段报告 | Phase 124 | DIFF-04；对标 GitNexus 落点但非硬门禁 |
| 硬门禁 pre-commit | v1 提示不阻断 | CONTEXT D-04 | 保护编码链吞吐 |

**Deprecated/outdated:**
- 依赖 webhook MR diff 做主通路：已被 Phase 123 mirror tree-to-tree 否定；本相位继续不走 webhook。

## Assumptions Log

| # | Claim | Section | Risk if Wrong |
|---|-------|---------|---------------|
| A1 | 任务描述/方案通常含 `repository_id`，agent 可填工具参数；短期不需新 env | Pattern 1 | agent 调工具缺 ID → 自查失败但 MR 报告仍由服务端保证（DIFF-04 不受影响） |
| A2 | `create_mr_for_task` / `build_mr_description` 仍有可达调用方，值得挂接消方言 | Discretionary Defaults | 若已死代码，多一次改动无害 |
| A3 | Risk 展示用大写四级与信封小写 `risk_level` 映射即可满足 DIFF-04 字面 | Discretionary Defaults | 验收文案微调 |

**若表非空：** A1 为最大产品风险但被 DIFF-04 服务端保证兜住；planner 无需为人确认阻塞。

## Open Questions (RESOLVED)

无阻塞问题。下列执行期注意点已由计划钉死：

1. **workflow 路径的 `user` 从哪取** — RESOLVED → `124-03` Task 1  
   - What we know: `run_detect_changes` 需要 `user` 做 ACL；dispatch 有 `dispatch_user` / `task_token_user_id`。  
   - Resolution: `_finalize_and_notify` 传入 `await self._resolve_dispatch_user(context)` 到 `_create_mr_for_repo(user=...)`；缺失则 `user=None` → helper stub `unavailable`（仍 fail-soft）。`mr_service.create_mr_for_task` 取 task 关联用户（有则传，无则 None→stub）。

2. **MCP `create_merge_request` 显式 description 已含自定义结构** — RESOLVED → `124-03` Task 2  
   - Resolution: 仅经 `append_impact_report` 按 `## 影响面` 标记头幂等 append；已含则不重复；不重排既有章节。`work_item_execution_service` 调用点传 `user=initiating_user`。

## Environment Availability

| Dependency | Required By | Available | Version | Fallback |
|------------|------------|-----------|---------|----------|
| uv | server/task 测试 | ✓ | 0.11.8 | — |
| Python | runtime | ✓ | 3.14.6 | — |
| pytest-django / pytest-asyncio | Validation | ✓（pyproject） | pin in repo | — |
| Qdrant / 真索引仓 | 本相位单测 | 不需要 | — | mock `run_detect_changes` / 既有 orchestrator fixtures |
| 新 PyPI/npm 包 | — | N/A | — | 不安装 |

**Missing dependencies with no fallback:** none  
**Missing dependencies with fallback:** none  

Step 2.6: 外部服务非硬依赖；单测 mock 编排入口即可。

## Validation Architecture

### Test Framework

| Property | Value |
|----------|-------|
| Framework | pytest + pytest-asyncio + pytest-django（server）；pytest（task） |
| Config file | `server/pyproject.toml`（`testpaths=tests`, `asyncio_mode=auto`）；`task/pyproject.toml` |
| Quick run command | `cd server && GALAXY_CACHE_WARM_ON_STARTUP=False GRAPH_BUILD_ORPHAN_RECONCILE_ON_STARTUP=False uv run pytest tests/services/code_graph/test_impact_report.py tests/workflows/test_coding_impact_report.py tests/mcp_tools/test_mr_impact_report.py -q --reuse-db` |
| Full suite command（本相位相关） | 上列 + `cd task && uv run pytest tests/test_knowledge_tools.py tests/test_openspec_prompt.py tests/test_detect_changes_prompt.py tests/test_claude_sdk_integration.py tests/test_blueprint_context_tools_schema.py -q` |

### Phase Requirements → Test Map

| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| DIFF-03 | `detect_changes` ∈ `KNOWLEDGE_TOOL_SCHEMAS`；schema 含 `repository_id`/`compare`；allowed 前缀 `mcp__friday-knowledge__detect_changes` | unit | `cd task && uv run pytest tests/test_knowledge_tools.py -k detect_changes -q` | ❌ Wave 0（扩既有文件） |
| DIFF-03 | knowledge 可挂载 + plan/execute → prompt 含自查关键词；explore / 无 knowledge → 不追加；不改 runner | unit | `cd task && uv run pytest tests/test_detect_changes_prompt.py -q` | ❌ Wave 0 |
| DIFF-03 | 工具计数 11；集成 allowed_tools 含新名 | unit | `cd task && uv run pytest tests/test_claude_sdk_integration.py tests/test_blueprint_context_tools_schema.py -q` | ✅ 文件在，需改断言 |
| DIFF-04 | formatter：fixture 信封 → 四段标题；截断注 `truncated`；无源码正文 | unit | `cd server && uv run pytest tests/services/code_graph/test_impact_report.py -q --reuse-db` | ❌ Wave 0 |
| DIFF-04 | `ok=False` / timeout / ACL → stub 含稳定 `error_code`；不抛 | unit | 同上 | ❌ Wave 0 |
| DIFF-04 | `_create_mr_for_repo`：mock `run_detect_changes` 失败仍 `create_merge_request` 且 description 含 stub | unit | `cd server && uv run pytest tests/workflows/test_coding_impact_report.py -q --reuse-db` | ❌ Wave 0 |
| DIFF-04 | MCP `create_merge_request` / draft 同 helper；幂等不双段 | unit | `cd server && uv run pytest tests/mcp_tools/test_mr_impact_report.py -q --reuse-db` | ❌ Wave 0 |
| DIFF-04 / D-14 | 同一 fixture 下 workflow 拼装段与 MCP 拼装段规范化后一致 | unit sentinel | `test_mr_impact_report.py::test_workflow_mcp_impact_section_parity` | ❌ Wave 0 |
| D-15 | 事件名静态字面量 / component / category / `initiated_by_user_id`（可 AST 或调用断言） | unit | `test_impact_report.py -k observability` | ❌ Wave 0 |

### Sampling Rate

- **Per task commit:** 上表 Quick run（目标 <30s，mock 编排）
- **Per wave merge:** Quick run + task 白名单/prompt 套件
- **Phase gate:** 相关套件全绿后 `/gsd-verify-work`；不要求生产仓人工点 MR（CONTEXT specifics）

### Wave 0 Gaps

- [ ] `server/tests/services/code_graph/test_impact_report.py` — formatter / stub / timeout / 体积 / 观测
- [ ] `server/tests/workflows/test_coding_impact_report.py` — `_create_mr_for_repo` fail-soft + 段附加
- [ ] `server/tests/mcp_tools/test_mr_impact_report.py` — MCP 路径 + D-14 对等哨兵
- [ ] `task/tests/test_detect_changes_prompt.py` — prompt 条件追加（可扩 `test_openspec_prompt.py`）
- [ ] 更新既有 task 计数断言 10→11（`test_knowledge_tools.py` docstring/断言、`test_blueprint_context_*`、`test_claude_sdk_integration.py`）

*(既有 `test_detect_changes_*` / orchestrator 套件不重复测内核；本相位 mock `run_detect_changes` 即可。)*

## Security Domain

### Applicable ASVS Categories

| ASVS Category | Applies | Standard Control |
|---------------|---------|-----------------|
| V2 Authentication | yes（容器 PAT / MCP） | 既有 task token + MCP PAT fail-closed；本相位不放宽 |
| V3 Session Management | no | — |
| V4 Access Control | yes | `run_detect_changes` → `ensure_repository_readable`；报告路径吞 ACL→stub，不绕过鉴权读私仓数据进 MR |
| V5 Input Validation | yes | 复用 `DetectChangesRequestSerializer` 字段表；task schema 对照；MR stub 禁止异常原文 |
| V6 Cryptography | no | — |

### Known Threat Patterns for coding-chain / impact report

| Pattern | STRIDE | Standard Mitigation |
|---------|--------|---------------------|
| PAT / token 进日志或 MR | Information Disclosure | knowledge_tools 既有脱敏；报告路径 `redact_secrets_in_text`；stub 只用稳定 error_code |
| Prompt 注入（动态拼接不可信文本） | Tampering | `_detect_changes_guidance` 静态字面量（D-01） |
| 通过 MR 报告泄露被 exclusion 的路径/源码 | Information Disclosure | 不调用 `include_content`；只渲染 123 信封已 exclusion 后的摘要；体积 top-N |
| ACL 失败被折成「无影响」 | Elevation / Spoofing | stub `unavailable`/`not_indexed`，禁止空成功四段 |
| 超时 DoS 拖垮建 MR | Denial of Service | 30s `wait_for`；不重试刷屏 |

## Sources

### Primary (HIGH confidence)

- `.planning/phases/124-coding-chain/124-CONTEXT.md` — D-01..D-16 锁定决策
- `.planning/REQUIREMENTS.md` — DIFF-03 / DIFF-04
- `server/services/code_graph_tools.py::run_detect_changes` — 信封与 ACL/超时语义
- `server/mcp_tools/serializers.py::DetectChangesRequestSerializer` — task schema 对照
- `server/mcp_tools/views.py::DetectChangesView` — PAT MCP 面已就绪
- `task/core/knowledge_tools.py` / `task/core/executor.py` — 白名单与 prompt 先例
- `server/workflows/nodes/ai/coding.py::_create_mr_for_repo` — workflow 挂点
- `server/mcp_tools/merge_request_service.py` — MCP 挂点
- `server/workflows/services/pr_cross_reference.py` — fail-soft 先例
- `.planning/research/ARCHITECTURE.md` Pattern 3 — 编码链挂点意图（坐标以 CONTEXT/代码为准）
- `.planning/phases/123-detect-changes/123-VERIFICATION.md` — Phase 123 已验契约
- `.cursor/rules/observability-logging.mdc` — 观测强制项

### Secondary (MEDIUM confidence)

- `.planning/research/SUMMARY.md` — Phase 124 交付定义（白名单+prompt+两处 MR）
- task 测试硬编码工具数 10 — 扩容时必改

### Tertiary (LOW confidence)

- A1：agent 能否稳定拿到 `repository_id`（见 Assumptions Log）

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH — 零新依赖；消费已验证的 Phase 123 API
- Architecture: HIGH — 挂点与文件在代码中核实；CONTEXT 与实现坐标一致
- Pitfalls: HIGH — ACL 上抛、计数回归、幂等双段均有代码证据

**Research date:** 2026-08-10  
**Valid until:** 2026-09-09（内部接线相位，栈稳定 30 天）
