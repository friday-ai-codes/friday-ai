# 迁移版本目录
此目录存放 Alembic 生成的迁移脚本。
## 使用方法
### 生成新迁移
```bash
cd server
uv run alembic revision --autogenerate -m "描述变更内容"
```
### 执行迁移（升级到最新版本）
```bash
cd server
uv run alembic upgrade head
```
### 回滚一个版本
```bash
cd server
uv run alembic downgrade -1
```
### 查看当前版本
```bash
cd server
uv run alembic current
```
### 查看历史
```bash
cd server
uv run alembic history
```
