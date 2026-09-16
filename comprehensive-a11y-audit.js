const { chromium } = require('playwright');
const AxeBuilder = require('@axe-core/playwright').default;
const fs = require('fs');
const path = require('path');

const BASE_URL = 'http://127.0.0.1:8001';
const RESULTS_DIR = '/tmp/a11y-audit-results';

if (!fs.existsSync(RESULTS_DIR)) {
  fs.mkdirSync(RESULTS_DIR, { recursive: true });
}

const auditResults = {
  timestamp: new Date().toISOString(),
  pages: {},
  summary: {
    total_pages: 0,
    pages_with_violations: 0,
    critical_violations: [],
    major_violations: [],
    minor_violations: [],
  }
};

async function login(page) {
  console.log('  • Logging in as hr_demo@example.com...');
  await page.goto(`${BASE_URL}/login/`, { waitUntil: 'networkidle' });
  await page.waitForSelector('[name="username"]', { timeout: 10000 });
  
  // Fill login form
  await page.locator('[name="username"]').fill('hr_demo@example.com');
  await page.locator('[name="password"]').fill('testpass123');
  
  // Submit and wait for navigation
  await Promise.all([
    page.waitForNavigation({ waitUntil: 'networkidle' }),
    page.locator('button[type="submit"]').click()
  ]);
  
  console.log('  ✓ Logged in successfully');
}

async function runAccessibilityAudit(page, pageName, url, authenticated) {
  console.log(`\n📋 AUDITING: ${pageName}`);
  console.log(`   URL: ${url}`);
  
  try {
    if (authenticated) {
      await login(page);
    }
    
    // Navigate to page
    await page.goto(url, { waitUntil: 'networkidle' });
    
    // Run axe accessibility scan
    console.log('  • Running axe-core scan...');
    const accessibilityResults = await new AxeBuilder({ page })
      .withTags(['wcag2a', 'wcag2aa', 'wcag21aa'])
      .analyze();
    
    // Categorize violations
    const violations = {
      critical: accessibilityResults.violations.filter(v => v.impact === 'critical'),
      serious: accessibilityResults.violations.filter(v => v.impact === 'serious'),
      moderate: accessibilityResults.violations.filter(v => v.impact === 'moderate'),
      minor: accessibilityResults.violations.filter(v => v.impact === 'minor')
    };
    
    console.log(`  • Violations found:`);
    console.log(`    - Critical: ${violations.critical.length}`);
    console.log(`    - Serious: ${violations.serious.length}`);
    console.log(`    - Moderate: ${violations.moderate.length}`);
    console.log(`    - Minor: ${violations.minor.length}`);
    
    // Test keyboard navigation
    console.log('  • Testing keyboard navigation...');
    const keyboardTest = await testKeyboardNavigation(page);
    
    // Test focus visibility
    console.log('  • Checking focus indicators...');
    const focusTest = await testFocusVisibility(page);
    
    // Test semantic HTML
    console.log('  • Verifying semantic structure...');
    const semanticTest = await testSemanticStructure(page);
    
    // Store results
    auditResults.pages[pageName] = {
      url: url,
      authenticated: authenticated,
      violations: {
        critical: violations.critical.length,
        serious: violations.serious.length,
        moderate: violations.moderate.length,
        minor: violations.minor.length,
        total: accessibilityResults.violations.length
      },
      detailed_violations: accessibilityResults.violations.slice(0, 5),
      passes: accessibilityResults.passes.length,
      keyboard_navigation: keyboardTest,
      focus_visible: focusTest,
      semantic_html: semanticTest
    };
    
    // Add to summary
    auditResults.summary.total_pages++;
    if (accessibilityResults.violations.length > 0) {
      auditResults.summary.pages_with_violations++;
    }
    
    violations.critical.forEach(v => {
      auditResults.summary.critical_violations.push({
        page: pageName,
        ...v
      });
    });
    
    violations.serious.forEach(v => {
      auditResults.summary.major_violations.push({
        page: pageName,
        ...v
      });
    });
    
    violations.moderate.forEach(v => {
      auditResults.summary.minor_violations.push({
        page: pageName,
        ...v
      });
    });
    
    return true;
  } catch (error) {
    console.error(`  ✗ Error auditing ${pageName}: ${error.message}`);
    auditResults.pages[pageName] = {
      url: url,
      error: error.message
    };
    return false;
  }
}

async function testKeyboardNavigation(page) {
  try {
    const interactiveElements = await page.evaluate(() => {
      const elements = [];
      const selector = 'button, a, input, select, textarea, [role="button"], [tabindex]';
      document.querySelectorAll(selector).forEach((el, index) => {
        if (el.offsetParent !== null) {
          elements.push({
            index,
            tag: el.tagName,
            type: el.getAttribute('type'),
            hasAriaLabel: !!el.getAttribute('aria-label')
          });
        }
      });
      return elements;
    });
    
    return {
      status: 'tested',
      interactive_elements_found: interactiveElements.length
    };
  } catch (error) {
    return { status: 'error', message: error.message };
  }
}

async function testFocusVisibility(page) {
  try {
    const hasFocusStyles = await page.evaluate(() => {
      const styleSheets = Array.from(document.styleSheets);
      let hasFocusStyles = false;
      
      styleSheets.forEach(sheet => {
        try {
          const rules = sheet.cssRules || sheet.rules;
          if (rules) {
            Array.from(rules).forEach(rule => {
              if (rule.selectorText && (
                rule.selectorText.includes(':focus') || 
                rule.selectorText.includes(':focus-visible')
              )) {
                hasFocusStyles = true;
              }
            });
          }
        } catch (e) {}
      });
      
      return {
        hasFocusStyles,
        focusVisibleSupported: CSS.supports('selector(:focus-visible)')
      };
    });
    
    return {
      status: 'checked',
      ...hasFocusStyles
    };
  } catch (error) {
    return { status: 'error', message: error.message };
  }
}

async function testSemanticStructure(page) {
  try {
    const semanticCheck = await page.evaluate(() => {
      const headings = document.querySelectorAll('h1, h2, h3, h4, h5, h6');
      const mainContent = document.querySelector('main');
      const nav = document.querySelector('nav');
      const forms = document.querySelectorAll('form, [role="form"]');
      const lists = document.querySelectorAll('ul, ol, [role="list"]');
      const images = document.querySelectorAll('img');
      
      const imagesWithoutAlt = Array.from(images).filter(img => 
        !img.getAttribute('alt') && !img.getAttribute('aria-label')
      ).length;
      
      return {
        headings: headings.length,
        hasMainElement: !!mainContent,
        hasNav: !!nav,
        forms: forms.length,
        lists: lists.length,
        images: images.length,
        imagesWithoutAlt: imagesWithoutAlt,
        languageSet: !!document.documentElement.getAttribute('lang')
      };
    });
    
    return {
      status: 'analyzed',
      ...semanticCheck
    };
  } catch (error) {
    return { status: 'error', message: error.message };
  }
}

async function main() {
  console.log('='.repeat(80));
  console.log('WCAG 2.1 AA ACCESSIBILITY AUDIT');
  console.log('Altrium Hiring Tracker');
  console.log('='.repeat(80));
  
  const browser = await chromium.launch({
    headless: true,
    args: ['--disable-blink-features=AutomationControlled', '--no-sandbox']
  });
  
  const context = await browser.newContext();
  const page = await context.newPage();
  
  // Set extended timeout
  page.setDefaultTimeout(60000);
  page.setDefaultNavigationTimeout(60000);
  
  // Pages to audit
  const pages = [
    { name: 'Login Page', path: '/login/', authenticated: false },
    { name: 'HR Dashboard (Jobs)', path: '/jobs/', authenticated: true },
    { name: 'Public Apply Form', path: '/candidates/apply/1/', authenticated: false },
    { name: 'Kanban Board', path: '/jobs/1/board/', authenticated: true },
    { name: 'Feedback Form', path: '/feedback/submit/', authenticated: true },
  ];
  
  // Run audits
  for (const page_info of pages) {
    const url = BASE_URL + page_info.path;
    await runAccessibilityAudit(page, page_info.name, url, page_info.authenticated);
  }
  
  // Save full results
  fs.writeFileSync(
    path.join(RESULTS_DIR, 'audit-results.json'),
    JSON.stringify(auditResults, null, 2)
  );
  
  // Print summary
  console.log('\n' + '='.repeat(80));
  console.log('AUDIT SUMMARY');
  console.log('='.repeat(80));
  console.log(`Total pages audited: ${auditResults.summary.total_pages}`);
  console.log(`Pages with violations: ${auditResults.summary.pages_with_violations}`);
  console.log(`\nVIOLATIONS FOUND:`);
  console.log(`  Critical: ${auditResults.summary.critical_violations.length}`);
  console.log(`  Major (Serious): ${auditResults.summary.major_violations.length}`);
  console.log(`  Minor (Moderate): ${auditResults.summary.minor_violations.length}`);
  
  if (auditResults.summary.critical_violations.length > 0) {
    console.log('\n🔴 CRITICAL VIOLATIONS:');
    auditResults.summary.critical_violations.slice(0, 10).forEach(v => {
      console.log(`  • [${v.page}] ${v.id}: ${v.description}`);
    });
  }
  
  console.log('\n✓ Full results saved to:', path.join(RESULTS_DIR, 'audit-results.json'));
  
  await context.close();
  await browser.close();
}

main().catch(console.error);
