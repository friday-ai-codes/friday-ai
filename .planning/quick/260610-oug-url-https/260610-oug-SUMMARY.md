---
phase: quick/260610-oug-url-https
plan: 01
subsystem: web-frontend
tags: [i18n, copy-fix, zod, validation-messages]
dependency_graph:
  requires: []
  provides:

    - 仓库弹窗 Git URL 帮助文案与后端仅支持 HTTPS 的行为一致
    - 工作流 zod 校验消息全量中文（数字消息含界值）
    - API 兜底错误文案与 Embedding 健康检查提示中文化
  affects: []
tech_stack:
  added: []
  patterns:

    - zod v4 字符串简写 message（`z.number().min(1, '不能小于 1')`、`z.enum([...], '请选择有效的选项')`）

key_files:
  created: []
  modified:

    - web/src/components/repository/CreateRepositoryModal.vue
    - web/src/components/repository/EditRepositoryModal.vue
    - web/src/types/workflow/schemas.ts
    - web/src/types/workflow/node-definitions/categories/action.ts
    - web/src/types/workflow/node-definitions/categories/trigger.ts
    - web/src/types/workflow/node-definitions/categories/integration.ts
    - web/src/types/workflow/node-definitions/categories/control.ts
    - web/src/components/settings/VectorIndexSettings.vue
    - web/src/api/client.ts
    - web/src/api/prompts.ts

decisions:

  - 不实现 SSH，仅修正文案为「仅支持 HTTPS 格式（认证基于 Access Token，暂不支持 SSH）」（用户已决策）
  - 校验消息格式统一：min →「不能小于 {界值}」，max →「不能大于 {界值}」，enum →「请选择有效的选项」

metrics:
  duration: ~4 min
  completed: 2026-06-10
  tasks: 3
  files: 10
audit_acknowledged:
  milestone: v0.25.0
  at: 2026-08-31
  status: unknown
---

# Quick Task 260610-oug: 仓库 URL 文案修正 + 英文提示汉化 Summary

仓库弹窗 Git URL 帮助文案改为「仅支持 HTTPS」并说明原因，工作流 zod 校验消息（uuid/min/max/enum）与硬编码英文错误文案全量汉化，校验逻辑零变更。

## Tasks Completed

| Task | Name | Commit | Files |
|------|------|--------|-------|
| 1 | 修复仓库弹窗 Git URL 帮助文案为仅支持 HTTPS | 351d9948 | CreateRepositoryModal.vue, EditRepositoryModal.vue |
| 2 | 为工作流 zod schema 补全中文校验消息 | 3ca2b3ff | schemas.ts + categories/{action,trigger,integration,control}.ts |
| 3 | 汉化硬编码英文错误文案并跑全量前端测试 | c4c60c4f | VectorIndexSettings.vue, client.ts, prompts.ts |

## Changes Detail

**Task 1：** 两个弹窗的帮助文案由「支持 HTTPS 或 SSH 格式」改为「仅支持 HTTPS 格式（认证基于 Access Token，暂不支持 SSH）」，与后端仅接受 http(s) URL 的行为及既有校验错误文案「当前仅支持 HTTPS 仓库 URL」一致。

**Task 2：** zod v4 字符串简写补中文 message：

- schemas.ts：4 处 `provider_credential_id` uuid →「凭证 ID 格式无效」；temperature/max_tokens/max_thinking_tokens(×2)/max_budget_usd(×2)/top_k/score_threshold/max_iterations(×2)/timeout_seconds/polling_interval 全部 min/max 带界值消息；output_format/work_item_type(×2)/filter_work_item_type/identifier_type/operator/logic/timeout_action 等 enum 补「请选择有效的选项」
- action.ts：timeout_seconds (1–300)
- integration.ts：timeout (1–300)、message_type/method enum
- control.ts：delay_seconds (1–86400)、wait_count/timeout/timeout_hours/max_concurrency、operator/wait_mode/merge_strategy/execution_mode/on_iteration_error enum
- trigger.ts：method enum
- 全部 enum 均成功补消息，无类型问题跳过项；界值/default/int()/nullable 零变更

**Task 3：** `client.ts` 5 处 + `prompts.ts` 1 处 `'Request failed'` →「请求失败」；`VectorIndexSettings.vue` 健康检查缺 URL 提示 →「请输入 Embedding API URL」。

## Verification

- `grep` 确认：`web/src/components/repository/` 无「支持 HTTPS 或 SSH」残留；`src/` 下无 `Request failed` / `Embedding API URL is required` 残留
- workflow 范围测试：6 文件 50 测试全部通过
- 全量前端测试：`pnpm vitest run` — 134 文件通过 + 1 跳过，932 测试通过 + 1 跳过（既有跳过），无回归
- lint：编辑文件无新增错误（VectorIndexSettings.vue 第 484 行 2 个 Tailwind class 写法警告为既有问题，与本次改动无关）

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] 计划中 verify 命令的 `--reporter=basic` 不可用**

- **Found during:** Task 2 verify
- **Issue:** vitest 4 已移除 `basic` reporter，`pnpm vitest run --reporter=basic` 报 `ERR_LOAD_URL` 启动失败
- **Fix:** 改用默认 reporter 运行同一测试范围，验证目标不变
- **Files modified:** 无（仅验证命令调整）
- **Commit:** N/A

## Known Stubs

None — 纯文案/校验消息修改，无数据流 stub。

## Threat Flags

无新增安全面：仅添加 zod message 参数与文案字符串，未改变校验逻辑、网络端点或信任边界（对应威胁登记 T-quick-01 mitigation 已由测试验证）。

## Self-Check: PASSED

- 10 个文件均存在且已修改 ✓
- 提交 351d9948 / 3ca2b3ff / c4c60c4f 均存在于 git log ✓
- 工作区无关改动未被卷入提交（逐文件 `git add`）✓
