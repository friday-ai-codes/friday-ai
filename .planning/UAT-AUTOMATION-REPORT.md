# v0.19.0 人工验收：浏览器可验证子集的自动化执行报告

_执行日期：2026-08-02 · 分支 `main` · 前端 `web/`_

v0.19.0「技术方案可信度」带着 **27 项零执行的人工验收**归档（见
`.planning/milestones/v0.19.0-MILESTONE-AUDIT.md` frontmatter `human_verification_outstanding: 27`）。
本次把其中 **13 项浏览器可验证** 的用 Playwright 实跑了一遍，另外 14 项按「为什么不能自动化」
逐条标注后留在 `[pending]`。

**结论：13 项全部通过，过程中发现并修复了 2 个真实缺陷。**

---

## 1. 结论速览

| UAT | 项 | 结果 | 覆盖它的 spec |
|---|---|---|---|
| 105 | 3 分数分解展开区 | pass | `routing-panel.spec.ts` |
| 106 | 4 权重设置区交互 | pass（**发现缺陷 1**） | `repo-router-weights.spec.ts` |
| 107 | 2 分组 / 跨组 / 降级三块 | pass（有契约缺口，见 §5） | `routing-panel.spec.ts` |
| 107 | 5 澄清 pending 态可见性 | pass | `clarification-visibility.spec.ts` |
| 109 | 3 草稿横幅 / 徽标 / 弹层 | pass | `draft-plan-gate.spec.ts` |
| 109 | 4 lark_md 方言呈现 | pass | `draft-plan-gate.spec.ts` |
| 110 | 1 SSE 直播链 | pass（有残留，见 §6） | `orchestration-observability.spec.ts` |
| 110 | 2 `plan_session_id` 相等性 | pass | `orchestration-observability.spec.ts` |
| 110 | 4 前半程失败复验 | pass | `orchestration-observability.spec.ts` |
| 110 | 5 折叠按钮可访问名 | pass | `orchestration-observability.spec.ts` |
| 110 | 6 live region 播报节奏 | pass | `orchestration-observability.spec.ts` |
| 110 | 7 空心点形状差异 | pass | `orchestration-observability.spec.ts` |
| 110 | 8 完成后版面收敛 | pass（**发现缺陷 2**） | `orchestration-observability.spec.ts` |

各 phase 的 `*-UAT.md` 已就地回填 `result:` 与逐条证据/残留说明。

---

## 2. 护栏是什么

### 2.1 一个更正

任务前提是「没有 `playwright.config.ts`」。实际上**有**一份（`web/playwright.config.ts`，
`bc32dd5c` 之前的版本），只是跑不起来：

- 声明了 firefox / webkit 两个 project，而本机 `~/Library/Caches/ms-playwright/` 只装了
  chromium —— `pnpm test:e2e` 直接失败；
- `webServer` 用 `pnpm dev`，而 `vite.config.ts` 里 `open: true` 会在无头跑用例时弹出宿主机
  浏览器，`strictPort: true` 又会与开发者常驻的 10240 dev server 撞口；
- 没有 timeout / 截图 / trace 设置，失败时没有可诊断物。

所以这次是**收紧**而不是新建。

### 2.2 现在的形状

`web/playwright.config.ts`：

- `testDir: './tests/e2e'`，**chromium 单 project**（与既有 `test:e2e:ci --project=chromium` 对齐）；
- `webServer` 起 Vite dev server 在专用端口 **10250**（避开常驻 dev server），带 `--no-open` +
  `BROWSER=none`，本地 `reuseExistingServer: true`；
- `baseURL` 让 `page.goto('/')` 可用；`testIdAttribute: 'data-test'`（本仓统一用这个属性，
  不是 Playwright 默认的 `data-testid`）；
- 固定 `colorScheme: 'light'` / `locale: 'zh-CN'` / `timezoneId`，让断言前提不受宿主机环境影响
  （需要暗色的 110-7 自己开 `colorScheme: 'dark'` 的 context）；
- 失败留 trace 与截图；`forbidOnly` 在 CI 生效。

### 2.3 后端替身

沿用 `tests/e2e/auth.spec.ts` 的模型：只起 Vite，**不起 Django、不连数据库**，
`page.route('**/api/**')` 拦截全部后端响应。

- `tests/e2e/support/api.ts` —— 默认路由表（已登录 + 一个空间 + 一个可用凭证），
  用例只覆盖自己关心的端点；顺带接管 `/ws/`（否则 `connectRealtime` 的指数退避重连会在
  trace 里刷噪声）；记录每次调用的 method / path / 相对毫秒数，供「是不是等到轮询才更新」
  这类断言使用。
- `tests/e2e/support/payloads.ts` —— 载荷 builder。**形状全部照抄真实序列化产物**，
  每个 builder 都标了出处：
  - 路由候选出参形状取自 `RepositoryRelevanceOutput`（schema 快照
    `server/tests/agents/fixtures/repository_relevance_output_schema.json`），外层是
    `{data, metadata}` 而不是 `{output:{data}}` —— 因为 `chat_runner._normalize_tool_result`
    取的是 `ToolResult.output` 本身（`server/agents/chat_runner.py:402`）再 `json.dumps`；
  - 编排工具在途 / 终态两种出参取自 `server/agents/tools/plan_research_tools.py`；
  - 事件名与 payload 取自 `server/services/process_runtime/builtin_processes.py`
    （`repo.routing` / `knowledge.recalling` / `repo.research.*`）；
  - 109-4 的 `tech_plan` 是对 `render_merged_plan_markdown` **实跑导出**的真实字符串；
  - 权重默认值与后端 400 的错误串是对 `DEFAULT_WEIGHT_CONFIG` / `validate_weight_config`
    **实跑导出**的真实产物。

  这条纪律是刻意的：形状对不上的 fixture 会产出「绿了但什么都没证明」的用例，
  那正是本里程碑审计点名的失败模式。

### 2.4 取证层：全部从用户入口出发

没有一条断言是挂叶子组件的。路由面走「打开会话 → 点开『分析过程』→ 点开『仓库分级路由』
那一步」；草稿弹层走「编排产出卡 →『进入编码』→ 惰性投影 → 内嵌 TechPlanCard → 选仓 →
『确认编码』」；权重设置区走「`/admin` → 点 RAG tab」；SSE 链走「在输入框里打字 → 点发送」。

---

## 3. 变异验证（每一条都改坏过一次）

对 13 项各做一次变异：改坏被测物 → 跑对应用例确认转红 → `git checkout --` 还原。
**14 次变异全部转红**（110-8 做了两次，分别针对「自动收起」与「不被抢回」两个分句）。

| UAT | 改坏了什么 | 结果 |
|---|---|---|
| 105-3 | `SIGNAL_LABELS` 里 `text` 键改名（回显英文 key） | RED |
| 106-4 | 撤回 `String()` 修复（还原 `.trim()` 抛错） | RED |
| 107-2 | `isCrossGroup()` 恒返回 false | RED |
| 107-5 | `ChatStatusBar` 的 `waiting_clarification` 文案换成通用兜底 | RED |
| 109-3 | `isUnresearched` 恒 false | RED |
| 109-4 | 渲染前把 `•` 替换成 `-`（模拟一次「好心的」归一化） | RED |
| 110-1 | store 里 `process_event` 分支改名（模拟直播链静默失效） | RED |
| 110-2 | 去掉 `planResearchSessionsFor` 的 `plan_session_id` 过滤 | RED |
| 110-4 | 删掉 `buildInner` 的 `sawSessionFailed` 兜底（GAP-1 修复前形态） | RED |
| 110-5 | aria-label 改回只有动作词（WCAG 2.5.3 修复前形态） | RED |
| 110-6 | 把步数计数拼进 live region | RED |
| 110-7 | `skipped` / `unknown` 圆点改成实心 | RED |
| 110-8a | 去掉日志组自动收起 | RED |
| 110-8b | 一次性 flag 换成「每次快照到达都重折」 | RED |

变异结束后工作区干净，全量 34 条 e2e 复跑仍全绿。

---

## 4. 发现的真实缺陷（各自独立 `fix(...)` 提交）

### 缺陷 1 —— 改路由权重常数会打断整块设置区的渲染（`76b39ff0`）

关键常数输入框是 `type="number"`，Vue 的 `vModelText` 对该类型会把 DOM 串**回写成 number**
（`castToNumber`）。`RepoRouterWeightSettings.vue` 的 `validationErrors` 里有
`(constantForm[key] ?? '').trim()`，用户改过任一常数后即抛 TypeError；它是 computed，
异常会打断整个组件的渲染：

- 保存按钮的 disabled 状态冻结在改动前 —— 改完常数**点不动保存**；
- 「保存前请修正以下问题」预校验框永远不出现 —— 填了非法区间（`c_lo >= c_hi`）**没有任何提示**；
- 控制台只有一条 Vue warn，界面上看不出异常。

修复：先 `String()` 再 `trim()`。

这正是 106-4 那条 UAT 想抓的东西：该组件零单测（106-MN-05 deferred），UAT 又从未执行，
于是这个缺陷在整个里程碑里没有任何一道网能拦住它。

### 缺陷 2 —— 路径里自带 query 的请求被编码成 `%3F` 而 404（`c09b8018`）

`web/src/api/client.ts` 的 `buildUrl` 用 `url.pathname = API_BASE + endpoint` 拼路径，而
`URL.pathname` 的 setter 会把 `?` 百分号编码成 `%3F`。凡是把 query 写进路径字面量的调用点，
实际发出的是 `/api/x/%3Fk=v?k=v`，服务端按路径匹配直接 404。受影响两处：

- `getConversationRuntime(id, orchestrationSeen)` —— 编排进入终态后，轮询会带上收敛令牌
  （110-MN-02），**从那一拍起每次 runtime 轮询都 404**；`pollConversationRuntime` 的 catch
  吞掉异常并停止轮询。用户看到的是「编排完成后调研日志组突然消失、实时更新静默停摆」。
- `validateInvitation(token)`（`web/src/api/users.ts`，`/auth/invite/?token=…`）—— 邀请链接
  校验同样 404（`c09b8018` 的提交信息里把它写成了 `getInvitation`，端点没写错、函数名笔误）。

修复：先拆出 endpoint 自带的 query 再拼 pathname，两处调用点零改动。

这个缺陷是 110-8 那条「手动展开后不被后到的轮询快照收走」用例逼出来的 —— 它是本批里
唯一一条**需要等真实轮询到达**的用例，没有它就不会踩到收敛令牌那条路径。

---

## 5. 顺带发现的契约缺口（未修，需要人决定）

**107-UI-SPEC §「Top-3 与溢出披露」没有实现。** SPEC 要求每组默认只渲染 Top-3、其余进组内
`Collapsible`，trigger 文案「显示其余 {n} 个候选」。`RoutingCandidateList.vue` 组内候选
**全量列出**，全仓检索不到该 trigger 文案。

两点缓解让它没那么严重：

1. pin-in 那一半（`selected_by_ai || selected_by_user_final` 无论排名一律可见）是为带
   `Checkbox` 的 `RoutingDecisionPanel` 写的，而实际挂载的是**只读**清单，pin-in 天然不适用；
2. 工具侧 `top_k` 默认 5（且按组配额截断），组内最多 5 行，溢出披露的实际收益有限。

没有把它记成 fail：107-2 那条 UAT 的主干（分区标题 / 跨组 / 降级三块）全部成立，这一条是
SPEC 里的一个分句。已在 `107-UAT.md` 的 Gaps 里挂账，请确认是「契约被降级采纳」还是漏实现。

---

## 6. 诚实的残余：覆盖了哪一半、剩哪一半是人判

| UAT | 用例锁住了什么 | 仍然只能靠人的部分 |
|---|---|---|
| 105-3 | 中文信号名、三位小数、等宽 + 右对齐（`getComputedStyle`）、合计 == 总分、无 breakdown 不出入口 | 「与 105-UI-SPEC 观感一致 / 视觉零漂移」 |
| 106-4 | 五下拉回显与可选、常数可编辑、两类预校验拦截并禁用保存、后端 errors 逐条显示、保存回读、PUT 不带 `is_default` | 无（这项覆盖得最完整） |
| 107-2 | 组标题与计数、跨组说明句与徽标、置顶两种措辞、降级横幅 + 徽标灰化（同页对照计算色）、闭集外原因不回显、历史 trace 平铺 | 「零新色板」；Top-3 / 溢出披露（见 §5） |
| 107-5 | 状态条文案、澄清卡问题与选项、待回复徽标、跳过出口；配负向对照 | `HumanTaskInbox` 那一路 |
| 109-3 | 横幅在正文之前（文档顺序）、折叠后徽标仍在、必勾才能确认、Tab 一圈焦点不出弹层、label 点击生效、取消不发请求、确认不跨次记忆、`acknowledge_unresearched` 只在勾选后出现 | 「无新色板 / 新字号 / 新组件」 |
| 109-4 | 渲染出字面 `•`、不产生 `<ul>/<li>`、不漏裸 `- `、两条风险原文都在、`**加粗**`/`> 引用` 仍走真 markdown | 「观感是否可接受」（VALIDATION 第 10 条本来也只要求人判） |
| 110-1 | 快照链饿死的前提下四阶段在单个 <2s 窗口内推进完毕、`/runtime` 调用 ≤1 | **网络级逐帧时序**：Playwright 的 `route.fulfill` 无法分帧下发，SSE 响应体一次性交付。用例证明「事件到达即渲染且早于轮询」，不证明后端 `get_stream_writer()` 在生产的 tool 调用栈里真能解析到 writer |
| 110-2 | 相等 / 不等两种绑定键下日志组的出现与不出现、卡标题是仓库名、无裸 UUID | **生产上两者是否确实相等** —— 这仍需一次真实跨进程实跑 |
| 110-4 | 标题转失败态、该步 sr-only 状态为「失败」+ 摘要「未知原因」、页面不再有「正在生成技术方案」 | 「前半程直播时该步应有脉冲」（`0681b463`）未单独断言 |
| 110-5 | 可访问名的**计算结果**（`toHaveAccessibleName`）两态正确、`aria-controls` 两态都能解析 | 真实读屏软件的播报顺序与断句 |
| 110-6 | 卡内 `[aria-live]` 恰 1 个、五仓完成期间播报文本恒定、摘要确实变化（证明事件被处理了） | 读屏是否真的只播一次 |
| 110-7 | 亮/暗两 context 下空心（透明底 + 有边框）与实心（不透明 + 无边框）的计算样式差异；两态各自的 sr-only 文本 | **「一个人在 10px 圆点上能不能分辨」** —— 主观判断，用例只证明差异客观存在 |
| 110-8 | 终态标题、时间线正文收起、日志组 `aria-expanded=false`、结果卡 `toBeInViewport()`、手动展开后跨 >2 拍轮询仍展开 | 真实多仓场景下的整体版面观感 |

另有一条**测试钩子失效**（非产品缺陷，未修）：`TechPlanCard.vue` 上的
`data-test="unresearched-dialog"` 挂在 `AlertDialogContent` 包装组件上，而它的根是
`AlertDialogPortal`（teleport 根），属性透传不到真实 DOM（控制台有对应 Vue warn）。
用例改用 `getByRole('alertdialog')`，并在原处留了注释。

---

## 7. 14 项不可自动化项的分类

均保持 `[pending]`，并在各自 `*-UAT.md` 里加了 `not_automatable:` 说明，避免以后重新争论。

**需要生产实例（8 项）** —— 被测物是生产的真实索引规模 / 语料 / 存量数据，本地跑出来的数字
回填进 MEASUREMENTS 反而是伪证据：
105-1（O-1 N_r 分布回填）、105-2（gk-001 真实样本）、106-1（N_r/N̄ 快照写入）、
106-2（O-2 余弦校准）、106-3（生产 dense 覆盖率与 S_top 口径）、107-3（O-6 延迟分位）、
107-4（澄清超时出口 dry-run）、109-5（迁移 0033 存量影响面）。

**需要真实飞书 / Git 平台 / Runner（4 项）** —— 跨系统链路，mock 掉就等于把被测物换成 mock 自己：
107-1（澄清必达真机链路）、109-1（编排直连执行流全链，要求容器真实拉起并产出 PR）、
109-2（飞书导出物的告示块）、110-3（真实调研容器的日志增量刷新与服务端脱敏）。

**团队策略决定（2 项）** —— 不是可断言的行为，是要人拍板的判断：
107-6（跨项目仓名可见是否仍可接受）、109-6（下游容器要不要消费 `unresearched` 标志）。

---

## 8. 闸门状态

| 闸门 | 结果 |
|---|---|
| `pnpm exec vitest run` | 2095 passed / 1 skipped（与基线一致） |
| `pnpm type-check` | exit 0 |
| `pnpm lint` | 111 problems（与基线一致，新增文件零新错） |
| `pnpm build` | 通过；构建对 `web/src/components.d.ts` 的改写已还原 |
| `pnpm exec playwright test --project=chromium` | **34 passed**（含既有 2 条 auth 用例） |
| 后端 | 未触碰（本次改动只在 `web/`），未复跑 9814 条 |

`web/pnpm-workspace.yaml` 无改动；`skills/` 与 `mcp/` 子模块指针未移动（全程按显式路径 `git add`）。

## 9. 怎么跑

```bash
cd web
pnpm test:e2e              # 全量（会自动起 10250 端口的 dev server）
pnpm test:e2e:ci           # 同上，显式 --project=chromium
pnpm exec playwright test --project=chromium routing-panel   # 单个 spec
```

本地若已有 dev server 跑在 10250，会被复用；CI 上 `reuseExistingServer: false`。

---

# v0.20.0 Phase 115 视觉 UAT 子集的自动化执行报告

_执行日期：2026-08-02 · 分支 `main` · 前端 `web/` · 追加于同一份报告，两个里程碑的 UAT 自动化记录并存_

## 10. 背景与结论

v0.20.0「技术方案蓝图」的 Phase 115 归档时留了 **4 项 `human_verification`**（见
`.planning/milestones/v0.20.0-phases/115-ui/115-VERIFICATION.md` frontmatter，全部 `blocking: false`）。
逐条读它们的 `why_human`，给出的理由**全部是 happy-dom 的能力缺口**，不是真需要人的判断：

| # | UAT | 原 `why_human` 的实质 |
|---|---|---|
| 1 | mermaid 出图 | 组件测试一律 `stubs: { MermaidDiagram: true }` ⇒ 测不到真渲染 |
| 2 | 选区 popover 落点 | happy-dom 无版面引擎，`Range.getBoundingClientRect()` 恒返零矩形 |
| 3 | 左栏十段导航高亮跟随滚动 | mount-only `IntersectionObserver` 需要真实版面 |
| 4 | 响应式断点 | happy-dom 不计算媒体查询 |

Chromium 有版面引擎、真 `getBoundingClientRect`、真 `IntersectionObserver`、真媒体查询 ⇒ 四条理由同时消解。

**结论：4 项判定核心全部 pass（11 条用例），过程中发现并修复 1 个真实缺陷。**
四项各自仍有真正需要人眼的**审美残留**，逐条留在 frontmatter 的 `residual_human` 里，⛔ 未整条勾掉。

## 11. 取证方式（沿用 v0.19 那一套，⛔ 不另起风格）

- 复用 `web/playwright.config.ts`：chromium 单浏览器、专用 10250 端口、自带 webServer。
- **API 全 mock、不起 Django、不连库**：`page.route('**/api/**')` + `tests/e2e/support/api.ts` 的默认路由表。
- 载荷形状照 `115-01-SUMMARY.md` §1 契约表与 `~/types/blueprint` 抄，落在新建的
  `tests/e2e/support/blueprintPayloads.ts`。`quality` 后三项**保持 `null` 不归一成 0**（§3 的
  「`null` ≠ `0`」纪律）—— fixture 一旦归一，「无数据档」的渲染分支就永不被走到，用例会绿得毫无意义。
- **一律从用户入口驱动**：`page.goto('/knowledge/blueprints/:id')` → 真滚动 / 真鼠标拖选 /
  真改视口宽度。⛔ 不挂任何叶子组件（那一层的 prop 契约 vitest 已覆盖，这一层要兜的恰恰是
  「组件对了但版面上不成立」）。
- ⚠️ 一个坑：`playwright.config.ts` 的 `testIdAttribute` 是 `data-test`，而蓝图这批组件用的是
  `data-testid` ⇒ 选择器一律写 `[data-testid="…"]`，不能用 `getByTestId()`。
- ⚠️ 另一个坑：`AppSidebar` 也是 `<aside><nav>` 结构，裸 `aside nav` 会先命中全局侧栏 ⇒ 段导航
  一律经 `aside.w-48 nav` 作用域化。

## 12. 逐项结果与变异证据

**变异方法**：每项都把被测物真改坏一次，确认用例转红，再还原。这是本报告唯一承认的「用例非空转」证据。

### 12.1 UAT 1 — mermaid 出图 · **pass**

`UAT 115-1`（3 例）：

- 合法源码 ⇒ 真 `<svg>` 恰 1 个且有面积（>80×80）、节点文案「库存充足?」出现在 SVG 内部、
  `path` 连线 >0、出图态下同卡零 `<pre>`、「放大」入口出现。
  ⭐ 断的是**真 SVG**，不是「组件收到了 `code` prop」——后者那层组件测试已覆盖。
- 空源码（缺 `mermaid` 键 / 全空白串）两张卡 ⇒ `<pre>` / `blueprint-block` / `svg` **三者全 0**，
  而 4 行步骤表照渲（证明段本身非空 ⇒ 「零 pre」不是恒真）。
- 非法源码 ⇒ 回退 `<pre>` + 「无法渲染流程图，已展示源码」，作**非恒真对照**：证明上一条的
  「零 `<pre>`」不是因为 `<pre>` 在这条链路上永远不渲染。

**变异**：
1. `MermaidDiagram.render` 里 `svg.value = out.svg` → `svg.value = ''` ⇒ SVG 计数 1→0，转红。
2. 去掉 `InteractionFlowsSection.mermaidBlocks` 的空源码闸（并让 `BlueprintBlock` 内层
   `v-else-if="text.trim()"` 恒真）⇒ **冒出 2 个空 `<pre>`**，`pre` 计数断言转红。
   这就是 UAT 原文「空源码时不出现空 `<pre>`」所防的形状。
3. 登记一次失败的变异尝试：单独让 `BlueprintBlock` 的内层闸恒真**测不出来** —— 因为外层
   `mermaidBlocks()` 已经把空源码挡掉，内层闸在这条链路上根本到不了。真正的「调用方 `v-if`」
   是 `mermaidBlocks()`，⛔ 不是组件内那一句。

### 12.2 UAT 2 — 选区 popover 落点 · **pass（判定核心）**

`UAT 115-2`（2 例）。真鼠标拖选（`mouse.down` → `move(steps:12)` → `up`）后：

- 选区矩形**非零**（正是 happy-dom 拿不到的那件东西）；
- 浮层与选区矩形**零交叠** ⇒ 不遮挡被选文本；
- 竖直缝隙 ∈ [0, 14]px（`side-offset=8` + 子像素余量）⇒ 「贴着」；
- 浮层水平中心与选区中心相差 ≤24px ⇒ **锚在选区上**，而不是漂在视口角落；
- Esc 后浮层 `count == 0` 且 `window.getSelection().toString()` **逐字等于**拖选前的文本。

**变异**：
1. 把 `PopoverAnchor` 的 `anchorStyle` 退化成零矩形（即 happy-dom 的形状）⇒ 浮层飘到选区外
   **352px**，「贴着」断言转红。这直接证明本例测的就是 happy-dom 测不到的那个量。
2. 在 `onOpenChange` 里补一句 `window.getSelection()?.removeAllRanges()` ⇒ Esc 保留选区转红。
3. 反例登记：去掉 `@close-auto-focus` 的 `preventDefault()` **不足以**破坏选区（Chromium 焦点
   归还不折叠选区）⇒ 该 handler 的选区保护作用**未被本层证实**，不宣称覆盖。

⚠️ **一条与实现不符的 expected（需人拍板，不由测试单方面认定）**：UAT 原文写「popover 贴着选区
**末端**出现」，而 `BlueprintSelectionPopover` 把**整个选区矩形**作为 `PopoverAnchor`、`side="top"`
⇒ 浮层实际落在选区**正上方居中**。可判定内核（不遮挡 / 贴着 / 锚在选区上）全部成立，但「末端」
这一措辞要么改 expected 要么改实现。⛔ 没有为了对齐措辞去松断言。

### 12.3 UAT 3 — 左栏十段导航高亮跟随滚动 · **pass，且发现 1 个真实缺陷**

`UAT 115-3`（2 例）。逐段滚动十次，左栏高亮下标实测走出 `[0..9]` **完整序列**；断言的是整条
序列相等 ⇒ 「一直是 0」与「卡在某一项」都会转红。高亮态取两个独立来源（`bg-primary/8` 类名 +
左侧指示条 span）并**互校**，不一致直接抛错而非静默取其一。

**变异（本次最关键的一条）**：给 `#impact_analysis` 加 `v-if="content"` ⇒
- 段容器在断言时**仍在 DOM**（`section[id]` 计数照样 10）、点击跳转照常工作；
- 但 mount 那一刻它不在 ⇒ observer 挂不上 ⇒ 第 5 项**永不点亮**；
- 用例报 `段 impact_analysis 未点亮左栏第 5 项`，转红。

这正是 P-4 描述的「人肉走查只会觉得高亮有点迟钝、不会当成 bug」的缺陷形状 —— 十个 `<section>`
之所以无条件渲染就是为了防它。**防线能真的触发。**

⭐ **新发现的缺陷（已修，commit `0fd29f56` `fix(nav):`）**：
`AnchorNavLayout` 的观察窗 `rootMargin: -15% 0px -55% 0px` 把可观察带掐到视口的 15%~45%，
于是**文档首尾各留了一段谁都不相交的死区**，而回调里 `if (visible.length > 0)` 在死区内不更新
`activeSection` ⇒ **滚回顶部时高亮冻在离开前那一段**。

实测（蓝图查看器，视口 720px）：观察窗 108~324px，而首段 `requirement_spec` 在 `scrollTop=0`
时起点是 **349px** ⇒ 顶部确实没有任何段相交。用户看着文档开头，左栏却高亮着「验收锚点」。
这与 P-4 防的「永远停在第一段」是同一类失守，只是方向相反。

- 该 349px 的空档来自页面自身的固定件（sticky 顶栏 + 阶段时间线），**不是 fixture 撑出来的**；
  真实数据下阶段时间线只会更高。
- 修法：相交集合为空时补一次基于位置的兜底 —— 取观察窗上沿之上最近的那一段，全都在下方则
  回到第一段。顺带把 15/55 抽成常量供 `rootMargin` 与兜底共用（用整数百分比：`0.55 * 100`
  在浮点下是 `55.00000000000001`）。
- **四个使用方同步受益**：蓝图查看器 / 知识实体详情 / 仓库详情 / 空间详情。
- 回归护栏：`UAT 115-3` 的第 2 例「回滚到顶部高亮退回第一段」。

### 12.4 UAT 4 — 响应式断点 · **pass**

`UAT 115-4`（4 例）。可判定内核 =「任一窗宽下**可见**的线程侧栏实例恰好一份」：

| 窗宽 | 常驻栏 `blueprint-sidebar-column` | 抽屉 `blueprint-sidebar-sheet` | 可见实例 |
|---|---|---|---|
| 1440（≥ xl） | 可见 | **整块不在 DOM**（`v-if="!isWide"`） | 1；点「查看批注」后仍 1 |
| 1279 / 1024（< xl） | 在 DOM 但 `hidden` | 点「查看批注」后可见 | 1 |
| 宽→窄→宽连续切换 | — | 回宽屏后 `count == 0` | 全程 ≤1 |
| 767（< md） | — | — | 左栏 `aside.w-48 nav` 隐藏、`blueprint-section-nav` 可见，且 `scrollWidth - clientWidth ≤ 1` |

⭐ 抽屉在宽屏是**整块不渲染**而不是 `xl:hidden` 藏起来 —— 后者会让 reka-ui 的焦点陷阱锁进一个
不可见容器。这条差异被 `toHaveCount(0)` 而不是 `toBeHidden()` 钉死。

**变异**：常驻侧栏 `xl:flex` → `lg:flex`（与抽屉的 `isWide` 闸脱钩）⇒ 1024px 下常驻栏与抽屉
**同时可见**，「< xl」与「连续切换」两例双双转红。

## 13. 残留人工项（⛔ 未因主体转绿而勾掉）

| UAT | 残留 | 为什么仍需人 |
|---|---|---|
| 1 | 「放大」全屏弹层内容 | 只验了触发按钮存在，未打开 `VueFinalModal` |
| 1 | 复杂真实流程图的排版观感 | 节点重叠 / 连线绕行 / 长中文标签截断属审美判断 |
| 2 | **「贴着选区末端」措辞与实现不符** | 实现是「选区正上方居中」；改措辞还是改实现要人拍板 |
| 2 | 跨行长选区的浮层落点 | 并集包围盒 ⇒ 浮层居中在整块之上，是否可接受属审美 |
| 3 | 连续惯性滚动下的高亮抖动观感 | 只验了瞬时跳转两种方式 |
| 4 | `BlueprintSectionNav` 的 Select 展开跳段 | 只验了它在 < md 可见、≥ md 隐藏 |
| 4 | < md 下逐段正文的窄屏可读性 | 只验了页面整体无横向溢出 |

## 14. 闸门状态（本次）

| 闸门 | 结果 | 对比基线 |
|---|---|---|
| `pnpm exec vitest run` | **2095 passed / 1 skipped** | 逐字一致 |
| `pnpm type-check` | exit **0** | 一致 |
| `pnpm lint` | **111 problems**（106 errors / 5 warnings） | 逐字一致，触碰文件零新增 |
| `pnpm build` | 通过 | 对 `web/src/components.d.ts` 的改写已 `git checkout` 还原 |
| `pnpm exec playwright test` | **45 passed** | 既有 34 + 本次 11，零回归 |
| 后端 | 未触碰（改动只在 `web/` 与 `.planning/`），未复跑 | — |

`web/pnpm-workspace.yaml` 无改动；`skills/` 与 `mcp/` 子模块指针未移动（全程按显式路径 `git add`）。

## 15. 本次提交

| commit | 内容 |
|---|---|
| `0fd29f56` | `fix(nav):` 滚回文档顶部时左栏锚点高亮冻在离开前那一段（`AnchorNavLayout` 死区兜底） |
| `cf7f3c26` | `test(e2e):` Phase 115 四条视觉 UAT 的浏览器护栏（11 例 + 载荷 builder） |

## 16. 怎么跑

```bash
cd web
pnpm exec playwright test blueprint-viewer-visual     # 只跑本次这 11 条
pnpm test:e2e                                          # 全量 45 条
```
