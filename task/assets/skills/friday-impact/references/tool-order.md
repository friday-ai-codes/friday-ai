# friday-impact 工具顺序小抄

```text
get_repository / route_repositories
        ↓ 读 staleness
detect_changes  或  impact
        ↓ 并行可选
list_processes / get_process
        ↓
解读信封 affected_processes → 报告 / MR 影响面
```

| 步骤 | 工具 | 目的 |
| --- | --- | --- |
| 0 | `get_repository` | 元数据、默认分支、索引是否就绪 |
| 1 | `detect_changes` | 工作区/分支改动的批量波及 |
| 1' | `impact` | 已知符号的影响面 |
| 2 | `list_processes` | 仓内执行流列表 / 按符号过滤 |
| 2' | `get_process` | 单条 Process 步骤细节 |

`affected_processes` 由服务端在 `detect_changes` / `impact` 信封内回填；客户端只消费，不本地重算。
