---
title: API 参考
---
# API 参考
本文档从 OpenAPI Schema 自动生成，与服务端代码保持同步。
## 端点分组
- [accounts](/api/accounts) — 3 个端点
- [chat](/api/chat) — 4 个端点
- [projects](/api/projects) — 5 个端点:: tip 更新 API 文档
运行以下命令重新生成 schema 并更新文档：
```bash
cd server && python manage.py spectacular --color --file ../docs/public/schema.json
cd .. && node docs/scripts/generate-api-docs.mjs
```::
