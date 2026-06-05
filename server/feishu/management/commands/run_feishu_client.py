"""Django management command to run Feishu WebSocket client.

Usage:
    python manage.py run_feishu_client --project-id <uuid>
    python manage.py run_feishu_client --app-id <cli_xxx> --app-secret <secret>

This command starts a long-lived WebSocket connection to Feishu servers
to receive events (messages, card callbacks) without requiring a public webhook.
"""

import signal
import sys

import structlog
from django.core.management.base import BaseCommand, CommandError

logger = structlog.get_logger(__name__)


class Command(BaseCommand):
    help = "Run Feishu WebSocket client for receiving events via long connection"

    def add_arguments(self, parser):
        parser.add_argument(
            "--project-id",
            type=str,
            help="Friday project UUID to use for Feishu credentials",
        )
        parser.add_argument(
            "--app-id",
            type=str,
            help="Feishu App ID (cli_xxx format). Required if --project-id not provided.",
        )
        parser.add_argument(
            "--app-secret",
            type=str,
            help="Feishu App Secret. Required if --project-id not provided.",
        )
        parser.add_argument(
            "--debug",
            action="store_true",
            help="Enable debug logging for Lark SDK",
        )

    def handle(self, *args, **options):
        import lark_oapi as lark

        from feishu.websocket_client import FeishuWebSocketClient, create_client_for_project

        project_id = options.get("project_id")
        app_id = options.get("app_id")
        app_secret = options.get("app_secret")
        debug = options.get("debug", False)

        # Determine log level
        log_level = lark.LogLevel.DEBUG if debug else lark.LogLevel.INFO

        # Create client
        client: FeishuWebSocketClient

        if project_id:
            self.stdout.write(f"Loading Feishu credentials from project: {project_id}")
            try:
                client = create_client_for_project(project_id)
            except ValueError as e:
                raise CommandError(str(e))
        elif app_id and app_secret:
            self.stdout.write(f"Using provided credentials for app: {app_id}")
            client = FeishuWebSocketClient(
                app_id=app_id,
                app_secret=app_secret,
                log_level=log_level,
            )
        else:
            raise CommandError(
                "Either --project-id or both --app-id and --app-secret are required.\n"
                "Example:\n"
                "  python manage.py run_feishu_client --project-id <uuid>\n"
                "  python manage.py run_feishu_client --app-id cli_xxx --app-secret xxx"
            )

        # Setup signal handlers for graceful shutdown
        def signal_handler(signum, frame):
            self.stdout.write("\nReceived shutdown signal, stopping...")
            client.stop()
            sys.exit(0)

        signal.signal(signal.SIGINT, signal_handler)
        signal.signal(signal.SIGTERM, signal_handler)

        # Start client
        self.stdout.write(self.style.SUCCESS(
            "\n"
            "╔═══════════════════════════════════════════════════════════════╗\n"
            "║           Feishu WebSocket Client Starting...                 ║\n"
            "╠═══════════════════════════════════════════════════════════════╣\n"
            f"║  App ID: {client.app_id:<52} ║\n"
            "║                                                               ║\n"
            "║  Listening for:                                               ║\n"
            "║    • IM messages (user replies)                               ║\n"
            "║    • Card actions (button clicks, form submissions)           ║\n"
            "║                                                               ║\n"
            "║  Press Ctrl+C to stop                                         ║\n"
            "╚═══════════════════════════════════════════════════════════════╝\n"
        ))

        try:
            client.start()
        except Exception as e:
            logger.error("ws_client_failed", error=str(e))
            raise CommandError(f"WebSocket client failed: {e}")
