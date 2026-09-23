import { Page, Locator } from '@playwright/test';

/**
 * Page Object for the Interviewer Dashboard (/interviewer-dashboard/)
 * — the "Pending Feedback" queue that links into scorecards.
 */
export class InterviewerDashboardPage {
  readonly page: Page;
  readonly assignedCount: Locator;
  readonly pendingFeedbackCard: Locator;
  readonly giveFeedbackButtons: Locator;

  constructor(page: Page) {
    this.page = page;
    this.assignedCount = page.locator('.ref-kpi-value').first();
    this.pendingFeedbackCard = page
      .locator('.ref-kpi-card')
      .filter({ hasText: 'Pending Feedback' });
    this.giveFeedbackButtons = page.getByRole('link', { name: 'Give feedback' });
  }

  async goto(): Promise<void> {
    await this.page.goto('/interviewer-dashboard/');
  }

  /** Click the first "Give feedback" button and wait for the scorecard. */
  async openFirstScorecard(): Promise<void> {
    await this.giveFeedbackButtons.first().click();
    await this.page.waitForURL(/\/feedback\/\d+\/\d+\//);
  }
}
