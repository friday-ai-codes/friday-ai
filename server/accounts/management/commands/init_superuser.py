"""Management command to initialize superuser on first startup."""
import os
import secrets
import string
import structlog
from django.core.management.base import BaseCommand
from accounts.models import User, UserSource
logger = structlog.get_logger(__name__)
def generate_random_password(length: int = 16) -> str:
 """Generate a secure random password."""
 alphabet = string.ascii_letters + string.digits + "!@#$%^&*"
 return "".join(secrets.choice(alphabet) for _ in range(length))
class Command(BaseCommand):
 """Initialize superuser if not exists."""
 help = "Create initial superuser if no superuser exists"
 def add_arguments(self, parser):
 parser.add_argument(
 "--username",
 type=str,
 help="Username for the superuser (default: env FRIDAY_ADMIN_USERNAME or 'admin')",
 )
 parser.add_argument(
 "--password",
 type=str,
 help="Password for the superuser (default: env FRIDAY_ADMIN_PASSWORD or auto-generated)",
 )
 def handle(self, *args, **options):
 # Check if any superuser exists
 if User.objects.filter(is_superuser=True).exists:
 self.stdout.write(
 self.style.SUCCESS("Superuser already exists, skipping initialization.")
 )
 return
 # Get configuration from arguments or environment variables
 username = options.get("username") or os.environ.get("FRIDAY_ADMIN_USERNAME", "admin")
 password = options.get("password") or os.environ.get("FRIDAY_ADMIN_PASSWORD")
 # Generate password if not provided
 password_generated = False
 if not password:
 password = generate_random_password
 password_generated = True
 # Create superuser
 user = User.objects.create_superuser(
 username=username,
 password=password,
 display_name="系统管理员",
 source=UserSource.SYSTEM.value,
 )
 # Set must_change_password flag if password was auto-generated
 if password_generated:
 user.must_change_password = True
 user.save(update_fields=["must_change_password"])
 self.stdout.write(self.style.SUCCESS(f"Superuser '{username}' created successfully."))
 if password_generated:
 self.stdout.write("")
 self.stdout.write(self.style.WARNING("=" * 60))
 self.stdout.write(self.style.WARNING(" work item PASSWORD (save this now!)"))
 self.stdout.write(self.style.WARNING("=" * 60))
 self.stdout.write(f" Username: {username}")
 self.stdout.write(f" Password: {password}")
 self.stdout.write(self.style.WARNING("=" * 60))
 self.stdout.write("")
 self.stdout.write(
 self.style.NOTICE("You will be required to change this password on first login.")
 )
 logger.warning(
 "Superuser created with auto-generated password",
 username=username,
 password=password,
 must_change_password=True,
 )
 else:
 logger.info("Superuser created with configured password", username=username)
