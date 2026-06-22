---
quick_id: 260623-ax1
slug: db-pool-pgbouncer
status: complete
date: 2026-06-23
---

# Quick Task 260623-ax1 — Summary

## 目标
Phase A 数据库连接池 + PgBouncer 支持，作为 async 高并发底座。进程角色分离
（server/worker/scheduler）此前已完成，本任务补齐连接复用层。

## 交付（4 个原子提交）
1. `feat(db)`：`settings.py` 纯函数 `configure_postgres_pool` + 单测（5 例）。
   仅 PostgreSQL 生效；直连启用 psycopg3 池 + CONN_MAX_AGE=0；`DB_PGBOUNCER=true`
   禁服务端游标 + 不叠加池；SQLite/MySQL 零回归。
2. `feat(compose)`：pgbouncer opt-in profile（`--profile pgbouncer`，edoburu
   v1.24.1-p1，transaction + max_prepared_statements=200）；worker/scheduler 改
   `${DATABASE_URL_DIRECT:-${DATABASE_URL:-...}}` 直连分流（未设时字节级向后兼容）。
3. `docs(env)`：`.env.example` 文档化连接池 env + PgBouncer 启用三步 + worker 直连提醒。
4. `feat(helm)`：`pgbouncer.enabled`（默认 off）+ Deployment/Service；启用时仅给
   server 追加 `DATABASE_URL→pgbouncer:6432` + `DB_PGBOUNCER=true`；external DB 组合
   fail-closed。

## 核心约束守住
- **默认零回归**：SQLite/MySQL 不动；`DATABASE_URL_DIRECT` 未设 / `pgbouncer.enabled=false`
  时 compose 与 helm 渲染与今天一致。
- **worker/scheduler 必须直连**：Procrastinate `LISTEN/NOTIFY` 穿不过 transaction pooling。
- **PgBouncer opt-in**：compose profile + helm flag，不强翻现网拓扑。

## 验证
- `pytest tests/test_settings_db_pool.py`：5/5 通过（三分支 + SQLite/MySQL 零回归）。
- `python manage.py check`：0 issues。
- `docker compose config -q`：通过；worker `DATABASE_URL_DIRECT` 未设时正确回退。
- `helm template`：off 无 pgbouncer；on 渲染 Deployment/Service + server 指向 pgbouncer；
  external DB + pgbouncer fail-closed。

## 未做 / 后续
- PgBouncer 运行期（真实集群/compose up）未做端到端验证 —— 属 opt-in，默认路径不受影响。
- Phase B 其余项（`_run_in_thread` 有界化、queue 进一步外推）与 Phase C
  （django-async-backend spike、free-threading 矩阵）按计划另开分支。
