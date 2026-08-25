"""
Centralized role-based access control for the Help Desk system.

Roles are Django Groups: 'Requesters', 'ICT Agents', 'Administrators'.
Every view that requires a specific role uses one of these decorators
instead of repeating group-membership checks inline, so enforcement is
consistent and auditable in one place.
"""

from functools import wraps

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.shortcuts import redirect


def is_agent(user):
    return user.is_authenticated and user.groups.filter(name='ICT Agents').exists()


def is_admin(user):
    return user.is_authenticated and user.groups.filter(name='Administrators').exists()


def is_requester(user):
    return user.is_authenticated and user.groups.filter(name='Requesters').exists()


def role_required(*role_checks, message="You don't have permission to do that.", redirect_to='my_tickets'):
    """
    Decorator factory: allows the request through if the user satisfies ANY
    of the given role-check predicates (e.g. is_admin, is_agent). Otherwise
    flashes `message` and redirects to `redirect_to`. Always requires login.
    """
    def decorator(view_func):
        @wraps(view_func)
        @login_required
        def wrapped(request, *args, **kwargs):
            if not any(check(request.user) for check in role_checks):
                messages.error(request, message)
                return redirect(redirect_to)
            return view_func(request, *args, **kwargs)
        return wrapped
    return decorator


def requester_required(view_func):
    return role_required(is_requester, message="Only Requesters can submit new tickets.")(view_func)


def admin_required(view_func):
    return role_required(is_admin, message="Only Administrators can view the reporting dashboard.")(view_func)


def agent_or_admin_required(view_func):
    return role_required(is_agent, is_admin, message="Only ICT Agents or Administrators can do that.")(view_func)


def can_view_ticket(user, ticket):
    return is_agent(user) or is_admin(user) or ticket.requester_id == user.id


def require_ticket_access(user, ticket):
    """Raises PermissionDenied (403) if the user has no business viewing this ticket."""
    if not can_view_ticket(user, ticket):
        raise PermissionDenied("You don't have permission to view this ticket.")
