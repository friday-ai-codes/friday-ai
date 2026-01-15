## 1. Nginx 配置
- [x] 1.1 创建 `web/nginx.conf` 配置文件
 - 配置静态文件服务 (root: /usr/share/nginx/html)
 - 配置 SPA fallback (try_files $uri $uri/ /index.html)
 - 配置 `/api/` 反向代理到 http://server:8000
 - 配置 `/health`、`/docs`、`/openapi.json` 代理
 - 配置 gzip 压缩
 - 配置缓存策略
## 2. 前端 Dockerfile 更新
- [x] 2.1 更新 `web/Dockerfile` 以包含 nginx 配置
 - 取消注释 nginx.conf 复制行
 - 确保构建产物正确复制
## 3. Docker Compose 配置优化
- [x] 3.1 更新 `docker-compose.yml`
 - 确认服务依赖关系正确
 - web 服务的健康检查配置
 - 移除后端直接暴露端口（可选，保持灵活性）
## 4. 环境变量配置
- [x] 4.1 更新 `.env.example`
 - 添加 `FRIDAY_WEB_PORT` 的说明
 - 补充必要配置的生成方法示例
## 5. 文档更新
- [x] 5.1 更新 `README.md` 添加 Docker 部署说明
- [x] 5.2 更新 `README.zh-CN.md` 添加 Docker 部署说明
## 6. 验证测试
- [x] 6.1 本地构建测试 `docker-compose build`
- [x] 6.2 完整启动测试 `docker-compose up -d`
- [x] 6.3 验证前端页面正常访问
- [x] 6.4 验证 API 代理正常工作 (访问 /api/projects)
- [x] 6.5 验证健康检查端点正常工作
## 7. 额外修复
- [x] 7.1 修复 `server/pyproject.toml` 移除 readme 字段
- [x] 7.2 修复 `web/src/composables/useApi.ts` TypeScript 类型推断问题
