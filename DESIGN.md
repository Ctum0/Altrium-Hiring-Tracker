# Altrium Tracker - Design Direction

## Mood
"Calm operational clarity" - an HR operations desk in morning light. Hiring pipelines move without drama. Trust-first, dense but never noisy.

## Strategy
Restrained. Pure white content surface, cool slate neutrals, one cobalt brand accent for primary actions and selection, amber for attention/escalation. Status colors are semantic and limited to state indicators (pipeline status pills), never decoration.

## Palette (OKLCH)
- Brand: oklch(0.55 0.15 230) cobalt, hover oklch(0.48 0.15 230)
- Accent: oklch(0.58 0.16 60) amber for warnings/escalations
- bg: oklch(1 0 0) pure white
- surface: oklch(0.97 0.005 230) cool panel
- border: oklch(0.90 0.01 230)
- ink: oklch(0.25 0.02 230), muted oklch(0.55 0.03 230)
- Semantic: new=blue, shortlisted=amber, in_progress=teal, hired=emerald, rejected=red, on_hold=slate

## Type
System-ui stack (Inter-first system stack), fixed rem scale 1.125 ratio. No display/body pairing: one family carries everything. Mono reserved for numeric data (scores).

## Shape
One radius system: 8px for controls and cards, pill (999px) for badges and buttons. Documented and consistent.

## Motion
150-200ms state transitions only (hover, focus, drag). No page-load choreography. prefers-reduced-motion respected globally.

## Components
Top bar + side nav (product standard). Buttons: primary, secondary, ghost, danger. Forms: label above input, error below. Tables: single bottom border per row. Kanban: columns per round, cards with candidate, job, score, assignee. Empty states that teach. Skeleton on load.

## Bans (from skills)
No em-dashes in UI copy. No gradient text. No glassmorphism. No side-stripe borders. No decorative motion. No modal-first thinking.
