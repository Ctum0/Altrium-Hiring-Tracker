"""URL configuration for altrium_tracker project."""
from django.conf import settings
from django.contrib import admin
from django.urls import include, path
from django.views.generic import RedirectView

from candidates.views import PublicJobsListView

urlpatterns = [
    path('admin/', admin.site.urls),
    # GAP-009: browsers request /favicon.ico regardless of <link rel="icon">
    # tags; redirect to the hashed static asset so every page load is 200.
    path(
        'favicon.ico',
        RedirectView.as_view(url='/static/favicon.ico', permanent=True),
    ),
    path('careers/', PublicJobsListView.as_view(), name='careers'),
    path('', include('accounts.urls')),
    path('jobs/', include('jobs.urls')),
    path('candidates/', include('candidates.urls')),
    path('notifications/', include('notifications.urls')),
    path('pipeline/', include('pipeline.urls')),
    path('feedback/', include('feedback.urls')),
]

if settings.DEBUG and not getattr(settings, 'STORAGES', {}).get('default', {}).get(
    'BACKEND', ''
).endswith('s3boto3.S3Boto3Storage'):
    # Local dev only: serve CVs through an authenticated, role-checked view.
    # Production uses the private S3 bucket with presigned URLs (settings.py).
    # The old static() route served every CV to anonymous clients
    # (audit SEC-MEDIA-001, critical).
    from candidates.media_views import ProtectedMediaView
    urlpatterns += [
        path('media/<path:path>', ProtectedMediaView.as_view()),
    ]
