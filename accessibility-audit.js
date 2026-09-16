const fs = require('fs');
const chromeLauncher = require('chrome-launcher');

const BASE_URL = 'http://127.0.0.1:8001';

// Pages to audit
const pages = [
  { name: 'Login Page', path: '/login/', authenticated: false },
  { name: 'HR Dashboard', path: '/jobs/', authenticated: true },
  { name: 'Public Apply Form', path: '/candidates/apply/1/', authenticated: false },
  { name: 'Kanban Board', path: '/jobs/1/board/', authenticated: true },
  { name: 'Feedback Form', path: '/feedback/submit/', authenticated: true },
];

const results = {
  audit_date: new Date().toISOString(),
  total_pages: pages.length,
  pages: {},
  summary: {
    critical_violations: [],
    major_violations: [],
    minor_violations: [],
    average_accessibility_score: 0
  }
};

async function runAudit(lighthouse, url, pageName) {
  console.log(`\n✓ Auditing: ${pageName} (${url})`);
  
  try {
    const chrome = await chromeLauncher.launch({
      chromeFlags: ['--headless', '--no-sandbox', '--disable-gpu', '--disable-dev-shm-usage']
    });

    const options = {
      logLevel: 'error',
      output: 'json',
      onlyCategories: ['accessibility'],
      port: chrome.port,
    };

    const runnerResult = await lighthouse(url, options);
    const reportJson = JSON.parse(runnerResult.report);

    const accessibilityScore = reportJson.categories.accessibility.score * 100;
    console.log(`  Accessibility Score: ${accessibilityScore.toFixed(1)}%`);

    // Extract violations
    const violations = [];
    Object.values(reportJson.audits).forEach((audit) => {
      if (audit.score !== 1 && audit.score !== null && audit.details) {
        const severity = audit.scoreDisplayMode === 'fail' ? 'critical' : 'major';
        violations.push({
          id: audit.id,
          title: audit.title,
          description: audit.description,
          severity: severity,
          score: audit.score,
          details: audit.details.items ? audit.details.items.slice(0, 3) : []
        });
      }
    });

    results.pages[pageName] = {
      url: url,
      accessibility_score: accessibilityScore,
      violations_count: violations.length,
      violations: violations
    };

    // Aggregate results
    violations.forEach(v => {
      if (v.severity === 'critical') {
        results.summary.critical_violations.push({
          page: pageName,
          ...v
        });
      } else {
        results.summary.major_violations.push({
          page: pageName,
          ...v
        });
      }
    });

    await chrome.kill();
    return true;
  } catch (error) {
    console.error(`  Error auditing ${pageName}: ${error.message}`);
    results.pages[pageName] = {
      url: url,
      error: error.message
    };
    return false;
  }
}

async function main() {
  console.log('='.repeat(80));
  console.log('WCAG 2.1 AA ACCESSIBILITY AUDIT');
  console.log('Altrium Hiring Tracker');
  console.log('='.repeat(80));

  // Import lighthouse as ES module
  const lighthouse = (await import('lighthouse')).default;

  let totalScores = 0;
  let auditCount = 0;

  for (const page of pages) {
    const url = BASE_URL + page.path;
    if (await runAudit(lighthouse, url, page.name)) {
      totalScores += results.pages[page.name].accessibility_score;
      auditCount++;
    }
  }

  // Calculate average score
  if (auditCount > 0) {
    results.summary.average_accessibility_score = (totalScores / auditCount).toFixed(1);
  }

  // Save results to JSON file
  fs.writeFileSync('/tmp/accessibility-audit-results.json', JSON.stringify(results, null, 2));
  console.log('\n✓ Audit results saved to /tmp/accessibility-audit-results.json');

  // Print summary
  console.log('\n' + '='.repeat(80));
  console.log('AUDIT SUMMARY');
  console.log('='.repeat(80));
  console.log(`Average Accessibility Score: ${results.summary.average_accessibility_score}%`);
  console.log(`Critical Violations Found: ${results.summary.critical_violations.length}`);
  console.log(`Major Violations Found: ${results.summary.major_violations.length}`);

  // List violations
  if (results.summary.critical_violations.length > 0) {
    console.log('\n🔴 CRITICAL VIOLATIONS:');
    results.summary.critical_violations.forEach(v => {
      console.log(`  - [${v.page}] ${v.title}`);
    });
  }

  if (results.summary.major_violations.length > 0) {
    console.log('\n🟠 MAJOR VIOLATIONS:');
    results.summary.major_violations.slice(0, 10).forEach(v => {
      console.log(`  - [${v.page}] ${v.title}`);
    });
  }

  console.log('\n✓ Audit complete');
}

main().catch(console.error);
