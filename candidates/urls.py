from django.urls import path

from . import views

app_name = 'candidates'

urlpatterns = [
    path('', views.CandidateListView.as_view(), name='list'),
    path('upload/', views.CandidateUploadView.as_view(), name='upload'),
    path('apply/<int:job_pk>/', views.PublicApplyView.as_view(), name='public_apply'),
    path(
        'apply/<int:job_pk>/thanks/',
        views.PublicApplyThanksView.as_view(),
        name='public_apply_thanks',
    ),
    path('import/', views.CandidateImportView.as_view(), name='import'),
    path('offboarding/', views.OffboardingCandidatesView.as_view(), name='offboarding'),
    path('<int:pk>/', views.CandidateDetailView.as_view(), name='detail'),
    path('<int:pk>/edit/', views.CandidateEditView.as_view(), name='edit'),
    path('<int:pk>/resume/', views.ResumeDownloadView.as_view(), name='resume'),
    path('<int:pk>/delete/', views.CandidateDeleteView.as_view(), name='delete'),
    path('<int:pk>/review/', views.CandidateReviewView.as_view(), name='review'),
    path('<int:pk>/score/', views.ScoreUpdateView.as_view(), name='score'),
    path('applications/<int:pk>/ai-fit/', views.AiFitSummaryView.as_view(), name='ai_fit'),
    path('applications/<int:pk>/assign/', views.AssignApplicationView.as_view(), name='assign'),
    path('bulk-assign/', views.BulkAssignView.as_view(), name='bulk_assign'),
    path(
        'applications/<int:pk>/interview-details/',
        views.InterviewDetailsView.as_view(),
        name='interview_details',
    ),
    path(
        'applications/<int:pk>/interviewer-slots/',
        views.InterviewerSlotsView.as_view(),
        name='interviewer_slots',
    ),
    path('review-all/', views.BulkMarkReviewedView.as_view(), name='bulk_review'),
]
