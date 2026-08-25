from django.core.validators import FileExtensionValidator
from django.db import models
from django.contrib.auth.models import User

IMAGE_EXTENSIONS = ['jpg', 'jpeg', 'png', 'gif', 'webp', 'bmp']


class Category(models.Model):
    name = models.CharField(max_length=100, unique=True)
    default_priority = models.ForeignKey(
        'Priority', on_delete=models.SET_NULL, null=True, blank=True,
        help_text="Priority automatically assigned to tickets in this category"
    )

    def __str__(self):
        return self.name

    class Meta:
        verbose_name_plural = "Categories"


class Priority(models.Model):
    name = models.CharField(max_length=50, unique=True)
    escalation_hours = models.PositiveIntegerField(
        help_text="Hours before a ticket at this priority is flagged as overdue"
    )

    def __str__(self):
        return self.name

    class Meta:
        verbose_name_plural = "Priorities"


class Department(models.Model):
    name = models.CharField(max_length=100, unique=True)

    def __str__(self):
        return self.name


class Location(models.Model):
    name = models.CharField(max_length=150, unique=True)

    def __str__(self):
        return self.name


class Profile(models.Model):
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name='profile')
    phone_number = models.CharField(max_length=20, blank=True)
    specialty = models.ForeignKey(
        Category, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='specialist_agents',
        help_text="For ICT Agents: the issue category this agent specializes in. "
                   "Auto-assignment prefers a matching specialist before falling back "
                   "to the least-loaded agent overall.",
    )

    def __str__(self):
        return f"{self.user.username} profile"


class Ticket(models.Model):
    STATUS_CHOICES = [
        ('open', 'Open'),
        ('in_progress', 'In Progress'),
        ('resolved', 'Resolved'),
        ('closed', 'Closed'),
    ]

    title = models.CharField(max_length=200)
    description = models.TextField()
    category = models.ForeignKey(Category, on_delete=models.SET_NULL, null=True)
    priority = models.ForeignKey(Priority, on_delete=models.SET_NULL, null=True)
    department = models.ForeignKey(Department, on_delete=models.SET_NULL, null=True)
    location = models.ForeignKey(Location, on_delete=models.SET_NULL, null=True, blank=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='open')
    contact_phone = models.CharField(max_length=20)
    attachment = models.FileField(
        upload_to='ticket_attachments/', blank=True, null=True,
        validators=[FileExtensionValidator(allowed_extensions=IMAGE_EXTENSIONS)],
    )

    requester = models.ForeignKey(
        User, on_delete=models.CASCADE, related_name='tickets_submitted'
    )
    assigned_agent = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='tickets_assigned'
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    resolved_at = models.DateTimeField(null=True, blank=True)

    def __str__(self):
        return f"#{self.id} - {self.title}"

    escalation_level = models.PositiveIntegerField(default=0)

    def is_overdue(self):
        if self.status in ('resolved', 'closed'):
            return False
        if not self.priority:
            return False
        from django.utils import timezone
        from datetime import timedelta
        deadline = self.created_at + timedelta(hours=self.priority.escalation_hours)
        return timezone.now() > deadline

    def is_severely_overdue(self):
        """True once a ticket has been open for 2x its SLA window (Level 2 escalation trigger)."""
        if self.status in ('resolved', 'closed'):
            return False
        if not self.priority:
            return False
        from django.utils import timezone
        from datetime import timedelta
        deadline = self.created_at + timedelta(hours=self.priority.escalation_hours * 2)
        return timezone.now() > deadline


class AuditLog(models.Model):
    ACTION_CHOICES = [
        ('created', 'Ticket Created'),
        ('auto_priority_set', 'Auto-Priority Set'),
        ('auto_assigned', 'Auto-Assigned'),
        ('manually_assigned', 'Manually Assigned'),
        ('reassigned', 'Reassigned'),
        ('status_changed', 'Status Changed'),
        ('sla_warning', 'SLA Warning Sent'),
        ('escalated', 'Escalated'),
        ('escalated_level2', 'Escalated (Urgent — Level 2)'),
        ('auto_closed', 'Auto-Closed'),
    ]

    ticket = models.ForeignKey(Ticket, on_delete=models.CASCADE, related_name='audit_logs')
    action = models.CharField(max_length=30, choices=ACTION_CHOICES)
    performed_by = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True,
        help_text="Null means the action was performed by SYSTEM automation"
    )
    details = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        who = self.performed_by.username if self.performed_by else 'SYSTEM'
        return f"[Ticket #{self.ticket_id}] {self.get_action_display()} by {who}"


class Notification(models.Model):
    NOTIFICATION_TYPES = [
        ('ticket_created', 'New Ticket Created'),
        ('ticket_assigned', 'Ticket Assigned'),
        ('ticket_resolved', 'Ticket Resolved'),
        ('ticket_overdue', 'Ticket Overdue'),
        ('ticket_escalated', 'Ticket Escalated'),
        ('ticket_auto_closed', 'Ticket Auto-Closed'),
    ]

    recipient = models.ForeignKey(
        User, on_delete=models.CASCADE, related_name='notifications'
    )
    ticket = models.ForeignKey(
        'Ticket', on_delete=models.CASCADE, related_name='notifications'
    )
    notification_type = models.CharField(max_length=30, choices=NOTIFICATION_TYPES)
    message = models.TextField()
    is_read = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.notification_type} → {self.recipient.username}"