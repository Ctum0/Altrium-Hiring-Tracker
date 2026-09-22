from django.contrib import admin

from .models import Notification, OutboundEmail


@admin.register(Notification)
class NotificationAdmin(admin.ModelAdmin):
    list_display = ('recipient', 'message', 'is_read', 'created_at')
    list_filter = ('is_read',)


@admin.register(OutboundEmail)
class OutboundEmailAdmin(admin.ModelAdmin):
    """Read-only audit of system-sent candidate emails."""
    list_display = ('created_at', 'template_name', 'recipient_email', 'candidate', 'success')
    list_filter = ('template_name', 'success')
    search_fields = ('recipient_email', 'candidate__first_name', 'candidate__last_name')
    date_hierarchy = 'created_at'

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False
