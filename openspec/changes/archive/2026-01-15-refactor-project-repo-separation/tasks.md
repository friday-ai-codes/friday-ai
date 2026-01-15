## 1. 后端实现 (Backend Implementation)
- [x] 1.1 创建 `Repository` 模型：在 `server/src/friday/models/repository.py` 中定义
- [x] 1.2 创建 `ProjectRepository` 关联模型：用于实现多对多关系
- [x] 1.3 更新 `Project` 模型：移除 Git 相关字段，添加 `repositories` 关联字段
- [x] 1.4 更新 `Task` 模型：添加 `repository_id` 字段以指定执行仓库（已改为可选字段）
- [x] 1.5 更新 `GitCredential` 模型：将凭证关联对象从 `Project` 改为 `Repository`
- [x] 1.6 创建数据迁移脚本：将现有的 Project 数据拆分为 Project + Repository 并建立关联
- [x] 1.7 实现仓库管理接口：在 `server/src/friday/routes/repositories.py` 中实现 Repository 的 CRUD 路由
- [x] 1.8 更新项目接口：在 Project 路由中处理仓库的关联/解除关联操作
- [x] 1.9 更新任务执行逻辑：修改 Task 执行流程，使用 `repository_id` 获取 Git 上下文和凭证
- [x] 1.10 更新 Webhook 逻辑：当项目只有一个关联仓库时自动分配 repository_id
## 2. 前端实现 (Frontend Implementation)
- [x] 2.1 添加类型定义：在 `web/src/types/index.ts` 中添加 `Repository` 相关类型
- [x] 2.2 创建仓库 API：创建 `web/src/api/repositories.ts` 封装后端接口
- [x] 2.3 创建仓库 Store：实现 `useRepositoriesStore` 用于状态管理
- [x] 2.4 创建仓库列表页：开发 `web/src/pages/repositories/index.vue`
- [x] 2.5 创建仓库编辑页：开发仓库的创建和编辑表单页面
- [x] 2.6 更新项目详情页：移除旧的 Git 配置展示，改为展示"关联仓库"列表
- [x] 2.7 实现关联功能：在项目详情页添加"关联仓库"对话框
- [x] 2.8 更新任务详情页：支持在任务详情页选择/更改关联的 Repository
## 3. 验证 (Verification)
- 3.1 验证数据迁移正确性：检查旧数据是否正确拆分且关联
- 3.2 验证关联管理：测试项目与仓库的关联、解除关联功能
- 3.3 验证任务执行：确保任务能正确获取关联仓库的 Git 配置并执行