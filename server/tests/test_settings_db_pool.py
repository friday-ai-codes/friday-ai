"""Phase A 守护：数据库连接池 / PgBouncer settings 逻辑。

直接测纯函数 ``configure_postgres_pool``——不触 env / 不重载 settings 模块，仅断言
三条分支（直连池化 / PgBouncer 安全 / 非 postgres 零回归）就地修改 db_config 的行为。
"""

from friday.settings import configure_postgres_pool

_PG = "django.db.backends.postgresql"
_SQLITE = "django.db.backends.sqlite3"
_MYSQL = "django.db.backends.mysql"

_POOL_KW = {"pool_enabled": True, "min_size": 2, "max_size": 10, "timeout": 30}


def test_postgres_direct_enables_pool():
    """直连 Postgres：CONN_MAX_AGE=0 + OPTIONS.pool 注入，不禁用服务端游标。"""
    cfg = {"ENGINE": _PG}
    configure_postgres_pool(cfg, pgbouncer=False, **_POOL_KW)

    assert cfg["CONN_MAX_AGE"] == 0
    assert cfg["OPTIONS"]["pool"] == {"min_size": 2, "max_size": 10, "timeout": 30}
    assert "DISABLE_SERVER_SIDE_CURSORS" not in cfg


def test_postgres_pgbouncer_disables_cursors_and_pool():
    """PgBouncer 后：禁用服务端游标 + 不叠加 psycopg 池；CONN_MAX_AGE=0。"""
    cfg = {"ENGINE": _PG, "OPTIONS": {"pool": {"max_size": 99}}}
    configure_postgres_pool(cfg, pgbouncer=True, **_POOL_KW)

    assert cfg["CONN_MAX_AGE"] == 0
    assert cfg["DISABLE_SERVER_SIDE_CURSORS"] is True
    assert "pool" not in cfg["OPTIONS"]


def test_postgres_pool_disabled():
    """直连但显式关闭池：CONN_MAX_AGE=0，但不注入 pool。"""
    cfg = {"ENGINE": _PG}
    configure_postgres_pool(
        cfg, pgbouncer=False, pool_enabled=False, min_size=2, max_size=10, timeout=30
    )

    assert cfg["CONN_MAX_AGE"] == 0
    assert "pool" not in cfg.get("OPTIONS", {})


def test_sqlite_untouched():
    """SQLite（dev/pytest）：完全不改任何字段（零回归红线）。"""
    cfg = {"ENGINE": _SQLITE, "NAME": "/tmp/x.db"}
    configure_postgres_pool(cfg, pgbouncer=False, **_POOL_KW)

    assert cfg == {"ENGINE": _SQLITE, "NAME": "/tmp/x.db"}


def test_mysql_untouched():
    """MySQL/MariaDB：非 postgres 引擎同样零改动。"""
    cfg = {"ENGINE": _MYSQL, "NAME": "friday"}
    configure_postgres_pool(cfg, pgbouncer=True, **_POOL_KW)

    assert cfg == {"ENGINE": _MYSQL, "NAME": "friday"}
