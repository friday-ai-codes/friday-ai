---
audit_acknowledged:
  milestone: v0.25.0
  at: 2026-08-31
  status: unknown
---

# Summary — ricelove-scheme 项目描述重写

## Done

- 用系统 `mimo` 凭证（`mimo-v2.5-pro`）为 **284** 个 `ricelove-scheme:*` 项目重写描述，替换「从能力簇「X」拆出的具体方案/项目」占位文案
- 全量成功：ok=284 / failed=0，DB 中占位描述剩余 0
- 生成材料：feature_list 模块/功能点清单（271 个项目有）+ 能力簇背景描述 + 关联文档标题
- 新描述 100～250 字纯文本，末尾保留「源文档：URL」行追溯
- 脚本可安全重跑（只匹配仍以「从能力簇」开头的描述）；报告在 `/tmp/ricelove-regen-desc-report.json`

## Notes

- MiMo 是推理模型，`max_output_tokens` 低于 4096 时思考会耗尽预算导致返回空文本
- LLM 调用走 `ProviderConfigService.aresolve_or_error` + `build_chat_model`，`call_source=AUX_CRAWL`
