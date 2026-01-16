## 1. 导航菜单增强
- [x] 1.1 在主导航菜单中添加"仓库"链接
## 2. 后端 API 支持
- [x] 2.1 添加 RepositoryWithProjectsRead 响应模式，包含 projects 字段
- [x] 2.2 修改 GET /api/repositories/{id} 返回关联项目信息
## 3. 前端类型定义
- [x] 3.1 添加 ProjectSummary 类型
- [x] 3.2 更新 Repository 类型定义，包含 projects 字段
## 4. 仓库 Store 增强
- [x] 4.1 Store 自动处理 API 返回的 projects 数据（无需额外修改）
## 5. 仓库详情页 UI
- [x] 5.1 在仓库详情页增加"关联项目"卡片
- [x] 5.2 展示关联项目列表，包含项目名称和链接
- [x] 5.3 处理无关联项目的空状态
## 6. 测试验证
- [x] 6.1 后端模型导入成功验证
- [x] 6.2 前端类型检查通过（vue-tsc）
- [x] 6.3 代码实现完成
