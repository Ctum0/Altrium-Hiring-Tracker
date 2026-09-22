from django.contrib import admin
from django.contrib.auth.admin import UserAdmin

from .models import AuditLog, User


@admin.register(User)
class CustomUserAdmin(UserAdmin):
    fieldsets = UserAdmin.fieldsets + (
        ('Role', {'fields': ('role', 'specialty', 'seniority', 'domain', 'photo')}),
        ('Security', {'fields': ('force_password_change',)}),
    )
    list_display = ('username', 'email', 'role', 'seniority', 'domain', 'is_active', 'force_password_change')
    list_filter = ('role', 'seniority', 'domain', 'is_active', 'force_password_change')


@admin.register(AuditLog)
class AuditLogAdmin(admin.ModelAdmin):
    """Read-only audit trail: entries are append-only, never edited."""
    list_display = ('created_at', 'actor', 'action', 'object_type', 'object_id')
    list_filter = ('action',)
    search_fields = ('actor__username', 'object_type', 'object_id', 'detail')
    date_hierarchy = 'created_at'
    readonly_fields = ('actor', 'action', 'object_type', 'object_id', 'detail', 'created_at')

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
