强制使用中文来生成注释、文档
## Database Migration Rules (数据库迁移规则)
当修改 `server/src/friday/models/` 中的模型定义时，**必须** 执行以下步骤：
1. **生成迁移脚本**：
 ```bash
 cd server && uv run alembic revision --autogenerate -m "描述变更"
 ```
2. **检查迁移脚本**：查看 `server/src/friday/alembic/versions/` 中生成的脚本
3. **本地测试迁移**：
 ```bash
 uv run alembic upgrade head
 ```
4. **提交迁移脚本**：迁移脚本必须包含在代码提交中
> **注意**：Docker 容器启动时会自动执行迁移，无需额外命令
