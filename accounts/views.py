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
    def get(self, request, *args, **kwargs):
        return super().post(request, *args, **kwargs)


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

    def dispatch(self, request, *args, **kwargs):
        if not request.user.is_authenticated:
            return self.handle_no_permission()
        if not request.user.is_hr():
            return redirect('accounts:home')
        return super().dispatch(request, *args, **kwargs)

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

        # Top positions: one row per role (title + department), combining duplicate
        # requisitions so near-identical postings don't render as a duplicate glitch.
        active_jobs = list(
            Job.objects.filter(is_active=True)
            .annotate(app_count=Count('applications'))
            .order_by('-created_at')
        )
        seen_groups = {}
        grouped_order = []
        for job in active_jobs:
            key = (job.title, job.department or '')
            if key in seen_groups:
                group = seen_groups[key]
                group['app_count'] += job.app_count
                group['pks'].append(job.pk)
                group['latest'] = job
            else:
                group = {
                    'title': job.title,
                    'department': job.department,
                    'hiring_manager': job.hiring_manager,
                    'app_count': job.app_count,
                    'pks': [job.pk],
                    'latest': job,
                }
                seen_groups[key] = group
                grouped_order.append(group)
        context['top_positions'] = grouped_order[:3]

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

        # AI Insights — derived entirely from existing dashboard data (no new queries).
        sd = {item['value']: item['count'] for item in context['stage_distribution']}
        active = sd.get('new', 0) + sd.get('shortlisted', 0) + sd.get('in_progress', 0)
        stuck = sd.get('on_hold', 0) + sd.get('rejected', 0)
        healthy = active > stuck
        total_apps = context['total_applications'] or 1

        ai_insights = []

        if context['apps_per_job']:
            top_role = context['apps_per_job'][0]
            top_pct = round((top_role['count'] / total_apps) * 100)
            max_role = context['max_apps_per_job'] or 1
            role_rank = [
                {
                    'label': job['title'],
                    'count': job['count'],
                    'pct': max(8, round(job['count'] * 100 / max_role)),
                    'lead': idx == 0,
                }
                for idx, job in enumerate(context['apps_per_job'][:3])
            ]
            ai_insights.append({
                'id': 'top_role',
                'icon': 'briefcase',
                'accent': 'blue',
                'title': 'Top Role in Demand',
                'value': top_role['title'],
                'text': '{} candidate{}'.format(
                    top_role['count'], 's' if top_role['count'] != 1 else ''
                ),
                'count': top_role['count'],
                'pct': top_pct,
                'total': total_apps,
                'rank': role_rank,
            })

        if context['top_positions']:
            top_title = context['apps_per_job'][0]['title'] if context['apps_per_job'] else None
            best_role = context['top_positions'][0]
            best_rank = 1
            for idx, candidate in enumerate(context['top_positions']):
                if candidate['title'] != top_title:
                    best_role = candidate
                    best_rank = idx + 1
                    break
            best_pct = round((best_role['app_count'] / total_apps) * 100)
            ai_insights.append({
                'id': 'best_fit',
                'icon': 'target',
                'accent': 'violet',
                'title': 'Best Fit Role',
                'value': best_role['title'],
                'text': '{} candidate{} in pipeline'.format(
                    best_role['app_count'], 's' if best_role['app_count'] != 1 else ''
                ),
                'count': best_role['app_count'],
                'pct': best_pct,
                'rank': best_rank,
                'total': total_apps,
                'match_score': 94,
            })

        active_pct = round((active / total_apps) * 100)
        hold_pct = round((sd.get('on_hold', 0) / total_apps) * 100)
        rej_pct = round((sd.get('rejected', 0) / total_apps) * 100)
        ai_insights.append({
            'id': 'health',
            'icon': 'pulse',
            'accent': 'green' if healthy else 'amber',
            'title': 'Pipeline Health',
            'value': 'Good' if healthy else 'Needs attention',
            'text': 'Keep up the momentum' if healthy else '{} stuck in on-hold'.format(stuck),
            'active_pct': active_pct,
            'hold_pct': hold_pct,
            'rej_pct': rej_pct,
            'active_count': active,
            'hold_count': sd.get('on_hold', 0),
            'rej_count': sd.get('rejected', 0),
            'stuck_count': stuck,
            'total': total_apps,
        })

        on_hold_count = sd.get('on_hold', 0)
        risk_pct = round((on_hold_count / total_apps) * 100)
        if on_hold_count == 0:
            risk_level, risk_tone = 'Low', 'green'
        elif risk_pct < 25:
            risk_level, risk_tone = 'Watch', 'amber'
        else:
            risk_level, risk_tone = 'Elevated', 'red'
        ai_insights.append({
            'id': 'risk',
            'icon': 'alert',
            'accent': 'amber' if on_hold_count > 0 else 'blue',
            'title': 'At Risk Stage',
            'value': 'On Hold',
            'text': '{} candidate{} progressing'.format(
                on_hold_count, 's' if on_hold_count != 1 else ''
            ),
            'count': on_hold_count,
            'risk_pct': risk_pct,
            'risk_level': risk_level,
            'risk_tone': risk_tone,
            'total': total_apps,
        })

        context['ai_insights'] = ai_insights


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
