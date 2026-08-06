# Quick 260806-fy2 — AI 澄清提问对话式改造

## Problem

规格门把多道澄清题拼成一条线程正文（`1. …\n2. …`），`options` 虽存了
`{text, options, citations}`，但 Web 侧 `BlueprintThreadComposer` 只认
`{label, value}`，导致：

1. 所有问题挤在一张卡里，没有逐题交互
2. 候选选项不渲染，只能自由文本回答
3. 题面大量裸写 `fp_27`，人无法理解，还得回左侧翻功能点

飞书澄清卡已是「每题选项 + 其他 + 整包提交」；Web 需对齐该体验。

## Decisions (LOCKED)

- **D-01 单线程逐步向导**：保持一条 `ai_clarification` 线程；卡内一题一题出现；
  最后整包提交一条 `answer/` 正文（⛔ 不拆多线程）。
- **D-02 每题交互**：候选单选 + 推荐标记 + 常驻「其他」自定义输入；无选项时仅自由输入。
- **D-03 人话 + 可跳转功能点**：打分 prompt 禁止裸写 `fp_id`；题面带
  `related_feature_points`；UI 以标题 chip 展示并可 `goto-anchor` → `fp-<id>`。
- **D-04 形状分流**：`options` 项含非空 `text`/`question` ⇒ 结构化向导；否则沿用旧
  `{label,value}` 扁平 composer（确认门/人工评论不受影响）。
- **D-05 首条 AI 消息**：结构化题时 UI 不重复渲染编号题面（向导即题面）；`options`
  与消息 body 仍保留供提醒卡 / decision_log / 回灌。

## Discretion

- 提交正文格式：`1. {题}\n→ {答}\n\n2. …`（便于人读与回灌）。
- 旧线程无 `related_feature_points` 时，从题面 regex 抽 `fp_\w+` 并靠页面标题 map 回填。

## Out of scope

- 飞书卡片改版（已基本符合）
- 拆多线程 / 改 answer API 契约
- 现状分析段等相关 chip 的标题回填（可顺带小改，非必须）
