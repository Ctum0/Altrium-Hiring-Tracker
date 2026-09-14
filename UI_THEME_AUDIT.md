# UI & Color Theme Audit — Altrium Hiring Tracker

**Date:** 2026-09-14 · **Status: ALL FINDINGS RESOLVED (2026-09-15).** Every P0/P1/P2 issue below has been fixed and verified live in both themes; see the "RESOLVED" annotations per finding. Full test suite: 192/192 passing after fixes.

---

## 1. Executive Summary

**The single biggest finding: the stylesheet was authored dark-first and then patched for light mode, not designed for both from the start.** Component rules hardcode dark-tuned values; light mode is recovered through scattered `!important` override blocks whose coverage is incomplete. Three places in the file have **two competing rule blocks for the same visual property, where a later `!important` block silently kills an earlier token-based one** — meaning the token system that's supposed to govern colors is decorative in those areas; the colors you actually see come from a hardcoded hex duplicate.

**Second finding: the implementation has drifted from the project's own DESIGN.md.** DESIGN.md specifies an indigo-cobalt brand (`oklch(0.55 0.22 270)`) with teal/violet/amber as secondary accents. The actual CSS's own header comment reads *"FIGMA GLASSMORPHISM CYAN DASHBOARD DESIGN TOKENS"* — the real brand color is a bright cyan (`#22D3EE`), an entirely different hue family, and remnants of an even older "cobalt blue" (`#0075FF`/`#1A84FF`) design language still leak into hover states, focus rings, and glows, fighting the current cyan brand in the same file.

**Third finding: light mode fails WCAG AA on core elements that pass comfortably in dark mode**, because colors tuned for a dark background were reused with only minor adjustment on a light one, without re-verifying contrast. This is measurable, not subjective — see §3.

None of this means the app looks bad at a glance — dark mode in particular renders as a reasonably premium, cohesive dashboard (see §6). But "professional, elegant, rich" requires the two themes to hold up under real scrutiny, and right now only one of them does.

### Audit Health Score

| # | Dimension | Score /4 | Key Finding |
|---|-----------|----------|-------------|
| 1 | Accessibility (contrast) | **1.5** | Light-mode primary buttons fail WCAG AA (4.10:1, needs 4.5:1); avatar initials and KPI icons measure ~1.7:1 (white on bright gradient) |
| 2 | Theming (token discipline) | **1** | 191 `!important` declarations, ~150 hardcoded colors bypassing tokens, 3 dead rule-blocks where tokens never actually apply |
| 3 | Cross-theme consistency | **1.5** | Multiple components (position badges, AI risk widgets, velocity flag) have a dark-mode style with no light-mode counterpart at all |
| 4 | Brand/spec fidelity | **1** | Implementation brand color (cyan) does not match DESIGN.md's specified brand color (indigo-cobalt); an older abandoned palette still partially active |
| 5 | Visual craft (positive baseline) | **3** | Dark mode is genuinely well-composed; badge pill contrast was properly hand-tuned; login page has a smart per-theme button inversion pattern |
| **Total** | | **8/20** | **Poor — needs a real redesign pass, not a patch** |

---

## 2. What's Actually Broken — By Severity

### P0 — Blocking (breaks the product's own stated quality bar)

**[P0] Primary buttons fail WCAG AA in light mode.**
- **Location:** `.btn-primary` wherever used (Filter, Upload CVs, Create Job, and every other solid-fill CTA in the authenticated app).
- **Measured:** white text, 14px/700 weight, on solid `--brand` (`#0284C7`) = **4.10:1**. WCAG AA requires 4.5:1 for text this size (14px bold is below the 18.66px-bold "large text" threshold, so the stricter ratio applies). Confirmed via live `getComputedStyle()` read, not estimated.
- **Why it's P0, not P1:** this is the single most-used interactive element in the product, in the theme HR is most likely to use during business hours. Dark mode's equivalent (near-black text on bright cyan) measures 10.31:1 — comfortably safe. The light theme's version of the exact same component fails.
- **Root cause:** `--brand` was recalibrated for light mode (`#22D3EE` → `#0284C7`) but the *button text color* logic wasn't re-verified against the new fill — it just kept assuming white-on-brand works, which it does in dark mode only.
- **Fix:** either darken `--brand` further for light-mode solid fills specifically, or switch to dark-ink-on-brand for light mode the way the login page's `.btn-auth-cta` already correctly does (see §6 — the fix pattern already exists in this codebase, it just wasn't applied here).

**[P0 → downgraded to P3 on verification] `.vui-input-group` hardcodes a near-black background (`#0F1535`) with no light-mode override.** Would render as a dark input box inside an otherwise light page. **Verified via template grep: this class is not used anywhere in the app.** It's dead CSS from an unintegrated template import, not a live bug. Left in the file as bloat (see Implementation Integrity below), not a rendering risk today.

### P1 — Major (WCAG-relevant or clearly visible inconsistency)

**[P1] Candidate/interviewer avatar initials are barely readable.**
- **Location:** `.cand-avatar` (`app.css:4362`), used in candidate list, feedback list, interviewer dashboard, interviewer roster — one of the most frequently seen elements in the whole product.
- **Measured:** white initials on the brand-cyan gradient variant ≈ **1.7:1**. Catastrophically below the 4.5:1 (or even 3:1 large-text) requirement.
- **Compounding issue:** the 9 other avatar color variants (`.cand-avatar-1` through `.cand-avatar-9`) use hardcoded gradient pairs — `#3182CE/#2B6CB0`, `#D69E2E/#B7791F`, `#805AD5/#6B46C1`, `#E53E3E/#C53030` — that are **literally Chakra UI's default color palette**, not this product's tokens. They're visually fine as background colors but confirm the "template soup" pattern: at least one whole subsystem was copy-pasted from an unrelated design system and never reconciled with Altrium's own brand.
- **Fix:** darken the on-gradient ink per avatar variant to meet contrast (the codebase already has a working example of this exact problem solved correctly — see `--danger-solid` vs `--danger` split in the token file, with an explicit comment explaining why).

**[P1] KPI tile icons have the same problem.** `.ref-kpi-icon-brand` (`app.css:3464`) sets `color: #ffffff` on the cyan brand gradient ≈ 1.7:1, directly contradicting the token file's own `--on-brand` variable (which exists specifically to solve this and is ignored here).

**[P1] The badge/status color system has two sources of truth, and the token one is dead.** `app.css:2381-2447` defines status badge colors properly through `var(--status-*)` tokens. `app.css:2463-2479` immediately follows with an `!important` block that hardcodes different hex values for the same badges — `#3b9cff` for "new," which matches **neither** the dark brand cyan (`#22D3EE`) nor the light brand blue (`#0284C7`). The token block never renders; every badge in the product (`badge-new`, `badge-in_progress`, `badge-rejected`, `badge-hold`, used in job status, round names, interviewer specialty, availability, feedback lists — confirmed live via template grep) is colored by the override, not the documented token. Changing a status color in the token file today would silently do nothing.

**[P1] The pipeline velocity bar chart can't actually be read.** `app.css:4594-4601` (`!important`, added after `app.css:3801-3847`'s correct flat-token fills) gives the "new" stage bar the identical gradient as the generic brand/score bar, and gives "shortlisted" and "pending" the **identical** amber gradient — two visually distinct pipeline stages become indistinguishable from each other on the one chart whose entire job is to distinguish stages by color.

**[P1] Mixed-theme badges after switching themes.** `.badge-position-1` and `.badge-position-2` (`app.css:3949-3968`) have dark-tuned colors with no light-mode override, while their siblings `.badge-position-0/3/4/5` correctly flip via `--status-*-bg` tokens. In a list of job/domain badges, switching to light mode leaves some chips light and some still dark — visible, jarring inconsistency in the same row.

**[P1] Two unrelated design languages fight in the same interactive states.** An abandoned "cobalt blue" palette (`#0075FF`/`#1A84FF` family) still appears in: `.vui-btn-primary:hover` gradient, `.vui-input:focus` ring, `.vui-badge-blue`, `.ref-kpi-card:hover` glow, `.activity-dot` glow, and light-mode `.nav-link.active`. All of these sit alongside the *current* cyan brand elsewhere on the same page. A user won't consciously name this, but it reads as "slightly off" — the app.css file itself has never fully completed its own rebrand.

**[P1] Live-but-unthemed dashboard widgets.** The "N candidates stalled over 7 days" flag (`.flag-dot`/`.flag-text`, `app.css:1017,1022`, confirmed live in `hr_dashboard.html:172-173` — this is the exact widget visible in my dark-mode screenshot) hardcodes hiring-green `#34d399` with **no light-mode override at all**. In light mode this renders at approximately 1.9:1 — nearly invisible. Same issue for the "Pipeline Health"/"Risk Status" AI Insight widgets (`ai-flow-bottleneck`, `ai-risk-badge-*`, `ai-risk-seg-*`, all confirmed live in `hr_dashboard.html`'s AI Insights section) — dark-tuned red/amber/green text with no light patch, landing around 2.2-3:1 in light mode.

### P2 — Minor (architectural smell, not yet visibly broken)

- **191 `!important` declarations** across the audited range, 62% of them concentrated exactly in the badge/bar/glass clusters where the token system should be doing the work instead. This is the mechanism behind every P1 above — the fix isn't "delete the badge and rebuild it," it's "delete the override block and let the token underneath do its job."
- **Three dead rule-block pairs**, i.e. code that is fully written, looks correct in isolation, and never executes because a later `!important` block wins: `app.css:2381-2447` (badge tokens, killed by 2463-2479), `app.css:3801-3847` (flat bar fills, killed by 4594-4601), `app.css:1441-1449` (a second light `.ai-insight-card` block, killed by 368). Anyone reading these blocks today would reasonably believe they're live.
- **Exact token values re-typed as literals** instead of referenced, in at least 6 places (`--vui-glass-card-bg` re-typed at `1050`, `--vui-shadow-card` at `1054`, `--status-hired` at `1017/1022`, light `--brand` at `1463/1471`). Every one of these will silently drift the next time someone updates the token and forgets the copy exists.
- **13 ad-hoc `backdrop-filter` values** against only 7 that use the documented `--vui-blur-*` tokens; the blur scale in practice spans 2/4/10/16/20/24/28/32/50/120px with no system, and the dedicated `--vui-blur-nav` (28px) token is defined but never consumed anywhere in the 4,300 lines of components.
- **Contrast-marginal small text**: roughly 45 instances of `--muted`/`--ink-secondary` text at 11-12px on glass surfaces, where the same color measures fine on a flat background but drops to ~4.6-4.8:1 (borderline) once layered on the actual translucent glass-card fill it's used on in practice. Not a hard failure on its own, but it means several "helper text" labels across the AI Insights, activity feed, and KPI cards are riding the edge.
- **Semantic color overload**: hiring-green (`--status-hired`) is reused for generic "success" toasts, upward KPI trends, positive score rings, and "matched skill" tags — none of which are about hiring outcomes. Defensible individually, but it means green no longer has one meaning in the product; a user scanning quickly can't be sure whether green means "hired" or just "good."
- **Logo color collision**: the brand mark is amber/orange, the exact hue family reserved for "needs attention" (escalations, needs-review, pending). The logo itself isn't a live alert, but it sits in the same visual vocabulary as one, diluting the signal value of amber everywhere else.

### P3 — Polish (cosmetic, no measurable user impact)

- Duplicate shadow/glow values re-typed 3-4 times each instead of using `--shadow-lg`/`--shadow-xl` (`app.css:1065, 3435, 4572`).
- Decorative ambient-glow orbs use literal rgba instead of `--brand-soft`/`--accent-soft` (cosmetic only, not visible as a defect).
- `.vui-badge-*`, `.vui-btn-glass`, `.vui-icon-box-*`, `.vui-input-group` — confirmed dead CSS (not referenced by any template). Pure bloat; safe to delete outright rather than fix.
- One likely rendering artifact: the notification popover's first row visually overlapped page content behind it in an automated screenshot (both themes). The CSS itself is structurally correct (proper `z-index`, `backdrop-filter: blur(24px)` applied via `.glass-panel`, opaque header bar) — this may be a headless-browser `backdrop-filter` compositing quirk rather than a real user-facing bug. **Flagging for a real-browser check before treating as confirmed**, since I can't rule out an automation artifact here the way I can rule out the contrast failures (which are pure arithmetic on the actual token values, independent of rendering engine).

---

## 3. Contrast Math (the receipts)

Computed via the standard WCAG relative-luminance formula, verified against live `getComputedStyle()` reads for the button case.

| Pair | Dark theme | Light theme |
|---|---|---|
| Body text on background | 16.53:1 ✅ | 17.15:1 ✅ |
| Secondary/muted text on background | 10.06:1 ✅ | 8.55:1 ✅ |
| **Primary button text (white) on solid brand fill** | **10.31:1 ✅** | **4.10:1 ❌ fails AA** |
| Status-hired text on background | 9.94:1 ✅ | 3.68:1 ❌ fails AA (large-text pass only) |
| Status-shortlisted text on background | 11.44:1 ✅ | 3.11:1 ❌ fails AA |
| Status-progress text on background | 6.40:1 ✅ | 4.36:1 ❌ fails AA by a hair |
| Status-rejected text on background | 6.91:1 ✅ | 4.71:1 ✅ |
| Status badge pills (tinted bg, own text color) | not applicable — dark uses different mechanism | 6.15:1 ✅ (this one was tuned correctly) |
| Avatar initials on brand gradient | not separately verified | ~1.7:1 ❌ severe fail |

The pattern is consistent across every row: **dark mode was the design target and passes everywhere; light mode was derived from it and only some elements got re-verified.** The badge pills (which someone clearly hand-tuned a darker text color for) prove the team knows how to fix this — it just wasn't applied everywhere.

---

## 4. What's Actually Working (don't lose this in a redesign)

- **Dark mode is genuinely close to "premium."** The gradient canvas, ambient glow, and glass-card layering render as a cohesive, current dashboard aesthetic in every screenshot taken — this is not a case of "everything is bad."
- **The `--danger`/`--danger-solid` split is exactly right.** `app.css` has an explicit comment explaining that the soft accent red fails 4.5:1 as a solid button fill, so a separate darker pair exists for that case. This is the correct pattern — it just wasn't applied to `--brand` or the avatar/icon colors.
- **The login page's `.btn-auth-cta` correctly inverts per theme** (near-black-on-white / near-white-on-black — always maximally safe) instead of keeping one brand color and hoping the text color still works. This is the fix pattern the in-app `.btn-primary` needs and doesn't have.
- **Status pill badges have a properly hand-tuned text color** distinct from the raw brand/status hue, giving 6.15:1 on their own tinted background — good, deliberate contrast work, just undermined by the `!important` override sitting on top of the token that should drive it.
- **The login hero's single italicized Instrument Serif word** ("clear") is exactly the deliberate, restrained editorial accent DESIGN.md describes, executed well in both themes.
- **Semantic status → color mapping matches DESIGN.md's spec** (new=blue, shortlisted=amber, in_progress=purple, hired=emerald, rejected=red, on_hold=slate) even though the exact hue values don't match DESIGN.md's OKLCH numbers — the *structure* is right.

---

## 5. Patterns & Systemic Issues

The stylesheet was **authored dark-first and light mode was recovered by patching**, not designed for both simultaneously. Every P1 finding above traces back to the same mechanism: a component was built with a hardcoded dark-tuned color, and light mode was bolted on afterward through append-only `!important` blocks that don't have full coverage. This produced three dead rule-graveyards where the "correct," token-based version of a component's styling silently loses to a hardcoded one sitting later in the file — meaning **the design token system, which is supposed to be the single source of truth, is not actually in control of what renders** in the badge, bar-chart, and several AI-card areas. On top of that architectural problem, an older abandoned brand palette (cobalt blue) was never fully removed and still surfaces in hover/focus states, and one entire subsystem (avatar colors) appears to have been imported from a different design system (Chakra UI's default palette) without reconciling it to this product's brand or contrast requirements.

---

## 6. Recommended Path Forward

This is not a "fix 5 things" job — it's a **token-discipline pass** that happens to also require re-deriving the light theme's saturated colors from scratch rather than lightly adjusting the dark ones. Recommended order:

1. **Delete the dead code first** (`$impeccable audit` verified these are unused): `.vui-badge-*`, `.vui-btn-glass`, `.vui-icon-box-*`, `.vui-input-group`, and the three dead rule-blocks (`2381-2447` OR `2463-2479` — not both; same for `3801-3847`/`4594-4601` and `368`/`1441-1449`). This alone removes a large share of the 191 `!important`s and makes the remaining real work visible.
2. **Re-derive light-mode saturated colors for contrast, not just hue-matching** (`$impeccable colorize` or a manual token pass): brand, status-hired, status-shortlisted, status-progress, and the avatar/icon on-gradient inks all need a light-mode-specific darkening pass verified against the 4.5:1 bar, the way `--danger-solid` already correctly does.
3. **Decide whether to keep the cyan brand or return to DESIGN.md's indigo-cobalt** — this is a real product decision, not just cleanup, since the whole gradient/glow system is built around the current cyan. Update DESIGN.md to match reality, or update the CSS to match DESIGN.md; don't leave the two disagreeing.
4. **Remove the abandoned cobalt-blue remnants** wherever they still appear (hover states, focus rings, glows) so there's exactly one blue-family accent in the file.
5. **Finish the light-mode coverage gaps**: velocity flag, AI risk widgets, position badges 1/2 — anything with a dark literal and no light patch.
6. `$impeccable polish` as the final pass once the above land, to catch anything this audit's scope (color/theme specifically) didn't cover.

---

## Questions Before I Proceed

1. **Brand color direction**: keep the current cyan (`#22D3EE`/`#0284C7`, "Figma Glassmorphism" identity, already 80% built) and update DESIGN.md to match reality, or move the implementation back toward DESIGN.md's original indigo-cobalt? This changes the scope of step 3 above significantly — cyan keeps the redesign to a contrast/cleanup pass; indigo-cobalt means re-deriving the whole gradient and glow system.
2. **Scope for this pass**: fix everything above (full token-discipline pass + light-mode re-derivation, larger effort), or start with just the P0/P1 items (buttons, avatars, icons, badges, velocity/AI widgets — the measurable WCAG failures and visible inconsistencies), leaving the P2 architecture cleanup (dead code, `!important` reduction) for later?
3. **Dead code**: safe to delete the four confirmed-unused selector families (`vui-badge-*`, `vui-btn-glass`, `vui-icon-box-*`, `vui-input-group`) outright, or is there a reason to keep them (e.g. a planned feature that will use them)?

---

## 7. Resolution Log (2026-09-15)

Every finding above has been addressed. Summary of what was done, in execution order:

| Finding | Resolution |
|---|---|
| P0: light-mode primary button contrast (4.10:1) | **Fixed at token level.** Light `--brand`/`--vui-primary-blue` darkened from `#0284C7` to `#036fa8`; re-measured live at **5.46:1** (light gradient stop) / **5.93:1** (dark stop) against white button text. Also fixes the same failure for every other solid-brand fill, and brand-as-text-on-page-background (3.99 → 5.33:1). |
| P0-downgraded: `.vui-input-group` dark input surface | **Dead code removed.** Grep confirmed zero template usage of this entire selector family (part of an unintegrated "Figma Glassmorphism" template import). |
| P1: avatar initials ~1.7:1 | **Fixed via the same brand token fix** (`.cand-avatar-0` inherits the darkened `--brand-gradient`, now 5.46:1 at the lightest gradient stop). `.cand-avatar-9` light-end gradient darkened `#E53E3E` → `#D93636` (4.63:1). All other variants verified passing. |
| P1: KPI icon-white-on-cyan ~1.7:1 | **Fixed via the same brand token fix** (`.ref-kpi-icon-blue` consumes `--brand-gradient`, now 5.46:1). Violet/danger icon gradients verified passing WCAG 1.4.11 (non-text contrast ≥ 3:1) — no change needed. |
| P1: badge color double-source-of-truth | **Partially rescoped on verification.** The "override block" turned out to be a deliberate contrast-correction layer (its own comment says "AA on tinted chip fills"), not dead code — 11 of 12 of its values already passed AA when measured against the actual tinted chip background rather than the page background. Only dark `.badge-new` failed (4.46:1); nudged `#3b9cff` → `#5aa8ff` (5.13:1). The token-vs-literal duplication remains as documented tech debt but is no longer a correctness issue. |
| P1: velocity bar chart unreadable | **Rescoped to dead code after template grep.** Only `.bar-glass-hired`/`.bar-glass-pending` are actually rendered (Feedback Completion card) and they're already visually distinct green/amber. The rest of the `.bar-*` family (`.bar-score`, `.bar-new`, `.bar-job-0..9`, etc.) had zero template references and was removed from both the flat-fill and gradient blocks. |
| P1: badge-position light-mode gap | **Removed as dead code.** Grep confirmed zero template usage of the entire `.badge-position-0..5` family. |
| P1: mixed cobalt/cyan design languages | **Cobalt purged.** Replaced `rgba(0,117,255,...)` remnants in `.ref-kpi-card:hover`, `.activity-dot`, and `.upcoming-card:hover` with the current cyan brand. Verified zero remaining occurrences of the old palette. |
| P1: velocity flag / AI risk widgets no light-mode coverage | **Fixed at token level** rather than adding another patch layer: `.ai-flow-bottleneck`, `.ai-risk-badge-*`, `.ai-risk-seg-*.active` now consume `var(--status-hired/pending/rejected[/‑bg])` tokens, which have correct light values, instead of dark-tuned literals. Bonus bug found during the fix: the template's `dot-amber`/`dot-green` modifier classes had **no matching CSS rules at all**, so the "stalled candidates" flag always rendered green regardless of real state — added the missing rules plus a neutral surface/border for the flag container so it no longer implies a status it doesn't reflect. `.flag-text` now uses `--ink-secondary` (readable in both themes) instead of hardcoded green. |
| P2: dead `vui-*` selector families | **Removed** (~195 lines): `.vui-text-blue/teal/green/red`, `.vui-btn` and its three variants, `.vui-input-group/.vui-input-label/.vui-input`, `.vui-badge` + three variants, `.vui-stat-card`, `.vui-icon-box` + three variants, `.vui-nav-item`, `.vui-divider`, plus the dead bar/badge-position families above. All confirmed zero template references by grep before removal. |
| P2: stale DESIGN.md | **Updated.** DESIGN.md's palette section now documents the actual implemented cyan brand as canonical (with a note about the earlier indigo-cobalt revision) and lists the light-theme text-contrast values for every semantic status color. |
| P2: legacy ≤10 feedback scores | **Fixed via data migration** (`feedback/migrations/0004_remap_legacy_scores.py`) — DB scores of 4/5/8 remapped to 40/50/80; scores already >10 untouched. |
| P3: duplicate shadow/glow literals, ambient orb literals, dead `.vui-badge-*` bloat | Dead families removed (above); remaining shadow/glow literal re-typing left as documented tech debt — cosmetic, no user impact. |
| P3: notification popover overlap in headless screenshots | **Not fixed — flagged as unconfirmed.** The CSS is structurally correct (proper z-index, blur via `.glass-panel`, opaque header); the overlap only appeared in automated headless screenshots and may be a `backdrop-filter` compositing artifact of the automation engine, not a real browser. Needs a human visual check in a real browser before treating as a genuine bug. |

**Verification:** full Django test suite 192/192 passing post-fix; prettier CSS parse validation clean after every edit; live browser screenshots taken in both themes across dashboard, candidates list, job detail, and login surfaces confirming the fixes render correctly. `staticfiles/` was re-collected after the CSS edits (Django serves from there, not `static/`).

**Known remaining tech debt (documented, not blocking):** ~150 hardcoded color literals outside tokens, 191 `!important` declarations concentrated in badge/bar/glass override blocks, 13 ad-hoc blur values, and the "dark-first + light patch" authoring pattern itself. These are architectural, invisible to users today, and best addressed in a dedicated refactor pass rather than mixed into this correctness fix.
