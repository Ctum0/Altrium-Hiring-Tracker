# Altrium Tracker - Design Direction

## Mood
"Calm operational clarity" - an HR operations desk in morning light. Hiring pipelines move without drama. Trust-first, dense but never noisy.

## Strategy
Modern SaaS dashboard language, calibrated to the 2024 soft-SaaS register (Linear-analytics / Attio / EduMate-class references): one confident brand accent carries ALL interactive state (buttons, active nav, active filters, pagination, links); semantic status colors are reserved exclusively for state indicators (pipeline pills, chart series) and never decorate chrome. Solid elevated cards on a soft cool-grey canvas, airy tinted directional shadows (never black, never heavy), pill-shaped buttons, and a sidebar whose active destination is a solid brand pill with white icon+text (no per-destination icon colors — wayfinding comes from position and the active pill, not a rainbow). Light is the flagship theme; dark remains available as a toggle and keeps its own frosted-glass identity as the night-mode variant.

## Palette (OKLCH)
- Brand: oklch(0.72 0.15 195) bright cyan (#22D3EE) for dark surfaces; oklch(0.55 0.15 230) deep azure blue (#036fa8) for light surfaces. Hover states step darker within the same hue.
- Light canvas: soft lavender-grey gradient (oklch(0.94 0.020 275) -> oklch(0.975 0.008 255)), solid white cards (oklch(1 0 0)) floating on it via soft tinted shadow, not translucency.
- Dark canvas: near-black gradient (#0a0a0c -> #020203, body #050507), frosted glass cards (backdrop-filter blur) - this is the one surface where the glass language still lives.
- border: oklch(0.90 0.012 260) light / rgba(255,255,255,0.14) dark
- ink: #081A2C light / white dark; secondary #132E48 light / oklch(0.35 0.02 270) dark; muted #334D66 light / oklch(0.50 0.03 270) dark
- Semantic (with light-mode text-contrast values noted): new=brand cyan/blue, shortlisted=amber darkened to #a35605 on light, in_progress=indigo #4f52d6 on light, hired=emerald #04815a on light, rejected=red #DC2626 both themes, on_hold=slate #3E5C7B on light, pending=amber #a35605 on light. Dark theme uses brighter variants of the same hues (see app.css token block). These same six hues double as the categorical chart ramp (stage bar chart, funnel-chart point colors, any future stage donut) so a chart color and a status pill always mean the same thing. The stage-distribution chart on the HR dashboard renders as a bar chart (not a smoothed line) since the underlying data is discrete pipeline-stage counts, not a continuous trend - each bar carries its own semantic status color from this ramp.
- Icon tiles (KPI cards, avatars): flat solid fills only, never gradients, never a glow/halo box-shadow. Sidebar navigation uses NO per-destination colors: all nav icons are neutral muted-grey; the active destination is a solid brand-accent pill with white icon+text (the EduMate pattern). Wayfinding comes from the active pill and position, not from a six-color rainbow. KPI card icons use a single brand-accent flat fill differentiated by glyph, not by hue. Person avatars (candidates, interviewers) use one flat brand-tinted tone regardless of identity - differentiation between people comes from their initials, not a per-person color assignment, so a table of many people never reads as unrelated confetti. Avatar clusters (stacked chips with an overflow count) are the table-scale version of the same discipline.

## Type
Plus Jakarta Sans (geometric sans) with a system-ui fallback, fixed rem scale 1.125 ratio. No display/body pairing: one family carries everything. Mono reserved for numeric data (scores). Minimum helper-text size is 11px in the dashboard surfaces.
Exception: the signed-out login page only, where a single italicized word in the hero headline runs in Instrument Serif (`--font-display`, `.font-display`) as a one-off editorial accent. This is the one deliberate display/body pairing in the product - never extend it into the authenticated app.

## Shape
One radius system: 20-24px for cards, pill (999px) for buttons/badges/segmented controls, 12-14px for inputs and selects only. Documented and consistent across both themes.

## Elevation
Light theme: solid opaque surfaces, airy two-layer shadow tinted toward the ink hue (`0 1px 2px rgba(16,24,40,0.04), 0 8px 24px rgba(16,24,40,0.06)` scale - shadow reads as soft height above the canvas, never a black outline), plus a 1px white inner highlight on cards for the soft-clay feel. No `backdrop-filter` on light-theme cards - they are legible on their own, matching a standard modern SaaS dashboard (Notion/Attio/Linear-analytics register), not a frosted-glass look.
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
