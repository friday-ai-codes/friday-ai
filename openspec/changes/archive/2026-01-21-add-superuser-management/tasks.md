# Tasks: 超级管理员用户管理
## 1. 后端 - 数据模型
- [x] 1.1 在 `User` 模型添加 `must_change_password` 布尔字段（默认 False）
- [x] 1.2 生成并执行数据库迁移
## 2. 后端 - 管理命令
- [x] 2.1 创建 `init_superuser` 命令：服务启动时检查并创建默认管理员
- [x] 2.2 创建 `reset_superuser_password` 命令：重置管理员密码并打印新密码
- [x] 2.3 修改 Docker 启动脚本，在 migrate 后调用 `init_superuser`
## 3. 后端 - 认证流程
- [x] 3.1 修改 `LoginView`：检测 `must_change_password`，返回特殊响应
- [x] 3.2 新增 `ForceChangePasswordView`：处理强制修改密码请求
- [x] 3.3 修改 `ChangePasswordView`：成功后清除 `must_change_password` 标记
## 4. 后端 - 管理员设置 API
- [x] 4.1 新增 `AdminProfileView`：获取/更新管理员用户名和显示名
- [x] 4.2 新增 `AdminChangePasswordView`：管理员修改自己密码
- [x] 4.3 添加相应的序列化器
- [x] 4.4 注册新的 URL 路由
## 5. 前端 - 强制修改密码
- [x] 5.1 修改登录逻辑：检测 `must_change_password` 响应
- [x] 5.2 创建强制修改密码页面/弹窗组件
- [x] 5.3 添加路由守卫：未修改密码前禁止访问其他页面
## 6. 前端 - 管理员设置页面
- [x] 6.1 在系统设置中添加「账号设置」入口
- [x] 6.2 创建账号设置页面：显示/修改用户名、显示名
- [x] 6.3 创建修改密码表单组件
- [x] 6.4 添加相应的 API 调用函数
## 7. 测试
- [x] 7.1 Django 系统检查通过
- [x] 7.2 管理命令可正常执行
