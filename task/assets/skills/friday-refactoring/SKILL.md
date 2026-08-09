---
name: friday-refactoring
description: "当用户要做 refactoring / 符号改名 / 重命名影响清单时使用：先 rename_preview 拿只读双源编辑清单（图引用 + 文本兜底），再自行编辑；不申请 apply。覆盖触发条件、preview→编辑顺序与失败不阻断交付。反向边界：只要影响面/执行流分析用 friday-impact；完整需求到 MR 用 friday-code。"
---

# Friday Refactoring

重构与符号改名工作流：先拿**只读**改名预览清单，再由代理在工作区自行编辑。全程使用 `friday` MCP（或容器白名单同名工具）。本技能只规定触发与顺序，不复制工具实现。

## 前置门槛

看不到 `friday` MCP 工具，或调用返回 401/403，引导用户运行 `npx -y @friday-ai-codes/mcp setup`。保留 `run_id`。

## 触发条件

| 用户意图 | 说明 |
| --- | --- |
| refactoring / 重构某符号 | 需要引用点清单再改 |
| 「把 X 改名为 Y」/ rename | 必须先 preview |
| 「有哪些地方引用了这个符号」 | 双源清单（图 + 文本） |

反向边界：只要 impact-analysis / 执行流波及 → `friday-impact`；要计划并建 MR → `friday-code`。

## 工具顺序 checklist

1. **定位目标**  
   - 确认 `repository_id` 与目标符号（优先 `symbol_id`；重名时按工具消歧参数收窄）。  
   - 读 `staleness`；索引明显过期时先提示再继续。

2. **先 `rename_preview`（只读）**  
   - 传入目标符号 + `new_name`。  
   - 输出按文件分组的 edits；每条置信为 `graph` 或 `text_search`。  
   - 信封 **`applied` 恒为 `false`**：本工具**从不**改工作树 / mirror，也没有 apply API。  
   - 阅读 `coverage_limitations`：动态引用（反射、模板拼名、`getattr`、配置拼路径等）v1 不保证命中。

3. **再自行编辑**  
   - 按清单在本地工作区用编辑工具改引用；以 `graph` 命中为优先依据，`text_search` 作兜底核对。  
   - 改完后可用测试 / `grep` 抽查；需要影响面叙事时接 `friday-impact`。

4. **失败不阻断交付**  
   - `rename_preview` 失败、配额用尽或返回空清单：记录原因，**继续**用本地 Grep/Read 完成改名或交付；不要因 preview 失败整单中止。  
   - 空清单仅在双源真实零命中且声明完整时成立——消歧失败 / ACL / 未索引应按错误处理，不假装「零引用」。

## 护栏

- ⛔ 不要寻找或调用「rename apply」类接口——本相位不提供。  
- ⛔ 不要把 preview 的 context 全文当可写补丁直接套用而不经审阅。  
- 不得编造未出现在清单中的引用行。  
- 凭证 / token 不得写入任何报告。
