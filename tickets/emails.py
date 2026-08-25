"""
Centralized email notifications for the Help Desk Ticketing System.

Every ticket lifecycle event that should reach a human by email goes through
this module. The requester should never need to log in to know what is
happening with their ticket — every state change reaches them by email.

All sends are best-effort: a failed email (e.g. no SMTP configured, no
recipient email on file) is logged and swallowed so it never crashes a
request or the background automation loop.
"""

import logging

from django.conf import settings
from django.core.mail import EmailMessage, get_connection

logger = logging.getLogger(__name__)


def _send(subject, message, recipient_list):
    """
    Send via the configured backend (Gmail SMTP). If that fails for any reason
    — most commonly no internet connection — fall back to the console backend
    so the email still prints to the terminal instead of being lost. This keeps
    the system fully usable offline: automation, tickets, and the dashboard
    never depend on real network access, only real delivery does.
    """
    recipient_list = [r for r in recipient_list if r]
    if not recipient_list:
        return

    email = EmailMessage(
        subject=subject,
        body=message,
        from_email=settings.DEFAULT_FROM_EMAIL,
        to=recipient_list,
    )
    try:
        email.send(fail_silently=False)
    except Exception as e:
        logger.warning(
            "Email send failed (%s) to %s: %s -- falling back to console output",
            subject, recipient_list, e,
        )
        try:
            console_connection = get_connection('django.core.mail.backends.console.EmailBackend')
            email.connection = console_connection
            email.send(fail_silently=True)
        except Exception as e2:
            logger.error("Console fallback also failed (%s): %s", subject, e2)


def _agent_name(user):
    return user.get_full_name() or user.username


def _agent_phone(agent):
    profile = getattr(agent, 'profile', None)
    return profile.phone_number if profile else 'not on file'


# ── Sent to the assigned agent / admins when a ticket is created ──

def send_ticket_assigned_agent_email(ticket, agent):
    subject = f'[Help Desk] Ticket #{ticket.id} assigned to you: {ticket.title}'
    message = (
        f'A new ticket has been automatically assigned to you.\n\n'
        f'Ticket #{ticket.id}: {ticket.title}\n'
        f'Category: {ticket.category}\n'
        f'Priority: {ticket.priority}\n'
        f'Requester: {_agent_name(ticket.requester)}\n'
        f'Requester phone: {ticket.contact_phone}\n'
        f'Location: {ticket.location or "Not specified"}\n'
        f'Department: {ticket.department or "Not specified"}\n\n'
        f'Description:\n{ticket.description}\n'
    )
    _send(subject, message, [agent.email])


def send_new_ticket_admin_email(ticket, admin):
    subject = f'[Help Desk] New ticket #{ticket.id}: {ticket.title}'
    message = (
        f'A new ticket was submitted and auto-assigned by the system.\n\n'
        f'Ticket #{ticket.id}: {ticket.title}\n'
        f'Category: {ticket.category}\n'
        f'Priority: {ticket.priority}\n'
        f'Requester: {_agent_name(ticket.requester)}\n'
        f'Assigned agent: {ticket.assigned_agent or "Unassigned"}\n'
    )
    _send(subject, message, [admin.email])


# ── Sent to the requester (never needs to log in) ──

def send_ticket_received_requester_email(ticket):
    subject = f'[Help Desk] Ticket #{ticket.id} received'
    sla = f'{ticket.priority.escalation_hours} hours' if ticket.priority else 'to be determined'
    message = (
        f'Your ticket has been received.\n\n'
        f'Ticket #{ticket.id}: {ticket.title}\n'
        f'Assigned to: {ticket.assigned_agent or "being assigned"}\n'
        f'Expected resolution: {sla}\n\n'
        f'We will email you as this ticket progresses.'
    )
    _send(subject, message, [ticket.requester.email])


def send_ticket_assigned_requester_email(ticket, agent):
    subject = f'[Help Desk] Ticket #{ticket.id} assigned to an agent'
    message = (
        f'Your ticket #{ticket.id} "{ticket.title}" has been assigned to '
        f'{_agent_name(agent)} ({_agent_phone(agent)}).'
    )
    _send(subject, message, [ticket.requester.email])


def send_ticket_resolved_requester_email(ticket):
    subject = f'[Help Desk] Ticket #{ticket.id} resolved'
    agent_name = _agent_name(ticket.assigned_agent) if ticket.assigned_agent else 'an ICT agent'
    message = (
        f'Your ticket #{ticket.id} "{ticket.title}" has been resolved by {agent_name}.\n\n'
        f'If the issue persists, please submit a new ticket.'
    )
    _send(subject, message, [ticket.requester.email])


def send_ticket_escalated_requester_email(ticket):
    subject = f'[Help Desk] Ticket #{ticket.id} escalated'
    message = (
        f'Your ticket #{ticket.id} "{ticket.title}" has been escalated to management '
        f'for faster resolution.'
    )
    _send(subject, message, [ticket.requester.email])


def send_ticket_auto_closed_requester_email(ticket):
    subject = f'[Help Desk] Ticket #{ticket.id} closed'
    message = (
        f'Your ticket #{ticket.id} "{ticket.title}" has been automatically closed '
        f'after being resolved for 48 hours with no further action.'
    )
    _send(subject, message, [ticket.requester.email])


# ── SLA warning to the assigned agent ──

def send_sla_warning_email(ticket):
    subject = f'[Help Desk] SLA WARNING: Ticket #{ticket.id} approaching deadline'
    message = (
        f'Ticket #{ticket.id} "{ticket.title}" is approaching its SLA deadline '
        f'({ticket.priority.name} — {ticket.priority.escalation_hours}hrs). '
        f'Please resolve promptly.'
    )
    _send(subject, message, [ticket.assigned_agent.email] if ticket.assigned_agent else [])


# ── Escalation (Level 1: reassigned to an Administrator) ──

def send_escalation_admin_email(ticket, admin):
    subject = f'[Help Desk] ESCALATED: Ticket #{ticket.id} breached SLA'
    message = (
        f'Ticket #{ticket.id} "{ticket.title}" has breached its SLA '
        f'({ticket.priority.name if ticket.priority else "N/A"}) and has been '
        f'automatically escalated to you.'
    )
    _send(subject, message, [admin.email])


def send_escalation_old_agent_email(ticket, old_agent):
    subject = f'[Help Desk] Ticket #{ticket.id} escalated away from you'
    message = (
        f'Ticket #{ticket.id} "{ticket.title}" was overdue and has been escalated '
        f'away from you to an Administrator.'
    )
    _send(subject, message, [old_agent.email])


# ── Escalation Level 2: still unresolved after 2x SLA — urgent, all admins ──

def send_escalation_level2_admin_email(ticket, admin):
    subject = f'[Help Desk] URGENT: Ticket #{ticket.id} still unresolved (2x SLA breached)'
    message = (
        f'URGENT — Ticket #{ticket.id} "{ticket.title}" has been open for more than '
        f'twice its SLA window ({ticket.priority.name if ticket.priority else "N/A"}) '
        f'and still has not been resolved. Immediate attention required.'
    )
    _send(subject, message, [admin.email])


# ── Manual reassignment by an admin ──

def send_reassignment_agent_email(ticket, agent):
    subject = f'[Help Desk] Ticket #{ticket.id} reassigned to you'
    message = (
        f'Ticket #{ticket.id} "{ticket.title}" has been manually reassigned to you.\n\n'
        f'Requester: {_agent_name(ticket.requester)}\n'
        f'Requester phone: {ticket.contact_phone}\n'
        f'Priority: {ticket.priority}\n'
    )
    _send(subject, message, [agent.email])
