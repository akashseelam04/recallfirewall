"""Live Hotdata through the actual ASGI gateway; no mocked sponsor calls.

Exercises gateway HTTP semantics in-process. This is not a worker sandbox test,
Cloud/MCP test, immutable-snapshot proof, or full AC-07 acceptance.
Run: .venv/bin/python -m probes.gateway_isolation
"""
import asyncio
import hashlib
import json
import secrets
import tempfile
import time
from decimal import Decimal
from pathlib import Path

import httpx

from gateway.app import create_app
from gateway.hotdata import TaskBinding
from gateway.store import ControlStore
from probes.hotdata_parallel import FACILITIES


async def main():
    bindings, tokens = [], {}
    for facility, target in FACILITIES.items():
        task = 'probe-' + facility.lower()
        tokens[task] = secrets.token_urlsafe(32)
        manifest = hashlib.sha256(Path(f'probes/data/{facility.lower().replace("-", "_")}_consumption.csv').read_bytes()).hexdigest()
        bindings.append(TaskBinding(task, 'gate0-isolation', facility, 1, 1,
                                    target['database'], target['catalog'],
                                    'workjtyq38oc9fwowtl6s8g4i42jne', manifest,
                                    hashlib.sha256(tokens[task].encode()).hexdigest(), time.time() + 300))
    temporary = tempfile.TemporaryDirectory()
    state_path = Path(temporary.name) / 'control.sqlite'
    store = ControlStore(state_path)
    app = create_app(bindings, store=store)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://gateway') as client:
        def headers(task):
            return {'Authorization': 'Bearer ' + tokens[task]}

        async def read(binding):
            response = await client.post(f'/v1/tasks/{binding.task_id}/consumption',
                                         headers=headers(binding.task_id), json={'ingredient_id': 'ING-041'})
            if response.status_code != 200:
                raise RuntimeError(f'{binding.facility_id}: HTTP {response.status_code}: {response.text}')
            return response.json()

        results = await asyncio.gather(*(read(b) for b in bindings))
        expected = {'PLANT-A': Decimal('506.500'), 'PLANT-B': Decimal('1030.750')}
        for result in results:
            total = sum(Decimal(row['qty_kg']) for row in result['rows'])
            assert total == expected[result['facility_id']]
            assert not result['coverage']['complete']
        overlap = min(r['client_ended_at'] for r in results) - max(r['client_started_at'] for r in results)
        assert overlap > 0, 'No client-observed overlap'

        a, b = bindings
        path = f'/v1/tasks/{a.task_id}/consumption'
        denied = 0
        for key in ['database', 'database_id', 'databaseId', 'workspace_id', 'task_id',
                    'query_run_id', 'result_id', 'headers', 'sql', 'facility_id']:
            response = await client.post(path, headers=headers(a.task_id),
                                         json={'ingredient_id': 'ING-041', key: b.database_id})
            assert response.status_code == 422, (key, response.status_code)
            denied += 1
            response = await client.post(path + f'?{key}={b.database_id}', headers=headers(a.task_id),
                                         json={'ingredient_id': 'ING-041'})
            assert response.status_code == 400
            denied += 1
        for name in ['X-Database-Id', 'Hotdata-Database-Id', 'X-Hotdata-Database-Id',
                     'Database', 'Database-Id', 'X-Workspace-Id', 'X-Task-Id']:
            response = await client.post(path, headers={**headers(a.task_id), name: b.database_id},
                                         json={'ingredient_id': 'ING-041'})
            assert response.status_code == 400
            denied += 1
        response = await client.post(f'/v1/tasks/{b.task_id}/consumption', headers=headers(a.task_id),
                                     json={'ingredient_id': 'ING-041'})
        assert response.status_code == 401
        denied += 1
        response = await client.get(f'/v1/tasks/{a.task_id}/receipts/{results[1]["receipt_id"]}', headers=headers(a.task_id))
        assert response.status_code == 404
        denied += 1
        response = await client.get(f'/v1/tasks/{b.task_id}/receipts/{results[1]["receipt_id"]}', headers=headers(a.task_id))
        assert response.status_code == 401
        denied += 1
        for rid in (results[1]['query_run_id'], results[1]['receipt_id']):
            response = await client.get(f'/v1/tasks/{a.task_id}/receipts/{rid}', headers=headers(a.task_id))
            assert response.status_code == 404
            denied += 1
        store.close()
        store = ControlStore(state_path)
        restarted = create_app(bindings, store=store)
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=restarted), base_url='http://gateway') as resumed:
            receipt_path = f'/v1/tasks/{a.task_id}/receipts/{results[0]["receipt_id"]}'
            persisted = await resumed.get(receipt_path, headers=headers(a.task_id))
            assert persisted.status_code == 200
            assert persisted.json()['rows'] == results[0]['rows']
            assert persisted.json()['query_run_id'] == results[0]['query_run_id']
            assert persisted.json()['current_status'] == 'CURRENT'
            store.invalidate_inputs(a.incident_id, a.input_epoch)
            stale = await resumed.get(receipt_path, headers=headers(a.task_id))
            assert stale.json()['current_status'] == 'STALE'
            blocked = await resumed.post(path, headers=headers(a.task_id), json={'ingredient_id': 'ING-041'})
            assert blocked.status_code == 409
            store.revoke(a.task_id)
            revoked = await resumed.get(receipt_path, headers=headers(a.task_id))
            assert revoked.status_code == 401
        report = {
            'kind': 'live_hotdata_in_process_gateway_http_probe',
            'client_overlap_ms': round(overlap * 1000), 'override_attempts_rejected': denied,
            'results': results,
            'persistence': 'real_sponsor_rows_and_native_query_id_survived_store_reopen',
            'lifecycle': {'stale_query_http': blocked.status_code, 'revoked_receipt_http': revoked.status_code},
            'limitations': ['Existing mutable probe databases; local manifest is not a vendor snapshot',
                            'Worker OS/filesystem/network isolation not tested',
                            'Cloud/MCP and pagination not tested; AC-07 remains open'],
        }
        output = Path('probes/results/gateway_isolation.json')
        output.parent.mkdir(exist_ok=True)
        output.write_text(json.dumps(report, indent=2) + '\n')
        print(json.dumps({'client_overlap_ms': report['client_overlap_ms'],
                          'override_attempts_rejected': denied,
                          'totals_kg': {r['facility_id']: str(sum(Decimal(row['qty_kg']) for row in r['rows'])) for r in results},
                          'report': str(output), 'AC-07': 'OPEN'}, indent=2))
    store.close()
    temporary.cleanup()


if __name__ == '__main__':
    asyncio.run(main())
