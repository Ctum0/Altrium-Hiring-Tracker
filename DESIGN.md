# Altrium Tracker - Design Direction

## Mood
"Calm operational clarity" - an HR operations desk in morning light. Hiring pipelines move without drama. Trust-first, dense but never noisy.

## Strategy
Vision UI: a deep-navy frosted-glass dashboard language with ambient glow, gradient surfaces, and a three-accent brand ramp (Vision Blue, Cyber Teal, Electric Violet). Glow is the house style and is intentional — it is the product's identity, not garnish. The glow never touches data legibility: numbers, labels, and status colors stay high-contrast in both themes. Semantic status colors are limited to state indicators (pipeline status pills, KPI states) and never decoration. Glass panels (`backdrop-filter` blur + soft border) carry the calm; gradient accents carry the energy.

## Palette (OKLCH)
- Brand: oklch(0.72 0.15 195) bright cyan (#22D3EE) for dark surfaces; oklch(0.55 0.15 230) deep azure blue (#036fa8) for light surfaces. Hover states step darker within the same hue. (NOTE: an earlier revision of this document specified indigo-cobalt oklch(0.55 0.22 270); the implemented palette is the source of truth and has been updated here to match reality.)
- bg: near-black gradient (#0a0a0c -> #020203, body #050507 — true black, not navy) dark canvas / oklch(0.97 0.005 270) slate-tinted light canvas (opt-in)
- surface: rgba(255,255,255,0.05-0.15) dark glass / rgba(255,255,255,0.85) light glass
- border: rgba(255,255,255,0.14) dark / rgba(226,232,240,0.5) light
- ink: oklch(0.20 0.02 270) dark / white; secondary oklch(0.35 0.02 270); muted oklch(0.50 0.03 270)
- Semantic (with light-mode text-contrast values noted): new=brand cyan/blue, shortlisted=amber darkened to #a35605 on light, in_progress=indigo #4f52d6 on light, hired=emerald #04815a on light, rejected=red #DC2626 both themes, on_hold=slate #3E5C7B on light, pending=amber #a35605 on light. Dark theme uses brighter variants of the same hues (see app.css token block).

## Type
Plus Jakarta Sans (geometric sans) with a system-ui fallback, fixed rem scale 1.125 ratio. No display/body pairing: one family carries everything. Mono reserved for numeric data (scores). Minimum helper-text size is 11px in the dashboard surfaces.
Exception: the signed-out login page only, where a single italicized word in the hero headline runs in Instrument Serif (`--font-display`, `.font-display`) as a one-off editorial accent. This is the one deliberate display/body pairing in the product — never extend it into the authenticated app.

## Shape
One radius system: 20px for glass cards, 12px for controls/buttons, pill (999px) for badges and segmented controls. Documented and consistent.

## Motion
150-200ms state transitions only (hover, focus, drag). No page-load choreography. prefers-reduced-motion respected globally.

## Components
Top bar + side nav (product standard). Buttons: primary, secondary, ghost, danger. Forms: label above input, error below. Tables: single bottom border per row. Kanban: columns per round, cards with candidate, job, score, assignee. Empty states that teach. Skeleton on load.

## Design Constraints
No em-dashes in UI copy. No gradient text. No decorative motion. No modal-first thinking. Data never clipped without a scroll affordance — content must remain reachable at every viewport height.
Frosted glass and ambient glow are the allowed surface language (not accidental glassmorphism) — they must stay structural and readable, with dark-mode surfaces that retain enough contrast to read the layering.
