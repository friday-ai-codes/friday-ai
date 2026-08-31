---
quick_id: 260808-g1c
status: completed
completed: 2026-08-08
commits:

  - 2c2dfdf3
  - a87ed7dd
  - 67dbc613
  - 7d9868a2
  - 4cd0f763
  - a77f3470

audit_acknowledged:
  milestone: v0.25.0
  at: 2026-08-31
  status: completed
---

# Quick Task 260808-g1c 执行总结

AI 对话的思考过程现在默认全量实时可见（不再有首行预览截断与内层滚动裁切），
上游不下发思考文本时界面显示「正在思考」占位而非孤立闪烁光标，后端补了一条
`chat_thinking_text_empty` 采样事件用于留痕。默认模型仍是 `claude-opus-4-8`，
未动任何数据库数据、`ProviderCredential.default_model` 与 `_thinking_budget_tokens`。

## 提交清单

| Task | Commit | 类型 | 文件 |
| --- | --- | --- | --- |
| Task 1 | `2c2dfdf3` | feat | `web/src/components/chat/ChatMessageBubble.vue` |
| Task 2 | `a87ed7dd` | feat | `web/src/components/chat/ToolProcessGroup.vue` |
| Task 3 | `67dbc613` | feat | `web/src/components/chat/ChatMessageBubble.vue` |
| Task 3 修正 | `4cd0f763` | fix | `web/src/components/chat/ChatMessageBubble.vue` |
| Task 4 | `7d9868a2` | feat | `server/agents/chat_runner.py` |
| Task 5 | `a77f3470` | test | 3 个测试文件 |

## 各 Task 实际改动

### Task 1 — thinking part 默认全量展开、去截断（`2c2dfdf3`）

`web/src/components/chat/ChatMessageBubble.vue`

- L256 `showThinking = ref(true)`（原 `ref(!!props.isStreaming)`），L266 附近换消息时的
  watch 重置同步改为恒 `true`，历史消息也默认展开。

- L692–701：`expandedThinking` → `collapsedThinking`，Set 语义反转为「记录被用户手动
  收起的 id」，新增 `isThinkingExpanded(id) => !collapsedThinking.has(id)`。按计划要求
  **没有**采用「把全量 id 塞进 Set」的写法——parts 流式增长，后到的 id 不在集合里会退回收起。

- 删除 `thinkingPreview()` 与 `thinkingIsMultiline()`（`rg` 确认本组件内无其他引用；
  `web/src/components/admin/ReadonlyConversationView.vue` 有各自的同名副本，不在本任务范围，未动）。

- 模板 L1296–1314：删除 `timeline-step-text--preview` 分支，正文始终渲染 `item.text.trim()`；
  chevron 的 `rotate-90` 与 `is-expanded` 改绑 `isThinkingExpanded(item.id)`。

- L1329 `:default-expanded="true"`（原 `!!isStreaming`）。
- 样式：删除 `.timeline-step-text--preview` 规则（已成死代码）；`.thinking-content`
  去掉 `max-height: 30rem` 与 `overflow-y: auto`，保留 `white-space: pre-wrap`。

思考块仍可点击手动收起（`is-expandable` 恒挂），只是初始态为展开。

### Task 2 — 过程面板内思考步骤默认展开、去截断（`a87ed7dd`）

`web/src/components/chat/ToolProcessGroup.vue`

- L53 `withDefaults(..., { defaultExpanded: true })`。
- L62–63：新增 `collapsedRows`（thinking 行的「手动收起集合」），保留 `expandedRows`
  给 tool 行。**两个集合并存**是必须的：thinking 默认展开需要收起集合，tool 维持
  默认收起需要展开集合，单一集合无法同时表达两个默认值。

- L106–117：新增 `rowExpanded(step)` 统一判定；`toggleRow(step)` 按步骤类型选桶
  （签名由 `id: string` 改为 `step: ProcessStep`，调用点 L210 同步）。

- L143–145 `rowExpandable`：thinking 分支恒 `true`（原「>90 字符或含换行」），
  短思考也能展开看全文。

- L120–126 `stepText` 的 90 字符截断按计划**保留**（行头单行摘要，去掉会破坏布局）。
- 样式：`.tpg-list` 去掉 `max-height: 26rem` / `overflow-y: auto`。

### Task 3 —「正在思考」占位（`67dbc613` + 修正 `4cd0f763`）

`web/src/components/chat/ChatMessageBubble.vue` L1443–1456、L2262–2272

- 原来的裸 `<span class="typing-cursor" />` 换成 `.thinking-placeholder`：
  `icon-[lucide--sparkles]` + `animate-pulse`（复用既有 `.thinking-icon`）+ 文案「正在思考」

  + 保留 `typing-cursor` 作为动态指示。文案硬编码中文，未引入 i18n key。
- L1450 的「非空时行尾光标」`v-else-if` 分支原样未动。
- 不依赖任何后端事件，`suppressTypingCursor`（`waiting_clarification`）抑制行为不变。

### Task 4 — 空思考文本的可观测事件（`7d9868a2`）

`server/agents/chat_runner.py`

- L889–890：turn 开头初始化 `_thinking_block_seen` / `_thinking_chars`。
- L965、L970：`reasoning`/`thinking` 分支置位并累加长度（**只累加长度，不留内容**）。
- L1006–1023：chunk 循环结束后、`if full_message is None` 之前，若
  「出现过 thinking 块且累计文本长度为 0」则记一次
  `logger.info("chat_thinking_text_empty", category="sampling", component="chat_runner",
  model=..., provider=..., session_id=..., duration_ms=...)`。

- 整段包在 `try/except Exception: pass` 里，best-effort，绝不反噬流式主链；
  只在 turn 收尾记一次，不进 chunk 循环。触发用户由入口中间件的 contextvars 注入
  （与相邻的 `arecord_llm_usage` 同一条链路），未额外传 `initiated_by_user_id`。

- 未改 `_thinking_budget_tokens`，未新增面向前端的解释性 `THINKING` 事件。

### Task 5 — 测试契约同步（`a77f3470`）

- `web/src/components/chat/__tests__/chat-visual-contract.spec.ts`：原「collapsible preview」
  契约整条替换为三条新契约——① thinking 默认展开（断言存在 `collapsedThinking` /
  `isThinkingExpanded`，不存在 `timeline-step-text--preview` / `thinkingPreview` /
  `thinkingIsMultiline`，`.thinking-content` 无 `max-height`）；②「正在思考」占位存在且
  判定不依赖后端事件；③ ToolProcessGroup 默认展开且 `.tpg-list` 无 `max-height`。

- `web/src/components/chat/__tests__/chatMessageBubble.parts.spec.ts`：新增 4b（长思考含换行
  且 >80 字符时默认全文可见、无 `…`、无 preview class）、4c（点击可手动收起）、
  4d（流式且无任何 part 时渲染「正在思考」）、4e（首个 thinking part 到达后占位让位）。

- `web/src/stores/__tests__/chat.parts.spec.ts`：新增 2b，thinking `part_started` + 三次
  `part_delta` 累加，断言 `streamingParts[0].text` 在 `part_completed` **之前**就是拼接全文。

## 偏离 PLAN.md 的地方

**1. Task 3 的触发条件从 `groupedDisplayItems.length === 0` 改为 `!hasVisibleContent`（`4cd0f763`）**

计划写的是「沿用现有的 `isStreaming && !suppressTypingCursor && groupedDisplayItems.length === 0`」。
按字面实现后，新写的 4d 用例红了。实测原因：流式且 `chatStore.streamingParts` 还空着时，
`displayParts`（L188–212）会走 `hydrateLegacyMessage` 兜底，合成一条 `text=''` 的 text part，
于是 `groupedDisplayItems.length` 恒 ≥ 1 —— 那条 `v-if` 分支在等待期**根本走不到**，
实际渲染的是「一个空 `.ai-prose` + `v-else-if` 的裸光标」，正好就是用户抱怨的现象。

因此新增 `hasVisibleContent`（L661–668）：空 text part 不算内容。这是让 Task 3 的
done 判据（「流式等待期不再是裸光标」）真正成立的必要修正，其余性质均保持计划要求
——不依赖后端事件、SSE 一通即出现、有内容自动让位、`suppressTypingCursor` 行为不变。
该修正单独一个 `fix` 提交，视觉契约测试里也加了对应断言防回归。

**2. Task 1 删掉了 `thinkingIsMultiline`（计划说「若仅用于是否可折叠可保留」）**

选择删除并让 thinking 块恒可切换，与 Task 2「thinking 行恒可展开」保持一致，
也避免短思考无法手动收起。计划对此留了余地，属允许范围。

**3. Task 2 保留了 `expandedRows` 而非只改名为 `collapsedRows`**

计划说「反转语义为 `collapsedRows`」，但同时要求 tool 行保持默认收起。单一集合
无法同时表达「thinking 默认展开」和「tool 默认收起」两个默认值，故两个集合并存，
由 `rowExpanded(step)` 统一分派。

**4. `server/agents/chat_runner.py` L284–287 的既有格式问题未纳入本次提交**

`uv run ruff format` 会顺手把这段（本任务未触碰、改动前就已存在）折行合并成一行。
为保持提交原子性已手工还原，因此 `ruff format --check` 对该文件仍报 1 处
「would reformat」——是既存历史问题，不是本次引入。`ruff check` 全绿。

## 测试与 Lint 结果

| 项 | 命令 | 结果 |
| --- | --- | --- |
| 前端定向 | `pnpm vitest run src/components/chat/__tests__ src/stores/__tests__` | 44 files / 479 tests 全通过 |
| 前端全量 | `pnpm vitest run` | 234 passed + 1 skipped（2328 passed / 1 skipped） |
| 前端 lint | `pnpm eslint --fix` 覆盖 5 个改动文件 | 无报错 |
| 后端 lint | `uv run ruff check agents/chat_runner.py` | All checks passed |
| 后端格式 | `uv run ruff format` | 本次改动均合规；仅剩 L284 既存历史问题（见偏离 4） |
| 后端测试 | `uv run pytest tests/ -k "chat_runner or stream_view or chat_e2e" -q` | 64 passed / 3 skipped |

### 后端测试环境说明

首次运行时 34 条用例在 **setup 阶段**报错：`DuplicateDatabase: database "test_friday"
already exists`，加 `--reuse-db` 后转为 `auth_permission` 外键约束冲突——远端 Postgres
（`10.8.8.153:15432`）上遗留的 `test_friday` 处于半迁移的损坏状态，与本次代码改动无关。
按「不修改任何数据库数据」的约束，**没有**去 drop 那个共享测试库，改为用一次性 SQLite
覆盖 `DATABASE_URL` 跑完验证（跑完即删临时文件）：

```bash
DATABASE_URL="sqlite:////tmp/g1c_test.sqlite3" uv run pytest tests/ -k "chat_runner or stream_view or chat_e2e" -q
```

若要在 Postgres 上复跑，需要先由环境负责人清理掉损坏的 `test_friday`。

## 人工验证待办

Task 3 的最终观感需要人工确认一次：新建对话发一句话，首字到达前界面应显示
「正在思考」（sparkles 图标 + 呼吸动效），首个 part 到达后自动让位。

## 未做（与计划一致）

- 未切换默认模型，`ProviderCredential.default_model` 保持 `claude-opus-4-8`。
- 未改 `_thinking_budget_tokens`、未动系统提示词/工具 schema。
- 未给 thinking 加 markdown 渲染，未引入 i18n key。
- 未改 store / SSE 层 / 后端事件协议（前端数据层本就实时累加，已由新增的 store 用例锁住）。
- 未动 `mcp/`、`skills/` 子模块与 `ROADMAP.md`；`.planning/` 下文档未提交。
