# QA Tooling Inventory

Audit of the existing environment before installing anything. Purpose: establish what already exists, avoid duplicates, and record retention decisions for the product-continuity QA system.

Audit date: 2026-09-21 · Project: Altrium Hiring Tracker (Django 5.2 + Django templates, Python 3.13, Node 24) · Repo: `Ctum0/Altrium-Hiring-Tracker` (public, no CI yet)

## Tool inventory

| Tool | Type | Version | Purpose | Current configuration | Existing capabilities | Overlaps requested tooling? | Retain? | Needs modification? |
|---|---|---|---|---|---|---|---|---|
| Playwright MCP (`@playwright/mcp`) | MCP server | 0.0.82 (pinned, vendored at `node_modules/.qa-mcp/`) | Browser automation layer for agent-driven QA | NEW: `.omp/mcp.json` → `--caps=network,storage,testing,vision,devtools --isolated --config qa/playwright-mcp.config.json`. Prior config existed only in `.zcode/config.json` (another agent's harness, `@latest` unpinned) | core, network, storage, testing, vision, devtools (69 tools verified via handshake) | IS the requested tooling | Yes (primary) | Config formalized: pinned version, capability set, timeouts, viewport, isolated contexts |
| Playwright (npm) | Test runner + library | 1.63.0 (project `package.json`) | E2E/transition tests, screenshots, tracing | `node_modules/playwright`; browsers at `~/.cache/ms-playwright/chromium-1243` (chromium 1243 = the 1.63 line) | `playwright/test` runner verified working; firefox/webkit browser builds already downloaded | No — this is the regression-test engine the MCP complements | Yes | New: `qa/playwright.config.js` (test-runner config) added; no project-wide `playwright.config` existed |
| @axe-core/playwright | npm dependency | 4.13.0 | Automated accessibility scans | Declared in `package.json`; used by `comprehensive-a11y-audit.js` | axe scan + keyboard-nav script exists | Requested a11y scanner — already present | Yes | No new install; `accessibility-reviewer` skill routes through it |
| axe-core | npm dependency | 4.12.1 | axe rule engine (peer of the above) | `package.json` | — | Same | Yes | — |
| Lighthouse | npm dependency | 13.4.1 (`chrome-launcher` 1.2.1) | Performance/a11y/SEO audits | `node_modules`; used by `accessibility-audit.js` (targets `127.0.0.1:8001`) | CLI + programmatic audits | Requested Lighthouse CI (Part 24) | Yes | No Lighthouse CI configured; CI does not exist yet, so CI integration is deferred (see notes) |
| chrome-launcher | npm dependency | 1.2.1 | Finds/launches Chrome for Lighthouse | `package.json` | — | No | Yes | — |
| Prettier | Formatter | 3.9.6 | Code formatting | `.prettierrc.json` | — | No | Yes | — |
| Playwright MCP podman container | Containerized MCP | image `mcr.microsoft.com/playwright/mcp:latest` (2 months old) | Shared browser for other agents (per `~/.agents/rules/browser-workflow.md`) | Exited container `playwright-mcp`, port 8931; managed by `~/.agents/bin/mcp` (helper script currently missing) | Same capability family as the new stdio server | DUPLICATE of the new stdio Playwright MCP | No (do not start) | Left stopped. The new project-scoped stdio server replaces it for this workflow. Documented as potential conflict |
| Figma MCP | MCP server (http) | — | Design reference | `.zcode/config.json` (other agent's harness, token inline) | Design-file access | No overlap with QA tooling | Out of scope | Not migrated; token lives in another tool's config |
| GitHub MCP (official, hosted) | MCP server (http) | `api.githubcopilot.com/mcp/` | Repo/issue/PR/Actions access | NEW: `.omp/mcp.json`, auth via `git credential fill` indirection (no token in any file). Toolsets exposed by token: repos, issues, pull_requests, code search; Actions toolset not exposed by this token (REST verified working: runs list returns 200) | 45 tools verified; file read, issues list, PR list, code search all pass | IS the requested tooling | Yes | Read-first posture; writes gated by omp approval + explicit instruction |
| gh CLI | CLI | NOT INSTALLED | GitHub access | omp's built-in `github` tool is disabled without it | — | Overlaps GitHub MCP | No | Not installed — GitHub MCP covers the need; installing gh would duplicate it |
| django-axes | Django app | 8.x | Login rate-limiting/lockout | `settings.py`: 5 failures, 1h cooldown, per username+IP | Protects QA from brute-forcing accounts | No | Yes | QA accounts (`qa_*`) must avoid lockout; seed script never fails logins |
| Django test framework | Test framework | 5.2.16 | Unit/integration tests | 88 test classes across `accounts/jobs/candidates/feedback/ai/tests.py` (~226K of test code) | Server-side logic coverage; no browser-level transition tests | Complements, does not overlap | Yes | Untouched |
| Existing audit scripts | Node scripts | — | One-off audits | `accessibility-audit.js` (Lighthouse, port 8001), `comprehensive-a11y-audit.js` (axe, port 8001), `test_responsive.py`, `profile_performance.py`, `seed_load_test.py` | Historical audit artifacts; hardcoded ports/paths | Partial overlap with new skills | Yes (read-only) | Left as-is; skills prefer live MCP-driven flows over these one-offs |
| omp built-in `github` tool | Harness tool | — | gh-CLI-backed GitHub ops | `github.enabled: false` (default; gh missing) | — | Overlaps GitHub MCP | No | Stays disabled |
| omp Eval `browser` facade | Harness tool | — | Browser automation inside eval kernel | Built-in | Puppeteer-based; separate from MCP | Partial overlap with Playwright MCP | Yes | Use Playwright MCP for QA per spec; eval browser remains for general automation |
| Existing seed commands | Django mgmt commands | — | Test data | `seed_users` (hr_demo/iv_demo/mgmt_demo, password `testpass123`), `seed_testdata`, `clean_and_seed_db`, `db_status`, `checkdb` | Demo accounts + data seeding | No | Yes | New `qa/scripts/seed_auth_states.py` builds on separate `qa_*` accounts to avoid touching demo logins |
| podman / docker | Container runtime | 5.4.2 / 29.8.1 | compose stack (web + postgres) | `compose.yaml` present | App can run containerized | No | Yes | Local dev currently runs venv on port 8100 instead |
| Git | VCS | — | Source control | SSH remote `git@github.com:Ctum0/Altrium-Hiring-Tracker.git`, credential store holds a PAT (broad scopes — user's own token) | — | No | Yes | GitHub MCP reads the same credential; no duplicate auth |

## Browser builds present

- `chromium-1243` + `chromium_headless_shell-1243` (matches project Playwright 1.63.0 and the pinned MCP's vendored playwright-core) — primary, used by config.
- `chromium-1234`, `firefox-1538`, `webkit-2336`, `playwright-driver-1.57.0` — older/other builds from previous experiments. Firefox/WebKit expansion later may reuse these or upgrade; no action now.

## Decisions recorded

1. **One browser MCP only** — the stdio `@playwright/mcp@0.0.82` server in `.omp/mcp.json`. The podman container stays stopped; the `.zcode/` config belongs to another agent's harness and was not modified.
2. **Pinned MCP version** — vendored at `node_modules/.qa-mcp/` (matches the project's convention of pinned deps in `package.json`; `@latest` would pull playwright-core 1.64-alpha and demand chromium 1246, breaking the pinned browser set).
3. **GitHub MCP official + hosted** — no third-party server, no gh CLI install, no Docker image pull needed (image was pulled as a fallback during evaluation but the hosted endpoint works and is preferred; the local image `ghcr.io/github/github-mcp-server` remains cached, unused).
4. **No new npm installs** — everything the workflow needs (playwright, axe, lighthouse) was already in `package.json`.
5. **No duplicate auth** — GitHub MCP resolves the token at connect time from `git credential fill`; no token stored in any config file.

## Potential conflicts

- If another agent starts the podman `playwright-mcp` container on port 8931, it does not conflict with the stdio server (different transport, different process), but both may fight over the display in headed mode. Keep the container stopped during QA runs.
- The running dev server occupies port 8100 (started outside this session). `qa/playwright.config.js` and `qa/playwright-mcp.config.json` default to 8100; override with `QA_BASE_URL` when the app runs elsewhere.
- `.zcode/config.json` contains a Figma token in plaintext (pre-existing, other tool's config) — flagged, not touched.

## Missing dependencies

- None blocking. Lighthouse CI integration is deferred until CI exists (no `.github/` directory in the repo); Part 24's conditional is unmet.
