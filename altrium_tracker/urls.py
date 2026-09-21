"""URL configuration for altrium_tracker project."""
from django.conf import settings
from django.conf.urls.static import static
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

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
