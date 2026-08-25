from django.contrib import admin
from .models import Category, Priority, Department, Location, Profile, Ticket, Notification, AuditLog


admin.site.register(Category)
admin.site.register(Priority)
admin.site.register(Department)
admin.site.register(Location)
@admin.register(Profile)
class ProfileAdmin(admin.ModelAdmin):
    list_display = ('user', 'phone_number', 'specialty')
    list_filter = ('specialty',)


@admin.register(Ticket)
class TicketAdmin(admin.ModelAdmin):
    list_display = ('id', 'title', 'category', 'priority', 'status', 'assigned_agent', 'escalation_level', 'created_at')
    list_filter = ('status', 'priority', 'category', 'escalation_level')
    search_fields = ('title', 'description')


@admin.register(Notification)
class NotificationAdmin(admin.ModelAdmin):
    list_display = ('recipient', 'notification_type', 'ticket', 'is_read', 'created_at')
    list_filter = ('notification_type', 'is_read')
    search_fields = ('message',)


@admin.register(AuditLog)
class AuditLogAdmin(admin.ModelAdmin):
    list_display = ('ticket', 'action', 'performed_by', 'created_at')
    list_filter = ('action',)
    search_fields = ('details',)
