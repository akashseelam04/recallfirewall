"""MOCK unit tests only. These do not satisfy any sponsor acceptance gate."""
import hashlib
import json
import time
import unittest
from dataclasses import replace
from decimal import Decimal
from unittest.mock import AsyncMock

from fastapi.testclient import TestClient

from gateway.app import create_app
from gateway.hotdata import SponsorFailure, TaskBinding, consumption_sql, decode_result


def binding(task='task-a', token='unit-test-a'):
    return TaskBinding(task, 'incident-test', 'PLANT-A', 1, 1, 'database-a',
                       'catalog_a', 'workspace-test', '0' * 64,
                       hashlib.sha256(token.encode()).hexdigest(), time.time() + 600)


def vendor_payload(qty='0.100'):
    return json.dumps({'columns': ['work_order_id', 'plant_id', 'output_lot', 'input_lot',
                                  'ingredient_id', 'qty_kg', 'completed_at'],
                       'rows': [['WO-1', 'PLANT-A', 'OUT-1', 'IN-1', 'ING-041', qty, '2026-01-01']],
                       'truncated': False, 'row_count': 1, 'total_row_count': 1,
                       'query_run_id': 'mock-native-id'})


class BoundaryTests(unittest.TestCase):
    def setUp(self):
        self.a = binding()
        self.b = replace(binding('task-b', 'unit-test-b'), database_id='database-b', facility_id='PLANT-B')
        self.adapter = AsyncMock()
        self.adapter.consumption.side_effect = lambda b, i: decode_result(vendor_payload(), b)
        self.client = TestClient(create_app([self.a, self.b], self.adapter))
        self.headers = {'Authorization': 'Bearer unit-test-a'}
        self.path = '/v1/tasks/task-a/consumption'

    def post(self, **kwargs):
        return self.client.post(self.path, headers=self.headers, **kwargs)

    def test_fixed_binding_and_scoped_receipts(self):
        result = self.post(json={'ingredient_id': 'ING-041'})
        self.assertEqual(result.status_code, 200)
        self.adapter.consumption.assert_awaited_once_with(self.a, 'ING-041')
        rid = result.json()['receipt_id']
        self.assertEqual(self.client.get(f'/v1/tasks/task-a/receipts/{rid}', headers=self.headers).status_code, 200)
        self.assertEqual(self.client.get(f'/v1/tasks/task-b/receipts/{rid}', headers={'Authorization': 'Bearer unit-test-b'}).status_code, 404)
        self.assertFalse(result.json()['coverage']['complete'])

    def test_override_surfaces_never_call_sponsor(self):
        fields = ['database', 'database_id', 'databaseId', 'task_id', 'workspace_id',
                  'headers', 'sql', 'query_run_id', 'result_id', 'snapshot', 'facility_id']
        for field in fields:
            with self.subTest(field=field):
                self.assertEqual(self.post(json={'ingredient_id': 'ING-041', field: 'database-b'}).status_code, 422)
                self.assertEqual(self.client.post(self.path + f'?{field}=database-b', headers=self.headers,
                                                 json={'ingredient_id': 'ING-041'}).status_code, 400)
        for name in ['X-Database-Id', 'Hotdata-Database-Id', 'X-Hotdata-Database-Id',
                     'Database', 'Database-Id', 'X-Workspace-Id', 'X-Task-Id']:
            with self.subTest(header=name):
                self.assertEqual(self.client.post(self.path, headers={**self.headers, name: 'database-b'},
                                                 json={'ingredient_id': 'ING-041'}).status_code, 400)
        self.assertEqual(self.client.post('/v1/tasks/task-b/consumption', headers=self.headers,
                                         json={'ingredient_id': 'ING-041'}).status_code, 401)
        self.assertEqual(self.post(json={'ingredient_id': "ING-041'; ATTACH x; --"}).status_code, 422)
        self.assertEqual(self.post(content='{"ingredient_id":"ING-041","ingredient_id":"ING-077"}',
                                   ).status_code, 415)
        self.assertEqual(self.client.post(self.path, headers={**self.headers, 'Content-Type': 'application/json'},
                                         content='{"ingredient_id":"ING-041","ingredient_id":"ING-077"}').status_code, 422)
        self.adapter.consumption.assert_not_awaited()

    def test_auth_and_unexposed_proxy(self):
        for headers in [{}, {'Authorization': 'Bearer wrong'},
                        [('Authorization', 'Bearer unit-test-a'), ('Authorization', 'Bearer unit-test-b')]]:
            self.assertEqual(self.client.post(self.path, headers=headers, json={'ingredient_id': 'ING-041'}).status_code, 401)
        for path in ['/query', '/mcp', '/databases/database-b', '/v1/tasks/task-a/query/mock-native-id']:
            self.assertEqual(self.client.get(path, headers=self.headers).status_code, 404)
        expired = TestClient(create_app([replace(self.a, expires_at=0)], self.adapter))
        self.assertEqual(expired.post(self.path, headers=self.headers, json={'ingredient_id': 'ING-041'}).status_code, 401)
        self.adapter.consumption.assert_not_awaited()

    def test_failure_visible_without_secret_echo(self):
        self.adapter.consumption.side_effect = SponsorFailure('MOCK SECRET')
        result = self.post(json={'ingredient_id': 'ING-041'})
        self.assertEqual(result.status_code, 502)
        self.assertNotIn('MOCK SECRET', result.text)


class ContractTests(unittest.TestCase):
    def test_decimal_string_and_non_dyadic_arithmetic(self):
        rows = [decode_result(vendor_payload(q), binding())['rows'][0] for q in ('0.100', '0.200')]
        self.assertEqual(sum(Decimal(row['qty_kg']) for row in rows), Decimal('0.300'))
        self.assertNotEqual(sum(float(row['qty_kg']) for row in rows), float('0.300'))
        for qty in (0.1, 'NaN', 'Infinity', None):
            with self.assertRaises(SponsorFailure):
                decode_result(vendor_payload(qty), binding())

    def test_unknown_total_and_truncation_fail_closed(self):
        data = json.loads(vendor_payload())
        data.update(total_row_count=None, truncated=True)
        result = decode_result(json.dumps(data), binding())
        self.assertFalse(result['coverage']['delivery_complete'])
        self.assertFalse(result['coverage']['complete'])
        self.assertIsNone(result['coverage']['snapshot_or_revision'])

    def test_wrong_facility_and_shape_rejected(self):
        for change in [{'columns': []}, {'row_count': 2}, {'query_run_id': None}]:
            data = json.loads(vendor_payload()) | change
            with self.assertRaises(SponsorFailure):
                decode_result(json.dumps(data), binding())
        with self.assertRaises(SponsorFailure):
            decode_result(vendor_payload().replace('PLANT-A', 'PLANT-B'), binding())

    def test_sql_cannot_be_supplied(self):
        with self.assertRaises(ValueError):
            consumption_sql(binding(), "'; SELECT * FROM other; --")
        self.assertIn('catalog_a.public.lot_consumption', consumption_sql(binding(), 'ING-041'))


if __name__ == '__main__':
    unittest.main()
