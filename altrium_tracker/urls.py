"""URL configuration for altrium_tracker project."""
from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.urls import include, path

urlpatterns = [
    path('admin/', admin.site.urls),
    path('', include('accounts.urls')),
    path('jobs/', include('jobs.urls')),
    path('candidates/', include('candidates.urls')),
    path('notifications/', include('notifications.urls')),
    path('pipeline/', include('pipeline.urls')),
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
