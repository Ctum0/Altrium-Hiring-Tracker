"""Seed realistic test data for manual testing.

Creates 3 job postings with different departments and requirements,
then populates candidates at various pipeline stages.
"""
from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand

from ai.matching import auto_apply
from candidates.models import Candidate, JobApplication
from jobs.models import InterviewRound, Job

User = get_user_model()

JOBS = [
    {
        'title': 'Senior Backend Engineer',
        'department': 'Engineering',
        'description': 'Build and scale our core API platform serving millions of requests.',
        'requirements': 'Python, Django, PostgreSQL, Docker, AWS',
    },
    {
        'title': 'Product Designer',
        'department': 'Design',
        'description': 'Design user experiences for our B2B SaaS platform.',
        'requirements': 'Figma, UX Research, Design Systems, Prototyping',
    },
    {
        'title': 'DevOps Engineer',
        'department': 'Engineering',
        'description': 'Manage our cloud infrastructure and CI/CD pipelines.',
        'requirements': 'AWS, Docker, Kubernetes, Terraform, CI/CD',
    },
]

CANDIDATES = [
    # Backend Engineer candidates
    ('Ada', 'Lovelace', 'ada@example.com', 'Python, Django, PostgreSQL, Docker, AWS', 'upload'),
    ('Grace', 'Hopper', 'grace@example.com', 'Python, COBOL, Debugging', 'LinkedIn'),
    ('Alan', 'Turing', 'alan@example.com', 'Python, Django, PostgreSQL', 'upload'),
    # Product Designer candidates
    ('Don', 'Norman', 'don@example.com',
     'UX Research, Design Systems, Figma, Prototyping', 'Dribbble'),
    ('Paula', 'Scher', 'paula@example.com', 'Figma, Typography, Branding', 'upload'),
    # DevOps candidates
    ('Linus', 'Torvalds', 'linus@example.com',
     'AWS, Docker, Kubernetes, Terraform, CI/CD, Linux', 'upload'),
    ('Brendan', 'Eich', 'brendan@example.com', 'JavaScript, Docker', 'Indeed'),
]


class Command(BaseCommand):
    help = 'Seed realistic test jobs and candidates at various pipeline stages.'

    def handle(self, *args, **options):
        hr = User.objects.get(username='hr_demo')
        iv = User.objects.get(username='iv_demo')
        self.stdout.write('Seeding test data...')

        job_map = {}
        for spec in JOBS:
            job, created = Job.objects.get_or_create(
                title=spec['title'],
                defaults={**spec, 'created_by': hr},
            )
            job_map[job.title] = job
            if created:
                InterviewRound.objects.create(job=job, name='Phone Screen', order=1)
                InterviewRound.objects.create(job=job, name='Technical Interview', order=2)
                InterviewRound.objects.create(job=job, name='Final Round', order=3)
                self.stdout.write(f'  Created job: {job.title}')
            else:
                self.stdout.write(f'  Job already exists: {job.title}')

        # Backend candidates
        self._place(CANDIDATES[0], job_map['Senior Backend Engineer'], hr, iv,
                    round_idx=1, status='in_progress')
        self._place(CANDIDATES[1], job_map['Senior Backend Engineer'], hr, iv,
                    round_idx=0, status='rejected')
        self._place(CANDIDATES[2], job_map['Senior Backend Engineer'], hr, None,
                    round_idx=0, status='shortlisted')

        # Designer candidates
        self._place(CANDIDATES[3], job_map['Product Designer'], hr, None,
                    round_idx=0, status='new')
        self._place(CANDIDATES[4], job_map['Product Designer'], hr, None,
                    round_idx=0, status='rejected')

        # DevOps candidates
        self._place(CANDIDATES[5], job_map['DevOps Engineer'], hr, iv,
                    round_idx=2, status='hired')  # perfect match, hired
        self._place(CANDIDATES[6], job_map['DevOps Engineer'], hr, None,
                    round_idx=0, status='new')  # assigned to no one yet

        self.stdout.write(self.style.SUCCESS('Test data seeded.'))

    def _place(self, spec, job, hr, interviewer, round_idx=0, status='new'):
        first, last, email, skills, source = spec
        candidate, _ = Candidate.objects.get_or_create(
            email=email,
            defaults={
                'first_name': first, 'last_name': last,
                'skills': skills, 'source': source,
            },
        )
        auto_apply(candidate, job)
        rounds = list(job.rounds.all())
        current_round = rounds[round_idx] if rounds and round_idx < len(rounds) else None
        app, _ = JobApplication.objects.get_or_create(
            candidate=candidate, job=job,
            defaults={
                'status': status,
                'current_round': current_round,
                'assigned_to': interviewer,
            },
        )

        label = f'{first} {last}'
        self.stdout.write(f'  {label}: score={candidate.score} status={app.status}')
