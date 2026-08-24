"""Management command to clean duplicate/test jobs & candidates and seed a realistic enterprise recruitment dataset."""

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


class Command(BaseCommand):
    help = 'Clean duplicate/test jobs and seed a clean enterprise hiring scenario.'

    def add_arguments(self, parser):
        parser.add_argument('--force', action='store_true', help='Force wipe and re-seed even if database is already clean.')

    def handle(self, *args, **options):
        force = options.get('force', False)
        existing_jobs = Job.objects.filter(is_active=True).count()
        existing_candidates = Candidate.objects.count()
        team_user_count = User.objects.filter(username__in=['hr_demo', 'hr_sarah', 'iv_demo', 'iv_chen', 'iv_rachel', 'iv_patel', 'mgmt_demo', 'mgmt_davis']).count()

        # Always ensure team user accounts exist
        users_spec = [
            ('hr_demo', Role.HR, 'Hana', 'Miller', 'testpass123'),
            ('hr_sarah', Role.HR, 'Sarah', 'Jenkins', 'testpass123'),
            ('iv_demo', Role.INTERVIEWER, 'Ivan', 'Vance', 'testpass123'),
            ('iv_chen', Role.INTERVIEWER, 'Marcus', 'Chen', 'testpass123'),
            ('iv_rachel', Role.INTERVIEWER, 'Rachel', 'Adams', 'testpass123'),
            ('iv_patel', Role.INTERVIEWER, 'Vikram', 'Patel', 'testpass123'),
            ('mgmt_demo', Role.MANAGEMENT, 'Mia', 'Thorne', 'testpass123'),
            ('mgmt_davis', Role.MANAGEMENT, 'David', 'Ross', 'testpass123'),
        ]
        users_by_username = {}
        for username, role, f_name, l_name, pwd in users_spec:
            u, _ = User.objects.get_or_create(username=username)
            u.role = role
            u.first_name = f_name
            u.last_name = l_name
            u.set_password(pwd)
            u.save()
            users_by_username[username] = u

        if not force and existing_jobs == 5 and existing_candidates >= 10 and team_user_count == 8:
            self.stdout.write(self.style.SUCCESS('Database is already clean and seeded with enterprise dataset (5 jobs, 10+ candidates, 8 team accounts). Skipping wipe.'))
            return

        self.stdout.write(self.style.WARNING('Starting database cleanup and enterprise seeding...'))

        with transaction.atomic():
            hr_main = users_by_username['hr_demo']
            mgmt_main = users_by_username['mgmt_demo']
            iv_demo = users_by_username['iv_demo']
            iv_chen = users_by_username['iv_chen']
            iv_rachel = users_by_username['iv_rachel']
            iv_patel = users_by_username['iv_patel']

            # Clean existing jobs & candidates
            JobApplication.objects.all().delete()
            InterviewFeedback.objects.all().delete()
            InterviewRound.objects.all().delete()
            Job.objects.all().delete()
            Candidate.objects.all().delete()

            self.stdout.write(self.style.SUCCESS('Cleared legacy test objects.'))

            # 2. Create 5 core enterprise jobs
            created_jobs = []
            for spec in REALISTIC_JOBS:
                job = Job.objects.create(
                    title=spec['title'],
                    department=spec['department'],
                    description=spec['description'],
                    requirements=spec['requirements'],
                    hiring_manager=mgmt_main,
                    created_by=hr_main,
                    is_active=True,
                )
                created_jobs.append(job)

            self.stdout.write(self.style.SUCCESS(f'Created {len(created_jobs)} core enterprise job postings.'))

            # 3. Seed Realistic Candidates & Multi-Evaluator Applications
            candidates_data = [
                {
                    'first_name': 'Alexander',
                    'last_name': 'Wright',
                    'email': 'alexander.wright@example.com',
                    'phone': '+1 415 555 0124',
                    'skills': 'Python, Django, PostgreSQL, Docker, Redis, REST API',
                    'score': 93,
                    'job_idx': 0, # Senior Backend
                    'status': 'interview',
                    'assigned_to': iv_demo,
                    'evaluations': [
                        (1, hr_main, 9, 'Great screening interview. Clear communication and strong Django fundamentals.'),
                        (2, iv_demo, 9, 'Excellent technical architecture review. Demonstrated deep knowledge of PostgreSQL indexing and async tasks.'),
                        (3, mgmt_main, 10, 'Executive round passed with flying colors. Strong leadership mindset for senior backend role.'),
                    ]
                },
                {
                    'first_name': 'Elena',
                    'last_name': 'Rostova',
                    'email': 'elena.rostova@example.com',
                    'phone': '+1 415 555 0244',
                    'skills': 'Python, Django, SQL, REST API',
                    'score': 72,
                    'job_idx': 0, # Senior Backend
                    'status': 'in_progress',
                    'assigned_to': iv_demo,
                    'evaluations': [
                        (1, hr_main, 8, 'Friendly candidate with good communication.'),
                        (2, iv_demo, 4, 'Struggled with complex query optimization and ORM performance questions. Recommend REJECT for senior level.'),
                    ]
                },
                {
                    'first_name': 'Marcus',
                    'last_name': 'Vance',
                    'email': 'marcus.vance@example.com',
                    'phone': '+1 415 555 0199',
                    'skills': 'React, JavaScript, HTMX, CSS, TypeScript, UI/UX',
                    'score': 95,
                    'job_idx': 1, # Frontend Engineer
                    'status': 'hired',
                    'assigned_to': iv_chen,
                    'evaluations': [
                        (1, hr_main, 9, 'Impressive portfolio and past frontend architecture projects.'),
                        (2, iv_chen, 10, 'Outstanding live coding demo. Mastered HTMX state swaps and component re-usability.'),
                    ]
                },
                {
                    'first_name': 'Sophia',
                    'last_name': 'Chen',
                    'email': 'sophia.chen@example.com',
                    'phone': '+1 415 555 0188',
                    'skills': 'React, JavaScript, CSS, HTML',
                    'score': 84,
                    'job_idx': 1, # Frontend Engineer
                    'status': 'interview',
                    'assigned_to': iv_chen,
                    'evaluations': [
                        (2, iv_chen, 8, 'Good understanding of React hooks and DOM rendering. Needs minor review on HTMX integration.'),
                    ]
                },
                {
                    'first_name': 'David',
                    'last_name': 'Miller',
                    'email': 'david.miller@example.com',
                    'phone': '+1 415 555 0311',
                    'skills': 'AWS, Docker, Kubernetes, Terraform, CI/CD, Linux, PostgreSQL',
                    'score': 90,
                    'job_idx': 2, # DevOps Lead
                    'status': 'interview',
                    'assigned_to': iv_rachel,
                    'evaluations': [
                        (1, hr_main, 9, 'Proven experience managing multi-region cloud infrastructure.'),
                        (2, iv_rachel, 9, 'Solid Terraform and Kubernetes cluster setup. Passed technical audit.'),
                    ]
                },
                {
                    'first_name': 'Aria',
                    'last_name': 'Montgomery',
                    'email': 'aria.montgomery@example.com',
                    'phone': '+1 415 555 0377',
                    'skills': 'AWS, Docker, Linux, Bash',
                    'score': 74,
                    'job_idx': 2, # DevOps Lead
                    'status': 'new',
                    'assigned_to': iv_rachel,
                    'evaluations': [] # 0 evaluations
                },
                {
                    'first_name': 'Lucas',
                    'last_name': 'Thorne',
                    'email': 'lucas.thorne@example.com',
                    'phone': '+1 415 555 0422',
                    'skills': 'Figma, UI/UX, Design System, Prototyping, Agile',
                    'score': 88,
                    'job_idx': 3, # Product Designer
                    'status': 'shortlisted',
                    'assigned_to': iv_chen,
                    'evaluations': [
                        (1, hr_main, 8, 'Strong design portfolio.'),
                        (2, iv_chen, 9, 'Great eye for UI hierarchy and glassmorphism design tokens.'),
                    ]
                },
                {
                    'first_name': 'Nadia',
                    'last_name': 'Patel',
                    'email': 'nadia.patel@example.com',
                    'phone': '+1 415 555 0499',
                    'skills': 'Python, Pytest, Selenium, Playwright, Automated Testing, API Testing',
                    'score': 94,
                    'job_idx': 4, # QA Lead
                    'status': 'interview',
                    'assigned_to': iv_patel,
                    'evaluations': [
                        (1, hr_main, 9, 'Very articulate QA engineer.'),
                        (2, iv_patel, 10, 'Built a working Playwright regression suite live. Exceptional candidate.'),
                    ]
                },
                {
                    'first_name': 'Julian',
                    'last_name': 'Hayes',
                    'email': 'julian.hayes@example.com',
                    'phone': '+1 415 555 0533',
                    'skills': 'Python, Django, PostgreSQL, Redis',
                    'score': 68,
                    'job_idx': 0, # Senior Backend
                    'status': 'on_hold',
                    'assigned_to': iv_demo,
                    'evaluations': [
                        (1, hr_main, 6, 'Average screening performance.'),
                        (2, iv_demo, 5, 'Marginal technical score. Put candidate on hold for now.'),
                    ]
                },
                {
                    'first_name': 'Claire',
                    'last_name': 'Dupont',
                    'email': 'claire.dupont@example.com',
                    'phone': '+1 415 555 0611',
                    'skills': 'React, TypeScript, CSS',
                    'score': 55,
                    'job_idx': 1, # Frontend Engineer
                    'status': 'rejected',
                    'assigned_to': iv_chen,
                    'evaluations': [
                        (1, hr_main, 4, 'Did not meet core position requirements.'),
                        (2, iv_chen, 3, 'Lacked experience in responsive UI systems. Recommend REJECT.'),
                    ]
                },
            ]

            app_count = 0
            fb_count = 0
            for spec in candidates_data:
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

                job = created_jobs[spec['job_idx']]
                rounds = list(job.rounds.all().order_by('order'))
                current_round = rounds[min(len(spec['evaluations']), len(rounds)-1)] if rounds else None

                app = JobApplication.objects.create(
                    candidate=candidate,
                    job=job,
                    status=spec['status'],
                    current_round=current_round,
                    assigned_to=spec['assigned_to'],
                    feedback_submitted=len(spec['evaluations']) > 0,
                )
                app.panel_interviewers.add(spec['assigned_to'])
                app_count += 1

                for r_order, interviewer_user, score, notes in spec['evaluations']:
                    r_obj = rounds[r_order-1] if (r_order-1) < len(rounds) else rounds[-1]
                    InterviewFeedback.objects.create(
                        application=app,
                        round=r_obj,
                        interviewer=interviewer_user,
                        score=score,
                        notes=notes,
                        raw_notes=f"Raw interviewer notes: {notes}",
                    )
                    fb_count += 1

            self.stdout.write(
                self.style.SUCCESS(
                    f'Successfully seeded {len(users_spec)} team accounts, {len(candidates_data)} candidates, '
                    f'{app_count} applications, and {fb_count} multi-evaluator scorecards across 5 enterprise positions.'
                )
            )
