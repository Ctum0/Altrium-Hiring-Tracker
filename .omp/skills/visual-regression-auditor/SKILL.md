---
name: visual-regression-auditor
description: Detect meaningful visual regressions by comparing Playwright screenshots against baselines — layout, spacing, typography, alignment, component sizing, hierarchy, responsive behavior. Use when a UI change needs visual verification, when a bug report describes something "looking wrong", or when establishing/updating visual baselines. Not a pixel-diff tool; judgment about meaningful change is the point.
---

# Visual Regression Auditor

You compare what IS against what SHOULD be, using real screenshots — never the model's memory of what a page looked like.

## Baselines

- Baselines live in `qa/screenshots/baselines/` (gitignored by default; promote a baseline into the repo under `tests/feature-transitions/__screenshots__/` only when a transition test pins it).
- Capture baselines at a stable, known-good commit. Record the commit SHA in a `baselines.md` sidecar next to the images.
- Refresh baselines only after an intentional, reviewed visual change — never to make a failing comparison pass.

## Capture discipline

1. Fixed viewport per capture. The app's viewport matrix (see below) defines the set. Same viewport, same auth state, same data state on both sides of any comparison.
2. Use the Playwright MCP `browser_take_screenshot` (or a Playwright test `toHaveScreenshot()` when scripted). Name files `<surface>-<viewport>-<state>.png`.
3. Wait for settled state: no spinners, no skeleton loaders, fonts loaded. The app uses a 150-200ms transition system — wait it out or disable animations in the capture.
4. Full-page screenshots for layout comparisons; viewport screenshots for above-the-fold judgment. Record which one you took.

## Viewport matrix (this app)

- Desktop 1440x900 — primary
- Laptop 1280x800
- Tablet 768x1024
- Mobile 390x844

If the app's actual supported matrix differs, adapt to it and record the deviation in `baselines.md`.

## What to check

Compare baseline vs current for:

- layout structure and element order
- spacing rhythm and alignment (grid consistency)
- typography (family, size scale, weight usage)
- component sizing and proportions
- button hierarchy (primary/secondary/ghost/danger usage per `DESIGN.md`)
- modal placement and layering
- navigation structure
- responsive behavior at each viewport: overflow, clipping, unreachable content
- missing elements and unexpected elements

## What NOT to flag

- Anti-aliasing and sub-pixel rendering noise
- Dynamic data differences (timestamps, counts, names) — mask or normalize before comparing
- Focus/hover states captured inconsistently
- Scrollbar presence differences between capture environments
- Deliberate theme variation (the app has distinct light and dark surface languages — compare within a theme)

The bar: does this difference affect **usability** or **design consistency**? If neither, note it and move on. Do not flag every pixel difference.

## Judgment workflow

1. Capture current state at the relevant viewports.
2. Compare against baseline (side-by-side read of both images; for scripted runs use `toHaveScreenshot` with a sensible `maxDiffPixelRatio` threshold, not zero).
3. For each candidate difference: classify — usability impact, consistency impact, or noise.
4. Meaningful differences → evidence into `PRODUCT_GAP_LEDGER.md` (CATEGORY: Visual Regression) with both images referenced, or → regression test if it guards a transition.
5. Intentional differences → update baseline and record the reason.

## Rules

- Never report a visual regression from memory. Both images must exist as files.
- Never update a baseline to hide an unexplained difference — root-cause first (see `bug-investigator`).
- When the same semantic component differs across pages, suspect the shared implementation before the pages (see UI consistency in `product-continuity-auditor`).
