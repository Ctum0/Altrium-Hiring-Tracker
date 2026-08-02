from django.urls import path

from . import views

app_name = 'jobs'

urlpatterns = [
    path('', views.JobListView.as_view(), name='list'),
    path('create/', views.JobCreateView.as_view(), name='create'),
    path('<int:pk>/', views.JobDetailView.as_view(), name='detail'),
    path('<int:pk>/edit/', views.JobEditView.as_view(), name='edit'),
    path('<int:pk>/close/', views.JobCloseView.as_view(), name='close'),
    path('<int:job_pk>/rounds/new/', views.RoundCreateView.as_view(), name='round_create'),
    path('rounds/<int:pk>/delete/', views.RoundDeleteView.as_view(), name='round_delete'),
]
