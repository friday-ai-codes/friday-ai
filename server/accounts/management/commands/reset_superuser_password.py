"""Management command to reset superuser password."""

import secrets
import string

import structlog
from django.core.management.base import BaseCommand, CommandError

from accounts.models import User

logger = structlog.get_logger(__name__)


def generate_random_password(length: int = 16) -> str:
    """Generate a secure random password."""
    alphabet = string.ascii_letters + string.digits + "!@#$%^&*"
    return "".join(secrets.choice(alphabet) for _ in range(length))


class Command(BaseCommand):
    """Reset superuser password."""

    help = "Reset superuser password and require password change on next login"

    def add_arguments(self, parser):
        parser.add_argument(
            "--username",
            type=str,
            default="admin",
            help="Username of the superuser to reset (default: 'admin')",
        )
        parser.add_argument(
            "--password",
            type=str,
            help="New password (if not provided, a random password will be generated)",
        )

    def handle(self, *args, **options):
        username = options["username"]
        password = options.get("password")

        # Find the user
        try:
            user = User.objects.get(username=username)
        except User.DoesNotExist:
            raise CommandError(f"User '{username}' does not exist.")

        if not user.is_superuser:
            raise CommandError(f"User '{username}' is not a superuser.")

        # Generate password if not provided
        password_generated = False
        if not password:
            password = generate_random_password()
            password_generated = True

        # Reset password
        user.set_password(password)
        user.must_change_password = True
        user.save(update_fields=["password", "must_change_password"])

        self.stdout.write("")
        self.stdout.write(self.style.SUCCESS(f"Password for '{username}' has been reset."))
        self.stdout.write("")

        if password_generated:
            self.stdout.write(self.style.WARNING("=" * 60))
            self.stdout.write(self.style.WARNING("  NEW PASSWORD (save this now!)"))
            self.stdout.write(self.style.WARNING("=" * 60))
            self.stdout.write(f"  Username: {username}")
            self.stdout.write(f"  Password: {password}")
            self.stdout.write(self.style.WARNING("=" * 60))
        else:
            self.stdout.write(f"  Username: {username}")
            self.stdout.write("  Password: [as specified]")

        self.stdout.write("")
        self.stdout.write(
            self.style.NOTICE("User will be required to change password on next login.")
        )

        logger.info(
            "Superuser password reset",
            username=username,
            password_generated=password_generated,
            must_change_password=True,
        )
