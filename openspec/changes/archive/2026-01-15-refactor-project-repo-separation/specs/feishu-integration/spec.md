## MODIFIED Requirements
### Requirement: 项目级飞书凭证配置
Project 模型 SHALL 仅包含飞书集成配置，不再包含 Git 配置。
#### Scenario: 配置飞书插件凭证
- **WHEN** 用户调用设置飞书配置接口
- **THEN** 系统更新 Project 的飞书凭证字段
- **AND** 不影响任何 Git 仓库配置
### Requirement: 数据模型扩展
Project 模型 SHALL 移除 Git 相关字段，保留飞书配置字段。
#### Scenario: Project 模型结构
- **WHEN** 查看 Project 模型定义
- **THEN** 包含 feishu_project_key, feishu_plugin_id, feishu_plugin_secret_encrypted 等字段
- **AND** 不包含 repo_url, git_platform 等字段