---
status: passed
phase: 87
verified: 2026-06-26
must_haves_verified: 2
must_haves_total: 2
---

# Phase 87 Verification — 看板拆分节点 + 群 + 流式卡片

## Status: PASSED

2/2 需求（BOARD-01/02）实现，4 plan（3 wave）全绿。Phase gate `tests/initiatives + tests/feishu` = **338 passed**，零回归（本期触面）。

## Requirement Coverage

| Req | 实现 | 提交 |
|-----|------|------|
| BOARD-01 | feature list 多源输入（文件/飞书链接回拉/粘贴）+ 结构化抽取（模块→功能点→验收项）+ 分块/token 降级；FeishuClient create_work_item + relation_type=1 关联项目跟踪 + 父子探测/降级；BoardSplitService 每 feature 一子看板 + ProjectWorkItemLink(INV-6)；工作流节点(自动注册) + AI 工具共用单一 service | 23b3ea31, b22d502, 3897c97b |
| BOARD-02 | 复用项目群/无则建群 + bot 入群（ProjectService.resolve_or_create_group + feishu_chat_id，migration 0009）+ CardKit 流式拆分卡片（开始创建/输入框+发送）+ 回调多轮重拆 | 58e4a86 |

## 关键决策落地确认

- 多源输入 + 82KB demo 分块降级（绝不整篇塞 LLM）✓
- 每 feature 一子看板 work_item（名=feature名/描述=feature原文）+ relation_type=1 ✓
- 父子关系探测/降级（缺则建看板不挂父子 + 提示配置中心，绝不阻断）✓
- 复用项目群、无则建新群 + bot 入群 ✓
- 工作流节点（自动注册）+ AI 会话工具共用同一 BoardSplitService（不造两套）✓
- 新增 LLM（board_split）赋 call_source（枚举 24→25，基线 bump）✓
- 写入收口 ProjectService（INV-6）；脱敏；fail-soft ✓

## Deferred / Live-Verification（[ASSUMED]，不阻断 — 见 87-UAT.md）

- 飞书写 API（work_item/create、relation 写、relation_type=2 父子、关系类型配置中心预配错误码）真机验证 — Phase 78 仅验证读，本期 respx mock + seam 覆盖契约。
- CardKit schema 2.0 按钮/输入框/回调 payload 结构真机抓包验证。

## 既有 tech_debt（非本期引入）

- `tests/workflows/test_execution_concurrency.py` 2 例预存在失败（sqlite `select_for_update` 行锁；独立运行亦失败，本期未触碰调度器）。归入既有 tech_debt，不阻断本 phase。
