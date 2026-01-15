## ADDED Requirements
### Requirement: Repository Management UI
系统 SHALL 提供仓库管理界面。
#### Scenario: Repository List Page
- **WHEN** 用户访问 `/repositories`
- **THEN** 显示所有已配置的 Git 仓库列表
#### Scenario: Create/Edit Repository
- **WHEN** 用户创建或编辑仓库
- **THEN** 提供表单输入 git_url, name, default_branch, claude_md_path 等信息
### Requirement: Project-Repository Linking UI
系统 SHALL 在项目详情页提供仓库关联管理功能。
#### Scenario: Link Repository
- **WHEN** 在项目详情页点击“关联仓库”
- **THEN** 弹出对话框选择已有仓库进行关联
#### Scenario: Unlink Repository
- **WHEN** 在已关联仓库列表中点击“移除”
- **THEN** 解除该仓库与当前项目的关联
## MODIFIED Requirements
### Requirement: 项目管理页面
项目详情页 SHALL 移除直接的 Git 配置展示，改为展示关联的仓库列表。
#### Scenario: 项目详情页
- **WHEN** 用户访问项目详情页
- **THEN** 显示“基本信息”（飞书配置）
- **AND** 显示“关联仓库”列表