from django.contrib import admin

from .models import Candidate, JobApplication


@admin.register(Candidate)
class CandidateAdmin(admin.ModelAdmin):
    list_display = ('full_name', 'email', 'score', 'source', 'created_at')
    list_filter = ('source',)
    search_fields = ('first_name', 'last_name', 'email', 'skills')


@admin.register(JobApplication)
class JobApplicationAdmin(admin.ModelAdmin):
    list_display = ('candidate', 'job', 'status', 'current_round', 'assigned_to', 'created_at')
    list_filter = ('status', 'job')
    autocomplete_fields = ('candidate',)
