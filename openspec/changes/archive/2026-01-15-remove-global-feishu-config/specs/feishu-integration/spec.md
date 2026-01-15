## REMOVED Requirements
### Requirement: 全局飞书配置
**Reason**: 项目已完整实现项目级飞书配置功能，全局配置从未被代码实际使用，保留它们会造成配置混淆和维护负担。
**Migration**: 无需迁移。用户应在 Web UI 中为每个项目单独配置飞书集成。
被移除的配置项：
- `FEISHU_PLUGIN_ID` - 全局飞书插件 ID
- `FEISHU_PLUGIN_SECRET` - 全局飞书插件 Secret
- `FEISHU_WEBHOOK_SECRET` - 全局 Webhook 验证 Token
对应的环境变量：
- `FRIDAY_FEISHU_PLUGIN_ID`
- `FRIDAY_FEISHU_PLUGIN_SECRET`
- `FRIDAY_FEISHU_VERIFICATION_TOKEN`
#### Scenario: 全局配置不再可用
- **WHEN** 用户在 .env 文件中设置 FRIDAY_FEISHU_PLUGIN_ID 等环境变量
- **THEN** 这些变量将被忽略
- **AND** 用户必须在 Web UI 中为每个项目单独配置飞书集成
## MODIFIED Requirements
### Requirement: 项目级飞书凭证配置
系统 SHALL 支持为每个 Project 独立配置飞书项目插件凭证，包括：
- 飞书项目空间 ID（Space ID / project_key）
- 飞书项目插件 ID（Plugin ID）
- 飞书项目插件 Secret（Plugin Secret，加密存储）
- Webhook 验证 Token（加密存储）
注：全局飞书配置已被移除，项目级配置是唯一支持的配置方式。
#### Scenario: 配置飞书插件凭证
- **WHEN** 用户调用 POST /api/projects/{project_id}/feishu-config 接口
- **AND** 提供有效的 plugin_id、plugin_secret 和 webhook_token
- **THEN** 系统将凭证加密存储到数据库
- **AND** 返回配置成功状态
#### Scenario: 查看飞书配置状态
- **WHEN** 用户调用 GET /api/projects/{project_id}/feishu-config 接口
- **THEN** 系统返回配置状态（已配置/未配置）
- **AND** 返回已配置的字段列表（不包含敏感凭证内容）
#### Scenario: 删除飞书配置
- **WHEN** 用户调用 DELETE /api/projects/{project_id}/feishu-config 接口
- **THEN** 系统清除该项目的所有飞书凭证
#### Scenario: 测试飞书凭证有效性
- **WHEN** 用户调用 POST /api/projects/{project_id}/feishu-config/test 接口
- **THEN** 系统使用配置的凭证尝试获取 tenant_access_token
- **AND** 返回凭证是否有效的结果
