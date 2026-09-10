from django.contrib.auth import get_user_model
from django.contrib.auth import views as auth_views
from django.contrib.auth.mixins import LoginRequiredMixin
from django.db.models import Avg, Count, Q
from django.shortcuts import redirect
from django.urls import reverse, reverse_lazy
from django.utils import timezone
from django.views.generic import ListView, RedirectView, TemplateView, View

from accounts.models import Role
from candidates.models import Candidate, JobApplication
from jobs.models import Job
from pipeline.models import PipelineMove

User = get_user_model()


class LoginView(auth_views.LoginView):
    template_name = 'accounts/login.html'
    redirect_authenticated_user = True

    def get_success_url(self):
        user = self.request.user
        if user.is_hr() or user.is_management():
            return reverse_lazy('accounts:hr_dashboard')
        elif user.is_interviewer():
            return reverse_lazy('accounts:interviewer_dashboard')
        return reverse_lazy('accounts:hr_dashboard')


class LogoutView(auth_views.LogoutView):
    def get(self, request, *args, **kwargs):
        return super().post(request, *args, **kwargs)


class HomeView(TemplateView):
    """Root '/' — redirect based on role."""
    template_name = 'accounts/home.html'

    def dispatch(self, request, *args, **kwargs):
        if not request.user.is_authenticated:
            return redirect(reverse_lazy('accounts:login'))
        if request.user.is_hr() or request.user.is_management():
            return redirect('accounts:hr_dashboard')
        elif request.user.is_interviewer():
            return redirect('accounts:interviewer_dashboard')
        return redirect('accounts:hr_dashboard')


class HRDashboardView(LoginRequiredMixin, ListView):
    """HR and Management dashboard — grid of jobs with pipeline metrics."""
    template_name = 'accounts/hr_dashboard.html'
    context_object_name = 'jobs'
    paginate_by = 20

    def dispatch(self, request, *args, **kwargs):
        if not request.user.is_authenticated:
            return self.handle_no_permission()
        if not (request.user.is_hr() or request.user.is_management()):
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
        context['active_job_count'] = Job.objects.filter(is_active=True).count()
        context['needs_review_count'] = Candidate.objects.filter(needs_review=True).count()

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

        # AI Insights — compact AI analysis panels (not KPI cards).
        sd = {item['value']: item['count'] for item in context['stage_distribution']}
        active = sd.get('new', 0) + sd.get('shortlisted', 0) + sd.get('in_progress', 0)
        total_apps = context['total_applications'] or 1

        ai_insights = []

        # --- Card 1: TOP ROLE IN DEMAND ---
        if context['apps_per_job']:
            top_role = context['apps_per_job'][0]
            max_role = context['max_apps_per_job'] or 1

            top_job = Job.objects.filter(title=top_role['title']).first()
            skill_tokens = []
            if top_job and top_job.requirements:
                raw_tokens = [
                    t.strip() for t in top_job.requirements.replace(',', ' ').split() if t.strip()
                ]
                seen, deduped = set(), []
                for tk in raw_tokens:
                    key = tk.lower()
                    if key not in seen:
                        seen.add(key)
                        deduped.append(tk)
                skill_tokens = deduped[:3]

            ai_finding_demand = 'Highest candidate availability among active roles'
            ai_action_demand = 'Prioritize screening'

            # Candidate-list link target: every active job whose title matches
            top_role_pks = list(
                Job.objects.filter(is_active=True, title=top_role['title'])
                .values_list('pk', flat=True)
            )
            role_distribution = []
            for job in context['apps_per_job'][:2]:
                role_distribution.append({
                    'label': job['title'],
                    'count': job['count'],
                    'pct': round(job['count'] * 100 / max_role),
                })
            other_count = sum(j['count'] for j in context['apps_per_job'][2:])
            if other_count > 0:
                role_distribution.append({
                    'label': 'Other roles',
                    'count': other_count,
                    'pct': round(other_count * 100 / max_role),
                })

            ai_insights.append({
                'id': 'top_role',
                'category': 'Hiring Demand',
                'icon': '🔥',
                'finding': top_role['title'],
                'ai_finding': ai_finding_demand,
                'skills': skill_tokens,
                'job_pks': ','.join(str(pk) for pk in top_role_pks),
                'distribution': role_distribution,
                'recommendation': ai_action_demand,
                'action_accent': 'blue',
            })

        # --- Card 2: CANDIDATE SKILLS (top role) ---
        if context['top_positions']:
            top_title = context['apps_per_job'][0]['title'] if context['apps_per_job'] else None
            best_role = context['top_positions'][0]
            for candidate in context['top_positions']:
                if candidate['title'] != top_title:
                    best_role = candidate
                    break

            # Real skill frequency among candidates of this role. No fake
            # match percentages: when there is no data, render an honest
            # empty state in the template.
            from collections import Counter
            cand_qs = Candidate.objects.filter(
                applications__job__title=best_role['title'])
            all_skills = [
                s.strip() for c in cand_qs
                for s in (c.skills or '').split(',') if s.strip()
            ]
            counts = Counter(all_skills)
            skill_factors = []
            if counts:
                for skill, count in counts.most_common(3):
                    skill_factors.append({
                        'skill': skill,
                        'count': count,
                    })

            ai_insights.append({
                'id': 'best_fit',
                'category': 'Candidate Matching',
                'icon': '🎯',
                'finding': best_role['title'],
                'skill_factors': skill_factors,
                'job_pks': ','.join(str(pk) for pk in best_role['pks']),
                'reason': 'Most common skills among current candidates',
                'recommendation': 'Prioritize technical interview scheduling',
                'action_accent': 'violet',
            })

        # --- Card 3: PIPELINE HEALTH ---
        # Active ratio: share of applications still moving (not hired/rejected).
        health_score = int(round((active / total_apps) * 100))
        if health_score >= 70:
            health_status = 'Optimal flow'
            health_band = 'strong'
            ai_detection_health = 'Strong candidate progression velocity'
            ai_recommendation_health = 'Maintain current screening pace'
        elif health_score >= 45:
            health_status = 'Needs attention'
            health_band = 'moderate'
            ai_detection_health = 'Active candidates pending stage progression'
            ai_recommendation_health = 'Review pending candidate evaluations'
        else:
            health_status = 'Pipeline stalled'
            health_band = 'weak'
            ai_detection_health = 'High concentration of pending candidates'
            ai_recommendation_health = 'Accelerate initial candidate screening'

        # Form standard stage flow with real database counts
        raw_stages = [
            {'label': 'Applied', 'count': sd.get('new', 0), 'value': 'new'},
            {'label': 'Screening', 'count': sd.get('shortlisted', 0), 'value': 'shortlisted'},
            {'label': 'Interview', 'count': sd.get('in_progress', 0), 'value': 'in_progress'},
            {'label': 'Hired', 'count': sd.get('hired', 0), 'value': 'hired'},
        ]
        # Bottleneck = the funnel stage holding the most candidates still
        # awaiting progression (exclude 'hired' which is a terminal win,
        # not a wait state).
        bottleneck_name = 'Screening'
        max_wait = -1
        for st in raw_stages[:3]:
            if st['count'] > max_wait:
                max_wait = st['count']
                bottleneck_name = st['label']

        ai_insights.append({
            'id': 'health',
            'category': 'Pipeline Intelligence',
            'icon': '📊',
            'score': health_score,
            'score_max': 100,
            'score_label': f'{health_score}%',  # Active Ratio display
            'status': health_status,
            'status_band': health_band,
            'ai_detection': ai_detection_health,
            'stage_flow': raw_stages,
            'bottleneck': bottleneck_name,
            'recommendation': ai_recommendation_health,
            'action_accent': 'amber',
        })

        # --- Card 4: RECRUITMENT RISK MONITOR ---
        from datetime import timedelta

        from django.utils import timezone

        week_ago = timezone.now() - timedelta(days=7)
        stalled_qs = JobApplication.objects.filter(
            updated_at__lt=week_ago
        ).exclude(status__in=['hired', 'rejected']).select_related(
            'candidate', 'job', 'assigned_to'
        ).order_by('updated_at')
        stalled_count = stalled_qs.count()
        context['stalled_applications'] = stalled_qs
        context['stalled_count'] = stalled_count

        if stalled_count >= 3:
            risk_level = 'HIGH'
            risk_tone = 'red'
            risk_condition = f'{stalled_count} candidate(s) stalled > 7 days'
            ai_recommendation_risk = 'Schedule overdue interviewer evaluations'
        elif stalled_count >= 1:
            risk_level = 'MEDIUM'
            risk_tone = 'amber'
            risk_condition = f'{stalled_count} candidate(s) awaiting movement'
            ai_recommendation_risk = 'Follow up with assigned interviewers'
        else:
            risk_level = 'LOW'
            risk_tone = 'green'
            risk_condition = '0 candidates stalled'
            ai_recommendation_risk = 'Pipeline is stable'

        ai_insights.append({
            'id': 'risk',
            'category': 'Risk Monitor',
            'icon': '🛡️',
            'risk_level': risk_level,
            'risk_tone': risk_tone,
            'condition': risk_condition,
            'inactive_count': stalled_count,
            'recommendation': ai_recommendation_risk,
            'action_accent': 'green',
        })

        context['ai_insights'] = ai_insights

        # Pipeline velocity: REAL measured time-in-stage. For every
        # application currently sitting in a stage, days since its last
        # state change (updated_at) — actual elapsed time, no formula.
        now = timezone.now()

        def _avg_days_in_status(status_value):
            """Average days since last PipelineMove into this status.

            Falls back to updated_at for applications with no move history.
            """
            app_ids_in_status = list(
                JobApplication.objects.filter(status=status_value).values_list('id', flat=True)
            )
            if not app_ids_in_status:
                return None

            last_move = {}
            for move in (
                PipelineMove.objects.filter(application_id__in=app_ids_in_status)
                .order_by('application_id', '-moved_at')
            ):
                if move.application_id not in last_move:
                    last_move[move.application_id] = move.moved_at

            ages = []
            for app_id in app_ids_in_status:
                ref_time = last_move.get(app_id)
                if ref_time is None:
                    # No moves yet — fall back to updated_at
                    ref_time = (
                        JobApplication.objects.filter(id=app_id)
                        .values_list('updated_at', flat=True)
                        .first()
                    )
                if ref_time:
                    ages.append((now - ref_time).total_seconds() / 86400.0)

            return round(sum(ages) / len(ages), 1) if ages else None

        context['velocity_screening'] = _avg_days_in_status('shortlisted')
        context['velocity_interview'] = _avg_days_in_status('in_progress')
        context['velocity_offer'] = _avg_days_in_status('hired')
        context['has_velocity_data'] = any(
            context[k] is not None
            for k in ('velocity_screening', 'velocity_interview', 'velocity_offer')
        )

        return context


class InterviewerDashboardView(LoginRequiredMixin, TemplateView):
    """Interviewer dashboard — assigned candidates + feedback needed."""
    template_name = 'accounts/interviewer_dashboard.html'

    def dispatch(self, request, *args, **kwargs):
        if not request.user.is_authenticated:
            return self.handle_no_permission()
        if not request.user.is_interviewer():
            return redirect('accounts:home')
        return super().dispatch(request, *args, **kwargs)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        user = self.request.user
        assigned_qs = JobApplication.objects.filter(
            Q(assigned_to=user) | Q(panel_interviewers=user)
        ).distinct().select_related(
            'candidate', 'job', 'current_round'
        )

        context['assigned_apps'] = assigned_qs.order_by('interview_at', '-updated_at')[:20]
        context['assigned_count'] = assigned_qs.count()
        context['pending_feedback'] = assigned_qs.filter(
            feedback_submitted=False, current_round__isnull=False
        ).count()

        # Upcoming interviews: scheduled, in the future, ordered nearest first.
        context['upcoming_interviews'] = (
            assigned_qs.filter(
                interview_at__isnull=False,
                interview_at__gte=timezone.now(),
            ).exclude(status__in=['hired', 'rejected'])
            .order_by('interview_at')[:5]
        )

        # The interviewer's own weekly availability, grouped by weekday order.
        context['availability_windows'] = (
            user.availability_windows.all()
        )
        context['has_availability'] = user.has_availability()

        context['active_nav'] = 'dashboard'
        return context


class ManagementDashboardView(LoginRequiredMixin, RedirectView):
    """Management lands on the shared executive dashboard on sign-in."""

    permanent = False

    def get_redirect_url(self, *args, **kwargs):
        return reverse('accounts:hr_dashboard')


class InterviewerRosterView(LoginRequiredMixin, ListView):
    """HR view of every interviewer: specialty, weekly availability, load.

    Real-time availability comes straight from InterviewerAvailability
    windows; workload counts in-flight applications per interviewer so HR
    can balance assignments against the role-match rule.
    """
    template_name = 'accounts/interviewer_roster.html'
    context_object_name = 'interviewers'

    def dispatch(self, request, *args, **kwargs):
        # Read-only oversight for management; full view for HR.
        if not (request.user.is_hr() or request.user.is_management()):
            return redirect('accounts:home')
        return super().dispatch(request, *args, **kwargs)

    def get_queryset(self):
        return (
            User.objects.filter(role=Role.INTERVIEWER)
            .prefetch_related('availability_windows')
            .order_by('first_name', 'last_name')
        )

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['active_nav'] = 'roster'

        # "Active Load" = DISTINCT applications where the interviewer is the
        # assignee OR a panel member, in a status that still needs work.
        # The two sets overlap heavily (assignees are auto-added to the
        # panel), so count the union per interviewer — never the sum.
        work_qs = (
            JobApplication.objects
            .exclude(status__in=['hired', 'rejected', 'on_hold'])
        )
        # Pre-compute load in two queries to avoid N+1.
        assignee_counts = dict(
            work_qs.filter(assigned_to__isnull=False)
            .values('assigned_to_id')
            .annotate(cnt=Count('id'))
            .values_list('assigned_to_id', 'cnt')
        )
        panel_counts = dict(
            work_qs.filter(panel_interviewers__isnull=False)
            .values('panel_interviewers__id')
            .annotate(cnt=Count('id'))
            .values_list('panel_interviewers__id', 'cnt')
        )
        load = {}
        all_iv_pks = set(assignee_counts.keys()) | set(panel_counts.keys())
        for pk in all_iv_pks:
            # Union approximation: max of the two counts (assignees overlap
            # with panel in practice, so this is close to DISTINCT).
            load[pk] = max(assignee_counts.get(pk, 0), panel_counts.get(pk, 0))
        pending = dict(
            JobApplication.objects.filter(
                assigned_to__isnull=False,
                feedback_submitted=False,
                current_round__isnull=False,
            )
            .exclude(status__in=['hired', 'rejected'])
            .values('assigned_to_id')
            .annotate(count=Count('id'))
            .values_list('assigned_to_id', 'count')
        )
        for iv in context['interviewers']:
            iv.active_load = load.get(iv.pk, 0)
            iv.pending_count = pending.get(iv.pk, 0)
        return context


class DeactivateInterviewerView(LoginRequiredMixin, View):
    """HR only: deactivate an interviewer account (is_active=False).

    Does NOT delete the user — historical feedback stays attributed.
    Active assignments surface on the offboarding page for HR to reassign.
    """

    def post(self, request, pk):
        if not request.user.is_hr():
            return HttpResponse('Only HR can deactivate interviewers.', status=403)
        user = get_object_or_404(User, pk=pk, role=Role.INTERVIEWER)
        if user == request.user:
            messages.error(request, 'You cannot deactivate your own account.')
            return redirect('accounts:interviewer_roster')
        if not user.is_active:
            messages.info(request, f'{user.get_full_name() or user.username} is already deactivated.')
            return redirect('accounts:interviewer_roster')
        user.is_active = False
        user.save(update_fields=['is_active'])
        messages.success(
            request,
            f'{user.get_full_name() or user.username} has been deactivated. '
            f'Active assignments are listed on the offboarding page.',
        )
        return redirect('accounts:interviewer_roster')
