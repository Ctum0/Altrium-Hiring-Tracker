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
            total_roles = len(context['apps_per_job'])
            pipeline_share_next = 0
            if len(context['apps_per_job']) > 1:
                pipeline_share_next = round(
                    (context['apps_per_job'][1]['count'] / total_apps) * 100
                )
            share_gap = top_pct - pipeline_share_next
            leader_label = 'Leading by {}%'.format(share_gap) if total_roles > 1 else 'Only active role'

            # Pick the matching Job model to compute skill demand
            top_job = None
            try:
                from jobs.models import Job as _Job
                top_job = _Job.objects.filter(title=top_role['title']).first()
            except Exception:
                pass
            skill_tokens = []
            if top_job and top_job.requirements:
                raw_tokens = [t.strip() for t in top_job.requirements.replace(',', ' ').split() if t.strip()]
                seen, deduped = set(), []
                for tk in raw_tokens:
                    key = tk.lower()
                    if key not in seen:
                        seen.add(key)
                        deduped.append(tk)
                skill_tokens = deduped[:3]
            demand_score = min(99, 68 + top_pct + (total_roles * 2))

            if total_roles == 1:
                ai_line = 'Only role with candidates'
                ai_reason = 'All {} apps target this role'.format(total_apps)
            elif share_gap >= 15:
                ai_line = 'Demand outlier — prioritize sourcing'
                ai_reason = '{:.0f}% above next role'.format(share_gap)
            elif top_pct >= 30:
                ai_line = 'Strong concentration in pipeline'
                ai_reason = '{:.0f}% of total; allocate interviews'.format(top_pct)
            else:
                ai_line = 'Balanced demand across roles'
                ai_reason = 'No single role dominates'

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
                    'title': 'Top Role',
                'value': top_role['title'],
                'text': '{} candidate{}'.format(
                    top_role['count'], 's' if top_role['count'] != 1 else ''
                ),
                'count': top_role['count'],
                'pct': top_pct,
                'total': total_apps,
                'rank': role_rank,
                'demand_score': demand_score,
                'leader_label': leader_label,
                'skill_tokens': skill_tokens,
                'ai_line': ai_line,
                'ai_reason': ai_reason,
                'total_roles': total_roles,
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
            # Compute a simple match signal from scoring + distribution
            avg_sc = context.get('avg_score') or 0
            match_score = min(99, max(54, round(0.55 * 94 + 0.45 * float(avg_sc or 60))))
            if match_score >= 85:
                match_band = 'Excellent'
                ai_line_best = 'Strong fit — prioritize interviews'
                ai_reason_best = 'Requirements align with talent'
            elif match_score >= 70:
                match_band = 'Strong'
                ai_line_best = 'Good overlap — prioritize interviews'
                ai_reason_best = 'Core skills present'
            else:
                match_band = 'Moderate'
                ai_line_best = 'Review skills vs requirements'
                ai_reason_best = 'Gaps detected — validate technically'
            best_job = None
            try:
                from jobs.models import Job as _BestJob
                best_job = _BestJob.objects.filter(title=best_role['title']).first()
            except Exception:
                pass
            skill_chips = []
            if best_job and best_job.requirements:
                req_tokens = [t.strip() for t in best_job.requirements.replace(',', ' ').split() if t.strip()]
                seen2, deduped2 = set(), []
                for tk in req_tokens:
                    key = tk.lower()
                    if key not in seen2:
                        seen2.add(key)
                        deduped2.append(tk)
                skill_chips = deduped2[:3]
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
                'match_score': match_score,
                'match_band': match_band,
                'ai_line_best': ai_line_best,
                'ai_reason_best': ai_reason_best,
                'skill_chips': skill_chips,
            })

        active_pct = round((active / total_apps) * 100)
        hold_pct = round((sd.get('on_hold', 0) / total_apps) * 100)
        rej_pct = round((sd.get('rejected', 0) / total_apps) * 100)
        health_score = min(99, max(22, active_pct + (2 if healthy else -8)))
        if health_score >= 75:
            health_label, health_band = 'Healthy', 'strong'
        elif health_score >= 55:
            health_label, health_band = 'Steady', 'ok'
        else:
            health_label, health_band = 'Strained', 'weak'
        # Bottleneck: which non-active stage has most candidates
        stage_scores = [
            ('On hold', sd.get('on_hold', 0), 'pending'),
            ('Rejected', sd.get('rejected', 0), 'danger'),
            ('In progress', sd.get('in_progress', 0), 'violet'),
        ]
        bottleneck = max(stage_scores, key=lambda x: x[1])
        if bottleneck[1] <= 1:
            bottleneck_line = 'No bottleneck — flow balanced'
            bottleneck_reason = '{}% active; healthy distribution'.format(active_pct)
        elif bottleneck[0] == 'On hold':
            bottleneck_line = 'Clear on-hold to restore flow'
            bottleneck_reason = '{} on hold — longest dwell time'.format(bottleneck[1])
        elif bottleneck[0] == 'Rejected':
            bottleneck_line = 'High rejection — review screening'
            bottleneck_reason = '{} rejected; tighten criteria'.format(bottleneck[1])
        else:
            bottleneck_line = '{} holds most — keep moving'.format(bottleneck[0])
            bottleneck_reason = '{} in {}; check SLA'.format(bottleneck[1], bottleneck[0])
        ai_insights.append({
            'id': 'health',
            'icon': 'pulse',
            'accent': 'green' if healthy else 'amber',
            'title': 'Pipeline Health',
            'value': health_label,
            'text': 'Keep up the momentum' if healthy else '{} stuck in on-hold'.format(stuck),
            'active_pct': active_pct,
            'hold_pct': hold_pct,
            'rej_pct': rej_pct,
            'active_count': active,
            'hold_count': sd.get('on_hold', 0),
            'rej_count': sd.get('rejected', 0),
            'stuck_count': stuck,
            'total': total_apps,
            'health_score': health_score,
            'health_band': health_band,
            'bottleneck_label': bottleneck[0],
            'bottleneck_count': bottleneck[1],
            'bottleneck_line': bottleneck_line,
            'bottleneck_reason': bottleneck_reason,
        })

        on_hold_count = sd.get('on_hold', 0)
        risk_pct = round((on_hold_count / total_apps) * 100)
        stale_count = 0
        try:
            from datetime import timedelta
            from django.utils import timezone as _tz
            from candidates.models import JobApplication as _App
            cutoff = _tz.now() - timedelta(days=3)
            stale_count = _App.objects.filter(status='on_hold', updated_at__lt=cutoff).count()
        except Exception:
            pass
        if on_hold_count == 0:
            risk_level, risk_tone = 'Low', 'green'
            risk_ai = 'No stalled candidates'
            risk_reason = '0% on hold'
        elif risk_pct < 25:
            risk_level, risk_tone = 'Watch', 'amber'
            risk_ai = 'Small queue — check in today'
            risk_reason = '{} on hold ({} stale)'.format(on_hold_count, stale_count)
        else:
            risk_level, risk_tone = 'Elevated', 'red'
            risk_ai = '{}% stalled — follow up soon'.format(risk_pct)
            risk_reason = '{} stalled, {} stale'.format(on_hold_count, stale_count)
        ai_insights.append({
            'id': 'risk',
            'icon': 'alert',
            'accent': 'amber' if on_hold_count > 0 else 'blue',
                'title': 'At Risk',
            'value': 'On Hold',
            'text': '{} candidate{} progressing'.format(
                on_hold_count, 's' if on_hold_count != 1 else ''
            ),
            'count': on_hold_count,
            'risk_pct': risk_pct,
            'risk_level': risk_level,
            'risk_tone': risk_tone,
            'risk_ai': risk_ai,
            'risk_reason': risk_reason,
            'stale_count': stale_count,
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
