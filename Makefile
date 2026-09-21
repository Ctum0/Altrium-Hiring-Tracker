# Product-continuity QA entry points.
# One command runs the whole guard suite: `make qa-all`.
#
# Prerequisites: .venv with requirements installed, node_modules with
# playwright (npm install), and the Chromium build (npx playwright install
# chromium — already present at ~/.cache/ms-playwright).

PY := .venv/bin/python

.PHONY: help qa-server qa-states qa-seed qa-lint qa-unit qa-e2e qa-all qa-clean

help:
	@echo "qa-server  - start the dev server on 127.0.0.1:8100 (no reload)"
	@echo "qa-states  - (re)generate role storage states for MCP exploration"
	@echo "qa-seed    - seed/reset the E2E data set for transition specs"
	@echo "qa-lint    - ruff over first-party code"
	@echo "qa-unit    - full Django test suite + gap regression tests"
	@echo "qa-e2e     - Playwright feature-transition specs (seeds first)"
	@echo "qa-all     - lint + unit + e2e (the whole guard suite)"
	@echo "qa-clean   - remove E2E seed data"

qa-server:
	@pgrep -f "manage.py runserver 127.0.0.1:8100" > /dev/null || \
	 (nohup $(PY) manage.py runserver 127.0.0.1:8100 --noreload > /tmp/django-dev.log 2>&1 & sleep 3)
	@curl -s -o /dev/null -w "dev server: %{http_code}\n" http://127.0.0.1:8100/login/ --max-time 5

qa-states:
	$(PY) qa/scripts/seed_auth_states.py

qa-seed:
	$(PY) qa/scripts/e2e_seed.py

# Lint gate: views/urls/settings/tags + QA scripts (the surfaces the
# continuity workflow touches). Pre-existing lint debt in seed scripts and
# old tests is tracked separately and must not block the gate.
qa-lint:
	$(PY) -m ruff check accounts/views.py accounts/urls.py accounts/templatetags/ jobs/views.py jobs/urls.py candidates/views.py candidates/urls.py feedback/views.py notifications/views.py pipeline/views.py ai/services.py ai/matching.py ai/confidence.py ai/cv_parser.py altrium_tracker/ tests/test_gap_regressions.py qa/scripts/

qa-unit:
	$(PY) manage.py test accounts jobs candidates feedback pipeline notifications ai tests.test_gap_regressions --parallel 1

qa-e2e: qa-server qa-seed
	npx playwright test --config qa/playwright.config.js tests/feature-transitions

qa-all: qa-lint qa-unit qa-e2e

qa-clean:
	$(PY) qa/scripts/e2e_seed.py --clean
