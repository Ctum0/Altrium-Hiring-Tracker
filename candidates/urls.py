from django.urls import path

from . import views

app_name = 'candidates'

urlpatterns = [
    path('', views.CandidateListView.as_view(), name='list'),
    path('upload/', views.CandidateUploadView.as_view(), name='upload'),
    path('import/', views.CandidateImportView.as_view(), name='import'),
    path('<int:pk>/', views.CandidateDetailView.as_view(), name='detail'),
    path('<int:pk>/score/', views.ScoreUpdateView.as_view(), name='score'),
    path('applications/<int:pk>/assign/', views.AssignApplicationView.as_view(), name='assign'),
]
