"""Management command to clean duplicate/test jobs & candidates and seed a realistic enterprise recruitment dataset."""

import random
from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand
from django.db import transaction

from accounts.models import Role
from jobs.models import InterviewRound, Job
from candidates.models import Candidate, JobApplication
from feedback.models import InterviewFeedback

User = get_user_model()

REALISTIC_JOBS = [
    {
        'title': 'Senior Backend Engineer',
        'department': 'Engineering',
        'description': 'Lead Python/Django backend architecture, microservices, and database performance for our core enterprise hiring engine.',
        'requirements': 'Python, Django, PostgreSQL, Docker, Redis, REST API',
    },
    {
        'title': 'Frontend Engineer (React / HTMX)',
        'department': 'Engineering',
        'description': 'Craft modern, responsive, high-density glassmorphism UI components and interactive pipelines using HTMX, React, and CSS design tokens.',
        'requirements': 'React, JavaScript, HTMX, CSS, TypeScript, UI/UX',
    },
    {
        'title': 'DevOps & Infrastructure Lead',
        'department': 'Infrastructure',
        'description': 'Manage Cloudflare R2 object storage, Railway container deployment pipelines, PostgreSQL clustering, and security hardening.',
        'requirements': 'AWS, Docker, Kubernetes, Terraform, CI/CD, Linux, PostgreSQL',
    },
    {
        'title': 'Product Designer (UI / UX)',
        'department': 'Design',
        'description': 'Own user journey mapping, design system component libraries, and interactive prototyping for recruitment workspace surfaces.',
        'requirements': 'Figma, UI/UX, Design System, Prototyping, Agile',
    },
    {
        'title': 'QA Automation Lead',
        'department': 'Quality Assurance',
        'description': 'Develop automated test suites, Playwright e2e browser checks, and API regression testing for enterprise hiring workflows.',
        'requirements': 'Python, Pytest, Selenium, Playwright, Automated Testing, API Testing',
    },
]

REALISTIC_CANDIDATES = [
    {
        'first_name': 'Alexander',
        'last_name': 'Wright',
        'email': 'alexander.wright@example.com',
        'phone': '+1 415 555 0124',
        'skills': 'Python, Django, PostgreSQL, Docker, Redis, REST API',
        'score': 92,
        'job_index': 0,
        'status': 'interview',
        'notes': 'Strong technical depth in Django ORM and microservice design. Clear communication during technical architecture review.',
    },
    {
        'first_name': 'Sophia',
        'last_name': 'Chen',
        'email': 'sophia.chen@example.com',
        'phone': '+1 415 555 0188',
        'skills': 'Python, Django, FastAPI, SQL, Docker',
        'score': 86,
        'job_index': 0,
        'status': 'shortlisted',
        'notes': 'Solid backend experience. Good understanding of database indexing and async task queues.',
    },
    {
        'first_name': 'Marcus',
        'last_name': 'Vance',
        'email': 'marcus.vance@example.com',
        'phone': '+1 415 555 0199',
        'skills': 'React, JavaScript, HTMX, CSS, TypeScript, UI/UX',
        'score': 95,
        'job_index': 1,
        'status': 'hired',
        'notes': 'Exceptional frontend architect. Built custom design systems using OKLCH color spaces and HTMX state swaps.',
    },
    {
        'first_name': 'Elena',
        'last_name': 'Rostova',
        'email': 'elena.rostova@example.com',
        'phone': '+1 415 555 0244',
        'skills': 'JavaScript, React, CSS, HTML',
        'score': 78,
        'job_index': 1,
        'status': 'screening',
        'notes': 'Good foundation in React components. Needs further assessment on advanced HTMX and state management.',
    },
    {
        'first_name': 'David',
        'last_name': 'Miller',
        'email': 'david.miller@example.com',
        'phone': '+1 415 555 0311',
        'skills': 'AWS, Docker, Kubernetes, Terraform, CI/CD, Linux, PostgreSQL',
        'score': 90,
        'job_index': 2,
        'status': 'interview',
        'notes': 'Proven track record in managing production cloud deployments, multi-region failovers, and Docker pipelines.',
    },
    {
        'first_name': 'Aria',
        'last_name': 'Montgomery',
        'email': 'aria.montgomery@example.com',
        'phone': '+1 415 555 0377',
        'skills': 'AWS, Docker, Linux, Bash',
        'score': 74,
        'job_index': 2,
        'status': 'new',
        'notes': 'Promising Junior DevOps candidate with strong Linux administration fundamentals.',
    },
    {
        'first_name': 'Lucas',
        'last_name': 'Thorne',
        'email': 'lucas.thorne@example.com',
        'phone': '+1 415 555 0422',
        'skills': 'Figma, UI/UX, Design System, Prototyping, Agile',
        'score': 88,
        'job_index': 3,
        'status': 'shortlisted',
        'notes': 'Creative designer with strong portfolio in SaaS productivity dashboards and accessible dark theme interfaces.',
    },
    {
        'first_name': 'Nadia',
        'last_name': 'Patel',
        'email': 'nadia.patel@example.com',
        'phone': '+1 415 555 0499',
        'skills': 'Python, Pytest, Selenium, Playwright, Automated Testing, API Testing',
        'score': 94,
        'job_index': 4,
        'status': 'interview',
        'notes': 'Expert QA Lead with hands-on Playwright automation and regression test suite setup.',
    },
    {
        'first_name': 'Julian',
        'last_name': 'Hayes',
        'email': 'julian.hayes@example.com',
        'phone': '+1 415 555 0533',
        'skills': 'Python, Django, PostgreSQL, Redis',
        'score': 82,
        'job_index': 0,
        'status': 'screening',
        'notes': 'Solid Django developer. Showed good grasp of database optimization.',
    },
    {
        'first_name': 'Claire',
        'last_name': 'Dupont',
        'email': 'claire.dupont@example.com',
        'phone': '+1 415 555 0611',
        'skills': 'React, TypeScript, CSS',
        'score': 65,
        'job_index': 1,
        'status': 'rejected',
        'notes': 'Lacked required experience with complex frontend design systems and server-driven interactive components.',
    },
]


class Command(BaseCommand):
    help = 'Clean duplicate/test jobs and seed a clean enterprise hiring scenario.'

    def handle(self, *args, **options):
        self.stdout.write(self.style.WARNING('Starting database cleanup and enterprise seeding...'))

        with transaction.atomic():
            # Ensure demo users exist
            hr_user, _ = User.objects.get_or_create(
                username='hr_demo',
                defaults={'role': Role.HR, 'first_name': 'Hana', 'last_name': 'HR Manager'},
            )
            if not hr_user.check_password('testpass123'):
                hr_user.set_password('testpass123')
                hr_user.save()

            iv_user, _ = User.objects.get_or_create(
                username='iv_demo',
                defaults={'role': Role.INTERVIEWER, 'first_name': 'Ivan', 'last_name': 'Interviewer'},
            )
            if not iv_user.check_password('testpass123'):
                iv_user.set_password('testpass123')
                iv_user.save()

            mgmt_user, _ = User.objects.get_or_create(
                username='mgmt_demo',
                defaults={'role': Role.MANAGEMENT, 'first_name': 'Mia', 'last_name': 'Director'},
            )
            if not mgmt_user.check_password('testpass123'):
                mgmt_user.set_password('testpass123')
                mgmt_user.save()

            # Clean existing jobs & candidates
            JobApplication.objects.all().delete()
            InterviewFeedback.objects.all().delete()
            InterviewRound.objects.all().delete()
            Job.objects.all().delete()
            Candidate.objects.all().delete()

            self.stdout.write(self.style.SUCCESS('Cleared legacy test objects.'))

            # Create 5 core enterprise jobs
            created_jobs = []
            for spec in REALISTIC_JOBS:
                job = Job.objects.create(
                    title=spec['title'],
                    department=spec['department'],
                    description=spec['description'],
                    requirements=spec['requirements'],
                    hiring_manager=mgmt_user,
                    created_by=hr_user,
                    is_active=True,
                )
                created_jobs.append(job)

            self.stdout.write(self.style.SUCCESS(f'Created {len(created_jobs)} core enterprise job postings.'))

            # Create realistic candidates and applications
            app_count = 0
            for spec in REALISTIC_CANDIDATES:
                candidate = Candidate.objects.create(
                    first_name=spec['first_name'],
                    last_name=spec['last_name'],
                    email=spec['email'],
                    phone=spec['phone'],
                    skills=spec['skills'],
                    score=spec['score'],
                    source='portal',
                    resume_text=f"{spec['first_name']} {spec['last_name']} CV content. Skills: {spec['skills']}",
                )

                job = created_jobs[spec['job_index']]
                current_round = job.rounds.filter(order=2).first() or job.rounds.first()

                app = JobApplication.objects.create(
                    candidate=candidate,
                    job=job,
                    status=spec['status'],
                    current_round=current_round,
                    assigned_to=iv_user,
                    feedback_submitted=(spec['status'] in ['interview', 'shortlisted', 'hired']),
                )
                app.panel_interviewers.add(iv_user)
                app_count += 1

                # If status is interview/shortlisted/hired, add structured feedback
                if spec['status'] in ['interview', 'shortlisted', 'hired']:
                    InterviewFeedback.objects.create(
                        application=app,
                        round=current_round,
                        interviewer=iv_user,
                        score=min(10, max(1, spec['score'] // 10)),
                        notes=spec['notes'],
                        raw_notes=f"Raw notes: {spec['notes']}",
                    )

            self.stdout.write(
                self.style.SUCCESS(f'Successfully seeded {len(REALISTIC_CANDIDATES)} candidates and {app_count} applications across 5 positions.')
            )
