"""蓝图 AI 正文的 markdown-lite 写作约定与中文语言质量规则。

该约定只约束 ``paragraph`` Block 的 ``text``；结构化表格、伪代码等内容仍使用各自的
Block 类型，避免把前端不支持的 Markdown 语法混入正文。

``HUMAN_WRITING_SUMMARY_GUIDE`` 取自开源 skill「活人感写作」的蒸馏版五条规则
（https://github.com/KKKKhazix/human-writing ，dist/human-writing-lite.md，v1.1.0，
MIT License），按技术方案摘要场景适配：编排系统的服务端 LLM 调用没有 Agent Skill
加载机制，skill 以 prompt 资产形态进入调用（与 ``MARKDOWN_LITE_WRITING_GUIDE`` 同款
落位）；容器侧 agent 走 claude-agent-sdk 的 ``setting_sources=["project"]`` 原生加载，
不经此处。
"""

from __future__ import annotations

__all__ = [
    "HUMAN_WRITING_SUMMARY_GUIDE",
    "LEADER_GOAL_DISCIPLINE",
    "MARKDOWN_LITE_WRITING_GUIDE",
]


# 取自开源 skill「leader」（https://github.com/KKKKhazix/khazix-skills/tree/main/leader ，
# MIT License）的「目标七问」心法蒸馏，按规格门场景适配：规格门的职责正是「把模糊需求
# 变成可开工的目标」，这四类缺口是长程自动化里代价最高的歧义（跑偏了没人纠正）。
LEADER_GOAL_DISCIPLINE = """## 目标质量心法（评估歧义与设计澄清问题时优先检查的四类缺口）

1. 完成态必须机器可判：「做完某功能」不是完成态，「哪个页面出现什么行为、哪条数据变成什么值」才是。验收写不出可观察行为的功能点，应产生一个澄清问题。
2. 「什么不能做」与「做什么」同等重要：范围边界缺「明确不做」清单时，实现者会自选最省力的解法。检查需求是否点名了禁区——不改哪些系统、不覆盖哪些端、不引入哪些新依赖；缺就问。
3. 反作弊：先想象最省力的偷懒实现（跳过鉴权直接展示、写死映射不做配置、只做正常路径不管中断恢复），需求文本挡不住这种实现时，就地提问把它挡住。
4. 取舍要有顺序：多个目标冲突时（正确、完整、快），需求没给优先级就该问；沉默替提出者拍板是越权，把假设摆到明面才是尽职。"""


HUMAN_WRITING_SUMMARY_GUIDE = """## 中文语言质量规则（优先级高于你的默认写作习惯）

1. 先清点材料再动笔：摘要里的每一句都要能指出它来自输入材料的哪一条（需求目标、仓库职责、实现项）。材料里没有的判断不要写，不要用抽象道理凑字数。
2. 判断从正面下，禁止翻案腔：不写「不是A，而是B」「你以为A，其实B」「表面上A，实际上B」及一切同类变形；想下判断就直接说出判断，把依据放在旁边。禁止三项以上的整齐排比，禁止结尾升华。
3. 句子先交出主干：先说谁做了什么，再补条件和原因。一句话堆四个「的」就重写，「进行了优化」写成「改顺了」。删掉一半连词，中文小句靠语序自己会接。
4. 长短句要有高低差：十个字的句子挨着三四十个字的句子；普通的地方用普通句子结束，不要每段都用短判断收尾；该重复的词就重复，不要换着花样找同义词。
5. 成稿不用破折号，冒号只用来引出列举；不用「说白了」「值得注意的是」「先说结论」，不用赋能、抓手、闭环、底层逻辑这类黑话。"""


MARKDOWN_LITE_WRITING_GUIDE = """## paragraph Block 正文写作约定（必须遵守）

以下规则适用于本次输出中所有面向读者的 `paragraph` Block 正文：

1. 凡是代码标识符、文件路径、函数名、变量名、组件名、配置键、包名、URL 参数名，一律用单个反引号包裹。
   - 正例：在 `SpecialCard.vue` 中调用 `browserJump`，跳转到 `apps/learn-rapid-score-boost`。
   - 反例：在 SpecialCard.vue 中调用 browserJump，跳转到 apps/learn-rapid-score-boost。
2. 多个并列要点必须用 `- ` 无序列表分条，不要写成用逗号、顿号或分号串联的一整段长句；存在先后顺序的步骤必须用 `1. `、`2. ` 有序列表。
3. 需要小标题时只用 `####`，不要用 `#`、`##` 或 `###`。
4. 关键约束或结论可用 `**加粗**` 标出，但只标真正需要读者注意的内容，不要整段加粗。
5. 禁止在 paragraph 中使用 markdown-lite 不支持的语法：Markdown 表格（如 `|---|`）、围栏代码块（三个反引号）、链接（如 `[text](url)`）、引用（`> `）和图片。多行代码必须输出为独立的 `pseudocode` Block，不要塞进 paragraph。

改造前：
按 monorepo 既有子应用形态（package.json 的 buildName/vite --configLoader runner 脚本、src/{pages,components,composables,services,stores,helpers,types} 结构、文件路由 [...all].vue + index.vue、typed-router）创建极速提分营独立子应用，接入 @util/global 请求封装、onion-ui/onion-utils、vue-router 文件路由与埋点公共参数初始化。

将 learn-textbook-sync 的 SpecialCard.vue 从「培优课（即将上线）」占位改造成真实培优卡片区：渲染「专项突破」等既有入口并在其右侧追加「极速提分营」入口，样式与同模块其他培优课入口一致；同时 ContentArea.vue 模板中按 showSpecialCard（SPECIAL_CARD featureCode）真正渲染 SpecialCard（当前模板未渲染），点击入口经 browserJump 跳转 apps/learn-rapid-score-boost 题型图谱页。

改造后：
#### 创建极速提分营子应用
- 按 monorepo 既有子应用形态创建独立应用：
  - 在 `package.json` 中配置 `buildName` 与 `vite --configLoader runner` 脚本。
  - 建立 `src/{pages,components,composables,services,stores,helpers,types}` 目录结构。
  - 使用 `[...all].vue`、`index.vue` 与 `typed-router` 接入文件路由。
- 接入 `@util/global` 请求封装、`onion-ui`、`onion-utils` 与 `vue-router`。
- 初始化埋点公共参数。

#### 接入极速提分营入口
1. 将 `learn-textbook-sync` 的 `SpecialCard.vue` 从「培优课（即将上线）」占位改造成真实培优卡片区。
2. 保留「专项突破」等既有入口，并在右侧追加「极速提分营」入口；**样式必须与同模块其他培优课入口一致**。
3. 在 `ContentArea.vue` 中根据 `showSpecialCard`（`SPECIAL_CARD` featureCode）渲染 `SpecialCard`，补齐当前模板未渲染的问题。
4. 点击入口时调用 `browserJump`，跳转到 `apps/learn-rapid-score-boost` 题型图谱页。
"""
