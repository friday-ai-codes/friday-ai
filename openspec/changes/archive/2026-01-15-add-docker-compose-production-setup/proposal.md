# Change: 完善 Docker Compose 生产部署配置
## Why
当前的 Docker 配置存在以下问题：
1. 前端 nginx 容器没有配置 API 反向代理，导致生产环境下前端无法访问后端 API
2. 用户从 GitHub 拉取项目后无法直接 `docker-compose up -d` 运行完整服务
3. 缺少必要的 nginx 配置文件和生产环境的环境变量说明
## What Changes
### 1. 新增 nginx 配置文件
- 创建 `web/nginx.conf` 配置文件
- 配置静态文件服务
- 配置 `/api` 路径的反向代理到后端服务
- 配置 `/health`、`/docs` 等后端端点的代理
### 2. 更新前端 Dockerfile
- 将 nginx.conf 复制到容器中
### 3. 更新 docker-compose.yml
- 优化服务依赖关系
- 添加前端构建时的环境变量支持
- 统一通过 nginx 对外暴露服务（可选的单端口模式）
### 4. 更新 .env.example
- 添加必要的 Web 端口配置说明
- 补充更完整的配置示例
### 5. 更新 README 文档
- 添加 Docker 部署的快速开始指南
- 说明环境变量配置方法
## Impact
- **Affected specs**: docker-deployment (新增)
- **Affected code**:
 - `web/nginx.conf` (新增)
 - `web/Dockerfile` (修改)
 - `docker-compose.yml` (修改)
 - `.env.example` (修改)
 - `README.md` / `README.zh-CN.md` (修改)
## Architecture Decision
采用 **Nginx 统一网关模式**：
- nginx 作为前端静态文件服务器
- nginx 同时作为后端 API 的反向代理
- 用户只需访问一个端口即可使用完整服务
- 避免 CORS 跨域问题
- 简化生产部署配置
```mermaid
graph LR
 User[用户浏览器] --> Nginx[Nginx:80]
 Nginx -->|静态文件| Static[/usr/share/nginx/html]
 Nginx -->|/api/*| Backend[Server:8000]
 Nginx -->|/health| Backend
 Nginx -->|/docs| Backend
```
