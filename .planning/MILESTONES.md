# Milestones

## v0.1.0 首启初始化向导 (Shipped: 2026-06-09)

**Phases completed:** 5 phases, 9 plans

**Delivered:** 用「首次访问引导用户自设账号」替代启动期自动建管理员，并在向导内一次配好管理员、LLM 供应商、安全校验与可选的飞书/RAG 集成。

**Key accomplishments:**

- 首启门禁：无任何 superuser 时首次访问自动进入向导，已初始化实例 fail-closed 拒绝（防重入/防接管）
- 管理员自设：向导内自定义用户名+密码（强度校验），提交即建 superuser 并自动登录直达首页
- 供应商一键预设：DeepSeek V4 Pro / MiMo V2.5 Pro / Kimi 2.6 / Anthropic 官方 / 自定义端点，Fernet 加密落库 + 健康校验 + 绑定 Claude Code 模型映射
- 安全与可选集成：SECRET_KEY/FRIDAY_ENCRYPTION_KEY 风险校验（非阻塞）+ 可一键跳过的飞书、向量检索（Qdrant/Embedding）配置步骤
- 向后兼容：`entrypoint.sh` 默认不再自动建号，`init_superuser`/`reset_superuser_password` 保留为运维兜底，老部署升级不回退

**Known deferred items at close:** 2 — Phase 01 / 02 人工验收（UAT）签字未完成（功能已实现，详见 STATE.md Deferred Items）

---
