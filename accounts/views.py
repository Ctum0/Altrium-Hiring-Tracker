import csv
from itertools import groupby

from django.contrib import messages
from django.contrib.auth import get_user_model
from django.contrib.auth import views as auth_views
from django.contrib.auth.mixins import LoginRequiredMixin
from django.db.models import Avg, Count, Q
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect
from django.urls import reverse, reverse_lazy
from django.utils import timezone
from django.views.generic import (
    CreateView, DetailView, ListView, RedirectView, TemplateView, View,
)

from accounts.forms import AvailabilityWindowForm, InterviewerProfileForm, OnboardUserForm
from accounts.models import InterviewerAvailability, Role

from candidates.models import Candidate, JobApplication
from jobs.models import InterviewRound, Job
from pipeline.models import PipelineMove

User = get_user_model()


def compute_avg_days_to_hire(job_id=None):
    """Average days from application creation to first hire.

    Uses the earliest PipelineMove(to_status='hired') per hired
    application (time-to-hire), not the most recent one (which would
    just measure time-since-hire). Falls back to stage_entered_at for
    hires with no move history (e.g. seeded/legacy data predating
    pipeline move logging).

    Pass job_id to scope the calculation to one job's hires (used by
    the per-job pipeline report); omit it for the global dashboard
    metric. Shared by HRDashboardView and ReportExportView so both
    stay in sync with the same audited formula.
    """
    hired_qs = JobApplication.objects.filter(status='hired')
    if job_id is not None:
        hired_qs = hired_qs.filter(job_id=job_id)
    # stage_entered_at fetched up front so the no-move-history fallback
    # needs no per-application query.
    hired_apps = list(hired_qs.values_list('id', 'created_at', 'stage_entered_at'))
    if not hired_apps:
        return None

    hired_ids = [app_id for app_id, _, _ in hired_apps]
    first_hire_move = {}
    for move in (
        PipelineMove.objects.filter(application_id__in=hired_ids, to_status='hired')
        .order_by('application_id', 'moved_at')
    ):
        if move.application_id not in first_hire_move:
            first_hire_move[move.application_id] = move.moved_at

    durations = []
    for app_id, created_at, stage_entered_at in hired_apps:
        hired_at = first_hire_move.get(app_id)
        if hired_at is None:
            # No move history — fall back to stage_entered_at.
            hired_at = stage_entered_at
        if hired_at and created_at:
            duration_days = (hired_at - created_at).total_seconds() / 86400.0
            if duration_days < 0:
                # Corrupted/inconsistent data: the hired timestamp is
                # earlier than the application's created_at (e.g. a
                # backdated stage_entered_at in seed data). A genuine
                # same-day hire is 0 days, never negative, so this only
                # ever excludes actually-corrupt rows, not fast hires.
                # We exclude rather than clip to 0, since clipping would
                # still inject a fabricated fast-hire data point and drag
                # the average down.
                continue
            durations.append(duration_days)

    return round(sum(durations) / len(durations), 1) if durations else None


# Threshold for flagging a round's fail rate as abnormal: more than 1.5x
# the mean fail rate across every round with move data. Kept as a simple,
# explainable multiplier (not a statistical z-score or black-box model)
# so HR can reason about why a round got flagged.
ABNORMAL_FAIL_RATE_MULTIPLIER = 1.5
# Minimum total outbound moves a round needs before it is eligible to be
# flagged, so a single rejection out of one candidate can't flag a round
# that simply has no real volume yet.
MIN_MOVES_FOR_ABNORMAL_FLAG = 3


def compute_stage_performance():
    """Per-InterviewRound pass/fail rates derived from PipelineMove history.

    For every round with at least one outbound PipelineMove
    (from_round=<round>): fail_count counts moves rejected out of that
    round; advance_count counts every other outbound move (advance to
    another round, or placed into hired/on_hold) — i.e. everything
    that isn't a rejection. Rounds with zero outbound moves are
    skipped (no data yet).

    Returns a list of dicts (round, fail_count, advance_count, total,
    pass_rate_pct, fail_rate_pct, is_abnormal), sorted by fail rate
    descending. Empty list means no round has move history yet.
    """
    rounds_with_moves = (
        InterviewRound.objects.filter(moves_from__isnull=False)
        .distinct()
        .select_related('job')
        .annotate(
            fail_count=Count('moves_from', filter=Q(moves_from__to_status='rejected')),
            advance_count=Count(
                'moves_from',
                filter=Q(moves_from__to_round__isnull=False)
                | Q(moves_from__to_status__in=['hired', 'on_hold']),
            ),
        )
    )

    stats = []
    for round_obj in rounds_with_moves:
        fail_count = round_obj.fail_count
        advance_count = round_obj.advance_count
        total = fail_count + advance_count
        if total == 0:
            continue
        stats.append({
            'round': round_obj,
            'fail_count': fail_count,
            'advance_count': advance_count,
            'total': total,
            'fail_rate': fail_count / total,
        })

    if not stats:
        return []

    mean_fail_rate = sum(s['fail_rate'] for s in stats) / len(stats)
    for s in stats:
        s['pass_rate_pct'] = round((1 - s['fail_rate']) * 100, 1)
        s['fail_rate_pct'] = round(s['fail_rate'] * 100, 1)
        s['is_abnormal'] = (
            mean_fail_rate > 0
            and s['total'] >= MIN_MOVES_FOR_ABNORMAL_FLAG
            and s['fail_rate'] > mean_fail_rate * ABNORMAL_FAIL_RATE_MULTIPLIER
        )

    stats.sort(key=lambda s: s['fail_rate'], reverse=True)
    return stats


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
    """POST-only logout (Django 5 default); the navbar uses a POST form."""





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
        score_stats = scored.aggregate(
            total=Count('id'),
            b25=Count('id', filter=Q(score__gte=0, score__lte=25)),
            b50=Count('id', filter=Q(score__gte=26, score__lte=50)),
            b75=Count('id', filter=Q(score__gte=51, score__lte=75)),
            b100=Count('id', filter=Q(score__gte=76, score__lte=100)),
            avg=Avg('score'),
        )
        total_scored = score_stats['total']
        context['score_distribution'] = [
            {'label': label, 'count': score_stats[key]}
            for label, key in (
                ('0-25', 'b25'), ('26-50', 'b50'), ('51-75', 'b75'), ('76-100', 'b100'),
            )
        ]
        context['scored_count'] = total_scored
        context['avg_score'] = (
            round(score_stats['avg'], 1)
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
            .select_related('hiring_manager')
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
                    'department': job.get_department_display() if job.department else '',
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
        # Actionable pending only: exclude unassigned applications — they are
        # nobody's work until HR assigns an evaluator, and counting them here
        # while the Feedback page's Pending tab excludes them made the two
        # numbers disagree (dashboard said 8, list said 2).
        context['feedback_pending'] = apps_in_round.filter(
            feedback_submitted=False,
        ).exclude(
            assigned_to__isnull=True, panel_interviewers__isnull=True,
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
                s.strip() for skills_str in cand_qs.values_list('skills', flat=True)
                for s in (skills_str or '').split(',') if s.strip()
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
            stage_entered_at__lt=week_ago
        ).exclude(status__in=['hired', 'rejected']).select_related(
            'candidate', 'job', 'assigned_to'
        ).order_by('stage_entered_at')
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

        # Pipeline velocity. "Screening"/"Interview" are REAL measured
        # time-in-stage: for every application currently sitting in a
        # stage, days since its last state change (moved_at, falling back
        # to updated_at) — actual elapsed time, no formula. "Hired" is
        # different in kind: it is a completed outcome, so it measures
        # time-TO-hire (creation -> first hire), not time-since-hire.
        now = timezone.now()

        def _avg_days_in_status(status_value):
            """Average days since last PipelineMove into this status.

            Falls back to updated_at for applications with no move history.
            """
            # Fetch updated_at up front so the no-move fallback needs no
            # per-application query.
            apps_in_status = list(
                JobApplication.objects.filter(status=status_value)
                .values_list('id', 'updated_at')
            )
            if not apps_in_status:
                return None

            app_ids = [app_id for app_id, _ in apps_in_status]
            last_move = {}
            for move in (
                PipelineMove.objects.filter(application_id__in=app_ids)
                .order_by('application_id', '-moved_at')
            ):
                if move.application_id not in last_move:
                    last_move[move.application_id] = move.moved_at

            ages = []
            for app_id, updated_at in apps_in_status:
                ref_time = last_move.get(app_id)
                if ref_time is None:
                    # No moves yet — fall back to updated_at
                    ref_time = updated_at
                if ref_time:
                    age_days = (now - ref_time).total_seconds() / 86400.0
                    if age_days < 0:
                        # Same corrupted-data guard as compute_avg_days_to_hire:
                        # a ref_time after "now" means bad seed/move data, not
                        # a real negative time-in-stage. Exclude, don't clip.
                        continue
                    ages.append(age_days)

            return round(sum(ages) / len(ages), 1) if ages else None

        context['velocity_screening'] = _avg_days_in_status('shortlisted')
        context['velocity_interview'] = _avg_days_in_status('in_progress')
        context['velocity_offer'] = compute_avg_days_to_hire()
        context['has_velocity_data'] = any(
            context[k] is not None
            for k in ('velocity_screening', 'velocity_interview', 'velocity_offer')
        )

        context['stage_performance'] = compute_stage_performance()

        return context


class ReportExportView(LoginRequiredMixin, View):
    """HR/Management: CSV export, one row per job (Feature 7: Pipeline
    Reporting). Covers every job — active and closed."""

    def dispatch(self, request, *args, **kwargs):
        if not request.user.is_authenticated:
            return self.handle_no_permission()
        if not (request.user.is_hr() or request.user.is_management()):
            return redirect('accounts:home')
        return super().dispatch(request, *args, **kwargs)

    def get(self, request, *args, **kwargs):
        jobs = (
            Job.objects.annotate(app_count=Count('applications'))
            .order_by('-created_at')
        )

        filename = f'pipeline_report_{timezone.now().date().isoformat()}.csv'
        response = HttpResponse(content_type='text/csv')
        response['Content-Disposition'] = f'attachment; filename="{filename}"'

        writer = csv.writer(response)
        writer.writerow([
            'Job Title', 'Department', 'Candidate Count',
            'Avg Time to Hire (days)', 'Status',
        ])
        for job in jobs:
            avg_days = compute_avg_days_to_hire(job_id=job.pk)
            writer.writerow([
                job.title,
                job.department or '',
                job.app_count,
                avg_days if avg_days is not None else 'N/A',
                'Active' if job.is_active else 'Closed',
            ])

        return response


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
        # The is_authenticated check MUST come first: role helpers on
        # AnonymousUser raise AttributeError, and dispatch runs before
        # LoginRequiredMixin gets a chance to redirect.
        if not request.user.is_authenticated:
            return self.handle_no_permission()
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


class HRRequiredMixin:
    """Dispatch gate: full access for HR; other roles bounce to home.

    Mirrors the role check in InterviewerRosterView.dispatch(). Management
    keeps read-only oversight of the roster, so anything that mutates
    interviewer data is restricted to HR only.
    """

    def dispatch(self, request, *args, **kwargs):
        if not request.user.is_authenticated:
            return self.handle_no_permission()
        if not request.user.is_hr():
            return redirect('accounts:home')
        return super().dispatch(request, *args, **kwargs)


class OnboardUserView(LoginRequiredMixin, HRRequiredMixin, CreateView):
    """HR creates a new account (interviewer / HR / management) directly.

    Sets the initial password chosen by HR, then routes HR to the roster
    where the new interviewer shows up with their matching fields.
    """

    template_name = 'accounts/onboard_user.html'
    form_class = OnboardUserForm

    def get_initial(self):
        return {'role': Role.INTERVIEWER}

    def form_valid(self, form):
        user = form.save()
        role_label = user.get_role_display()
        messages.success(
            self.request,
            f'{user.get_full_name() or user.username} has been onboarded as '
            f'{role_label}.',
        )
        return redirect('accounts:interviewer_roster')


class MyAvailabilityView(LoginRequiredMixin, TemplateView):
    """Interviewer self-service for their recurring weekly windows.

    There is no pk parameter by design: an interviewer can only ever see
    and edit their own windows (request.user is the owner).
    """

    template_name = 'accounts/my_availability.html'

    def dispatch(self, request, *args, **kwargs):
        if not request.user.is_authenticated:
            return self.handle_no_permission()
        if not request.user.is_interviewer():
            return redirect('accounts:home')
        return super().dispatch(request, *args, **kwargs)

    def get_windows(self):
        return self.request.user.availability_windows.order_by('weekday', 'start_time')

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        windows = self.get_windows()
        weekdays = InterviewerAvailability.Weekday
        grouped = [
            (label, list(rows))
            for label, rows in groupby(windows, key=lambda w: w.get_weekday_display())
        ]
        context['weekday_groups'] = grouped
        context['has_availability'] = windows.exists()
        context['form'] = kwargs.get('form') or AvailabilityWindowForm()
        context['active_nav'] = 'availability'
        return context

    def get(self, request, *args, **kwargs):
        return self.render_to_response(self.get_context_data())

    def post(self, request, *args, **kwargs):
        if 'remove' in request.POST:
            window = get_object_or_404(
                InterviewerAvailability,
                pk=request.POST['remove'],
                interviewer=request.user,
            )
            window.delete()
            messages.success(request, 'Availability window removed.')
            return redirect('accounts:my_availability')
        form = AvailabilityWindowForm(request.POST)
        if form.is_valid():
            saved = form.save_for(request.user)
            if saved is not None:
                messages.success(request, 'Availability window added.')
                return redirect('accounts:my_availability')
        # Re-render with errors plus the current windows (post-save state).
        return self.render_to_response(self.get_context_data(form=form))


class MyCalendarView(LoginRequiredMixin, TemplateView):
    """Interviewer's own booked interviews grouped by date."""

    template_name = 'accounts/my_calendar.html'

    def dispatch(self, request, *args, **kwargs):
        if not request.user.is_authenticated:
            return self.handle_no_permission()
        if not request.user.is_interviewer():
            return redirect('accounts:home')
        return super().dispatch(request, *args, **kwargs)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        booked = (
            JobApplication.objects
            .filter(assigned_to=self.request.user, interview_at__isnull=False)
            .exclude(status__in=['hired', 'rejected'])
            .select_related('candidate', 'job', 'current_round')
            .order_by('interview_at')
        )
        days = []
        for date, apps in groupby(booked, key=lambda app: timezone.localdate(app.interview_at)):
            days.append({'date': date, 'apps': list(apps)})
        context['calendar_days'] = days
        context['active_nav'] = 'calendar'
        return context


class InterviewerProfileView(LoginRequiredMixin, DetailView):
    """HR/Management profile of one interviewer: matching fields, weekly
    availability, current load, pending feedback, upcoming interviews.

    Role-mirrors InterviewerRosterView: HR and Management have read access;
    interviewers are redirected to home. HR can additionally correct the
    matching profile (name, specialty, seniority, domain) — those fields
    drive the assign-eligibility rules and previously had no edit path
    after onboarding.
    """

    template_name = 'accounts/interviewer_profile.html'
    context_object_name = 'interviewer'

    def dispatch(self, request, *args, **kwargs):
        if not request.user.is_authenticated:
            return self.handle_no_permission()
        if not (request.user.is_hr() or request.user.is_management()):
            return redirect('accounts:home')
        return super().dispatch(request, *args, **kwargs)

    def get_queryset(self):
        return User.objects.filter(role=Role.INTERVIEWER)

    def post(self, request, *args, **kwargs):
        # HR-only edit of the matching profile; management stays read-only.
        if not request.user.is_hr():
            return redirect('accounts:interviewer_profile', pk=kwargs['pk'])
        self.object = self.get_object()
        form = InterviewerProfileForm(request.POST, instance=self.object)
        if form.is_valid():
            form.save()
            messages.success(
                request,
                f'{self.object.get_full_name() or self.object.username} '
                f'updated. They now appear in the Assign dropdown for jobs '
                f'their profile matches.',
            )
            return redirect('accounts:interviewer_profile', pk=self.object.pk)
        context = self.get_context_data(object=self.object)
        context['profile_form'] = form
        return self.render_to_response(context)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        interviewer = self.object

        work_qs = JobApplication.objects.exclude(status__in=['hired', 'rejected', 'on_hold'])
        active_load = (
            work_qs.filter(Q(assigned_to=interviewer) | Q(panel_interviewers=interviewer))
            .distinct()
            .count()
        )
        pending_feedback = (
            JobApplication.objects
            .filter(assigned_to=interviewer, feedback_submitted=False, current_round__isnull=False)
            .exclude(status__in=['hired', 'rejected'])
            .count()
        )
        upcoming = (
            JobApplication.objects
            .filter(
                Q(assigned_to=interviewer) | Q(panel_interviewers=interviewer),
                interview_at__isnull=False,
                interview_at__gte=timezone.now(),
            )
            .exclude(status__in=['hired', 'rejected'])
            .select_related('candidate', 'job', 'current_round')
            .order_by('interview_at')[:10]
        )

        context['availability_windows'] = interviewer.availability_windows.all()
        context['active_load'] = active_load
        context['pending_feedback_count'] = pending_feedback
        context['upcoming_interviews'] = upcoming
        context['active_nav'] = 'roster'
        context['profile_form'] = kwargs.get('profile_form') or (
            InterviewerProfileForm(instance=interviewer)
            if self.request.user.is_hr() else None
        )
        return context


class RetentionReportView(LoginRequiredMixin, ListView):
    """HR/Management: read-only audit of the data retention policy.

    Phase 11 (NFR): closing a job (JobCloseView) only flips is_active and
    stamps closed_at; it never deletes or archives Candidate or
    JobApplication rows. This view makes that policy explicit and
    auditable by listing every closed job with how long ago it closed and
    how many candidates are still on file, each linking back to the
    ordinary candidate list to prove the data stays searchable. It adds
    no deletion, archival, or expiry mechanism of its own.
    """

    template_name = 'accounts/retention_report.html'
    context_object_name = 'closed_jobs'

    def dispatch(self, request, *args, **kwargs):
        if not request.user.is_authenticated:
            return self.handle_no_permission()
        if not (request.user.is_hr() or request.user.is_management()):
            return redirect('accounts:home')
        return super().dispatch(request, *args, **kwargs)

    def get_queryset(self):
        return (
            Job.objects.filter(is_active=False)
            .annotate(num_applications=Count('applications'))
            .order_by('-closed_at')
        )

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['active_nav'] = 'jobs'
        now = timezone.now()
        for job in context['closed_jobs']:
            job.days_since_closure = (now - job.closed_at).days if job.closed_at else None
        return context
