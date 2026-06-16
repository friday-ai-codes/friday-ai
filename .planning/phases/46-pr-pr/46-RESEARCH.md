# Phase 46: 多仓融合 PR + 跨仓 PR 关联 - Research

**Researched:** 2026-06-16
**Domain:** 后端工作流收尾收口（多仓 MR/PR 创建 + 跨仓 cross-ref + 方案/工作项可追溯），纯 Python/Django async
**Confidence:** HIGH（全部基于既有代码实测，无新外部依赖、无新架构）

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions

> 基础设施 + 接口决策 phase——以下为「推荐 / 最安全默认」技术决策，autonomous 模式已全部 AUTO-ACCEPT 推荐项，均在 the agent's Discretion 范围内。Planner 可在 PLAN.md 细化，但应保持「挂既有收尾收口、走既有 git client + aresolve_git_token、各仓 default_branch 独立解析、复用既有 cross-ref 模式、对空/单仓零回归、不造两套」的方向。

**Area 1：各仓 target_branch 解析（PR-01）**
- **D-01 target_branch 权威源**：各仓 PR/MR `target_branch` = **该仓自己的** `Repository.default_branch`（每仓独立），fallback 链 `repository.default_branch → 现有 base_branch（node 级）→ "main"`。`execution_plan[]` 每项仅 `{repository_id, coding_instruction, dependencies}`，**不含** per-repo target_branch 字段，故权威源为 `Repository.default_branch`。
- **D-02 修复落点**：`AICodingNode._create_mr_for_repo` 现签名已收 `repository`（仓对象）+ `base_branch`（共用），新增/改为以 `repository.default_branch` 为 `target_branch` 优先解析（参数兜底）。`_finalize_and_notify` 调用处无须为每仓预解析（仓对象已在手）。保持 `MRCreateRequest(source_branch=branch_name, target_branch=<per-repo resolved>)`。
- **D-03 source_branch（head）**：维持现状单一 `branch_name`（多仓同名特性分支，v0.8 既有约定）。本 phase **不**改 head 分支策略。
- **D-04 零回归命门**：单仓 / 所有仓 default_branch 恰等于现 base_branch 时，行为与 Phase 45 逐字等价。仅当多仓 default_branch 不一致时才体现修复价值。

**Area 2：跨仓 cross-ref + 可追溯（PR-02）**
- **D-05 cross-ref 触发条件**：`_finalize_and_notify` 中**成功创建 MR 的仓 ≥ 2** 时才做 cross-ref（对齐 `CreatePRNode` 的 `len(successful) > 1` 守门）。失败/无凭证仓不进 cross-ref 名单。
- **D-06 cross-ref 内容**：每个成功 PR 的描述追加「## 关联 PR」段，列出**其它**兄弟仓 PR 的 `- [repo_name](pr_url)`（复用 `CreatePRNode._generate_cross_reference_section` 语义）。
- **D-07 可追溯段（traceability）**：PR 描述含「关联方案 / 工作项」——经 `plan_data.plan_version_id` 反查 `PlanVersion → TechnicalPlan → work_item`（async ORM 安全），渲染 `TechnicalPlan` 标识 + `WorkItem` 飞书链接（若 `metadata.feishu_url`/`feishu_title` 在手则优先用之）。取不到 → 仅省略该段（fail-soft，不阻塞 PR 创建）。
- **D-08 cross-ref 实现模式**：复用 `CreatePRNode` 已验证的「先批量建 MR → 再回写描述」两段式：建完所有 done 仓 MR 后，对成功名单做一次回写（GitHub `repo.get_pull(id).edit(body=...)` / GitLab `project.mergerequests.get(id).save()`，经 `asyncio.to_thread` 包同步 SDK 调用）。回写经 `aresolve_git_token` 重取 token + `get_git_platform_client`。
- **D-09 helper 复用 / 去重**：倾向把 cross-ref section 生成 + 回写逻辑提取为**可复用 helper**（如 `workflows/services/` 下 `pr_cross_reference.py` 或复用 `mr_service.py`），供 `CreatePRNode`（手动节点）与 `AICodingNode._finalize_and_notify`（wave 收尾）共用，消除双份漂移。若提取成本/风险偏高，planner 可在 the agent's Discretion 内选择 wave 路径内联镜像既有模式（但须显式标注同源）。
- **D-10 fail-soft / 不回退**：cross-ref 回写任一环失败仅 `logger.warning` 降级（PR 已成功创建，cross-ref 是增强非命门）；缺凭证、平台未知、单 PR 回写异常都不让收尾失败、不回灌容器回调 5xx。

**Area 3：测试与零回归（验收硬项）**
- **D-11 PR-01 单测**：构造多仓（repo A default_branch="develop"、repo B default_branch="release/x"），断言各仓 MR 请求的 `target_branch` = 各仓自己的 default_branch（**非** 第一个仓的 / 非 "main"）。mock git client 捕获 `MRCreateRequest`。
- **D-12 PR-02 cross-ref 单测**：`_generate_cross_reference_section`（或复用 helper）纯函数——多 PR → 段含各兄弟仓链接、排除自身；单 PR → 空段。回写路径以 mock client（`_get_repo`/`_get_project`）断言 `edit`/`save` 被调用且 body 含兄弟链接 + 方案/工作项追溯段。
- **D-13 可追溯单测**：mock `PlanVersion → TechnicalPlan → work_item` 链，断言 PR body 含 TechnicalPlan 标识 / WorkItem 飞书链接；链断（取不到）→ 省略追溯段且不抛、PR 仍创建。
- **D-14 零回归断言**：单仓收尾 → 无 cross-ref（不调回写）、target_branch = 该仓 default_branch、输出结构与 Phase 45 一致；所有仓 default_branch 同值 → target_branch 与现 base_branch 等价。
- **D-15 fail-soft / 幂等**：cross-ref 回写抛错 → 收尾仍 `completed`、PR 仍在 output；无凭证仓不进 cross-ref；重复 finalize（重复回调）经既有 wave gating（aadvance 幂等）不重复创建 MR。

### Claude's Discretion
- cross-ref 段与可追溯段的中文文案 / Markdown 结构细节、是否合并为单段「## 关联」由 planner 按可读性定。
- helper 提取的具体模块落点（`workflows/services/pr_cross_reference.py` vs 扩展 `mr_service.py`）与是否同时重构 `CreatePRNode` 复用同 helper 由 planner 按最小 diff / 风险定。
- target_branch fallback 链细节（是否保留 node 级 base_branch 作为第二兜底）、是否顺带发 `coding.pr.created` / `coding.pr.cross_referenced` trace 事件由 planner 决定，倾向低成本接通。
- 是否给 git 平台 client 增公共「更新 MR 描述」抽象方法（替代私有 `_get_repo`/`_get_project` 访问）由 planner 权衡：倾向本 phase 沿用既有私有模式保最小 diff，公共抽象留 backlog。

### Deferred Ideas (OUT OF SCOPE)
- 编码遇阻 question 抛人（HITL）→ Phase 47（HITL-01）。
- 全自动回溯重规划 → 里程碑显式非目标 / backlog。
- per-repo head（source）分支策略（多仓不同特性分支名）→ backlog（本 phase head 维持单一 branch_name）。
- git 平台 client 公共「更新 MR 描述」抽象方法 → backlog（本 phase 沿用既有私有模式）。
- PR 自动合并（`MergePRNode`）→ 非本 phase（创建 + 关联，不合并）。
- chat 编码入口（`coding_session_service`）的 cross-ref 接线 → follow-up。
- 真实 runner + Docker 容器端到端 PR 创建/cross-ref 验收 → 既有 deferred（本地无法闭环，本 phase 以 mock git client 边界覆盖）。
</user_constraints>

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| PR-01 | 多仓产出关联的 PR/MR，各仓 diff base 用各仓正确的 `target_branch`（非假设 master） | `_create_mr_for_repo` 已持有 `repository` 对象（`coding.py:1660`），改 `target_branch=base_branch`（`coding.py:1708`）为 per-repo `repository.default_branch` 解析；蓝本见 `mr_service.create_mr_for_task`（`target_branch or repository.default_branch`，`mr_service.py:159`） |
| PR-02 | 跨仓 PR 关联（cross-ref）——同一方案多仓 PR 互相引用，可追溯到同一 `TechnicalPlan`/`WorkItem` | cross-ref 蓝本 `CreatePRNode._generate_cross_reference_section`（`pr.py:285`）+ `_add_cross_references`（`pr.py:312`）；追溯链 `plan_data.plan_version_id → PlanVersion → TechnicalPlan.work_item`（`technical_plan.py:55`、`repo_coding_task.py:45`）；挂载点 `_finalize_and_notify`（`coding.py:1070`） |
</phase_requirements>

## Summary

本 phase 是纯后端、**零新依赖、零新模型、零迁移**的收口增强：在已存在的多仓 wave 编码收尾段 `AICodingNode._finalize_and_notify`（`coding.py:1070`）里补两件事——(1) PR-01：每仓 MR 的 `target_branch` 用各仓自己的 `Repository.default_branch`（而非现状取第一个仓 default_branch 当全局 `base_branch` 对所有仓共用）；(2) PR-02：所有 done 仓 MR 批量建完后，对成功名单（≥2 仓）做一次描述回写，追加「关联 PR」cross-ref 段 + 「关联方案/工作项」可追溯段。

两处修复都有**已验证的既有蓝本**可直接镜像/复用，无需任何新架构或第二套创建/回写路径：
- PR-01 蓝本 = `mr_service.create_mr_for_task`（`mr_service.py:159` 已是 `target_branch or repository.default_branch` 范式）。
- PR-02 蓝本 = `CreatePRNode._generate_cross_reference_section`（`pr.py:285`，纯函数）+ `_add_cross_references`（`pr.py:312`，GitHub `pr.edit(body=)` / GitLab `mr.save()` 经 `asyncio.to_thread`）。

关键验证结论：`_create_mr_for_repo` 已在签名里持有 `repository` 对象（`coding.py:1660`），所以 per-repo target_branch 解析是**纯局部改动**（一行参数解析），调用处 `_finalize_and_notify` 无须改。`MRCreateResult.mr_id` 对 GitHub = `pr.number`、对 GitLab = `mr.iid`（`github_client.py:145` / `gitlab_client.py:159`），与回写时 `int(pr_id)` 喂给 `get_pull(number)` / `mergerequests.get(iid)` 一致——cross-ref 回写的 `pr_id` 复用无歧义。

**Primary recommendation:** PR-01 在 `_create_mr_for_repo` 内一行解析 `target_branch = repository.default_branch or base_branch or "main"`；PR-02 提取一个共用 helper 模块 `workflows/services/pr_cross_reference.py`（含纯函数 cross-ref section 生成 + 异步回写 + 追溯段渲染），在 `_finalize_and_notify` 批量建 MR 后调用，全程 fail-soft（`logger.warning` 降级，绝不阻塞收尾或回灌回调 5xx）。

## Architectural Responsibility Map

| Capability | Primary Tier | Secondary Tier | Rationale |
|------------|-------------|----------------|-----------|
| 各仓 target_branch 解析（PR-01） | API/Backend（workflow 节点逻辑） | DB（读 `Repository.default_branch`） | 解析逻辑属 MR 创建业务；权威值来自 DB 的仓级字段，仓对象已在手无需额外查询 |
| 批量创建 MR/PR | API/Backend（git_platform service） | 外部 git 平台（GitHub/GitLab API） | 走既有 `get_git_platform_client` → `create_merge_request`，平台差异封装在 client |
| cross-ref 回写描述 | API/Backend（pr_cross_reference helper） | 外部 git 平台 API | 创建后副作用，经既有私有 `_get_repo`/`_get_project` + `asyncio.to_thread` |
| 方案/工作项可追溯渲染 | API/Backend（async ORM 读链） | DB（PlanVersion/TechnicalPlan/WorkItem） | 纯读链 + 字符串渲染，无写入，async ORM 经 `afirst`/`*_id` 标量 |
| 凭证解析 | API/Backend（git_credentials） | DB（GitCredential/GitInstanceCredential 加密列） | 已统一在 `aresolve_git_token`，本 phase 只调用不改 |

## Standard Stack

### Core

**本 phase 不引入任何新外部依赖**——全部复用既有运行时栈与既有内部 service。下表是「将被消费的既有组件」清单（非新增）。

| 组件 | 出处 | 用途 | 为何用它 |
|------|------|------|----------|
| `aresolve_git_token(repository)` | `services/git_credentials.py:100` | per-repo token（per-repo → host 池 fallback，缺凭证返回 None） | 唯一取 token 入口（Phase 26 REPO-01 硬约束，禁另写） |
| `get_git_platform_client(repo, token)` | `services/git_platform/__init__.py:114` | 平台 client 工厂（GitHub/GitLab） | 既有唯一 client 工厂，封装 URL 解析 |
| `MRCreateRequest` / `MRCreateResult` | `services/git_platform/models.py:8/19` | MR 创建请求/结果 dataclass | 既有契约，含 `target_branch` 字段 |
| `client.create_merge_request(req)` | `git_platform/base.py:35`（抽象） | 创建 MR/PR | 既有唯一创建入口 |
| `client._get_repo()` / `client._get_project()` | `github_client.py:47` / `gitlab_client.py:71` | cross-ref 回写时取底层 SDK 对象 | 既有 cross-ref 私有访问模式（`CreatePRNode` 已用） |
| `asyncio.to_thread(...)` | stdlib | 包同步 git SDK（PyGithub/python-gitlab）调用 | 既有约定，规避阻塞 event loop |
| `PlanVersion` / `TechnicalPlan` / `WorkItem` | `delivery/models/` | 可追溯链 ORM | 既有 canonical 脊柱 |
| `structlog.get_logger()` | 既有 | fail-soft 降级日志 | 既有结构化日志约定 |

### Supporting

| 组件 | 出处 | 用途 | 何时用 |
|------|------|------|--------|
| `_finalize_and_notify` | `coding.py:1070` | 唯一收尾收口（单 wave / wave 全终态共用） | PR-01/02 唯一挂载点 |
| `_create_mr_for_repo` | `coding.py:1658` | 单仓 MR 创建 | PR-01 一行解析修复点 |
| `workflows/services/__init__.py` | `workflows/services/__init__.py:1` | barrel 导出 | 若新建 `pr_cross_reference.py` 经此导出 |
| `mr_service.build_mr_description` | `mr_service.py:13` | 飞书段/技术摘要/文件段渲染 | 可借鉴追溯段渲染风格（`## 关联飞书工作项`） |

### Alternatives Considered

| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| 新建共用 helper `pr_cross_reference.py`（D-09 倾向） | 在 wave 路径内联镜像 `CreatePRNode` 模式 | 内联省去重构 `CreatePRNode` 的 blast radius，但留双份漂移风险；D-09 已允许 planner 按最小 diff 二选一（内联须显式标注同源） |
| 私有 `_get_repo`/`_get_project` 访问回写 | 给 `GitPlatformClient` 加公共 `update_mr_description` 抽象方法 | 公共抽象更干净但需改 base + 两子类（blast radius 大），D-08/Discretion 倾向本 phase 沿用私有保最小 diff，公共抽象留 backlog |
| `target_branch = repository.default_branch or base_branch or "main"` | 在 `execution_plan[]` 加 per-repo target_branch 字段 | execution_plan 项无此字段（D-01），加字段会改上游 schema（v0.7 编排，超本 phase scope）；权威源就是 `Repository.default_branch` |

**Installation:** 无需安装任何包（纯内部代码改动）。

**Version verification:** N/A — 无新增依赖。既有运行时：Python 3.14、Django 5.1+（async ORM）、PyGithub / python-gitlab（既有 git_platform client 已用，本 phase 不升级）。

## Package Legitimacy Audit

> 本 phase **不安装任何外部包**。无 npm/PyPI/crates 新增项。Package Legitimacy Gate 不适用（no external installs）。所有被消费组件均为仓库内既有模块，已在生产路径验证。

| Package | Registry | Disposition |
|---------|----------|-------------|
| （无新增） | — | N/A — 纯内部代码复用 |

**Packages removed due to slopcheck [SLOP] verdict:** none
**Packages flagged as suspicious [SUS]:** none

## Architecture Patterns

### System Architecture Diagram

```text
容器回调 (_resume_after_containers)
        │
        ├── wave 模式 (plan_version_id 非空) ──► _resume_wave
        │                                          │ aadvance_coding_waves 判 gate
        │                                          ├─ waiting  → 重挂起
        │                                          ├─ dispatch → 派下一 wave + waiting_event
        │                                          └─ all_terminal → _finalize_wave
        │                                                              │ 从 DB(RepoCodingTask) 重算 done/failed
        └── legacy 模式 (无 plan_version_id) ──► _resume_legacy
                                                   │ 从 pending_sessions 查 done/failed
                                                   ▼
                                ┌──────── _finalize_and_notify (唯一收口) ────────┐
                                │                                                  │
                                │  for repo in succeeded:                          │
                                │    _create_mr_for_repo(repository, base_branch)  │  ◄── PR-01 修复点：
                                │      token = aresolve_git_token(repo)            │      target_branch =
                                │      client = get_git_platform_client(repo,tok)  │      repo.default_branch
                                │      create_merge_request(MRCreateRequest(...))  │      ┘  (per-repo)
                                │                                                  │
                                │  ── 新增 PR-02 段（成功仓 ≥ 2 时）──             │
                                │  traceability = render_traceability(             │  ◄── plan_version_id →
                                │      plan_data.plan_version_id)  (fail-soft)     │      PlanVersion →
                                │  add_cross_references(successful_mrs,             │      TechnicalPlan →
                                │      traceability)  (fail-soft, ≥2 守门)         │      WorkItem
                                │    per PR: _get_repo().get_pull(id).edit(body)   │
                                │           / _get_project().mr.get(id).save()     │
                                │                                                  │
                                │  _send_result_notification (飞书卡片)            │
                                │  _build_output → NodeResult(completed)           │
                                └──────────────────────────────────────────────────┘
```

### Recommended Project Structure

```text
server/workflows/
├── nodes/ai/coding.py              # 改: _create_mr_for_repo (PR-01) + _finalize_and_notify (PR-02 调用)
├── nodes/git/pr.py                 # 可选改: CreatePRNode 复用新 helper（Discretion，可不动）
└── services/
    ├── __init__.py                 # 改: barrel 导出 pr_cross_reference 符号
    ├── mr_service.py               # 不改（追溯段渲染可借鉴）
    └── pr_cross_reference.py       # 新增（D-09 倾向）: cross-ref section 生成 + 回写 + 追溯渲染
server/tests/
├── test_coding_wave.py            # 既有 wave 测试 harness 可复用（mock 边界范式）
├── test_batch_pr.py               # 既有 cross-ref 测试范式（纯函数 + mock client）
└── test_pr_cross_reference.py     # 新增: helper 单测（PR-01/02 + fail-soft + 零回归）
```

### Pattern 1: per-repo target_branch 解析（PR-01）

**What:** 在 `_create_mr_for_repo` 内用仓对象自己的 `default_branch` 解析 `target_branch`，参数 `base_branch` 降级为兜底。
**When to use:** 多仓 MR 创建，各仓目标分支可能不同。
**Example（镜像 `mr_service.py:159` 已验证范式）:**

```python
# Source: server/workflows/services/mr_service.py:157-163 (已验证范式)
request = MRCreateRequest(
    source_branch=branch_name,
    target_branch=target_branch or repository.default_branch,  # per-repo 权威
    title=title,
    description=description,
    reviewer_usernames=reviewers,
)
```

PR-01 落到 `_create_mr_for_repo`（`coding.py:1706`）的等价改法：

```python
# 改前 (coding.py:1706-1712)：target_branch=base_branch 对所有仓共用 → PR-01 病根
# 改后：各仓独立解析，base_branch 降为 node 级兜底（D-01 fallback 链）
resolved_target = repository.default_branch or base_branch or "main"
request = MRCreateRequest(
    source_branch=branch_name,
    target_branch=resolved_target,
    title=plan_title,
    description=body,
    reviewer_usernames=[],
)
```

零回归命门（D-04）：当所有仓 `default_branch` == 现 `base_branch`（如全是 "main"），`resolved_target` 逐字等于现值。

### Pattern 2: create-all-then-update-each cross-ref（PR-02）

**What:** 先批量创建全部 MR，收集成功结果，再对成功名单（≥2）逐个回写描述追加兄弟链接 + 追溯段。
**When to use:** 同批多仓 PR 需互相引用——必须先建完才知道彼此 URL。
**Example（镜像 `pr.py:312-418` 已验证范式）:**

```python
# Source: server/workflows/nodes/git/pr.py:373-383 (已验证 cross-ref 回写)
pr_id = result.get("pr_id", "")
if hasattr(client, "_get_repo"):          # GitHub: pr_id = pr.number
    repo_obj = client._get_repo()
    pr = await asyncio.to_thread(repo_obj.get_pull, int(pr_id))
    await asyncio.to_thread(pr.edit, body=new_body)
elif hasattr(client, "_get_project"):     # GitLab: pr_id = mr.iid
    project = client._get_project()
    mr = await asyncio.to_thread(project.mergerequests.get, int(pr_id))
    mr.description = new_body
    await asyncio.to_thread(mr.save)
else:
    logger.warning("cross_reference_unknown_platform", ...)
    return pr_url, False
```

纯函数 cross-ref 段生成（`pr.py:285-310`，直接可提取共用）：

```python
# Source: server/workflows/nodes/git/pr.py:299-310 (已验证纯函数)
other_prs = [r for r in all_successful_results if r.get("pr_url") != current_pr_url]
if not other_prs:
    return ""
lines = ["\n---", "## 关联 PR", ""]  # 中文文案由 planner 定（Discretion）
for pr in other_prs:
    lines.append(f"- [{pr.get('repository_name', 'unknown')}]({pr.get('pr_url', '')})")
return "\n".join(lines)
```

### Pattern 3: async ORM 安全读追溯链（PR-02 / D-07）

**What:** 从 async 收尾上下文读 `plan_version_id → PlanVersion → TechnicalPlan → WorkItem`，全程用 `afirst()` / `*_id` 标量，绝不裸触同步 lazy-FK。
**When to use:** 渲染追溯段。
**Example:**

```python
# Source: 镜像 coding.py:370 (PlanVersion.objects.filter(id=...).afirst()) 既有范式
from delivery.models import PlanVersion, TechnicalPlan  # lazy import 防循环

pv = await PlanVersion.objects.filter(id=plan_version_id).afirst()
if pv is None:
    return ""  # fail-soft：省略追溯段
# TechnicalPlan ← PlanVersion.plan（FK），用 plan_id 标量再查，规避 lazy-FK
tp = await TechnicalPlan.objects.filter(id=pv.plan_id).afirst()
if tp is None:
    return ""
# WorkItem ← TechnicalPlan.work_item（nullable FK），用 work_item_id 标量
wi = None
if tp.work_item_id:
    from delivery.models import WorkItem
    wi = await WorkItem.objects.filter(id=tp.work_item_id).afirst()
# 渲染：TechnicalPlan 标识 + WorkItem 飞书三元组/链接
```

> ⚠️ `WorkItem` **无直接 feishu_url 字段**（`work_item.py:32-89`），仅存三元组 `(feishu_project_key, work_item_type, work_item_id)`。飞书链接需从三元组**构造**，或优先用 `plan_data`/`metadata.feishu_url`（若 planner 确认其在 wave 路径可达）。见 Open Questions Q1。

### Anti-Patterns to Avoid

- **对所有仓共用单一 base_branch 当 target_branch**（PR-01 病根，`coding.py:317-319` + `1708`）：多仓 default_branch 不一致时把 MR 打到错误目标分支。改为 per-repo 解析。
- **另造第二套 MR 创建 / cross-ref 路径**：硬约束禁止。只挂 `_finalize_and_notify`、只走既有 client + `aresolve_git_token`、只镜像/复用 `CreatePRNode` cross-ref 模式。
- **cross-ref/追溯失败让收尾失败**：违反 fail-soft（D-10）。任何回写/读链异常只 `logger.warning`，PR 已建即成功。
- **裸访问同步 lazy-FK**（如 `pv.plan.work_item.work_item_id`）：在 async 触发 `SynchronousOnlyOperation`。用 `*_id` 标量 + `afirst()` 逐跳。
- **凭证/token 入 PR 描述或日志**：安全红线。日志仅记 `pr_url` / `repository_name` / `has_*` 布尔。
- **单仓也做 cross-ref**：无兄弟可引用，须 `len(successful) >= 2` 守门（D-05，对齐 `pr.py:491` `len(successful) > 1`）。

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| 取仓 git token | 自写 GitCredential/实例池查询 | `aresolve_git_token(repository)`（`git_credentials.py:100`） | per-repo→host fallback + 解密 + fail-soft 已封装；Phase 26 硬约束禁另写 |
| 平台 client 构造 | 自判 GitHub/GitLab + URL 解析 | `get_git_platform_client(repo, token)`（`__init__.py:114`） | URL/owner/project 解析 + 平台分支已封装 |
| cross-ref section markdown | 重写链接拼接逻辑 | `CreatePRNode._generate_cross_reference_section`（`pr.py:285`，提取共用） | 已验证纯函数（含排除自身、空段守门） |
| MR 描述回写 | 自调 PyGithub/python-gitlab | 镜像 `_add_cross_references`（`pr.py:312`）的 `_get_repo`/`_get_project` + `to_thread` | 平台差异 + 同步 SDK 包装已验证 |
| GitLab MR id 选择 | 自己判 iid vs id | 复用 `MRCreateResult.mr_id`（GitLab=iid `gitlab_client.py:159`，GitHub=number `github_client.py:145`） | 回写 `get(iid)`/`get_pull(number)` 与创建返回 id 已对齐 |
| 飞书段渲染风格 | 新文案体系 | 借鉴 `mr_service.build_mr_description`（`mr_service.py:13`，`## 关联飞书工作项`段） | 既有风格一致 |

**Key insight:** 本 phase 的全部「难点」（凭证、平台差异、同步 SDK、cross-ref 回写、id 对齐）都已在 `CreatePRNode` / `mr_service` / `git_credentials` 里解决并跑在生产。研究结论是**复用/镜像而非重造**——风险点不在技术实现，而在「确保零回归 + fail-soft 边界正确」。

## Common Pitfalls

### Pitfall 1: cross-ref 回写抛错回灌容器回调 5xx

**What goes wrong:** `_finalize_and_notify` 在容器回调链路里执行；若 cross-ref 回写异常上抛，会让节点重入失败 → 回调返回 5xx → runner 重试风暴。
**Why it happens:** 忘记包 try/except 降级。
**How to avoid:** 整个 PR-02 段（追溯渲染 + 逐 PR 回写）`try/except` 包裹，异常仅 `logger.warning`，绝不上抛（对齐 `_add_cross_references` 逐 PR fail-soft `pr.py:399-405` + `_resume_wave` 的 `noqa: BLE001` 降级 `coding.py:821`）。
**Warning signs:** 测试里 mock client `.edit`/`.save` 抛异常后收尾 status 不是 `completed`。

### Pitfall 2: per-repo target_branch 改动破坏零回归

**What goes wrong:** 改 `_create_mr_for_repo` 后，单仓/同 default_branch 多仓的 target_branch 与 Phase 45 不一致。
**Why it happens:** fallback 链顺序写反，或误删 base_branch 兜底。
**How to avoid:** 严格 `repository.default_branch or base_branch or "main"`；写 D-14 零回归断言（所有仓 default_branch=base_branch → target 等价）。
**Warning signs:** `test_empty_deps_zero_regression`（`test_coding_wave.py`）类用例 MR 请求 target_branch 变化。

### Pitfall 3: async lazy-FK 触发 SynchronousOnlyOperation

**What goes wrong:** 读追溯链时 `pv.plan` / `tp.work_item` 触发同步 ORM。
**Why it happens:** Django async 上下文裸访问未预取的 FK。
**How to avoid:** 用 `pv.plan_id` / `tp.work_item_id` 标量 + 独立 `afirst()` 逐跳（Pattern 3）。
**Warning signs:** 测试 `SynchronousOnlyOperation` 报错（`transaction=True` DB 测试会暴露）。

### Pitfall 4: cross-ref 用错 pr_id 喂错平台 API

**What goes wrong:** 把 GitLab 全局 MR id 当 iid 喂 `mergerequests.get()`，404。
**Why it happens:** 误以为两平台 id 语义相同。
**How to avoid:** 直接复用 `MRCreateResult.mr_id`（已是 GitLab iid / GitHub number），回写 `int(mr_id)`——与 `CreatePRNode` 一致，无需重新取 id。
**Warning signs:** GitLab 回写 404 / GitHub 回写命中错 PR。

### Pitfall 5: 单 PR / 无兄弟仍执行回写

**What goes wrong:** 单仓收尾也走 cross-ref 回写，多一次无意义 API 调用甚至改描述。
**Why it happens:** 漏 `len(successful) >= 2` 守门。
**How to avoid:** D-05 守门；纯函数 `_generate_cross_reference_section` 对单 PR 已返回空段（`pr.py:301-302`），但仍应在调用层守门避免无谓回写循环。
**Warning signs:** 单仓用例触发了 `_get_repo`/`_get_project` mock。

## Code Examples

### 追溯段渲染（D-07，fail-soft，全函数包裹）

```python
# 新 helper: workflows/services/pr_cross_reference.py（D-09 倾向）
async def render_traceability_section(plan_version_id: str | None) -> str:
    """渲染「关联方案 / 工作项」段；任一跳取不到 → 返回空串（fail-soft）。"""
    if not plan_version_id:
        return ""
    try:
        from delivery.models import PlanVersion, TechnicalPlan, WorkItem
        pv = await PlanVersion.objects.filter(id=plan_version_id).afirst()
        if pv is None:
            return ""
        tp = await TechnicalPlan.objects.filter(id=pv.plan_id).afirst()
        if tp is None:
            return ""
        lines = ["\n---", "## 关联方案", "", f"- 技术方案: `{tp.id}` (v{pv.version})"]
        if tp.work_item_id:
            wi = await WorkItem.objects.filter(id=tp.work_item_id).afirst()
            if wi is not None:
                # WorkItem 无 url 字段，用三元组标识（飞书链接构造见 Open Q1）
                lines.append(f"- 工作项: {wi.work_item_type}/{wi.work_item_id} {wi.title}")
        return "\n".join(lines)
    except Exception as exc:  # noqa: BLE001 — 追溯增强 fail-soft，绝不阻塞收尾
        logger.warning("pr_traceability_render_failed", error=str(exc))
        return ""
```

### fail-soft 调用骨架（_finalize_and_notify 内，PR-02）

```python
# coding.py:_finalize_and_notify 内，批量建 MR 后追加：
successful_mrs = [r for r in mr_results if r.get("mr_url") and not r.get("error")]
if len(successful_mrs) >= 2:  # D-05 守门
    try:
        from workflows.services.pr_cross_reference import add_cross_references
        await add_cross_references(
            successful_mrs,                      # 含 repository_id / mr_url / mr_id
            plan_version_id=(plan_data or {}).get("plan_version_id"),
        )
    except Exception as exc:  # noqa: BLE001 — cross-ref 增强 fail-soft
        log.warning("coding_cross_reference_failed", error=str(exc))
```

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| MR target_branch 假设 master | 锚定真实 default_branch / merge 元数据 | v0.6（DOMAIN line 116） | 历史 diff/MR 不再打错分支；本 phase 把该原则贯彻到多仓 wave MR 创建 |
| 多仓全并行 dispatch + 单一 base_branch | wave 拓扑分层 + per-repo（Phase 44/45 + 本 phase） | v0.8 | 本 phase 补 per-repo target_branch 收口 |

**Deprecated/outdated:** 无。本 phase 不弃用任何既有路径，`base_branch`（node 级）保留作兜底。

## Assumptions Log

| # | Claim | Section | Risk if Wrong |
|---|-------|---------|---------------|
| A1 | `plan_data` 在 wave finalize 路径稳定携带 `plan_version_id`（已验证：`_build_waiting_output` 透传 + `_finalize_wave` 读 `output_data["plan_data"]`） | Pattern 3 | 低 — 已读码确认 `coding.py:643`/`988` 透传 plan_data；plan_version_id 在 `plan_data` 内（`coding.py:365`） |
| A2 | wave 路径 `metadata.feishu_url`/`feishu_title` 不一定可达（plan_data 内未见该键；chat 路径 `task.metadata` 才有） | D-07 / Open Q1 | 中 — 若误设其必达，追溯段飞书链接可能空；缓解：以 PlanVersion→WorkItem 三元组为权威 fallback |
| A3 | cross-ref 回写复用 `MRCreateResult.mr_id` 无需重新取 id（GitLab=iid/GitHub=number 已对齐回写 API） | Pitfall 4 | 低 — 已验证 `gitlab_client.py:159` / `github_client.py:145` |
| A4 | `CreatePRNode._generate_cross_reference_section` 可安全提取为模块级纯函数（不依赖 self 状态） | Pattern 2 | 低 — 已读码确认仅用入参（`pr.py:285-310`） |

**若 planner 选择内联镜像（D-09 备选）而非提取 helper：** A4 不影响——内联同样复制纯逻辑，须显式注释「同源 `CreatePRNode`」。

## Open Questions

1. **WorkItem 飞书链接如何构造？**
   - What we know: `WorkItem` 存 `(feishu_project_key, work_item_type, work_item_id)` 三元组（`work_item.py:38-41`），**无** url 字段；`mr_service.build_mr_description` 用的是 `task.metadata["feishu_url"]`（chat 路径）。
   - What's unclear: wave 收尾路径 `plan_data`/`context` 是否携带现成 `feishu_url`；若无，需从三元组构造飞书 URL（飞书项目链接格式）。
   - Recommendation: 优先用现成 `feishu_url`（若 planner 确认可从 `context.get_trigger_data("payload...")` 或 plan_data metadata 取到）；否则追溯段降级为「工作项 类型/ID + 标题」纯文本标识（A2 已采此 fallback），飞书 URL 构造留 Discretion / 不阻塞 PR-02 验收。

2. **是否同步重构 `CreatePRNode` 复用新 helper？**
   - What we know: D-09 倾向提取共用消除漂移；但 `CreatePRNode` 已生产运行，重构有回归面。
   - What's unclear: 重构 blast radius 是否值当。
   - Recommendation: planner 二选一（Discretion）——(a) 提取 helper 且 `CreatePRNode` 切换复用（需跑 `test_batch_pr.py` 全绿）；(b) 仅 wave 路径用新 helper、`CreatePRNode` 留原样并加注释「后续统一」。倾向 (a) 若 `test_batch_pr.py` 覆盖足够。

3. **是否发 `coding.pr.created` / `coding.pr.cross_referenced` trace 事件？**
   - What we know: Discretion 项，倾向低成本接通（若 DOMAIN §15 已定义词表）。
   - Recommendation: 非 PR-01/02 验收硬项；planner 若低成本可接，否则 backlog。

## Environment Availability

> 本 phase 单测全程 mock git 平台 IO 边界（`get_git_platform_client` / `aresolve_git_token` / `_get_repo` / `_get_project`），**无真实外部依赖参与测试**。运行时依赖（GitHub/GitLab API、有效凭证）属部署态，不影响规划/单测。

| Dependency | Required By | Available (测试时) | Fallback |
|------------|------------|-------------------|----------|
| GitHub/GitLab API | 运行时 MR 创建/回写 | ✗（mock） | 单测 mock client，真实端到端 deferred（既有 mock IO 边界） |
| 有效 git 凭证 | 运行时 token | ✗（mock `aresolve_git_token`） | 缺凭证 fail-soft 已是被测路径之一 |
| pytest / pytest-asyncio / pytest-django | 单测 | ✓（既有） | — |

**Missing dependencies with no fallback:** 无（纯内部改动 + mock 测试）。

## Validation Architecture

### Test Framework

| Property | Value |
|----------|-------|
| Framework | pytest 9.x + pytest-asyncio + pytest-django（既有） |
| Config file | `server/pyproject.toml`（`[tool.pytest]` 既有） |
| Quick run command | `cd server && uv run pytest tests/test_pr_cross_reference.py -x -q` |
| Full suite command | `cd server && uv run pytest tests/test_coding_wave.py tests/test_batch_pr.py tests/test_pr_cross_reference.py -q` |

### Phase Requirements → Test Map

| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| PR-01 | 多仓各仓 MR target_branch = 各仓 default_branch（A=develop, B=release/x） | unit | `uv run pytest tests/test_pr_cross_reference.py -k target_branch -x` | ❌ Wave 0 |
| PR-01 | 零回归：所有仓 default_branch=base_branch → target 等价（D-14） | unit | `uv run pytest tests/test_pr_cross_reference.py -k zero_regression -x` | ❌ Wave 0 |
| PR-01 | 零回归：单仓收尾结构与 Phase 45 一致、无 cross-ref | unit | `uv run pytest tests/test_coding_wave.py -k single_repo -x` | ⚠️ 扩展既有 |
| PR-02 | cross-ref 纯函数：多 PR 含兄弟链接排除自身；单 PR 空段（D-12） | unit | `uv run pytest tests/test_pr_cross_reference.py -k cross_reference_section -x` | ❌ Wave 0 |
| PR-02 | 回写路径：mock `_get_repo`/`_get_project` 断言 `edit`/`save` 被调 + body 含兄弟链接（D-12） | unit | `uv run pytest tests/test_pr_cross_reference.py -k writeback -x` | ❌ Wave 0 |
| PR-02 | 可追溯：mock PlanVersion→TechnicalPlan→WorkItem，body 含方案/工作项；链断省略段不抛（D-13） | unit | `uv run pytest tests/test_pr_cross_reference.py -k traceability -x` | ❌ Wave 0 |
| PR-02 | fail-soft：回写抛错 → 收尾仍 completed、PR 仍在 output（D-15） | unit | `uv run pytest tests/test_pr_cross_reference.py -k fail_soft -x` | ❌ Wave 0 |
| PR-02 | 无凭证仓不进 cross-ref 名单；<2 仓不回写（D-05/D-15） | unit | `uv run pytest tests/test_pr_cross_reference.py -k guard -x` | ❌ Wave 0 |

### Sampling Rate

- **Per task commit:** `uv run pytest tests/test_pr_cross_reference.py -x -q`
- **Per wave merge:** `uv run pytest tests/test_coding_wave.py tests/test_batch_pr.py tests/test_pr_cross_reference.py -q`
- **Phase gate:** `cd server && uv run pytest -q` 全绿（含 ruff line 100 / mypy）后 `/gsd-verify-work`。

### Wave 0 Gaps

- [ ] `server/tests/test_pr_cross_reference.py` — 覆盖 PR-01（target_branch 解析 + 零回归）、PR-02（纯函数 + 回写 + 追溯 + fail-soft + 守门）。可直接借 `test_batch_pr.py` 的 mock client 范式（`AsyncMock` + `MagicMock(_get_repo/_get_project)`）+ `test_coding_wave.py` 的 DB harness（`@pytest.mark.django_db(transaction=True)` 真实 PlanVersion/TechnicalPlan/WorkItem 行）。
- [ ] mock 范式确认：捕获 `MRCreateRequest` → 用 `AsyncMock` 的 `create_merge_request.side_effect` 记录 `request.target_branch`（断言 per-repo）。
- [ ] 既有框架已装，无需新增 install。

## Security Domain

> `security_enforcement: true`，`security_asvs_level: 1`，`security_block_on: high`。本 phase 创建外部 PR + 回写描述 + 读 DB 链，涉凭证与外部写。

### Applicable ASVS Categories

| ASVS Category | Applies | Standard Control |
|---------------|---------|-----------------|
| V2 Authentication | yes（git 平台 token） | `aresolve_git_token` 唯一入口，Fernet 密文存库，`decrypt_value` 唯一解密出口；token 绝不入描述/日志 |
| V3 Session Management | no | 无会话态变更 |
| V4 Access Control | no | 不新增 API 端点/权限面；只读 DB + 写外部 PR |
| V5 Input Validation | yes（PR body / repo url） | repo_name/pr_url 来自 DB 与平台返回，渲染进 markdown 时不引入用户原始注入面；plan/work_item 标题入 body 须避免破坏 markdown（低风险，纯展示） |
| V6 Cryptography | yes | 复用既有 Fernet 加密（不 hand-roll），本 phase 不新增加密逻辑 |
| V7 Errors & Logging | yes | fail-soft 日志仅记 pr_url/repo_name/has_* 布尔，token/密文绝不入日志（`git_credentials.py:10-12` 安全契约） |

### Known Threat Patterns for {workflow 收尾 + 外部 git 写}

| Pattern | STRIDE | Standard Mitigation |
|---------|--------|---------------------|
| token 泄漏入 PR 描述/日志 | Information Disclosure | 仅记 url/name/布尔；描述只含方案/链接，绝不含凭证（既有约定） |
| cross-ref 回写异常回灌容器回调 5xx → 重试风暴/DoS | Denial of Service | 全段 fail-soft `logger.warning` 降级（D-10），绝不上抛（对齐 `_resume_wave` `noqa: BLE001`） |
| 重复 finalize 重复创建 MR | Tampering（重复副作用） | 沿用既有 wave gating（`aadvance_coding_waves` 幂等 + RepoCodingTask 状态机），本 phase 不新增第二处创建（D-15） |
| 跨仓 host 凭证错配 | Spoofing | 沿用 `aresolve_git_token` 的 host 归一化解析（`git_credentials.py:36`，威胁 T-26-03 已防），本 phase 不改 |
| 飞书工作项标题含恶意 markdown 破坏 PR 描述 | Tampering（展示） | 低风险纯展示；planner 可选对标题做最小转义（Discretion，非硬项） |

## Sources

### Primary (HIGH confidence) — 仓内代码实测
- `server/workflows/nodes/ai/coding.py` — `_execute_with_branch`（317-319 病根）、`_finalize_and_notify`（1070 挂载点）、`_create_mr_for_repo`（1658 修复点）、`_finalize_wave`/`_resume_wave`/`_build_waiting_output`（plan_data 透传链）
- `server/workflows/nodes/git/pr.py` — `_generate_cross_reference_section`（285）、`_add_cross_references`（312）、`execute` 守门（491）
- `server/workflows/services/mr_service.py` — `create_mr_for_task`（159 per-repo target_branch 范式）、`build_mr_description`（13）
- `server/services/git_credentials.py` — `aresolve_git_token`（100）
- `server/services/git_platform/__init__.py`（114 工厂）、`base.py`（35 无公共 update 方法）、`models.py`（8/19 dataclass）、`github_client.py`（47/145）、`gitlab_client.py`（71/159）
- `server/delivery/models/technical_plan.py`（48/96 TechnicalPlan/PlanVersion）、`work_item.py`（32 WorkItem 无 url 字段）、`repo_coding_task.py`（45）
- `server/tests/test_batch_pr.py`、`server/tests/test_coding_wave.py`（测试范式）
- `.planning/config.json`（nyquist/security 开关）、`.planning/phases/46-pr-pr/46-CONTEXT.md`、`.planning/REQUIREMENTS.md`

### Secondary (MEDIUM confidence)
- 无外部源（纯内部）

### Tertiary (LOW confidence)
- 无

## Metadata

**Confidence breakdown:**
- Standard stack（既有组件复用）: HIGH — 全部读码确认接口签名与返回语义
- Architecture（挂载点 + 两段式模式）: HIGH — `_finalize_and_notify` / `CreatePRNode` cross-ref 均已读全
- Pitfalls: HIGH — 病根（317-319/1708）与 fail-soft 约定（_resume_wave noqa）实测
- Traceability（feishu url 构造）: MEDIUM — WorkItem 无 url 字段确认，但 feishu_url 在 wave 路径可达性需 planner 确认（Open Q1）

**Research date:** 2026-06-16
**Valid until:** 2026-07-16（内部代码，稳定；除非 Phase 47+ 重构收尾路径）
