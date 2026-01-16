# Change: 完善前端项目与仓库分离架构
## Why
当前前端实现存在以下问题：
1. **仓库详情页缺少关联项目列表**：项目可以查看和管理关联的仓库，但仓库详情页无法查看关联的项目
2. **双向关联不对称**：项目配置与仓库配置是两个独立的维度，但当前前端只实现了项目→仓库的单向关联展示
3. **用户体验不一致**：用户从仓库角度无法快速了解该仓库被哪些项目使用
4. **仓库管理入口缺失**：导航菜单中没有仓库管理的独立入口，用户只能从项目中间接访问
## What Changes
1. **导航菜单增加仓库入口**
 - 在主导航中添加"仓库"链接，与"项目"并列
 - 直接跳转到仓库列表页
2. **仓库详情页增加关联项目列表**
 - 显示当前仓库关联的所有项目
 - 提供跳转到项目详情的链接
3. **完善后端 API**
 - 添加 RepositoryWithProjectsRead 响应模式
 - GET /api/repositories/{id} 返回关联项目信息
4. **优化 UI 一致性**
 - 仓库详情页与项目详情页保持对称的关联展示
 - 统一卡片布局和信息展示
## Impact
- 受影响的规范：`frontend-architecture`
- 受影响的代码：
 - `web/src/layouts/default.vue` - 导航菜单
 - `web/src/pages/repositories/[id].vue` - 仓库详情页
 - `web/src/types/index.ts` - 前端类型定义
 - `server/src/friday/models/repository.py` - 后端模型
 - `server/src/friday/routes/repositories.py` - 仓库 API
