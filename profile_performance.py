#!/usr/bin/env python
"""
Comprehensive performance profiling script for load testing.
Measures response times, query counts, and identifies bottlenecks.
"""
import os
import sys
import django
import time
import json
from datetime import datetime

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'altrium_tracker.settings')
django.setup()

from django.conf import settings
from django.db import connection
from django.test.utils import CaptureQueriesContext
from django.contrib.auth import get_user_model

from candidates.models import Candidate, JobApplication
from jobs.models import Job
from feedback.models import InterviewFeedback

User = get_user_model()

# Performance metrics storage
metrics = {
    "timestamp": datetime.now().isoformat(),
    "paths": {},
    "n_plus_1_issues": [],
    "index_recommendations": []
}

# Get test user (HR)
hr_user = User.objects.filter(role='hr').first()
if not hr_user:
    hr_user = User.objects.first()

print("=" * 70)
print("PERFORMANCE PROFILING REPORT - Altrium Hiring Tracker")
print("=" * 70)
print(f"Candidates: {Candidate.objects.count()}")
print(f"Job Applications: {JobApplication.objects.count()}")
print(f"Interview Feedback: {InterviewFeedback.objects.count()}")
print(f"Test user: {hr_user.email if hr_user else 'None'}")
print()

# 1. Test HR Dashboard
print("\n[1] Testing HR Dashboard")
print("-" * 70)

try:
    start = time.time()
    with CaptureQueriesContext(connection) as ctx:
        # Simulate dashboard queries
        candidates_count = Candidate.objects.count()
        jobs = Job.objects.all()
        applications = JobApplication.objects.values('status').annotate(__import__('django.db.models', fromlist=['Count']).Count('id'))
        app_list = list(applications)
    elapsed = time.time() - start
    
    metrics["paths"]["hr_dashboard"] = {
        "time_ms": round(elapsed * 1000, 2),
        "query_count": len(ctx.captured_queries),
        "target_ms": 2000,
        "passed": elapsed < 2
    }
    
    print(f"  Response time: {elapsed*1000:.2f}ms")
    print(f"  Database queries: {len(ctx.captured_queries)}")
    print(f"  Status: {'✓ PASS' if elapsed < 2 else '✗ FAIL'} (target: <2000ms)")
    
except Exception as e:
    print(f"  ✗ Error: {str(e)}")
    metrics["paths"]["hr_dashboard"] = {"error": str(e)}

# 2. Test Kanban Board (simulating 500+ applications)
print("\n[2] Testing Kanban Board")
print("-" * 70)

try:
    start = time.time()
    with CaptureQueriesContext(connection) as ctx:
        # Simulate Kanban board fetching applications by status
        statuses = ['new', 'in_screening', 'interview_1', 'feedback_given', 'hired', 'rejected']
        apps_by_status = {}
        for status in statuses:
            apps = JobApplication.objects.filter(status=status).select_related('candidate', 'job')[:100]
            apps_by_status[status] = list(apps)
    elapsed = time.time() - start
    
    total_apps_loaded = sum(len(v) for v in apps_by_status.values())
    
    metrics["paths"]["kanban_board"] = {
        "time_ms": round(elapsed * 1000, 2),
        "query_count": len(ctx.captured_queries),
        "applications_loaded": total_apps_loaded,
        "target_ms": 3000,
        "passed": elapsed < 3
    }
    
    print(f"  Response time: {elapsed*1000:.2f}ms")
    print(f"  Database queries: {len(ctx.captured_queries)}")
    print(f"  Applications loaded: {total_apps_loaded}")
    print(f"  Status: {'✓ PASS' if elapsed < 3 else '✗ FAIL'} (target: <3000ms)")
    
except Exception as e:
    print(f"  ✗ Error: {str(e)}")
    metrics["paths"]["kanban_board"] = {"error": str(e)}

# 3. Test CSV Export (simulating 1000+ CVs)
print("\n[3] Testing CSV Export")
print("-" * 70)

try:
    start = time.time()
    with CaptureQueriesContext(connection) as ctx:
        # Simulate CSV export: fetch all candidates with applications
        candidates = Candidate.objects.all().prefetch_related('jobapplication_set')
        csv_data = []
        for candidate in candidates:
            apps = candidate.jobapplication_set.all()
            for app in apps:
                csv_data.append({
                    'name': candidate.full_name,
                    'email': candidate.email,
                    'job': app.job.title if app.job else '',
                    'status': app.status
                })
    elapsed = time.time() - start
    
    metrics["paths"]["csv_export"] = {
        "time_ms": round(elapsed * 1000, 2),
        "query_count": len(ctx.captured_queries),
        "rows_generated": len(csv_data),
        "target_ms": 5000,
        "passed": elapsed < 5
    }
    
    print(f"  Response time: {elapsed*1000:.2f}ms")
    print(f"  Database queries: {len(ctx.captured_queries)}")
    print(f"  CSV rows generated: {len(csv_data)}")
    print(f"  Status: {'✓ PASS' if elapsed < 5 else '✗ FAIL'} (target: <5000ms)")
    
except Exception as e:
    print(f"  ✗ Error: {str(e)}")
    metrics["paths"]["csv_export"] = {"error": str(e)}

# 4. Test Candidate Search
print("\n[4] Testing Candidate Search")
print("-" * 70)

try:
    start = time.time()
    with CaptureQueriesContext(connection) as ctx:
        # Simulate search with filters
        results = Candidate.objects.filter(skills__icontains='Python').select_related()[:50]
        result_list = list(results)
    elapsed = time.time() - start
    
    metrics["paths"]["candidate_search"] = {
        "time_ms": round(elapsed * 1000, 2),
        "query_count": len(ctx.captured_queries),
        "results": len(result_list),
        "target_ms": 1000,
        "passed": elapsed < 1
    }
    
    print(f"  Response time: {elapsed*1000:.2f}ms")
    print(f"  Database queries: {len(ctx.captured_queries)}")
    print(f"  Results found: {len(result_list)}")
    print(f"  Status: {'✓ PASS' if elapsed < 1 else '✗ FAIL'} (target: <1000ms)")
    
except Exception as e:
    print(f"  ✗ Error: {str(e)}")
    metrics["paths"]["candidate_search"] = {"error": str(e)}

# 5. Test Feedback List
print("\n[5] Testing Feedback List")
print("-" * 70)

try:
    start = time.time()
    with CaptureQueriesContext(connection) as ctx:
        feedbacks = InterviewFeedback.objects.all().select_related('application', 'interviewer')[:500]
        feedback_list = list(feedbacks)
    elapsed = time.time() - start
    
    metrics["paths"]["feedback_list"] = {
        "time_ms": round(elapsed * 1000, 2),
        "query_count": len(ctx.captured_queries),
        "records": len(feedback_list),
        "target_ms": 1500,
        "passed": elapsed < 1.5
    }
    
    print(f"  Response time: {elapsed*1000:.2f}ms")
    print(f"  Database queries: {len(ctx.captured_queries)}")
    print(f"  Feedback records: {len(feedback_list)}")
    print(f"  Status: {'✓ PASS' if elapsed < 1.5 else '✗ FAIL'} (target: <1500ms)")
    
except Exception as e:
    print(f"  ✗ Error: {str(e)}")
    metrics["paths"]["feedback_list"] = {"error": str(e)}

# 6. Check for N+1 Query Patterns
print("\n[6] Checking for N+1 Query Patterns")
print("-" * 70)

try:
    # Naively loading applications without select_related - likely to have N+1
    with CaptureQueriesContext(connection) as ctx:
        apps = JobApplication.objects.all()[:50]
        for app in apps:
            # Access candidate name - this causes N+1 without select_related
            _ = app.candidate.full_name
    
    naive_query_count = len(ctx.captured_queries)
    
    # Now test with proper optimization
    with CaptureQueriesContext(connection) as ctx:
        apps = JobApplication.objects.select_related('candidate').all()[:50]
        for app in apps:
            _ = app.candidate.full_name
    
    optimized_query_count = len(ctx.captured_queries)
    
    extra_queries = naive_query_count - optimized_query_count
    if extra_queries > 10:
        print(f"  ⚠ POTENTIAL N+1 FOUND")
        print(f"    Without select_related: {naive_query_count} queries")
        print(f"    With select_related: {optimized_query_count} queries")
        print(f"    Extra queries (N+1 pattern): {extra_queries}")
        print(f"    Recommendation: Use select_related('candidate') on JobApplication queries")
        metrics["n_plus_1_issues"].append({
            "issue": "JobApplication.candidate access",
            "without_optimization": naive_query_count,
            "with_select_related": optimized_query_count,
            "extra_queries": extra_queries,
            "recommendation": "Use select_related('candidate') on all JobApplication queries"
        })
    else:
        print(f"  ✓ No obvious N+1 patterns")
        print(f"    50 applications: {optimized_query_count} queries (avg {optimized_query_count/50:.2f} per app)")
    
except Exception as e:
    print(f"  ✗ Error: {str(e)}")

# 7. Check pagination need
print("\n[7] Pagination Analysis")
print("-" * 70)

try:
    app_count = JobApplication.objects.count()
    candidate_count = Candidate.objects.count()
    feedback_count = InterviewFeedback.objects.count()
    
    print(f"  JobApplication records: {app_count}")
    print(f"    Recommendation: Paginate if displaying more than 50")
    print(f"  Candidate records: {candidate_count}")
    print(f"    Recommendation: Paginate if displaying more than 50")
    print(f"  InterviewFeedback records: {feedback_count}")
    print(f"    Recommendation: Paginate if displaying more than 100")
    
    if app_count > 500 or candidate_count > 500:
        print(f"\n  ⚠ HIGH VOLUME DATA: Pagination is critical for performance")
        metrics["index_recommendations"].append({
            "issue": "High data volume",
            "recommendation": "Implement pagination on list views (50-100 items per page)"
        })
    
except Exception as e:
    print(f"  ✗ Error: {str(e)}")

# Summary
print("\n" + "=" * 70)
print("PERFORMANCE SUMMARY")
print("=" * 70)

all_passed = all(
    metrics["paths"].get(path, {}).get("passed", False)
    for path in ["hr_dashboard", "kanban_board", "csv_export", "candidate_search", "feedback_list"]
)

print(f"\nResults:")
for path, data in sorted(metrics["paths"].items()):
    if "error" not in data:
        status = "✓ PASS" if data.get("passed") else "✗ FAIL"
        print(f"  {path:20} {data['time_ms']:8.2f}ms / {data['target_ms']}ms  {status}")

print(f"\nOverall Status: {'✓ ALL TARGETS MET' if all_passed else '✗ SOME TARGETS MISSED'}")

if metrics["n_plus_1_issues"]:
    print(f"\nN+1 Query Issues: {len(metrics['n_plus_1_issues'])}")
    for issue in metrics["n_plus_1_issues"]:
        print(f"  - {issue['issue']}: {issue['extra_queries']} extra queries")

# Save metrics to file
with open('/tmp/performance_metrics.json', 'w') as f:
    json.dump(metrics, f, indent=2, default=str)
print(f"\nFull metrics saved to: /tmp/performance_metrics.json")

print("\n" + "=" * 70)
