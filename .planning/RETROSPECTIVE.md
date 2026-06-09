# Retrospective

## Milestone: v0.1.0 — 首启初始化向导

**Shipped:** 2026-06-09
**Phases:** 5 | **Plans:** 9

### What Was Built
用「首次访问引导用户自设账号」替代启动期自动建管理员：首启门禁（fail-closed 防重入）、管理员自设+自动登录、Anthropic 兼容供应商一键预设（Fernet 加密 + 健康校验 + 绑 Claude Code）、安全密钥校验、可选飞书/RAG 步骤、entrypoint 去自动建号且向后兼容。

### What Worked
- 严格复用既有 `ProviderConfigService` / `ProviderCredential` / `SystemSetting` / Fernet 加密路径，未重写既有系统，集成风险低。
- fail-closed 安全门禁（仅无 superuser 可用）从 Phase 1 就锁定为独立权限类，后续阶段直接复用。
- 一键模型预设以「anthropic 类型 + base_url 覆盖」统一接入第三方模型，前端常量化，扩展简单。

### What Was Inefficient
- Phase 01/02 的人工验收（UAT）签字未闭环，里程碑关闭时作为 deferred 项带走。
- SUMMARY.md 的 one-liner 格式与 SDK summary-extract 不匹配，归档成果摘要需手动补全。

### Patterns Established
- 敏感配置一律走加密落库（`is_encrypted=True` + `SettingKeys.*`），不走通用明文 PUT /settings/。
- 薄编排端点（IsSuperUser）承担「校验→加密→落库→绑定」的组合写操作。

### Key Lessons
- 向导类需求要尽早把「安全门禁 + 向后兼容」作为一等公民，避免收尾阶段返工。
- 人工验收门应在每个 Phase 完成时即时签字，避免堆积到里程碑关闭。

## Cross-Milestone Trends

| Milestone | Phases | Plans | Shipped |
|-----------|--------|-------|---------|
| v0.1.0 首启初始化向导 | 5 | 9 | 2026-06-09 |
