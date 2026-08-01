from django.contrib import admin

from .models import InterviewRound, Job


class InterviewRoundInline(admin.TabularInline):
    model = InterviewRound
    extra = 1


@admin.register(Job)
class JobAdmin(admin.ModelAdmin):
    list_display = ('title', 'is_active', 'hiring_manager', 'created_by', 'created_at')
    list_filter = ('is_active',)
    inlines = [InterviewRoundInline]
