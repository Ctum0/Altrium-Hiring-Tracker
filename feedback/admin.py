from django.contrib import admin

from .models import FeedbackEditHistory, InterviewFeedback


class FeedbackEditHistoryInline(admin.TabularInline):
    model = FeedbackEditHistory
    extra = 0
    readonly_fields = ('old_score', 'old_notes', 'edited_at', 'edited_by')
    can_delete = False


@admin.register(InterviewFeedback)
class InterviewFeedbackAdmin(admin.ModelAdmin):
    list_display = (
        'candidate_name', 'job_title', 'round_name', 'score',
        'interviewer', 'submitted_at',
    )
    list_filter = ('round__job', 'round', 'submitted_at')
    inlines = [FeedbackEditHistoryInline]

    def candidate_name(self, obj):
        return obj.application.candidate.full_name

    def job_title(self, obj):
        return obj.application.job.title

    def round_name(self, obj):
        return obj.round.name
