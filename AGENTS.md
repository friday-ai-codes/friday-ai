<!-- OPENSPEC:START -->
# OpenSpec Instructions
These instructions are for AI assistants working in this project.
Always open `@/openspec/AGENTS.md` when the request:
- Mentions planning or proposals (words like proposal, spec, change, plan)
- Introduces new capabilities, breaking changes, architecture shifts, or big performance/security work
- Sounds ambiguous and you need the authoritative spec before coding
Use `@/openspec/AGENTS.md` to learn:
- How to create and apply change proposals
- Spec format and conventions
- Project structure and guidelines
Keep this managed block so 'openspec update' can refresh the instructions.
<!-- OPENSPEC:END -->
强制使用中文来生成注释、openspec 的文档
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