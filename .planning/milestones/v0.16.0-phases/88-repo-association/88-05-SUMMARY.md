# 88-05 Summary — 仓库关联回调状态机 + Phase 89 输出契约（REPO-02）

**Status:** ✅ Done | **Wave:** 5 | **Requirements:** REPO-02 | **Decisions:** D-03 / D-06

## 交付物

### 1. 卡片回调状态机（NEW）`server/feishu/callbacks/repo_association_callback.py`
`@register_card_callback("repo_assoc_")`（前缀唯一，不撞 `board_split_`/`chat_question_` 等），
逐字镜像 `board_split_callback`：同步入口即时返回轻量 ack 卡（3s 内），重活走
`_run_in_thread` + `bind_task_context`（re-bind 触发用户 `callback.user_open_id`）。四动作 FSM：

| action | 后台处理 | 状态迁移 | 是否 approve |
|--------|----------|----------|--------------|
| `repo_assoc_confirm` | `_do_confirm_and_verify_async` | `confirm_repos` + `dispatch_verify(node_execution_id=...)` 派逐仓深验容器；output_data stage=`verifying` + confirmed_repo_ids | ❌ 保持 waiting（容器回调经 `_schedule_workflow_resume` 续驱节点聚合） |
| `repo_assoc_refine` | `_do_refine_async` | `service.refine(extra_instruction=...)` 重 route → round+1 + stage=`clarify` → 重发候选流式卡 | ❌ 保持 waiting |
| `repo_assoc_reconfirm` | `_do_reconfirm_async` | `reopen_candidates` 回置 proposed → stage=`clarify` → 重发候选卡 | ❌ 保持 waiting |
| `repo_assoc_accept_mismatch` | `_do_accept_async` | `accept_mismatch` 置 verified → 发终态卡 → SUSPENDED→RUNNING → `approve_node` | ✅ 恢复（携 verified 仓 + verdict） |

- output_data 权威：confirm 集 = 候选交集（action_value 仅携路由 ID，校验后取交集）。
- 全程 fail-soft：四个后台协程整段 try/except，异常记 `*_failed`（error 经 `redact_secrets_in_text`）不反噬飞书主响应；发卡 best-effort；非 waiting → 幂等 no-op。
- 状态写入一律经 `RepoAssociationService`（INV-6），回调零旁路写表。
- 已在 `server/feishu/urls.py` 注册 import（触发装饰器注册）。

### 2. 服务扩展（EXTEND）`server/initiatives/services/repo_association_service.py`（INV-6 写入收口）
- `accept_mismatch(association)`：rejected/verifying → verified（条件更新幂等）。
- `reopen_candidates(association)`：非 proposed → proposed（回退重确认，幂等）。
- `get_verified_associations(project, work_item=None)`：**Phase 89 输出契约**（只读）。

### 3. 测试（NEW）
- `server/tests/feishu/test_repo_association_callback.py`：同步入口（confirm/refine/reconfirm/accept + 缺 ids/未知动作）、confirm→dispatch 保持 waiting（断言不 approve + node_execution_id 透传）、confirm 非 waiting 幂等、confirm fail-soft、refine 保持 waiting、`test_mismatch_rollback`(reconfirm 回 clarify 重发卡)、accept_mismatch→approve_node。
- `server/tests/initiatives/test_repo_association_output.py`：`get_verified_associations` 输出形态 + 仅 verified 计入 + 空返 [] + 无 task verdict 缺省。

## Phase 89 输出契约 `get_verified_associations`

```python
[
  {
    "repository_id": "<repo uuid str>",   # → PlanSession.decomposition.include_repos 直接消费
    "repo_name": "rv",
    "verdict": {                          # 粗「该仓是否适配 + 摘要 + 证据」（精确 feature→repo 分配留 Phase 89）
      "fit": "fit",                       # fit | mismatch | unknown（无 task 缺省 unknown）
      "confidence": "high",
      "summary": "深验适配",
      "evidence_files": ["a.py"],
      "mismatch_reasons": []
    },
    "matched_node_paths": ["rv/auth"],
    "routed_reason": "命中能力节点 auth",
    "score": 0.91
  }
]
```
仅 `status=verified` 关联计入（proposed/confirmed/verifying/rejected 不计）；按 `-score` 排序；
`repository_id` 对齐 `RepoRouterV2Adapter._resolve_repository_ids` 的 include 优先级；无 verified → `[]`。

## 验证
- `uv run pytest tests/feishu/test_repo_association_callback.py tests/initiatives/test_repo_association_output.py tests/initiatives/test_repo_association_inv6_guard.py -q` → 18 passed。
- `uv run pytest tests/initiatives tests/feishu -q` → 385 passed。
- ruff（5 文件）All checks passed；mypy（callback + service）Success no issues。
- `@register_card_callback("repo_assoc_")` 前缀唯一（grep 确认）。

## 观测
- `repo_association_card_action`(caller, action/execution_id/round)、`repo_association_confirm`/`_refine`/`_reconfirm`/`_accept_mismatch`(caller, +duration_ms)，失败 status=failed（error 脱敏）；`repo_association_output_collected`(caller)。归因 `user_id=callback.user_open_id`（bind_task_context re-bind），系统行为 `system`。
