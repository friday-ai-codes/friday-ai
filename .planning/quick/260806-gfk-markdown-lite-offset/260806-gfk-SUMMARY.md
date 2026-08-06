---
quick_id: 260806-gfk
slug: markdown-lite-offset
status: complete
date: 2026-08-06
---

# Quick 260806-gfk 总结：需求规格正文 markdown-lite 渲染

## 交付

| 层 | 改动 |
|----|------|
| 前端工具 | 新增 `blueprintMarkdownLite.ts`：`isMarkdownishText` 分流 + `parseMarkdownLite`（行分级 h1–h4/task/bullet/ordered/blank + 行内 marker/bold/code 区间，全绝对 offset） |
| 块渲染 | `BlueprintBlock` paragraph 新增富分支：批注 segment ∪ 行 ∪ 样式三源切点出原子，标题分级加粗、`##`/`**`/`- [ ]` 记号淡化、加粗内容真加粗、行内 code 着色、按缩进 padding |
| 段容器 | `RequirementSpecSection` 目标/背景 BlockList 包 `.card`，正文不再裸浮渐变背景 |
| 类型修复 | `BlueprintThreadCard` 旧 composer 分支过滤出扁平 `{label,value}`（修上一任务 options 双形态引入的 TS 错） |

## 关键决策

- **坐标系零漂移是硬约束**：选区/批注 offset 按块内全部文本节点扁平拼接（`rangeOffsets`）
  ⇒ 富分支**逐字保留**全部字符（含记号、缩进空格、行尾 `\n`），只包元素与着色——
  Typora 源码高亮式，⛔ 不做渲染式 markdown（不删 `##`、不换 checkbox 控件）。
- 行尾 `\n` 留在行 div 末段文本节点里，作为块级末行分隔被浏览器丢弃，视觉无副作用。
- 组件测试钉死不变式：`rich.element.textContent === 源文本`；富分支上挂 anchor ⇒ `<mark>` 照常。

## 验证

- vitest：blueprintMarkdownLite 9 + BlueprintBlock 32 + sections 31 + threadSidebar 35 全绿
- `vue-tsc --noEmit` 退出 0；eslint 干净
- 可观测性：纯前端展示改动，无新调用入口/LLM/召回，无需新增埋点

## 复验补丁（2026-08-06 12:00，真机截图驱动）

- Playwright 带 superuser cookie 实测 `blueprints/bbedc1f2`：富分支已生效（此前用户看到旧样式是浏览器旧 bundle）。
- 据真实数据补两处：`- #### 功能点` 列表嵌标题按标题渲染（`- ####` 整段淡化）；
  句中任务框 `- [ ]`（`验收：- [ ]…`）以 inline marker 淡化，行首记号区间作已占用传入防重叠。
- vitest 43 passed；`vue-tsc` 退出 0。

## 升级为预览式渲染（2026-08-06 12:14，用户点名要预览效果）

- 记号档从「淡化可见」升级为「**零宽隐藏**」：`marker`/`taskbox` 用 `text-[0px]`，
  字符仍在文本节点里（`rangeOffsets` 坐标系与 `selection.toString()` 都不受影响），
  视觉替代物全部用**伪元素**画（不产生文本节点）：任务框 `- [ ]` → CSS 勾选框、
  bullet `- ` → 圆点、`##`/`**`/反引号 → 彻底不可见。
- 有序编号（`1. `）新增 `dim` 档：携带信息 ⇒ 淡化可见，⛔ 不隐藏。
- 隐藏记号原子挂 `aria-hidden`（语法噪声对读屏静音）。
- Playwright 真机复验：标题干净无 `##`、验收行是勾选框 + 加粗关键词，预览观感达成；
  vitest 75 passed、`vue-tsc` 退出 0。

## v3：渲染映射取代零宽隐藏（2026-08-06 12:45，用户点名「给字符位置做映射、直接渲染 markdown」）

- 新增 `buildMarkdownRender(text)`：记号（`##`/`**`/反引号/`- `/`- [ ]`）从渲染文本**真正删除**，
  维护「源 ↔ 渲染」单调保留区间表，`toSource`/`toRendered` 双向逐字符映射；
  任务框输出 glyph 插入点（渲染坐标，`[x]` 识别 checked）。
- `BlueprintBlock` 富分支改为渲染空间：DOM 只放渲染文本；批注锚点（源坐标）经
  `toRendered` 映射后 `sliceBlockText` 切 `<mark>`；勾选框是 iconify 元素（无文本节点）。
  合法性/越界降级仍按源坐标判，行为不变。
- `BlueprintBlockList.detectSelection`：markdown 预览块的选区偏移经 `toSource` 换算回
  源坐标再上报；末端按「最后一个字符 +1」映射防止卷入相邻被删记号；`quoted_text`
  从**源文本**切（后端 `reanchor` 模糊匹配语料是带记号的源文本）。
- 移除 v2 的 `text-[0px]` 零宽隐藏与伪元素勾选框 hack。
- 测试：逐字符往返映射、夹取语义、glyph、mark 映射、taskbox 元素化；
  vitest 480 passed（blueprint + utils 全量）、`vue-tsc` 退出 0。
- Playwright 真机复验：DOM textContent 无任何记号字符、46 个勾选框图标、观感达成。

## 备注

- list 块按 `\n` split 丢换行字符的存量偏移问题（选区 offset 潜在漂移）本次未动，属既有行为。
- 未提交（用户未要求）。
