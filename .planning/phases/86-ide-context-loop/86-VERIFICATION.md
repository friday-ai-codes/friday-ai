---
status: passed
phase: 86
verified: 2026-06-26
must_haves_verified: 4
must_haves_total: 4
accepted_deviation: true
---

# Phase 86 Verification — IDE 上下文闭环（hooks）

## Status: PASSED (含用户授权 accepted deviation)

4/4 需求（HOOK-01~04）实现，5 plan（3 wave）全绿。Phase gate `tests/initiatives + tests/mcp_tools + tests/chat` = **494 passed**，零回归。

## Requirement Coverage

| Req | 实现 | 提交 |
|-----|------|------|
| HOOK-01 读路径 | 三家 always-on rule + CC UserPromptSubmit 注入 + ide-hook-assets(kind=read) 下发 + 复用 lookup_project_by_branch MCP（写 RetrievalTrace）；Cursor 不押注入 hook | a12c676 |
| HOOK-02 写路径 | stop hook 默认开启 + 静默 **active 直写**（report_project_knowledge active）+ 三家 stop hook 资产(kind=write) | f922700b, b032e39d |
| HOOK-03 STATE 回写 | report_project_state MCP → ProjectStateApi 结构化直写（method/path/params/status，幂等 upsert，审计可回滚，逐条 fail-soft） | c6226957, b032e39d |
| HOOK-04 runner+session | SessionStore→Redis 跨容器 resume + DB fallback + cwd 一致校验 + dispatch 带 pack_project_context（写 RetrievalTrace） | 2fa52b4a |

## ⚠️ Accepted Deviation（用户 2026-06-26 明确授权）

stop hook 写路径采用 **真·全自动 active 直写（无 draft 人工确认）**，**覆盖**：
- REQUIREMENTS HOOK-02「MEMORY/RESEARCH 落 draft 人工确认」
- Out-of-Scope「记忆全自动写入（无人确认）本期不做」

**四道兜底齐备且各有守护测试（绝不绕过）**：
1. 质量门槛过滤（低质/空内容不写）✓
2. 脱敏不可绕过（redact_secrets_in_text / redact_for_ledger）✓
3. 归因（resolve_feishu_user，unmapped=system）+ 非成员/无 PAT/未绑项目静默跳过不阻断编码 ✓
4. 审计可回滚（每次自动写入 AuditEvent + supersede 可撤销）✓

draft 默认路径（CURSOR-03，v0.15.0）逐字不回退；前端/会话内记忆仍走 draft 确认。

## 关键决策落地确认

- 读路径：MCP + always-on rule 三家通；CC UserPromptSubmit 注入，Cursor beforeSubmitPrompt 不注入（架构层接受的不对称）✓
- 新增 LLM（ide_hook_distill）赋 call_source（枚举 23→24，基线测试 bump）✓
- 新增召回（MCP 注入/dispatch 上下文）写 RetrievalTrace ✓
- SessionStore→Redis + DB fallback + cwd 一致（漂移→新 session 重灌）✓
- 写入收口 service（INV-6）；复用 report_project_knowledge/cursor_rules/MemoryService/SessionStore，未重造 ✓

## Deferred / Live-Verification（不阻断）

- 真·跨容器/冷启动 resume 命中 → 运行时联验（逻辑+单测已覆盖，同 v0.12 真机遗留类）。
- Codex 原生 stop hook 自动注入（能力弱，本期仅手动/CI 脚本）。
- STATE API 清单从 diff 自动提取未做（脚本以 FRIDAY_STATE_APIS_FILE 显式提供为准）。
- WORKSPACE_CWD 容器约定常量（未改 task/；若容器用 tempdir 需回调回传真实 cwd）。
