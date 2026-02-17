from __future__ import annotations
import os
from pathlib import Path
import tomlkit
from tomlkit.toml_document import TOMLDocument
CONFIG_DIR = Path.home / ".friday-runner"
CONFIG_FILE = CONFIG_DIR / "config.toml"
def ensure_config_dir -> None:
 CONFIG_DIR.mkdir(mode=0o700, parents=True, exist_ok=True)
def load_config -> TOMLDocument:
 if CONFIG_FILE.exists:
 return tomlkit.parse(CONFIG_FILE.read_text)
 return tomlkit.document
def save_config(doc: TOMLDocument) -> None:
 ensure_config_dir
 CONFIG_FILE.write_text(tomlkit.dumps(doc))
 CONFIG_FILE.chmod(0o600)
def get_runners(doc: TOMLDocument) -> list[dict]:
 runners = doc.get("runner", )
 return [dict(r) for r in runners]
def append_runner(doc: TOMLDocument, runner_data: dict) -> None:
 if "runner" not in doc:
 doc.add("runner", tomlkit.aot)
 table = tomlkit.table
 for k, v in runner_data.items:
 table.add(k, v)
 doc["runner"].append(table)
def remove_runner(doc: TOMLDocument, name: str) -> bool:
 runners = doc.get("runner")
 if not runners:
 return False
 for i, r in enumerate(runners):
 if r.get("name") == name:
 del runners[i]
 return True
 return False
def find_runner(doc: TOMLDocument, name: str | None = None) -> dict | None:
 runners = doc.get("runner", )
 if not runners:
 return None
 if name is None:
 return dict(runners[0])
 for r in runners:
 if r.get("name") == name:
 return dict(r)
 return None
_ENV_MAP = {
 "FRIDAY_RUNNER_URL": "url",
 "FRIDAY_RUNNER_NAME": "name",
 "FRIDAY_RUNNER_CONCURRENT": "concurrent",
}
def apply_env_overrides(runner: dict) -> dict:
 result = dict(runner)
 for env_key, field in _ENV_MAP.items:
 val = os.environ.get(env_key)
 if val is not None:
 result[field] = int(val) if field == "concurrent" else val
 return result
