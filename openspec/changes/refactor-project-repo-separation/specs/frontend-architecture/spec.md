## ADDED Requirements
### Requirement: Repository Navigation Entry
系统 SHALL 在主导航菜单中提供仓库管理的独立入口。
#### Scenario: Repository Navigation Link
- **WHEN** 用户查看主导航菜单
- **THEN** 显示"仓库"导航链接
- **AND** 点击后跳转到 `/repositories` 仓库列表页
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
- **WHEN** 在项目详情页点击"关联仓库"
- **THEN** 弹出对话框选择已有仓库进行关联
#### Scenario: Unlink Repository
- **WHEN** 在已关联仓库列表中点击"移除"
- **THEN** 解除该仓库与当前项目的关联
### Requirement: Repository-Project Association Display
系统 SHALL 在仓库详情页展示关联的项目列表。
#### Scenario: Repository Detail Shows Associated Projects
- **WHEN** 用户访问仓库详情页 `/repositories/:id`
- **THEN** 显示"关联项目"卡片
- **AND** 列出所有与该仓库关联的项目
- **AND** 每个项目提供跳转到项目详情的链接
#### Scenario: No Associated Projects
- **WHEN** 仓库没有关联任何项目
- **THEN** 显示"暂无关联项目"的空状态提示
### Requirement: Repositories Store Projects Support
仓库 Store SHALL 支持管理仓库关联的项目数据。
#### Scenario: Fetch Repository With Projects
- **WHEN** 调用 `repositoriesStore.fetchRepository(id)`
- **THEN** 返回的仓库数据应包含 `projects` 字段
- **AND** `projects` 字段包含关联项目的基本信息（id、name）
## MODIFIED Requirements
### Requirement: 项目管理页面
前端项目 SHALL 提供完整的项目管理界面。
1. 项目列表页 `/projects`
2. 新建项目页 `/projects/new`
3. 项目详情页 `/projects/:id`
4. 编辑项目页 `/projects/:id/edit`
5. 飞书配置页 `/projects/:id/feishu`
项目详情页 SHALL 移除直接的 Git 配置展示，改为展示关联的仓库列表。
#### Scenario: 项目列表页
- **WHEN** 用户访问 `/projects`
- **THEN** 应显示项目表格
- **AND** 每行显示项目名称
#### Scenario: 项目详情页
- **WHEN** 用户访问项目详情页
- **THEN** 显示"基本信息"（飞书配置）
- **AND** 显示"关联仓库"列表
- **AND** 提供关联/解除关联仓库的操作
#### Scenario: 新建项目页
- **WHEN** 用户访问 `/projects/new`
- **THEN** 应显示项目创建表单
- **AND** 验证必填字段
#### Scenario: 飞书配置页
- **WHEN** 用户访问 `/projects/:id/feishu`
- **THEN** 应显示飞书集成配置表单
- **AND** 支持配置应用凭证
