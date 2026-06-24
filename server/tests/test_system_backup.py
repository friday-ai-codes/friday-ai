"""SystemBackupView 按数据库引擎分派的单元测试。

只测分派与命令构造逻辑：
- sqlite 走真实文件复制（不依赖外部二进制）；
- postgres / mysql 通过 monkeypatch `_run_dump_cmd` 模拟子进程，不真正调 pg_dump。

不加 `django_db`：这些用例只读 `settings.DATABASES` 字典与本地临时文件，不触 ORM。
asyncio_mode=auto（见 pyproject），async 用例自动运行。
"""

from pathlib import Path

from django.http import FileResponse
from django.test import override_settings
from rest_framework.response import Response

from system.views import SystemBackupView, _db_conn_params, _db_engine_kind

SQLITE_ENGINE = "django.db.backends.sqlite3"
PG_ENGINE = "django.db.backends.postgresql"
MYSQL_ENGINE = "django.db.backends.mysql"


def _pg_db(name: str = "friday"):
    return {
        "default": {
            "ENGINE": PG_ENGINE,
            "NAME": name,
            "USER": "fuser",
            "PASSWORD": "fpwd",
            "HOST": "dbhost",
            "PORT": "5432",
        }
    }


class TestEngineKind:
    def test_sqlite(self):
        with override_settings(DATABASES={"default": {"ENGINE": SQLITE_ENGINE, "NAME": "x.db"}}):
            assert _db_engine_kind() == "sqlite"

    def test_postgres(self):
        with override_settings(DATABASES=_pg_db()):
            assert _db_engine_kind() == "postgres"
            params = _db_conn_params()
            assert params["name"] == "friday"
            assert params["password"] == "fpwd"
            assert params["port"] == "5432"

    def test_mysql(self):
        with override_settings(DATABASES={"default": {"ENGINE": MYSQL_ENGINE, "NAME": "db"}}):
            assert _db_engine_kind() == "mysql"

    def test_unknown(self):
        with override_settings(DATABASES={"default": {"ENGINE": "django.db.backends.oracle", "NAME": "db"}}):
            assert _db_engine_kind() == "unknown"


class TestSqliteBackup:
    async def test_download_sqlite_returns_file(self, tmp_path):
        db = tmp_path / "friday.db"
        db.write_bytes(b"SQLite format 3\x00 fake payload")
        with override_settings(DATABASES={"default": {"ENGINE": SQLITE_ENGINE, "NAME": str(db)}}):
            resp = await SystemBackupView()._download_sqlite()
        assert isinstance(resp, FileResponse)
        assert resp.status_code == 200
        assert "friday_backup_" in resp.filename
        resp.close()

    async def test_download_sqlite_missing_file(self, tmp_path):
        db = tmp_path / "nope.db"
        with override_settings(DATABASES={"default": {"ENGINE": SQLITE_ENGINE, "NAME": str(db)}}):
            resp = await SystemBackupView()._download_sqlite()
        assert isinstance(resp, Response)
        assert resp.status_code == 404


class TestPostgresBackup:
    async def test_download_postgres_success(self, monkeypatch):
        captured: dict = {}

        async def fake_run(cmd, env_extra, **kwargs):
            captured["cmd"] = cmd
            captured["env"] = env_extra
            # 模拟 pg_dump 写出 -f 指定的输出文件
            if "-f" in cmd:
                Path(cmd[cmd.index("-f") + 1]).write_bytes(b"PGDMP fake dump")
            return 0, ""

        monkeypatch.setattr("system.views._run_dump_cmd", fake_run)
        with override_settings(DATABASES=_pg_db()):
            resp = await SystemBackupView()._download_postgres()
        assert isinstance(resp, FileResponse)
        assert resp.status_code == 200
        assert resp.filename.endswith(".dump")
        assert "pg_dump" in captured["cmd"]
        assert "-Fc" in captured["cmd"]
        assert captured["env"]["PGPASSWORD"] == "fpwd"
        resp.close()

    async def test_download_postgres_failure_returns_500(self, monkeypatch):
        async def fake_run(cmd, env_extra, **kwargs):
            return 127, "未找到可执行文件：pg_dump"

        monkeypatch.setattr("system.views._run_dump_cmd", fake_run)
        with override_settings(DATABASES=_pg_db()):
            resp = await SystemBackupView()._download_postgres()
        assert isinstance(resp, Response)
        assert resp.status_code == 500


class TestMysqlBackup:
    async def test_download_mysql_success(self, monkeypatch):
        captured: dict = {}

        async def fake_run(cmd, env_extra, *, stdout_path=None, stdin_path=None):
            captured["cmd"] = cmd
            captured["env"] = env_extra
            if stdout_path:
                Path(stdout_path).write_bytes(b"-- mysql dump")
            return 0, ""

        monkeypatch.setattr("system.views._run_dump_cmd", fake_run)
        with override_settings(DATABASES={
            "default": {
                "ENGINE": MYSQL_ENGINE,
                "NAME": "friday",
                "USER": "u",
                "PASSWORD": "p",
                "HOST": "h",
                "PORT": "3306",
            }
        }):
            resp = await SystemBackupView()._download_mysql()
        assert isinstance(resp, FileResponse)
        assert resp.filename.endswith(".sql")
        assert "mysqldump" in captured["cmd"]
        assert captured["env"]["MYSQL_PWD"] == "p"
        resp.close()


class TestDispatch:
    async def test_get_unknown_engine_returns_400(self):
        with override_settings(DATABASES={"default": {"ENGINE": "django.db.backends.oracle", "NAME": "x"}}):
            resp = await SystemBackupView().get(None)
        assert isinstance(resp, Response)
        assert resp.status_code == 400
