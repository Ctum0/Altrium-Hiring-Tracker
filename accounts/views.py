from django.contrib.auth import views as auth_views
from django.contrib.auth.mixins import LoginRequiredMixin
from django.db.models import Avg, Case, Count, Q, When
from django.shortcuts import redirect
from django.urls import reverse, reverse_lazy
from django.views.generic import ListView, RedirectView, TemplateView

from candidates.models import Candidate, JobApplication
from feedback.models import InterviewFeedback
from jobs.models import Job


class LoginView(auth_views.LoginView):
    template_name = 'accounts/login.html'
    redirect_authenticated_user = True

    def get_success_url(self):
        user = self.request.user
        if user.is_hr():
            return reverse_lazy('accounts:hr_dashboard')
        elif user.is_interviewer():
            return reverse_lazy('accounts:interviewer_dashboard')
        return reverse_lazy('accounts:management_dashboard')


class LogoutView(auth_views.LogoutView):
    pass


class HomeView(TemplateView):
    """Root '/' — redirect based on role."""
    template_name = 'accounts/home.html'

    def dispatch(self, request, *args, **kwargs):
        if not request.user.is_authenticated:
            return redirect(reverse_lazy('accounts:login'))
        if request.user.is_hr():
            return redirect('accounts:hr_dashboard')
        elif request.user.is_interviewer():
            return redirect('accounts:interviewer_dashboard')
        return redirect('accounts:management_dashboard')


class HRDashboardView(LoginRequiredMixin, ListView):
    """HR dashboard — grid of jobs with pipeline metrics."""
    template_name = 'accounts/hr_dashboard.html'
    context_object_name = 'jobs'
    paginate_by = 20

    def get_queryset(self):
        return (
            Job.objects.filter(is_active=True)
            .annotate(app_count=Count('applications'))
            .order_by('-created_at')
        )

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['active_nav'] = 'dashboard'

        # Pipeline stage distribution
        stage_counts = dict(
            JobApplication.objects.values('status')
            .annotate(count=Count('id'))
            .values_list('status', 'count')
        )
        context['stage_distribution'] = [
            {'label': choice[1], 'value': choice[0], 'count': stage_counts.get(choice[0], 0)}
            for choice in JobApplication.Status.choices
        ]
        context['total_applications'] = sum(item['count'] for item in context['stage_distribution'])

        # Score distribution
        scored = Candidate.objects.filter(score__isnull=False)
        score_buckets = [
            ('0-25', Q(score__gte=0, score__lte=25)),
            ('26-50', Q(score__gte=26, score__lte=50)),
            ('51-75', Q(score__gte=51, score__lte=75)),
            ('76-100', Q(score__gte=76, score__lte=100)),
        ]
        total_scored = scored.count()
        context['score_distribution'] = [
            {'label': label, 'count': scored.filter(q).count()}
            for label, q in score_buckets
        ]
        context['scored_count'] = total_scored
        context['avg_score'] = (
            round(scored.aggregate(Avg('score'))['score__avg'], 1)
            if total_scored else None
        )

        # Applications per job (top 6)
        apps_per_job = list(
            Job.objects.filter(is_active=True)
            .annotate(count=Count('applications'))
            .values('title', 'count')
            .order_by('-count')[:6]
        )
        context['apps_per_job'] = apps_per_job
        context['max_apps_per_job'] = apps_per_job[0]['count'] if apps_per_job else 1

        # Feedback status
        apps_in_round = JobApplication.objects.filter(
            current_round__isnull=False,
        ).exclude(status__in=['hired', 'rejected'])
        context['feedback_submitted'] = apps_in_round.filter(
            feedback_submitted=True
        ).count()
        context['feedback_pending'] = apps_in_round.filter(
            feedback_submitted=False
        ).count()
        context['total_feedback'] = (
            context['feedback_submitted'] + context['feedback_pending'] or 1
        )

        # Recent activity: last 8 applications
        context['recent_applications'] = list(
            JobApplication.objects
            .select_related('candidate', 'job')
            .order_by('-updated_at')[:8]
        )

        return context


class InterviewerDashboardView(LoginRequiredMixin, TemplateView):
    """Interviewer dashboard — assigned candidates + feedback needed."""
    template_name = 'accounts/interviewer_dashboard.html'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        user = self.request.user
        assigned_qs = JobApplication.objects.filter(
            assigned_to=user
        ).select_related(
            'candidate', 'job', 'current_round'
        )

        context['assigned_apps'] = assigned_qs.order_by('-updated_at')[:20]
        context['pending_feedback'] = assigned_qs.filter(
            feedback_submitted=False, current_round__isnull=False
        ).count()
        context['active_nav'] = 'dashboard'
        return context


class ManagementDashboardView(LoginRequiredMixin, RedirectView):
    """Management lands on the read-only candidate pipeline on sign-in."""

    permanent = False

    def get_redirect_url(self, *args, **kwargs):
        return reverse('candidates:list')
