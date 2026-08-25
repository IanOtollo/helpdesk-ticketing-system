import csv
from django import forms
from django.core.exceptions import PermissionDenied
from django.db.models import Q
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.models import User, Group
from django.contrib.auth.forms import UserCreationForm
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.http import HttpResponse
from django.utils import timezone

from . import emails
from .audit import log_action
from .decorators import (
    is_agent, is_admin,
    requester_required, admin_required,
    require_ticket_access,
)
from .models import AuditLog, Ticket, Category, Priority, Department, Location, Profile, Notification


class RequesterRegistrationForm(UserCreationForm):
    email = forms.EmailField(required=True, help_text="We'll use this to send you ticket updates.")

    class Meta(UserCreationForm.Meta):
        model = User
        fields = ('username', 'email')

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['username'].help_text = 'Letters, numbers and @/./+/-/_ only.'
        self.fields['password1'].help_text = 'At least 8 characters. Avoid common or all-numeric passwords.'
        self.fields['password2'].help_text = ''


def register(request):
    if request.method != 'POST':
        form = RequesterRegistrationForm()
        return render(request, 'tickets/register.html', {'form': form})

    form = RequesterRegistrationForm(request.POST)
    if form.is_valid():
        user = form.save()
        requesters_group = Group.objects.get(name='Requesters')
        user.groups.add(requesters_group)
        messages.success(request, 'Account created successfully. You can now log in.')
        return redirect('login')

    return render(request, 'tickets/register.html', {'form': form})


@requester_required
def create_ticket(request):
    if request.method != 'POST':
        categories = Category.objects.all()
        departments = Department.objects.all()
        locations = Location.objects.all()
        return render(request, 'tickets/create_ticket.html', {
            'categories': categories,
            'departments': departments,
            'locations': locations,
        })

    title = request.POST.get('title')
    description = request.POST.get('description')
    category_id = request.POST.get('category')
    department_id = request.POST.get('department')
    location_id = request.POST.get('location')
    contact_phone = request.POST.get('contact_phone')
    attachment = request.FILES.get('attachment')

    if attachment and not attachment.content_type.startswith('image/'):
        messages.error(request, 'Only image attachments are allowed.')
        return redirect('create_ticket')

    # Priority is NOT set here — it's automatically determined from the
    # category's default_priority via the post_save signal in signals.py.
    # This is a deliberate automation: requesters describe the problem,
    # the system determines urgency based on predefined rules.
    Ticket.objects.create(
        title=title,
        description=description,
        category_id=category_id,
        department_id=department_id,
        location_id=location_id,
        contact_phone=contact_phone,
        attachment=attachment,
        requester=request.user,
    )

    messages.success(request, 'Ticket submitted successfully.')
    return redirect('my_tickets')


@login_required
def home(request):
    """Post-login landing: send Administrators to the reporting dashboard,
    everyone else to their ticket list."""
    if is_admin(request.user):
        return redirect('dashboard')
    return redirect('my_tickets')


@login_required
def my_tickets(request):
    filter_param = request.GET.get('filter')
    unassigned_qs = Ticket.objects.filter(
        assigned_agent__isnull=True
    ).exclude(status__in=['resolved', 'closed'])

    if is_admin(request.user):
        if filter_param == 'mine':
            tickets = Ticket.objects.filter(assigned_agent=request.user).order_by('-created_at')
        elif filter_param == 'unassigned':
            tickets = unassigned_qs.order_by('-created_at')
        else:
            tickets = Ticket.objects.all().order_by('-created_at')
        unassigned_count = unassigned_qs.count()

    elif is_agent(request.user):
        if filter_param == 'mine':
            tickets = Ticket.objects.filter(assigned_agent=request.user).order_by('-created_at')
        elif filter_param == 'unassigned':
            tickets = unassigned_qs.order_by('-created_at')
        else:
            tickets = Ticket.objects.filter(
                Q(assigned_agent=request.user) | Q(id__in=unassigned_qs)
            ).order_by('-created_at')
        unassigned_count = unassigned_qs.count()

    else:
        tickets = Ticket.objects.filter(requester=request.user).order_by('-created_at')
        unassigned_count = None
        filter_param = None

    return render(request, 'tickets/my_tickets.html', {
        'tickets': tickets,
        'unassigned_count': unassigned_count,
        'filter_param': filter_param,
        'is_admin_user': is_admin(request.user),
        'is_agent_user': is_agent(request.user),
    })


@login_required
def notifications_view(request):
    """Show all notifications for the logged-in user, mark them read on visit."""
    user_notifications = Notification.objects.filter(recipient=request.user).order_by('-created_at')[:50]

    # Mark all as read
    Notification.objects.filter(recipient=request.user, is_read=False).update(is_read=True)

    return render(request, 'tickets/notifications.html', {
        'notifications': user_notifications,
    })


@admin_required
def dashboard(request):
    all_tickets = Ticket.objects.select_related('category', 'location', 'assigned_agent').all()
    total_tickets = all_tickets.count()

    overdue_tickets = [t for t in all_tickets if t.is_overdue()]
    overdue_count = len(overdue_tickets)

    overdue_by_category = {}
    for t in overdue_tickets:
        name = t.category.name if t.category else 'Uncategorized'
        overdue_by_category[name] = overdue_by_category.get(name, 0) + 1
    overdue_by_category = sorted(overdue_by_category.items(), key=lambda x: -x[1])
    overdue_labels = [x[0] for x in overdue_by_category]
    overdue_data = [x[1] for x in overdue_by_category]

    category_totals = {}
    for t in all_tickets:
        cat = t.category.name if t.category else 'Uncategorized'
        category_totals[cat] = category_totals.get(cat, 0) + 1
    category_pie_labels = list(category_totals.keys())
    category_pie_data = list(category_totals.values())

    location_data = {}
    for t in all_tickets:
        loc = t.location.name if t.location else 'Not specified'
        cat = t.category.name if t.category else 'Uncategorized'
        location_data.setdefault(loc, {})
        location_data[loc][cat] = location_data[loc].get(cat, 0) + 1

    location_breakdown = []
    for loc, cats in location_data.items():
        total = sum(cats.values())
        top_category = max(cats.items(), key=lambda x: x[1])
        location_breakdown.append({
            'location': loc, 'total': total,
            'top_category': top_category[0], 'top_category_count': top_category[1],
        })
    location_breakdown.sort(key=lambda x: -x['total'])
    location_labels = [row['location'] for row in location_breakdown]
    location_totals = [row['total'] for row in location_breakdown]

    agent_stats = []
    for agent in User.objects.filter(groups__name='ICT Agents'):
        assigned = all_tickets.filter(assigned_agent=agent).count()
        resolved = all_tickets.filter(assigned_agent=agent, status__in=['resolved', 'closed']).count()
        agent_stats.append({'agent': agent.username, 'assigned': assigned, 'resolved': resolved})
    agent_stats.sort(key=lambda x: -x['resolved'])
    agent_labels = [row['agent'] for row in agent_stats]
    agent_assigned = [row['assigned'] for row in agent_stats]
    agent_resolved = [row['resolved'] for row in agent_stats]

    resolved_tickets = all_tickets.filter(resolved_at__isnull=False)
    if resolved_tickets.exists():
        total_seconds = sum((t.resolved_at - t.created_at).total_seconds() for t in resolved_tickets)
        avg_hours = round((total_seconds / resolved_tickets.count()) / 3600, 1)
    else:
        avg_hours = None

    # Automation stats for the dashboard
    escalated_count = all_tickets.filter(escalation_level__gte=1).count()
    escalated_l2_count = all_tickets.filter(escalation_level__gte=2).count()
    auto_assigned_count = all_tickets.exclude(assigned_agent__isnull=True).count()
    auto_closed_count = AuditLog.objects.filter(action='auto_closed').values('ticket').distinct().count()

    recent_audit_logs = AuditLog.objects.select_related('ticket', 'performed_by').all()[:15]

    return render(request, 'tickets/dashboard.html', {
        'total_tickets': total_tickets,
        'overdue_count': overdue_count,
        'overdue_by_category': overdue_by_category,
        'location_breakdown': location_breakdown,
        'agent_stats': agent_stats,
        'avg_hours': avg_hours,
        'overdue_labels': overdue_labels,
        'overdue_data': overdue_data,
        'category_pie_labels': category_pie_labels,
        'category_pie_data': category_pie_data,
        'location_labels': location_labels,
        'location_totals': location_totals,
        'agent_labels': agent_labels,
        'agent_assigned': agent_assigned,
        'agent_resolved': agent_resolved,
        'escalated_count': escalated_count,
        'escalated_l2_count': escalated_l2_count,
        'auto_assigned_count': auto_assigned_count,
        'auto_closed_count': auto_closed_count,
        'recent_audit_logs': recent_audit_logs,
    })


@admin_required
def dashboard_export(request):
    response = HttpResponse(content_type='text/csv')
    response['Content-Disposition'] = 'attachment; filename="ticket_export.csv"'

    writer = csv.writer(response)
    writer.writerow([
        'ID', 'Title', 'Category', 'Priority', 'Department', 'Location',
        'Status', 'Overdue', 'Escalation Level', 'Requester', 'Contact Phone',
        'Assigned Agent', 'Created At', 'Resolved At',
    ])

    for t in Ticket.objects.select_related(
        'category', 'priority', 'department', 'location', 'requester', 'assigned_agent'
    ).all():
        writer.writerow([
            t.id, t.title,
            t.category.name if t.category else '',
            t.priority.name if t.priority else '',
            t.department.name if t.department else '',
            t.location.name if t.location else '',
            t.status, 'Yes' if t.is_overdue() else 'No',
            t.escalation_level,
            t.requester.username, t.contact_phone,
            t.assigned_agent.username if t.assigned_agent else '',
            t.created_at, t.resolved_at or '',
        ])

    return response


ROLE_GROUPS = ['Requesters', 'ICT Agents', 'Administrators']


@admin_required
def manage_users(request):
    if request.method == 'POST':
        target_user = get_object_or_404(User, id=request.POST.get('user_id'))
        new_role = request.POST.get('role')

        if target_user == request.user:
            messages.error(request, "You can't change your own role.")
            return redirect('manage_users')

        if new_role not in ROLE_GROUPS:
            messages.error(request, 'Invalid role selected.')
            return redirect('manage_users')

        for group_name in ROLE_GROUPS:
            group = Group.objects.get(name=group_name)
            if group_name == new_role:
                target_user.groups.add(group)
            else:
                target_user.groups.remove(group)

        if new_role == 'ICT Agents':
            specialty_id = request.POST.get('specialty') or None
            profile, _ = Profile.objects.get_or_create(user=target_user)
            profile.specialty_id = specialty_id
            profile.save()
            messages.success(request, f'{target_user.username} is now an ICT Agent.')
        else:
            messages.success(request, f'{target_user.username} is now a {new_role[:-1]}.')

        return redirect('manage_users')

    users = User.objects.filter(is_superuser=False).select_related('profile').order_by('username')
    user_rows = []
    for u in users:
        if is_admin(u):
            role = 'Administrators'
        elif is_agent(u):
            role = 'ICT Agents'
        else:
            role = 'Requesters'
        user_rows.append({
            'user': u,
            'role': role,
            'specialty': getattr(getattr(u, 'profile', None), 'specialty', None),
        })

    return render(request, 'tickets/manage_users.html', {
        'user_rows': user_rows,
        'categories': Category.objects.all(),
    })


@login_required
def ticket_detail(request, ticket_id):
    ticket = get_object_or_404(Ticket, id=ticket_id)
    require_ticket_access(request.user, ticket)

    if request.method == 'POST':
        if not (is_agent(request.user) or is_admin(request.user)):
            raise PermissionDenied("Only ICT Agents or Administrators can act on tickets.")

        action = request.POST.get('action')

        if action == 'assign_to_me':
            ticket.assigned_agent = request.user
            ticket.save()
            log_action(
                ticket, 'manually_assigned', performed_by=request.user,
                details=f'{request.user.username} assigned this ticket to themselves.',
            )
            messages.success(request, 'Ticket assigned to you.')

        elif action == 'assign_to_agent':
            if not is_admin(request.user):
                raise PermissionDenied("Only Administrators can reassign tickets.")

            agent_id = request.POST.get('agent_id')
            agent = User.objects.filter(id=agent_id, groups__name='ICT Agents').first()
            if not agent:
                messages.error(request, 'Invalid agent selected.')
                return redirect('ticket_detail', ticket_id=ticket.id)

            old_agent = ticket.assigned_agent
            ticket.assigned_agent = agent
            ticket.save()
            log_action(
                ticket, 'reassigned', performed_by=request.user,
                details=(
                    f'{request.user.username} reassigned from '
                    f'{old_agent.username if old_agent else "unassigned"} to {agent.username}.'
                ),
            )
            emails.send_reassignment_agent_email(ticket, agent)
            messages.success(request, 'Ticket reassigned.')

        elif action == 'update_status':
            new_status = request.POST.get('status')
            valid_statuses = dict(Ticket.STATUS_CHOICES)
            if new_status not in valid_statuses:
                messages.error(request, 'Invalid status.')
                return redirect('ticket_detail', ticket_id=ticket.id)

            old_status = ticket.status
            ticket.status = new_status
            if new_status == 'resolved':
                ticket.resolved_at = timezone.now()
            ticket.save()

            log_action(
                ticket, 'status_changed', performed_by=request.user,
                details=f'{request.user.username} changed status from {old_status} to {new_status}.',
            )

            # Notify requester when their ticket is resolved
            if new_status == 'resolved' and old_status != 'resolved':
                Notification.objects.create(
                    recipient=ticket.requester,
                    ticket=ticket,
                    notification_type='ticket_resolved',
                    message=(
                        f'Your ticket #{ticket.id} "{ticket.title}" has been resolved '
                        f'by {request.user.username}.'
                    ),
                )
                emails.send_ticket_resolved_requester_email(ticket)

            messages.success(request, 'Ticket status updated.')

        return redirect('ticket_detail', ticket_id=ticket.id)

    agent_phone = None
    if ticket.assigned_agent:
        profile = Profile.objects.filter(user=ticket.assigned_agent).first()
        if profile:
            agent_phone = profile.phone_number

    audit_logs = ticket.audit_logs.select_related('performed_by').all()

    return render(request, 'tickets/ticket_detail.html', {
        'ticket': ticket,
        'is_agent_or_admin': is_agent(request.user) or is_admin(request.user),
        'is_admin_user': is_admin(request.user),
        'agents': User.objects.filter(groups__name='ICT Agents') if is_admin(request.user) else None,
        'agent_phone': agent_phone,
        'audit_logs': audit_logs,
    })
