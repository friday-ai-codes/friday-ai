# Phase 62 — UI Review

**Audited:** 2026-06-21
**Baseline:** `.planning/phases/62-crawl/62-UI-SPEC.md` (approved design contract)
**Component:** `web/src/components/knowledge/BatchIngestPanel.vue`
**Screenshots:** not captured — Playwright browser binary not installed; panel also sits behind auth + requires live backend durable-queue data, so a static capture would only show the login wall. Audit is code + contract + guard-test based.
**Status:** Advisory / non-blocking.

---

## Pillar Scores

| Pillar | Score | Key Finding |
|--------|-------|-------------|
| 1. Copywriting | 4/4 | 全部文案走 `t('crawlQueue.*')`，与契约逐字一致；无硬编码中文 |
| 2. Visuals | 4/4 | 卡片头/入队区/列表区清晰分层，徽标图标+文字双编码，CTA 为焦点 |
| 3. Color | 4/4 | primary 仅用于 CTA/spinner/链接，徽标复用既有 5 个 variant，无新增色板 |
| 4. Typography | 4/4 | `text-sm`/`text-xs` 一致，`font-semibold`/`font-medium` 分级，无越界字号 |
| 5. Spacing | 4/4 | `p-5`/`px-5 py-3.5`/`py-3`/`gap-2`/`gap-3` 完全沿用既有刻度，无任意 px 值 |
| 6. Experience Design | 3/4 | 六态齐全且确认/轮询/在途禁用到位；但**轮询条件含 `queued`**，偏离契约「仅 running」 |

**Overall: 23/24**

---

## Top 3 Priority Fixes

1. **轮询条件偏离契约（WARNING）** — `refetchInterval` 在 `running || queued` 时启动 2s 轮询（`BatchIngestPanel.vue:31-32`），契约 Interaction 明确为「存在 `running` 项 → 2000ms，否则 false（全部终态停轮）」。一个仅含 `queued`（未点开始）的批次会**永久 2s 轮询且状态不变**，造成无意义网络开销。修复：改为 `r => r.status === 'running'`，或与 ui-researcher 确认是否要更新契约把 `queued` 纳入（若确为有意改进，应回写 UI-SPEC 而非静默偏离）。
2. **列表项 `title` 暴露 batch_id 而非链接全文（minor）** — 第一行 url 摘要 `:title="item.batch_id"`（`BatchIngestPanel.vue:318`），契约 Layout 要求 url 摘要 `truncate` + `title` 显示「全文」。因后端只回 `url_count` 不回 URL 列表，显示「N 个链接」合理，但 hover title 给出 `batch_id` 与契约语义不符。修复：若需调试用 id 钩子，改用 `font-mono` 的次要展示或保持 title 但在文档注明语义；否则移除误导性 title。
3. **`crawlQueue.loading` 键已定义但未使用（trivial）** — 契约状态 1 规定 loading 用 `Skeleton`，实现正确用了骨架（`:284-286`），导致 i18n 中 `crawlQueue.loading`（zh-CN.json:620）成为死键。修复：删除该键，或在骨架旁加可读 loading 文案以消费它（可提升可访问性）。

---

## Detailed Findings

### Pillar 1: Copywriting (4/4)
- 全部用户可见文本经 `t('crawlQueue.*')`：标题/副标题（`:199,:203`）、入队按钮含 enqueuing 态（`:226`）、状态徽标（`:326`）、动作含进行态（`:358,:375,:392`）、停止确认三段（`:129-132`）、空态（`:303-304`）、错误与重试（`:291,:295`）。
- `web/src/locales/zh-CN.json:610-659` 的 `crawlQueue.*` 与契约 i18n 块**逐字一致**（status/actions/stopConfirm/feishuNotConfigured 全覆盖），新增为 additive，未改动既有键。
- feishu 引导按钮文案复用 `crawlQueue.feishuNotConfigured.configure`（`:248`），提示正文用后端 `res.message`（`:238`）——符合契约「复用既有 key + 后端 message 直出」。
- 守护测试 `__tests__/BatchIngestPanel.spec.ts` 以真实 `zh-CN.json` 锁文案（排队中/进行中/已停止/失败/已完成、失败原因、停止任务、幂等可重投），关键措辞不被改空。
- 唯一瑕疵：`crawlQueue.loading` 键未被消费（见 Top Fix 3）。非文案缺陷。

### Pillar 2: Visuals (4/4)
- 单卡片容器（`class="card"`，`:193`），四段式分层：卡片头 → 入队区 → 列表头 → 列表/空/错/骨架，段间 `border-b border-border/50`，与 `ReconcilePanel` 视觉同构。
- 焦点清晰：主 CTA「入队」为 primary 实心按钮，列表行内动作为 outline 次级按钮，层级分明。
- 状态徽标**颜色+图标+文字三重编码**（`:321-327`），不靠颜色单独表意，满足契约 Accessibility 要求。
- 行内动作进行中显式 spinner（`icon-[lucide--loader-circle] animate-spin`），状态徽标 running 同样旋转，反馈一致。
- 轻微：装饰性图标（`link-2`/`alert-triangle`/`plus`/`settings`）未加 `aria-hidden`；因 iconify span 无文本内容对读屏基本无害，不扣分。

### Pillar 3: Color (4/4)
- Accent（`primary`）严格限定：入队 CTA（default variant = primary）、入队 spinner（`:224`）、卡片头图标（`:197`）、输入框 focus ring（`focus:ring-primary/40`，`:215`）。次级按钮一律 `variant="outline"`，未滥用 primary，符合契约「primary 不用于行内 start/retry」。
- 停止按钮用 `text-destructive hover:text-destructive` + outline（`:366`），符合契约「停止用 destructive 文字色」而非整块红底。
- 状态徽标复用 `ui/badge` 既有 5 个 variant（`muted/info/warning/destructive/success`，`:156-162`），与契约配色表逐行对应，**未新增 variant / 色板**。
- 唯一硬编码色为 feishu 黄框 `amber-500/30`+`amber-600/700`（`:233-237`）——契约 State 6 明确要求「保留既有黄框引导块 amber-500/30」，属合规例外。

### Pillar 4: Typography (4/4)
- 字号仅 `text-sm`（标题/url 摘要/列表头）与 `text-xs`（副标题/时间戳/进度/错误/feishu 文案），未超契约 token，无 >4 字号问题。
- 权重 `font-semibold`（卡片标题 `:198`）/`font-medium`（列表头 `:265`、url 摘要 `:318`），契约将 url 摘要归为 body(400)，此处用 medium 略重——视为可接受的层级强化，不扣分。
- 机器值（`batch_id`）当前仅出现在 `title` 属性未在正文渲染，故未触发契约的 `font-mono text-[11px]` 要求；若后续展示 `run_id`/idempotency key 需补 `font-mono`。

### Pillar 5: Spacing (4/4)
- 卡片头 `px-5 py-3.5`、入队区 `p-5`、列表头/项 `px-5 py-3`、徽标/动作 `gap-2`、行内段 `gap-3`、`space-y-3`/`space-y-2`——与契约 Spacing Scale 及 `ReconcilePanel` 完全一致。
- 输入框 `h-9`、次级按钮 `h-8`、feishu 按钮 `h-7`——契约允许的紧凑触控目标区间。
- 列表项分隔 `divide-y divide-border/40`（`:309`），符合契约 Layout。
- 全文件**无任意值 spacing**（无 `p-[..px]`/`m-[..rem]`），刻度纪律良好。

### Pillar 6: Experience Design (3/4)
覆盖六态（契约 Component States 1–6）全部命中：
- **loading**：`Skeleton ×3`（`:284-286`），不显示空态。✓
- **empty**：`CompactEmptyState` icon `lucide--inbox` + title/body（`:300-306`），`data-testid="crawl-queue-empty"`。✓
- **populated**：`v-for` 列表项，含 url 摘要/徽标/进度/时间戳。✓
- **per-item status**：5 态徽标 + failed 项展开后端 `error` 红字（`:338-340`）。✓
- **error**：`isError` → loadError 红字 + 「重试加载」`refetch`（`:289-297`），沿用 `ReconcilePanel` 范式。✓
- **feishu_not_configured**：amber 黄框 + 深链按钮 `router.push`（`:231-251`），行为不回退。✓

交互纪律到位：
- **真相源为后端 DB**：列表来自 `useQuery(['crawl-ingest-queue'])`，无内存 `batchId`/`runTriple`/`pollStartedAt` 作为列表来源（`actingKey` 仅作在途标记，合规）。刷新/容器重建可由 list 端点恢复。✓
- **停止破坏性确认**：`confirm({ variant:'destructive', confirmText, description含「幂等可重投」})`（`:127-136`），取消则不调用——守护测试 b2/b2b 验证。✓
- **retry 非破坏性无确认**（`:143`），守护测试 b3 验证。✓
- **在途禁用 + spinner**：`isRowBusy` 禁用整行动作，`isActing` 切换 spinner/文案。✓
- 动作成功后 `invalidateQueries` 立即重拉。✓

**扣 1 分的偏离**：
- **轮询条件含 `queued`**（`:31-32`）偏离契约「仅 `running` 触发 2s，全部终态停轮」。`queued` 非终态但在未点开始时不会自行推进，会导致无谓的持续轮询（见 Top Fix 1）。属真实契约偏离，建议改回 `running` 或正式回写 UI-SPEC。
- 次要：入队为 `crawlUrl()` → `enqueueQueue()` 两步非原子（`:55-66`）；契约 Interaction 第 145 行明确允许「入队前预处理」，故合规，但若 `crawlUrl` 成功而 `enqueueQueue` 失败，仅走 `enqueueFailed` 错误处理、不会留下半入队态——可接受，记录备查。

---

## data-testid / Reuse / a11y 合规核对

**data-testid 钩子（契约 9 项，全部命中）：** `crawl-queue-panel`(:193)、`crawl-url-input`(:213)、`crawl-enqueue-button`(:220)、`crawl-queue-list`(:309)、`crawl-queue-item`(:313)、`crawl-item-status`(:322)、`crawl-item-start/stop/retry`(:346/:363/:380)、`crawl-queue-empty`(:300)、`crawl-feishu-deeplink`(:241)。✓ 全覆盖。

**Reuse Map 合规：** 全部复用既有件，无重造——
- 派发→轮询：`useMutation`+`useQuery refetchInterval` 沿用 `ReconcilePanel`（除 queued 偏离）。
- 徽标：`~/components/ui/badge`，复用 `muted/info/warning/destructive/success`，无新 variant。
- 破坏性确认：`useConfirmDialog().confirm({variant:'destructive'})` + 全局 `GlobalConfirmDialog`（未新增弹窗组件）。
- 空态：`CompactEmptyState`；骨架：`~/components/ui/skeleton`；按钮：`~/components/ui/button`。
- API：在 `ingestApi` 扩展 `listQueue/enqueueQueue/startRun/stopRun/retryRun`（`api/ingest.ts:252-272`），未另起 client。
- 未引入第三方 registry（`shadcn_initialized: false`，Registry 安全门 not applicable）。✓

**i18n 合规：** `crawlQueue.*` additive 落地于 `zh-CN.json:610-659`，与契约逐字一致；模板无硬编码中文（仅注释为中文，`fmtTime` 的 `'zh-CN'` 为 `toLocaleTimeString` 区域参数，非文案）。✓

**Accessibility：** 徽标图标+文字双编码；行内动作按钮均带可读文案（开始/停止/重试），无纯图标按钮故无需额外 `aria-label`；`:disabled` 阻断点击；确认弹窗由 reka-ui AlertDialog 提供焦点陷阱/ESC。轻微：装饰性 icon span 未标 `aria-hidden`（无文本内容，影响低）。

---

## Registry Safety
`shadcn_initialized: false`，契约未列任何第三方 registry。Registry 审计跳过（not applicable）。

---

## Files Audited
- `.planning/phases/62-crawl/62-UI-SPEC.md`（契约基线）
- `web/src/components/knowledge/BatchIngestPanel.vue`（实现）
- `web/src/api/ingest.ts`（队列 list/enqueue/start/stop/retry）
- `web/src/locales/zh-CN.json`（`crawlQueue.*` 键）
- `web/src/components/knowledge/__tests__/BatchIngestPanel.spec.ts`（守护测试）
- 复用件核对：`web/src/components/common/CompactEmptyState.vue`、`web/src/components/ui/badge/index.ts`、`web/src/composables/useConfirmDialog.ts`、`web/src/components/repository/ReconcilePanel.vue`（轮询/确认参考实现）
