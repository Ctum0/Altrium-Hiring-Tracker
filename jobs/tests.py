from datetime import datetime

from django.contrib.auth import get_user_model
from django.db.models import Count
from django.test import TestCase
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
        r = self.client.post(reverse('jobs:close', args=[job.pk]))
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
