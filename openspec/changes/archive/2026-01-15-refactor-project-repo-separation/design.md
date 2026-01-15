# Design: Project and Repository Separation
## Context
当前系统中的 `Project` 模型是一个“上帝对象”，同时承载了 Git 仓库信息和飞书项目信息。随着多项目多仓库场景的出现（如“智课”项目和“学习工具”项目共享 `study-app` 仓库），这种 1:1 的强耦合关系不再适用。
## Goals
- 解耦 `Project`（飞书项目）和 `Repository`（Git 仓库）。
- 实现 M:N 的关联关系。
- 保持现有功能（任务执行、Webhook 处理）的向后兼容性。
## Data Model Changes
### 1. New Model: `Repository`
将原 `Project` 中的 Git 相关字段剥离。
```python
class Repository(SQLModel, table=True):
 id: str
 name: str # 仓库显示名称
 git_url: str # 原 repo_url
 git_platform: GitPlatform
 default_branch: str
 claude_md_path: str
 description: Optional[str]
 # Relationships
 credentials: List["GitCredential"]
 projects: List["Project"] = Relationship(back_populates="repositories", link_model=ProjectRepository)
```
### 2. Modified Model: `Project`
保留飞书相关字段，移除 Git 字段。
```python
class Project(SQLModel, table=True):
 # ... basic fields ...
 feishu_project_key: str
 feishu_plugin_id: str
 # ... other feishu fields ...
 # Relationships
 repositories: List["Repository"] = Relationship(back_populates="projects", link_model=ProjectRepository)
```
### 3. New Association Model: `ProjectRepository`
```python
class ProjectRepository(SQLModel, table=True):
 project_id: str = Field(foreign_key="projects.id", primary_key=True)
 repository_id: str = Field(foreign_key="repositories.id", primary_key=True)
```
### 4. Updated Model: `Task`
任务需要明确知道它属于哪个飞书项目（来源）以及在哪个仓库执行（目的地）。
```python
class Task(SQLModel, table=True):
 # ...
 project_id: str # 关联的飞书项目
 repository_id: str # 新增：关联的执行仓库
```
## Migration Plan
由于是破坏性变更，且涉及数据拆分，需要谨慎处理。
1. **Step 1: Schema Migration**
 - 创建 `repositories` 表。
 - 创建 `project_repositories` 关联表。
 - 在 `tasks` 表中添加 `repository_id` 字段（nullable）。
2. **Step 2: Data Migration Script**
 - 遍历现有 `projects` 表。
 - 为每个 Project 创建一个对应的 `Repository` 记录（复制 git_url 等字段）。
 - 创建 `ProjectRepository` 关联记录。
 - 将原 Project 的 GitCredential 迁移关联到新 Repository。
 - 更新该 Project 下的所有 Task，填充 `repository_id`。
3. **Step 3: Cleanup**
 - 删除 `projects` 表中的 Git 相关列（repo_url, default_branch 等）。
 - 将 `tasks.repository_id` 设为 non-nullable。
## API Design
### Repository Management
- `GET /repositories`
- `POST /repositories`
- `GET /repositories/{id}`
- `PATCH /repositories/{id}`
- `DELETE /repositories/{id}`
### Association Management
- `POST /projects/{id}/repositories`: 关联仓库
- `DELETE /projects/{id}/repositories/{repo_id}`: 解除关联
- `GET /projects/{id}/repositories`: 获取项目关联的仓库列表
## UI UX
- **项目详情页**：新增“关联仓库”卡片，展示已关联仓库，支持添加/移除。
- **仓库管理页**：新增全局仓库管理页面，支持 CRUD。
- **任务创建**：
 - 如果项目只关联一个仓库 -> 自动选择。
 - 如果关联多个仓库 -> 任务创建后需人工选择仓库（或创建时选择）。