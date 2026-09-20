---
name: ui-consistency-inventory
description: Build and maintain the UI pattern inventory — detect when the same semantic component appears in multiple places with different behavior, and route fixes to the shared implementation. Use when inconsistencies accumulate across pages, before UI refactors, or when a patch would be the Nth copy-paste of the same pattern.
---

# UI Consistency Inventory

The app's conventions live in `DESIGN.md` — read it first. It defines the component language: buttons (primary/secondary/ghost/danger), forms (label above input, error below), tables (single bottom border per row), radius system (20-24px cards, 12-14px controls, pill badges), icon tiles, breadcrumb convention, empty states that teach, skeleton on load, semantic status colors, motion (150-200ms, reduced-motion respected), and the light/dark surface split.

## Inventory

Maintain a lightweight inventory of the recurring patterns, per type:

- buttons, forms, inputs, dropdowns
- modals, tabs, cards, tables
- alerts, notifications, toasts
- empty states, loading states, error states
- navigation patterns (sidebar, breadcrumbs, pagination)

For each: where it appears (templates/files), which shared implementation backs it (Django template include, base block, CSS class, shared view mixin), and whether all occurrences actually use the shared implementation.

This app is Django templates: shared behavior lives in `templates/base.html` blocks, `templates/includes/`, and template tags. Grep templates for repeated inline patterns — a component re-implemented inline in several templates is a consistency liability even when it currently looks identical.

## Consistency audit method

1. **Enumerate occurrences.** For each pattern type, list every place it appears (grep templates + static CSS/JS).
2. **Compare behavior, not just looks.** Same semantic component must behave identically: same confirmation pattern for destructive actions, same feedback mechanism for saves, same empty-state structure with a CTA, same error presentation, same loading treatment.
3. **Compare against DESIGN.md.** Deviations from the documented conventions are findings even when individually defensible.
4. **Compare terminology.** Same concept = same word everywhere ("Candidate" everywhere, not candidate/applicant/person interchangeably). Same action = same verb ("Move", not sometimes "Change stage").
5. **Check both themes.** Light and dark have distinct surface languages by design; behavior and semantics must still match.

## The shared-first rule

If the same semantic component appears in multiple places with different behavior:

1. Investigate the shared implementation BEFORE patching individual pages.
2. Prefer fixing the shared component when appropriate — one fix, all occurrences consistent.
3. Only patch individually when the occurrences are genuinely semantically different (then document why they differ, so the next auditor doesn't re-flag it).

## Output

- New/updated inventory → keep it in `PRODUCT_FEATURE_GRAPH.md` (UI patterns section) or a dedicated section of the gap ledger.
- Inconsistencies → `PRODUCT_GAP_LEDGER.md` (CATEGORY: Consistency), each naming the shared implementation to touch.
- When a fix is warranted, the ledger entry's PROPOSED FIX names the shared file, not the pages.

## Rules

- Never patch page-level symptoms of a shared-component divergence without at least recording the shared root.
- The inventory is evidence-based: every entry cites template paths. No remembered inventories.
