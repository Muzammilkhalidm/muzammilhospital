from django.contrib.auth.models import User
from django.core.management.base import BaseCommand

from hospital.models import AdminProfile


class Command(BaseCommand):
    help = "Create the main admin account (muzammil) if it does not exist."

    def handle(self, *args, **options):
        username, password = "muzammil", "Muzammil@2026!"
        user = User.objects.filter(username=username).first()
        if user is None:
            user = User.objects.create_superuser(username=username, email="admin@example.com", password=password,
                                                 first_name="Muzammil", last_name="Khalid")
            self.stdout.write(self.style.SUCCESS("Main admin created."))
        else:
            self.stdout.write(self.style.WARNING("Admin 'muzammil' already exists. Password not changed."))
        AdminProfile.objects.get_or_create(user=user)
        self.stdout.write("Sign in at http://127.0.0.1:8000/login/")
        self.stdout.write(f"Username: {username}")
        self.stdout.write(f"Password: {password}  (change it after first login: Profile > Change password)")
