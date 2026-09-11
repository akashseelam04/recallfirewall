"""Executed local control tests; sponsor calls are MOCKS, not gate evidence."""
import hashlib
import json
import subprocess
import sys
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import AsyncMock

from fastapi.testclient import TestClient

from gateway.app import create_app
from gateway.hotdata import TaskBinding
from gateway.store import ControlStore, StaleTask
from test_gateway import binding


class PersistenceTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / 'control.sqlite'
        self.store = ControlStore(self.path)
        self.addCleanup(self.store.close)
        self.a = binding()
        self.store.register(self.a)

    def test_receipt_survives_separate_reader_process(self):
        self.store.save_receipt(self.a, {'receipt_id': 'receipt-a', 'status': 'INCOMPLETE',
                                         'rows': [{'qty_kg': '0.100'}], 'query_run_id': 'MOCK-query'})
        script = '''import json, sys
from gateway.store import ControlStore
s = ControlStore(sys.argv[1])
b = s.credential_binding('task-a')
print(json.dumps(s.receipt(b, 'receipt-a')))
s.close()
'''
        result = subprocess.run([sys.executable, '-c', script, str(self.path)],
                                capture_output=True, text=True, check=True)
        receipt = json.loads(result.stdout)
        self.assertEqual(receipt['rows'], [{'qty_kg': '0.100'}])
        self.assertEqual(receipt['current_status'], 'CURRENT')

    def test_startup_cannot_rebind_or_unrevoke(self):
        self.store.revoke(self.a.task_id)
        other = ControlStore(self.path)
        self.addCleanup(other.close)
        other.register(self.a)
        self.assertIsNone(other.credential_binding(self.a.task_id))
        with self.assertRaises(ValueError):
            other.register(replace(self.a, database_id='database-b'))
        self.assertNotIn('unit-test-a', self.path.read_bytes().decode(errors='ignore'))

    def test_dirty_epoch_and_obsolete_publish(self):
        self.assertEqual(self.store.invalidate_inputs(self.a.incident_id, 1), 2)
        with self.assertRaises(StaleTask):
            self.store.require_current(self.a)
        with self.assertRaises(StaleTask):
            self.store.publish_inputs(self.a.incident_id, 1, 1)
        with self.assertRaises(StaleTask):
            self.store.register(replace(binding('task-new', 'token-new'), input_epoch=2))
        self.store.invalidate_inputs(self.a.incident_id, 2)
        with self.assertRaises(StaleTask):
            self.store.publish_inputs(self.a.incident_id, 2, 1)
        self.store.publish_inputs(self.a.incident_id, 3, 1)
        with self.assertRaises(StaleTask):
            self.store.require_current(self.a)
        fresh = replace(binding('task-new', 'token-new'), input_epoch=3, knowledge_revision=1,
                        source_manifest_sha256='1' * 64)
        self.store.register(fresh)
        self.store.require_current(fresh)

    def test_refresh_one_facility_does_not_retire_another(self):
        b = replace(binding('task-b', 'token-b'), facility_id='PLANT-B')
        self.store.register(b)
        fresh_a = replace(binding('task-a-new', 'token-a-new'), scope_revision=2,
                          source_manifest_sha256='2' * 64)
        self.store.register(fresh_a)
        with self.assertRaises(StaleTask):
            self.store.require_current(self.a)
        self.store.require_current(b)
        self.store.require_current(fresh_a)
        # An old config replay must not make the old task active again.
        self.store.register(self.a)
        self.store.require_current(fresh_a)

    def test_unrelated_incident_stays_current(self):
        other = replace(binding('task-other', 'token-other'), incident_id='incident-other')
        self.store.register(other)
        self.store.invalidate_inputs(self.a.incident_id, 1)
        self.store.require_current(other)


class InFlightTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        path = Path(self.tmp.name) / 'control.sqlite'
        self.store = ControlStore(path)
        self.writer = ControlStore(path)
        self.addCleanup(self.store.close)
        self.addCleanup(self.writer.close)
        self.a = binding()
        self.adapter = AsyncMock()
        self.client = TestClient(create_app([self.a], self.adapter, store=self.store))
        self.headers = {'Authorization': 'Bearer unit-test-a'}
        self.path = '/v1/tasks/task-a/consumption'

    def test_input_arrival_during_sponsor_call_retains_stale_receipt(self):
        async def sponsor_call(task, ingredient):
            self.writer.invalidate_inputs(task.incident_id, 1)
            return {'rows': [{'qty_kg': '0.100'}], 'query_run_id': 'MOCK-query',
                    'coverage': {'complete': False}}
        self.adapter.consumption.side_effect = sponsor_call
        response = self.client.post(self.path, headers=self.headers, json={'ingredient_id': 'ING-041'})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['status'], 'STALE')
        rid = response.json()['receipt_id']
        receipt = self.client.get(f'/v1/tasks/task-a/receipts/{rid}', headers=self.headers).json()
        self.assertEqual(receipt['admission_status'], 'STALE')
        self.assertEqual(receipt['rows'], [{'qty_kg': '0.100'}])
        retry = self.client.post(self.path, headers=self.headers, json={'ingredient_id': 'ING-041'})
        self.assertEqual(retry.status_code, 409)
        self.adapter.consumption.assert_awaited_once()

    def test_revocation_during_call_denies_response_but_retains_history(self):
        async def sponsor_call(task, ingredient):
            self.writer.revoke(task.task_id)
            return {'rows': [], 'coverage': {'complete': False}}
        self.adapter.consumption.side_effect = sponsor_call
        result = self.client.post(self.path, headers=self.headers, json={'ingredient_id': 'ING-041'})
        self.assertEqual(result.status_code, 401)
        with self.store.transaction() as db:
            row = db.execute('SELECT result_json FROM receipts').fetchone()
        self.assertEqual(json.loads(row['result_json'])['status'], 'STALE')
        restart = TestClient(create_app([self.a], self.adapter, store=self.writer))
        self.assertEqual(restart.post(self.path, headers=self.headers,
                                     json={'ingredient_id': 'ING-041'}).status_code, 401)

    def test_existing_receipt_becomes_historical_after_input_change(self):
        self.adapter.consumption.return_value = {'rows': [], 'coverage': {'complete': False}}
        result = self.client.post(self.path, headers=self.headers, json={'ingredient_id': 'ING-041'}).json()
        self.writer.invalidate_inputs(self.a.incident_id, 1)
        receipt = self.client.get(f'/v1/tasks/task-a/receipts/{result["receipt_id"]}', headers=self.headers).json()
        self.assertEqual(receipt['admission_status'], 'CURRENT')
        self.assertEqual(receipt['current_status'], 'STALE')


class BindingValidationTests(unittest.TestCase):
    def test_nonfinite_expiry_and_invalid_revisions_rejected(self):
        for value in (float('nan'), float('inf'), True, 'tomorrow'):
            with self.assertRaises(ValueError):
                replace(binding(), expires_at=value)
        for value in (-1, True, '2', 1.5):
            with self.assertRaises(ValueError):
                replace(binding(), input_epoch=value)


if __name__ == '__main__':
    unittest.main()
