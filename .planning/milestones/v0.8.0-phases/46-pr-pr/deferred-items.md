# Phase 46 — Deferred / Out-of-Scope Items

## 46-02 执行期发现（out-of-scope，未修复）
- status: acknowledged


- **`server/tests/test_batch_pr.py` 5 例 PRE-EXISTING 失败（stale）**
  - 现象：`AttributeError: module 'workflows.nodes.git.pr' has no attribute 'GitCredential'`
    （及 `decrypt_value`）。失败用例：`test_batch_create_pr_all_success` /
    `_partial_failure` / `_cross_reference_disabled` / `_backward_compat` / `_no_credential`。
  - 根因：Phase 26（REPO-01）已把 `pr.py` 的取 token 路径统一到 `aresolve_git_token`，
    移除了 `GitCredential` / `decrypt_value` 的模块级符号；但 `test_batch_pr.py` 仍 `patch`
    `workflows.nodes.git.pr.GitCredential` / `decrypt_value`，故 patch target 不存在即 fail。
  - 证据：将本 plan 的 `coding.py` 改动 stash 后这 5 例仍失败 → 与 46-02 改动无关（46-02 未
    触 `pr.py`，D-09 明确 `CreatePRNode` 保持原样不改）。
  - 处置：超出 46-02 scope boundary，不在本 plan 修复。建议后续 quick task 把
    `test_batch_pr.py` 的 mock 范式迁移到 `aresolve_git_token`（对齐 `test_coding_pr_target_branch.py`）。
