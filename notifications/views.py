from django.contrib.auth.mixins import LoginRequiredMixin
from django.http import HttpResponse
from django.views import View
from django.views.generic import ListView

from .models import Notification


class NotificationListView(LoginRequiredMixin, ListView):
    template_name = 'notifications/notification_list.html'
    context_object_name = 'notifications'
    paginate_by = 30

    def paginate_queryset(self, queryset, page_size):
        """Clamp out-of-range pages instead of 404ing."""
        try:
            return super().paginate_queryset(queryset, page_size)
        except Exception:
            self.kwargs['page'] = 'last'
            return super().paginate_queryset(queryset, page_size)

    def get_queryset(self):
        qs = Notification.objects.filter(recipient=self.request.user)
        if self.request.GET.get('unread') == '1':
            qs = qs.filter(is_read=False)
        return qs

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['active_nav'] = 'notifications'
        return context


class UnreadCountView(LoginRequiredMixin, View):
    """HTMX endpoint: returns just the unread count for the bell badge."""

    def get(self, request):
        count = Notification.objects.filter(recipient=request.user, is_read=False).count()
        return HttpResponse(str(count))


class MarkReadView(LoginRequiredMixin, View):
    """HTMX endpoint: mark a single notification as read."""

    def post(self, request, pk):
        notification = Notification.objects.filter(pk=pk, recipient=request.user).first()
        if notification:
            notification.mark_read()
        return HttpResponse(status=204)
