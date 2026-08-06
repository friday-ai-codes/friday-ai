---
phase: quick-260806-gfk
plan: 01
type: execute
wave: 1
depends_on: []
files_modified:
  - web/src/utils/blueprintMarkdownLite.ts
  - web/src/utils/__tests__/blueprintMarkdownLite.test.ts
  - web/src/components/blueprint/BlueprintBlock.vue
  - web/src/components/blueprint/sections/RequirementSpecSection.vue
  - web/src/components/blueprint/__tests__/BlueprintBlock.spec.ts
autonomous: true
requirements: [QUICK-260806-GFK]

must_haves:
  truths:
    - "需求规格 goal 里的 feature-list markdown（## 标题 / - [ ] 验收 / **加粗**）以结构化视觉渲染：标题分级加粗、标记字符淡化、任务/列表行缩进"
    - "渲染后块内文本节点扁平拼接与 blockText 逐字相等（批注 offset 坐标系与选区评论零回归）"
    - "普通短段落（无 markdown 记号）渲染路径不变（<p> 分支）"
    - "目标/背景块列表包进 .card 容器，正文不再裸浮在页面渐变背景上"
  artifacts:
    - path: "web/src/utils/blueprintMarkdownLite.ts"
      provides: "isMarkdownishText / parseMarkdownLite（行分级 + 行内样式区间，全部绝对 offset）"
    - path: "web/src/components/blueprint/BlueprintBlock.vue"
      provides: "paragraph 块 markdown-lite 富渲染分支（原子切分与批注 <mark> 相交）"
  key_links:
    - from: "BlueprintBlock paragraph 分支"
      to: "blueprintMarkdownLite"
      via: "isMarkdownishText(text) 分流"
      pattern: "isMarkdownishText"
---

<objective>
需求规格·目标区把整段 feature-list markdown 当纯文本渲染（`## 模块 1`、`- [ ] **当**…` 裸露），
一面文字墙且直接浮在页面渐变背景上。改为 markdown-lite 富渲染 + 卡片容器。

**硬约束（P-13 同源）**：块正文是批注锚点坐标系（`rangeOffsets` 按块内全部文本节点扁平拼接），
⛔ 不得删除/隐藏任何字符（含 `##`、`**`、`- [ ]`、缩进空格与 `\n`）；只允许包元素与着色。
标记字符淡化（`text-muted-foreground`），加粗内容真加粗——Typora 源码高亮式而非渲染式。
</objective>

<context>
@web/src/components/blueprint/BlueprintBlock.vue
@web/src/utils/blueprintAnnotations.ts（rangeOffsets/collectTextNodes/sliceBlockText）
@web/src/components/blueprint/sections/RequirementSpecSection.vue
@.cursor 设计规范：sub2api clean card（白卡 + border-border/50 + 主色单一强调）

已核实：
- 选区 offset = TreeWalker 收集块内全部文本节点长度累加 ⇒ 文本节点串必须与 blockText 相等。
- 每行末尾 `\n` 必须保留在文本节点里；行渲染为块级 div 时末尾 `\n` 作为块末行分隔被浏览器丢弃，视觉无副作用。
- 现有 list/pseudocode 分支按 `\n` split 丢了换行字符（存量已然），本次 paragraph 富分支不复制该缺陷。
- 测试 1a 用纯数字文本 ⇒ 不触发富分支，保持 `<p>`。
</context>

<tasks>

<task type="auto">
  <name>Task 1: blueprintMarkdownLite 工具 + 单测</name>
  <action>
新建 `web/src/utils/blueprintMarkdownLite.ts`：
- `isMarkdownishText(text)`：多行且含（行首 `#{1,6} ` 或 ≥2 行 `- `/`- [ ]` 或 `**…**`）。
- `parseMarkdownLite(text)` → `{ lines, styles }`：
  - lines：`{ start, end(含尾 \n), kind: h1|h2|h3|h4|task|bullet|ordered|blank|plain, depth }`
  - styles：非重叠 `{ start, end, style: marker|bold|code }`（行首记号、`**`、行内 `` ` `` 对）
- 不变式：lines 覆盖全文无缝隙；styles 均落在行内且互不重叠。
单测断言：行分类、depth、style 区间、拼接不变式、空文本/无记号文本。
  </action>
</task>

<task type="auto">
  <name>Task 2: BlueprintBlock 富渲染分支 + RequirementSpec 卡片容器 + 组件测试</name>
  <action>
- BlueprintBlock：paragraph 且 isMarkdownishText ⇒ 富分支：
  切点 = 批注 segment 边界 ∪ 行边界 ∪ style 边界 → 原子；原子按行分组渲染
  `<div :class="lineClass">`，原子 mark 属性照旧（annotation cls + style cls 叠加），
  非 mark 用 `<span :class="styleCls">`。行类：h1/h2 `text-[15px] font-semibold mt-4 first:mt-0`、
  h3/h4 `text-sm font-semibold mt-3 first:mt-0`、task/bullet/ordered 按 depth padding、blank `h-2`。
  标记 `text-muted-foreground/50`、bold `font-semibold`、code `font-mono text-[12px] bg-muted/60 rounded px-0.5`。
- RequirementSpecSection：goal/background 的 BlockList 外包 `.card px-4 py-3.5`。
- 组件测试：富分支容器 textContent === 源文本（坐标系不变式）；标题行类命中；
  纯数字段落仍走 `<p>`；富分支上挂合法 anchor ⇒ `<mark>` 正常出现。
  </action>
</task>

</tasks>

<verification>
- vitest：blueprintMarkdownLite + BlueprintBlock 全绿
- vue-tsc 无新错
- 手动：blueprints/bbedc1f2 页需求规格区标题分级、验收行缩进、划线评论照常
</verification>
