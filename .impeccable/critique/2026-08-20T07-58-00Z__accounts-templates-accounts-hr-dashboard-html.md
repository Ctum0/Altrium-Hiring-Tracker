---
target: HR dashboard (accounts/templates/accounts/hr_dashboard.html)
total_score: 24
p0_count: 2
p1_count: 2
timestamp: 2026-08-20T07-58-00Z
slug: accounts-templates-accounts-hr-dashboard-html
---
# Design Critique — HR Dashboard (`accounts/templates/accounts/hr_dashboard.html`)

Method: dual-agent (A: ses_fe235cf7cffeDdcfGexPPTFZiN · B: ses_fe1e21d76ffeI7mYSzBSkcxezU)

## Design Health Score

| # | Heuristic | Score | Key Issue |
|---|-----------|-------|-----------|
| 1 | Visibility of System Status | 3 | "Live Activity" shows updates 6 days–2 weeks old; trend chevrons imply live deltas that are static context text |
| 2 | Match System / Real World | 1 | "Pipeline Trend" is stage counts, not time; "Feedback Turnaround" shows completion counts, not turnaround time; two "14"s read as the same metric |
| 3 | User Control and Freedom | 3 | Theme toggle + Esc/cancel dialogs solid; the "Action needed" KPI is not a link, so the loudest signal has no path to act |
| 4 | Consistency and Standards | 2 | Tokenization incomplete: `#0075FF` hardcoded in chart JS, near-black tooltips in both themes, inline 9px overrides, dead inline style (9px badge computes to 12px) |
| 5 | Error Prevention | 3 | Empty states, `widthratio` zero-guard, em-dash fallback — little here to prevent |
| 6 | Recognition Rather Than Recall | 2 | Duplicate "Lead Cloud & DevOps Architect" rows; three "6"s and two "14"s tax working memory; "Action needed" requires recalling where to go |
| 7 | Flexibility and Efficiency | 3 | Topbar search + context links; no accelerators for repeat HR use; Live Activity has no "view all" |
| 8 | Aesthetic and Minimalist Design | 1 | Decorative glow everywhere contradicts the brief; loudest objects are red (43% rejected bar, 86% red pending bar) in a tool meant to be calm |
| 9 | Error Recovery | 3 | No error-prone surface here; toast infra exists elsewhere |
| 10 | Help and Documentation | 3 | "Details →" / "All jobs →" present; nothing explains "Avg AI Score" or "Turnaround" |
| **Total** | | **24/40** | **Acceptable — significant improvements needed** |

## Anti-Patterns Verdict

**LLM assessment**: Yes, someone would say "AI made this." The CSS self-identifies at `app.css:1-3` as the "Vision UI Dashboard" template, and the page renders its signature garnish: ambient glow orbs (`blur(136px)`, `app.css:291`), gradient navy canvas, hero-metric KPI cards with floating gradient icon chips + glow shadows + hover `translateY(-3px)`, gradient progress bars (`!important`, `app.css:3750-3756`), gradient primary buttons and active seg pill, 20px card radii (brief says 8px), and a 3px gradient side-stripe on the active nav link (`app.css:875`). All four banned by DESIGN.md ("calm operational clarity… depth is structural not decorative glow"). Off-palette "Cyber Teal" (`#4FD1C5→#319795`) and red-for-pending where the brief reserves red for `rejected` and amber for escalation. Honest counters: no gradient text, no numbered section markers, no text overflow.

**Deterministic scan**: Degraded. `detect.mjs` ran a real attempt but its element-level engine deps (`htmlparser2`, `css-select`, `css-tree`, `domutils`) are not installed in the skill tree, so it silently fell back to regex-only and returned 0 findings for both `hr_dashboard.html` and `base.html`. Treat those empty results as false negatives, not cleanliness. No rule hits with file/line are available.

**Visual overlays**: Not used — no live-server/detect.js overlay was injected; evidence was collected via direct native browser inspection (mutation preflight succeeded: `document.title` set and a `<script>` tag executed). Browser console was clean (0 errors/warnings) aside from a 404 `favicon.ico`.

## Overall Impression

The structural discipline is real — this genuinely fits one viewport, the data reconciles, and the defensive detail (skip link, focus-visible, ARIA on the segmented control and canvases) is above average for a Django template app. But the Vision UI garnish is fighting the product brief at every layer, two verified bugs clip or blind the dashboard at common sizes, and the data semantics quietly lie. The single biggest opportunity: strip the decorative glow, let the slate canvas and indigo-cobalt accent carry the design, and make the data tell the truth — then the same competent layout becomes calm operational clarity instead of a screenshot-first template.

## What's Working

1. **Single-viewport discipline is real.** Verified at 1440×900 and 1366×768: no page scroll, chart canvas fixed-height with `resize()` on tab switch. The layout genuinely fits one screen.
2. **The data reconciles.** 14 = 3+2+2+1+6+0 across modules; the 6 pending matches between the KPI and Feedback Turnaround; empty states, 0-width bars, and em-dash score fallback are handled.
3. **Defensive detail.** Skip link, `:focus-visible` outlines, `aria-selected`/`role=tablist`, `role=img` + `aria-label` on canvases, ellipsis on long titles, mono numerals for counts, reduced-motion respected.

## Priority Issues

**1. [P0] Content silently unreachable at 1024×768.** At exactly 1024px the `max-width:1024px` stacking query AND the `min-width:1024px` `overflow-y:hidden !important` clip both fire (`app.css:772-777`, `app.css:2881-2887`). Measured: `mainScrollH=1271` vs `mainClientH=708`, no page scroll, wheel/PageDown scroll to 0. Stage Distribution and Feedback Turnaround are half-cut; Live Activity and Top Positions are fully off-screen with no way to reach them. *Why it matters*: a common office resolution hides half the dashboard. *Fix*: scope the single-screen clip to a min-height, let the dashboard scroll below 1024px, and make the stacking breakpoint unambiguous. *Command*: `/impeccable layout`

**2. [P0] The Vision UI aesthetic contradicts the product brief.** Glow orbs, gradient navy canvas, gradient icon chips with glow shadows, gradient bars (`!important`), gradient primary buttons and active seg pill, 20px radii, and the 3px gradient side-stripe are all banned "decorative glow / template garnish." *Why it matters*: HR sees a demo of someone else's template, not a calm operational tool; the loudest objects are red in a product DESIGN.md says should be calm. *Fix*: strip orbs, flatten the canvas to a slate token, remove icon-box gradients/glows, restore 8px radii, delete the side-stripe; recolor the pending state amber, keep red for rejected. *Command*: `/impeccable quieter`

**3. [P1] Chart.js is not theme-aware.** Tick/grid colors are computed once from `data-theme` at load (`hr_dashboard.html:236-238`); `toggleTheme()` (`base.html:21-26`) never touches the charts. Load dark → toggle light → `window.trendChartObj.options.scales.x.ticks.color` stays `rgba(255,255,255,0.75)` on a white glass panel: **white-on-white, invisible axis labels** (verified on both trend and score charts). Tooltips are near-black in both themes. *Why it matters*: theme switching is the product's own feature; it currently breaks the chart readout. *Fix*: re-render/update charts on theme change or read colors from CSS variables at draw time. *Command*: `/impeccable harden`

**4. [P1] Misleading data semantics.** Three distinct lies: (a) "Pipeline Trend" is stage counts, not a time trend; (b) "Feedback Turnaround" shows 1 Completed / 6 Pending counts with bars — no turnaround time anywhere; (c) `kpi-trend` chevrons ("Active pipeline", "Active roles") imply deltas with no baseline. *Why it matters*: an HR manager will make decisions on data that reads differently than it is. *Fix*: retitle per view ("Candidates by stage"), rename the card "Feedback Completion" or add a true median-hours metric, drop chevrons on non-delta labels. *Command*: `/impeccable clarify`

**5. [P2] Typography collapsed below usable size.** KPI labels 9px, trend 10px, activity time 9px, page-sub 11px, chart ticks 10px, all via inline `style=` overrides that fight the design system (one badge inline 9px yet computes 12px — a dead override). *Why it matters*: 9px uppercase tracked text at `#A0AEC0` is the wrong tool for operational reading; low-vision users are excluded. *Fix*: remove inline overrides, let the tokenized `--text-*` scale render, enforce a ≥11px floor for muted helper text. *Command*: `/impeccable typeset`

## Persona Red Flags

**Alex (Power User)**: No keyboard shortcuts anywhere. The primary action — clearing the 6 pending feedback items — is announced by a red "Action needed" card that is *not a link*; Alex must find the tiny "Details →" or navigate the sidebar. Live Activity truncates at 3 with no "view all," so older items are unreachable. The chart's "Pipeline Trend" mislabel will read as a flat line when it's stage buckets — misleading under load.

**Sam (Accessibility)**: The segmented control is `role=tablist`/`role=tab` with **no arrow-key navigation** (verified: ArrowLeft does nothing), no `aria-controls`, no tabpanel association, no announcement on switch. Charts are `role=img` with **no data table or text fallback** — a screen reader user gets "Pipeline Trend Chart" and zero numbers. White-on-white axis ticks after theme toggle, 9px labels, and dark-theme reds at 3.66–3.99:1 (badges `in_progress` 3.40, `rejected` 3.66, `on_hold` 3.99, `new` 3.81) all fail WCAG AA. Light theme: `shortlisted` 2.98, `new` 3.58, `hired` 3.69 fail.

**Riley (Stress Tester)**: The single-viewport contract breaks exactly at 1024px where content clips with no affordance (verified reachability failure). Duplicate "Lead Cloud & DevOps Architect (Infrastructure)" rows (jobs pk 18 and 17) look like a glitch. "Live Activity" is 6 days old at its newest — the freshness promise breaks under scrutiny.

## Minor Observations

- Two identical job rows in Top Positions; UI should disambiguate or dedupe.
- "Live Activity" — either surface a real freshness window or drop "Live".
- `seg-btn.active` uses a blue gradient pill with 30px radius against the design system's 8px control radius.
- KPI values are inline `1.8rem` vs the component's designed `2.4rem` — the hero metric was scaled down and flattened.
- "Stage Distribution" shows a 0-count "On Hold" bar — a full label row of noise for zero information.
- 18 elements in the rendered DOM carry inline `color`/`background`; font-size inline overrides on nearly every card bypass the rem scale.
- Chart tooltips are near-black navy (`rgba(6,11,40,0.95)`) in both themes.
- `.ref-kpi-card` has hover `translateY(-3px)` + gradient `::after` hairline — decorative motion language.
- Sidebar renders at 390px as a 24px sliver with clipped nav links instead of collapsing.
- Favicon missing (404 on load).

## Questions to Consider

- DESIGN.md bans exactly what this page ships — glow orbs, gradient garnish, side-stripes, 20px radii, off-palette teal. Is the demo showing HR a custom product, or a template the team hasn't finished replacing? Who is the glow for — the data or the screenshot?
- When 6 pending feedback (43%) is the loudest, reddest object on screen, is the design telling HR to panic — or should amber plus an age indicator ("oldest pending: 9 days") turn the same number into a calm, concrete action?
- With 200 applications and 20 open roles, which of the six modules gets cut — or is "everything visible always" the wrong contract for an HR desk?
- Three stacked page titles — "Altrium Tracker" breadcrumb, "Dashboard" topbar, "Pipeline Overview" H1. If you had to delete two, which one encodes the user's actual mental model of where they are?
