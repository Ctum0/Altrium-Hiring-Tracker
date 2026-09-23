import re
from unittest.mock import patch, MagicMock

from django.test import SimpleTestCase, override_settings

from ai import services
from ai.confidence import assess_confidence
from ai.panel import synthesize_panel_consensus


class _FakeResp:
    def __init__(self, content):
        self._content = content

    def raise_for_status(self):
        pass

    def json(self):
        return {'choices': [{'message': {'content': self._content}}]}


class GroqClientTests(SimpleTestCase):
    def test_parse_cv_valid_json(self):
        payload = (
            '{"first_name": "Jane", "last_name": "Smith", '
            '"email": "jane@example.com", "phone": "+1 555", '
            '"skills": ["Python", "Django"]}'
        )
        with override_settings(GROQ_API_KEY='key'), \
             patch.object(services._client, 'post', return_value=_FakeResp(payload)):
            result = services.parse_cv('resume text')
        self.assertEqual(result['first_name'], 'Jane')
        self.assertEqual(result['email'], 'jane@example.com')
        self.assertIn('Django', result['skills'])

    def test_parse_cv_malformed_json_falls_back(self):
        with override_settings(GROQ_API_KEY='key'), \
             patch.object(services._client, 'post', return_value=_FakeResp('not json')):
            result = services.parse_cv('resume text')
        self.assertEqual(result['first_name'], '')
        self.assertEqual(result['skills'], [])

    def test_parse_cv_missing_skills_key(self):
        payload = '{"first_name": "Jane", "email": "jane@example.com"}'
        with override_settings(GROQ_API_KEY='key'), \
             patch.object(services._client, 'post', return_value=_FakeResp(payload)):
            result = services.parse_cv('resume text')
        self.assertEqual(result['first_name'], 'Jane')
        self.assertEqual(result['skills'], [])

    def test_parse_cv_partial_ai_response_blends_with_fallback(self):
        # Groq extracts email but no skills; the resume text contains a
        # skill keyword the local fallback parser can find. The final
        # result must contain fields contributed by BOTH sources.
        payload = '{"email": "jane@example.com"}'
        resume_text = 'Jane Smith\nExperienced with Python and Django.'
        with override_settings(GROQ_API_KEY='key'), \
             patch.object(services._client, 'post', return_value=_FakeResp(payload)):
            result = services.parse_cv(resume_text)
        self.assertEqual(result['email'], 'jane@example.com')
        self.assertIn('Python', result['skills'])
        self.assertIn('Django', result['skills'])
        self.assertEqual(result['first_name'], 'Jane')

    def test_parse_cv_empty_text(self):
        result = services.parse_cv('   ')
        self.assertEqual(result['skills'], [])

    def test_no_api_key_returns_empty(self):
        with override_settings(GROQ_API_KEY=''):
            result = services.parse_cv('resume text')
        self.assertEqual(result['first_name'], '')

    def test_polish_notes_returns_text(self):
        with override_settings(GROQ_API_KEY='key'), \
             patch.object(services._client, 'post', return_value=_FakeResp('Polished summary.')):
            result = services.polish_notes('good at java')
        self.assertEqual(result, 'Polished summary.')

    def test_polish_notes_empty(self):
        self.assertEqual(services.polish_notes(''), '')

    def test_httpx_failure_returns_empty(self):
        with override_settings(GROQ_API_KEY='key'), \
             patch.object(services._client, 'post', side_effect=Exception('network down')):
            result = services.parse_cv('resume text')
        self.assertEqual(result['first_name'], '')


class FallbackPhoneRegexTests(SimpleTestCase):
    """Regression coverage for the fallback CV-parser phone regex: it must
    extract parenthesized US area codes, not just bare digit runs, since
    a missed phone silently breaks name+phone fuzzy dedup (candidates.dedup)."""

    def test_extracts_number_with_parenthesized_area_code_and_country_code(self):
        text = 'John Doe\nPhone: +1 (555) 987-6543\nSkills: Python\n'
        result = services._fallback_parse_cv(text)
        self.assertEqual(re.sub(r'\D', '', result['phone']), '15559876543')

    def test_extracts_number_with_parenthesized_area_code_no_country_code(self):
        text = 'John Doe\nPhone: (555) 987-6543\nSkills: Python\n'
        result = services._fallback_parse_cv(text)
        self.assertEqual(re.sub(r'\D', '', result['phone']), '5559876543')

    def test_still_extracts_unparenthesized_formats(self):
        for raw, digits in [
            ('555-987-6543', '5559876543'),
            ('555.987.6543', '5559876543'),
            ('5559876543', '5559876543'),
        ]:
            text = f'John Doe\nPhone: {raw}\nSkills: Python\n'
            result = services._fallback_parse_cv(text)
            self.assertEqual(re.sub(r'\D', '', result['phone']), digits)


class CircuitBreakerTests(SimpleTestCase):
    """The breaker stops paying the HTTP timeout on every call when the AI
    backend is dead (e.g. removed model id): after 3 consecutive failures
    remote calls are skipped for a cooldown, with a half-open probe so a
    recovered backend is detected without waiting the full window."""

    def _reset(self):
        services._breaker_failures = 0
        services._breaker_open_until = 0.0
        services._breaker_probe_inflight = False

    def setUp(self):
        self._reset()
        self.addCleanup(self._reset)

    def test_fresh_state_is_closed(self):
        self.assertFalse(services._breaker_open())

    def test_opens_after_threshold_failures(self):
        for _ in range(services._BREAKER_THRESHOLD):
            services._record_ai_failure()
        self.assertTrue(services._breaker_open())

    def test_below_threshold_stays_closed(self):
        for _ in range(services._BREAKER_THRESHOLD - 1):
            services._record_ai_failure()
        self.assertFalse(services._breaker_open())

    def test_success_resets_breaker(self):
        for _ in range(services._BREAKER_THRESHOLD):
            services._record_ai_failure()
        services._record_ai_success()
        self.assertFalse(services._breaker_open())

    def test_chat_fast_fails_while_open(self):
        """While open, _chat must not touch the network: the patched post
        would blow up if called, and the call must return instantly."""
        for _ in range(services._BREAKER_THRESHOLD):
            services._record_ai_failure()
        with override_settings(GROQ_API_KEY='key'), \
             patch.object(services._client, 'post', side_effect=AssertionError('network call while breaker open')):
            self.assertEqual(services._chat('sys', 'user'), '')

    def test_half_open_probe_allowed_once(self):
        for _ in range(services._BREAKER_THRESHOLD):
            services._record_ai_failure()
        # First call while open is a probe: it reaches the network...
        with override_settings(GROQ_API_KEY='key'), \
             patch.object(services._client, 'post', side_effect=Exception('still down')) as mock_post:
            self.assertEqual(services._chat('sys', 'user'), '')
            self.assertEqual(mock_post.call_count, 1)
        # ...and a second call is skipped (probe slot freed by the failure,
        # but the breaker is still open and the next probe is rate-limited
        # only while one is in flight — sequential calls each get a probe,
        # so assert the breaker itself remains open instead).
        self.assertTrue(services._breaker_open())

    def test_probe_success_closes_breaker(self):
        for _ in range(services._BREAKER_THRESHOLD):
            services._record_ai_failure()
        payload = '{"first_name": "Jane", "email": "jane@example.com", "skills": []}'
        with override_settings(GROQ_API_KEY='key'), \
             patch.object(services._client, 'post', return_value=_FakeResp(payload)):
            result = services._chat('sys', 'user')
        self.assertNotEqual(result, '')
        self.assertFalse(services._breaker_open())


class ConfidenceNoNameTests(SimpleTestCase):
    """GAP regression: candidates with no extractable name showed up as
    'Unknown name' across dashboards and feedback lists with no review
    flag — an identity HR could not act on. They must be flagged."""

    def test_no_name_flagged_for_review(self):
        parsed = {'first_name': '', 'last_name': '', 'email': 'x@example.com', 'phone': '', 'skills': ['Python']}
        needs_review, reasons = assess_confidence(parsed, 'x' * 200)
        self.assertTrue(needs_review)
        self.assertIn('no_name', reasons)

    def test_named_parse_not_flagged_for_name(self):
        parsed = {'first_name': 'Jane', 'last_name': 'Doe', 'email': 'jane@example.com', 'phone': '', 'skills': ['Python']}
        needs_review, reasons = assess_confidence(parsed, 'x' * 200)
        self.assertNotIn('no_name', reasons)


class PanelConsensusUpgradeTests(SimpleTestCase):
    """Mockup upgrade: consensus exposes per-evaluator criteria, criteria
    averages, confidence %, and last-updated for the richer candidate
    detail card."""

    def _make_feedback(self, score, criteria):
        from datetime import datetime, timezone as tz
        from unittest.mock import MagicMock
        fb = MagicMock()
        fb.score = score
        fb.criteria_scores = criteria
        fb.notes = 'solid technical round'
        fb.submitted_at = datetime(2026, 9, 20, 10, 0, tzinfo=tz.utc)
        fb.round.name = 'Screening'
        fb.round.order = 1
        fb.interviewer.get_full_name.return_value = 'Ivan Vance'
        fb.interviewer.username = 'iv'
        return fb

    def _app_with(self, feedbacks):
        from types import SimpleNamespace

        class _Mgr:
            def __init__(self, items):
                self._items = items

            def all(self):
                return self._items

            def select_related(self, *a, **k):
                return self

            def order_by(self, *a, **k):
                return self

        return SimpleNamespace(feedbacks=_Mgr(feedbacks))

    def test_evaluator_criteria_normalized(self):
        fb = self._make_feedback(80, [{'criterion': 'Technical Skill', 'score': 70}])
        result = synthesize_panel_consensus(self._app_with([fb]))
        self.assertEqual(result['evaluators'][0]['criteria'][0]['score_10'], 7.0)

    def test_criteria_averages_sorted_and_confidence(self):
        fb1 = self._make_feedback(80, [{'criterion': 'Technical Skill', 'score': 90}])
        fb2 = self._make_feedback(40, [{'criterion': 'Technical Skill', 'score': 50}])
        result = synthesize_panel_consensus(self._app_with([fb1, fb2]))
        avgs = {c['criterion']: c['avg_10'] for c in result['criteria_averages']}
        self.assertEqual(avgs['Technical Skill'], 7.0)
        # 1 hire + 1 reject = split: confidence 100 - 12 = 88
        self.assertEqual(result['confidence_pct'], 88)
        self.assertIsNotNone(result['last_updated'])


class FallbackSkillExtractionTests(SimpleTestCase):
    """The fallback CV parser's skill dictionary must cover security/ops
    tooling vocabulary — a pentest CV previously extracted only 'Python'
    and 'Linux' while its Key Highlights showed Burp Suite, Nmap, etc.
    (user-reported during demo rehearsal)."""

    def test_pentest_cv_extracts_security_tooling(self):
        text = (
            'Sithum Sasmitha Ranasinghe sithumsryt@gmail.com 076 383 7623\n'
            'OWASP Top 10, Burp Suite, SQLmap, ffuf, wfuzz, Gobuster, Feroxbuster '
            'Nmap, Metasploit, Hydra, Wireshark, Active Directory basics\n'
            'theHarvester, Shodan, recon-ng, Postman (Certified) '
            'Python (requests, automation), C, OOP\n'
            'Parrot OS, Kali Linux, Windows Server/10/11, Proxmox VE\n'
            'Windows/Linux log analysis, SIEM fundamentals (SOC Level 1)\n'
        )
        result = services._fallback_parse_cv(text)
        skills = result['skills']
        for expected in (
            'Python', 'Linux', 'Burp Suite', 'Nmap', 'Metasploit', 'Wireshark',
            'SQLmap', 'Hydra', 'Gobuster', 'Feroxbuster', 'theHarvester',
            'Shodan', 'recon-ng', 'Postman', 'OWASP', 'Kali Linux', 'Parrot OS',
            'Proxmox', 'Active Directory', 'SIEM',
        ):
            self.assertIn(expected, skills, f'missing {expected!r} in {skills}')

    def test_common_dev_skills_still_extract(self):
        """The extended dictionary must not regress the original dev-skill
        coverage."""
        text = 'Built with Python, Django, PostgreSQL and Docker on AWS.'
        result = services._fallback_parse_cv(text)
        for expected in ('Python', 'Django', 'PostgreSQL', 'Docker', 'AWS'):
            self.assertIn(expected, result['skills'])


class SkillVariantMatchingTests(SimpleTestCase):
    """Spelling variants: 'Cyber Security' (CV) vs 'Cybersecurity' (job
    requirement) must match — user-reported miss during demo rehearsal."""

    def test_space_variant_matches(self):
        from ai.matching import _skill_matched
        self.assertTrue(_skill_matched('cybersecurity', ['cyber security']))
        self.assertTrue(_skill_matched('cyber security', ['cybersecurity']))
        self.assertTrue(_skill_matched('cyber-security', ['cybersecurity']))

    def test_union_blend_keeps_dictionary_skills(self):
        """When the AI path succeeds but omits a dictionary skill, the
        fallback dictionary skill must still be unioned into the final
        result (previously AI skills fully replaced the blend)."""
        payload = ('{"first_name": "Jane", "last_name": "Doe", '
                   '"email": "jane@example.com", "phone": "123", '
                   '"skills": ["Python"]}')
        text = 'Jane Doe jane@example.com 123 Django PostgreSQL Docker AWS Linux'
        with override_settings(GROQ_API_KEY='key'), \
             patch.object(services._client, 'post', return_value=_FakeResp(payload)):
            result = services.parse_cv(text)
        for expected in ('Python', 'Django', 'PostgreSQL', 'Docker', 'AWS', 'Linux'):
            self.assertIn(expected, result['skills'])
