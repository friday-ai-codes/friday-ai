---
phase: 115-ui
plan: 07
subsystem: blueprint-confirmation-gate-ui
tags: [frontend, vue3, mutation-tested, append-only, deferrable-tail, scope-increment, no-permission-inference]
requires:
  - "112-05：`blueprint-gate/` 八端点（快照 + 七动作），本 plan 只消费、⛔ 后端零改动"
  - "115-02：`~/api/blueprints` 的 gate 七动作封装、`~/types/blueprint` 的三个 gate 类型、i18n `knowledge.blueprints.gate.*` 子树"
  - "115-06：查看器页预留的 `blueprint-gate-mount` 插槽、`gateQuery`（`['blueprint','gate',id]` + `retry:false`）与 `gateAvailable` 派生值"
  - "既有件：`~/components/workflow/RepositoryPicker.vue`、`~/composables/useConfirmDialog`、`ui/{dialog,textarea,tooltip,badge,button,checkbox,separator}`、`useToast`"
provides:
  - "`web/src/components/blueprint/BlueprintGatePanel.vue` —— 确认门面板：说明条 + 仓库行列表 + 添加仓库（复用 `RepositoryPicker`）+ rejected 沉淀次级动作 + 确认锁定主按钮；七动作统一「一次 POST + 双 invalidate」，confirm 409 两档"
  - "`web/src/components/blueprint/BlueprintGateRepoRow.vue` —— 单仓行：role segmented control（即时提交）/ 移除（二次确认）/ 编辑职责（受控 Dialog + Textarea）/ 升级深调研（仅 indirect）/ pending 调研态整行禁用"
  - "`web/src/components/blueprint/__tests__/gatePanel.spec.ts` —— **22 例**：三种 404 并列、七动作各一次 POST 与双失效、pending 正反、confirm 409 两档、二次确认正反、职责空值禁提交、升级仅 indirect"
  - "查看器页的 gate 挂载（**+28 行 / −0**）与 `goto-unresolved` 落点"
  - "i18n **20 个新叶子键**（`knowledge.blueprints.gate.*`，0 删除 / 0 修改）"
affects:
  - "⭐ **FLOW-03 在 UI 上第一次可达**：112 的八个端点此前全仓零前端，用户走不到 113 的阶段 2"
  - "STATE Pending Todos：本 plan 提出三条（gate 链无项目范围闸 / 409 未下发 `blocked_reason` / SC-4 范围收窄）"
tech-stack:
  added: []
  patterns:
    - "单条 `useMutation` + 任务闭包（`GateTask{name,run,success}`）承载七个动作：一处成功分档、一处错误分档，⛔ 不写七份 mutation"
    - "「后端缺口用机器可读键顶住」：409 两档读 `body.blocked_reason` 而不是中文 `detail`；后端尚未下发时功能降级但语义正确，⛔ 不退化成按文案分支"
    - "锚点行逐字保留 + 面板作兄弟节点追加：把「容器内追加子节点」改写成「同级追加」，换来删除行严格为 0"
key-files:
  created:
    - web/src/components/blueprint/BlueprintGatePanel.vue
    - web/src/components/blueprint/BlueprintGateRepoRow.vue
    - web/src/components/blueprint/__tests__/gatePanel.spec.ts
  modified:
    - web/src/pages/knowledge/blueprints/[id].vue
    - web/src/locales/zh-CN.json
    - web/src/components.d.ts
decisions:
  - "⭐ `rerun` 挂在 `edit-responsibility/` 而不是 `upgrade-research/`（PLAN 措辞与后端实读不符，取后端）"
  - "⭐ confirm 409 两档靠 `body.blocked_reason`，⛔ 不靠中文 `detail`；后端当前未下发该键 ⇒ 记进 Pending Todos"
  - "rejected 候选清单快照里不存在，用 `repos[].removed` 作唯一可派生代理"
  - "页面追加取「删除行 = 0」而不是「把空容器改成有子节点的容器」（两者在同一条验收里互斥）"
  - "面板自持动作执行，`action` emit 降级为完成通知；⛔ 不把七动作塞进页面的动作分发器"
metrics:
  duration: "约 1.5 小时"
  completed: 2026-08-01
  tasks: 2
  commits: 2
  tests_added: 22
---

# Phase 115 Plan 07: 阶段 1 确认门面板 Summary

**一句话**：把 112 交付却**全仓零前端**的 `blueprint-gate/` 八端点接上界面 —— 2 个新建组件（约 620 行）+ 1 处**零删除行**的页面追加 + **22 例全绿**的组件测试，让 FLOW-03 第一次在 UI 上可达；同时用**三种 404 各跑一遍且断言同一组结果**的并列用例，把「⛔ 不得据这条链的状态码推断权限、不得按后端文案分支」钉成可证伪的事实。⭐ **「可独立顺延」经实跑验证**：把本 plan 三处改动整体回退后，前端三道门逐字回到 115-06 的基线（1618/1、type-check 0、build ✓）。**零新增依赖、后端零改动、§13.2 的四个归属面 `git diff` 全空。**

---

## 1. 门禁与基线（对比 115-06 的 1618/1）

| 门 | 结果 | 对比基线 |
|---|---|---|
| `pnpm exec vitest run` | **1640 passed / 1 skipped（1641 例，213 文件）** | 基线 1618 / 1（212 文件）⇒ **+22 例 / +1 文件，零回归** |
| `pnpm type-check`（`vue-tsc --noEmit`） | **通过（exit 0）** | 同基线 |
| `pnpm lint`（`eslint .`） | **111 problems（106 errors / 5 warnings）** | ⭐ **与基线逐个相同 ⇒ 零新增** |
| `pnpm build`（`vue-tsc -b && vite build`） | **通过（✓ built in 5.5s）** | 新组件进得了打包 |
| 源码守卫 `blueprint-source-guard.spec.ts` | **6 条全绿**，扫描面 41 → **43 个文件** | 三条断言在**完整**代码面下生效 |

那 1 条 skip 仍是既有的 `src/layouts/__tests__/default.spec.ts:66`。lint 判据沿用 115-02 §1：「自己碰的文件零新增问题」，⛔ 不是整体退出码为 0。

新增 22 例全部在 `components/blueprint/__tests__/gatePanel.spec.ts`；⛔ **未改动 `blueprintViewer.spec.ts`**（它的 9 例在本 plan 之后仍 9/9 绿 —— 它的 `getBlueprintGate` 在每个用例里都 404，所以面板在那份 spec 里永不渲染）。

---

## 2. ⭐ 「gate 非 200 ⇒ 不渲染且不报错」的落地方式

### 2.1 判据被压缩成一条，且只有一个 DOM 落点

渲染条件 = 页面 `gateAvailable`（115-06 已按「`gateQuery` 有数据且无 error」派生）。本 plan **一行未改它**。
组件被渲染出来时，快照必然已经是 200 ⇒ 面板内部**根本没有** 404 分支可写，也就无从按文案分档。

⛔ 面板内零 `try/catch` 快照、⛔ 零错误态、⛔ 零 toast、⛔ 不进 §8.2 分档。

### 2.2 三种 404 的并列用例名（证明没有靠 `detail` 分支）

| # | 用例名 | `detail` |
|---|---|---|
| 1a | `404「确认门未开启」⇒ 面板不存在、无错误态、toast 零调用` | `确认门未开启`（`blueprint_gate_views.py:53,213`，绝大多数蓝图绝大多数时间的正常态） |
| 1b | `404「artifact 不存在」⇒ 行为与 1a 逐字相同` | `artifact 不存在`（`:54,174,211`） |
| 1c | `404「该 artifact 没有蓝图编排会话」⇒ 行为与 1a 逐字相同` | `该 artifact 没有蓝图编排会话`（`:55,179`） |

三条断言**同一组**结果：`[data-testid=blueprint-gate-panel]` 不存在、`[data-testid=blueprint-error-state]` 不存在、六个 toast mock 全部零调用。
⇒ 任何按 `detail` 文本分档的实现，三条里必然至少有一条转红（T-115-59 / T-115-60 的可证伪判据）。

### 2.3 ⭐ 权限推断的实读证据（组件 docstring 逐字登记）

`blueprint_gate_views._ablueprint_project_id`（`:511`）**只在 `BlueprintRejectedToBoundaryView`（`:385`）里被调用过一次** —— 八个端点里**其余七个只有 `IsAuthenticated`，没有项目范围闸**。它的 404 混合三种语义 ⇒ **状态码不携带任何权限信息**。
页面的权限判定仍**只由四个有闸的主查询**（正文 / 人审快照 / threads / events）承担。

> ⚠️ 组件 docstring 里这三种语义刻意**不写后端原文**：写了既是把文案抄进前端，也会命中本 plan 自己的源码扫描（见 Deviation 5）。

---

## 3. 两个组件的 props / emits 逐字

### 3.1 `BlueprintGatePanel.vue`

```ts
props:  { artifactId: string, snapshot: BlueprintGateSnapshot, submitting?: boolean = false }
emits:  {
  action: [name: string, payload?: unknown]   // ⭐ 完成通知（动作已由面板执行完），⛔ 不是请求
  'goto-unresolved': []                        // confirm 409 pending_clarification 的解药入口
}
data-testid: blueprint-gate-panel
```

⭐ **动作由面板自持并执行**（PLAN 在两个选项里取的就是这个）：七个动作与页面其余六个动作语义独立（它们改的是确认门不是人审），塞进页面的动作分发器会让页面再长一截；而本面板本就要在被顺延时整体拿掉，自持动作让「拿掉」是一次纯删除。这条选择已写进组件 docstring。

### 3.2 `BlueprintGateRepoRow.vue`

```ts
props:  { repo: BlueprintGateRepo, pending?: boolean = false, submitting?: boolean = false }
emits:  {
  remove: [repositoryId: string]
  reclassify: [repositoryId: string, role: 'direct' | 'indirect']
  'edit-responsibility': [repositoryId: string, text: string, rerun: boolean]
  'upgrade-research': [repositoryId: string]
}
data-testid: blueprint-gate-repo-row（+ data-repository-id / data-pending 两个身份属性）
```

行内容：仓名 + `role_suggestion` 双色徽标（`direct`→`default` / `indirect`→`secondary`）+ `fitness.verdict` 三档徽标 + 职责 + 现状摘要（`line-clamp-2`）+ 证据 chip 数。徽标 variant 映射与 `RepoAssociationCard` **逐字一致**；⛔ 组件内零颜色字面量、⛔ 零 `Badge` 上 `:class` 加色。

---

## 4. ⭐ 七个动作：端点 → 入参 → 状态码 → toast 映射表

统一范式：**一次 POST → 成功 toast → 双 invalidate**（`['blueprint','gate',artifactId]` **与** `['blueprint','snapshot',artifactId]`）。⛔ 零乐观更新、⛔ 零 `setQueryData`（源码扫描 + 用例 3 双证）。

| 动作 | 端点 | 入参（逐字实读 115-02 的封装） | 成功 toast | 失败分档 |
|---|---|---|---|---|
| 确认锁定 | `confirm/` | 无 body | `gate.confirmSuccess` | ⭐ **409 两档**（见 §5）；其余 4xx 回显 `detail`；5xx 通用失败 |
| 移除仓 | `remove-repo/` | `{repository_id}` | `gate.removeSuccess` | 4xx 回显 `detail`；5xx 通用失败 |
| 手动加仓 | `add-repo/` | `{repository_id}` | `gate.addSuccess` | 同上（多选逐个提交，见 §6） |
| 改判 role | `reclassify-role/` | `{repository_id, role}` | `gate.reclassifySuccess` | 非法 role → 400 原样回显 |
| 修改职责 | `edit-responsibility/` | `{repository_id, responsibility, rerun}` | `gate.editSuccess` | 同上 |
| rejected 沉淀 | `rejected-to-boundary/` | `{}`（⛔ **不自行传 `project_id`** —— 传了且与蓝图不等即 403） | `gate.boundarySuccess`（插值响应体 `draft_count`） | 400 / 403 / 503 一律回显 `detail` |
| 升级深调研 | `upgrade-research/` | `{repository_id}` | `gate.upgradeSuccess` | 503（调研依赖不可用）回显 `detail` |

失败分档的三条通则（`reportFailure`）：
1. `confirm` + 409 ⇒ 走 §5 的两档；
2. 其余 4xx ⇒ **原样回显 `detail`**（后端的中性文案就是给人看的）；
3. 5xx / 非 `ApiError` ⇒ `error.unavailable`，面板保持可重试。

---

## 5. ⭐ `confirm/` 409 的两档，以及一处**后端缺口**

| 档 | 判据 | 呈现 |
|---|---|---|
| A | `error.body.blocked_reason === 'pending_clarification'` | 面板内 `role="status"` 提示条「存在未解决的阻塞澄清线程」+ **「前往未决线程」按钮** ⇒ emit `goto-unresolved`。⛔ 不弹 toast（面板内已有入口，再弹一条是重复） |
| B | 其余 `blocked_reason`（`pending_research` / `snapshot_changed` / 缺省） | `toast.error(detail, '刷新重试')` + 立即双 invalidate |

> ⚠️ **实读发现的后端缺口**：`blueprint_gate_views.py:240` 与 `:249` 的两个 409 **响应体里只有 `detail`**，并没有下发 `blocked_reason`（该键只存在于 service 层的返回值里，视图把它消费掉了）。
>
> 本 plan 的取舍：**坚持读机器可读键**。后端未下发时一律落到档 B —— 功能降级（少一个跳转入口）但**语义正确**；⛔ 绝不退化成按中文 `detail` 分支（那等于把后端文案当协议，后端改一个字前端就错，正是 T-115-60）。补齐 `blocked_reason` 已提请写进 STATE 的 Pending Todos（见 §11 第 ②条）。
>
> 两档各有一条用例（12 / 13），用例 13 显式断言**没有**跳转按钮，防止「两档塌成一档」的静默假通过。

---

## 6. ⭐ `add-repo` 复用 `RepositoryPicker` 的接线形状

N2 已定夺：**复用既有 `~/components/workflow/RepositoryPicker.vue`**，`~/components/chat/RepoMultiSelector.vue` 的备选**已撤销**。核对：`git diff` 这两个文件**输出为空**（⛔ 不修改被复用组件）。

```vue
const picked = ref<string[]>([])
<RepositoryPicker v-model="picked" :repositories="repositoryOptions" :placeholder="…" />
```

- ⭐ **形状实读补正**：PLAN 的清单里漏了一个 **必填** prop —— `repositories: {id,name}[]`（`RepositoryPicker.vue:32`，无 `withDefaults` 默认值）。本面板用既有 `repositoriesApi.list()` 起一个 `useQuery`（`queryKey: ['repositories','list']`、`staleTime: 60s`、⭐ `retry: false`）供数。**它的失败不反噬本面板**：拿不到列表 ⇒ 空数组 ⇒ 该组件的 `allowManualInput`（默认 `true`）自动切到手输 id 模式，用户仍能加仓。
- **多选提交顺序**：点「加入本方案」后按选中顺序**逐个** `await addRepo`；⭐ **任一失败即停在该处**，已成功的不回滚（后端每个动作各自持久化），未提交的 id **留在选择器里**可直接重试。全部成功 ⇒ `picked.value = []`。
- ⛔ 不包薄适配层、⛔ 不新造选择器。

---

## 7. ⭐ pending 调研态与确认主按钮

| 位置 | 判据 | 呈现 |
|---|---|---|
| 单仓行 | `snapshot.pending_research_repository_ids.includes(repo.repository_id)` | 行内**全部**动作 `disabled` + `icon-[lucide--loader-2] animate-spin` + 「调研中」（`aria-live="polite"`）；行上带 `data-pending="true"` 便于定位 |
| 确认主按钮 | `pending_research_repository_ids.length > 0` | `disabled` + Tooltip 回显 `_LOCK_BLOCKED_MESSAGES['pending_research']` 的语义：「调研中，暂不可确认」 |

两处都有**正反并列**用例（10 / 11）：无 pending 时行按钮与主按钮都可用、Tooltip 不渲染。漏判会让用户在调研途中提交动作，后端拒绝且体验断裂（T-115-63）。

`icon-[lucide--loader-2]` 是**字面量**写死在模板里（⛔ 不是运行时拼接）⇒ Tailwind content 扫描直接命中，**无需动 safelist**（`styles/main.css` 本 plan 零改动）。

---

## 8. ⭐ 页面挂载：删除行严格为 0

`git diff web/src/pages/knowledge/blueprints/[id].vue` → **+28 / −0**，`rg "^-[^-]"` **空输出**。
`rg -n "blueprint-gate-mount"` **仍命中**（`?panel=gate` 的滚动定位依赖它）；`rg -n "BlueprintGatePanel"` 命中。

三处追加：

| 位置 | 追加内容 |
|---|---|
| import 区 | 一行 `import BlueprintGatePanel from '~/components/blueprint/BlueprintGatePanel.vue'`（按字典序插在 `BlueprintErrorState` 之后） |
| script 尾 | `onGotoUnresolved()`：展开侧栏（`sidebarCollapsed = false`）+ `resetKindFilters()` + `showClosedAnnotations = false` + 打开抽屉。⭐ 未决分组本身 `defaultOpen: true`，所以「展开未决组」要做的是**把它露出来**，⛔ 不弹 toast |
| gate 挂载点 | 在既有锚点 `<div v-if="gateAvailable" id="gate" data-testid="blueprint-gate-mount" />` **之后**追加一个同条件的兄弟容器，内含 `<BlueprintGatePanel>`，ring 高亮同样绑在它上面 |

⭐ **为什么是兄弟节点而不是「容器内追加子节点」**：把那个自闭合锚点改成有子节点的容器，必然把 `/>` 改成 `>` —— 那是**一行删除**，与同一条验收里的「删除行为 0」直接冲突。取「删除行 = 0」：锚点行**逐字保留**，面板紧随其后渲染 ⇒ `scrollToDom('gate')` 落到锚点即等于落到面板顶部，2s ring 由追加的外层容器承担，观感与原设计一致。⛔ **`gateAvailable` 的定义一行未改**，⛔ 未新增任何错误分档、未弹任何 toast。

组件用**静态 import**（⛔ 不是 `defineAsyncComponent`）：与 115-06 页面里其余 20+ 个组件的写法保持一致；该页只有 `ProjectMaterialsPanel` 那种「分区面板」才用异步，查看器页本身零异步 import。

---

## 9. ⭐ 可独立顺延性：**实跑验证**（不是静态论证）

在临时分支 `tmp/115-07-deferability` 上把本 plan 的两个提交整体 `git revert`，然后：

| 检查 | 结果 |
|---|---|
| 回退后的树与本 plan 之前是否逐字一致 | `git diff <本plan前> HEAD -- web/` → **空输出** ⇒ 回退干净，无残留 |
| `pnpm exec vitest run` | **1618 passed / 1 skipped（212 文件）** ⇒ ⭐ **逐字回到 115-06 的基线** |
| `pnpm type-check` | **exit 0** |
| `pnpm build` | **✓ built in 5.6s** |

⇒ **前六个 plan 不依赖本 plan**，本面板确实可以整体顺延到 Phase 116 而不破坏任何已交付的面。

**工作区恢复确认**：验证后 `git checkout -- web/src/components.d.ts`（build 的重写）→ 切回 `milestone/v0.20.0-blueprint` → `git branch -D tmp/115-07-deferability` → `git status --porcelain` **空输出**，与验证前逐字一致。
⛔ 全程未用 `git stash`（它的 stash 栈跨 worktree 共享）、未用 `git reset --hard`、未用 `git clean`。

---

## 10. ⭐ 相位级收口报告

| 检查 | 结果 |
|---|---|
| **§13.2 的 0.19 归属面**（`chat/TechPlanCard.vue` / `chat/RoutingDecisionPanel.vue` / `execution/NodeDataTab.vue` / `delivery/ArtifactTimeline.vue`） | ⭐ `git diff <相位基线> HEAD` **四个全空** |
| 前端五个追加点删除行（`pages/knowledge/index.vue` / `ProjectMaterialsPanel.vue` / `api/index.ts` / `styles/main.css` / `locales/zh-CN.json`） | **全部 0**（`main.css` 与 `api/index.ts` 相位内**零改动**） |
| 本相位自建页 `pages/knowledge/blueprints/[id].vue` 删除行 | **0** |
| `git diff --name-only <相位基线> HEAD -- server/` | ⭐ **只含 115-01 声明的七个文件**（`blueprint_doc_views.py` / `blueprint_list_views.py` / `blueprint_comment_action.py` / `urls.py` + 三个 test） |
| 相位内 migration | **零个**（后端改动清单里无 `migrations/`） |
| `uv run python manage.py makemigrations --check --dry-run` | **No changes detected，退出码 0** |
| `git diff web/package.json web/pnpm-lock.yaml web/pnpm-workspace.yaml` | **零行**（本 plan 未触发 pnpm 10 的 catalog 回填漂移） |
| 源码守卫扫描面 | **43 个文件**（115-06 的 41 + 本 plan 的 2），6 条断言全绿 |
| `rg "v-html\|refetchInterval\|edit-block\|edit-blocks\|editBlocks" src/components/blueprint/ src/pages/knowledge/blueprints/` | **零命中** |
| `rg "setQueryData\|RepoMultiSelector\|hsl("` 两个新组件 | **零命中** |
| `git diff RepositoryPicker.vue RepoMultiSelector.vue` | **空输出**（⛔ 未修改被复用组件） |

### ⭐ 全量后端 pytest（相位收口实跑）

本 plan **后端零改动**（上表第四行的 `git diff --name-only server/` 逐字证明：相位内后端改动仅 115-01 的七个文件，本 plan 一个未碰）。相位收口仍实跑了全量 `cd server && uv run pytest tests/ -q`（470s）：

```
1 failed, 8606 passed, 63 skipped, 26 deselected, 1 xfailed
FAILED tests/mcp_tools/test_skills_snapshot_guard.py::test_skill_files_discovered
```

| 项 | 基线（8546 passed / 1 failed） | 本次 | 判定 |
|---|---|---|---|
| failed | 1 | **1** | ⭐ **零新增失败** |
| 那条 failed 是谁 | `test_skills_snapshot_guard.py::test_skill_files_discovered` | **同一条** | STATE 已登记的**纯 worktree 环境现象**（断言 `skills/skills/*/SKILL.md` ≥4，而本 worktree 的 `skills/` 是空目录，主检出里有内容），与蓝图相位无关；里程碑收尾在主检出复跑即可 |
| passed | 8546 | **8606** | +60（相位期间其它 plan 的后端用例增量），零回归 |

---

## 11. ⭐ 提请写入 STATE 的 Pending Todos

| # | 条目 | 证据 / 出处 | 为什么不在本相位修 |
|---|---|---|---|
| ① | **`blueprint-gate/` 八端点中七个没有项目范围闸** | `server/delivery/api/blueprint_gate_views.py:385`（唯一调用点）与 `:511`（helper 定义）—— 其余七个 View 只有 `IsAuthenticated` | 这是 112 遗留的**既有后端缺口**，本相位边界是「只加读面」；修它要动权限模型与八个端点的测试，属独立工作项（P-10 已要求登记） |
| ② | **`confirm/` 的 409 未下发 `blocked_reason`** | `blueprint_gate_views.py:240,249` 两处 409 响应体只有 `detail`；`blocked_reason` 只活在 service 返回值里 | 前端已按机器可读键实现（§5），后端补一个键即可让「一键跳未决线程」这档生效；⛔ 前端不为此改成按中文文案分支 |
| ③ | **SC-4 的范围收窄** | 115-05-SUMMARY 已登记：关联段的「引用了本蓝图 / 关联知识」需要知识图谱物化 | 顺延 Phase 116 的知识图谱物化 |

---

## 12. Deviations from Plan

### 1. `[Rule 1 - 契约订正] rerun 属于 edit-responsibility，不属于 upgrade-research`

- **发现于**：Task 1（`read_first` 的后端全文实读）
- **问题**：PLAN 与 UI-SPEC §11.3 都写「升级深调研带『重新调研该仓』勾选（`{rerun: true}`）」。但逐字实读
  `blueprint_gate_views.py:338` 的 `BlueprintGateEditResponsibilityView` docstring：*「只有调用方显式传
  `{"rerun": true}`（**用户在 UI 勾选「重新调研该仓」**）才触发」* —— `rerun` 是 **`edit-responsibility/`**
  的入参；`BlueprintGateUpgradeResearchView`（`:452-471`）**只读 `body['repository_id']`**。115-02 的
  API 封装也逐字如此（`editResponsibility` 有 `rerun?`，`upgradeResearch` 没有）。
- **处理**：勾选框渲染在**职责编辑弹窗**里，`edit-responsibility` 的 emit 与 payload 带 `rerun`；
  升级深调研按钮不带勾选、payload 只有 `repository_id`。PLAN 的「⛔ 不得猜测入参键」优先于它自己的措辞。
- **用例**：7（`edit-responsibility` 入参含 `rerun: true`）、8（`upgrade-research` 入参**只有** `repository_id`）
- **文件**：两个新组件 ｜ **Commit**：`0fcac3ad`

### 2. `[Rule 3 - 阻塞] RepositoryPicker 有一个 PLAN 清单里漏掉的必填 prop`

- **问题**：PLAN 把该组件的形状写成「`modelValue` + `placeholder` + `allowManualInput`」，但 `:32` 还有一个
  **无默认值的必填** `repositories: Repository[]`。不传 ⇒ `type-check` 直接红。
- **处理**：面板内起一个 `useQuery(['repositories','list'], repositoriesApi.list, { retry: false })` 供数并映射成
  `{id,name}`。⭐ 失败**不反噬面板**：空数组 ⇒ 该组件自动切到手输 id 模式。⛔ 未修改 `RepositoryPicker.vue`。
- **Commit**：`0fcac3ad`

### 3. `[Rule 2 - 契约缺口] 快照里没有 rejected 候选清单，用 removed 作代理`

- **问题**：PLAN 要求「rejected 候选清单为空时不渲染沉淀动作」，但 `BlueprintGateSnapshotSerializer`（`:199-211`）
  逐字只有八键，**没有** rejected 清单；后端是在 `rejected-to-boundary/` 内部自己查 `RepoAssociation.status=rejected`。
- **处理**：用唯一可派生的代理 `snapshot.repos.some(r => r.removed === true)` —— 确认门里被移除的仓正是产
  `boundaries` 草案的那一批（`BlueprintGateRemoveRepoView` docstring 逐字）。⛔ 不猜键名、⛔ 不为此加端点。
- **用例**：9（有 `removed` 行 ⇒ 渲染并可提交）、19（无 ⇒ 不渲染）

### 4. `[Rule 1 - 死接口取舍] action emit 保留但降级为「完成通知」`

- PLAN 的 emits 契约里有 `action: [name, payload?]`，但同一段又定下「面板自持 `useMutation` 自己执行」。
  两者并存会让 `action` 变成零消费的死接口（115-03 订正一的判例）。
- **处理**：保留该 emit 但**语义改写为完成通知**（动作成功后 emit，供页面或测试观察），并在 docstring 里
  逐字写明「⛔ 不是请求」。页面当前不绑定它 —— 它是给「面板缺席可顺延」之外的后续接线留的观察点。

### 5. `[Rule 1 - 自洽修正] 两处 docstring 字面量会触发本 plan 自己的验收断言`

- **发现于**：Task 1 的验收复跑
- **问题**：① 面板 docstring 为解释「三种 404 的语义」写了后端原文「确认门未开启」「没有蓝图编排会话」，
  正好命中本 plan 自己的「不得用后端文案分支」扫描；② docstring 里写「⛔ 零 `setQueryData`」，命中
  「`setQueryData` 零命中」的扫描。
- **处理**：① 改写成不含原文的等义表述（「门尚未开启 / artifact 查不到 / 该 artifact 上没有蓝图编排的会话」）
  并补一句说明**为什么刻意不写原文**；② 改写成「⛔ 不预写任何查询缓存」。语义完整保留。
- **与 115-02 §12.3、115-03 Deviation 5、115-04 Deviation 6、115-05 Deviation 4、115-06 Deviation 4 同一类。**

### 6. `[对 PLAN 验收的一处取舍] 页面追加取「删除行 = 0」`

- PLAN 同一条验收里既要求「把空容器替换为包含面板的**同一个**容器」，又要求 `rg "^-[^-]"` **为空**。
  前者必然把 `/>` 改成 `>` ⇒ 至少一行删除，两者互斥。
- **处理**：取「删除行 = 0」（它才是 §13.2 CREATE-ONLY 纪律的落点，也是可机械验证的那一条）。
  锚点行**逐字保留**，面板作紧邻兄弟节点追加，ring 高亮绑在追加的容器上 ⇒ `?panel=gate` 的滚动定位与
  2s 高亮都不失效。详见 §8。

### 7. `[用户显式授权] i18n 追加 20 个键`

- PLAN 写「⛔ 不碰 `zh-CN.json`，缺键回报而不是自己补」，但执行指令显式授权：「115-06 已完成，
  `zh-CN.json` 是既有的可追加点，additive 即可，但要在 SUMMARY 里说明」。
- **处理**：**只增不改不删** —— 键集差分 **added 20 / removed 0 / changed 0**，
  `git diff | rg "^-[^-]"` 空输出。沿用 115-06 §11 的落位习惯（新键插在对象**最后一项之前**，
  避免给原最后一行补逗号而在 diff 里表现为一删一增）。
- **新键清单**（全在 `knowledge.blueprints.gate.*`）：`notice` / `researching` / `evidenceCount` /
  `responsibilityTitle` / `responsibilityHint` / `responsibilityPlaceholder` / `rerunResearch` /
  `save` / `cancel` / `addRepoPlaceholder` / `addRepoSubmit` / `unresolvedClarification` /
  `gotoUnresolved` / `confirmSuccess` / `removeSuccess` / `addSuccess` / `reclassifySuccess` /
  `editSuccess` / `upgradeSuccess` / `boundarySuccess`。
  原有 18 个 gate 键（含 §16 的两组破坏性确认文案）**一个字未改**。

### 8. `[环境事实] components.d.ts 仍需手工增行；pnpm workspace 本次无漂移`

- `pnpm build` 重写 `src/components.d.ts` 时，除加上本 plan 的 2 个组件外**又裁掉 29 条既有条目**
  （与 115-06 Deviation 6 逐字相同的现象）。已 `git checkout` 还原后按字典序**手工插入那 2 行**，
  最终 diff **+2 / −0**。
- `web/pnpm-workspace.yaml` 本次**未出现** catalog 回填漂移（115-06 出现过），三个依赖文件 diff 零行。

---

## 13. Task Commits

| Task | 内容 | Commit | 变更 |
|---|---|---|---|
| 1 | 确认门面板 + 单仓行 + 20 个 i18n 键 | `0fcac3ad` | 3 文件 / +721 / −0 |
| 2 | 页面挂载（+28/−0）+ 22 例组件测试 + `components.d.ts` 手工增 2 行 | `acd9127e` | 4 文件 / +683 / −1 |

（`−1` 是本 plan **自己创建**的面板文件里的一行 docstring 改写，见 Deviation 5；既有文件删除行仍为 0。）

---

## 14. ⭐ UAT 清单（确认门专属，happy-dom 测不了的）

| # | 项 | 为什么自动化测不了 | 期望 |
|---|---|---|---|
| 1 | **role segmented control 的即时提交手感** | 无真实点击节奏与网络延迟 | 点另一档后按钮立刻进 `disabled`、成功 toast 出现、列表重取后新档位保持；⛔ 不许出现「点完弹回旧档再跳新档」的闪烁（那是乐观更新的味道，本实现没有） |
| 2 | **`RepositoryPicker` 的弹出与选择流** | 测试里整体 stub 掉 | 弹层能搜、多选 chip 正常、无仓库时自动切手输模式；选完点「加入本方案」逐个提交，失败时未提交的 id 还留在框里 |
| 3 | **pending 行的 spin 动效** | 无 CSS 动画引擎 | `animate-spin` 真的在转，且该行所有按钮肉眼可见地灰掉 |
| 4 | **二次确认弹窗的文案与焦点** | Portal + 焦点模型不完整 | 两条破坏性确认文案与 §16 逐字一致；`Esc` / 点遮罩 = 取消且**不发 POST**；关闭后焦点回到触发按钮 |
| 5 | **职责编辑弹窗** | 同上 | 打开时回填当前职责、`rerun` 每次打开都重置为未勾选、空/纯空格时提交灰掉 |
| 6 | **`?panel=gate` 的滚动定位与 2s ring** | 无布局几何 | 深链进入后滚到确认门、顶栏不遮挡（88px 偏移）、**面板整块**被 ring 高亮 2s 后自然消失（本 plan 把 ring 挪到了面板容器上，需人眼确认观感与其它锚点一致） |
| 7 | **确认主按钮的 Tooltip** | 悬停延迟在测试里被拍平 | 有 pending 时悬停 disabled 的主按钮能看到「调研中，暂不可确认」 |
| 8 | **确认锁定的完整闭环** | 需要真实后端状态机 | 点确认 → 二次确认 → 成功 → 蓝图状态与阶段时间线**同时**更新（双 invalidate 的真实验证）；若后端返 409，两档提示各自可复现 |
| 9 | **面板与十段正文的视觉层次** | 无渲染引擎 | 面板夹在「关联」段与质量面板之间时，不会被误读成第十一段正文 |

---

## 15. FLOW-03 的界面可达性说明

| 项 | 内容 |
|---|---|
| **在做什么** | 112 交付了确认门的完整后端（八端点 + 状态机 + 续驱），但**全仓零前端**。本 plan 补的是「链条第一关的界面可达性」 |
| **不做的后果** | 用户看得到蓝图正文，却无法确认仓库集与职责 ⇒ **永远走不到 113 的阶段 2**，整条需求→方案链在界面上断在第一关 |
| **为什么是范围增量** | 它相对 ROADMAP 的 SC 是增量（CONTEXT `<deferred>` 与 UI-SPEC §11.3 双处登记），因此被安排成本相位**最后一个可独立顺延的 plan** |
| **若要顺延** | 顺延目标是 **Phase 116**，且必须在 STATE 显式登记。⛔ **不得默默丢掉** |
| **顺延的技术前提已验证** | §9：回退本 plan 后前端三道门逐字回到 115-06 基线 ⇒ 前六个 plan 不依赖它 |

---

## Self-Check: PASSED

**创建的 3 个文件全部存在**：`components/blueprint/BlueprintGatePanel.vue` /
`components/blueprint/BlueprintGateRepoRow.vue` / `components/blueprint/__tests__/gatePanel.spec.ts`，
逐个 `[ -f ]` 命中。

**两个实现 commit 都在 `git log`**：`0fcac3ad` / `acd9127e`。

**门禁实跑**：vitest **1640 passed / 1 skipped**（基线 1618 / 1，**+22 零回归**）、type-check **exit 0**、
`eslint .` **111 problems**（与基线逐个相同 ⇒ 零新增）、`pnpm build` **通过**、源码守卫 **6 条全绿**
（扫描面 **43** 个文件）。

**可顺延性实跑**：临时分支整体回退本 plan 两个提交 ⇒ vitest **1618 / 1**、type-check **exit 0**、
build **通过**，与 115-06 基线**逐字相同**；验证后工作区 `git status --porcelain` **空输出**。

**边界核算**：§13.2 的四个归属面 `git diff` 全空；六个追加点删除行全为 0；`server/` 相位内只含 115-01 的
七个文件且零 migration；`makemigrations --check --dry-run` **退出码 0**；依赖三件套 diff **零行**；
`zh-CN.json` 键集差分 **added 20 / removed 0 / changed 0**；生成物 `components.d.ts` 手工增 **2 行**、零删除。

**全量后端 pytest 实跑**：**8606 passed / 1 failed / 63 skipped**，那条 failed 是 STATE 已登记的 worktree
环境项（`test_skills_snapshot_guard.py::test_skill_files_discovered`）⇒ **相对基线零新增失败**。
