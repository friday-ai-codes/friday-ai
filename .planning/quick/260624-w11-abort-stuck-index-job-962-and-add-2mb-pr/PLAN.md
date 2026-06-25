---
status: completed
created_at: 2026-06-24T15:03:38Z
---

# Abort stuck index job 962 and add 2MB pre-parse large-file exclusion

- Abort the stuck production durable_index job and restart worker if needed.
- Add pre-parse large-file protection for index parsing at 2MB.
- Persist automatically skipped large-file paths into repository exclusion rules.
