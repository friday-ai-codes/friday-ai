# friday-refactoring 工具顺序小抄

```text
get_repository →（消歧）符号
        ↓
rename_preview   ← applied 恒 false，只读清单
        ↓
代理本地编辑（Edit / ApplyPatch 等）
        ↓ 可选
friday-impact（impact / detect_changes / list_processes）
```

| 字段 | 含义 |
| --- | --- |
| `applied` | 恒 `false`；无服务端写仓 |
| `confidence` | `graph` \| `text_search` |
| `coverage_limitations` | 动态引用覆盖声明 |

Preview 失败 → 记录原因 → 本地 Grep 继续，不阻断交付。
