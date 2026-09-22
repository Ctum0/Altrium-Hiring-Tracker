from django.urls import path

from . import views

app_name = 'accounts'

urlpatterns = [
    path('login/', views.LoginView.as_view(), name='login'),
    path('logout/', views.LogoutView.as_view(), name='logout'),
    path('profile/', views.ProfileUpdateView.as_view(), name='profile'),
    path('', views.HomeView.as_view(), name='home'),
    path('hr-dashboard/', views.HRDashboardView.as_view(), name='hr_dashboard'),
    path('reports/export/', views.ReportExportView.as_view(), name='report_export'),
    path('reports/retention/', views.RetentionReportView.as_view(), name='retention_report'),
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
    path(
        'interviewer/<int:pk>/deactivate/',
        views.DeactivateInterviewerView.as_view(),
        name='deactivate_interviewer',
    ),
    path('onboard/', views.OnboardUserView.as_view(), name='onboard_user'),
    path('my-availability/', views.MyAvailabilityView.as_view(), name='my_availability'),
    path('my-calendar/', views.MyCalendarView.as_view(), name='my_calendar'),
    path(
        'interviewer/<int:pk>/',
        views.InterviewerProfileView.as_view(),
        name='interviewer_profile',
    ),
    path('password-change/', views.PasswordChangeView.as_view(), name='password_change'),
    path('user-admin/', views.AdminUserListView.as_view(), name='admin_users'),
    path('user-admin/create/', views.AdminUserCreateView.as_view(), name='admin_user_create'),
    path(
        'user-admin/<int:pk>/toggle-active/',
        views.AdminUserToggleActiveView.as_view(),
        name='admin_user_toggle_active',
    ),
    path(
        'user-admin/<int:pk>/reset-password/',
        views.AdminUserResetPasswordView.as_view(),
        name='admin_user_reset_password',
    ),
    path(
        'reschedule-requests/',
        views.RescheduleRequestListView.as_view(),
        name='reschedule_requests',
    ),
    path(
        'interview/<int:pk>/reschedule-request/',
        views.RescheduleRequestCreateView.as_view(),
        name='reschedule_request_create',
    ),
]
