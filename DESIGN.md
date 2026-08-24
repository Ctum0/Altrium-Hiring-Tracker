# Altrium Tracker - Design Direction

## Mood
"Calm operational clarity" - an HR operations desk in morning light. Hiring pipelines move without drama. Trust-first, dense but never noisy.

## Strategy
Vision UI: a deep-navy frosted-glass dashboard language with ambient glow, gradient surfaces, and a three-accent brand ramp (Vision Blue, Cyber Teal, Electric Violet). Glow is the house style and is intentional — it is the product's identity, not garnish. The glow never touches data legibility: numbers, labels, and status colors stay high-contrast in both themes. Semantic status colors are limited to state indicators (pipeline status pills, KPI states) and never decoration. Glass panels (`backdrop-filter` blur + soft border) carry the calm; gradient accents carry the energy.

## Palette (OKLCH)
- Brand: oklch(0.55 0.22 270) indigo-cobalt, hover oklch(0.60 0.22 270)
- Accent: oklch(0.52 0.17 60) amber for warnings/escalations
- Accent teal: oklch(0.68 0.13 195) (Cyber Teal) for secondary accent
- Accent violet: oklch(0.55 0.24 300) (Electric Violet) for tertiary accent
- bg: dark navy gradient (deep canvas default) / oklch(0.97 0.005 270) slate-tinted light canvas (opt-in)
- surface: rgba(255,255,255,0.05-0.15) dark glass / rgba(255,255,255,0.85) light glass
- border: rgba(255,255,255,0.14) dark / rgba(226,232,240,0.5) light
- ink: oklch(0.20 0.02 270) dark / white; secondary oklch(0.35 0.02 270); muted oklch(0.50 0.03 270)
- Semantic: new=blue, shortlisted=amber, in_progress=purple, hired=emerald, rejected=red, on_hold=slate, pending=amber

## Type
Plus Jakarta Sans (geometric sans) with a system-ui fallback, fixed rem scale 1.125 ratio. No display/body pairing: one family carries everything. Mono reserved for numeric data (scores). Minimum helper-text size is 11px in the dashboard surfaces.

## Shape
One radius system: 20px for glass cards, 12px for controls/buttons, pill (999px) for badges and segmented controls. Documented and consistent.

## Motion
150-200ms state transitions only (hover, focus, drag). No page-load choreography. prefers-reduced-motion respected globally.

## Components
Top bar + side nav (product standard). Buttons: primary, secondary, ghost, danger. Forms: label above input, error below. Tables: single bottom border per row. Kanban: columns per round, cards with candidate, job, score, assignee. Empty states that teach. Skeleton on load.

## Bans
No em-dashes in UI copy. No gradient text. No decorative motion. No modal-first thinking. Data never clipped without a scroll affordance — content must remain reachable at every viewport height.
Frosted glass and ambient glow are the allowed surface language (not accidental glassmorphism) — they must stay structural and readable, with dark-mode surfaces that retain enough contrast to read the layering.
