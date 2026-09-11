"""Local static replay boundary; no sponsor mocks or live vendor calls."""
import unittest
from fastapi.testclient import TestClient
from gateway.replay import app


class ReplayTests(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app)

    def test_pages_and_recorded_bundle_are_available(self):
        for path in ('/', '/presentation.html', '/data.js', '/app.js', '/style.css'):
            self.assertEqual(self.client.get(path).status_code, 200)

    def test_no_actions_or_private_files_are_exposed(self):
        for path in ('/api/holds', '/api/approvals', '/api/departures', '/'):
            self.assertIn(self.client.post(path, json={}).status_code, (404, 405))
        for path in ('/.env', '/session.json', '/memory.md', '/%2e%2e/.env'):
            self.assertEqual(self.client.get(path).status_code, 404)
        self.assertNotIn('__OPERATOR_KEY__', self.client.get('/').text)
