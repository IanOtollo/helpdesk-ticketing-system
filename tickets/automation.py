"""
Background automation engine for the Help Desk Ticketing System.

Starts automatically when Django launches. Runs a check loop every 10 minutes:
  1. SLA Warning — tickets at 80%+ of their SLA window get a warning notification + email
  2. Auto-Escalation (Level 1) — overdue tickets get reassigned to an Administrator
  3. Auto-Escalation (Level 2) — tickets still unresolved after 2x SLA get an urgent
     email to every Administrator
  4. Auto-Closure — resolved tickets untouched for 48 hours get closed automatically

Every step writes an AuditLog entry and sends the relevant emails. The same
functions back the `auto_escalate` / `auto_close` management commands so
there is exactly one implementation of each rule.

No manual commands required. No cron. No Task Scheduler. Fully self-contained.
"""

import threading
import logging
from datetime import timedelta

from django.utils import timezone
from django.contrib.auth.models import User

from . import emails
from .audit import log_action

logger = logging.getLogger(__name__)

# How often the automation loop runs (in seconds)
CHECK_INTERVAL = 600  # 10 minutes

# Hours after resolution before auto-closing
AUTO_CLOSE_HOURS = 48


def run_sla_warning_check():
    """Tickets past 80% of their SLA window but not yet overdue get a one-time warning."""
    from .models import Ticket, Notification

    now = timezone.now()
    warned = 0

    active_tickets = Ticket.objects.filter(
        status__in=['open', 'in_progress'],
        priority__isnull=False,
    ).select_related('priority', 'assigned_agent')

    for ticket in active_tickets:
        if not ticket.priority or not ticket.priority.escalation_hours:
            continue

        deadline = ticket.created_at + timedelta(hours=ticket.priority.escalation_hours)
        warning_threshold = ticket.created_at + timedelta(
            hours=ticket.priority.escalation_hours * 0.8
        )

        if not (warning_threshold <= now < deadline):
            continue

        already_warned = Notification.objects.filter(
            ticket=ticket,
            notification_type='ticket_overdue',
            message__icontains='approaching SLA',
        ).exists()

        if already_warned or not ticket.assigned_agent:
            continue

        Notification.objects.create(
            recipient=ticket.assigned_agent,
            ticket=ticket,
            notification_type='ticket_overdue',
            message=(
                f'WARNING: Ticket #{ticket.id} "{ticket.title}" is approaching its '
                f'SLA deadline ({ticket.priority.name} — {ticket.priority.escalation_hours}hrs). '
                f'Please resolve promptly.'
            ),
        )
        log_action(
            ticket, 'sla_warning', performed_by=None,
            details=f'SYSTEM sent SLA warning to {ticket.assigned_agent.username}. Deadline: {deadline}.',
        )
        emails.send_sla_warning_email(ticket)
        warned += 1

    return warned


def run_auto_escalation():
    """
    Level 1: first SLA breach — reassign from agent to an Administrator.
    Level 2: still unresolved after 2x the SLA window — urgent email to all Administrators.
    """
    from .models import Ticket, Notification

    admin_user = User.objects.filter(groups__name='Administrators').first()
    all_admins = list(User.objects.filter(groups__name='Administrators'))

    if not admin_user:
        return 0, 0

    active_tickets = Ticket.objects.filter(
        status__in=['open', 'in_progress']
    ).select_related('priority', 'assigned_agent', 'category')

    escalated_l1 = 0
    escalated_l2 = 0

    for ticket in active_tickets:
        if ticket.escalation_level < 1 and ticket.is_overdue():
            old_agent = ticket.assigned_agent

            ticket.assigned_agent = admin_user
            ticket.escalation_level = 1
            ticket.save()

            log_action(
                ticket, 'escalated', performed_by=None,
                details=(
                    f'SYSTEM escalated to {admin_user.username}. '
                    f'Previous agent: {old_agent.username if old_agent else "none"}. '
                    f'SLA breached: {ticket.priority.name if ticket.priority else "N/A"}.'
                ),
            )

            Notification.objects.create(
                recipient=admin_user,
                ticket=ticket,
                notification_type='ticket_escalated',
                message=(
                    f'ESCALATED: Ticket #{ticket.id} "{ticket.title}" has breached its SLA '
                    f'({ticket.priority.name if ticket.priority else "N/A"}) and has been '
                    f'automatically escalated to you.'
                ),
            )
            emails.send_escalation_admin_email(ticket, admin_user)

            if old_agent and old_agent != admin_user:
                Notification.objects.create(
                    recipient=old_agent,
                    ticket=ticket,
                    notification_type='ticket_escalated',
                    message=(
                        f'Ticket #{ticket.id} "{ticket.title}" was overdue and has been '
                        f'escalated away from you to an Administrator.'
                    ),
                )
                emails.send_escalation_old_agent_email(ticket, old_agent)

            emails.send_ticket_escalated_requester_email(ticket)
            escalated_l1 += 1

        elif ticket.escalation_level < 2 and ticket.is_severely_overdue():
            ticket.escalation_level = 2
            ticket.save()

            log_action(
                ticket, 'escalated_level2', performed_by=None,
                details=(
                    f'SYSTEM raised Ticket #{ticket.id} to Level 2 (urgent) — unresolved after '
                    f'2x SLA window ({ticket.priority.name if ticket.priority else "N/A"}). '
                    f'All Administrators notified.'
                ),
            )

            for admin in all_admins:
                Notification.objects.create(
                    recipient=admin,
                    ticket=ticket,
                    notification_type='ticket_escalated',
                    message=(
                        f'URGENT: Ticket #{ticket.id} "{ticket.title}" is still unresolved after '
                        f'2x its SLA window.'
                    ),
                )
                emails.send_escalation_level2_admin_email(ticket, admin)

            escalated_l2 += 1

    return escalated_l1, escalated_l2


def run_auto_closure(hours=AUTO_CLOSE_HOURS):
    """Resolved tickets untouched for `hours` get closed automatically."""
    from .models import Ticket, Notification

    cutoff = timezone.now() - timedelta(hours=hours)
    stale_resolved = Ticket.objects.filter(
        status='resolved',
        resolved_at__isnull=False,
        resolved_at__lte=cutoff,
    ).select_related('requester')

    closed = 0
    for ticket in stale_resolved:
        ticket.status = 'closed'
        ticket.save()

        log_action(
            ticket, 'auto_closed', performed_by=None,
            details=f'SYSTEM auto-closed after {hours} hours in resolved status.',
        )

        Notification.objects.create(
            recipient=ticket.requester,
            ticket=ticket,
            notification_type='ticket_auto_closed',
            message=(
                f'Ticket #{ticket.id} "{ticket.title}" has been automatically closed '
                f'after being resolved for {hours} hours with no further action.'
            ),
        )
        emails.send_ticket_auto_closed_requester_email(ticket)
        closed += 1

    return closed


def _run_automation_cycle():
    """Single cycle of all automation checks."""
    now = timezone.now()

    warned = run_sla_warning_check()
    escalated_l1, escalated_l2 = run_auto_escalation()
    closed = run_auto_closure()

    logger.info(
        "Automation cycle complete at %s - warned: %d, escalated L1: %d, escalated L2: %d, closed: %d",
        now.strftime('%H:%M:%S'), warned, escalated_l1, escalated_l2, closed,
    )


def _automation_loop():
    """Runs the automation cycle, then reschedules itself."""
    try:
        _run_automation_cycle()
    except Exception as e:
        logger.error(f"Automation cycle error: {e}")

    # Schedule next run
    timer = threading.Timer(CHECK_INTERVAL, _automation_loop)
    timer.daemon = True  # Dies when Django stops — no zombie threads
    timer.start()


def start_automation():
    """Called once from AppConfig.ready(). Kicks off the background loop."""
    # Delay first run by 30 seconds to let Django fully initialize
    timer = threading.Timer(30, _automation_loop)
    timer.daemon = True
    timer.start()
    logger.info("Help Desk automation engine started (interval: %ds)", CHECK_INTERVAL)
