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
