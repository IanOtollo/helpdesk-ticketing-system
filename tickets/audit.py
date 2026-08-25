"""Single entry point for writing AuditLog entries so every ticket action
is recorded the same way, whether triggered by a human or SYSTEM automation."""

from .models import AuditLog


def log_action(ticket, action, performed_by=None, details=''):
    AuditLog.objects.create(
        ticket=ticket,
        action=action,
        performed_by=performed_by,
        details=details,
    )
