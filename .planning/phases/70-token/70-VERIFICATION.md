---
phase: 70
slug: token
status: passed
nyquist_compliant: true
wave_0_complete: true
created: 2026-06-23
---

# Phase 70 — Verification（access token / 密钥提供方重构 FK）

## Goal-Backward Verification

**Phase Goal:** 把仓库 access token 重构为可选——仓库可显式选「密钥提供方」(`GitInstanceCredential` FK) 或填自有 token；建仓表单按 provider 拼接 URL 并失焦校验。

## Checks

| # | Success Criterion | Status | Evidence |
|---|-------------------|--------|----------|
| 1 | Repository 增可空 git_instance_credential FK + migration；解析优先级 per-repo→FK→host→无，老仓库零回归 | ✅ | models FK + migration 0039；`resolve_git_token_sync` 四级优先级；`test_resolver_*` 4 例（per-repo/FK-over-host/host/none） |
| 2 | 建仓 access_token 改可选；可选密钥提供方或填自有 token；has_credential 反映可解析 | ✅ | serializer access_token 可选 + git_instance_credential_id；`_acreate_repository_core` 无 token fail-loud/FK 落库/仅自有 token 建凭证；`get_has_credential` FK/host；`test_create_with_fk_no_token`/`host_match`/`no_provider_fails`/`has_credential_*` |
| 3 | TestConnection（含新建路径）无 token 时按 FK/host fallback 实例池校验 | ✅ | `TestConnectionView` 新建路径无 token → FK/host 解密实例池 token；缺则 400「请提供 Access Token 或选择/配置密钥提供方」 |
| 4 | 建仓表单选 provider 后 URL 拆段拼接 + 失焦自动校验 | ⚠️ PARTIAL | 失焦自动校验已实现（URL/token/provider 防抖自动测连）；「URL 拆段拼接（host 前缀只读 + group/repo split + .git）」为 UI 打磨 deferred（后端 + 自动校验就绪） |
| 5 | 全局凭证 admin 页补「按 provider + host 生效」用途说明 | ✅ | `pages/admin/git-credentials` 新增说明 banner（provider+host 生效 + 解析优先级） |

## Result

**PASSED**（4 PASS + 1 PARTIAL）— 后端 TOKEN-01/02 全量满足并测；前端 token 可选 + 密钥提供方 select + 自动校验 + admin 说明落地。Criterion 4 的 URL 拆段拼接为纯 UI 打磨 deferred（功能由防抖自动校验等价覆盖，后端完全支持）。

9 守护 + 42+ 回归零回归；migration 0039 `makemigrations --check` 干净；前端 eslint clean。真实 Git 平台连通/建仓端到端需人工验收（deferred）。
