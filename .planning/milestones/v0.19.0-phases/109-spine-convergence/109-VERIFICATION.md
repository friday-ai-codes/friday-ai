---
phase: 109-spine-convergence
verified: 2026-07-31T03:38:41Z
status: human_needed
score: 64/64 must-haves verified
overrides_applied: 0
re_verification: null
evidence:
  backend_tests: "8106 passed, 61 skipped, 26 deselected, 1 xfailed, 0 failed（`server/.venv/bin/python -m pytest -q -p no:randomly`，全量套件，508.53s；按测试环境说明排除 `tests/services/test_commit_index.py` / `tests/services/test_commit_index_integration.py` / `tests/mcp_tools/test_grep_repository.py` 三个受文件系统沙箱限制的文件）"
  frontend_tests: "1425 passed, 1 skipped / 198 files（`cd web && CI=true pnpm vitest run --watch=false`，全量套件；已按要求断言 `Tests N passed` 行而非退出码）"
  types: "`pnpm vue-tsc --noEmit` 退出码 0、零输出"
  migrations: "`manage.py makemigrations --check --dry-run` → `No changes detected`，退出码 0"
  debt_markers: "49 个改动源文件（server/ + web/）零 TBD / FIXME / XXX / TODO / HACK / PLACEHOLDER"
  negative_controls: "verifier 独立跑 8 组反向对照，全部按预期变红（见正文 §5）；未接受 REVIEW 自报的对照结论"
human_verification:
  - test: "在真实环境导出一份草稿方案到飞书，核对文档正文顶部的「未经代码调研」告示，并与界面横幅主句逐字比对"
    expected: "导出物含告示块且置于「## 技术方案」之前；主句「本方案未经代码调研」与界面横幅逐字一致"
    why_human: "飞书文档创建依赖真实 IM 凭证与外部 API，本地只能验证 markdown 组装（已由 5 条导出器用例覆盖）"
    requirement: RELY-01
  - test: "真实会话触发一次编排，从「进入编码」卡片走完选目标仓 → 配置分支 → 确认编码 → 飞书导出全链"
    expected: "四步全部挂在同一个 CodingPlan.id 上，无需重新生成方案；容器真实拉起并产出 PR"
    why_human: "需真实 Git 平台、Runner 与飞书环境；本地只验证到 dispatch 契约组装（e2e 护栏覆盖四步 HTTP 面）"
    requirement: SPINE-01
  - test: "浏览器里核对草稿横幅 / 头部常驻徽标 / 阻断式确认弹层的视觉与交互，并确认折叠后徽标仍可见"
    expected: "与 109-UI-SPEC 一致；无新色板 / 新字号 / 新组件；弹层焦点陷阱与 label 点击生效"
    why_human: "视觉观感与真实焦点行为无法程序化断言（结构层已由 63 条 TechPlanCard 用例覆盖）"
    requirement: RELY-01
  - test: "核对投影出的 tech_plan 在界面 markdown 下的观感（`render_merged_plan_markdown` 产 lark_md 方言，`•` 而非 `- `）"
    expected: "项目符号显示为纯文本 `•`，可读、语义不丢"
    why_human: "109-VALIDATION 第 10 条已裁定「接受现状」，但观感是否可接受须人判；若不可接受，处置是给该函数加 flavor 参数而非 fork 渲染器"
    requirement: SPINE-01
  - test: "生产升级后确认迁移 0033 的影响面：存量 CodingPlan 全部落 provenance=draft，历史方案卡集体出现「未经代码调研」横幅与徽标，送编码时各弹一次确认"
    expected: "影响面可接受（存量确实是 SPINE-02 之前的徒手产物，保守标注在事实层正确）"
    why_human: "需生产存量数据规模；这是 RELY-01 的**预期行为而非回归**，109-08 must-have 已显式登记，须在 UAT 中如实向用户交代"
    requirement: RELY-01
  - test: "确认下游容器对 dispatch payload 里 `unresearched` 标志的消费策略"
    expected: "本 phase 只保证标志出现在 payload；容器侧是否据此调整行为由后续决定"
    why_human: "跨进程契约的下游半边不在本 phase 边界内（109-07 已显式声明「容器侧消费与否留后续」）"
    requirement: RELY-01
deferred:
  - truth: "无 conversation 的编排入口（workflow / MCP）投影为 CodingPlan"
    addressed_in: "本里程碑外（裁决 D-3 显式记 deferred）"
    evidence: "109-CONTEXT 裁决 D-3：`ConvergenceSession` 无 space FK，反查有歧义；限定 chat 入口后 SC-1 的用户故事即完整成立。代码以稳定机器码 `projection_requires_chat_entrypoint` 显式拒绝，不猜 space、不建合成会话"
  - truth: "编排阶段流式输出、容器日志可见、阶段时间线"
    addressed_in: "Phase 110（过程可观测）"
    evidence: "ROADMAP Phase 110 目标即「阶段流式 + 容器日志 + 阶段时间线」；109-CONTEXT 裁决 D-4 明确本 phase 的 chat 呈现只做最小可操作面"
  - truth: "方案结构深度（DEPTH-01~05）"
    addressed_in: "里程碑 v0.20.0"
    evidence: "109-CONTEXT 边界外条款：`process_runtime` 的 prompt/schema 冻结，本 phase 以现行 §7 `execution_plan` 对接执行流"
  - truth: "两套 CodingPlan（chat 与 mcp_tools）合表为 canonical"
    addressed_in: "Future（REQUIREMENTS 已列）"
    evidence: "109-CONTEXT Out of Scope：本 phase 不合表"
---

# Phase 109: 双脊柱合流 验证报告

**Phase Goal**: 编排产出的技术方案可直接进入「选目标仓 → 配置分支 → 确认编码 → 飞书导出」的执行流，系统不再存在由对话模型徒手编写方案正文的产出路径，用户拿到的方案一定来自完整编排链路。

**Verified**: 2026-07-31T03:38:41Z
**Status**: human_needed（自动化面全通，剩余项须真实环境 / 浏览器 / 生产数据）
**Diff base**: `256899d5` → `76bd36c4`（49 个改动源文件，10585 insertions）
**Re-verification**: No —— 首次验证

---

## 1. 成功标准达成情况

### SC-1 —— 编排产出直连执行流（SPINE-01）

| # | 可观测事实 | 状态 | 证据 |
|---|---|---|---|
| 1.1 | 编排产出在 chat 里有可操作呈现面 | ✓ VERIFIED | `web/src/components/chat/OrchestratedPlanCard.vue`（170 行，新建）；`ChatMessageBubble.vue:1252` 按 `isOrchestrationTool(item.name) && item.status === 'done' && orchestratedPlanData` 渲染 |
| 1.2 | 两个编排入口走同一判定同一张卡 | ✓ VERIFIED | `isOrchestrationTool()` 同时覆盖 `start_plan_research` / `start_feature_solution`（`ChatMessageBubble.vue:776-778`） |
| 1.3 | 两个编排工具已进 `UNGROUPABLE_TOOLS`（漏改则卡片静默不渲染） | ✓ VERIFIED | `ChatMessageBubble.vue:506-512` |
| 1.4 | 「进入编码」触发惰性投影，成功后就地内嵌 `TechPlanCard` | ✓ VERIFIED | `OrchestratedPlanCard.vue:79-103`（`handleEnterCoding`）+ `:155-168`（就地交棒，7 个 props 全部取投影响应） |
| 1.5 | 交棒后选仓面真的有可勾选行（HI-01 修复面） | ✓ VERIFIED | 端点回 `recommended_repositories`（`chat/views.py`）→ 组件同时传 `:available-repositories` 与 `:target-repositories`；`OrchestratedPlanCard.spec.ts:326-353` 用**真实 TechPlanCard**（仅叶子 UI 原语 passthrough）断言两行仓库名与方案正文 |
| 1.6 | 执行流四步只以 `CodingPlan.id` 为锚点 | ✓ VERIFIED | `tests/test_spa_coding_chain_e2e.py::test_spa_coding_chain_four_steps_share_one_plan_id` + `::test_projected_plan_completes_fanout_and_export` |
| 1.7 | 编排在途 / 失败零渲染（无进度条、无阶段文案） | ✓ VERIFIED | `orchestratedPlanData` 仅在 `status === 'done'` 且 `artifact_version_id` 非空串时返回；`OrchestratedPlanCard.spec.ts:121-130` 断言无 `.animate-pulse` |
| 1.8 | 重复点击得中性「已复用既有编码方案」提示 | ✓ VERIFIED | `OrchestratedPlanCard.vue:94` 走 success 通道；spec:152-163 断言 `toastError` 未被调用 |
| 1.9 | 编排工具在 tool pill / 分析过程有中文标签与图标 | ✓ VERIFIED | `useToolDisplay.ts:52-53`（标签）、`:85-86`（图标）、`:389-390`（摘要） |

### SC-2 —— 移除徒手创作路径 + 两条链零回归（SPINE-02）

| # | 可观测事实 | 状态 | 证据 |
|---|---|---|---|
| 2.1 | `create_coding_plan` schema 无 `tech_plan` / `affected_files` | ✓ VERIFIED | 逐行读 `agents/tools/coding_tools.py:76-120`；入参仅 `space_id` / `conversation_id` / `repository_id` / `artifact_version_id` / `recommended_repository_ids` |
| 2.2 | `update_coding_plan` 同样收窄（裁决 D-1「两个门一起收」） | ✓ VERIFIED | `coding_tools.py:386-411`；入参仅 `conversation_id` / `coding_plan_id` / `session_id` / `artifact_version_id` |
| 2.3 | 两个工具必填 `artifact_version_id`，无来源被拒并留痕 | ✓ VERIFIED | `required` 含该键；handler 空值早退并打 `coding_plan_authoring_attempt_rejected`（`_log_authoring_rejected`，`reason` 过 `redact_secrets_in_text`） |
| 2.4 | 有**正向不变量**守护，后人加回入参会变红 | ✓ VERIFIED | `tests/agents/test_coding_tools_schema_guard.py`：具名否定断言 + **键集合枚举式相等断言**（防换名正文入参）+ 函数签名断言，三层 |
| 2.5 | 签名字节级漂移守护 | ✓ VERIFIED | `tests/agents/test_tool_contracts.py` + `fixtures/{create,update}_coding_plan_signature.json` |
| 2.6 | 全仓无第二个徒手写正文的口子 | ✓ VERIFIED | verifier 独立扫 `tech_plan\s*=` 全部非测试写入点：`CodingPlan.aupdate_plan`（models.py:379）**已无任何生产调用方**；`aget_or_create_for_conversation` 剩两个调用方——离线迁移命令与 `coding_tools.py:532` legacy 分支（用 `session.tech_plan` 既有值，随后被 `arebind` 从来源版本覆盖），均非模型入参 |
| 2.7 | 执行半边保持可用（推荐仓解析、落库、payload 键集合） | ✓ VERIFIED | `tests/test_coding_tools.py::TestCreateCodingPlan`（10 条，含 `payload_key_set_is_frozen`）+ `TestCreateCodingPlanRecommendedRepos`（11 条） |
| 2.8 | MCP 桥接三对象零回归（新列必须有 default） | ✓ VERIFIED | `tests/mcp_tools/test_bridge_session.py::test_create_bridge_session_builds_three_objects` + `::test_create_bridge_session_defaults_new_provenance_columns`；裸 `objects.create()` 在两列新增后仍成功 |
| 2.9 | 凡挂 `create_coding_plan` 的白名单必挂编排工具（不留「要来源却拿不到来源」死路） | ✓ VERIFIED | `tests/test_chat_tools.py:436-453` 参数化守护，覆盖所有清单来源 |

### SC-3 —— 草稿双侧标注 + 送编码防护（RELY-01）

| # | 可观测事实 | 状态 | 证据 |
|---|---|---|---|
| 3.1 | 数据层来源标志作为唯一载体 | ✓ VERIFIED | `CodingPlanProvenance` TextChoices + `CodingPlan.provenance`（`chat/models.py:212-227, 282-289`） |
| 3.2 | 界面：展开态告警横幅（正文之前）+ 头部常驻徽标 | ✓ VERIFIED | `TechPlanCard.vue:602-618`（横幅，`role="alert"` 无 `aria-live`）+ `:572`（头部 Badge）；折叠后徽标仍在（spec:1120） |
| 3.3 | 导出物：正文顶部「未经代码调研」告示 | ✓ VERIFIED | `feishu/coding_plan_exporter.py:52-58`（`_DRAFT_NOTICE`）+ `:206-207`（置于 `## 技术方案` 之前）；5 条用例含「与界面主句逐字一致」 |
| 3.4 | 服务端 fail-closed gate，拒绝时 DB 零写入 | ✓ VERIFIED | `create_sessions_for_plan` 首部（`coding_session_service.py:718-734`），`acknowledge_unresearched is not True` 即抛 |
| 3.5 | 拒绝带稳定机器码 `draft_requires_explicit_confirm` | ✓ VERIFIED | 响应体 `{code, detail}` 双键（`chat/views.py`），前端按 `code` 分支（`TechPlanCard.vue:378-383`） |
| 3.6 | 执行契约携带「未经调研」标志 | ✓ VERIFIED | `CodingExecutionSpec.unresearched`（带默认值，不破坏既有构造点）+ `as_dict()` 增补该键；历史无 plan 关联的 session 走保守 `True` |
| 3.7 | 编排方案零摩擦（弹层不出现、字段不发送） | ✓ VERIFIED | `ensureUnresearchedAcknowledged` 早退；store 只在 `=== true` 时放键（**不发 false**）；spec:1206 断言请求体不含该键 |
| 3.8 | 确认与拒绝两条路径都留痕 | ✓ VERIFIED | `draft_plan_coding_confirmed` / `draft_plan_coding_rejected`，`actor_user_id` 由视图显式传入（MN-06） |

### SC-4 —— 投影幂等

| # | 可观测事实 | 状态 | 证据 |
|---|---|---|---|
| 4.1 | DB 层**无条件**唯一约束（不带 `condition`，避免 MySQL 静默跳过） | ✓ VERIFIED | `models.py:311-324` + 迁移 `0033` `AddConstraint`；`tests/test_coding_plan_model.py:227-243` 读 `connection.introspection.get_constraints` 直接断言约束**确实存在** |
| 4.2 | 幂等三件套齐备 | ✓ VERIFIED | `aget_or_create` + `except IntegrityError` 重 `aget`（`plan_projection_service.py:343-361`）；`test_concurrent_projection_yields_single_row_without_raising` / `test_concurrent_integrity_error_degrades_to_idempotent_hit` |
| 4.3 | 版本更新后可新建投影、旧投影保留 | ✓ VERIFIED | `test_new_version_keeps_old_projection_intact` |
| 4.4 | 两跳可追溯到需求 | ✓ VERIFIED | `test_traceability_two_hops_from_plan_to_work_item` |
| 4.5 | `action: create → change_type: add` 枚举转换有显式断言（研究点名的静默失守点） | ✓ VERIFIED | `_ACTION_TO_CHANGE_TYPE` + `test_mapping_action_to_change_type_enum_exhaustive` / `test_mapping_action_table_is_exactly_create_add`，逐条同时断言 `file_path` **与** `change_type` |

---

## 2. Must-have 计分

| 来源 | 条数 | 通过 |
|---|---|---|
| ROADMAP Success Criteria | 4 | 4 |
| 109-01（回归护栏） | 3 | 3 |
| 109-02（来源标志 + 唯一约束） | 5 | 5 |
| 109-03（映射 + 投影 service + 端点） | 6 | 6 |
| 109-04（进入编码入口） | 6 primary + 6 backstop | 12 |
| 109-05（两个门收窄） | 7 | 7 |
| 109-06（正文三级优先） | 4 primary + 2 backstop | 6 |
| 109-07（服务端 gate + 导出告示） | 7 | 7 |
| 109-08（界面标注 + 确认弹层） | 7 primary + 7 backstop | 14 |
| **合计** | **64** | **64** |

无 FAILED、无 UNCERTAIN、无 override。

---

## 3. 高风险不变量逐条核验（post-fix 代码实态）

| # | 不变量 | 结论 | 依据 |
|---|---|---|---|
| 1 | 草稿判定是**允许清单** | ✓ 成立 | 三处判定全为 `!== 'orchestrated'` 形态：`TechPlanCard.vue:291`、`coding_session_service.py:93`、`coding_plan_exporter.py:207`。`draft` / 未知取值 / `null` / `undefined` / `''` 全落标注侧；判定是纯字面比较，不对 `undefined` 做属性访问。类型层 `provenance?: CodingPlanProvenance \| string \| null` 刻意保留 `string`，让后端新增枚举值走保守分支而非编译失败 |
| 2 | 前端绝不自行产生 `acknowledge_unresearched: true` | ✓ 成立 | 全仓 grep 该键仅 4 个非测试出现点。`ensureUnresearchedAcknowledged`（`TechPlanCard.vue:365-370`）是唯一产生点；`acknowledged` 为组件本地 `ref`，每次打开重置、不写 store、不入 localStorage；store 层 `if (acknowledgeUnresearched === true)` 才放键；`retrySingleRepository` 原样转发不补值。三条路径逐条核过：创建态与追加态共用 `handleMultiConfirm`（结构性同过闸门），单仓重试在 `handleSessionRowRetry:417` 独立过闸门且**不把 `undefined` 当第三参显式传入** |
| 3 | 每个 `runtime.coding_plan` 消费点都过 `plan_id` 守卫 | ✓ 成立 | MN-05 已把守卫**下沉到 `codingPlanRuntime` 入口**（`TechPlanCard.vue:116-123`），`sessions` / `hasSessions` / `existingActiveRepoIds` / `visibleTargetRepositories` / `feishuDocUrl` / `resolvedTechPlan` / `resolvedAffectedFiles` / `resolvedProvenance` 全部从该 computed 取数。verifier 独立确认组件内 `activeCodingPlan` 仅在入口出现一次（其余为注释） |
| 4 | 服务端 gate fail-closed 且回机器码 | ✓ 成立 | gate 在 `create_sessions_for_plan` 最前面、任何 session 创建之前；serializer `default=False`；`is not True` 判定；`DraftPlanRequiresConfirmError` → 400 `{code: "draft_requires_explicit_confirm", detail: ...}`。单仓重试与追加态走同一端点同一 service，无绕过路径 |
| 5 | 无残留徒手创作路径 + MCP 桥接零回归 | ✓ 成立 | 见 §1 SC-2 第 2.1–2.9 条。MCP 桥接额外经 MN-01 修正为显式标 `ORCHESTRATED`（原实现落 DB default `draft`，会让所有 MCP 执行任务的 `unresearched` 恒为 true）——**这是修复而非回归**，且刻意不填 `source_artifact_version_id`（语义不符 + 无条件唯一约束会挡住 MCP 链允许的重复桥接） |
| 6 | 投影幂等 + owner check | ✓ 成立 | `_assert_owner` 在 service 内、**早于 `map_merged_plan_to_coding_plan`**（晚一步即构成跨会话读取他人完整方案正文）；`actor_user_id` 必填无默认值（有默认值会让漏传方静默获得 `"system"` 绕过判定）；端点侧三层纵深（只读前置解析 → service 内判定 → 投影后落点复核）；「不存在」与「无权限」措辞逐字一致，不泄漏存在性 |
| 7 | BL-01 修复真实解决生产绑定形态，且未削弱越权防护 | ✓ 成立 | 见 §4 |

---

## 4. BL-01 专项核验

原缺陷形状：整套测试手工 `bind_contextvars(user_id=<真实 id>)`，而生产中间件 `RequestLogContextMiddleware._bind` 写的是硬编码占位 `user_id="system"`（它早于 DRF 认证执行），`LogContextMixin` 全仓无视图继承 ⇒ `update_coding_plan` 在生产恒早退，785 行新测试无一条按生产形态调用。

修复的三个面，逐条核验：

1. **生产绑定链路打通**。`ChatStreamView.post` 补 `rebind_user(resolve_user_id(request))`；**生成器体内**另行 `bind_contextvars`（关键时序：`post` 返回 `StreamingHttpResponse` 后中间件 `finally` 立即 `clear_request_context()`，生成器在那之后才被 ASGI handler 消费）；生成器 `finally` 清理，防止泄漏到同 worker 复用的后续任务。
2. **有按真实绑定路径的测试**。`tests/test_log_context_propagation.py::test_chat_sse_generator_binds_real_user` 先 `clear_request_context()` 复现生产时序，再驱动 `view._stream_events(...)`，断言生成器体内 `user_id == "42"` 且 `source == "chat_sse"`，并断言流结束后上下文已清空。另有 `tests/test_coding_tools.py` 的 `as_production_request_context` fixture —— 它按中间件真实形态绑 `user_id="system"`，`TestUpdateCodingPlanActorResolution` 全组用它而**刻意不用** `as_owner`。
3. **越权防护未被削弱**。归属主体的退路取的是**服务端注入**的 `conversation.created_by_id`，而 `conversation_id` 由 `chat_runner._build_tool_specs` 从模型可见 schema 剔除后闭包注入（`chat_runner.py:677-678`，且 `allowed = set(_props) - set(_injected)` 使模型自造的同名字段被 drop 并告警）—— 模型改不了它。退路**不是**「被改写 plan 的会话创建者」（那等于让攻击者挑他人 `plan_id` 自选身份）。此外：
   - `_context_user_id()` 仍拒绝 `"system"` 哨兵（`test_context_user_id_still_refuses_system_sentinel` 锁住这条纪律不因修复而松动）；
   - MN-04 把 legacy `session_id` 分支的会话一致性判定**提前到补 FK 的两次写之前**，即防护被**加强**而非放松（`test_update_legacy_session_of_another_conversation_writes_nothing` 断言 `CodingPlan` 计数与 `session.coding_plan_id` 均未被污染）；
   - `test_update_rejects_plan_of_another_conversation` 断言拒绝措辞与「不存在」逐字一致且受害者正文零改动。

verifier 独立反向对照（§5 NC-6 / NC-8）确认这两处若回退即变红。

---

## 5. Verifier 独立反向对照

不采信 REVIEW 自报的对照结论，逐条自行改坏 → 跑测 → 还原（`git status` 已确认工作区仅剩一处 GSD 记账改动）：

| # | 改坏点 | 结果 |
|---|---|---|
| NC-1 | `TechPlanCard.isUnresearched` 允许清单 → 拒绝清单（`=== 'draft'`） | **7 failed** / 56 passed |
| NC-2 | 删除 `codingPlanRuntime` 入口的 `plan_id` 守卫 | **4 failed** / 59 passed |
| NC-3 | store 层无条件注入 `acknowledge_unresearched = true` | **1 failed** / 62 passed |
| NC-4 | 服务端 gate 允许清单 → 拒绝清单 | **failed**：`test_draft_gate_unknown_provenance_requires_confirm` |
| NC-5 | 删除 `aproject` 里的 `_assert_owner` | **failed**：`test_forbidden_actor_cannot_be_sentinel_or_blank`、`test_reject_cross_conversation_source_without_leaking_body` 等 |
| NC-6 | 删除 `update_coding_plan` 的 BL-01 退路 | **failed**：`TestUpdateCodingPlanActorResolution` 多条 |
| NC-7 | 导出器允许清单 → 拒绝清单 | **failed**：`test_unknown_provenance_still_gets_draft_notice_and_hides_raw_value` |
| NC-8 | 删除 SSE 生成器体内的用户重绑 | **failed**：`test_chat_sse_generator_binds_real_user` |

结论：**没有发现「不写实现也会绿」的用例**。REVIEW 已抓到的那一例（HI-01：240 行绿色 spec 里用 stub 组件掩盖真实交棒缺口）确已修复 —— `OrchestratedPlanCard.spec.ts:270-353` 改用**真实 `TechPlanCard`**（仅 `Badge` / `Button` / `Input` / `Checkbox` / `Command*` / `Dialog*` / `AlertDialog*` / `Select*` 等叶子 UI 原语 passthrough），断言的是渲染出的仓库行与方案正文，删掉两行 props 即变红。verifier 未在其余 spec 中发现同款形状。

---

## 6. 已知预期行为（**不是**缺陷 / 回归）

**迁移 0033 把 `provenance` default 设为 `draft`，存量 `CodingPlan` 行全部变草稿。** 因此升级后：

- 每一张历史方案卡都会显示「未经代码调研」告警横幅与头部 warning 徽标；
- 任何历史方案送编码都会命中一次阻断式确认弹层；
- 历史方案的飞书导出物会带告示块；
- 历史 session 的 `execution_spec.unresearched` 为 `true`。

这是 RELY-01 的**预期结果**：存量行确实是 SPINE-02 之前的徒手产物，保守标注在事实层正确。109-08 must-have 已把它作为 backstop 显式登记，此处如实记录以免被后续读者误判为回归。唯一的例外是 MCP 桥接链——它经 MN-01 显式标 `ORCHESTRATED`（其正文来自 `McpCodingPlanVersion`，而 MCP 端 `create_coding_plan` 早在 Phase 94 就 delegate 到统一编排，**是**编排产出）。

---

## 7. 已接受债务（5 条 LOW，verifier 复核后同意不阻断）

| ID | 内容 | verifier 复核结论 |
|---|---|---|
| LO-01 | gate 拒绝后重开的弹层是死胡同（`void openUnresearchedDialog()` 丢掉 promise，用户在新弹层里确认后什么都不会发生） | **同意为低后果，但确是真实用户可见缺陷。** 触发条件苛刻：前端闸门已在提交前拦住所有 `provenance != orchestrated` 的方案，服务端拒绝只在前后端 provenance 认知不一致（如 props 陈旧）时才发生；用户可回到原「确认编码」按钮重走。建议按 REVIEW 方案 (a)（只发 toast、不重开弹层）在后续 quick 中收口 |
| LO-02 | `orchestratedPlanData` 用 `toolCalls.find`，同一条消息内两次编排调用会让两张卡拿到同一个 `artifact_version_id` | **同意。** 形状照抄既有 `codingPlanData`（pre-existing）；编排工具是阻塞式，同轮多次调用概率低。但代价是「投影出的是另一份方案」这类看不出来的错，建议不要长期挂账 |
| LO-03 | `create_coding_plan` 的 `conversation_id` 已不决定投影落点却不做一致性校验 | **同意为低后果。** 跨**用户**的越权已由 service 内 `_assert_owner` 挡死（NC-5 验证）；残留面仅限**同一用户**在会话 B 里传会话 A 的 `artifact_version_id`，plan 落在 A 下。HI-02 修复后正文与 provenance 随工具结果直达 props，不再触发「空正文 + 误挂草稿横幅」的失效面，实际影响退化为 sessions 状态不在本会话刷新。HTTP 端点已有该道纵深复核，工具路径照抄即可 |
| LO-04 | `_DRAFT_NOTICE` 插在了 `_STATUS_LABEL` 的注释块与定义之间 | **同意。** 纯可读性，零行为影响 |
| LO-05 | ROADMAP 109-02 条目仍写「条件唯一约束」，实现是**无条件**唯一约束 | **同意，但建议尽快订正。** 实现是对的（带 `condition` 会在 MySQL 上被 `_unique_supported()` 静默跳过，理由已写在 `models.py:311-319`）；文档留错会让后续评审按错误前提判断「约束是不是漏了 condition」。这是文档改动，不占 phase 预算 |

---

## 8. 明确未验证的部分

- **真实飞书投递**：只验证到 markdown 组装与 `provenance` 判定，`create_document` 的真实调用未跑（无凭证）。
- **真实 Runner / 容器执行**：`CodingExecutionSpec.unresearched` 只验证到出现在 `as_dict()` 与 dispatch payload；容器侧是否消费不在本 phase 边界。
- **浏览器真实渲染与焦点行为**：焦点陷阱由 reka-ui `AlertDialog` 提供，happy-dom 下无法断言真实焦点循环；`label` 包裹与 `aria-disabled` 已在源码层核对。
- **生产存量数据规模**：迁移 0033 的影响面（§6）须在生产确认。
- **`render_merged_plan_markdown` 的 lark_md 观感**：109-VALIDATION 第 10 条已裁定接受现状，观感须人判。
- **三个受沙箱限制的测试文件**：`tests/services/test_commit_index.py` / `tests/services/test_commit_index_integration.py` / `tests/mcp_tools/test_grep_repository.py` 按测试环境说明排除（临时目录 `git init` 被文件系统沙箱阻断）。verifier 已确认这三个文件均不在本 phase 的 49 个改动文件内，与本 phase 无耦合。

---

## 9. 其它观察（不影响判定）

- 工作区存在一处**未提交**改动：`.planning/STATE.md`（GSD 记账字段：`last_updated` / `completed_plans` 24→31 / `stopped_at` 转义清理）。非代码改动，由 orchestrator 一并处置。
- 全量后端跑时观察到若干条 `database table is locked` 的 **structlog 日志行**（SQLite 并发写观测表），落在 best-effort 观测路径且被吞，未造成任何测试失败——符合「观测代码绝不反噬业务」的纪律。
- 本次全量后端为 **8106 passed**，高于编排者给出的参考基线 3500（后者应为子集口径）；前端全量 **1425 passed / 198 files**，同样高于参考基线 479/51。两侧均零失败。

---

_Verified: 2026-07-31T03:38:41Z_
_Verifier: Claude (gsd-verifier)_
_Method: goal-backward + 8 组独立反向对照 + 全量双端测试自跑_
