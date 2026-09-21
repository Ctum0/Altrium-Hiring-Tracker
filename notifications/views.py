from itertools import groupby

from django.contrib.auth.mixins import LoginRequiredMixin
from django.http import HttpResponse
from django.shortcuts import redirect, render
from django.utils import timezone
from django.views import View
from django.views.generic import ListView

from .models import Notification


class NotificationListView(LoginRequiredMixin, ListView):
    template_name = 'notifications/notification_list.html'
    context_object_name = 'notifications'
    paginate_by = 30

    def get_template_names(self):
        if self.request.GET.get('popover') == '1':
            return ['notifications/_notification_popover.html']
        return [self.template_name]

    def paginate_queryset(self, queryset, page_size):
        """Clamp out-of-range pages instead of 404ing."""
        from django.core.paginator import EmptyPage, PageNotAnInteger
        try:
            return super().paginate_queryset(queryset, page_size)
        except (PageNotAnInteger, EmptyPage):
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
        # Basic date grouping (Today / Yesterday / older dates) for the
        # current page's notifications. No new model field: grouped from
        # the existing created_at timestamp only.
        today = timezone.localdate()
        yesterday = today - timezone.timedelta(days=1)
        groups = []
        for day, items in groupby(
            context['notifications'],
            key=lambda n: timezone.localtime(n.created_at).date(),
        ):
            if day == today:
                label = 'Today'
            elif day == yesterday:
                label = 'Yesterday'
            else:
                label = day.strftime('%B %d, %Y')
            groups.append({'label': label, 'items': list(items)})
        context['notification_groups'] = groups
        context['unread_on_page'] = sum(
            1 for n in context['notifications'] if not n.is_read
        )
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
            return render(request, 'notifications/_notification_row.html', {
                'n': notification,
            })
        return HttpResponse(status=204)


class MarkAllReadView(LoginRequiredMixin, View):
    """Mark every unread notification for the current user as read."""

    def post(self, request):
        Notification.objects.filter(
            recipient=request.user, is_read=False,
        ).update(is_read=True)
        return redirect('notifications:list')


class MarkPageReadView(LoginRequiredMixin, View):
    """Mark the unread notifications currently shown on one list page as
    read. Triage-sized alternative to mark-all: page through the backlog
    and clear what you've seen without nuking the rest."""

    def post(self, request):
        pks = request.POST.get('pks', '')
        # Only integers, comma-separated; ignore anything else.
        ids = [p.strip() for p in pks.split(',') if p.strip().isdigit()]
        if ids:
            Notification.objects.filter(
                recipient=request.user, is_read=False, pk__in=ids,
            ).update(is_read=True)
        return redirect(request.POST.get('next') or 'notifications:list')
