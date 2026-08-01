from django.urls import path

from . import views

app_name = 'pipeline'

urlpatterns = [
    path('job/<int:pk>/', views.KanbanBoardView.as_view(), name='board'),
    path('move/<int:pk>/', views.PipelineMoveView.as_view(), name='move'),
]
