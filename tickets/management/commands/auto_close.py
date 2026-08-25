from django.core.management.base import BaseCommand

from tickets.automation import run_auto_closure, AUTO_CLOSE_HOURS


class Command(BaseCommand):
    help = (
        "Auto-closes tickets that have been in 'resolved' status for more than N hours "
        "(default 48) with no further action, and notifies the requester by email. "
        "Runs automatically every 10 minutes via the background automation engine - "
        "this command lets you trigger it manually."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            '--hours',
            type=int,
            default=AUTO_CLOSE_HOURS,
            help='Hours after resolution before auto-closing (default: 48)',
        )

    def handle(self, *args, **options):
        closed_count = run_auto_closure(hours=options['hours'])
        self.stdout.write(self.style.SUCCESS(
            f"Auto-close complete: {closed_count} ticket(s) closed."
        ))
