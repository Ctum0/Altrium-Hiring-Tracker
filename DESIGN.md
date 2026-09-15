# Altrium Tracker - Design Direction

## Mood
"Calm operational clarity" - an HR operations desk in morning light. Hiring pipelines move without drama. Trust-first, dense but never noisy.

## Strategy
Modern SaaS dashboard language: solid elevated cards on a soft lavender-tinted canvas, soft tinted shadows for depth (not blur/glassmorphism), colored icon tiles per navigation destination, and a three-accent brand ramp (Vision Blue, Cyber Teal, Electric Violet) plus a categorical status ramp for data visualization. Light is the flagship theme (matches the mood's "morning light" framing); dark remains available as a toggle and keeps its own frosted-glass identity as the night-mode variant. Semantic status colors are limited to state indicators (pipeline status pills, KPI states, chart series) and never decoration. Cards carry the calm; color-coded icon tiles and chart series carry wayfinding and category meaning.

## Palette (OKLCH)
- Brand: oklch(0.72 0.15 195) bright cyan (#22D3EE) for dark surfaces; oklch(0.55 0.15 230) deep azure blue (#036fa8) for light surfaces. Hover states step darker within the same hue.
- Light canvas: soft lavender-grey gradient (oklch(0.94 0.020 275) -> oklch(0.975 0.008 255)), solid white cards (oklch(1 0 0)) floating on it via soft tinted shadow, not translucency.
- Dark canvas: near-black gradient (#0a0a0c -> #020203, body #050507), frosted glass cards (backdrop-filter blur) - this is the one surface where the glass language still lives.
- border: oklch(0.90 0.012 260) light / rgba(255,255,255,0.14) dark
- ink: #081A2C light / white dark; secondary #132E48 light / oklch(0.35 0.02 270) dark; muted #334D66 light / oklch(0.50 0.03 270) dark
- Semantic (with light-mode text-contrast values noted): new=brand cyan/blue, shortlisted=amber darkened to #a35605 on light, in_progress=indigo #4f52d6 on light, hired=emerald #04815a on light, rejected=red #DC2626 both themes, on_hold=slate #3E5C7B on light, pending=amber #a35605 on light. Dark theme uses brighter variants of the same hues (see app.css token block). These same six hues double as the categorical chart ramp (funnel-chart point colors, any future stage donut) so a chart color and a status pill always mean the same thing.
- Icon tiles (sidebar navigation): each workspace destination carries a fixed, distinct solid-gradient tile so the nav reads as a set of destinations, not a flat list - Dashboard=brand blue, Jobs=violet, Interviewers=teal, Candidates=emerald, Feedback=amber, Notifications=danger/rose. Reuses the same gradients already defined for KPI card icons (`--brand-gradient`, `--grad-violet`, `--grad-teal`, `--grad-emerald`, `--grad-amber`, `--grad-danger`) - one icon-badge visual language for the whole product, not two.

## Type
Plus Jakarta Sans (geometric sans) with a system-ui fallback, fixed rem scale 1.125 ratio. No display/body pairing: one family carries everything. Mono reserved for numeric data (scores). Minimum helper-text size is 11px in the dashboard surfaces.
Exception: the signed-out login page only, where a single italicized word in the hero headline runs in Instrument Serif (`--font-display`, `.font-display`) as a one-off editorial accent. This is the one deliberate display/body pairing in the product - never extend it into the authenticated app.

## Shape
One radius system: 20-24px for cards, 12-14px for controls/buttons, pill (999px) for badges and segmented controls. Documented and consistent across both themes.

## Elevation
Light theme: solid opaque surfaces, soft shadow tinted toward the canvas hue (`rgba(30,41,59,...)`), never pure black. No `backdrop-filter` on light-theme cards - they are legible on their own, matching a standard modern SaaS dashboard (Notion/Attio/Linear-analytics register), not a frosted-glass look.
Dark theme: frosted glass panels (`backdrop-filter` blur + soft border) remain the surface language, per the original Vision UI direction - this is the one place blur is still the default.

## Navigation
Breadcrumb trail in the topbar (`{% block breadcrumb %}`) for any page nested under a list view - `Jobs / <Job Title>`, `Candidates / <Name>`, `Feedback / <Name>`, `Interviewers / <Name>`. Top-level list/dashboard pages keep the plain product-name breadcrumb.

## Motion
150-200ms state transitions only (hover, focus, drag). No page-load choreography. prefers-reduced-motion respected globally.

## Components
Top bar (with breadcrumb) + side nav (colored icon tiles). Buttons: primary, secondary, ghost, danger. Forms: label above input, error below. Tables: single bottom border per row. Kanban: columns per round, cards with candidate, job, score, assignee. Empty states that teach. Skeleton on load.

## Design Constraints
No em-dashes in UI copy. No gradient text. No decorative motion. No modal-first thinking. Data never clipped without a scroll affordance - content must remain reachable at every viewport height.
Light theme is solid-card only - no accidental translucency/blur reintroduced there. Dark theme keeps frosted glass and ambient glow as its allowed surface language, with contrast retained through the layering.
