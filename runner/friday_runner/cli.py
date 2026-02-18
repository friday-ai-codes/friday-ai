from __future__ import annotations
import asyncio
import json
import socket
import httpx
import typer
from rich import print as rprint
from rich.table import Table
from . import __version__
from .client import FridayClient
from .config import (
 append_runner,
 apply_env_overrides,
 find_runner,
 load_config,
 remove_runner,
 save_config,
)
from .crypto import decrypt_token, encrypt_token
from .ws import run_ws
app = typer.Typer(name="friday-runner", help="Friday Runner CLI")
@app.command
def register(
 url: str = typer.Option(None, "--url", prompt="Server URL"),
 token: str = typer.Option(None, "--token", prompt="Registration token"),
 name: str = typer.Option("", "--name", prompt="Runner name (leave empty for hostname)"),
 scope: str = typer.Option(None, "--scope", prompt="Scope (global/project)"),
 concurrent: int = typer.Option(None, "--concurrent", prompt="Concurrent jobs"),
) -> None:
 """注册 Runner 到 Friday 服务端。"""
 if not name:
 name = socket.gethostname
 if scope not in ("global", "project"):
 rprint(f"[red]Invalid scope '{scope}', must be 'global' or 'project'[/red]")
 raise typer.Exit(1)
 client = FridayClient(url)
 try:
 resp = client.register(token, name, scope, concurrent, __version__)
 except httpx.HTTPStatusError as e:
 detail = e.response.json.get("detail", e.response.text) if e.response.content else str(e)
 rprint(f"[red]Registration failed: {detail}[/red]")
 raise typer.Exit(1)
 except (httpx.ConnectError, httpx.TimeoutException) as e:
 rprint(f"[red]Connection failed after retries: {e}[/red]")
 raise typer.Exit(1)
 except Exception as e:
 rprint(f"[red]Error: {e}[/red]")
 raise typer.Exit(1)
 finally:
 client.close
 encrypted = encrypt_token(resp.runner_token)
 doc = load_config
 append_runner(doc, {
 "name": resp.name,
 "url": url,
 "token": encrypted,
 "scope": resp.scope,
 "concurrent": concurrent,
 })
 save_config(doc)
 rprint("[green]Runner registered successfully![/green]")
 rprint(f" ID: {resp.runner_id}")
 rprint(f" Name: {resp.name}")
 rprint(f" Scope: {resp.scope}")
@app.command
def status(
 name: str = typer.Option(None, "--name", help="Runner name (default: first runner)"),
 json_output: bool = typer.Option(False, "--json", help="Output as JSON"),
) -> None:
 """查看 Runner 状态。"""
 doc = load_config
 runner = find_runner(doc, name)
 if not runner:
 rprint("[red]No runner configured[/red]")
 raise typer.Exit(1)
 runner = apply_env_overrides(runner)
 runner_token = decrypt_token(runner["token"])
 server_status: dict | None = None
 try:
 client = FridayClient(runner["url"])
 try:
 st = client.verify(runner_token)
 server_status = {
 "status": st.status,
 "version": st.version,
 "last_heartbeat": st.last_heartbeat,
 }
 finally:
 client.close
 except Exception:
 server_status = None
 if json_output:
 output = {
 "name": runner["name"],
 "url": runner["url"],
 "scope": runner["scope"],
 "concurrent": runner["concurrent"],
 **(server_status or {"status": "unknown", "version": "unknown", "last_heartbeat": None}),
 }
 typer.echo(json.dumps(output, indent=2))
 return
 table = Table(title=f"Runner: {runner['name']}")
 table.add_column("Field", style="cyan")
 table.add_column("Value")
 table.add_row("Name", runner["name"])
 table.add_row("Server URL", runner["url"])
 table.add_row("Scope", runner["scope"])
 table.add_row("Concurrent", str(runner["concurrent"]))
 if server_status:
 table.add_row("Status", server_status["status"])
 table.add_row("Version", server_status["version"])
 table.add_row("Last Heartbeat", server_status["last_heartbeat"] or "N/A")
 else:
 table.add_row("Status", "unknown (server unreachable)")
 rprint(table)
@app.command
def unregister(
 name: str = typer.Option(None, "--name", help="Runner name (default: first runner)"),
 force: bool = typer.Option(False, "--force", "-f", help="Skip confirmation"),
) -> None:
 """注销 Runner。"""
 doc = load_config
 runner = find_runner(doc, name)
 if not runner:
 rprint("[red]No runner configured[/red]")
 raise typer.Exit(1)
 runner_name = runner["name"]
 if not force:
 typer.confirm(f"Unregister runner '{runner_name}'?", abort=True)
 runner_token = decrypt_token(runner["token"])
 try:
 client = FridayClient(runner["url"])
 try:
 client.unregister(runner_token)
 finally:
 client.close
 except Exception as e:
 rprint(f"[yellow]Warning: server call failed ({e}), removing local config only[/yellow]")
 remove_runner(doc, runner_name)
 save_config(doc)
 rprint(f"[green]Runner '{runner_name}' unregistered successfully[/green]")
@app.command
def run(
 name: str = typer.Option(None, "--name", help="Runner name (default: first runner)"),
) -> None:
 """启动 Runner，连接 Server WebSocket。"""
 doc = load_config
 runner = find_runner(doc, name)
 if not runner:
 rprint("[red]No runner configured. Run 'friday-runner register' first.[/red]")
 raise typer.Exit(1)
 runner = apply_env_overrides(runner)
 runner_token = decrypt_token(runner["token"])
 rprint(f"[green]Starting runner '{runner['name']}'...[/green]")
 try:
 asyncio.run(
 run_ws(
 url=runner["url"],
 token=runner_token,
 name=runner["name"],
 version=__version__,
 concurrent=runner["concurrent"],
 )
 )
 except KeyboardInterrupt:
 rprint("\n[yellow]Runner stopped.[/yellow]")
 except RuntimeError as e:
 rprint(f"[red]{e}[/red]")
 raise typer.Exit(1)
