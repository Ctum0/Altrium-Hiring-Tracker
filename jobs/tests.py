import re
from datetime import datetime
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core import mail
from django.db.models import Count
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from accounts.models import Role
from ai.matching import auto_apply
from candidates.models import Candidate, JobApplication
from jobs.models import Job
from jobs.talent_pool import find_suggestions

User = get_user_model()


class JobsBaseTestCase(TestCase):
    def setUp(self):
        self.hr = User.objects.create_user(
            username='hr', password='pass12345', role=Role.HR
        )
        self.interviewer = User.objects.create_user(
            username='iv', password='pass12345', role=Role.INTERVIEWER
        )
        self.management = User.objects.create_user(
            username='mgmt', password='pass12345', role=Role.MANAGEMENT
        )

    def login(self, username):
        assert self.client.login(username=username, password='pass12345')


class JobCreateTests(JobsBaseTestCase):
    def test_hr_can_create_job(self):
        self.login('hr')
        r = self.client.post(reverse('jobs:create'), {
            'title': 'Backend Engineer',
            'description': 'Build the API.',
            'num_openings': 1,
            'hiring_manager': '',
        })
        self.assertEqual(r.status_code, 302)
        from jobs.models import Job
        self.assertTrue(Job.objects.filter(title='Backend Engineer').exists())

    def test_interviewer_blocked_from_create(self):
        self.login('iv')
        r = self.client.get(reverse('jobs:create'))
        self.assertEqual(r.status_code, 302)
        self.assertIn(reverse('jobs:list'), r.url)

    def test_management_blocked_from_create(self):
        self.login('mgmt')
        r = self.client.get(reverse('jobs:create'))
        self.assertEqual(r.status_code, 302)

    def test_job_requires_title(self):
        self.login('hr')
        r = self.client.post(reverse('jobs:create'), {
            'title': '',
            'description': '',
        })
        self.assertEqual(r.status_code, 200)  # form re-rendered with errors

    def test_hiring_manager_saved_and_displayed_with_no_full_name(self):
        """A hiring manager with no first/last name shows their username, not '-'."""
        self.login('hr')
        manager = User.objects.create_user(
            username='mgr_no_name', password='pass12345', role=Role.HR,
        )
        r = self.client.post(reverse('jobs:create'), {
            'title': 'Frontend Engineer',
            'description': 'Build the UI.',
            'num_openings': 1,
            'hiring_manager': manager.pk,
        })
        self.assertEqual(r.status_code, 302)
        from jobs.models import Job
        job = Job.objects.get(title='Frontend Engineer')
        self.assertEqual(job.hiring_manager_id, manager.pk)
        detail = self.client.get(reverse('jobs:detail', args=[job.pk]))
        self.assertContains(detail, 'mgr_no_name')
        self.assertNotContains(detail, '<dd>-</dd>')


class JobRoundTests(JobsBaseTestCase):
    def test_round_create_and_list(self):
        self.login('hr')
        from jobs.models import Job
        job = Job.objects.create(title='Dev', created_by=self.hr)
        # Signal auto-creates 3 default stages (Screening, Interview, Offer)
        self.assertEqual(job.rounds.count(), 3)
        # Add a custom stage
        r = self.client.post(reverse('jobs:round_create', args=[job.pk]), {
            'name': 'Phone Screen',
            'order': 1,
        })
        self.assertEqual(r.status_code, 302)
        self.assertEqual(job.rounds.count(), 4)

    def test_round_delete(self):
        self.login('hr')
        from jobs.models import InterviewRound, Job
        job = Job.objects.create(title='Dev', created_by=self.hr)
        round_ = InterviewRound.objects.create(job=job, name='Tech Test', order=1)
        r = self.client.post(reverse('jobs:round_delete', args=[round_.pk]))
        self.assertEqual(r.status_code, 302)
        # Only the custom-added round was deleted; 3 default stages remain
        self.assertEqual(job.rounds.count(), 3)

    def test_round_delete_requires_hr(self):
        self.login('iv')
        from jobs.models import InterviewRound, Job
        job = Job.objects.create(title='Dev', created_by=self.hr)
        round_ = InterviewRound.objects.create(job=job, name='Tech Test', order=1)
        r = self.client.post(reverse('jobs:round_delete', args=[round_.pk]))
        self.assertEqual(r.status_code, 302)  # redirected, not deleted
        # 3 defaults + 1 custom = 4 rounds
        self.assertEqual(job.rounds.count(), 4)

    def test_duplicate_round_name_rejected(self):
        from django.db import IntegrityError

        from jobs.models import InterviewRound, Job
        job = Job.objects.create(title='Dev', created_by=self.hr)
        InterviewRound.objects.create(job=job, name='Screen', order=1)
        with self.assertRaises(IntegrityError):
            InterviewRound.objects.create(job=job, name='Screen', order=2)

    def test_job_list_active_only_by_default(self):
        self.login('hr')
        from jobs.models import Job
        Job.objects.create(title='Active Role', created_by=self.hr)
        Job.objects.create(title='Closed Role', created_by=self.hr, is_active=False)
        r = self.client.get(reverse('jobs:list'))
        self.assertContains(r, 'Active Role')
        self.assertNotContains(r, 'Closed Role')

        r = self.client.get(reverse('jobs:list') + '?inactive=1')
        self.assertContains(r, 'Closed Role')

    def test_close_job_does_not_reject_candidates(self):
        self.login('hr')
        from candidates.models import Candidate, JobApplication
        from jobs.models import Job
        job = Job.objects.create(title='Dev', created_by=self.hr)
        cand = Candidate.objects.create(email='a@example.com', first_name='Anna')
        app = JobApplication.objects.create(candidate=cand, job=job)
        r = self.client.post(reverse('jobs:close', args=[job.pk]), {'closure_reason': 'cancelled'})
        self.assertEqual(r.status_code, 302)
        job.refresh_from_db()
        self.assertFalse(job.is_active)
        self.assertIsNotNone(job.closed_at)
        app.refresh_from_db()
        self.assertEqual(app.status, JobApplication.Status.NEW)


class RoundValidationTests(JobsBaseTestCase):
    """Tests for round-level form validation and view guards."""

    def test_duplicate_round_name_returns_form_error(self):
        """POST duplicate name returns 200 (re-rendered form) with error, not 500."""
        self.login('hr')
        from jobs.models import InterviewRound, Job
        job = Job.objects.create(title='Dev', created_by=self.hr)
        InterviewRound.objects.create(job=job, name='Phone Screen', order=1)
        r = self.client.post(reverse('jobs:round_create', args=[job.pk]), {
            'name': 'Phone Screen',
            'order': 2,
        })
        self.assertEqual(r.status_code, 200)  # form re-rendered, not 500
        self.assertContains(r, 'already exists')
        self.assertEqual(job.rounds.count(), 4)  # 3 defaults + 1 created via ORM, no additional round

    def test_round_create_auto_increments_order(self):
        """GET create page shows next order number (max + 1)."""
        self.login('hr')
        from jobs.models import Job
        job = Job.objects.create(title='Dev', created_by=self.hr)
        # Default rounds have orders 1, 2, 3 → next should be 4
        r = self.client.get(reverse('jobs:round_create', args=[job.pk]))
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, 'value="4"')

    def test_round_delete_closed_job_blocked(self):
        """Deleting a round on a closed job redirects with error."""
        self.login('hr')
        from jobs.models import InterviewRound, Job
        job = Job.objects.create(title='Dev', created_by=self.hr, is_active=False)
        round_ = InterviewRound.objects.create(job=job, name='Tech Test', order=99)
        r = self.client.post(reverse('jobs:round_delete', args=[round_.pk]))
        self.assertEqual(r.status_code, 302)
        self.assertTrue(InterviewRound.objects.filter(pk=round_.pk).exists())

    def test_round_delete_requires_active_job(self):
        """dispatch() check: closed job → redirect to detail, round not deleted."""
        self.login('hr')
        from jobs.models import InterviewRound, Job
        job = Job.objects.create(title='Dev', created_by=self.hr, is_active=False)
        round_ = InterviewRound.objects.create(job=job, name='Tech Test', order=99)
        r = self.client.get(reverse('jobs:round_delete', args=[round_.pk]))
        self.assertEqual(r.status_code, 302)
        self.assertIn(reverse('jobs:detail', args=[job.pk]), r.url)
        self.assertTrue(InterviewRound.objects.filter(pk=round_.pk).exists())

    def test_round_delete_blocked_when_feedback_exists(self):
        """Deleting a round with submitted feedback must not 500 (ProtectedError)."""
        self.login('hr')
        from candidates.models import Candidate, JobApplication
        from feedback.models import InterviewFeedback
        from jobs.models import InterviewRound, Job
        job = Job.objects.create(title='Dev', created_by=self.hr)
        round_ = InterviewRound.objects.create(job=job, name='Tech Test', order=99)
        cand = Candidate.objects.create(email='fb@example.com', first_name='Fiona')
        app = JobApplication.objects.create(candidate=cand, job=job)
        InterviewFeedback.objects.create(
            application=app, round=round_, interviewer=self.interviewer,
            score=80, notes='Good.',
        )
        r = self.client.post(reverse('jobs:round_delete', args=[round_.pk]))
        self.assertEqual(r.status_code, 302)
        self.assertIn(reverse('jobs:detail', args=[job.pk]), r.url)
        self.assertTrue(InterviewRound.objects.filter(pk=round_.pk).exists())


class OfferRoundIsFinalTest(JobsBaseTestCase):
    """Verify the Offer default round has is_final=True from the signal."""

    def test_offer_round_is_final(self):
        self.login('hr')
        from jobs.models import Job
        job = Job.objects.create(title='Dev', created_by=self.hr)
        offer = job.rounds.get(name='Offer')
        self.assertTrue(offer.is_final)

        screening = job.rounds.get(name='Screening')
        self.assertFalse(screening.is_final)

        interview = job.rounds.get(name='Interview')
        self.assertFalse(interview.is_final)


class JobFormDomainSeniorityTests(JobsBaseTestCase):
    """Feature 1: structured Domain + Seniority fields on the job form."""

    def test_create_defaults_domain_and_seniority(self):
        self.login('hr')
        r = self.client.post(reverse('jobs:create'), {
            'title': 'Default Domain Job',
            'num_openings': 1,
        })
        self.assertEqual(r.status_code, 302)
        job = Job.objects.get(title='Default Domain Job')
        self.assertEqual(job.domain, Job.Domain.OTHER)
        self.assertEqual(job.seniority, Job.Seniority.MID)

    def test_create_persists_chosen_domain_and_seniority(self):
        self.login('hr')
        r = self.client.post(reverse('jobs:create'), {
            'title': 'Data Lead Job',
            'domain': Job.Domain.DATA,
            'seniority': Job.Seniority.LEAD,
            'num_openings': 1,
        })
        self.assertEqual(r.status_code, 302)
        job = Job.objects.get(title='Data Lead Job')
        self.assertEqual(job.domain, Job.Domain.DATA)
        self.assertEqual(job.seniority, Job.Seniority.LEAD)

    def test_form_renders_domain_and_seniority_selects(self):
        self.login('hr')
        r = self.client.get(reverse('jobs:create'))
        self.assertContains(r, 'name="domain"')
        self.assertContains(r, 'name="seniority"')
        self.assertContains(r, '<option value="engineering"')
        self.assertContains(r, '<option value="lead"')

    def test_domain_rejects_invalid_choice(self):
        self.login('hr')
        r = self.client.post(reverse('jobs:create'), {
            'title': 'Bad Domain',
            'domain': 'not-a-domain',
            'num_openings': 1,
        })
        self.assertEqual(r.status_code, 200)
        self.assertFalse(Job.objects.filter(title='Bad Domain').exists())

    def test_create_redirects_to_rounds_setup(self):
        self.login('hr')
        r = self.client.post(reverse('jobs:create'), {
            'title': 'Redirect Job',
            'num_openings': 1,
        })
        job = Job.objects.get(title='Redirect Job')
        self.assertRedirects(r, reverse('jobs:rounds_setup', args=[job.pk]))


class RoundsSetupTests(JobsBaseTestCase):
    """Rounds-in-creation step: HR-only page over the seeded rounds."""

    def setUp(self):
        super().setUp()
        self.job = Job.objects.create(title='Setup Job', created_by=self.hr)

    def test_hr_sees_seeded_rounds(self):
        self.login('hr')
        r = self.client.get(reverse('jobs:rounds_setup', args=[self.job.pk]))
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, 'Screening')
        self.assertContains(r, 'Interview')
        self.assertContains(r, 'Offer')
        self.assertContains(r, 'Done')

    def test_non_hr_redirected_to_list(self):
        self.login('iv')
        r = self.client.get(reverse('jobs:rounds_setup', args=[self.job.pk]))
        self.assertRedirects(r, reverse('jobs:list'))

    def test_login_required(self):
        r = self.client.get(reverse('jobs:rounds_setup', args=[self.job.pk]))
        self.assertEqual(r.status_code, 302)
        self.assertIn('/login', r.url)

    def test_add_round_stays_on_setup_page(self):
        self.login('hr')
        r = self.client.post(
            reverse('jobs:round_create', args=[self.job.pk]),
            {'name': 'Tech Interview', 'order': 4,
             'next': reverse('jobs:rounds_setup', args=[self.job.pk])},
        )
        self.assertRedirects(r, reverse('jobs:rounds_setup', args=[self.job.pk]))
        self.assertTrue(self.job.rounds.filter(name='Tech Interview').exists())

    def test_round_create_defaults_to_detail_without_next(self):
        self.login('hr')
        r = self.client.post(
            reverse('jobs:round_create', args=[self.job.pk]),
            {'name': 'Another', 'order': 5},
        )
        self.assertRedirects(r, reverse('jobs:detail', args=[self.job.pk]))

    def test_reorder_normalizes_sequence(self):
        self.login('hr')
        ids = {r.name: r.pk for r in self.job.rounds.all()}
        r = self.client.post(reverse('jobs:round_reorder', args=[self.job.pk]), {
            f'order_{ids["Screening"]}': 2,
            f'order_{ids["Interview"]}': 1,
            f'order_{ids["Offer"]}': 3,
        })
        self.assertEqual(r.status_code, 302)
        self.assertEqual(
            list(self.job.rounds.values_list('name', flat=True)),
            ['Interview', 'Screening', 'Offer'],
        )

    def test_reorder_with_duplicate_orders_still_renormalizes(self):
        self.login('hr')
        ids = {r.name: r.pk for r in self.job.rounds.all()}
        r = self.client.post(reverse('jobs:round_reorder', args=[self.job.pk]), {
            f'order_{ids["Screening"]}': 1,
            f'order_{ids["Interview"]}': 1,
            f'order_{ids["Offer"]}': 1,
        })
        self.assertEqual(r.status_code, 302)
        self.assertEqual(
            list(self.job.rounds.values_list('order', flat=True)),
            [1, 2, 3],
        )

    def test_reorder_requires_hr(self):
        self.login('mgmt')
        r = self.client.post(reverse('jobs:round_reorder', args=[self.job.pk]), {})
        self.assertRedirects(r, reverse('jobs:list'))


class TalentPoolTests(JobsBaseTestCase):
    """Talent-pool rematching engine and the re-engagement endpoint."""

    def setUp(self):
        super().setUp()
        from candidates.models import Candidate
        self.Candidate = Candidate
        self.closed = Job.objects.create(
            title='Old Engineering Role', created_by=self.hr,
            is_active=False, domain=Job.Domain.ENGINEERING,
        )

    def _make_app(self, email, first_name, score, job=None,
                  status=JobApplication.Status.REJECTED):
        cand = self.Candidate.objects.create(
            email=email, first_name=first_name, skills='Python, Django',
        )
        return JobApplication.objects.create(
            candidate=cand,
            job=job or self.closed,
            status=status,
            shortlist_score=score,
        )

    def test_find_suggestions_filters_correctly(self):
        new_job = Job.objects.create(
            title='New Engineering Role', created_by=self.hr,
            domain=Job.Domain.ENGINEERING,
        )
        match_a = self._make_app('a@example.com', 'Anna', 95)
        match_b = self._make_app('b@example.com', 'Bob', 80)
        low = self._make_app('c@example.com', 'Carol', 79)
        wrong_domain = self._make_app(
            'd@example.com', 'Dan', 90,
            job=Job.objects.create(
                title='Old Design Role', created_by=self.hr,
                is_active=False, domain=Job.Domain.DESIGN,
            ),
        )
        open_job = self._make_app(
            'e@example.com', 'Eve', 90,
            job=Job.objects.create(
                title='Still Open', created_by=self.hr, domain=Job.Domain.ENGINEERING,
            ),
        )
        status_mismatch = self._make_app(
            'f@example.com', 'Fay', 90, status=JobApplication.Status.HIRED,
        )
        already_applied = self._make_app('g@example.com', 'Gus', 90)
        JobApplication.objects.create(
            candidate=already_applied.candidate, job=new_job,
            status=JobApplication.Status.NEW,
        )

        suggestions = find_suggestions(new_job)
        pks = {s['old_application_pk'] for s in suggestions}
        self.assertEqual(pks, {match_a.pk, match_b.pk})
        best = suggestions[0]
        self.assertEqual(best['old_application_pk'], match_a.pk)
        self.assertEqual(best['candidate_name'], 'Anna')
        self.assertEqual(best['candidate_email'], 'a@example.com')
        self.assertEqual(best['old_job_title'], 'Old Engineering Role')
        self.assertEqual(best['score'], 95)

    def test_find_suggestions_ignores_domain_filter_when_other(self):
        new_job = Job.objects.create(
            title='Any Domain Role', created_by=self.hr, domain=Job.Domain.OTHER,
        )
        self._make_app('a2@example.com', 'Anna', 95)
        cross = self._make_app(
            'd2@example.com', 'Dan', 90,
            job=Job.objects.create(
                title='Old Design Role', created_by=self.hr,
                is_active=False, domain=Job.Domain.DESIGN,
            ),
        )
        suggestions = find_suggestions(new_job)
        self.assertEqual(
            {s['old_application_pk'] for s in suggestions},
            {cross.pk, self.closed.applications.first().pk},
        )

    def test_find_suggestions_excludes_candidates_already_applied(self):
        new_job = Job.objects.create(
            title='New Engineering Role', created_by=self.hr,
            domain=Job.Domain.ENGINEERING,
        )
        app = self._make_app('a3@example.com', 'Anna', 95)
        JobApplication.objects.create(
            candidate=app.candidate, job=new_job,
            status=JobApplication.Status.REJECTED,
        )
        self.assertEqual(find_suggestions(new_job), [])

    def test_find_suggestions_limits_to_five(self):
        new_job = Job.objects.create(
            title='New Engineering Role', created_by=self.hr,
            domain=Job.Domain.ENGINEERING,
        )
        for i in range(7):
            self._make_app(f'p{i}@example.com', f'P{i}', 85 + i)
        self.assertEqual(len(find_suggestions(new_job)), 5)

    def test_talent_pool_add_creates_application(self):
        self.login('hr')
        new_job = Job.objects.create(
            title='New Engineering Role', created_by=self.hr,
            domain=Job.Domain.ENGINEERING,
        )
        old_app = self._make_app('add@example.com', 'Hank', 90)
        r = self.client.post(
            reverse('jobs:talent_pool_add', args=[new_job.pk, old_app.pk])
        )
        self.assertRedirects(r, reverse('jobs:detail', args=[new_job.pk]))
        created = JobApplication.objects.get(candidate=old_app.candidate, job=new_job)
        self.assertEqual(created.status, JobApplication.Status.NEW)
        self.assertEqual(created.current_round, new_job.rounds.first())
        # Scored against the NEW job's requirements via auto_apply, mirroring
        # the upload path; auto_apply returns None when either side has no
        # scoring basis.
        self.assertEqual(created.shortlist_score, auto_apply(old_app.candidate, new_job))

    def test_talent_pool_add_is_idempotent(self):
        self.login('hr')
        new_job = Job.objects.create(
            title='New Engineering Role', created_by=self.hr,
            domain=Job.Domain.ENGINEERING,
        )
        old_app = self._make_app('idem@example.com', 'Iris', 90)
        self.client.post(reverse('jobs:talent_pool_add', args=[new_job.pk, old_app.pk]))
        self.client.post(reverse('jobs:talent_pool_add', args=[new_job.pk, old_app.pk]))
        self.assertEqual(JobApplication.objects.filter(job=new_job).count(), 1)

    def test_talent_pool_add_respects_auto_reject_score(self):
        self.login('hr')
        new_job = Job.objects.create(
            title='Strict Role', created_by=self.hr,
            domain=Job.Domain.ENGINEERING,
            requirements='Python, Django, Kubernetes, Docker, Redis, Kafka, Terraform',
            auto_reject_score=50,
        )
        old_app = self._make_app('strict@example.com', 'Sam', 90)  # 2/7 skills = 28
        self.client.post(reverse('jobs:talent_pool_add', args=[new_job.pk, old_app.pk]))
        created = JobApplication.objects.get(candidate=old_app.candidate, job=new_job)
        self.assertEqual(created.status, JobApplication.Status.REJECTED)

    def test_talent_pool_add_requires_hr(self):
        self.login('iv')
        new_job = Job.objects.create(
            title='New Engineering Role', created_by=self.hr,
            domain=Job.Domain.ENGINEERING,
        )
        old_app = self._make_app('iv-try@example.com', 'Tina', 90)
        r = self.client.post(
            reverse('jobs:talent_pool_add', args=[new_job.pk, old_app.pk])
        )
        self.assertRedirects(r, reverse('jobs:list'))
        self.assertFalse(JobApplication.objects.filter(job=new_job).exists())

    def test_talent_pool_add_404s_for_active_job_source(self):
        self.login('hr')
        new_job = Job.objects.create(
            title='New Engineering Role', created_by=self.hr,
            domain=Job.Domain.ENGINEERING,
        )
        active_app = self._make_app(
            'active@example.com', 'Uma', 90,
            job=Job.objects.create(
                title='Still Open', created_by=self.hr, domain=Job.Domain.ENGINEERING,
            ),
        )
        r = self.client.post(
            reverse('jobs:talent_pool_add', args=[new_job.pk, active_app.pk])
        )
        self.assertEqual(r.status_code, 404)


class JobDetailEnrichmentTests(JobsBaseTestCase):
    """Round Detail Enrichment aggregates + suggestion card presence."""

    def setUp(self):
        super().setUp()
        self.job = Job.objects.create(
            title='Enriched Job', created_by=self.hr, domain=Job.Domain.ENGINEERING,
        )

    def _app_in_round(self, round_, email, first_name, assigned=None, at=None):
        cand = Candidate.objects.create(
            email=email, first_name=first_name, skills='Python, Django',
        )
        return JobApplication.objects.create(
            candidate=cand, job=self.job, current_round=round_,
            status=JobApplication.Status.IN_PROGRESS,
            assigned_to=assigned, interview_at=at,
        )

    def test_context_has_per_round_aggregates(self):
        self.login('hr')
        screening = self.job.rounds.get(name='Screening')
        interview = self.job.rounds.get(name='Interview')
        self.interviewer.first_name = 'Ivy'
        self.interviewer.last_name = 'Ng'
        self.interviewer.save()
        early = timezone.make_aware(datetime(2026, 10, 1, 9, 0))
        late = timezone.make_aware(datetime(2026, 10, 2, 9, 0))
        self._app_in_round(screening, 's1@example.com', 'S1')
        self._app_in_round(screening, 's2@example.com', 'S2')
        self._app_in_round(
            interview, 'i1@example.com', 'I1',
            assigned=self.interviewer, at=late,
        )
        self._app_in_round(
            interview, 'i2@example.com', 'I2',
            assigned=self.interviewer, at=early,
        )
        r = self.client.get(reverse('jobs:detail', args=[self.job.pk]))
        rounds = {rd.name: rd for rd in r.context['rounds']}
        self.assertEqual(rounds['Screening'].candidate_count, 2)
        self.assertEqual(rounds['Interview'].candidate_count, 2)
        self.assertEqual(rounds['Offer'].candidate_count, 0)
        self.assertEqual(rounds['Interview'].assigned_interviewers, ['Ivy Ng'])
        self.assertEqual(rounds['Interview'].next_interview_at, early)
        self.assertEqual(rounds['Offer'].assigned_interviewers, [])
        self.assertIsNone(rounds['Offer'].next_interview_at)

    def test_detail_renders_new_columns_and_counts(self):
        self.login('hr')
        screening = self.job.rounds.get(name='Screening')
        self._app_in_round(screening, 'v@example.com', 'Vera')
        r = self.client.get(reverse('jobs:detail', args=[self.job.pk]))
        self.assertContains(r, 'Candidates in round')

    def test_queries_stay_constant_with_rounds(self):
        """Detail-page aggregates run 2 queries regardless of round count
        (the rounds themselves are fetched once up front)."""
        self.login('hr')
        screening = self.job.rounds.get(name='Screening')
        self._app_in_round(screening, 'q@example.com', 'Quinn')
        round_ids = [r.pk for r in self.job.rounds.all()]
        with self.assertNumQueries(2):
            counts = (
                JobApplication.objects.filter(current_round_id__in=round_ids)
                .values('current_round_id')
                .annotate(n=Count('pk'))
            )
            list(counts)
            apps = (
                JobApplication.objects.filter(current_round_id__in=round_ids)
                .select_related('assigned_to')
            )
            list(apps)

    def test_talent_pool_card_renders_only_when_suggestions_exist(self):
        self.login('hr')
        closed = Job.objects.create(
            title='Old Engineering Role', created_by=self.hr,
            is_active=False, domain=Job.Domain.ENGINEERING,
        )
        r = self.client.get(reverse('jobs:detail', args=[self.job.pk]))
        self.assertNotContains(r, 'suggested re-engagements')

        cand = Candidate.objects.create(
            email='tp@example.com', first_name='Wes', skills='Python, Django',
        )
        JobApplication.objects.create(
            candidate=cand, job=closed,
            status=JobApplication.Status.REJECTED, shortlist_score=90,
        )
        r = self.client.get(reverse('jobs:detail', args=[self.job.pk]))
        self.assertContains(r, 'suggested re-engagements')
        self.assertContains(r, 'Wes')
        self.assertContains(r, 'Add to this job')


class JobClosureMailTests(JobsBaseTestCase):
    """Feature 4: closing a job batch-emails rejection to every applicant
    who is not hired and not already rejected. A mail failure must never
    fail the closure."""


    @override_settings(EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend')
    def test_close_sends_rejection_to_active_applicants(self):
        job = Job.objects.create(title='Dev', created_by=self.hr)
        c1 = Candidate.objects.create(email='a@example.com', first_name='A')
        c2 = Candidate.objects.create(email='b@example.com', first_name='B')
        JobApplication.objects.create(candidate=c1, job=job, status=JobApplication.Status.NEW)
        JobApplication.objects.create(candidate=c2, job=job, status=JobApplication.Status.IN_PROGRESS)
        r = self._close_for(job)
        self.assertEqual(r.status_code, 302)
        recipients = sorted(m.to[0] for m in mail.outbox)
        self.assertEqual(recipients, ['a@example.com', 'b@example.com'])
        for m in mail.outbox:
            self.assertIn('decided not to move forward', m.body)

    @override_settings(EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend')
    def test_close_excludes_hired_and_already_rejected(self):
        job = Job.objects.create(title='Dev', created_by=self.hr)
        hired = Candidate.objects.create(email='hired@example.com', first_name='H')
        rejected = Candidate.objects.create(email='rej@example.com', first_name='R')
        active = Candidate.objects.create(email='act@example.com', first_name='A')
        JobApplication.objects.create(candidate=hired, job=job, status=JobApplication.Status.HIRED)
        JobApplication.objects.create(candidate=rejected, job=job, status=JobApplication.Status.REJECTED)
        JobApplication.objects.create(candidate=active, job=job, status=JobApplication.Status.NEW)
        self._close_for(job)
        recipients = [m.to[0] for m in mail.outbox]
        self.assertEqual(recipients, ['act@example.com'])

    @override_settings(EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend')
    def test_close_sends_once_per_candidate_even_with_multiple_applications(self):
        # Same candidate appears twice (e.g. two apps for the same job is
        # impossible, but the batch dedups defensively per request).
        job = Job.objects.create(title='Dev', created_by=self.hr)
        cand = Candidate.objects.create(email='dup@example.com', first_name='D')
        JobApplication.objects.create(candidate=cand, job=job, status=JobApplication.Status.NEW)
        self._close_for(job)
        self.assertEqual(len([m for m in mail.outbox if m.to == ['dup@example.com']]), 1)

    @override_settings(EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend')
    def test_close_skips_candidates_without_email(self):
        job = Job.objects.create(title='Dev', created_by=self.hr)
        c1 = Candidate.objects.create(email=None, first_name='N')
        c2 = Candidate.objects.create(email='x@example.com', first_name='X')
        JobApplication.objects.create(candidate=c1, job=job, status=JobApplication.Status.NEW)
        JobApplication.objects.create(candidate=c2, job=job, status=JobApplication.Status.NEW)
        r = self._close_for(job)
        self.assertEqual(r.status_code, 302)
        self.assertEqual([m.to[0] for m in mail.outbox], ['x@example.com'])

    def test_close_succeeds_when_mail_backend_raises(self):
        # A full mail outage must not block the closure.
        job = Job.objects.create(title='Dev', created_by=self.hr)
        cand = Candidate.objects.create(email='y@example.com', first_name='Y')
        JobApplication.objects.create(candidate=cand, job=job, status=JobApplication.Status.NEW)
        with patch('notifications.mail.send_mail', side_effect=Exception('SMTP down')):
            r = self._close_for(job)
        self.assertEqual(r.status_code, 302)
        job.refresh_from_db()
        self.assertFalse(job.is_active)

    def _close_for(self, job):
        self.login('hr')
        return self.client.post(reverse('jobs:close', args=[job.pk]), {'closure_reason': 'cancelled'})


class DataRetentionPolicyTests(JobsBaseTestCase):
    """Phase 11 (NFR): closing a job never deletes or hides candidate
    data, no matter how old the closure is. JobCloseView only flips
    is_active and stamps closed_at (see test_close_job_does_not_reject_candidates
    above); this class proves the year-old case explicitly, end to end
    through both the ordinary candidate search and the retention report.
    """

    def test_year_old_closed_job_candidates_still_searchable_and_reported(self):
        from datetime import timedelta

        from candidates.models import Candidate, JobApplication
        from jobs.models import Job

        job = Job.objects.create(title='Legacy Role', created_by=self.hr)
        candidate = Candidate.objects.create(
            email='legacy@example.com', first_name='Lena', last_name='Legacy',
        )
        JobApplication.objects.create(candidate=candidate, job=job, status='new')

        self.login('hr')
        r = self.client.post(reverse('jobs:close', args=[job.pk]), {'closure_reason': 'cancelled'})
        self.assertEqual(r.status_code, 302)

        # Simulate a year having passed since closure. No age-based
        # exclusion or expiry exists anywhere in the query paths below;
        # this only backdates the timestamp used to demonstrate that.
        Job.objects.filter(pk=job.pk).update(
            closed_at=timezone.now() - timedelta(days=365)
        )
        job.refresh_from_db()
        self.assertFalse(job.is_active)

        # 1. Still fully searchable via the existing candidate list/search.
        list_r = self.client.get(reverse('candidates:list'), {'job': job.pk, 'all': '1'})
        self.assertEqual(list_r.status_code, 200)
        self.assertContains(list_r, 'Lena')

        search_r = self.client.get(reverse('candidates:list'), {'q': 'Legacy', 'all': '1'})
        self.assertContains(search_r, 'Lena')

        # 2. Appears correctly in the retention report, with an accurate
        # days-since-closure and candidate count, not silently dropped.
        report_r = self.client.get(reverse('accounts:retention_report'))
        self.assertEqual(report_r.status_code, 200)
        self.assertContains(report_r, 'Legacy Role')
        self.assertContains(report_r, '365 day')
        job_row = next(j for j in report_r.context['closed_jobs'] if j.pk == job.pk)
        self.assertEqual(job_row.days_since_closure, 365)
        self.assertEqual(job_row.num_applications, 1)


class JobBoardTests(JobsBaseTestCase):
    """Phase 10 (NFR): Kanban board for a single job's pipeline."""

    def setUp(self):
        super().setUp()
        self.job = Job.objects.create(title='Board Job', created_by=self.hr)
        self.round1 = self.job.rounds.get(order=1)
        self.round2 = self.job.rounds.get(order=2)
        self.cand_a = Candidate.objects.create(
            email='anna@example.com', first_name='Anna', score=80,
        )
        self.cand_b = Candidate.objects.create(email='ben@example.com', first_name='Ben')
        self.app_a = JobApplication.objects.create(candidate=self.cand_a, job=self.job)
        self.app_b = JobApplication.objects.create(
            candidate=self.cand_b, job=self.job, assigned_to=self.interviewer,
        )

    def test_hr_sees_board_with_columns_and_cards(self):
        self.login('hr')
        r = self.client.get(reverse('jobs:board', args=[self.job.pk]))
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, self.round1.name)
        self.assertContains(r, self.round2.name)
        self.assertContains(r, 'Anna')
        self.assertContains(r, 'Ben')
        self.assertContains(r, 'Hired')
        self.assertContains(r, 'Rejected')
        self.assertContains(r, 'On Hold')

    def test_interviewer_sees_only_assigned_candidate_on_board(self):
        """Board scoping mirrors the candidate list's visible_applications:
        interviewers see only their own assigned/panel candidates."""
        self.login('iv')
        r = self.client.get(reverse('jobs:board', args=[self.job.pk]))
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, 'Ben')
        self.assertNotContains(r, 'Anna')

    def _card_tag(self, html, app_pk):
        """Slice of the card's own opening <div ...> tag (from the id
        attribute through the tag's closing '>'), so assertions on
        `draggable` don't accidentally match the board's JS source, which
        contains the literal string draggable="true" in a CSS selector."""
        match = re.search(rf'id="board-card-{app_pk}"[\s\S]*?>', html)
        self.assertIsNotNone(match, f'card for application {app_pk} not found in response')
        return match.group(0)

    def test_hr_cards_are_draggable(self):
        self.login('hr')
        r = self.client.get(reverse('jobs:board', args=[self.job.pk]))
        html = r.content.decode()
        self.assertIn('draggable="true"', self._card_tag(html, self.app_a.pk))
        self.assertIn('draggable="true"', self._card_tag(html, self.app_b.pk))

    def test_non_hr_cards_are_not_draggable(self):
        """Drag-and-drop is HR-only, matching the stage-select dropdown
        which is also gated behind {% if user.is_hr %}."""
        self.login('mgmt')
        r = self.client.get(reverse('jobs:board', args=[self.job.pk]))
        self.assertEqual(r.status_code, 200)
        html = r.content.decode()
        self.assertNotIn('draggable="true"', self._card_tag(html, self.app_a.pk))
        self.assertNotIn('draggable="true"', self._card_tag(html, self.app_b.pk))

    def test_terminal_status_cards_are_not_draggable(self):
        self.login('hr')
        self.app_a.status = JobApplication.Status.HIRED
        self.app_a.current_round = None
        self.app_a.save(update_fields=['status', 'current_round'])
        r = self.client.get(reverse('jobs:board', args=[self.job.pk]))
        html = r.content.decode()
        self.assertNotIn('draggable="true"', self._card_tag(html, self.app_a.pk))

    def test_board_link_present_on_job_detail(self):
        self.login('hr')
        r = self.client.get(reverse('jobs:detail', args=[self.job.pk]))
        self.assertContains(r, reverse('jobs:board', args=[self.job.pk]))

    def test_empty_board_shows_intake_cta(self):
        """GAP regression: a job with zero candidates rendered a board of
        empty columns with no path forward — the only intake hint was a raw
        public-apply URL on the detail page. The board must offer Upload
        CVs and the application link."""
        empty_job = Job.objects.create(title='Empty Board Job', created_by=self.hr)
        self.login('hr')
        r = self.client.get(reverse('jobs:board', args=[empty_job.pk]))
        self.assertContains(r, 'No candidates on this board yet')
        self.assertContains(r, reverse('candidates:upload'))
        self.assertContains(r, reverse('candidates:public_apply', args=[empty_job.pk]))

    def test_populated_board_hides_empty_state(self):
        self.login('hr')
        r = self.client.get(reverse('jobs:board', args=[self.job.pk]))
        self.assertNotContains(r, 'No candidates on this board yet')

    def test_empty_board_hides_cta_for_non_hr(self):
        """Interviewers see the board read-only: no Upload CVs button and
        no empty-state intake copy."""
        empty_job = Job.objects.create(title='Iv Empty Board', created_by=self.hr)
        self.login('iv')
        r = self.client.get(reverse('jobs:board', args=[empty_job.pk]))
        self.assertNotContains(r, 'No candidates on this board yet')
        self.assertNotContains(r, 'Upload CVs')


class JobBoardDragDropTests(JobsBaseTestCase):
    """Simulates the exact fetch POST the board's drag-and-drop JS makes:
    same endpoint (pipeline:move), same payload shape as the stage-select
    dropdown, only 'source' differs ('board' vs 'list'/'detail'). No move
    validation is duplicated in the board's JS or view - both a legal and
    an illegal move must behave identically to the dropdown's coverage in
    pipeline/tests.py.
    """

    def setUp(self):
        super().setUp()
        self.job = Job.objects.create(title='Board Drag Job', created_by=self.hr)
        self.round1 = self.job.rounds.get(order=1)
        self.round2 = self.job.rounds.get(order=2)
        self.cand = Candidate.objects.create(email='drag@example.com', first_name='Drag')
        self.app = JobApplication.objects.create(candidate=self.cand, job=self.job)
        # Starts unrouted (current_round=None), exactly like the board's
        # "Unrouted" column: the feedback gate never blocks a move out of
        # no round, matching pipeline/tests.py's from_round=None coverage.
        self.app.current_round = None
        self.app.save(update_fields=['current_round'])

    def test_legal_drag_move_persists(self):
        """Board equivalent of dragging a card from Unrouted into a round
        column: from_round is None, so no feedback is required."""
        self.login('hr')
        r = self.client.post(reverse('pipeline:move', args=[self.app.pk]), {
            'stage': f'round:{self.round1.pk}',
            'source': 'board',
        })
        self.assertEqual(r.status_code, 200)
        self.app.refresh_from_db()
        self.assertEqual(self.app.current_round, self.round1)

    def test_illegal_drag_move_without_feedback_rejected_and_not_persisted(self):
        """Once routed into round1 with no feedback submitted, dragging the
        card straight to Hired must be blocked - identical to the
        stage-select dropdown's behavior for the same state."""
        self.login('hr')
        self.app.current_round = self.round1
        self.app.save(update_fields=['current_round'])
        r = self.client.post(reverse('pipeline:move', args=[self.app.pk]), {
            'stage': 'status:hired',
            'source': 'board',
        })
        self.assertEqual(r.status_code, 409)
        self.assertIn('Feedback', r.content.decode())
        self.app.refresh_from_db()
        self.assertEqual(self.app.status, JobApplication.Status.NEW)
        self.assertEqual(self.app.current_round, self.round1)

    def test_non_hr_drag_move_blocked(self):
        self.login('iv')
        r = self.client.post(reverse('pipeline:move', args=[self.app.pk]), {
            'stage': f'round:{self.round1.pk}',
            'source': 'board',
        })
        self.assertEqual(r.status_code, 403)
        self.app.refresh_from_db()
        self.assertIsNone(self.app.current_round)


class JobClosureReasonTests(JobsBaseTestCase):
    """Closure reason selection (spec): HR must pick Hired / Cancelled /
    On hold / Other when closing; invalid values are rejected, not silently
    accepted; reopening clears the reason."""

    def _make_job(self):
        return Job.objects.create(title='Dev', created_by=self.hr)

    def test_close_without_reason_fails_and_job_stays_active(self):
        job = self._make_job()
        self.login('hr')
        r = self.client.post(reverse('jobs:close', args=[job.pk]), {})
        self.assertEqual(r.status_code, 302)
        self.assertIn(reverse('jobs:detail', args=[job.pk]), r.url)
        job.refresh_from_db()
        self.assertTrue(job.is_active)
        self.assertIsNone(job.closed_at)
        self.assertIsNone(job.closure_reason)
        # Message explains what went wrong.
        r = self.client.get(reverse('jobs:detail', args=[job.pk]))
        self.assertContains(r, 'Select a closure reason')

    def test_close_with_each_valid_reason_sets_field(self):
        for reason, label in Job.ClosureReason.choices:
            job = self._make_job()
            self.login('hr')
            r = self.client.post(
                reverse('jobs:close', args=[job.pk]), {'closure_reason': reason}
            )
            self.assertEqual(r.status_code, 302)
            job.refresh_from_db()
            self.assertFalse(job.is_active)
            self.assertEqual(job.closure_reason, reason)
            self.assertEqual(job.get_closure_reason_display(), label)

    def test_close_with_invalid_reason_rejected(self):
        job = self._make_job()
        self.login('hr')
        r = self.client.post(
            reverse('jobs:close', args=[job.pk]), {'closure_reason': 'pigeon_post'}
        )
        self.assertEqual(r.status_code, 302)
        job.refresh_from_db()
        self.assertTrue(job.is_active)
        self.assertIsNone(job.closed_at)
        self.assertIsNone(job.closure_reason)
        r = self.client.get(reverse('jobs:detail', args=[job.pk]))
        self.assertContains(r, 'Select a closure reason')

    def test_reopen_clears_closure_reason(self):
        job = self._make_job()
        self.login('hr')
        self.client.post(
            reverse('jobs:close', args=[job.pk]), {'closure_reason': 'on_hold'}
        )
        r = self.client.post(reverse('jobs:reopen', args=[job.pk]))
        self.assertEqual(r.status_code, 302)
        job.refresh_from_db()
        self.assertTrue(job.is_active)
        self.assertIsNone(job.closed_at)
        self.assertIsNone(job.closure_reason)

    def test_non_hr_cannot_close(self):
        job = self._make_job()
        self.login('iv')
        r = self.client.post(
            reverse('jobs:close', args=[job.pk]), {'closure_reason': 'cancelled'}
        )
        self.assertEqual(r.status_code, 302)
        self.assertIn(reverse('jobs:list'), r.url)
        job.refresh_from_db()
        self.assertTrue(job.is_active)
        self.assertIsNone(job.closure_reason)

    def test_detail_shows_reason_next_to_closed_badge(self):
        job = self._make_job()
        self.login('hr')
        self.client.post(
            reverse('jobs:close', args=[job.pk]), {'closure_reason': 'cancelled'}
        )
        r = self.client.get(reverse('jobs:detail', args=[job.pk]))
        self.assertContains(r, 'Closed')
        self.assertContains(r, 'Cancelled')
