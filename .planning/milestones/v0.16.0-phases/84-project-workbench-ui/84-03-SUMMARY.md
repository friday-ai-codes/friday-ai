# 84-03 SUMMARY — WB-03 工作区 5 文件查看/编辑 + 记忆草稿确认

**Plan:** `.planning/phases/84-project-workbench-ui/84-03-PLAN.md`
**Wave:** 2 · depends_on [84-01, 84-02]
**Status:** ✅ 完成（vue-tsc 绿；DocsSection 守护测试 5/5 通过；workbench 全量 17/17 通过）

## 交付物

| 文件 | 类型 | 说明 |
|------|------|------|
| `web/src/components/project/workbench/MarkdownSourceEditor.vue` | 新增 | CM6 markdown 源码编辑器：`markdown()` + `fridayLightTheme` + `search()` + `lineWrapping`，`:readonly`（`:disabled`）双向绑定；仿 `PromptBodyEditor`/`JsonEditor`，不引入暗色 one-dark。 |
| `web/src/components/project/workbench/DocsSection.vue` | 补全占位 | 5 文件切换（memory/state/milestones/research/preflight，带 sync_status 灯）+ 查看态 `MarkdownRenderer` 渲染 `rendered_markdown` + 编辑态按 block `section` 渲染（system 只读 / human 可编辑）+ 「保存到飞书」调 `updateHumanBlocks` → 失效查询 + sync_status 轮询；冲突（409/422）保留改动并提示。 |
| `web/src/components/project/workbench/MemorySection.vue` | 新增 | 复用 `MemoryTab` 模式：记忆条目（`MarkdownRenderer` 渲染）/ 新增 / 行内编辑 + LLM 草稿采纳（`useConfirmDialog` 二次确认 → `confirmDraft`）/ 拒绝（`rejectDraft`）。 |
| `web/src/components/project/workbench/__tests__/DocsSection.spec.ts` | 新增 | 守护测试：5 文件切换、查看渲染、编辑态 system 只读 vs human 可编辑、保存调 `updateHumanBlocks` + 重新拉取、MEMORY 草稿采纳触发 confirm+confirmDraft，真实 `zh-CN.json` 文案断言。 |

## 关键实现决策

- **依赖**：`@codemirror/lang-markdown` 已在 `web/pnpm-workspace.yaml` catalog（`^6.5.0`）+ `web/package.json` 引用且已安装（`node_modules/.pnpm/@codemirror+lang-markdown@6.5.0`），故 Task 1 无需改 catalog/package.json。
- **i18n**：`projects.workbench.docs.*` 键已存在（`file.{memory,state,milestones,research,preflight}`、`humanArea`、`noHumanArea`、`fileNavLabel`、`saveFailed`、`saveConflict`、`systemReadonly`、`empty` 等），组件直接复用，**未改动共享 `zh-CN.json`**（规避与并行 84-04 的冲突）。
- **查看 = 渲染、编辑 = 源码**：查看走 `MarkdownRenderer`（`getMarkdownRenderer` `html:false`，XSS 隔离于渲染侧）；编辑走 CM6 源码（不渲染/不执行 HTML），符合 CONTEXT 特定意见（弃 tiptap）。
- **只读保护**：前端 system block 强制 `:readonly`；真正闸门在后端 84-01（拒绝 system 写）。
- **派发→轮询**：`refetchInterval: q => q.state.data?.sync_status === 'syncing' ? 2000 : false`（仿 `ReconcilePanel`）；保存成功 `invalidateQueries(['project-doc', id, docType])`。
- **queryKeys**：`['project-docs', idRef]`（文件灯）、`['project-doc', idRef, docType]`（单文档）。
- **MEMORY 路由**：`doc_type === 'memory'` 时 DocsSection 挂载 `MemorySection`，其余 4 文件走通用查看/编辑。

## 验证

- `pnpm vue-tsc --noEmit` → 通过（exit 0）。
- `pnpm vitest run src/components/project/workbench/__tests__/DocsSection.spec.ts` → 5/5 通过。
- `pnpm vitest run src/components/project/workbench` → 17/17 通过（含既有 MemoryTab/Overview 等，基线未破）。
- 无 lint 报错。

## 安全（threat_model 对账）

- T-84-08（渲染 XSS）：`MarkdownRenderer` `html:false`，CM 源码不执行。
- T-84-09（系统区篡改）：system block `:readonly`，后端为最终闸门。
- T-84-10（草稿采纳）：采纳/拒绝均经 `useConfirmDialog` 二次确认。
- T-84-SC（依赖来源）：`@codemirror/lang-markdown` 为 CM6 官方 scope，经 catalog 钉版本 + lockfile。

## 未做 / 范围外

- 未改 `package.json` / `pnpm-workspace.yaml`（依赖已就位）。
- 未改 `zh-CN.json` / `components.d.ts`（键已存在；组件走显式 import，无需全局注册）。
- LLM 提议 vs 现状 diff（UI-SPEC 标「可选增强」）未做。
