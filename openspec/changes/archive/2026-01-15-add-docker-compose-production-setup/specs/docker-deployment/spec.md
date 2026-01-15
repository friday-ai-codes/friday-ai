## ADDED Requirements
### Requirement: Docker Compose 一键部署
系统 SHALL 支持用户通过 `docker-compose up -d` 命令一键启动完整的前后端服务。
#### Scenario: 首次启动服务
- **WHEN** 用户克隆项目并配置 `.env` 文件后执行 `docker-compose up -d`
- **THEN** 系统成功构建并启动所有服务容器
- **AND** 前端页面可通过配置的端口访问
- **AND** API 请求能正确代理到后端服务
#### Scenario: 服务重启
- **WHEN** 用户执行 `docker-compose restart`
- **THEN** 所有服务正常重启
- **AND** 数据卷中的数据保持不变
### Requirement: Nginx 反向代理配置
前端服务 SHALL 通过 Nginx 作为反向代理，统一处理静态文件服务和 API 请求转发。
#### Scenario: 静态文件访问
- **WHEN** 用户访问根路径或前端路由
- **THEN** Nginx 返回 Vue 应用的静态文件
- **AND** SPA 路由正常工作（刷新页面不会 404）
#### Scenario: API 请求代理
- **WHEN** 前端发起 `/api/*` 请求
- **THEN** Nginx 将请求转发到后端服务
- **AND** 响应正确返回给前端
#### Scenario: API 文档访问
- **WHEN** 用户访问 `/docs` 或 `/redoc`
- **THEN** Nginx 将请求转发到后端服务
- **AND** Swagger/ReDoc 文档页面正常显示
### Requirement: 环境变量配置
系统 SHALL 支持通过 `.env` 文件配置所有必要的运行时参数。
#### Scenario: 端口配置
- **WHEN** 用户在 `.env` 中设置 `FRIDAY_WEB_PORT=3000`
- **THEN** 前端服务在端口 3000 上对外提供服务
#### Scenario: 使用默认配置
- **WHEN** 用户未设置某个环境变量
- **THEN** 系统使用预定义的默认值运行
### Requirement: 健康检查端点代理
Nginx SHALL 正确代理后端的健康检查端点。
#### Scenario: 健康检查访问
- **WHEN** 用户或监控系统访问 `/health`
- **THEN** 请求被转发到后端服务
- **AND** 返回 JSON 格式的健康状态信息
