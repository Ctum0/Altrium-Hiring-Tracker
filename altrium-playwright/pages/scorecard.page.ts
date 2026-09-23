import { Page, Locator } from '@playwright/test';

/**
 * Page Object for the Interviewer Scorecard (feedback form):
 * /feedback/<application_pk>/<round_pk>/
 *
 * Mirrors feedback/templates/feedback/feedback_form.html.
 */
export class ScorecardPage {
  readonly page: Page;
  readonly technicalInput: Locator;
  readonly communicationInput: Locator;
  readonly cultureInput: Locator;
  readonly rawNotesInput: Locator;
  readonly notesInput: Locator;
  readonly overallScoreInput: Locator;
  readonly suggestRatingsButton: Locator;
  readonly summarizeButton: Locator;
  readonly submitButton: Locator;
  readonly cancelButton: Locator;
  readonly errorMessages: Locator;

  constructor(page: Page) {
    this.page = page;
    // Scorecard criteria inputs (id: criterion_0/1/2)
    this.technicalInput = page.locator('#criterion_0');
    this.communicationInput = page.locator('#criterion_1');
    this.cultureInput = page.locator('#criterion_2');
    this.rawNotesInput = page.locator('#id_raw_notes');
    this.notesInput = page.locator('#id_notes');
    this.overallScoreInput = page.locator('#id_score');
    this.suggestRatingsButton = page.locator('#ai-suggest-btn');
    this.summarizeButton = page.locator('#ai-polish-btn');
    this.submitButton = page.getByRole('button', { name: /Submit feedback|Update feedback/ });
    this.cancelButton = page.getByRole('link', { name: 'Cancel' });
    this.errorMessages = page.locator('.form-error');
  }

  /** Fill the three criteria inputs. */
  async fillCriteria(technical: number, communication: number, culture: number): Promise<void> {
    await this.technicalInput.fill(String(technical));
    await this.communicationInput.fill(String(communication));
    await this.cultureInput.fill(String(culture));
  }

  /** Fill overall score only (no criteria). */
  async fillOverallScore(score: number): Promise<void> {
    await this.overallScoreInput.fill(String(score));
  }

  async fillNotes(notes: string): Promise<void> {
    await this.notesInput.fill(notes);
  }

  async fillRawNotes(raw: string): Promise<void> {
    await this.rawNotesInput.fill(raw);
  }

  async submit(): Promise<void> {
    await this.submitButton.click();
  }
}
