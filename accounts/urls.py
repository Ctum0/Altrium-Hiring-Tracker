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
    path(
        'interviewer-roster/',
        views.InterviewerRosterView.as_view(),
        name='interviewer_roster',
    ),
    path('dashboard/', views.ManagementDashboardView.as_view(), name='management_dashboard'),
    path('interviewer/<int:pk>/deactivate/', views.DeactivateInterviewerView.as_view(), name='deactivate_interviewer'),
    path('onboard/', views.OnboardUserView.as_view(), name='onboard_user'),
    path('my-availability/', views.MyAvailabilityView.as_view(), name='my_availability'),
    path('my-calendar/', views.MyCalendarView.as_view(), name='my_calendar'),
    path('interviewer/<int:pk>/', views.InterviewerProfileView.as_view(), name='interviewer_profile'),
]
