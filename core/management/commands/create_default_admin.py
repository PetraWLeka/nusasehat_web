"""
Management command: create_default_admin
Creates the default admin user (admin/admin123).
"""

from django.core.management.base import BaseCommand

from core.models import User


class Command(BaseCommand):
    help = "Create default admin user for initial setup"

    def handle(self, *args, **options):
        if User.objects.filter(username="admin").exists():
            self.stdout.write(self.style.WARNING("Admin user already exists."))
            return

        user = User.objects.create_superuser(
            username="admin",
            email="admin@nusahealth.local",
            password="admin123",
            role="admin",
            must_change_password=False,
            full_name="Administrator",
        )
        self.stdout.write(
            self.style.SUCCESS(
                f"Default admin created: {user.username}"
            )
        )
