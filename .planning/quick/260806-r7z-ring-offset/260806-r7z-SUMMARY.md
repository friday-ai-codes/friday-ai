---
quick_id: 260806-r7z
status: complete
date: 2026-08-06
---

# Summary: 段落跳转高亮环加呼吸边距

## 改动

`web/src/pages/knowledge/blueprints/[id].vue` 一处常量：

- `HIGHLIGHT_CLASS` 由 `'rounded-xl ring-2 ring-primary/60'` 改为
  `'rounded-xl ring-2 ring-primary/60 ring-offset-8 ring-offset-background'`。

段落跳转 / gate 深链 / 质量报告卡的 2 秒命中高亮环，原先直接画在段容器的内容
边界上（段容器零 padding），标题与卡片紧贴高亮框。加 `ring-offset-8` 后环外扩
8px，offset 区域用背景色填充，内容与框之间有了呼吸边距。四处消费点
（`sectionClass` 的十个段容器、`#gate` 锚点、gate 面板包裹层、`blueprint-quality`
卡）共用该常量，自动同步。

## 验证

- `pnpm vitest run src/pages/knowledge/__tests__/blueprintViewer.spec.ts`：30 通过。
- grep 确认无测试断言旧类名串；`ring-offset-*` 在代码库已有既成用法
  （`profile.vue` / ui 组件），Tailwind 扫描字面量直接命中。
