from .decorators import is_admin, is_agent
from .models import Notification


def notification_count(request):
    """Injects unread notification count and RBAC role info into every template context."""
    if not request.user.is_authenticated:
        return {
            'unread_notification_count': 0,
            'nav_is_admin': False,
            'nav_is_agent': False,
            'nav_role_label': None,
        }

    count = Notification.objects.filter(
        recipient=request.user, is_read=False
    ).count()

    if is_admin(request.user):
        role_label = 'Administrator'
    elif is_agent(request.user):
        role_label = 'ICT Agent'
    else:
        role_label = 'Requester'

    return {
        'unread_notification_count': count,
        'nav_is_admin': is_admin(request.user),
        'nav_is_agent': is_agent(request.user),
        'nav_role_label': role_label,
    }
