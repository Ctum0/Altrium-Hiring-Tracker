from django.contrib import admin

from .models import PipelineMove


@admin.register(PipelineMove)
class PipelineMoveAdmin(admin.ModelAdmin):
    list_display = ('application', 'from_round', 'to_round', 'moved_by', 'moved_at')
    list_filter = ('moved_at',)
