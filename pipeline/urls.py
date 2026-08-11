from django.urls import path

from . import views

app_name = 'pipeline'

urlpatterns = [
    path('move/<int:pk>/', views.PipelineMoveView.as_view(), name='move'),
]
