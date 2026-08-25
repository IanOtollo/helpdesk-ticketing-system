from django.db.models.signals import m2m_changed, post_save
from django.contrib.auth.models import User, Group
from django.dispatch import receiver

from . import emails
from .audit import log_action
from .models import Ticket, Notification


@receiver(m2m_changed, sender=User.groups.through)
def sync_admin_staff_status(sender, instance, action, **kwargs):
    if action in ('post_add', 'post_remove', 'post_clear'):
        is_admin_group_member = instance.groups.filter(name='Administrators').exists()
        if instance.is_staff != is_admin_group_member:
            instance.is_staff = is_admin_group_member
            instance.save()


@receiver(post_save, sender=Ticket)
def auto_assign_and_notify(sender, instance, created, **kwargs):
    """
    On ticket creation (fully automatic, no human intervention):
    1. Auto-set priority from category's default_priority (rule-based, not requester-chosen).
    2. Auto-assign to the ICT Agent with the fewest open tickets (least-loaded balancing).
    3. Auto-set status to 'in_progress' (no manual claim step needed).
    4. Notify the assigned agent, all Administrators, and the requester (in-app + email).
    5. Record every step in the audit trail.
    """
    if not created:
        return

    log_action(instance, 'created', performed_by=instance.requester, details='Ticket submitted by requester.')

    updates = {}

    # ── AUTO-PRIORITY: derive from category rules, not requester input ──
    if instance.category and instance.category.default_priority:
        updates['priority_id'] = instance.category.default_priority_id

    # ── AUTO-ASSIGNMENT: least-loaded agent, preferring a category specialist ──
    agents = User.objects.filter(groups__name='ICT Agents')
    best_agent = None
    lowest_count = None
    matched_specialist = False

    candidate_pool = agents
    if instance.category:
        specialists = agents.filter(profile__specialty=instance.category)
        if specialists.exists():
            candidate_pool = specialists
            matched_specialist = True

    if agents.exists():
        for agent in candidate_pool:
            open_count = Ticket.objects.filter(
                assigned_agent=agent
            ).exclude(
                status__in=['resolved', 'closed']
            ).count()
            if lowest_count is None or open_count < lowest_count:
                lowest_count = open_count
                best_agent = agent

    if best_agent:
        updates['assigned_agent_id'] = best_agent.id
        updates['status'] = 'in_progress'

    # Apply all updates in one query (avoids re-triggering post_save)
    if updates:
        Ticket.objects.filter(pk=instance.pk).update(**updates)
        instance.refresh_from_db()

    if 'priority_id' in updates:
        log_action(
            instance, 'auto_priority_set', performed_by=None,
            details=f'SYSTEM set priority to {instance.priority} based on category {instance.category}.',
        )

    # ── NOTIFICATIONS (in-app + email) ──
    if best_agent:
        specialist_note = ' — matched by specialty' if matched_specialist else ''
        log_action(
            instance, 'auto_assigned', performed_by=None,
            details=(
                f'SYSTEM auto-assigned to {best_agent.username} '
                f'(workload: {lowest_count} open tickets{specialist_note}).'
            ),
        )
        Notification.objects.create(
            recipient=best_agent,
            ticket=instance,
            notification_type='ticket_assigned',
            message=f'Ticket #{instance.id} "{instance.title}" has been automatically assigned to you.',
        )
        emails.send_ticket_assigned_agent_email(instance, best_agent)
        emails.send_ticket_assigned_requester_email(instance, best_agent)

    admins = User.objects.filter(groups__name='Administrators')
    for admin_user in admins:
        Notification.objects.create(
            recipient=admin_user,
            ticket=instance,
            notification_type='ticket_created',
            message=f'New ticket #{instance.id} "{instance.title}" submitted by {instance.requester.username}.',
        )
        emails.send_new_ticket_admin_email(instance, admin_user)

    emails.send_ticket_received_requester_email(instance)
