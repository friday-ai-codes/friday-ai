# Change: 移除全局飞书配置
## Why
当前系统中存在全局飞书配置（`FEISHU_PLUGIN_ID`、`FEISHU_PLUGIN_SECRET`、`FEISHU_WEBHOOK_SECRET`），这些配置已被标记为 `deprecated`。系统已经完整实现了项目级别的飞书配置功能，全局配置不再被使用，保留它们只会造成以下问题：
1. **配置混淆**：用户可能误以为设置全局配置就能使用飞书功能
2. **代码冗余**：需要维护不再使用的配置字段和相关代码
3. **文档不一致**：`.env.example` 中存在已弃用但仍可配置的字段
## What Changes
- 从 [`server/src/friday/config.py`](server/src/friday/config.py) 中移除 `FEISHU_PLUGIN_ID`、`FEISHU_PLUGIN_SECRET`、`FEISHU_WEBHOOK_SECRET` 配置字段
- 从 [`.env.example`](.env.example) 中移除对应的环境变量配置说明
- 更新 `feishu-integration` 规格，记录全局配置已被移除
## Impact
- **Affected specs**: `feishu-integration`
- **Affected backend code**:
 - [`server/src/friday/config.py`](server/src/friday/config.py:34-39) - 移除飞书全局配置字段
- **Affected configuration files**:
 - [`.env.example`](.env.example:40-56) - 移除飞书全局配置说明
- **Breaking changes**: 无。这些配置从未被代码实际使用，项目级配置是唯一使用的方式
