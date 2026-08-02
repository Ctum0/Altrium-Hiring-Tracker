from django.urls import path

from . import views

app_name = 'feedback'

urlpatterns = [
    path('', views.FeedbackListView.as_view(), name='list'),
    path('<int:application_pk>/<int:round_pk>/', views.FeedbackFormView.as_view(), name='form'),
    path('<int:pk>/', views.FeedbackDetailView.as_view(), name='detail'),
    path('<int:pk>/history/', views.FeedbackHistoryView.as_view(), name='history'),
    path('ai-polish/', views.AIPolishView.as_view(), name='ai_polish'),
]
