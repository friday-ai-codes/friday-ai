# Phase 46: 多仓融合 PR + 跨仓 PR 关联 - Context

**Gathered:** 2026-06-16
**Status:** Ready for planning

<domain>
## Phase Boundary

本 phase 在 Phase 44（多仓 wave 编码操作态脊柱 + 拓扑调度）、Phase 45（上游产物提取/注入）之上，补齐多仓 wave 编码结果**落 PR/MR + 跨仓关联**的最后一环，纯后端基础设施（无新 Vue 组件；UI hint=maybe，复用既有执行/方案视图与编码结果卡片）：

1. **PR-01 — 各仓正确 target_branch（非假设 master）**：多仓 wave 编码收尾时，各仓产出的 PR/MR `target_branch` 必须用**各仓自己的** `Repository.default_branch`（每仓独立解析），而非现状的「取第一个仓的 default_branch 当全局 base_branch、对所有仓共用」。对齐 v0.6 坐实的「MR target_branch 锚定、绝不假设 master」（DOMAIN §历史 diff，line 116）。

2. **PR-02 — 跨仓 PR cross-ref + 可追溯**：同一方案版本（`PlanVersion`/`TechnicalPlan`/`WorkItem`）下多仓产出的 PR 互相引用（cross-ref：每个 PR 描述含其它兄弟仓 PR 链接），并可追溯到同一 `TechnicalPlan`/`WorkItem`（PR 描述含方案/飞书工作项关联）。复用既有 `CreatePRNode` 已验证的「先建后回写描述」cross-ref 模式（`_generate_cross_reference_section` / `_add_cross_references`），不另造第二套。

**复用既有机制（硬约束，不另造）**：
- PR/MR 创建**只走**既有 git 平台 client（`services/git_platform/get_git_platform_client` → `create_merge_request(MRCreateRequest)`）+ `aresolve_git_token`（per-repo 优先 → host 实例池 fallback，缺凭证 fail-soft 不回退）。
- 创建/cross-ref **只挂**既有 wave 收尾收口 `AICodingNode._finalize_and_notify`（单 wave / wave 全终态共用收尾段，所有 done 仓 MR 在此一批创建——天然适合一处做 cross-ref）。
- cross-ref 回写描述复用 `CreatePRNode` 已落地的 GitHub `_get_repo().get_pull().edit(body=)` / GitLab `_get_project().mergerequests.get().save()` 模式（提取为可复用 helper，避免双份漂移）。

**显式不做**（留后续 phase / backlog）：编码遇阻 question 抛人 HITL（Phase 47）、全自动回溯重规划（里程碑显式非目标）、PR 自动合并（既有 `MergePRNode` 不在本 phase 触发）、新增 git 平台 client 公共「更新 MR 描述」抽象方法（本 phase 沿用既有私有访问模式，保最小 diff；可在 the agent's Discretion 内择优）、真实 runner+Docker 端到端 PR 验收（沿用既有 mock IO 边界 deferred）。

</domain>

<decisions>
## Implementation Decisions

> 基础设施 + 接口决策 phase——以下为「推荐 / 最安全默认」技术决策，autonomous 模式已全部 AUTO-ACCEPT 推荐项，均在 the agent's Discretion 范围内。Planner 可在 PLAN.md 细化，但应保持「挂既有收尾收口、走既有 git client + aresolve_git_token、各仓 default_branch 独立解析、复用既有 cross-ref 模式、对空/单仓零回归、不造两套」的方向。

### Area 1：各仓 target_branch 解析（PR-01）

- **D-01 target_branch 权威源**：各仓 PR/MR `target_branch` = **该仓自己的** `Repository.default_branch`（每仓独立），fallback 链 `repository.default_branch → 现有 base_branch（node 级）→ "main"`。`execution_plan[]` 每项仅 `{repository_id, coding_instruction, dependencies}`（DOMAIN line 319），**不含** per-repo target_branch 字段，故权威源为 `Repository.default_branch`。
- **D-02 修复落点**：`AICodingNode._create_mr_for_repo` 现签名已收 `repository`（仓对象）+ `base_branch`（共用），新增/改为以 `repository.default_branch` 为 `target_branch` 优先解析（参数兜底）。`_finalize_and_notify` 调用处无须为每仓预解析（仓对象已在手）。保持 `MRCreateRequest(source_branch=branch_name, target_branch=<per-repo resolved>)`。
- **D-03 source_branch（head）**：维持现状单一 `branch_name`（多仓同名特性分支，v0.8 既有约定）。本 phase **不**改 head 分支策略（per-repo head 分支留 backlog，非 PR-01 目标）。
- **D-04 零回归命门**：单仓 / 所有仓 default_branch 恰等于现 base_branch 时，行为与 Phase 45 逐字等价（target_branch 解析结果不变）。仅当多仓 default_branch 不一致时才体现修复价值。

### Area 2：跨仓 cross-ref + 可追溯（PR-02）

- **D-05 cross-ref 触发条件**：`_finalize_and_notify` 中**成功创建 MR 的仓 ≥ 2** 时才做 cross-ref（单仓无兄弟可引用，跳过——对齐 `CreatePRNode` 的 `len(successful) > 1` 守门）。失败/无凭证仓不进 cross-ref 名单。
- **D-06 cross-ref 内容**：每个成功 PR 的描述追加「## 关联 PR」段，列出**其它**兄弟仓 PR 的 `- [repo_name](pr_url)`（复用 `CreatePRNode._generate_cross_reference_section` 语义）。
- **D-07 可追溯段（traceability）**：PR 描述含「关联方案 / 工作项」——经 `plan_data.plan_version_id` 反查 `PlanVersion → TechnicalPlan → work_item`（async ORM 安全），渲染 `TechnicalPlan` 标识 + `WorkItem` 飞书链接（若 `metadata.feishu_url`/`feishu_title` 在手则优先用之）。取不到 → 仅省略该段（fail-soft，不阻塞 PR 创建）。
- **D-08 cross-ref 实现模式**：复用 `CreatePRNode` 已验证的「先批量建 MR → 再回写描述」两段式：建完所有 done 仓 MR 后，对成功名单做一次回写（GitHub `repo.get_pull(id).edit(body=...)` / GitLab `project.mergerequests.get(id).save()`，经 `asyncio.to_thread` 包同步 SDK 调用）。回写经 `aresolve_git_token` 重取 token + `get_git_platform_client`。
- **D-09 helper 复用 / 去重**：倾向把 cross-ref section 生成 + 回写逻辑提取为**可复用 helper**（如 `workflows/services/` 下 `pr_cross_reference.py` 或复用 `mr_service.py`），供 `CreatePRNode`（手动节点）与 `AICodingNode._finalize_and_notify`（wave 收尾）共用，消除双份漂移。若提取成本/风险偏高，planner 可在 the agent's Discretion 内选择 wave 路径内联镜像既有模式（但须显式标注同源）。
- **D-10 fail-soft / 不回退**：cross-ref 回写任一环失败仅 `logger.warning` 降级（PR 已成功创建，cross-ref 是增强非命门）；缺凭证、平台未知、单 PR 回写异常都不让收尾失败、不回灌容器回调 5xx（对齐既有 `_add_cross_references` 逐 PR fail-soft）。

### Area 3：测试与零回归（验收硬项）

- **D-11 PR-01 单测**：构造多仓（repo A default_branch="develop"、repo B default_branch="release/x"），断言各仓 MR 请求的 `target_branch` = 各仓自己的 default_branch（**非** 第一个仓的 / 非 "main"）。mock git client 捕获 `MRCreateRequest`。
- **D-12 PR-02 cross-ref 单测**：`_generate_cross_reference_section`（或复用 helper）纯函数——多 PR → 段含各兄弟仓链接、排除自身；单 PR → 空段。回写路径以 mock client（`_get_repo`/`_get_project`）断言 `edit`/`save` 被调用且 body 含兄弟链接 + 方案/工作项追溯段。
- **D-13 可追溯单测**：mock `PlanVersion → TechnicalPlan → work_item` 链，断言 PR body 含 TechnicalPlan 标识 / WorkItem 飞书链接；链断（取不到）→ 省略追溯段且不抛、PR 仍创建。
- **D-14 零回归断言**：单仓收尾 → 无 cross-ref（不调回写）、target_branch = 该仓 default_branch、输出结构与 Phase 45 一致；所有仓 default_branch 同值 → target_branch 与现 base_branch 等价。
- **D-15 fail-soft / 幂等**：cross-ref 回写抛错 → 收尾仍 `completed`、PR 仍在 output；无凭证仓不进 cross-ref；重复 finalize（重复回调）经既有 wave gating（aadvance 幂等）不重复创建 MR（MR 创建幂等性沿用既有行为，本 phase 不新增第二处创建）。

### the agent's Discretion

- cross-ref 段与可追溯段的中文文案 / Markdown 结构细节、是否合并为单段「## 关联」由 planner 按可读性定。
- helper 提取的具体模块落点（`workflows/services/pr_cross_reference.py` vs 扩展 `mr_service.py`）与是否同时重构 `CreatePRNode` 复用同 helper（倾向提取共用、消除漂移；但若 `CreatePRNode` 重构 blast radius 偏大，可仅 wave 路径用新 helper、`CreatePRNode` 留原样并标注后续统一）由 planner 按最小 diff / 风险定。
- target_branch fallback 链细节（是否保留 node 级 base_branch 作为第二兜底）、是否顺带发 `coding.pr.created` / `coding.pr.cross_referenced` trace 事件（DOMAIN §15 若已定义）由 planner 决定，倾向低成本接通。
- 是否给 git 平台 client 增公共「更新 MR 描述」抽象方法（替代私有 `_get_repo`/`_get_project` 访问）由 planner 权衡：倾向本 phase 沿用既有私有模式保最小 diff，公共抽象留 backlog。

</decisions>

<code_context>
## Existing Code Insights

### Reusable Assets
- `workflows/nodes/ai/coding.py:AICodingNode._finalize_and_notify`（行 ~1070）——单 wave / wave 全终态共用**收尾收口**；现已对每个 done 仓循环调 `_create_mr_for_repo` 一批创建 MR（**PR-01/02 唯一挂载点**：cross-ref 在此批创建后追加一段回写）。
- `workflows/nodes/ai/coding.py:AICodingNode._create_mr_for_repo`（行 ~1658）——单仓 MR 创建（`aresolve_git_token` → `get_git_platform_client` → `MRCreateRequest(target_branch=base_branch)`）。**PR-01 修复点**：`target_branch` 改用 `repository.default_branch` 各仓独立解析。
- `workflows/nodes/ai/coding.py:AICodingNode._execute_with_branch`（行 317-319）——现 `base_branch = first_repo.default_branch or "main"` 单值共用（**PR-01 病根**）；本 phase 不必删此变量（保留作 node 级兜底），只须在 `_create_mr_for_repo` 内按仓覆盖。
- `workflows/nodes/git/pr.py:CreatePRNode`——手动工作流节点，已落地多仓并行建 PR + `_generate_cross_reference_section`（行 285）+ `_add_cross_references`（行 312，GitHub `pr.edit(body=)` / GitLab `mr.save()` 回写模式）。**PR-02 cross-ref 蓝本 / 可提取共用 helper 来源**。
- `services/git_platform/__init__.py`：`get_git_platform_client(repository, token)`、`MRCreateRequest(source_branch, target_branch, title, description, reviewer_usernames)`、`MRCreateResult(success, mr_url, mr_id, has_conflicts, error)`。
- `services/git_credentials.py:aresolve_git_token(repository)`——per-repo 优先 → host 实例凭证池 fallback（缺凭证返回 None → fail-soft）。
- `workflows/services/mr_service.py`——`build_mr_title` / `build_mr_description` / `create_mr_for_task`（chat 编码路径，`target_branch or repository.default_branch` 已是各仓 default_branch 范式，可作 PR-01 解析蓝本）。
- `repositories/models.py:Repository.default_branch`（行 160，`default="main"`）——各仓 target_branch 权威源。
- `delivery/models/PlanVersion`、`TechnicalPlan`（`work_item FK`，DOMAIN line 484）、`WorkItem`——可追溯链；`plan_data.plan_version_id` 为锚。

### Established Patterns
- async ORM 经 `*_id` 标量 / `afirst` / `aexists` / `async for`，绝不裸访问同步 lazy-FK（规避 `SynchronousOnlyOperation`）。
- 同步 git SDK（python-gitlab / PyGithub）调用经 `asyncio.to_thread(...)` 包装（见 `_add_cross_references`）。
- 收尾 / 通知 / cross-ref 副作用 fail-soft：失败仅 `logger.warning`，绝不让节点收尾失败 / 回调 5xx。
- 凭证/敏感值绝不入 PR 描述、不入日志（仅记 url / repo_name / has_* 布尔）。
- ruff line 100、Python 3.14、async adrf；注释/docstring 中文（zh-CN）。
- INV-6：状态写库只经 service；本 phase 不写 RepoCodingTask 状态字段（仅读 done 仓 + 创建外部 PR），不触 INV-6 写入面。

### Integration Points
- PR-01：`_finalize_and_notify` → `_create_mr_for_repo(repository, ...)` 内以 `repository.default_branch` 解析 `target_branch`。
- PR-02：`_finalize_and_notify` 在 MR 创建循环后 → 新增 cross-ref 回写段（成功仓 ≥ 2 时）→ 复用/镜像 `CreatePRNode` cross-ref 回写 + 可追溯段（`PlanVersion → TechnicalPlan → WorkItem`）。
- 无新模型 / 无新迁移（仅消费既有 Repository.default_branch + 创建外部 PR + 回写描述）。
- 可选 helper 新模块：`workflows/services/pr_cross_reference.py`（barrel 经 `workflows/services/__init__.py` 导出），供 `CreatePRNode` 与 `AICodingNode` 共用。

</code_context>

<specifics>
## Specific Ideas

- PR-01 病根明确：`_execute_with_branch` 取「第一个仓 default_branch」当全局 base_branch、`_create_mr_for_repo` 对所有仓共用该值当 target_branch；修复 = 各仓用各仓 `default_branch`。
- PR-02 复用 `CreatePRNode` 已验证 cross-ref 模式（先建后回写），不在 wave 路径另造第三套；倾向提取共用 helper 消除与 `CreatePRNode` 的双份漂移。
- wave 收尾时所有 done 仓 MR 在 `_finalize_and_notify` 一批创建——天然适合一处做 cross-ref（无需跨 wave 增量回写）。
- 可追溯到同一 `TechnicalPlan`/`WorkItem`：经 `plan_version_id` 反查链 + 既有 `metadata.feishu_url/feishu_title`。
- 全程 fail-soft：cross-ref / 可追溯是增强，缺失只降级 warning，绝不阻塞 PR 创建或收尾完成。
- 对齐 v0.6（DOMAIN line 116）：MR target_branch 锚定真实值、绝不假设 master。

</specifics>

<deferred>
## Deferred Ideas

- 编码遇阻 question 抛人（HITL）→ Phase 47（HITL-01）。
- 全自动回溯重规划 → 里程碑显式非目标 / backlog。
- per-repo head（source）分支策略（多仓不同特性分支名）→ backlog（本 phase head 维持单一 branch_name）。
- git 平台 client 公共「更新 MR 描述」抽象方法（替代私有 `_get_repo`/`_get_project`）→ backlog（本 phase 沿用既有私有模式）。
- PR 自动合并（`MergePRNode`）→ 非本 phase（创建 + 关联，不合并）。
- chat 编码入口（`coding_session_service`）的 cross-ref 接线 → follow-up（本 phase 优先 workflow wave 收尾路径；helper 入口无关以便复用）。
- 真实 runner + Docker 容器端到端 PR 创建/cross-ref 验收 → 既有 deferred（本地无法闭环，本 phase 以 mock git client 边界覆盖）。

</deferred>
