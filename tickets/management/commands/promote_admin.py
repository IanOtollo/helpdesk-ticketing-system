from django.contrib.auth.models import User, Group
from django.core.management.base import BaseCommand, CommandError


class Command(BaseCommand):
    help = "Adds an existing user to the Administrators group (grants dashboard access)."

    def add_arguments(self, parser):
        parser.add_argument('username', type=str)

    def handle(self, *args, **options):
        username = options['username']
        try:
            user = User.objects.get(username=username)
        except User.DoesNotExist:
            raise CommandError(f'No such user: {username}')

        group, _ = Group.objects.get_or_create(name='Administrators')
        user.groups.add(group)
        self.stdout.write(self.style.SUCCESS(
            f'{username} added to Administrators group.'
        ))
