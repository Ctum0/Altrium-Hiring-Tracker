import csv
import secrets
import string
from datetime import timedelta
from itertools import groupby

from django.contrib import messages
from django.contrib.auth import get_user_model, update_session_auth_hash
from django.contrib.auth import views as auth_views
from django.contrib.auth.forms import PasswordChangeForm
from django.contrib.auth.mixins import LoginRequiredMixin
from django.core.files.storage import default_storage
from django.db import transaction
from django.db.models import Avg, Count, Prefetch, Q
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse, reverse_lazy
from django.utils import timezone
from django.views.generic import (
    CreateView,
    DetailView,
    ListView,
    RedirectView,
    TemplateView,
    View,
)

from accounts.forms import (
    AdminUserCreateForm,
    AvailabilityExceptionForm,
    AvailabilityWindowForm,
    InterviewerProfileForm,
    OnboardUserForm,
    ProfileUpdateForm,
)
from accounts.models import (
    AuditLog,
    AvailabilityException,
    InterviewerAvailability,
    RescheduleRequest,
    Role,
)
from candidates.models import Candidate, JobApplication
from feedback.models import InterviewFeedback
from jobs.models import InterviewRound, Job
from notifications.models import Notification
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

    def form_valid(self, form):
        """Log the successful sign-in, then run Django's normal login."""
        AuditLog.record(
            form.get_user(),
            AuditLog.Action.LOGIN,
            object_type='User',
            object_id=form.get_user().pk,
            detail=f'Signed in from {self.request.META.get("REMOTE_ADDR", "")}',
        )
        return super().form_valid(form)

    def get_success_url(self):
        # A ?next= target (e.g. the page a session drop interrupted) wins
        # over the role default — the user returns to where they were.
        # Relative paths only (open-redirect guard).
        next_url = self.request.POST.get('next') or self.request.GET.get('next') or ''
        if next_url.startswith('/') and not next_url.startswith('//'):
            # A forced password change outranks ?next=: a user with a
            # temporary password must land on the change page regardless
            # of where their session drop interrupted them.
            if self.request.user.force_password_change:
                return reverse_lazy('accounts:password_change')
            return next_url
        user = self.request.user
        if user.force_password_change:
            return reverse_lazy('accounts:password_change')
        if user.is_hr() or user.is_management():
            return reverse_lazy('accounts:hr_dashboard')
        elif user.is_interviewer():
            return reverse_lazy('accounts:interviewer_dashboard')
        return reverse_lazy('accounts:hr_dashboard')


class LogoutView(auth_views.LogoutView):
    """POST-only logout (Django 5 default); the navbar uses a POST form."""

    def dispatch(self, request, *args, **kwargs):
        if request.user.is_authenticated:
            AuditLog.record(
                request.user,
                AuditLog.Action.LOGOUT,
                object_type='User',
                object_id=request.user.pk,
            )
        return super().dispatch(request, *args, **kwargs)


def _resize_photo(django_file, size=256):
    """Square-crop and resize an uploaded image with Pillow.

    Returns (django_file, extension) for re-saving onto the model, or
    None if the file cannot be decoded. Center-crops to a square first so
    avatars never come out stretched; JPEG output keeps storage small.
    """
    from io import BytesIO

    from django.core.files.base import File as DjangoFile
    from PIL import Image

    try:
        img = Image.open(django_file)
        img.load()
        fmt = (img.format or '').upper()
    except Exception:
        return None
    if fmt not in ('JPEG', 'PNG', 'WEBP'):
        return None
    side = min(img.size)
    left = (img.width - side) // 2
    top = (img.height - side) // 2
    img = img.crop((left, top, left + side, top + side)).resize((size, size))
    if img.mode not in ('RGB', 'L'):
        img = img.convert('RGB')
    buf = BytesIO()
    img.save(buf, format='JPEG', quality=85)
    buf.seek(0)
    return DjangoFile(buf, name='avatar.jpg'), 'jpg'


class ProfileUpdateView(LoginRequiredMixin, View):
    """Every role's own profile: name, email and photo (GET form / POST)."""

    template_name = 'accounts/profile.html'

    def get(self, request, *args, **kwargs):
        form = ProfileUpdateForm(instance=request.user)
        return self.render(request, form)

    def post(self, request, *args, **kwargs):
        old_photo = request.user.photo.name if request.user.photo else None
        form = ProfileUpdateForm(request.POST, request.FILES, instance=request.user)
        if form.is_valid():
            user = form.save(commit=False)
            if request.FILES.get('photo'):
                photo_file = request.FILES['photo']
                with photo_file.open('rb'):
                    resized = _resize_photo(photo_file)
                if resized is None:
                    form.add_error(
                        'photo', 'Could not process that image. Upload a JPEG, PNG or WebP.'
                    )
                    return self.render(request, form)
                new_file, _ext = resized
                user.photo.save(f'avatar_{user.pk}.jpg', new_file, save=False)
                if old_photo and old_photo != user.photo.name:
                    default_storage.delete(old_photo)
            user.save()
            messages.success(request, 'Profile updated.')
            return redirect('accounts:profile')
        return self.render(request, form)

    def render(self, request, form):
        return render(
            request,
            self.template_name,
            {'form': form, 'active_nav': 'profile'},
        )





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
        if not (request.user.is_hr() or request.user.is_management()
                or request.user.is_admin()):
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

        # Pipeline stage distribution — scoped to ACTIVE jobs to match the
        # "Active pipeline" KPI subtitle (GAP-004): closed-job applications
        # are historical data, not an active pipeline, and counting them
        # made the KPI disagree with every active-job-filtered view.
        stage_counts = dict(
            JobApplication.objects.filter(job__is_active=True)
            .values('status')
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
                'action_url': (
                    f'{reverse("candidates:list")}'
                    f'?job={",".join(str(pk) for pk in top_role_pks)}'
                ),
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
                # pks is a list; interpolating it directly rendered
                # '?job=[97]' which 500s the candidate list (int('[97]')
                # ValueError). Join comma-separated like the top_role card.
                'action_url': (
                    f'{reverse("candidates:list")}'
                    f'?job={",".join(str(pk) for pk in best_role["pks"])}'
                ),
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
            # Health recommendations are about evaluation throughput; the
            # pending-feedback list is the actionable surface for them.
            'action_url': f'{reverse("feedback:list")}?status=pending',
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
        # Cap the rendered list: the right column is a scan surface, not a
        # worklist — 750 rows made the dashboard ~31,000px tall. Show the
        # 10 most-stalled; the count badge carries the full number.
        context['stalled_applications'] = stalled_qs[:10]
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
            # Risk recommendations are about stalled candidates; the stalled
            # filter on the candidates list is the actionable surface.
            'action_url': f'{reverse("candidates:list")}?stalled=1',
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

        # Week-over-week trend panel ('This Week vs Last Week'). Kept as
        # separate small aggregate queries — the view's existing structure
        # is perf-tuned and untouched; this adds 4 queries total.
        week_start = (now - timedelta(days=now.weekday())).replace(
            hour=0, minute=0, second=0, microsecond=0,
        )
        last_week_start = week_start - timedelta(weeks=1)

        context['trend_apps_this_week'] = JobApplication.objects.filter(
            created_at__gte=week_start, created_at__lt=week_start + timedelta(weeks=1),
        ).count()
        context['trend_apps_last_week'] = JobApplication.objects.filter(
            created_at__gte=last_week_start, created_at__lt=week_start,
        ).count()
        context['trend_hires_this_week'] = PipelineMove.objects.filter(
            to_status='hired', moved_at__gte=week_start,
            moved_at__lt=week_start + timedelta(weeks=1),
        ).values('application_id').distinct().count()
        context['trend_hires_last_week'] = PipelineMove.objects.filter(
            to_status='hired', moved_at__gte=last_week_start, moved_at__lt=week_start,
        ).values('application_id').distinct().count()
        context['trend_rejections_this_week'] = PipelineMove.objects.filter(
            to_status='rejected', moved_at__gte=week_start,
            moved_at__lt=week_start + timedelta(weeks=1),
        ).values('application_id').distinct().count()
        context['trend_rejections_last_week'] = PipelineMove.objects.filter(
            to_status='rejected', moved_at__gte=last_week_start, moved_at__lt=week_start,
        ).values('application_id').distinct().count()
        # Pending feedback reuses the existing feedback_pending key.
        context['trend_feedback_pending'] = context['feedback_pending']

        # Hires-per-week mini chart: last 8 weekly buckets (oldest first).
        # Pull timestamps once, bucket in Python.
        hire_times = list(
            PipelineMove.objects.filter(
                to_status='hired', moved_at__gte=week_start - timedelta(weeks=7),
            ).values_list('moved_at', flat=True)
        )
        context['hires_per_week'] = []
        for i in range(8):
            bucket_start = week_start - timedelta(weeks=7 - i)
            bucket_end = bucket_start + timedelta(weeks=1)
            count = sum(1 for t in hire_times if bucket_start <= t < bucket_end)
            context['hires_per_week'].append({
                'label': bucket_start.strftime('%b %-d'),
                'count': count,
            })

        return context


class ReportExportView(LoginRequiredMixin, View):
    """HR/Management: CSV export (Feature 7: Pipeline Reporting).

    ?detail=1 switches to the per-application export: one row per
    application with candidate, stage, scores, assignment, and stage-age
    data. Default remains the per-job summary for backward compatibility.
    """

    def dispatch(self, request, *args, **kwargs):
        if not request.user.is_authenticated:
            return self.handle_no_permission()
        if not (request.user.is_hr() or request.user.is_management()):
            return redirect('accounts:home')
        return super().dispatch(request, *args, **kwargs)

    def get(self, request, *args, **kwargs):
        if request.GET.get('detail') == '1':
            return self._detailed_export()

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

    def _detailed_export(self):
        """One row per application: the candidate-level pipeline detail the
        per-job summary can't carry (candidate identity, stage, scores,
        assignment, stage age, feedback state)."""
        rows = (
            JobApplication.objects
            .select_related('candidate', 'job', 'current_round', 'assigned_to')
            .order_by('job__title', '-created_at')
        )
        now = timezone.now()
        filename = f'pipeline_report_detail_{timezone.now().date().isoformat()}.csv'
        response = HttpResponse(content_type='text/csv')
        response['Content-Disposition'] = f'attachment; filename="{filename}"'

        writer = csv.writer(response)
        writer.writerow([
            'Job Title', 'Job Status', 'Candidate', 'Email', 'Phone',
            'Stage', 'Current Round', 'Auto-Match Score', 'HR Score',
            'Needs Review', 'Assigned Interviewer', 'Feedback Submitted',
            'Days In Current Stage', 'Applied At',
        ])
        for app in rows:
            days_in_stage = (
                (now - app.stage_entered_at).days
                if app.stage_entered_at else ''
            )
            writer.writerow([
                app.job.title,
                'Active' if app.job.is_active else 'Closed',
                app.candidate.full_name,
                app.candidate.email or '',
                app.candidate.phone or '',
                app.get_status_display(),
                app.current_round.name if app.current_round else '',
                app.shortlist_score if app.shortlist_score is not None else '',
                app.candidate.score if app.candidate.score is not None else '',
                'Yes' if app.candidate.needs_review else 'No',
                (
                    app.assigned_to.get_full_name() or app.assigned_to.username
                ) if app.assigned_to else '',
                'Yes' if app.feedback_submitted else 'No',
                days_in_stage,
                app.created_at.date().isoformat() if app.created_at else '',
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
        ).prefetch_related(
            # GAP-010: the dashboard's Feedback cell links to the viewer's
            # own submitted feedback for edit access; prefetch avoids an
            # N+1 on the row loop.
            Prefetch(
                'feedbacks',
                queryset=InterviewFeedback.objects.filter(interviewer=user),
                to_attr='own_feedbacks',
            )
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

        # KPI: feedback the interviewer personally submitted this calendar
        # month. Same scoping rule as the table above: own feedback only.
        month_start = timezone.now().replace(
            day=1, hour=0, minute=0, second=0, microsecond=0,
        )
        context['feedback_this_month'] = InterviewFeedback.objects.filter(
            interviewer=user, submitted_at__gte=month_start,
        ).count()

        # KPI: interviews scheduled within the next 7 days (still active).
        now = timezone.now()
        context['upcoming_this_week'] = assigned_qs.filter(
            interview_at__gte=now,
            interview_at__lt=now + timedelta(days=7),
        ).exclude(status__in=['hired', 'rejected']).count()

        # Mini bar chart: feedback submitted per week over the last 8 weeks
        # (oldest bucket first). One aggregated query; buckets are computed
        # in Python from the submitted_at timestamps.
        week_start = (now - timedelta(days=now.weekday())).replace(
            hour=0, minute=0, second=0, microsecond=0,
        )
        window_start = week_start - timedelta(weeks=7)
        submitted_times = list(
            InterviewFeedback.objects.filter(
                interviewer=user, submitted_at__gte=window_start,
            ).values_list('submitted_at', flat=True)
        )
        weekly_feedback_counts = []
        for i in range(8):
            bucket_start = window_start + timedelta(weeks=i)
            bucket_end = bucket_start + timedelta(weeks=1)
            count = sum(
                1 for t in submitted_times if bucket_start <= t < bucket_end
            )
            weekly_feedback_counts.append({
                'label': bucket_start.strftime('%b %-d'),
                'count': count,
            })
        context['weekly_feedback_counts'] = weekly_feedback_counts

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
            name = user.get_full_name() or user.username
            messages.info(request, f'{name} is already deactivated.')
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
        grouped = [
            (label, list(rows))
            for label, rows in groupby(windows, key=lambda w: w.get_weekday_display())
        ]
        context['weekday_groups'] = grouped
        context['has_availability'] = windows.exists()
        context['form'] = kwargs.get('form') or AvailabilityWindowForm()
        context['exception_form'] = (
            kwargs.get('exception_form') or AvailabilityExceptionForm()
        )
        context['exceptions'] = list(
            AvailabilityException.objects.filter(interviewer=self.request.user)
        )
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
        if 'remove_exception' in request.POST:
            exception = get_object_or_404(
                AvailabilityException,
                pk=request.POST['remove_exception'],
                interviewer=request.user,
            )
            exception.delete()
            messages.success(request, 'Availability exception removed.')
            return redirect('accounts:my_availability')
        if 'exception-date' in request.POST or 'exception-is_unavailable' in request.POST:
            # Exceptions section has its own submit; the weekly-window form
            # keys off 'weekday', so the prefixed 'exception-*' fields
            # disambiguate which form this POST belongs to.
            exception_form = AvailabilityExceptionForm(request.POST)
            if exception_form.is_valid():
                saved = exception_form.save_for(request.user)
                if saved is not None:
                    kind = 'Blackout date added' if saved.is_unavailable else 'Extra hours added'
                    messages.success(request, f'{kind}.')
                    return redirect('accounts:my_availability')
            return self.render_to_response(
                self.get_context_data(exception_form=exception_form)
            )
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
            .prefetch_related('reschedule_requests')
            .order_by('interview_at')
        )
        days = []
        for date, apps in groupby(booked, key=lambda app: timezone.localdate(app.interview_at)):
            days.append({'date': date, 'apps': list(apps)})
        context['calendar_days'] = days
        # Assigned but not yet scheduled: these still need HR to book a
        # time, so the calendar answers 'what's on my plate' completely.
        awaiting = (
            JobApplication.objects
            .filter(assigned_to=self.request.user, interview_at__isnull=True)
            .exclude(status__in=['hired', 'rejected'])
            .select_related('candidate', 'job', 'current_round')
            .order_by('-updated_at')
        )
        context['awaiting_scheduling'] = list(awaiting)
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


# ---------------------------------------------------------------------------
# Admin: user management + password change (Wave 2a)
# ---------------------------------------------------------------------------

def generate_temp_password(length=14):
    """Server-generated temporary password, shown to the admin exactly once."""
    alphabet = string.ascii_letters + string.digits
    # Guarantee at least one of each character class so AUTH_PASSWORD_VALIDATORS'
    # complexity expectations (lower/upper/digit) are met without surprise.
    while True:
        pwd = ''.join(secrets.choice(alphabet) for _ in range(length))
        if (any(c.islower() for c in pwd) and any(c.isupper() for c in pwd)
                and any(c.isdigit() for c in pwd)):
            return pwd


class AdminRequiredMixin:
    """Gate: admins only (staff with role=Admin, or superuser).
    Everyone else bounces to home."""

    def dispatch(self, request, *args, **kwargs):
        if not request.user.is_authenticated:
            return self.handle_no_permission()
        if not request.user.is_admin():
            return redirect('accounts:home')
        return super().dispatch(request, *args, **kwargs)


class AdminUserListView(LoginRequiredMixin, AdminRequiredMixin, ListView):
    """Admin-only directory of every account with search + role filter."""

    template_name = 'accounts/admin_users.html'
    context_object_name = 'users'
    paginate_by = 25

    def get_queryset(self):
        qs = User.objects.all().order_by('username')
        query = (self.request.GET.get('q') or '').strip()
        if query:
            qs = qs.filter(
                Q(username__icontains=query)
                | Q(first_name__icontains=query)
                | Q(last_name__icontains=query)
                | Q(email__icontains=query)
            )
        role = self.request.GET.get('role') or ''
        if role:
            qs = qs.filter(role=role)
        return qs

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['active_nav'] = 'admin_users'
        context['search_query'] = (self.request.GET.get('q') or '').strip()
        context['role_filter'] = self.request.GET.get('role') or ''
        context['role_choices'] = Role.choices
        return context


class AdminUserCreateView(LoginRequiredMixin, AdminRequiredMixin, View):
    """Admin-only account creation with a server-generated temporary password.

    The temp password is rendered ONCE on the confirmation screen; it is
    never stored in plaintext and the user must change it at first login
    (force_password_change)."""

    template_name = 'accounts/admin_user_create.html'

    def get(self, request):
        form = AdminUserCreateForm()
        return render(request, self.template_name, {'form': form, 'active_nav': 'admin_users'})

    def post(self, request):
        form = AdminUserCreateForm(request.POST)
        if not form.is_valid():
            return render(request, self.template_name, {'form': form, 'active_nav': 'admin_users'})

        user = form.save(commit=False)
        temp_password = generate_temp_password()
        user.set_password(temp_password)
        user.is_staff = user.role == Role.ADMIN
        user.force_password_change = True
        user.save()
        form.save_m2m()  # no-op for now, keeps the ModelForm contract
        AuditLog.record(
            request.user,
            AuditLog.Action.CREATE,
            object_type='User',
            object_id=user.pk,
            detail=f'Created {user.get_role_display()} account "{user.username}" '
           f'with a temporary password.',
        )
        return render(request, 'accounts/admin_user_created.html', {
            'created_user': user,
            'temp_password': temp_password,
            'active_nav': 'admin_users',
        })


class AdminUserToggleActiveView(LoginRequiredMixin, AdminRequiredMixin, View):
    """Deactivate/reactivate an account.

    Protections: an admin cannot deactivate themselves, and the last
    active admin cannot be deactivated (or the instance would be
    unmanageable)."""

    def post(self, request, pk):
        target = get_object_or_404(User, pk=pk)
        if target == request.user:
            messages.error(request, 'You cannot deactivate your own account.')
            return redirect('accounts:admin_users')
        if target.is_active and target.is_admin() and not (
            User.objects.filter(is_active=True, is_staff=True, role=Role.ADMIN)
            .exclude(pk=target.pk).exists()
        ) and not User.objects.filter(
            is_superuser=True, is_active=True
        ).exclude(pk=target.pk).exists():
            messages.error(
                request,
                'Cannot deactivate the last active admin — promote another admin first.',
            )
            return redirect('accounts:admin_users')
        target.is_active = not target.is_active
        target.save(update_fields=['is_active'])
        AuditLog.record(
            request.user,
            AuditLog.Action.UPDATE,
            object_type='User',
            object_id=target.pk,
            detail=f'{"Deactivated" if not target.is_active else "Reactivated"} '
                   f'account "{target.username}".',
        )
        messages.success(
            request,
            f'Account "{target.username}" '
            f'{"deactivated" if not target.is_active else "reactivated"}.',
        )
        return redirect('accounts:admin_users')


class AdminUserResetPasswordView(LoginRequiredMixin, AdminRequiredMixin, View):
    """Issue a fresh temporary password: shown once, forces a change at
    next login. The old password stops working immediately."""

    def post(self, request, pk):
        target = get_object_or_404(User, pk=pk)
        temp_password = generate_temp_password()
        target.set_password(temp_password)
        target.force_password_change = True
        target.save(update_fields=['password', 'force_password_change'])
        AuditLog.record(
            request.user,
            AuditLog.Action.PASSWORD_RESET,
            object_type='User',
            object_id=target.pk,
            detail=f'Issued a temporary password for "{target.username}".',
        )
        return render(request, 'accounts/admin_user_password_reset.html', {
            'target_user': target,
            'temp_password': temp_password,
            'active_nav': 'admin_users',
        })


class PasswordChangeView(LoginRequiredMixin, View):
    """All roles change their own password. Clears force_password_change
    on success; keeps the session alive instead of forcing a re-login."""

    template_name = 'accounts/password_change.html'

    def get(self, request):
        form = PasswordChangeForm(request.user)
        return render(request, self.template_name, {'form': form, 'active_nav': 'password'})

    def post(self, request):
        form = PasswordChangeForm(request.user, request.POST)
        if not form.is_valid():
            return render(request, self.template_name, {'form': form, 'active_nav': 'password'})

        user = form.save()  # sets + hashes the new password
        update_session_auth_hash(request, user)  # keep the session logged in
        user.force_password_change = False
        user.save(update_fields=['force_password_change'])
        AuditLog.record(
            request.user,
            AuditLog.Action.PASSWORD_RESET,
            object_type='User',
            object_id=user.pk,
            detail='Changed own password.',
        )
        messages.success(request, 'Your password has been changed.')
        return redirect('accounts:profile')


class RescheduleRequestCreateView(LoginRequiredMixin, View):
    """Interviewer asks HR to move one of their booked interviews.

    POST from My Calendar: up to 3 proposed slots (ISO datetimes) plus an
    optional note. Creates the request and notifies the assigned HR user
    (in-app Notification, same pattern as assignment/scheduling notices).
    """

    MAX_SLOTS = 3

    def post(self, request, pk):
        if not request.user.is_interviewer():
            messages.error(request, 'Only interviewers can request reschedules.')
            return redirect('accounts:home')
        app = get_object_or_404(JobApplication, pk=pk)
        if app.assigned_to_id != request.user.pk:
            messages.error(request, 'You can only request reschedules for your own interviews.')
            return redirect('accounts:my_calendar')
        if not app.interview_at:
            messages.error(request, 'This interview has no booked slot to reschedule.')
            return redirect('accounts:my_calendar')

        from datetime import datetime as dt
        from datetime import timezone as dt_timezone

        proposed = []
        for raw in request.POST.getlist('proposed_slot')[:self.MAX_SLOTS]:
            raw = (raw or '').strip()
            if not raw:
                continue
            try:
                parsed = dt.fromisoformat(raw)
                if timezone.is_naive(parsed):
                    parsed = timezone.make_aware(parsed, dt_timezone.utc)
            except ValueError:
                messages.error(
                    request,
                    f'Could not read proposed slot "{raw}". Use YYYY-MM-DD HH:MM.',
                )
                return redirect('accounts:my_calendar')
            if parsed <= timezone.now():
                messages.error(request, 'Proposed slots must be in the future.')
                return redirect('accounts:my_calendar')
            proposed.append(parsed.isoformat())

        if not proposed:
            messages.error(request, 'Propose at least one alternative slot.')
            return redirect('accounts:my_calendar')

        req = RescheduleRequest.objects.create(
            application=app,
            requested_by=request.user,
            original_slot=app.interview_at,
            proposed_slots=proposed,
            note=request.POST.get('note', '').strip(),
        )
        AuditLog.record(
            request.user,
            AuditLog.Action.CREATE,
            object_type='RescheduleRequest',
            object_id=req.pk,
            detail=f'Reschedule requested for {app.candidate.full_name} ({app.job.title}).',
        )
        # Notify HR: the application's creator when identifiable, else all
        # active HR users (same fallback spirit as dispatch_escalations).
        hr_recipients = User.objects.filter(role=Role.HR, is_active=True)
        creator = getattr(app, 'created_by', None)
        if creator is not None and creator.is_hr():
            hr_recipients = User.objects.filter(pk=creator.pk)
        link = reverse('accounts:reschedule_requests')
        for hr in hr_recipients:
            Notification.objects.create(
                recipient=hr,
                message=(
                    f'{request.user.get_full_name() or request.user.username} '
                    f'requests to reschedule {app.candidate.full_name} '
                    f'({app.job.title}) currently booked at '
                    f'{app.interview_at:%Y-%m-%d %H:%M} UTC.'
                ),
                link=link,
            )
        messages.success(request, 'Reschedule request sent to HR.')
        return redirect('accounts:my_calendar')


class RescheduleRequestListView(LoginRequiredMixin, ListView):
    """HR console for pending reschedule requests.

    Accept applies the FIRST proposed slot to the application (re-running
    the same availability/clash validation a direct booking would, so an
    accepted slot can never be one the save would reject). Decline just
    marks it. Interviewers get redirected home; management is read-only.
    """

    template_name = 'accounts/reschedule_requests.html'
    context_object_name = 'requests'

    def dispatch(self, request, *args, **kwargs):
        if not request.user.is_authenticated:
            return self.handle_no_permission()
        if not request.user.is_hr():
            return redirect('accounts:home')
        return super().dispatch(request, *args, **kwargs)

    def get_queryset(self):
        return (
            RescheduleRequest.objects
            .select_related('application__candidate', 'application__job', 'requested_by')
            .order_by('-created_at')
        )

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['pending_count'] = self.get_queryset().filter(status='pending').count()
        context['active_nav'] = 'calendar'
        return context

    def post(self, request, *args, **kwargs):
        if not request.user.is_hr():
            return redirect('accounts:home')
        req = get_object_or_404(
            RescheduleRequest,
            pk=request.POST.get('request_pk'),
            status=RescheduleRequest.Status.PENDING,
        )
        app = req.application
        decision = request.POST.get('decision')
        if decision == 'accept':
            proposed = req.proposed_slots or []
            if not proposed:
                messages.error(request, 'This request has no proposed slots left.')
                return redirect('accounts:reschedule_requests')
            from datetime import datetime as dt
            from datetime import timezone as dt_timezone

            try:
                new_slot = dt.fromisoformat(proposed[0])
                if timezone.is_naive(new_slot):
                    new_slot = timezone.make_aware(new_slot, dt_timezone.utc)
            except (ValueError, TypeError):
                messages.error(request, 'The proposed slot could not be parsed.')
                return redirect('accounts:reschedule_requests')
            if new_slot < timezone.now():
                messages.error(
                    request,
                    'The proposed slot is already in the past; decline it instead.',
                )
                return redirect('accounts:reschedule_requests')

            interviewer = app.assigned_to
            if not interviewer:
                messages.error(request, 'The application no longer has an assigned interviewer.')
                return redirect('accounts:reschedule_requests')

            with transaction.atomic():
                User.objects.select_for_update().get(pk=interviewer.pk)
                if not interviewer.is_available_at(new_slot):
                    messages.error(
                        request,
                        f'{interviewer.get_full_name() or interviewer.username} is '
                        f'not available at the proposed slot; it was NOT applied. '
                        f'Decline the request or pick another slot.',
                    )
                    return redirect('accounts:reschedule_requests')
                if interviewer.has_booking_clash(new_slot, exclude_pk=app.pk):
                    messages.error(
                        request,
                        f'{interviewer.get_full_name() or interviewer.username} has '
                        f'another booking too close to the proposed slot; it was '
                        f'NOT applied.',
                    )
                    return redirect('accounts:reschedule_requests')
                app.interview_at = new_slot
                app.save(update_fields=['interview_at', 'updated_at'])
                req.status = RescheduleRequest.Status.ACCEPTED
                req.save(update_fields=['status'])
            Notification.objects.create(
                recipient=req.requested_by,
                message=(
                    f'Your reschedule request for {app.candidate.full_name} '
                    f'({app.job.title}) was accepted. New slot: '
                    f'{new_slot:%Y-%m-%d %H:%M} UTC.'
                ),
                link=reverse('candidates:detail', kwargs={'pk': app.candidate_id}),
            )
            AuditLog.record(
                request.user,
                AuditLog.Action.UPDATE,
                object_type='RescheduleRequest',
                object_id=req.pk,
                detail=f'Accepted; slot moved to {new_slot:%Y-%m-%d %H:%M} UTC.',
            )
            messages.success(
                request,
                f'Reschedule accepted. Interview moved to {new_slot:%Y-%m-%d %H:%M} UTC.',
            )
        elif decision == 'decline':
            req.status = RescheduleRequest.Status.DECLINED
            req.save(update_fields=['status'])
            Notification.objects.create(
                recipient=req.requested_by,
                message=(
                    f'Your reschedule request for {app.candidate.full_name} '
                    f'({app.job.title}) was declined. The current slot '
                    f'({req.original_slot:%Y-%m-%d %H:%M} UTC) stays booked.'
                ),
                link=reverse('candidates:detail', kwargs={'pk': app.candidate_id}),
            )
            AuditLog.record(
                request.user,
                AuditLog.Action.UPDATE,
                object_type='RescheduleRequest',
                object_id=req.pk,
                detail='Declined.',
            )
            messages.info(request, 'Reschedule request declined.')
        else:
            messages.error(request, 'Unknown action.')
        return redirect('accounts:reschedule_requests')
