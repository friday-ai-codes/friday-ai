# Deferred / Out-of-scope items (C2 wave)

- `tests/knowledge/test_triggers.py::TestCodingTriggers::test_coding_chat_pr_created_branch_delivers_once`
  **PRE-EXISTING FAILURE, out of scope for C2.** Fails inside
  `orchestration/coding_graph.py:create_pr_or_skip_node` → `services/git_credentials.py:resolve_git_token_sync`
  with `GitCredential.objects.filter(repository=repo)` where `repo` is a `[]` list
  (`django.core.exceptions.ValidationError: '[]' 不是一个有效的 UUID`). None of the C2-changed files
  touch the coding-PR / git-credential path. Discovered while running the C2 backend test batch
  (611 passed, this 1 failed). Belongs to the coding/git-credentials domain (likely D2 / a separate fix).
