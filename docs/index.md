---
layout: home

hero:
  name: Friday AI
  text: 开源 AI 开发自动化平台
  tagline: 把已经确认的需求自动推进到可审查的代码变更 —— 工作流编排、Graph RAG 代码智能、可审计的 Agent 执行
  image:
    light: /logo-mark.svg
    dark: /logo-mark-dark.svg
    alt: Friday AI
  actions:
    - theme: brand
      text: 快速开始
      link: /guide/quick-start
    - theme: alt
      text: 什么是 Friday AI
      link: /guide/introduction
    - theme: alt
      text: GitHub
      link: https://github.com/friday-ai-codes/friday-ai

features:
  - icon: 🔁
    title: 需求到 PR 全链路
    details: 飞书工作项触发工作流，AI 生成技术方案，人工确认后由 Claude Code 在隔离环境执行编码，自动建分支、提交 PR / MR 并回写结果。
    link: /guide/workflows
    linkText: 工作流指南
  - icon: 🧠
    title: Graph RAG 代码智能
    details: 语义检索 + 代码图谱扩散 + 跨仓 API 关联。进入模型的不是散落片段，而是「需求 + 文件 + 符号 + 调用关系 + 跨仓线索」的组合证据。
    link: /internals/code-intelligence
    linkText: 了解代码智能层
  - icon: 🛰️
    title: 隔离的 Agent 执行
    details: Go Runner 调度 Docker / Kubernetes 任务容器，claude-agent-sdk 在容器内执行编码任务，执行轨迹、Tool Call 与失败恢复点全程可观测。
    link: /internals/runner
    linkText: Runner 架构
  - icon: 🧩
    title: 可编排的工作流引擎
    details: DAG 调度器 + 自动注册的节点体系。AI、控制流、Git、飞书集成节点开箱即用，新节点放进目录即可被发现。
    link: /internals/workflow-engine
    linkText: 引擎实现
  - icon: 🛠️
    title: Agent Skills 与 MCP
    details: 一条命令把 Friday 的代码索引与执行工具接入 Cursor / Claude Code / Codex。19 个 MCP 工具覆盖仓库发现、分析、计划、执行与 MR 创建。
    link: /integrations/mcp
    linkText: MCP Server
  - icon: 🚀
    title: 自托管，开箱即用
    details: Docker Compose 一键起完整栈（Web、Server、Runner、PostgreSQL、Redis、Qdrant），生产环境可用 Helm Chart 部署到 Kubernetes。
    link: /deploy/
    linkText: 部署指南
---
