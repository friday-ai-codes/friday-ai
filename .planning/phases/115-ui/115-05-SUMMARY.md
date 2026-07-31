---
phase: 115-ui
plan: 05
subsystem: blueprint-section-rendering
tags: [frontend, vue3, sections, cards, scope-narrowing, mutation-tested, i18n-gap]
requires:
  - "115-03：`BlueprintBlockList.vue`（十一处块序列的唯一下游，props/emits 逐字照它）、`BlueprintCitationChip.vue`（关联段的引用 chip）、`SelectionPayload`（`import type` 复用，⛔ 未重写）"
  - "115-02：`~/types/blueprint` 全量契约（本 plan 零新增类型）、i18n `knowledge.blueprints.*`、safelist 12 图标、源码守卫 spec"
  - "既有可复用件：`~/components/common/CompactEmptyState.vue`（`icon` 收裸名）、`~/components/ui/{table,collapsible,badge}`、`.card` + `px-5 py-3.5` / `p-5` 卡片骨架"
provides:
  - "`web/src/components/blueprint/sections/RequirementSpecSection.vue` —— 段 0：目标 / 背景 / 功能点卡（⭐ 挂 `id=\"fp-<id>\"` 跨段锚点）"
  - "`web/src/components/blueprint/sections/RepoAssociationsSection.vue` —— 段 1：`lg:grid-cols-2` 网格 + 空态"
  - "`web/src/components/blueprint/RepoAssociationCard.vue` —— UI-SPEC §6.3 逐行；role 双色 / fitness 三档 / ⭐ SC-3 跳仓库页 / cross_team / confirmed_at_gate"
  - "`web/src/components/blueprint/sections/CurrentStateSection.vue` —— 段 2：按仓分组 + kind 四档 + ⭐ 缺引用质量信号 + 功能点 chip 跨段跳转"
  - "`web/src/components/blueprint/sections/ImplementationOverviewSection.vue` —— 段 3：三层 + ⭐ 波次泳道纯客户端筛选"
  - "`web/src/components/blueprint/ImplementationItemCard.vue` —— change_type 四档 + 四分区（含 `files_touched` 紧凑表）"
  - "`web/src/components/blueprint/sections/ApiContractsSection.vue` —— 段 4：卡片网格 + 空态（⛔ 不 expose 派生值）"
  - "`web/src/components/blueprint/ApiContractCard.vue` —— UI-SPEC §6.6 逐行；⭐ `availability` 只从 `data_source` 读 + `id=\"api-<id>\"` 跨段锚点"
  - "`web/src/components/blueprint/sections/ImpactAnalysisSection.vue` —— 段 5 薄壳 + 空态"
  - "`web/src/components/blueprint/ImpactMatrixTable.vue` —— 五块 + ⭐ 窄屏卡片堆叠降级 + `reversible === false` 严格判等"
  - "`web/src/components/blueprint/sections/InteractionFlowsSection.vue` —— 段 6：⭐ 时序图经前端合成块交给块序列（threads 恒空）+ 步骤表 + 备选路径"
  - "`web/src/components/blueprint/sections/MustHavesSection.vue` —— 段 7：⭐ 全文唯一不走块序列、不收 blockCtx 的正文段"
  - "`web/src/components/blueprint/sections/DecisionLogSection.vue` —— 段 8：⭐ 同样不接批注层 + `open-thread` 语义定夺 + 段尾 `deferred_ideas` 折叠"
  - "`web/src/components/blueprint/BlueprintAssociationsSection.vue` —— 段 9：⭐ SC-4 范围收窄后的两块，零关联端点调用"
  - "两个测试文件共 **37 例**：`__tests__/mustHaves.spec.ts`(8) / `__tests__/sections.spec.ts`(29)"
affects:
  - "115-06 页面装配：按本 SUMMARY §2 的 props/emits 逐字表接线；⭐ 十个 `<section id>` 容器与导航项**由页面无条件渲染**（P-4），本层组件只决定段内出不出内容"
  - "115-06 需要接住两个跨段跳转锚点：`fp-<feature_point_id>`（`RequirementSpecSection` 的功能点卡）与 `api-<contract_id>`（`ApiContractCard` 根元素），88px 偏移常量归页面"
  - "⚠️ **回报给 115-06 的 i18n 缺口（21 个键）**：见 §6，本 plan 按 §13.2 一律回报而不自补，21 处都有可用降级"
  - "⭐ **SC-4 范围收窄**：关联段只做「本蓝图引用了」+「关联项目」，反向「被谁引用」顺延 Phase 116（已在 STATE Pending Todos 登记）"
  - "源码守卫扫描面从 22 个文件增至 **36 个**，6 条断言全绿"
tech-stack:
  added: []
  patterns:
    - "blockCtx 五项原样透传 + 四个 emit 逐个转发：段组件退化成纯排版件，批注层只有一个实现点"
    - "前端合成块：把非 Block[] 的裸字段（`flow.mermaid`）包成一个 `type: 'mermaid'` 的块交给既有块序列渲染，`threads` 恒传空数组以示「后端不会往这里挂线程」"
    - "缺 i18n 键时的三档降级：① 复用语义最近的既有键 ② 不渲染文字小标题、身份交给 `data-field` ③ 枚举/布尔标记渲染 schema 原样 token，颜色由 variant 承载"
    - "零约束裸 array 的收窄集中在 computed：模板里零 `item.x` 裸访问，缺键统一落到「—」"
    - "窄屏降级用双份结构（`hidden md:table` + `md:hidden`），⛔ 不用横向滚动表"
key-files:
  created:
    - web/src/components/blueprint/sections/RequirementSpecSection.vue
    - web/src/components/blueprint/sections/RepoAssociationsSection.vue
    - web/src/components/blueprint/sections/CurrentStateSection.vue
    - web/src/components/blueprint/sections/ImplementationOverviewSection.vue
    - web/src/components/blueprint/sections/ApiContractsSection.vue
    - web/src/components/blueprint/sections/ImpactAnalysisSection.vue
    - web/src/components/blueprint/sections/InteractionFlowsSection.vue
    - web/src/components/blueprint/sections/MustHavesSection.vue
    - web/src/components/blueprint/sections/DecisionLogSection.vue
    - web/src/components/blueprint/RepoAssociationCard.vue
    - web/src/components/blueprint/ImplementationItemCard.vue
    - web/src/components/blueprint/ApiContractCard.vue
    - web/src/components/blueprint/ImpactMatrixTable.vue
    - web/src/components/blueprint/BlueprintAssociationsSection.vue
    - web/src/components/blueprint/__tests__/mustHaves.spec.ts
    - web/src/components/blueprint/__tests__/sections.spec.ts
  modified:
    - web/src/components.d.ts
decisions:
  - "⭐ `decision_log` 的 `open-thread` 语义定夺 = 「跳转到该决策对应的线程」；`thread_id` 存在才渲染入口按钮，不存在则不渲染（⛔ 不是「在本段发起批注」、⛔ 不留点了没反应的按钮）"
  - "⭐ SC-4 范围收窄落地：关联段只做「本蓝图引用了」+「关联项目」，零调用两个必然 404 的反查端点；顺延 Phase 116"
  - "⭐ `unsuitable` 的「替代建议」按 `fitness.reasons` 自由文本原样展示，⛔ 不补 schema 字段（同时定夺 STATE 登记的「Phase 112 残留 PARTIAL / FLOW-02」）"
  - "删除 `RequirementSpecSection` / `RepoAssociationCard` 上恒不触发的 `goto-anchor` emit（沿用 115-03 订正一「声明恒不触发的 emit 是死接口」的判例）"
  - "`regression_scope` 改为行式呈现而非带列头的表（缺「区域 / 理由」列头文案键，⛔ 不发明中文文案）"
  - "缺 i18n 键的枚举与布尔标记一律渲染 schema 原样 token（`intent` / finding `kind` / `change_type` / `actor` / `cross_team` / `reversible=false`），颜色由 `variant` 承载、身份由 `data-*` 承载"
  - "测试里把折叠组件拍平成直通 div（reka-ui 默认收起时不挂载内容），才能断言折叠区里交出去的块序列"
metrics:
  duration: "约 1.5 小时"
  completed: 2026-08-01
  tasks: 3
  commits: 3
  tests_added: 37
---

# Phase 115 Plan 05: 十个导航段的结构化渲染 Summary

**一句话**：把蓝图 content 的**十个可导航段全部渲染出来**——14 个新建组件（约 3000 行）+ 2 个测试文件（**37 例全绿**），而**一行批注逻辑都没有重复实现**：十一处块序列一律经 `BlueprintBlockList` 透传 blockCtx，两个「零 `block_id`」的特例段（`must_haves` / `decision_log`）明确不接批注层且组件内写明原因，SC-4 的范围收窄被写进 docstring 与用例而不是靠 404 兜底掩盖。三处后端口径在 UI 侧各有一条**可被变异逼红**的对称防线（`availability` 不回落顶层 / `reversible` 严格判等 / finding 缺引用亮质量信号）。**零既有源文件修改（生成物除外）、零新增依赖、零原始 HTML 注入、零颜色字面量、后端零改动。**

---

## 1. 门禁与基线（对比 115-04 的 1565/1）

| 门 | 结果 | 对比基线 |
|---|---|---|
| `pnpm exec vitest run` | **1602 passed / 1 skipped（1603 例，210 文件）** | 基线 1565 / 1（208 文件）⇒ **+37 例 / +2 文件，零回归** |
| `pnpm type-check`（`vue-tsc --noEmit`） | **通过（exit 0）** | 同基线 |
| `pnpm lint`（`eslint .`） | **111 problems（106 errors / 5 warnings）** | ⭐ **与基线逐个相同 ⇒ 零新增**；`eslint src/components/blueprint/` → **0 problems** |
| 源码守卫 `blueprint-source-guard.spec.ts` | **6 条全绿**，扫描面 22 → **36 个文件** | 断言 6（`refetchInterval`）与 10（`edit-block`）在更大扫描面上仍绿 |

那 1 条 skip 是**既有**的 `src/layouts/__tests__/default.spec.ts:66`，与本 plan 无关。lint 判据沿用 115-02 §1 的结论：**「自己碰的文件零新增问题」**，⛔ 不是整体退出码为 0（那需要先清 106 个历史 error，超出相位边界）。

新增用例分布：

| 文件 | 例数 | 锁住什么 |
|---|---|---|
| `__tests__/mustHaves.spec.ts` | 8 | ⭐ §20 断言 9 两半（段被渲染 + 段内 mark 计数 0）/ 不复用块序列 / 全空与整键缺失 / 部分子块空的正反并列 / 缺键渲染「—」 |
| `__tests__/sections.spec.ts` | 29 | 七段透传 blockCtx + 零批注 / role 双色 / SC-3 跳转 / cross_team 与 confirmed_at_gate 正反 / 缺引用正反 / ⭐ `availability` 三档含「顶层有而 data_source 无」的证伪 / `reversible` 严格判等正反 / mermaid 合成块有无 / 两个跨段跳转载荷 / `decision_log` 四条 / ⭐ 关联段零端点调用 / **P-4 的段内半边（九段空数据仍渲染内容区）** |

---

## 2. ⭐ 十段组件的 props / emits 逐字表（115-06 照此接线）

**通用约定**：`blockCtx` = `threads` / `citations` / `readonly` / `activeThreadId` / `showClosed` 五项，全部有默认值，**原样透传**给 `BlueprintBlockList`。凡收 blockCtx 的组件都统一转发这四个 emit：

```ts
'thread-click':          [threadId: string, allThreadIds: string[]]   // 115-03 的两参签名
'citation-click':        [citationId: string]
'selection-comment':     [payload: SelectionPayload]                  // import type 自 BlueprintBlockList.vue
'cross-block-selection': []
```

| # | 段 key | 组件 | 段专属 props | 收 blockCtx？ | 额外 emits |
|---|---|---|---|---|---|
| 0 | `requirement_spec` | `sections/RequirementSpecSection.vue` | `spec?: BlueprintRequirementSpec \| null` | ✅ | — |
| 1 | `repo_associations` | `sections/RepoAssociationsSection.vue` | `associations?: BlueprintRepoAssociation[]`、`repoNames?: Record<string,string>` | ✅ | — |
| 2 | `current_state_analysis` | `sections/CurrentStateSection.vue` | `analysis?: BlueprintCurrentStateAnalysis[]`、`repoNames?` | ✅ | ⭐ `'goto-anchor': [domId]` |
| 3 | `implementation_overview` | `sections/ImplementationOverviewSection.vue` | `overview?: BlueprintImplementationOverview \| null`、`repoNames?` | ✅ | ⭐ `'goto-anchor': [domId]` |
| 4 | `api_contracts` | `sections/ApiContractsSection.vue` | `contracts?: BlueprintApiContract[]`、`repoNames?` | ✅ | — |
| 5 | `impact_analysis` | `sections/ImpactAnalysisSection.vue` | `impact?: BlueprintImpactAnalysis \| null`、`repoNames?` | ✅ | — |
| 6 | `interaction_flows` | `sections/InteractionFlowsSection.vue` | `flows?: BlueprintInteractionFlow[]` | ✅ | ⭐ `'goto-anchor': [domId]` |
| 7 | `must_haves` | `sections/MustHavesSection.vue` | `mustHaves?: Partial<BlueprintMustHaves> \| null` | ⛔ **不收** | 无 emits |
| 8 | `decision_log` | `sections/DecisionLogSection.vue` | `decisionLog?: unknown[]`、`deferredIdeas?: unknown[]` | ⛔ **不收** | ⭐ `'open-thread': [threadId]` |
| 9 | `associations` | `BlueprintAssociationsSection.vue` | `artifactId: string`（必填）、`citations?: Record<string,Citation>`、`projectId?: string \| null`、`projectName?: string` | ⛔ **不收** | `'citation-click': [citationId]` |

### 2.1 四张卡（由上表的段组件内部渲染，115-06 一般不直接用）

| 组件 | 卡专属 props | 收 blockCtx？ | emits |
|---|---|---|---|
| `RepoAssociationCard.vue` | `association: BlueprintRepoAssociation`（必填）、`repoName?: string` | ✅ | 四个透传 |
| `ImplementationItemCard.vue` | `item: BlueprintImplementationItem`（必填）、`moduleName?`、`repoName?` | ✅ | 四个透传 |
| `ApiContractCard.vue` | `contract: BlueprintApiContract`（必填）、`repoName?`、`supportRepoName?` | ✅ | 四个透传 |
| `ImpactMatrixTable.vue` | `impact?: BlueprintImpactAnalysis \| null`、`repoNames?` | ✅ | 四个透传 |

### 2.2 ⚠️ 与 PLAN 的 emits 差异（一处，见 Deviation 1）

PLAN 给 `RequirementSpecSection` 与 `RepoAssociationCard` 各列了一个 `goto-anchor`，但这两处**没有任何触发源**（需求规格段是跳转的**目标**不是来源；仓库卡的 `constraint_refs` 在本相位没有对应 DOM 锚点）。按 115-03 订正一「声明一个恒不触发的 emit 是死接口，会误导接线方去监听它」的判例**删掉**。115-06 若在这两处写 `@goto-anchor` 只会退化为无害的 fallthrough attr。

---

## 3. ⭐ 跨段跳转的锚点约定（115-06 必须接住）

| 锚点 id | 由谁挂 | 由谁 emit | 载荷 |
|---|---|---|---|
| `fp-<feature_point_id>` | `RequirementSpecSection` 的功能点卡根元素 | `CurrentStateSection`（finding 的 `related_feature_points` chip）、`ImplementationOverviewSection`（模块卡的关联功能点 chip） | `goto-anchor('fp-fp_1')` |
| `api-<contract_id>` | `ApiContractCard` 根元素 | `InteractionFlowsSection`（步骤表的 `api_ref` chip） | `goto-anchor('api-api_1')` |
| `impl-<item_id>` | `ImplementationItemCard` 根元素（预留，本 plan 无 emit 源） | — | — |

⭐ **段组件内零滚动实现**：`rg -n "window.scrollTo|scrollIntoView"` 在本 plan 全部 14 个组件里**零命中**。页面统一处理 88px 偏移与 2s ring 高亮（T-115-47：段内自己滚会与 `AnchorNavLayout` 的偏移常量分叉）。

---

## 4. ⭐ 三个「最容易做错」的点各自的落地形态

### 4.1 `must_haves` 段的四条约束（§6.9）

| 约束 | 落地 | 证据 |
|---|---|---|
| 不接批注层 | 组件**不收 blockCtx**，无任何划线标记 | 用例 2（段内 mark 计数 == 0）；MUT-2 逼红 |
| 不复用 `BlueprintBlockList` | 全段自渲染（`<ul>` / 紧凑表 / 箭头行） | 用例 3（`findComponent` 不存在 + html 不含块序列 testid） |
| 三块同空 / 整键缺失 ⇒ 整段不出内容卡 | `hasContent` 为假时组件根 `v-if` 掉 | 用例 4a / 4b |
| ⭐ 段容器由页面无条件渲染 | 本组件根是普通 `<div data-testid>`，**不含 `<section id>`** | docstring 写明分工；页面侧归 115-06 |

组件 docstring 逐字写明了原因：`iter_blocks` 不走查 `must_haves` ⇒ 三个数组零 `block_id` ⇒ 后端不会往这里挂线程 ⇒ 接上批注层只会得到死码。

### 4.2 `decision_log` 的 `open-thread` 语义定夺

**语义 = 「跳转到该决策对应的线程」**（⛔ 不是「在本段发起批注」）。落地：条目取 `item?.thread_id`，**存在时**才渲染 `data-testid="blueprint-decision-goto-thread"` 的按钮并 emit；不存在则该按钮不渲染。用例 8a / 8b 正反并列。

`decision_log` / `deferred_ideas` 的**逐项收窄集中在 computed**（模板里零 `item.x` 裸访问，已用脚本核实），缺键统一落到 `—`；⭐ **`answer` 键被显式渲染**（用例 8c 断言其文本出现）——它是唯一有下游消费方的键。非法 `decided_at` 原样显示（用例 8e）。

⛔ `execution_plan` 在九个段组件的**模板里零命中**（脚本已核实）；不渲染的理由写进了 `DecisionLogSection` 的 docstring。

### 4.3 ⭐ SC-4 的范围收窄（最终形态 + 证据链）

**本相位交付两块**：

1. **本蓝图引用了** —— `content.citations` 引用池按 `source_type` 分组统计（九档文案键复用 `citation.source*`）+ 每组下可点 `BlueprintCitationChip`，点击经 `citation-click` 交给页面开**同一个**二级预览弹层。**零端点。**
2. **关联项目** —— `meta.project_id` + `RouterLink to="/projects/{projectId}"`（路由已实测：`pages/projects/index.vue:230` 同款写法）。

**顺延 Phase 116 的一块**：「引用了本蓝图 / 关联知识」。证据链：那两个反查端点查的是 `initiatives.Artifact` 投影出来的 KnowledgeEntity（`server/knowledge/artifact_associations.py:75`），而蓝图存在 `delivery.Artifact` ⇒ 拿蓝图 id 去调**必然 404 / 空**。⛔ 靠 404 兜底糊过去等于把「这块没做」伪装成「暂时没数据」。

**兑现证据**：`rg "getRelated|getArtifactAssociations" BlueprintAssociationsSection.vue` **零命中**；用例 9a 用 `vi.mock('~/api')` 断言两个 mock 的 `toHaveBeenCalledTimes(0)`。**已在本 SUMMARY §7 与 STATE 的 Pending Todos 双处登记。**

---

## 5. ⭐ 变异验证（执行期实跑，四条防线各自被逼红）

每条变异后都还原并核实工作树干净。

| # | 变异 | 结果 | 负向对照 |
|---|---|---|---|
| MUT-1 | `MustHavesSection` 的 `hasContent` 恒 `false`（漏渲 `must_haves`） | **用例 1 / 5 / 6 / 7 转红**（`4 failed \| 4 passed`） | 用例 2（mark 计数 0）、3（不复用块序列）、4a/4b（空态）仍绿 ✅ —— 正确：它们断言的是「**不**出现」 |
| MUT-2 | 给 `must_haves` 的 truths 接上划线标记 | **用例 2 转红**（`1 failed \| 7 passed`） | 用例 1 / 3 仍绿 ✅ |
| MUT-3 | `ApiContractCard` 的 `availability` 回落读顶层 | **用例 5b 转红** | 5a / 5c 仍绿 ✅ |
| MUT-4 | `ImpactMatrixTable` 的 `reversible` 改真值判断（`!item.reversible`） | **用例 6b 转红** | 6a（`false` ⇒ 有徽标）仍绿 ✅ —— ⭐ **正是要逮的陷阱形状**：只写 6a 一条逮不住 |

⭐ **MUT-4 的形状与 115-04 的 MUT-5 同类**：真值判断下「缺键」那条红而「显式 false」那条绿 —— 正反并列用例的存在理由就在这里。

---

## 6. ⚠️ 回报给 115-06 的 i18n 缺口（21 个键，⛔ 本 plan 按 §13.2 未自补）

i18n 三处追加点已由 115-02 一次做完并对本相位关闭 ⇒ **回报而不自补**（沿用 115-03 §9 / 115-04 §7 的判例）。**21 处都有可用的降级实现，补键后各只需换一处 `t()` 调用或加回一行 `<p>`，无结构改动。**

降级分三档：**① 复用语义最近的既有键**；**② 不渲染文字小标题，身份交给 `data-field`**；**③ 枚举 / 布尔标记渲染 schema 原样 token**（颜色由 `variant` 承载、身份由 `data-*` 承载，语义不丢，只是没中文名）。

| # | 建议键 | 建议文案 | 用在哪 | 当前降级 |
|---|---|---|---|---|
| 1 | `section.goal` | 目标 | 需求规格段 | ②（`data-field="goal"`） |
| 2 | `section.background` | 背景 | 需求规格段 | ②（`data-field="background"`） |
| 3–5 | `spec.intentGreenfield` / `...Brownfield` / `...Fix` | 净新增 / 存量改造 / 缺陷修复 | 功能点徽标 | ③（`data-intent` + variant 三色） |
| 6 | `repo.rationale` | 选仓理由 | 仓库卡折叠组头 | ① 复用 `repo.role`（关联角色）+ `data-field="rationale"` |
| 7 | `repo.capabilitiesUsed` | 会被用到的能力 | indirect 专属分区 | ① 复用 `knowledge.entity.associations.capabilities`（关联能力）**跨子树** |
| 8 | `repo.crossTeam` | 跨组协作 | routing 行徽标 | ③（`data-cross-team="true"` + warning） |
| 9–10 | `repo.confirmedAtGate` / `repo.notConfirmedAtGate` | 已在确认门锁定 / 未经确认门锁定 | 卡底徽标 | ① 复用 `thread.kindRepoConfirmation`（确认门）+ 图标 + `data-confirmed-at-gate` 两档 |
| 11 | `section.currentStateSummary` | 现状综述 | 现状分析组内 | ②（`data-field="summary"`） |
| 12–15 | `state.kindCapability` / `...Gap` / `...Risk` / `...Convention` | 能力 / 缺口 / 风险 / 约定 | finding 徽标 | ③（`data-kind` + variant 四色） |
| 16 | `state.missingCitations` | 缺引用 | ⭐ 质量信号徽标 | ① 复用 `citation.empty` + `data-missing-citations="true"` + destructive |
| 17–20 | `impl.changeTypeCreate` / `...Modify` / `...Remove` / `...IndirectRefine` | 新建 / 改动 / 删除 / 间接完善 | 实现项徽标 | ③（`data-change-type` + variant + 图标四档） |
| 21 | `impl.existingIntegration` | 与既有功能如何配合 | 实现项分区 | ②（`data-field="existing-integration"`） |
| 22 | `impl.testStrategy` | 测试策略 | 实现项分区 | ②（`data-field="test-strategy"`） |
| 23 | `impl.waveCount` | wave {n} · {c} 项 | 波次泳道条 | ③（`wave {n}` + 计数徽标） |
| 24 | `api.availabilityUnknown` | 未标注 | ⭐ `availability` 读不到 | ① 复用 `quality.noData`（暂无数据）+ `data-availability="unknown"` |
| 25 | `impact.irreversible` | 不可逆 | 数据迁移徽标 | ③（`data-irreversible="true"` + destructive，可见串为 `reversible=false`） |
| 26–29 | `flow.actorUser` / `...Frontend` / `...Backend` / `...Service` | 用户 / 前端 / 后端 / 服务 | 步骤表 actor 徽标 | ③（`data-actor` + variant 四档） |
| 30 | `section.deferredIdeas` | 本方案明确不做的事（{n}） | 决策段尾折叠组头 | ③（原样键名 `deferred_ideas` + 条数徽标） |
| 31 | `decision.gotoThread` | 查看对应线程 | 决策条目跳转入口 | ① 复用 `annotation.sidebarToggleEmpty`（批注）+ 图标 |
| 32 | `associations.citedByThis` | 本蓝图引用了 | 关联段块头 | ① 复用 `knowledge.relation.REFERENCES`（引用文档）**跨子树** |

> **三处跨子树复用**（`knowledge.entity.associations.capabilities` / `knowledge.relation.REFERENCES` / `projects.workbench.deps.projectsTitle`）都是真实稳定键、语义贴合，但补齐本子树键后**应当换回**，以免蓝图文案跟着别的功能改。

⚠️ **不是 safelist 缺口**：本 plan 运行期拼接的裸名只有 `change_type` 四档（`file-plus` / `file-pen-line` / `file-x` / `file-cog`）与 8 个空态图标（`file-text` / `folder-git-2` / `scan-eye` / `layers` / `link` / `alert-triangle` / `workflow`），**全部已在 `main.css` 的 `@source inline` 里**。写在模板里的字面量完整类名（`icon-[lucide--mouse-pointer-click]` / `icon-[lucide--check]` / `icon-[lucide--chevron-right]` / `icon-[lucide--message-square-dot]` / `icon-[lucide--external-link]` / `icon-[lucide--minus-circle]`）按 115-02 §8.2 的纪律**不需要** safelist —— Tailwind content 扫描直接命中源码，**缺席不是遗漏**。⛔ 本 plan 未追加 `main.css`。

---

## 7. 各段的空态规则表（⭐ P-4 的段内半边）

| 段 | 段内数据为空时 | 理由 |
|---|---|---|
| `requirement_spec` | `CompactEmptyState`（`lucide--file-text`） | required 键，空是异常信号 |
| `repo_associations` | `CompactEmptyState`（`lucide--folder-git-2`，`repo.empty`） | 同上 |
| `current_state_analysis` | `CompactEmptyState`（`lucide--scan-eye`） | 同上 |
| `implementation_overview` | `CompactEmptyState`（`lucide--layers`） | 同上 |
| `api_contracts` | `CompactEmptyState`（`lucide--link`，`api.empty`） | 「本方案不涉及接口」是合法结论，要说出来 |
| `impact_analysis` | `CompactEmptyState`（`lucide--alert-triangle`，`impact.empty`） | 同上 |
| `interaction_flows` | `CompactEmptyState`（`lucide--workflow`，`flow.empty`） | 同上 |
| `must_haves` | ⭐ **不渲染任何内容卡**（⛔ 不出空态卡） | §6.9 明令，对齐 `deferred_ideas` 的处理 |
| `decision_log` | `CompactEmptyState`（两个裸 array 都空时） | 可选键，但段容器已在导航里 |
| `associations` | `CompactEmptyState`（`lucide--link`，`citation.empty`） | 两块都空时 |

⭐ **无论哪一档，段容器（`<section id>`）与导航项都由 115-06 无条件渲染**：`AnchorNavLayout` 的 IntersectionObserver 只在 mount 时注册，条件渲染段容器会让左栏高亮**静默失效**（点击跳转仍正常，人工走查逮不住）。用例 10 覆盖了「九段空数据仍渲染各自内容区」这半边。

---

## 8. `data-testid` 完整清单（本 plan 新增 30 个）

| 归属 | testid |
|---|---|
| 段容器（内容区根） | `blueprint-requirement-spec` / `blueprint-repo-associations` / `blueprint-current-state` / `blueprint-implementation-overview` / `blueprint-api-contracts` / `blueprint-impact-analysis` / `blueprint-interaction-flows` / `blueprint-must-haves` / `blueprint-decision-log` / `blueprint-associations` |
| 需求规格 | `blueprint-feature-point`（配 `data-feature-point-id`，DOM id 为 `fp-<id>`） |
| 仓库关联 | `blueprint-repo-card`（配 `data-role` / `data-repository-id`）/ `blueprint-repo-open`（⭐ SC-3）/ `blueprint-repo-constraint-ref` / `blueprint-repo-capability` / `blueprint-repo-routing-score`；徽标身份 `data-verdict` / `data-cross-team` / `data-confirmed-at-gate` |
| 现状分析 | `blueprint-current-state-group` / `blueprint-finding`（配 `data-finding-id`）/ `blueprint-finding-missing-citations`（配 `data-missing-citations`）/ `blueprint-feature-point-chip` |
| 实现概述 | `blueprint-impl-module` / `blueprint-impl-item`（配 `data-change-type` / `data-wave`，DOM id 为 `impl-<id>`）/ `blueprint-impl-file` / `blueprint-impl-depends-on` / `blueprint-wave-lane` / `blueprint-wave-chip`（配 `data-wave`） |
| API 契约 | `blueprint-api-card`（配 `data-direction` / `data-contract-id`，DOM id 为 `api-<id>`）/ `blueprint-api-request` / `blueprint-api-response` / `blueprint-api-request-toggle` / `blueprint-api-response-toggle` / `blueprint-api-data-source` / `blueprint-api-availability`（配 `data-availability`）/ `blueprint-api-support-repo` |
| 影响矩阵 | `blueprint-impact-matrix` / `blueprint-impact-row` / `blueprint-impact-cards` / `blueprint-impact-card` / `blueprint-regression-row` / `blueprint-data-migration` / `blueprint-migration-irreversible`（配 `data-irreversible`） |
| 交互流程 | `blueprint-flow-card`（配 `data-flow-id`）/ `blueprint-flow-diagram` / `blueprint-flow-step` / `blueprint-flow-step-note` / `blueprint-api-ref-chip` / `blueprint-flow-alternative` / `blueprint-flow-alt-step` |
| 验收锚点 | `blueprint-must-haves-truths` / `-artifacts` / `-key-links` / `blueprint-must-haves-artifact-row` / `blueprint-must-haves-key-link-row` |
| 决策记录 | `blueprint-decision-entry` / `blueprint-decision-goto-thread` / `blueprint-deferred-ideas` / `blueprint-deferred-idea`；字段身份 `data-field="question\|answer\|decision\|decided-by\|decided-at\|applied-in-version"` |
| 关联 | `blueprint-associations-citations` / `blueprint-associations-group`（配 `data-source-type`）/ `blueprint-associations-project` / `blueprint-associations-project-link` |

---

## 9. Task Commits

| Task | 内容 | Commit | 变更 |
|---|---|---|---|
| 1 | 需求规格 / 仓库关联 / 现状分析三段与仓库关联卡 | `d030f673` | 4 文件 / +777 |
| 2 | 实现概述 / API 契约 / 影响范围 / 交互流程四段与三张卡 | `0ac9d393` | 7 文件 / +1560 |
| 3 | 验收锚点 / 决策记录 / 关联三段 + 37 例组件测试 | `293276ae` | 6 文件 / +1243 |

---

## 10. Deviations from Plan

### 1. `[Rule 1 - 死接口] 删掉 RequirementSpecSection 与 RepoAssociationCard 上恒不触发的 goto-anchor`

- **发现于**：Task 1
- **问题**：PLAN 给这两处各列了一个 `goto-anchor` emit，但它们**没有触发源**——需求规格段是跨段跳转的**目标**（挂 `fp-<id>` 锚点）而不是来源；仓库卡的 `rationale.constraint_refs` 在本相位没有任何对应 DOM 锚点（`requirement_spec.constraints` 本相位不渲染成可锚定元素）。
- **处理**：两处删掉该 emit，沿用 115-03 订正一的判例（「声明一个恒不触发的 emit 是死接口，会误导接线方去监听它」）。真正有触发源的三段（现状分析 / 实现概述 / 交互流程）都保留并有用例。115-06 若误写 `@goto-anchor` 只会退化为无害的 fallthrough attr。
- **文件**：`RequirementSpecSection.vue` / `RepoAssociationCard.vue` ｜ **Commit**：`d030f673`

### 2. `[§13.2 回报而不自补] 21 处 i18n 缺口`

- 详见 §6。21 处都有可用降级，⛔ **未修改 `zh-CN.json`**（`git diff` 为空）。其中三处是**跨子树复用**既有键，补齐本子树键后应换回。

### 3. `[Rule 3 - 阻塞] regression_scope 改为行式呈现而非带列头的表`

- **发现于**：Task 2
- **问题**：PLAN 要求 `regression_scope` 用「紧凑表」，但它的三列（区域 / 级别 / 理由）里**只有级别有 i18n 键**（`impact.level*`）。语义 `<table>` 必须有 `<th>`，而给两个列头发明中文文案会违反「缺键回报不自补」。
- **处理**：改为「级别徽标 + 区域 + 理由」的行式呈现（`data-testid="blueprint-regression-row"`），信息量与紧凑表一致、无需列头文案。补齐两个键后改回 `~/components/ui/table` 是**纯加法**。`affected_features` 的**矩阵表照 PLAN 用了真表**（五列的列头都能从既有键凑齐，含跨用的 `tabPanel.filterRepository`＝「涉及仓库」）。
- **文件**：`ImpactMatrixTable.vue` ｜ **Commit**：`0ac9d393`

### 4. `[Rule 1 - 自洽修正] 两处 docstring 字面量会触发本 plan 自己的验收断言`

- **发现于**：Task 1 与 Task 3 的验收复跑
- **问题**：① `CurrentStateSection` 的 docstring 为了说明「⛔ 段内不自行滚动」写了那个滚动 API 的字面量，正好命中本 plan 自己的「零命中」断言；② `BlueprintAssociationsSection` 的 docstring 按 PLAN 要写明证据链，而证据链里含那两个端点的函数名，正好命中「关联段零端点调用」的源码扫描。
- **处理**：两处改写成不含该字面量的等义中文表述（语义与纪律说明完整保留，证据链改为指向 `server/knowledge/artifact_associations.py:75` 的代码位置）。与 115-02 §12.3、115-03 Deviation 5、115-04 Deviation 6 **同一类**。
- **Commit**：`d030f673` / `293276ae`

### 5. `[判据澄清] decision_log 用 computed 归一化而非模板内逐项可选链`

- **性质**：PLAN 的验收脚本核对「模板里每个 `item.x` 都带可选链」，并允许「若改用 computed 归一化，则核对归一化函数内逐项 `?? '—'` 并在 SUMMARY 登记」——本实现走的是后者。
- **落地**：`decisions` / `deferred` 两个 computed 内经 `text(bag, key)` 逐键收窄，非字符串 / 空串一律落到 `PLACEHOLDER = '—'`；`formatTime` 对非法值原样返回。**模板里 `item.` 零命中**（脚本已核实输出 `optional chaining OK`）。用例 8c / 8e 覆盖「缺键渲染「—」不含 undefined」与「非法时间原样显示」。

### 6. `[测试环境事实] reka-ui 折叠区默认收起时不挂载内容`

- **发现于**：Task 3
- **现象**：`fitness.reasons` 交给块序列的断言最初转红，因为它在**默认折叠**的 `CollapsibleContent` 里，reka-ui 在收起态根本不渲染子树。
- **处理**：测试里把 `Collapsible` / `CollapsibleTrigger` / `CollapsibleContent` 三件拍平成直通 div（沿用 115-04 对 Portal 类组件的同款做法），断言的才是「组件把什么交给了块序列」而不是「reka-ui 此刻展开没有」。⛔ 未改动组件的默认折叠行为（那是 UI-SPEC §6.3 明确要的）。
- **文件**：`__tests__/sections.spec.ts` ｜ **Commit**：`293276ae`

### 7. `[执行事实登记] components.d.ts 是本 plan 唯一的既有文件改动`

- **性质**：`unplugin-vue-components` **自动生成**的声明文件，随新建组件自动重写。本次为**纯追加 14 行、零删除**（14 个新组件的类型声明），且被 eslint ignore。
- **判断**：与 115-02 §12.4、115-03 Deviation 8、115-04 Deviation 7 同一判例 —— CREATE-ONLY 约束针对**手写源文件**。`auto-imports.d.ts` 本 plan **未变动**（新组件全部走显式 import）。

### 8. `[环境事实] pnpm 10 的 workspace 漂移本次出现并已还原`

- 跑完前端门后 `web/pnpm-workspace.yaml` 出现 +8 行的 catalog 回填（115-02 §12.7 预警的现象）。提交前已 `git checkout --` 还原，三个提交内 `git diff web/package.json web/pnpm-lock.yaml web/pnpm-workspace.yaml` **零行**。

---

## 11. ⭐ UAT 清单（happy-dom 测不了的，交给 115-07 / 人工走查）

| # | 项 | 为什么自动化测不了 | 期望 |
|---|---|---|---|
| 1 | **交互流程的时序图实渲** | 测试里图表组件必 stub | 每条 flow 的图出 SVG；源码为空时只出步骤表、不留空容器 |
| 2 | **窄屏矩阵表的卡片堆叠** | happy-dom 无布局引擎，媒体查询不生效（双份结构在 DOM 里同时存在） | `< md` 只见卡片堆叠、`≥ md` 只见表；⛔ 全程不出现横向滚动条 |
| 3 | **`lg:grid-cols-2` 断点** | 同上 | 仓库关联卡与 API 契约卡在宽屏两列、窄屏一列，卡内示例双栏同步切换 |
| 4 | **波次泳道筛选的交互手感** | 逻辑已自动化（本地 ref），手感测不了 | 点击即筛、再点取消；筛选后列表不跳动；⛔ URL 不变 |
| 5 | **跨段跳转的滚动定位** | 需页面接线后才可测（emit 已有用例） | 点功能点 chip / `api_ref` chip 后滚动到位、顶栏不遮挡（88px 偏移）、目标 2s ring 高亮 |
| 6 | **验收锚点 `key_links` 的窄屏竖排** | 同 2 | `< md` 是「来源 / 通过 / 去向」三行标签值，`≥ md` 是一行箭头式 |
| 7 | **JSON 示例超 20 行的折叠** | 行数阈值逻辑可测，视觉可读性不可测 | 折叠时截断处不突兀，「展开全部 / 收起」切换正常（`block.expandAll` / `block.collapse`） |
| 8 | **21 处 i18n 降级的可读性** | 缺键是既定事实，不是 bug | 走查降级后的段是否仍读得懂；补键优先级按 §6 的顺序 |

---

## 12. 边界核算

| 检查 | 结果 |
|---|---|
| 本 plan 变更文件 | **16 个新建 + 1 个生成物**（`components.d.ts`，+14 行 / −0） |
| `git diff --name-only <base>..HEAD -- web/src \| rg -v "^web/src/components/blueprint/"` | 只有 `web/src/components.d.ts`（生成物，见 Deviation 7） |
| 四个禁改文件（`TechPlanCard.vue` / `RoutingDecisionPanel.vue` / `NodeDataTab.vue` / `ArtifactTimeline.vue`） | **`git diff` 全空** |
| 115-02 三处追加点（`zh-CN.json` / `main.css` / `api/index.ts`） | **`git diff` 全空** |
| 115-03 / 115-04 的 25 个产物 | **一个都未修改**（`BlueprintBlockList.vue` / `BlueprintCitationChip.vue` 只 import 不改） |
| `git diff --name-only <base>..HEAD -- server/` | **0 个文件** |
| `git diff web/package.json web/pnpm-lock.yaml web/pnpm-workspace.yaml` | **0 行**（零新增依赖，pnpm 漂移已还原） |
| `rg "sliceBlockText\|annotationClass\|blueprint-annotation-mark\|<mark"` 于本 plan 14 组件 | **零命中** |
| `rg "v-html\|hsl(\|#[0-9a-fA-F]{6}\|refetchInterval\|edit-block"` 于本 plan 14 组件 | **零命中** |
| `rg "window.scrollTo\|scrollIntoView"` 于 `sections/` 与四张卡 | **零命中** |
| `rg "getRelated\|getArtifactAssociations"` 于 `BlueprintAssociationsSection.vue` | **零命中** |
| `rg "MermaidDiagram"` 于 `InteractionFlowsSection.vue` | **零命中**（经合成块走块序列） |
| `execution_plan` 于九个段组件的模板 | **零命中** |
| 源码守卫扫描面 | **36 个文件**，6 条断言全绿 |

---

## 13. 给 115-06 的五条注意

1. **十个 `<section id>` 容器与左栏导航项必须无条件渲染**（P-4）。段内空态已由本层组件处理好（§7 的规则表），页面**不要**再加一层 `v-if` 判空——那正是让 `AnchorNavLayout` 的 mount-only observer 观察不到、左栏高亮静默失效的写法。
2. **接住两个跨段跳转锚点**（§3）：`goto-anchor` 的载荷已经是**完整 DOM id**（`fp-<id>` / `api-<id>`），页面只需 `document.getElementById(domId)` + 88px 偏移 + 2s ring 高亮，⛔ 不要再拼一次前缀。
3. **`must_haves` / `decision_log` / `associations` 三段不收 blockCtx**（§2 的表）。给它们传 `threads` 之类只会变成无用的 fallthrough attr；`decision_log` 要接的是 `open-thread`（语义 = 跳到对应线程，见 §4.2）。
4. **`repoNames` 是可选的展示增强**：不传时各卡会回落到条目自带的 `repository_name` 或裸 id，⛔ 不会崩。`ApiContractCard` 的 `supportRepoName` 同理，但支持仓 id **只从 `data_source` 内取**（§4）。
5. **21 个 i18n 键待补**（§6）。补之前请先读那一节的降级说明——21 处都能正常工作，⛔ 不要当成 bug 去改组件结构；补键时优先 ①→③ 档（③ 档的原样 token 最影响可读性）。

---

## Self-Check: PASSED

**创建的 16 个文件全部存在**——九个 `sections/*.vue`（`RequirementSpecSection` / `RepoAssociationsSection` / `CurrentStateSection` / `ImplementationOverviewSection` / `ApiContractsSection` / `ImpactAnalysisSection` / `InteractionFlowsSection` / `MustHavesSection` / `DecisionLogSection`）+ 四张卡（`RepoAssociationCard` / `ImplementationItemCard` / `ApiContractCard` / `ImpactMatrixTable`）+ `BlueprintAssociationsSection.vue` + 两个 spec，逐个 `[ -f ]` 命中。

**三个 commit 全部在 `git log`**：`d030f673` / `0ac9d393` / `293276ae`。

**门禁实跑**：vitest **1602 passed / 1 skipped**（基线 1565 / 1，**+37 零回归**）、type-check **exit 0**、`eslint .` **111 problems**（与基线逐个相同 ⇒ 零新增）、`eslint src/components/blueprint/` **0 problems**、源码守卫 **6 条全绿**（扫描面 36 文件）。

**变异验证实跑**：四条变异（漏渲 `must_haves` / 给它接批注层 / `availability` 回落顶层 / `reversible` 真值判断）分别把用例 1·5·6·7 / 2 / 5b / 6b 逼红，负向对照全部保持绿；每次变异后均还原并核实工作树干净。

**边界核算**：四个禁改文件、115-02 三处追加点、115-03/04 的 25 个产物 `git diff` 全空；`server/` 零改动；依赖零行变更（pnpm 漂移已还原）；本 plan 14 个组件内零划线实现、零原始 HTML 注入、零颜色字面量、零滚动 API、零关联端点调用。
