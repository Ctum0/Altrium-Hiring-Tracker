import { Page, Locator } from '@playwright/test';

/**
 * Page Object for the Candidate Detail page (/candidates/<pk>/).
 * Hosts the Panel Consensus card, application rows, stage moves.
 */
export class CandidateDetailPage {
  readonly page: Page;
  readonly heading: Locator;
  readonly consensusCard: Locator;
  readonly consensusStatusBadge: Locator;
  readonly consensusVerdict: Locator;
  readonly divergenceNote: Locator;
  readonly applicationCards: Locator;
  readonly cvSummarySection: Locator;
  readonly viewCvTextButton: Locator;
  readonly cvOverlay: Locator;
  readonly cvOverlayBody: Locator;
  readonly cvOverlayClose: Locator;
  readonly lowConfidenceBadge: Locator;

  constructor(page: Page) {
    this.page = page;
    this.heading = page.locator('h1.page-title');
    this.consensusCard = page.locator('.panel-consensus-card');
    this.consensusStatusBadge = page.locator('.panel-consensus-card .badge').first();
    this.consensusVerdict = page.locator('.consensus-verdict-value');
    this.divergenceNote = page.locator('.consensus-divergence-note');
    this.applicationCards = page.locator('.app-card');
    this.cvSummarySection = page.locator('.cd-skills-block').filter({ hasText: 'CV Summary' });
    this.viewCvTextButton = page.getByRole('button', { name: /View full extracted CV text/ });
    this.cvOverlay = page.locator('#cv-overlay');
    this.cvOverlayBody = page.locator('.cv-overlay-body');
    this.cvOverlayClose = page.locator('#cv-overlay .btn-icon');
    this.lowConfidenceBadge = page.getByText('Parse low confidence');
  }

  async goto(candidateId: number): Promise<void> {
    await this.page.goto(`/candidates/${candidateId}/`);
  }

  /** Expand all collapsed application rows (details elements). */
  async expandAllApplications(): Promise<void> {
    const toggle = this.page.getByRole('button', { name: 'Expand all' });
    if (await toggle.isVisible().catch(() => false)) {
      await toggle.click();
    }
  }

  async openCvTextOverlay(): Promise<void> {
    await this.viewCvTextButton.click();
    await this.page.waitForTimeout(300);
  }

  async closeCvTextOverlay(): Promise<void> {
    await this.cvOverlayClose.click();
  }
}
