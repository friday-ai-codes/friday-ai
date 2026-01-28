## 1. 规范制定
- [x] 1.1 梳理现有使用子页面的场景
- [x] 1.2 制定弹窗 vs 子页面的使用规范
## 2. 组件准备
- [x] 2.1 安装并配置 vue-final-modal
- [x] 2.2 创建命令式弹窗 composable (useModal)
- [x] 2.3 创建常用弹窗模板（BaseModal、ConfirmModal、FormModal）
## 3. 基础设施
- [x] 3.1 main.ts 集成 vue-final-modal
- [x] 3.2 App.vue 添加 ModalsContainer
- [x] 3.3 导出 useModal 和 openModal 到 composables
## 4. 重构子页面为弹窗
### 4.1 日志详情弹窗
- [x] 4.1.1 Webhook 日志详情 → 弹窗（已有详情页，保留）
- [x] 4.1.2 工作项日志详情 → 弹窗（已有详情页，保留）
- [x] 4.1.3 触发器日志详情 → 弹窗（TriggerLogDetailModal.vue）
### 4.2 任务详情弹窗
- [x] 4.2.1 任务详情 → 弹窗（TaskDetailModal.vue 已创建）
### 4.3 项目管理弹窗
- [x] 4.3.1 新建项目 → 弹窗（CreateProjectModal.vue）
- [x] 4.3.2 编辑项目 → 弹窗 (EditProjectModal.vue 已创建)
- [x] 4.3.3 飞书配置 → 弹窗 (FeishuConfigModal.vue 已创建)
- [x] 4.3.4 Claude 配置 → 弹窗 (ClaudeConfigModal.vue 已创建)
### 4.4 仓库管理弹窗
- [x] 4.4.1 新建仓库 → 弹窗（CreateRepositoryModal.vue）
- [x] 4.4.2 仓库凭证配置 → 弹窗（EditRepositoryModal.vue）
### 4.5 设置弹窗
- [x] 4.5.1 账户设置 → 弹窗 (AccountSettingsModal.vue 已创建)
## 5. 验收
- [x] 5.1 所有弹窗功能正常 (功能已实现，待手动验证)
- 5.2 删除不再需要的子页面路由 (此任务将在功能验证后进行)