#!/usr/bin/env python
"""
Seed script to load 1000+ candidates across 5 jobs with varied statuses for load testing.
Run with: python manage.py shell < seed_load_test.py
"""

import os
import sys
import django
from datetime import datetime, timedelta
from random import choice, randint, shuffle

# Setup Django
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'altrium_tracker.settings')
django.setup()

from django.contrib.auth import get_user_model
from django.db import transaction
from jobs.models import Job
from candidates.models import Candidate, JobApplication
from feedback.models import InterviewFeedback

User = get_user_model()

# Target 5 jobs
JOBS_TO_USE = 5

# Status distribution
STATUSES = [
    ('new', 30),           # 30% new
    ('in_screening', 25),  # 25% in screening
    ('interview_1', 20),   # 20% first interview
    ('feedback_given', 15),# 15% feedback given
    ('hired', 5),          # 5% hired
    ('rejected', 5),       # 5% rejected
]

FIRST_NAMES = [
    'Alice', 'Bob', 'Charlie', 'Diana', 'Edward', 'Fiona', 'George', 'Helen',
    'Isaac', 'Julia', 'Kevin', 'Laura', 'Michael', 'Nancy', 'Oliver', 'Patricia',
    'Quinn', 'Rachel', 'Samuel', 'Tina', 'Uma', 'Victor', 'Wendy', 'Xavier',
    'Yara', 'Zachary', 'Amber', 'Benjamin', 'Catherine', 'Daniel', 'Eleanor',
]

LAST_NAMES = [
    'Anderson', 'Baker', 'Brown', 'Carter', 'Davis', 'Evans', 'Fisher', 'Garcia',
    'Harris', 'Johnson', 'Kelly', 'Lewis', 'Martin', 'Nelson', 'Oliver', 'Parker',
    'Quinn', 'Roberts', 'Smith', 'Taylor', 'Upton', 'Vaughn', 'Watson', 'Xavier',
    'Young', 'Zhang', 'Abbott', 'Bailey', 'Campbell', 'Douglas', 'Edwards',
]

SKILLS_POOL = [
    'Python', 'Django', 'JavaScript', 'React', 'TypeScript', 'PostgreSQL', 'SQL',
    'Docker', 'Kubernetes', 'AWS', 'GCP', 'API Design', 'REST', 'GraphQL',
    'Redis', 'Celery', 'Testing', 'TDD', 'Git', 'Linux', 'DevOps',
    'Java', 'Go', 'Rust', 'C++', 'Node.js', 'Vue.js', 'Angular',
    'HTML', 'CSS', 'SCSS', 'Webpack', 'CI/CD', 'Terraform',
]

def get_random_status():
    """Pick a status based on distribution."""
    total = sum(weight for _, weight in STATUSES)
    pick = randint(1, total)
    current = 0
    for status, weight in STATUSES:
        current += weight
        if pick <= current:
            return status
    return 'new'

def get_random_email(first, last, index):
    """Generate a unique email."""
    return f"{first.lower()}{last.lower()}{index}@example.com"

def get_random_skills():
    """Pick 5-10 random skills."""
    count = randint(5, 10)
    picked = []
    for _ in range(count):
        picked.append(choice(SKILLS_POOL))
    return ', '.join(list(set(picked))[:count])

def seed_candidates(num_candidates=1100):
    """Seed 1100+ candidates across 5 jobs."""
    
    # Get first 5 active jobs
    jobs = list(Job.objects.all()[:JOBS_TO_USE])
    if len(jobs) < JOBS_TO_USE:
        print(f"WARNING: Only {len(jobs)} jobs found, need {JOBS_TO_USE}. Using {len(jobs)}.")
    
    if not jobs:
        print("ERROR: No jobs found. Please create jobs first.")
        return
    
    print(f"Using jobs: {[j.title for j in jobs]}")
    
    # Get or create HR user for review tracking
    hr_user, _ = User.objects.get_or_create(
        username='hr_bot',
        defaults={'email': 'hr_bot@test.local', 'first_name': 'HR', 'last_name': 'Bot'}
    )
    
    # Track created candidates
    candidates_created = 0
    applications_created = 0
    feedback_created = 0
    
    with transaction.atomic():
        batch_size = 100
        candidates_batch = []
        
        for i in range(num_candidates):
            first = choice(FIRST_NAMES)
            last = choice(LAST_NAMES)
            email = get_random_email(first, last, i)
            
            candidate = Candidate(
                first_name=first,
                last_name=last,
                email=email,
                phone=f"+1{randint(2000000000, 9999999999)}",
                skills=get_random_skills(),
                score=randint(30, 95),
                source='job_board',
                needs_review=False,
                reviewed_by=hr_user if randint(0, 1) else None,
                reviewed_at=datetime.now() if randint(0, 1) else None,
            )
            candidates_batch.append(candidate)
            
            if len(candidates_batch) >= batch_size:
                Candidate.objects.bulk_create(candidates_batch)
                candidates_created += len(candidates_batch)
                candidates_batch = []
                if candidates_created % 500 == 0:
                    print(f"  Created {candidates_created} candidates...")
        
        # Create remaining batch
        if candidates_batch:
            Candidate.objects.bulk_create(candidates_batch)
            candidates_created += len(candidates_batch)
    
    print(f"✓ Created {candidates_created} candidates")
    
    # Create job applications with varied statuses
    candidates = list(Candidate.objects.all()[:num_candidates])
    with transaction.atomic():
        apps_batch = []
        job_idx = 0
        
        for idx, candidate in enumerate(candidates):
            # Distribute candidates across jobs
            job = jobs[job_idx % len(jobs)]
            job_idx += 1
            
            status = get_random_status()
            applied_at = datetime.now() - timedelta(days=randint(1, 90))
            
            app = JobApplication(
                candidate=candidate,
                job=job,
                status=status,
                applied_at=applied_at,
                created_at=applied_at,
                updated_at=applied_at,
            )
            apps_batch.append(app)
            
            if len(apps_batch) >= batch_size:
                JobApplication.objects.bulk_create(apps_batch)
                applications_created += len(apps_batch)
                apps_batch = []
                if applications_created % 500 == 0:
                    print(f"  Created {applications_created} job applications...")
        
        if apps_batch:
            JobApplication.objects.bulk_create(apps_batch)
            applications_created += len(apps_batch)
    
    print(f"✓ Created {applications_created} job applications")
    
    # Create some feedback records for applications in interview stages
    interview_apps = JobApplication.objects.filter(
        status__in=['interview_1', 'feedback_given']
    )[:500]
    
    with transaction.atomic():
        feedback_batch = []
        
        for app in interview_apps:
            feedback = InterviewFeedback(
                application=app,
                interviewer=choice(list(User.objects.filter(role__in=['hr', 'interviewer']))),
                round_number=1,
                rating=randint(1, 5),
                comments=f"Interview feedback for {app.candidate.full_name}",
                created_at=app.applied_at + timedelta(days=randint(1, 30)),
            )
            feedback_batch.append(feedback)
            
            if len(feedback_batch) >= batch_size:
                InterviewFeedback.objects.bulk_create(feedback_batch)
                feedback_created += len(feedback_batch)
                feedback_batch = []
        
        if feedback_batch:
            InterviewFeedback.objects.bulk_create(feedback_batch)
            feedback_created += len(feedback_batch)
    
    print(f"✓ Created {feedback_created} feedback records")
    print(f"\n✓ Load test data seeded successfully!")
    print(f"  Total candidates: {Candidate.objects.count()}")
    print(f"  Total applications: {JobApplication.objects.count()}")
    print(f"  Total feedback: {InterviewFeedback.objects.count()}")

if __name__ == '__main__':
    print("Seeding database with 1100+ candidates for load testing...")
    seed_candidates(1100)
