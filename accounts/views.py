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

        # AI Insights — compact insight panels (not KPI cards).
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

            # Sparkline: candidate availability trend (simulated from score distribution)
            scored_buckets = context.get('score_distribution', [])
            spark_vals = [b['count'] for b in scored_buckets[:5]] or [0, 0, 0, 0, 0]
            spark_max = max(spark_vals) or 1
            spark_pct = [round(v * 100 / spark_max) for v in spark_vals]

            # AI finding text
            if total_roles == 1:
                ai_finding = 'Only role with candidates'
                ai_evidence = 'All {} apps target this role'.format(total_apps)
                ai_action = 'Open more requisitions'
            elif share_gap >= 15:
                ai_finding = 'Demand outlier — highest concentration'
                ai_evidence = '{:.0f}% above next role'.format(share_gap)
                ai_action = 'Prioritize screening here'
            elif top_pct >= 30:
                ai_finding = 'Strong concentration in pipeline'
                ai_evidence = '{:.0f}% of total candidates'.format(top_pct)
                ai_action = 'Allocate interview capacity'
            else:
                ai_finding = 'Balanced demand across roles'
                ai_evidence = 'No single role dominates'
                ai_action = 'Keep the funnel wide'

            role_rank = [
                {
                    'label': job['title'],
                    'count': job['count'],
                    'pct': max(8, round(job['count'] * 100 / max_role)),
                }
                for idx, job in enumerate(context['apps_per_job'][:3])
            ]
            ai_insights.append({
                'id': 'top_role',
                'category': 'Hiring Demand',
                'finding': top_role['title'],
                'score': demand_score,
                'score_label': 'Demand',
                'evidence': ai_evidence,
                'action': ai_action,
                'action_accent': 'blue',
                'sparkline': spark_pct,
                'skills': skill_tokens,
                'rank': role_rank,
                'count': top_role['count'],
                'pct': top_pct,
                'total': total_apps,
            })

        if context['top_positions']:
            top_title = context['apps_per_job'][0]['title'] if context['apps_per_job'] else None
            best_role = context['top_positions'][0]
            for idx, candidate in enumerate(context['top_positions']):
                if candidate['title'] != top_title:
                    best_role = candidate
                    break
            best_pct = round((best_role['app_count'] / total_apps) * 100)
            avg_sc = context.get('avg_score') or 0
            match_score = min(99, max(54, round(0.55 * 94 + 0.45 * float(avg_sc or 60))))
            if match_score >= 85:
                match_band = 'Excellent'
                ai_finding_best = 'Strong alignment — prioritize interviews'
                ai_action_best = 'Move to interview stage'
            elif match_score >= 70:
                match_band = 'Strong'
                ai_finding_best = 'Good overlap — core skills match'
                ai_action_best = 'Screen for edge requirements'
            else:
                match_band = 'Moderate'
                ai_finding_best = 'Partial match — gaps detected'
                ai_action_best = 'Validate with technical screen'

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

            # Simulated skill factors from requirements
            skill_factors = []
            if skill_chips:
                for i, sk in enumerate(skill_chips[:3]):
                    skill_factors.append({'skill': sk, 'pct': max(50, 95 - i * 15)})

            ai_insights.append({
                'id': 'best_fit',
                'category': 'AI Matching',
                'finding': best_role['title'],
                'score': match_score,
                'score_label': 'Match',
                'evidence': ai_finding_best,
                'action': ai_action_best,
                'action_accent': 'violet',
                'skill_factors': skill_factors,
                'count': best_role['app_count'],
                'match_band': match_band,
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

        # Stage flow: compute which stage is the bottleneck
        stage_flow = []
        for s in context['stage_distribution']:
            if s['count'] > 0:
                stage_flow.append({'label': s['label'], 'count': s['count'], 'value': s['value']})
        bottleneck_stage = max(stage_flow, key=lambda x: x['count']) if stage_flow else None

        if health_score >= 75:
            ai_finding_health = 'Strong pipeline velocity'
            ai_evidence_health = '{}% active, healthy distribution'.format(active_pct)
        elif health_score >= 55:
            ai_finding_health = 'Moderate flow — some friction'
            ai_evidence_health = '{} on hold, {} rejected'.format(
                sd.get('on_hold', 0), sd.get('rejected', 0))
        else:
            ai_finding_health = 'Pipeline needs attention'
            ai_evidence_health = '{}% stuck in non-active stages'.format(round(stuck * 100 / total_apps))

        ai_insights.append({
            'id': 'health',
            'category': 'Pipeline Intelligence',
            'score': health_score,
            'score_label': 'Health',
            'status': health_label,
            'status_band': health_band,
            'finding': ai_finding_health,
            'evidence': ai_evidence_health,
            'stage_flow': stage_flow,
            'bottleneck': bottleneck_stage['label'] if bottleneck_stage else None,
            'active_pct': active_pct,
            'hold_pct': hold_pct,
            'rej_pct': rej_pct,
            'active_count': active,
            'hold_count': sd.get('on_hold', 0),
            'rej_count': sd.get('rejected', 0),
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
            ai_finding_risk = 'No stalled candidates'
            ai_evidence_risk = 'Pipeline is stable'
            ai_action_risk = 'Continue current workflow'
        elif risk_pct < 25:
            risk_level, risk_tone = 'Watch', 'amber'
            ai_finding_risk = '{} candidates stalled'.format(on_hold_count)
            ai_evidence_risk = '{} inactive 3+ days'.format(stale_count) if stale_count else 'Recently paused'
            ai_action_risk = 'Follow up within 48h'
        else:
            risk_level, risk_tone = 'Elevated', 'red'
            ai_finding_risk = '{}% stalled — action needed'.format(risk_pct)
            ai_evidence_risk = '{} stalled, {} stale'.format(on_hold_count, stale_count)
            ai_action_risk = 'Unblock immediately'

        ai_insights.append({
            'id': 'risk',
            'category': 'Risk Monitor',
            'risk_level': risk_level,
            'risk_tone': risk_tone,
            'finding': ai_finding_risk,
            'evidence': ai_evidence_risk,
            'action': ai_action_risk,
            'inactive_count': on_hold_count,
            'stale_count': stale_count,
            'risk_pct': risk_pct,
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
