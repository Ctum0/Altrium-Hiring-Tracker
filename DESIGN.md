# Altrium Tracker - Design Direction

## Mood
"Calm operational clarity" - an HR operations desk in morning light. Hiring pipelines move without drama. Trust-first, dense but never noisy.

## Strategy
Restrained with a frosted-glass surface language. Cool slate canvas, one indigo-cobalt brand accent for primary actions and selection, amber for attention/escalation. Status colors are semantic and limited to state indicators (pipeline status pills), never decoration. Glass panels (`backdrop-filter` blur + soft border) carry the operational calm; depth is structural (surface layering), not decorative glow.

## Palette (OKLCH)
- Brand: oklch(0.55 0.22 270) indigo-cobalt, hover oklch(0.60 0.22 270)
- Accent: oklch(0.52 0.17 60) amber for warnings/escalations
- bg: oklch(0.97 0.005 270) slate-tinted canvas
- surface: rgba(255,255,255,0.55) light glass / rgba(30,41,59,0.82) dark glass
- border: rgba(226,232,240,0.5) light / rgba(255,255,255,0.14) dark
- ink: oklch(0.20 0.02 270), secondary oklch(0.35 0.02 270), muted oklch(0.50 0.03 270)
- Semantic: new=blue, shortlisted=amber, in_progress=purple, hired=emerald, rejected=red, on_hold=slate

## Type
Plus Jakarta Sans (geometric sans) with a system-ui fallback, fixed rem scale 1.125 ratio. No display/body pairing: one family carries everything. Mono reserved for numeric data (scores).

## Shape
One radius system: 8px for controls and cards, pill (999px) for badges and buttons. Documented and consistent.

## Motion
150-200ms state transitions only (hover, focus, drag). No page-load choreography. prefers-reduced-motion respected globally.

## Components
Top bar + side nav (product standard). Buttons: primary, secondary, ghost, danger. Forms: label above input, error below. Tables: single bottom border per row. Kanban: columns per round, cards with candidate, job, score, assignee. Empty states that teach. Skeleton on load.

## Bans (from skills)
No em-dashes in UI copy. No gradient text. No side-stripe borders. No decorative motion. No modal-first thinking.
Frosted glass is an allowed surface language (not "glassmorphism as default decoration") — it must stay structural and readable, with dark-mode surfaces that retain enough contrast to read the layering.
