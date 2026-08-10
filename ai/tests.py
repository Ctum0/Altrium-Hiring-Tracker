from unittest.mock import patch

from django.test import SimpleTestCase, override_settings

from ai import services


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

    def test_generate_rejection_email(self):
        with override_settings(GROQ_API_KEY='key'), \
             patch.object(services._client, 'post', return_value=_FakeResp('Dear Jane, ...')):
            result = services.generate_rejection_email('Jane Smith', 'Backend Engineer')
        self.assertIn('Jane', result)

    def test_generate_rejection_no_name_fallback(self):
        with override_settings(GROQ_API_KEY='key'), \
             patch.object(services._client, 'post', return_value=_FakeResp('Dear Candidate, ...')):
            result = services.generate_rejection_email('', 'Backend Engineer')
        self.assertEqual(result, 'Dear Candidate, ...')

    def test_httpx_failure_returns_empty(self):
        with override_settings(GROQ_API_KEY='key'), \
             patch.object(services._client, 'post', side_effect=Exception('network down')):
            result = services.parse_cv('resume text')
        self.assertEqual(result['first_name'], '')
