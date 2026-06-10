---
title: 什么是 Friday AI
---

# 什么是 Friday AI

Friday AI 是一个开源 AI 开发自动化平台。它把需求、协作系统、代码仓库、Graph RAG、审批、Claude Code 和 PR / MR 串成一条能回看的流水线，让 AI 不只是「回答问题」，而是把已经确认的需求推进到可审查的代码变更。

可以把 Friday AI 理解成研发团队旁边的一张自动化工作台。它不是替 PM、Tech Lead、Reviewer 做所有判断的人，也不是一个「把 Agent 扔进仓库让它自由发挥」的按钮。它更像一位很有耐心的项目助理：先接住需求，翻出相关文档和评论，再去代码仓库里找证据，整理出技术方案，等人确认后，才让 Claude Code 在 Runner 管理的隔离环境里动手。

动手之后，Friday 也不会把结果丢在黑盒里。它会把分支、提交、PR / MR、代码审查、飞书通知、Tool Call、检索证据、模型用量和失败恢复点放回同一条轨迹里。团队看到的不是一句「AI 已完成」，而是一段可以追问、可以审查、可以继续推进的工程过程。

## 它怎么工作

![Friday AI 工作流](/readme/how-it-works.png)

一条典型链路：

<FlowPipeline :steps="['飞书工作项触发', 'Graph RAG 检索证据', 'AI 生成技术方案', '人工确认', 'Claude Code 执行', 'PR / MR 回写']" />

1. 飞书工作项触发工作流，Friday 拉取字段、关系、评论和关联文档；
2. Graph RAG 从已索引仓库里找相关文件、符号、调用关系和跨仓 API 线索；
3. AI 生成技术方案并写回飞书字段或文档；
4. 团队通过字段、卡片或群聊确认；
5. Runner 调度 Claude Code 执行编码、审查和分支整理；
6. 把 PR / MR、执行状态和审计轨迹回写到协作界面。

## 系统组成

| 组件 | 路径 | 技术栈 | 职责 |
| --- | --- | --- | --- |
| Server | `server/` | Django 5.1+ / Python 3.14 | REST + WebSocket API、工作流引擎、代码智能（codegraph / RAG） |
| Web | `web/` | Vue 3 + TypeScript + Tailwind 4 | 控制台、流程编辑器、Web Chat |
| Runner | `runner/` | Go 1.25 | 调度并在 Docker / Kubernetes 中运行任务容器 |
| Task | `task/` | Python 3.14 + claude-agent-sdk | 容器内运行 AI 编码代理 |

详细架构见[架构总览](/internals/)。

## 它能做什么

| 场景 | 实际例子 | Friday 怎么推进 |
| --- | --- | --- |
| 需求从飞书进入开发 | 工作项状态变成「待开发」，评论里补了一个需求文档链接。 | 监听飞书事件，拉取工作项、评论、关系和文档内容，生成技术方案，等确认后再派发编码任务。 |
| 方案要先评审 | Tech Lead 想先看风险、改动范围、测试建议，而不是让 AI 直接改代码。 | 用 Graph RAG 找代码证据，生成方案并回填飞书字段或文档，通过卡片 / 字段等待人工确认。 |
| 跨仓改造 | 前端页面要改接口参数，后端 handler、调用方、类型定义和测试可能分散在不同仓库。 | 通过语义检索、代码图谱和跨仓 API 关系找到上下游，拆出仓库任务矩阵，再分别执行。 |
| 群里持续协作 | 执行中缺字段、缺截图、需要确认分支或要通知结果。 | 飞书机器人在群聊 / 私聊里发送问题卡片、审批卡片、代码审查卡片和结果通知。 |
| 用户自己问代码库 | 「这个支付回调现在走哪几个入口？」「这个组件还有哪些调用方？」 | 在 Friday Web Chat 里选择已索引仓库，模型可以调用检索和代码浏览工具回答。 |
| 用 Agent Skill 增强自己 | 你在 Cursor / Claude Code / Codex 里写代码，希望 AI 助手直接调用 Friday 的代码索引、Graph RAG 和执行工具。 | `npx skills add friday-ai-codes/skills --skill friday-codebase-agent` 一键安装 Skill，配合 `@friday-ai-codes/mcp` 做仓库发现、分析、计划、执行和 MR 创建。 |
| AI 代码审查 | Claude Code 改完之后还需要一轮自动 review 和可读摘要。 | 工作流可以接 `ai_code_review`，把审查结果、分支摘要和 PR / MR 信息回写到飞书。 |

## 飞书深度集成，但不绑定飞书

Friday 当前对飞书的集成已经很深，不只是发通知 —— 项目空间绑定、云文档读写、机器人卡片、回调处理和工作流节点都已打通，详见[飞书集成](/integrations/feishu)。

但 Friday 的底层模型是「协作入口 + 工作流 + 代码智能 + Runner」，所以以后接入其他项目管理、文档、IM 或自动化系统时，不需要推翻这套主流程。

## AI Provider 支持

Friday 内置 Web Chat，也能在工作流、技术方案生成、代码分析和 Agent 工具里使用模型能力。Provider 凭据在 Web 界面里配置，加密存储在数据库中：

| Provider | 用途 |
| --- | --- |
| Anthropic Claude | Claude 模型、Claude Code 执行、方案生成、代码分析和审查 |
| OpenAI Responses API | OpenAI 新版 Responses 能力，适合对话、推理和工具调用 |
| OpenAI Chat Completions | 兼容 Chat Completions 的模型和网关 |
| Google Gemini | Gemini 模型、推理和视觉能力 |
| Ollama | 本地或私有部署模型，适合内网实验和轻量场景 |

Friday 会识别模型输入模态。Web Chat 已支持图片上传（PNG、JPEG、GIF、WebP）；如果你选择的模型支持视觉输入，Friday 可以把图片作为多模态消息的一部分发给模型。

## 下一步

<LinkCards>
  <LinkCard icon="⚡" title="快速开始" desc="15 分钟跑通从部署到第一条工作流" link="/guide/quick-start" />
  <LinkCard icon="🚀" title="部署总览" desc="Docker Compose、Helm / Kubernetes、源码部署选型" link="/deploy/" />
  <LinkCard icon="🏗️" title="架构总览" desc="四组件协作方式与核心数据流" link="/internals/" />
</LinkCards>
