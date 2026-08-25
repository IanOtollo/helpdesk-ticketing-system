from django.core.management.base import BaseCommand

from tickets.automation import run_auto_escalation


class Command(BaseCommand):
    help = (
        "Checks all open/in-progress tickets for SLA breaches. Escalates overdue tickets "
        "(Level 1: reassigns to an Administrator) and flags severely overdue tickets "
        "(Level 2: urgent email to all Administrators). Runs automatically every 10 minutes "
        "via the background automation engine - this command lets you trigger it manually."
    )

    def handle(self, *args, **options):
        escalated_l1, escalated_l2 = run_auto_escalation()
        self.stdout.write(self.style.SUCCESS(
            f"Escalation complete: {escalated_l1} ticket(s) escalated to Level 1, "
            f"{escalated_l2} ticket(s) raised to Level 2 (urgent)."
        ))
