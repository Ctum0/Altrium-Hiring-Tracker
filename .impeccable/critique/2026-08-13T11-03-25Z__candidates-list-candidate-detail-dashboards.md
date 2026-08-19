---
target: candidates list + candidate detail + dashboards
total_score: 20
p0_count: 1
p1_count: 2
timestamp: 2026-08-13T11-03-25Z
slug: candidates-list-candidate-detail-dashboards
---
# Altrium Tracker — Design Critique (candidates list + candidate detail + dashboards)

## Design Health Score

| # | Heuristic | Score | Key Issue |
|---|-----------|-------|-----------|
| 1 | Visibility of System Status | 2 | Inline HTMX moves give no explicit confirmation; feedback-required responses render as bare unstyled text; alerts auto-dismiss in 5s |
| 2 | Match System / Real World | 3 | Copy is mostly task-shaped; jargon limited to "Shortlist Score Override" / "Source: upload" |
| 3 | User Control and Freedom | 2 | No undo anywhere; a dropdown `change` fires instantly and is irreversible; no cancel path |
| 4 | Consistency and Standards | 2 | Four radius tokens vs "one radius system"; heavy inline `style=` overrides; three competing shadow recipes |
| 5 | Error Prevention | 1 | "Rejected"/"Hired" are one `change` event away with no confirmation, undo, or audit surface |
| 6 | Recognition Rather Than Recall | 2 | Score chips are bare numbers; "Move to…" merges rounds + terminal states ungrouped |
| 7 | Flexibility and Efficiency | 2 | No bulk actions, keyboard, or saved filters; nested scroll; per-row dropdowns only |
| 8 | Aesthetic and Minimalist Design | 2 | Glass/glow/3D decoration fights "calm operational clarity"; dead CSS leaves missing separators |
| 9 | Error Recovery | 2 | Login error is generic-but-fine; inline move errors are unstyled plain text |
| 10 | Help and Documentation | 2 | Empty states teach, but no onboarding; icon-only buttons rely on `title`; "Link to another job" unexplained |
| **Total** | | **20/40** | **Acceptable — significant improvements needed** |

## Anti-Patterns Verdict

**LLM assessment:** Not "obvious AI slop" as a whole — there's a real token system, a product-standard shell, and clear IA. But the candidate detail page reads as template slop, and the glass execution is the core problem: a wall of tiny uppercase tracked eyebrows, glow-on-everything (gradient bars + pill glow + 3D KPI inset + doubled hover shadows), and ten arbitrary rainbow position colors with no legend. Glass is applied uniformly at the same blur/border on every surface, so it reads as a coat of paint rather than a depth system — it flattens hierarchy instead of creating it. The tell isn't the glassmorphism; it's that the content *behind* the glass (labels, status semantics, error/confirm behavior) hasn't been designed with the same care.

**Deterministic scan:** 3 warnings, all `severity: warning`, no errors.
- `layout-transition` — hr_dashboard.html:342 `transition: width` (real but low-severity; fixable with `transform: scaleX` without touching the aesthetic)
- `overused-font` — base.html:10 Plus Jakarta Sans (effectively a "keep" — it's a documented part of the glass aesthetic)
- `single-font` — base.html:1 (false positive — the design already pairs Plus Jakarta Sans with `--font-mono` for scores/data)

The detector caught the layout-property animation that the manual review would have under-weighted; the manual review caught the undefined CSS classes, mobile grid clipping, and z-index escape that the detector doesn't scan for.

**Visual overlays:** Not available — the Playwright MCP transport is broken this session (the container exposes a legacy `/sse` transport while the client expects `/mcp`), so I used Playwright directly to capture screenshots and inspected them as the fallback signal.

## Overall Impression

The shell is genuinely calm and competent — status pills, empty states, and accessibility fundamentals are right. But the two places where the product does its real work — the candidate list and the candidate detail page — are where the design is weakest. The candidate detail is a fixed 660+420px grid with clipped content on mobile, tiny inline 10-11px labels, and a profile panel that can't scroll. The single biggest opportunity is that the riskiest action in the product (rejecting a candidate) is the only irreversible action with no confirmation, while a trivial action (closing a job) has a full confirm dialog.

## What's Working

1. **Status-pill semantics are sound.** Text + dedicated color tokens make the core ATS signal legible and consistently used — the hardest part to get right, done well.
2. **Empty states teach.** "Upload CVs to parse their details automatically…" and "Candidates assigned to you will appear here once HR assigns them" are specific and role-aware — rare and valuable.
3. **Accessibility fundamentals are wired correctly.** Global `:focus-visible`, skip link, `prefers-reduced-motion`, and `aria-live` on the notification count are all present and correct.

## Priority Issues

- **[P0] Destructive candidate moves have no confirmation, undo, or audit surface.** "Rejected"/"Hired" fire immediately on `select` `change` (pipeline/_app_row.html:68-84). A human's candidacy ends with one accidental mouse-wheel change — irreversible and invisible. Fix: intercept terminal-state changes and reuse the existing `confirm-modal` with an explicit "current → next" message; add undo or at minimum surface the move audit entry. → `$impeccable polish` (pipeline move interaction).

- **[P1] Mobile is broken by a fixed two-column grid inside a locked viewport.** candidate_detail.html:22 hardcodes `grid-template-columns:660px 420px` with `overflow:hidden`, and `html/body { overflow:hidden; height:100vh }` locks page scroll. On a phone this produces horizontal overflow, a clipped profile panel with no scroll, and unreachable content. Fix: make the grid `1fr` below 900px, give the profile panel its own `overflow-y:auto`, and drop the global `overflow:hidden` in favor of normal flow. → `$impeccable adapt`.

- **[P1] Semantic color misuse and the >4-option Move dropdown tax working memory.** "Feedback Pending" reuses the rejected-red badge and "Feedback Submitted" reuses hired-green; position pills use 10 arbitrary colors; the Move dropdown mixes rounds + terminal states ungrouped (typically 6-8 options). Fix: neutral feedback badge, collapse position pills, use `<optgroup>` or two controls. → `$impeccable colorize` + `$impeccable layout`.

- **[P2] Dead CSS classes and undefined tokens silently degrade rendering.** `.brand-mark`, `.badge-secondary`, `.btn-xs`, `.ml-auto`, `.text-brand` are used but never defined; `.app-card` references undefined `--fg`, `--border-subtle`, `--accent-border`, `--transition`. The login brand is a bare unstyled "A"; app-card separators don't render. Fix: define tokens, add missing utilities, lint for undefined classes. → `$impeccable harden`.

- **[P2] Dark mode loses surface definition.** `--glass-bg: rgba(15,23,42,0.65)` over `--bg: #0b0f19` with a 10%-white border — panel vs canvas is nearly identical. Fix: raise panel luminance or border contrast in dark tokens. → `$impeccable colorize`.

## Persona Red Flags

- **Alex (Power User):** No bulk move/assign, no keyboard, no saved filters; per-row dropdowns are the only control; a fixed 660+420px grid leaves a wide monitor mostly empty.
- **Jordan (First-Timer):** "Move to…", "Link to another job", "Shortlist Score Override", and "Source: upload" are unexplained; the login page gives zero indication of what the product does; no onboarding.
- **Sam (Accessibility):** Instant-activation `<select>` fires on `change` with no confirm and no focus restoration after HTMX swap; bare score chips rely on color+number with no label; global `overflow:hidden` breaks natural keyboard/document scrolling.
- **Casey (Mobile):** The fixed 660+420px grid with `overflow:hidden` causes horizontal overflow and a clipped, unscrollable profile panel; `btn-sm` targets (`padding:2px 8px`) are below touch-target size.

## Minor Observations

- The notification bell always renders a red badge, including "0" — pure noise.
- DESIGN.md bans glassmorphism and mandates "pure white surface / one 8px radius," while app.css is glass-first with four radii — the spec and implementation disagree, and the user's "keep the glass" constraint isn't reflected in DESIGN.md.
- Heavy inline `style=` attributes bypass the token system and won't respond to theme changes.
- `.notif-popover` hard-codes `z-index: 10000 !important`, bypassing the documented z-index scale.
- Several fonts are 10-11px (`0.65rem`, `0.68rem`, inline `10px`/`11px`), below the readability floor.
- The "By Position" tab has no empty/zero-height fallback matching "By Stage," so tab switches can visibly jump card height.
- The login "A" brand mark is unstyled (no `.brand-mark` rule), inconsistent with the sidebar's logo image.

## Questions to Consider

1. Why is rejecting a candidate — the one action that ends someone's candidacy — the only irreversible action with no confirmation, undo, or surfaced audit trail, when closing a job already has a confirm dialog?
2. If the tool is meant to "disappear into the work," what is the glass/glow/3D layer actually doing for an HR operator scanning a 200-candidate table — and does it survive density, or is it decoration they'll learn to ignore?
3. Which is the source of truth going forward: DESIGN.md ("no glassmorphism, 8px radius, pure white surface") or app.css (glass-first, four radii, gradient-glow bars) — and who reconciles them given the user explicitly wants to keep the glass aesthetic?
