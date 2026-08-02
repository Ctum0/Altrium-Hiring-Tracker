from django.urls import path

from . import views

app_name = 'accounts'

urlpatterns = [
    path('login/', views.LoginView.as_view(), name='login'),
    path('logout/', views.LogoutView.as_view(), name='logout'),
    path('', views.HomeView.as_view(), name='home'),
    path('hr-dashboard/', views.HRDashboardView.as_view(), name='hr_dashboard'),
    path(
        'interviewer-dashboard/',
        views.InterviewerDashboardView.as_view(),
        name='interviewer_dashboard',
    ),
    path('dashboard/', views.ManagementDashboardView.as_view(), name='management_dashboard'),
]
